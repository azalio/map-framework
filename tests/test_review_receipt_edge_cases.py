"""Public review lifecycle regressions for immutable and malformed receipts."""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest

SCRIPTS_PATH = Path(__file__).resolve().parents[1] / "src/mapify_cli/templates/map/scripts"
sys.path.insert(0, str(SCRIPTS_PATH))

import map_step_runner  # type: ignore[import-not-found]

runner = cast(Any, map_step_runner)


@pytest.fixture()
def receipt_workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(runner, "get_branch_name", lambda: "test-branch")
    subprocess.run(["git", "init", "-b", "main"], check=True, capture_output=True)
    for key, value in (("user.email", "test@example.com"), ("user.name", "Test")):
        subprocess.run(["git", "config", key, value], check=True)
    Path(".gitignore").write_text(".map/\n")
    Path("writer.py").write_text("VALUE = 1\n")
    profile = Path(".claude/agents/review-reader.md")
    profile.parent.mkdir(parents=True)
    profile.write_text("---\nname: review-reader\ntools: Read, Glob, Grep\n---\nRead only.\n")
    subprocess.run(["git", "add", "."], check=True)
    subprocess.run(["git", "commit", "-m", "base"], check=True, capture_output=True)
    subprocess.run(["git", "checkout", "-b", "test-branch"], check=True, capture_output=True)
    Path("writer.py").write_text("VALUE = 2\n")
    return tmp_path / ".map/test-branch"


def _admit(*, adversarial=False):
    result = runner.begin_review_run(
        arguments="--adversarial" if adversarial else "", round_id="receipt", provider="claude",
        scheduled_reviewers=None if adversarial else ["monitor"],
    )
    assert result["status"] == "success", result
    assert runner.create_review_bundle()["status"] == "success"
    return result


def _receipt(admission):
    return {"covered_files": admission["required_files"], "skipped_files": [],
            "denied_access": [], "check_evidence": []}


@pytest.mark.parametrize("terminal", ["completed", "abandoned"])
def test_create_review_bundle_preserves_terminal_receipt_on_new_snapshot(receipt_workspace, terminal):
    admission = _admit()
    if terminal == "completed":
        envelope = {"verdict": "approved", "issues": [], "receipt": _receipt(admission)}
        assert runner.capture_review_output("monitor", json.dumps(envelope), "receipt")["status"] == "success"
        assert runner.write_review_verdict_ledger(current_run=True)["code_approval"]["approved"]
    else:
        assert runner.abandon_review_round("receipt", "new work")["status"] == "success"
    ledger_path = receipt_workspace / "review-verdict-ledger.json"
    before = ledger_path.read_bytes()
    row = json.loads(before)["convergence"]["rounds"][-1]
    object_path = receipt_workspace / row["bundle_receipt"]["artifact"]
    object_before = object_path.read_bytes()
    Path("writer.py").write_text("VALUE = 3\n")
    bundle = runner.create_review_bundle()
    assert bundle["status"] == "success", bundle
    assert bundle["snapshot"]["target"] != row["target"]
    assert ledger_path.read_bytes() == before
    assert object_path.read_bytes() == object_before


def test_create_review_bundle_keeps_pending_snapshot_binding(receipt_workspace):
    _admit()
    ledger_path = receipt_workspace / "review-verdict-ledger.json"
    before = ledger_path.read_bytes()
    Path("writer.py").write_text("VALUE = 3\n")
    result = runner.create_review_bundle()
    assert result["status"] == "error", result
    assert ledger_path.read_bytes() == before


@pytest.mark.parametrize("receipt", [None, []])
def test_complete_review_round_records_invalid_receipt_without_crashing(receipt_workspace, receipt):
    _admit()
    envelope = {"verdict": "approved", "issues": [], "receipt": receipt}
    assert runner.capture_review_output("monitor", json.dumps(envelope), "receipt")["status"] == "success"
    result = runner.write_review_verdict_ledger(current_run=True)
    assert result["status"] == "success", result
    ledger = json.loads((receipt_workspace / "review-verdict-ledger.json").read_text())
    assert ledger["completeness"]["status"] == "INCOMPLETE"
    assert ledger["code_approval"]["approved"] is False
    assert ledger["convergence"]["rounds"][-1]["covered_files"] == []


def test_complete_review_round_retains_adversarial_raw_coverage(receipt_workspace):
    admission = _admit(adversarial=True)
    envelope = json.dumps({"all_clear": True, "findings": [], "checks_performed": ["read changed source"],
                           "receipt": _receipt(admission)})
    aggregate = runner.aggregate_adversarial_findings(
        blind_json=envelope, edge_case_json=envelope, acceptance_json=envelope,
        role_json={"maintainer": envelope, "user_experience": envelope},
    )
    assert runner.capture_review_output("adversarial", json.dumps(aggregate), "receipt")["status"] == "success"
    result = runner.write_review_verdict_ledger(current_run=True)
    assert result["status"] == "success", result
    ledger = json.loads((receipt_workspace / "review-verdict-ledger.json").read_text())
    assert ledger["completeness"]["status"] == "COMPLETE", ledger["completeness"]
    assert ledger["convergence"]["rounds"][-1]["covered_files"] == admission["required_files"]
    assert "writer.py" in admission["required_files"]


def test_begin_review_run_missing_yaml_records_unverified_capability(receipt_workspace, monkeypatch):
    monkeypatch.setitem(sys.modules, "yaml", None)
    result = runner.begin_review_run(scheduled_reviewers=["monitor"], round_id="receipt", provider="claude")
    assert result["status"] == "success", result
    ledger = json.loads((receipt_workspace / "review-verdict-ledger.json").read_text())
    capability = ledger["convergence"]["rounds"][-1]["capability"]
    assert capability["status"] == "unverified"
    assert "PyYAML" in capability["reason"]
