"""Acceptance is derived from frozen contracts and runner-witnessed evidence."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

RUNNER = Path(__file__).resolve().parents[1] / "src/mapify_cli/templates/map/scripts/map_step_runner.py"


@pytest.fixture()
def acceptance_workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-b", "main"], check=True, capture_output=True)
    for key, value in (("user.email", "test@example.com"), ("user.name", "Test")):
        subprocess.run(["git", "config", key, value], check=True)
    Path(".gitignore").write_text(".map/\n__pycache__/\n")
    Path("product.txt").write_text("ready")
    Path("proof.py").write_text("from pathlib import Path\nassert Path('product.txt').read_text() == 'ready'\nprint('verified')\n")
    subprocess.run(["git", "add", "."], check=True)
    subprocess.run(["git", "commit", "-m", "base"], check=True, capture_output=True)
    branch = tmp_path / ".map/main"
    branch.mkdir(parents=True)
    (branch / "spec_main.md").write_text(
        "# Spec\n<!-- mapify:requirements-index:v1 -->\n```yaml\nrequirements:\n"
        "  - id: AC-1\n    kind: acceptance_criterion\n"
        "```\n<!-- /mapify:requirements-index:v1 -->\n"
    )
    return branch


def cli(api_name, **payload):
    process = subprocess.run(
        [sys.executable, str(RUNNER), api_name, "--json", json.dumps(payload)],
        capture_output=True, text=True, check=False,
    )
    assert process.stdout, process.stderr
    return json.loads(process.stdout)


def freeze(**overrides):
    payload = {"ac_id": "AC-1", "command": [sys.executable, "proof.py"],
               "proof_files": ["proof.py"], "subtask_id": "ST-001", "author": "test-writer"}
    return cli("freeze_acceptance_contract", **{**payload, **overrides})


def test_frozen_proof_runs_without_review_and_survives_restart(acceptance_workspace):
    assert freeze()["status"] == "success"
    assert cli("evaluate_acceptance")["requirements"][0]["status"] == "unproven"
    result = cli("run_acceptance_proofs")
    assert result["status"] == "success", result
    report = cli("evaluate_acceptance")
    assert report["allowed"] is True, report
    row = report["requirements"][0]
    assert row["status"] == "proven", row
    assert row["receipt"]["exit_code"] == 0
    assert "verified" in (acceptance_workspace / row["receipt"]["output_artifact"]).read_text()
    assert not (acceptance_workspace / "review-verdict-ledger.json").exists()
    assert cli("run_acceptance_proofs")["requirements"][0]["receipt"]["attempt_id"] == row["receipt"]["attempt_id"]


def test_failed_rerun_cannot_fall_back_to_success(acceptance_workspace):
    del acceptance_workspace
    Path("proof.py").write_text("from pathlib import Path\nassert not Path('.map/fail').exists()\n")
    assert freeze()["status"] == "success"
    assert cli("run_acceptance_proofs")["requirements"][0]["status"] == "proven"
    Path(".map/fail").touch()
    result = cli("run_acceptance_proofs", rerun=True)
    assert result["allowed"] is False
    assert result["requirements"][0]["status"] == "failed"
    assert cli("evaluate_acceptance")["requirements"][0]["status"] == "failed"


def test_manual_and_omitted_inventory_are_unproven(acceptance_workspace):
    spec = acceptance_workspace / "spec_main.md"
    spec.write_text(spec.read_text().replace("```\n<!-- /", "  - id: AC-001\n    kind: acceptance_criterion\n```\n<!-- /"))
    assert freeze(command=None, proof_files=[], manual_reason="requires hardware")["status"] == "success"
    report = cli("evaluate_acceptance")
    assert report["allowed"] is True
    assert [row["id"] for row in report["requirements"]] == ["AC-1", "AC-001"]
    assert report["summary"]["unproven"] == 2
    assert cli("evaluate_acceptance", strict=True)["allowed"] is False


@pytest.mark.parametrize("mutation", ["local", "commit", "proof", "output", "store", "inventory"])
def test_current_evidence_detects_staleness_and_corruption(acceptance_workspace, mutation):
    assert freeze()["status"] == "success"
    report = cli("run_acceptance_proofs")
    if mutation == "local":
        Path("product.txt").write_text("changed")
    elif mutation == "commit":
        subprocess.run(["git", "commit", "--allow-empty", "-m", "new"], check=True, capture_output=True)
    elif mutation == "proof":
        Path("proof.py").write_text("pass\n")
    elif mutation == "output":
        (acceptance_workspace / report["requirements"][0]["receipt"]["output_artifact"]).unlink()
    elif mutation == "store":
        (acceptance_workspace / "acceptance-proofs.json").unlink()
    else:
        (acceptance_workspace / "spec_main.md").unlink()
    assert cli("evaluate_acceptance")["allowed"] is False


def test_runner_interruption_preserves_owner_and_requires_new_attempt(acceptance_workspace):
    import time

    Path("proof.py").write_text(
        "import time\nfrom pathlib import Path\nPath('.map/started').touch()\n"
        "while not Path('.map/release').exists(): time.sleep(.02)\n"
    )
    assert freeze(timeout=1.0)["status"] == "success"
    proc = subprocess.Popen([sys.executable, str(RUNNER), "run_acceptance_proofs"],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 5
        while not Path(".map/started").exists() and time.monotonic() < deadline:
            time.sleep(.02)
        assert Path(".map/started").exists()
        old_attempt = json.loads((acceptance_workspace / "acceptance-proofs.json").read_text())["attempts"][-1]["attempt_id"]
        proc.kill()
        proc.wait(timeout=3)
        blocked = cli("run_acceptance_proofs")
        assert blocked["status"] == "error" and "still running" in blocked["message"]
        assert cli("evaluate_acceptance")["allowed"] is False
        Path(".map/release").touch()
        time.sleep(1.2)
        assert cli("evaluate_acceptance")["allowed"] is False
        recovered = cli("run_acceptance_proofs")
        assert recovered["requirements"][0]["status"] == "proven", recovered
        assert recovered["requirements"][0]["receipt"]["attempt_id"] != old_attempt
        history = json.loads((acceptance_workspace / "acceptance-proofs.json").read_text())["attempts"]
        assert history[0]["state"] == "interrupted"
    finally:
        Path(".map/release").touch()
        if proc.poll() is None:
            proc.kill()
        proc.communicate(timeout=5)


def test_independent_revision_keeps_full_audit_and_invalidates_receipts(acceptance_workspace):
    assert freeze()["status"] == "success"
    old = cli("run_acceptance_proofs")["requirements"][0]
    Path("proof.py").write_text("print('weaker')\n")
    revised = cli("revise_acceptance_contract", ac_id="AC-1", command=[sys.executable, "proof.py"],
                  proof_files=["proof.py"], author="independent-test-writer", reason="Changed requirement",
                  assessment="weakening", weakening_justification="Owner removed obsolete behavior")
    assert revised["status"] == "success", revised
    report = cli("evaluate_acceptance")
    assert report["requirements"][0]["status"] == "unproven"
    revision = report["revisions"][0]
    assert revision["author"] == "independent-test-writer"
    assert revision["reason"] == "Changed requirement"
    assert revision["created_at"]
    assert revision["invalidated_attempts"] == [old["receipt"]["attempt_id"]]
    assert revision["old_contract"] == old["contract"]
    assert "assert" in revision["proof_diff"]
    assert revision["assessment"] == "weakening"
    assert cli("run_acceptance_proofs")["requirements"][0]["status"] == "proven"
    summary = cli("write_acceptance_report")
    assert summary["status"] == "success", summary
    assert "Owner removed obsolete behavior" in (acceptance_workspace / "acceptance-report.md").read_text()


@pytest.mark.parametrize("assessment,justification", [("equivalent", ""), ("weakening", ""), ("unknown", "")])
def test_removal_cannot_be_silently_declared_safe(acceptance_workspace, assessment, justification):
    del acceptance_workspace
    assert freeze()["status"] == "success"
    Path("proof.py").write_text("pass\n")
    revised = cli("revise_acceptance_contract", ac_id="AC-1", command=[sys.executable, "proof.py"],
                  proof_files=["proof.py"], author="independent-test-writer", reason="Rewrite",
                  assessment=assessment, weakening_justification=justification)
    assert revised["status"] == "success", revised
    assert cli("evaluate_acceptance")["allowed"] is False


def test_unresolved_revision_requires_audited_independent_assessment(acceptance_workspace):
    del acceptance_workspace
    assert freeze()["status"] == "success"
    Path("proof.py").write_text("pass\n")
    revised = cli("revise_acceptance_contract", ac_id="AC-1", command=[sys.executable, "proof.py"],
                  proof_files=["proof.py"], author="independent-test-writer", reason="Rewrite",
                  assessment="unknown")
    assert revised["status"] == "success"
    assert cli("evaluate_acceptance")["allowed"] is False
    assessed = cli("assess_acceptance_revision", ac_id="AC-1", revision=2, author="reviewer",
                   assessment="weakening", reason="Independent review completed",
                   weakening_justification="Obsolete assertion removed by requirement owner")
    assert assessed["status"] == "success", assessed
    report = cli("evaluate_acceptance")
    assert report["allowed"] is True, report
    assert report["revisions"][0]["assessment"] == "unknown"
    assert report["revisions"][0]["assessments"][-1]["author"] == "reviewer"


def test_legacy_review_owner_blocks_acceptance_execution(acceptance_workspace):
    assert freeze()["status"] == "success"
    (acceptance_workspace / "review-verdict-ledger.json").write_text(json.dumps({
        "execution_checks": {"legacy": {"state": "running"}},
    }))
    result = cli("run_acceptance_proofs")
    assert result["status"] == "error", result
    assert "ownership" in result["message"].lower()
    repro = acceptance_workspace / "repro"
    repro.mkdir()
    probe = repro / "probe.sh"
    probe.write_text("#!/bin/sh\nexit 42\n")
    denied = subprocess.run([sys.executable, str(RUNNER), "record_repro_probe", str(probe)],
                            capture_output=True, text=True, check=False)
    assert json.loads(denied.stdout)["status"] == "error"
    assert not (repro / ".locked/probe.snapshot").exists()


def test_repro_record_does_not_mutate_frozen_input_while_owner_active(acceptance_workspace):
    import fcntl

    repro = acceptance_workspace / "repro"
    repro.mkdir()
    probe = repro / "probe.sh"
    probe.write_text("#!/bin/sh\nexit 42\n")
    initial = subprocess.run([sys.executable, str(RUNNER), "record_repro_probe", str(probe)],
                             capture_output=True, text=True, check=False)
    assert json.loads(initial.stdout)["status"] == "success", initial.stdout
    snapshot = repro / ".locked/probe.snapshot"
    before = snapshot.read_bytes()
    probe.write_text("#!/bin/sh\nexit 0\n")
    with (acceptance_workspace / ".review-execution.lock").open("a") as lease:
        fcntl.flock(lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        blocked = subprocess.run([sys.executable, str(RUNNER), "record_repro_probe", str(probe)],
                                 capture_output=True, text=True, check=False)
    assert json.loads(blocked.stdout)["status"] == "error", blocked.stdout
    assert snapshot.read_bytes() == before
