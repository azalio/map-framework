"""Independent public CLI proofs for strict additive acceptance revisions (#555)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

RUNNER = Path(__file__).resolve().parents[1] / "src/mapify_cli/templates/map/scripts/map_step_runner.py"


def _cli(api: str, **payload: Any) -> dict[str, Any]:
    result = subprocess.run([sys.executable, str(RUNNER), api, "--json", json.dumps(payload)],
                            capture_output=True, text=True, check=False)
    assert result.stdout, result.stderr
    return json.loads(result.stdout)


@pytest.fixture()
def frozen_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-b", "main"], check=True, capture_output=True)
    for key, value in (("user.email", "test@example.com"), ("user.name", "Test")):
        subprocess.run(["git", "config", key, value], check=True, capture_output=True)
    Path(".gitignore").write_text(".map/\n__pycache__/\n.pytest_cache/\n")
    Path("test_original.py").write_text(
        "from pathlib import Path\ndef test_original():\n    Path('.map/old-ran').touch()\n"
    )
    Path("test_added.py").write_text(
        "from pathlib import Path\ndef test_added():\n    Path('.map/new-ran').touch()\n"
    )
    Path("auxiliary.txt").write_text("unchanged supporting proof input\n")
    subprocess.run(["git", "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "synthetic base"], check=True, capture_output=True)
    branch = Path(".map/main")
    branch.mkdir(parents=True)
    (branch / "spec_main.md").write_text(
        "# Spec\n<!-- mapify:requirements-index:v1 -->\n```yaml\nrequirements:\n"
        "  - id: AC-1\n    kind: acceptance_criterion\n```\n<!-- /mapify:requirements-index:v1 -->\n"
    )
    command = [sys.executable, "-m", "pytest", "test_original.py", "-q"]
    frozen = _cli("freeze_acceptance_contract", ac_id="AC-1", command=command,
                  proof_files=["test_original.py", "auxiliary.txt"], subtask_id="ST-001",
                  author="test-writer", cwd=".", timeout=30)
    assert frozen["status"] == "success", frozen
    return {"command": command, "contract": frozen["contract"]}


def _revise(workspace: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    payload = {"ac_id": "AC-1", "command": [*workspace["command"], "test_added.py"],
               "proof_files": ["test_original.py", "auxiliary.txt", "test_added.py"],
               "author": "independent-test-writer", "authoring_stage": "independent_test_first",
               "reason": "Add independent test without changing any original proof",
               "assessment": "additive", "cwd": ".", "timeout": 30}
    return _cli("revise_acceptance_contract", **{**payload, **overrides})


@pytest.mark.parametrize("placement", ["append", "before_quiet"])
def test_additive_pytest_target_retains_old_contract_and_runs_both(
    frozen_workspace: dict[str, Any], placement: str,
) -> None:
    command = [*frozen_workspace["command"], "test_added.py"]
    if placement == "before_quiet":
        command = [*frozen_workspace["command"][:-1], "test_added.py", "-q"]
    revised = _revise(frozen_workspace, command=command)
    assert revised["status"] == "success", revised
    integrity = _cli("verify_acceptance_contracts")
    assert integrity["allowed"] is True, integrity
    report = _cli("evaluate_acceptance")
    assert report["allowed"] is True, report
    assert report["revisions"][0]["old_contract"] == frozen_workspace["contract"]
    old_files = {entry["path"]: entry["sha256"] for entry in frozen_workspace["contract"]["files"]}
    new_files = {entry["path"]: entry["sha256"] for entry in revised["contract"]["files"]}
    assert all(new_files[path] == digest for path, digest in old_files.items())
    result = _cli("run_acceptance_proofs")
    assert result["allowed"] is True, result
    assert result["requirements"][0]["status"] == "proven"
    assert Path(".map/old-ran").exists() and Path(".map/new-ran").exists()


def test_pending_unknown_revision_recovers_through_mechanically_checked_assessment(
    frozen_workspace: dict[str, Any],
) -> None:
    command = [*frozen_workspace["command"][:-1], "test_added.py", "-q"]
    pending = _revise(frozen_workspace, command=command, assessment="unknown")
    assert pending["status"] == "success", pending
    assert _cli("verify_acceptance_contracts")["allowed"] is False
    assessed = _cli("assess_acceptance_revision", ac_id="AC-1", revision=2,
                    author="independent-reviewer", assessment="additive",
                    reason="All old files and argv unchanged; only a new frozen pytest target inserted")
    assert assessed["status"] == "success", assessed
    assert _cli("verify_acceptance_contracts")["allowed"] is True
    report = _cli("evaluate_acceptance")
    assert report["allowed"] is True, report
    assert report["revisions"][0]["old_contract"] == frozen_workspace["contract"]


@pytest.mark.parametrize("entrypoint", ["revision", "assessment"])
@pytest.mark.parametrize("case", [
    "removed_target", "removed_argument", "narrowed_target", "removed_proof", "mutated_proof",
    "mutated_auxiliary", "changed_cwd", "reduced_timeout", "added_filter", "added_ignore",
    "duplicate_old_target", "duplicate_new_target", "option_value_as_target", "unfrozen_target",
    "changed_interpreter", "unsupported_command",
])
def test_nonadditive_or_ambiguous_revision_stays_blocked(
    frozen_workspace: dict[str, Any], case: str, entrypoint: str,
) -> None:
    command = [*frozen_workspace["command"], "test_added.py"]
    overrides: dict[str, Any] = {}
    if case == "removed_target":
        command.remove("test_original.py")
    elif case == "removed_argument":
        command.remove("-q")
    elif case == "narrowed_target":
        command[3] = "test_original.py::test_original"
    elif case == "removed_proof":
        overrides["proof_files"] = ["test_original.py", "test_added.py"]
    elif case == "mutated_proof":
        Path("test_original.py").write_text("def test_original():\n    pass\n")
    elif case == "mutated_auxiliary":
        Path("auxiliary.txt").write_text("changed\n")
    elif case == "changed_cwd":
        Path("other").mkdir()
        overrides["cwd"] = "other"
    elif case == "reduced_timeout":
        overrides["timeout"] = 1
    elif case == "added_filter":
        command += ["-k", "test_added"]
    elif case == "added_ignore":
        command += ["--ignore=test_original.py"]
    elif case == "duplicate_old_target":
        command += ["test_original.py"]
    elif case == "duplicate_new_target":
        command += ["test_added.py"]
    elif case == "option_value_as_target":
        command = [*frozen_workspace["command"], "-k", "test_added.py"]
    elif case == "unfrozen_target":
        overrides["proof_files"] = ["test_original.py", "auxiliary.txt"]
    elif case == "changed_interpreter":
        command[0] = "python"
    elif case == "unsupported_command":
        command = ["sh", "-c", "true", *frozen_workspace["command"], "test_added.py"]
    if entrypoint == "assessment":
        overrides["assessment"] = "unknown"
    revised = _revise(frozen_workspace, command=command, **overrides)
    if revised.get("status") == "success" and entrypoint == "assessment":
        _cli("assess_acceptance_revision", ac_id="AC-1", revision=2, author="independent-reviewer",
             assessment="additive", reason="Claimed additive must be independently checked")
    if revised.get("status") == "success":
        integrity = _cli("verify_acceptance_contracts")
        assert integrity["allowed"] is False, (case, revised, integrity)
        assert _cli("evaluate_acceptance")["allowed"] is False
    else:
        assert revised.get("status") == "error", revised
