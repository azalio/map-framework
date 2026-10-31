"""Incomplete evidence stays resumable without consuming the bounded review budget."""

import copy
import json
import sys
from pathlib import Path

import pytest

from tests import test_review_verdict_ledger as ledger_tests

runner = ledger_tests.map_step_runner
branch_workspace = ledger_tests.branch_workspace
review_git_workspace = ledger_tests.review_git_workspace


@pytest.mark.parametrize("flags", ["", "--compare-orderings", "--adversarial", "--adversarial --compare-orderings"])
@pytest.mark.parametrize("gap", ["scope", "denied", "check", "codex"])
def test_pending_third_round_resumes_across_restart(review_git_workspace, flags, gap):
    workspace = review_git_workspace
    profile = Path(".claude/agents/review-reader.md")
    profile.parent.mkdir(parents=True)
    profile.write_text("---\nname: review-reader\ntools: Read, Glob, Grep\n---\n")
    provider = "codex" if gap == "codex" else "claude"
    for round_id in ("1", "2"):
        assert runner.begin_review_run(arguments=flags, mode="lightweight", provider=provider, round_id=round_id)["status"] == "success"
        assert runner.abandon_review_round(round_id, reason="Explicitly cancel earlier attempt")["status"] == "success"
    admission = runner.begin_review_run(arguments=flags, mode="lightweight", provider=provider, round_id="3")
    assert admission["status"] == "success", admission
    assert runner.create_review_bundle()["status"] == "success"
    receipt = {"covered_files": admission["required_files"], "skipped_files": [],
               "denied_access": [], "check_evidence": []}
    incomplete = copy.deepcopy(receipt)
    if gap == "scope":
        incomplete["covered_files"] = []
        incomplete["skipped_files"] = ["writer.py"]
    elif gap == "denied":
        incomplete["denied_access"] = ["writer.py"]
    elif gap == "check":
        incomplete["check_evidence"] = ["unrecorded-check"]

    def capture(value):
        if "--adversarial" in flags:
            report = ledger_tests._produced_adversarial_report(receipt=value)
            return ledger_tests._capture_aggregate(report, "3", flags)
        payload = {**ledger_tests._monitor_with_critical(), "receipt": value}
        for ordering in (("default", "reverse") if "--compare-orderings" in flags else ("",)):
            assert runner.capture_review_output("monitor", json.dumps(payload), "3", ordering=ordering)["status"] == "success"
        return runner.write_review_verdict_ledger(current_run=True)

    result = capture(incomplete)
    assert result["status"] == "success", result
    ledger = json.loads((workspace / "review-verdict-ledger.json").read_text())
    row = ledger["convergence"]["rounds"][-1]
    assert ledger["completeness"]["status"] == ("BLOCKED" if gap == "denied" else "INCOMPLETE")
    assert ledger["code_approval"]["approved"] is False
    assert ledger["findings_registry"]
    assert ledger["convergence"]["completed_rounds"] == 0
    assert ledger["convergence"]["attempted_rounds"] == 2
    assert ledger["convergence"]["outcome"] == "incomplete"
    assert not {"completed_at", "submission_digest", "covered_files"}.intersection(row)
    assert runner.review_round_scope()["kind"] == "full"
    _, gate = ledger_tests._review_cli("write_stage_gate", "review", "ready", "review.md", "pending")
    assert gate["status"] == "error"
    proc, resumed = ledger_tests._review_cli("begin_review_run", f"--arguments={flags}", "--mode", "lightweight",
                                            "--provider", provider, "--round-id", "3")
    assert proc.returncode == 0 and resumed["resumed"] and not resumed["completed"], resumed
    assert resumed["target"] == admission["target"]
    assert runner.begin_review_run(arguments=flags, mode="lightweight", provider=provider, round_id="4")["status"] == "error"
    corrected = capture(receipt)
    assert corrected["status"] == "success", corrected
    after = json.loads((workspace / "review-verdict-ledger.json").read_text())
    assert [f["id"] for f in after["findings_registry"]] == [f["id"] for f in ledger["findings_registry"]]
    if gap == "codex":
        assert after["completeness"]["status"] == "INCOMPLETE"
        assert after["convergence"]["attempted_rounds"] == 2
        assert runner.abandon_review_round("3", reason="Capability remains unverified")["convergence"]["outcome"] == "capped"
    else:
        assert after["completeness"]["status"] == "COMPLETE", after["completeness"]
        assert after["convergence"]["completed_rounds"] == 1
        assert after["convergence"]["attempted_rounds"] == 3
        assert after["convergence"]["outcome"] == "capped"
        assert runner.write_review_verdict_ledger(current_run=True)["convergence"] == after["convergence"]
        assert runner.capture_review_output("monitor", "{}", "3")["status"] == "error"
    assert runner.begin_review_run(arguments=flags, mode="lightweight", provider=provider, round_id="4")["stop_reason"] == "reconsider_approach"


@pytest.mark.parametrize("failed_first", [False, True])
def test_required_check_can_finish_after_pending_ledger(review_git_workspace, failed_first):
    workspace = review_git_workspace
    marker = workspace / "check-ready"
    command = [sys.executable, "-c", f"from pathlib import Path; raise SystemExit(0 if Path({str(marker)!r}).exists() else 1)"]
    admission = ledger_tests._admit_receipt_review(runner, required_checks=["suite"], check_specs={"suite": command})
    payload = {**ledger_tests._monitor_no_issues(), "receipt": {
        "covered_files": admission["required_files"], "skipped_files": [],
        "denied_access": [], "check_evidence": ["suite"]}}
    assert runner.capture_review_output("monitor", json.dumps(payload), "receipt")["status"] == "success"
    if failed_first:
        _, check = ledger_tests._review_cli("run_test_gate", "--check-id", "suite")
        assert check["passed"] is False
    result = runner.write_review_verdict_ledger(current_run=True)
    assert result["code_approval"]["approved"] is False
    assert result["convergence"]["attempted_rounds"] == 0
    marker.touch()
    proc, check = ledger_tests._review_cli("run_test_gate", "--check-id", "suite")
    assert proc.returncode == 0 and check["passed"], check
    proc, completed = ledger_tests._review_cli("write_review_verdict_ledger", "--current-run")
    assert proc.returncode == 0 and completed["code_approval"]["approved"], completed
    assert completed["convergence"]["completed_rounds"] == 1
    ledger = json.loads((workspace / "review-verdict-ledger.json").read_text())
    assert ledger["execution_checks"]["suite"]["passed"] is True
    assert len(ledger["execution_check_history"]) == int(failed_first)
