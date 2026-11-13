"""A failed command is collected evidence, never an implicit passing review gate."""

import copy
import json
import sys
from pathlib import Path
from typing import Any, cast

import pytest

from tests import test_review_verdict_ledger as ledger_tests

runner = cast(Any, ledger_tests.map_step_runner)
branch_workspace = ledger_tests.branch_workspace
review_git_workspace = ledger_tests.review_git_workspace


def _admit(workspace, program="print('diagnostic remains visible'); raise SystemExit(2)", *,
           command=None, timeout=10):
    profile = Path(".claude/agents/review-reader.md")
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text("---\nname: review-reader\ntools: Read, Glob, Grep\n---\nRead only.\n")
    argv = command if command is not None else [sys.executable, "-c", program]
    admission = runner.begin_review_run(
        scheduled_reviewers=["monitor"], round_id="receipt", provider="claude",
        required_checks=["suite"], check_specs={"suite": argv}, check_timeouts={"suite": timeout})
    assert admission["status"] == "success", admission
    assert runner.create_review_bundle()["status"] == "success"
    result = runner.run_test_gate(check_id="suite")
    ledger = json.loads((workspace / "review-verdict-ledger.json").read_text())
    return admission, result, ledger


def _capture(admission, context_receipt=None):
    envelope = {**ledger_tests._monitor_no_issues(), "receipt": {
        "covered_files": admission["required_files"], "skipped_files": [],
        "denied_access": [], "check_evidence": ["suite"]}}
    if context_receipt is not None:
        envelope["context_receipt"] = context_receipt
    result = runner.capture_review_output("monitor", json.dumps(envelope), "receipt")
    assert result["status"] == "success", result


def test_failed_command_is_valid_observation_but_not_strict_pass(review_git_workspace):
    workspace = review_git_workspace
    _, result, ledger = _admit(workspace)
    row = ledger["convergence"]["rounds"][-1]
    assert result["passed"] is False and result["exit_code"] == 2
    assert ledger["execution_checks"]["suite"]["status"] == "success"
    assert runner._review_check_observation_valid(workspace, "suite", row) is True
    assert runner._review_check_valid(workspace, "suite", row) is False
    assert "diagnostic remains visible" in (
        workspace / ledger["execution_checks"]["suite"]["output_artifact"]).read_text()


@pytest.mark.parametrize("kind", ["timeout", "launch", "signal"])
def test_abnormal_execution_is_not_collected_observation(review_git_workspace, kind):
    workspace = review_git_workspace
    kwargs = {
        "timeout": {"program": "import time; time.sleep(1)", "timeout": 0.02},
        "launch": {"command": ["/no/such/review-check"]},
        "signal": {"program": "import os, signal; os.kill(os.getpid(), signal.SIGTERM)"},
    }[kind]
    _, result, ledger = _admit(workspace, **kwargs)
    row = ledger["convergence"]["rounds"][-1]
    assert result["passed"] is False
    assert runner._review_check_observation_valid(workspace, "suite", row) is False
    assert runner._review_check_valid(workspace, "suite", row) is False


@pytest.mark.parametrize("defect", [
    "output", "missing_output", "hash", "command", "attempt", "round", "timeout",
    "policy", "before", "after", "lease", "state", "status", "boolean_exit", "negative_exit",
])
def test_failed_observation_rejects_tampered_or_misbound_evidence(review_git_workspace, defect):
    workspace = review_git_workspace
    _, _, ledger = _admit(workspace)
    row = ledger["convergence"]["rounds"][-1]
    assert runner._review_check_observation_valid(workspace, "suite", row) is True
    check = ledger["execution_checks"]["suite"]
    mutations = {
        "hash": ("output_sha256", "0" * 64), "command": ("command", [sys.executable, "-c", "pass"]),
        "attempt": ("attempt_id", ""), "round": ("round_id", "other-round"),
        "timeout": ("timeout_seconds", 11), "policy": ("policy_hash", "other-policy"),
        "before": ("before", {}), "after": ("after", {}), "lease": ("lease_protocol", "legacy"),
        "state": ("state", "running"), "status": ("status", "cleanup_blocked"),
        "boolean_exit": ("exit_code", True), "negative_exit": ("exit_code", -15),
    }
    if defect == "output":
        (workspace / check["output_artifact"]).write_text("forged output")
    elif defect == "missing_output":
        (workspace / check["output_artifact"]).unlink()
    else:
        key, value = mutations[defect]
        check[key] = value
        (workspace / "review-verdict-ledger.json").write_text(json.dumps(ledger))
    assert runner._review_check_observation_valid(workspace, "suite", row) is False
    assert runner._review_check_valid(workspace, "suite", row) is False


def test_failed_log_is_visible_in_compact_prompt_and_frozen_lazy_resource(review_git_workspace):
    workspace = review_git_workspace
    _, _, ledger = _admit(workspace)
    row = ledger["convergence"]["rounds"][-1]
    text = runner._review_compact_bundle("test-branch")
    assert '"passed": false' in text
    assert '"full_gate_status": "failed"' in text
    assert '"output_resource": "check:suite"' in text
    metadata, created = runner._review_lazy_check_resource(workspace, row, "check:suite")
    assert created is True
    check = ledger["execution_checks"]["suite"]
    assert metadata["check_identity"] == {
        "attempt_id": check["attempt_id"], "output_sha256": check["output_sha256"]}
    stored = workspace / "review-context-objects" / metadata["sha256"]
    assert "diagnostic remains visible" in stored.read_text()
    assert runner._review_lazy_check_resource(workspace, row, "check:suite") == (metadata, False)


def test_complete_failed_check_receipt_collects_but_cannot_approve(review_git_workspace):
    workspace = review_git_workspace
    admission, _, _ = _admit(workspace)
    _capture(admission)
    final = runner.write_review_verdict_ledger(current_run=True)
    assert final["status"] == "success", final
    ledger = json.loads((workspace / "review-verdict-ledger.json").read_text())
    assert ledger["completeness"]["status"] == "COMPLETE", ledger["completeness"]
    assert ledger["code_approval"]["approved"] is False
    assert ledger["execution_checks"]["suite"]["passed"] is False
    assert runner.write_stage_gate("review", "ready", "review.md")["status"] == "error"


def test_rerun_after_summary_only_delivery_invalidates_observation_and_completion(review_git_workspace):
    workspace = review_git_workspace
    admission, _, ledger = _admit(workspace)
    first = ledger["execution_checks"]["suite"]
    summary = runner._review_compact_bundle("test-branch")
    assert '"passed": false' in summary
    ledger = json.loads((workspace / "review-verdict-ledger.json").read_text())
    row = ledger["convergence"]["rounds"][-1]
    assert "check:suite" not in row.get("context_lazy", {})
    _capture(admission)
    ledger = json.loads((workspace / "review-verdict-ledger.json").read_text())
    row = ledger["convergence"]["rounds"][-1]
    assert runner._review_completeness(row, workspace)["status"] == "COMPLETE"
    rerun = runner.run_test_gate(check_id="suite")
    assert rerun["state"] == "finished" and rerun["passed"] is False, rerun
    assert rerun["attempt_id"] != first["attempt_id"]
    ledger = json.loads((workspace / "review-verdict-ledger.json").read_text())
    row = ledger["convergence"]["rounds"][-1]
    assert "check:suite" not in row.get("context_lazy", {})
    assert runner._review_check_observation_valid(workspace, "suite", row) is False
    final = runner.write_review_verdict_ledger(current_run=True)
    assert final.get("code_approval", {}).get("approved") is not True, final
    ledger = json.loads((workspace / "review-verdict-ledger.json").read_text())
    assert ledger["completeness"]["status"] == "INCOMPLETE"
    assert ledger["code_approval"]["approved"] is False


def test_rerun_after_failed_log_delivery_invalidates_frozen_resource_and_completion(review_git_workspace):
    workspace = review_git_workspace
    admission, _, ledger = _admit(workspace)
    prompts = runner.build_review_prompts()
    assert prompts["status"] == "success", prompts
    context_id = prompts["prompts"]["monitor"]["context_transport"]["context_id"]
    state = runner.bind_review_context("monitor", context_id, "native-agent", "receipt")
    assert state["status"] == "context_pending", state
    while state["status"] == "context_pending":
        request = {"type": "context_request", "context_id": context_id,
                   "resource_id": state["remaining"][0]["resource_id"],
                   "offset": state["remaining"][0]["offset"]}
        chunk = runner.serve_review_context("monitor", json.dumps(request), "receipt",
                                           session_id=state["session_id"], agent_id="native-agent")
        assert chunk["status"] == "context_response", chunk
        state = runner.ack_review_context(state["session_id"], "native-agent", json.dumps(chunk), "receipt")
        assert state["status"] in {"context_pending", "context_ready"}, state
    request = {"type": "context_request", "context_id": context_id, "resource_id": "check:suite", "offset": 0}
    chunk = runner.serve_review_context("monitor", json.dumps(request), "receipt",
                                       session_id=state["session_id"], agent_id="native-agent")
    assert chunk["status"] == "context_response", chunk
    state = runner.ack_review_context(state["session_id"], "native-agent", json.dumps(chunk), "receipt")
    assert state["status"] == "context_ready", state
    _capture(admission, {"session_id": state["session_id"], "finalization_token": state["finalization_token"]})
    first = copy.deepcopy(ledger["execution_checks"]["suite"])
    rerun = runner.run_test_gate(check_id="suite")
    assert rerun["state"] == "finished" and rerun["passed"] is False, rerun
    ledger = json.loads((workspace / "review-verdict-ledger.json").read_text())
    row = ledger["convergence"]["rounds"][-1]
    assert ledger["execution_checks"]["suite"]["attempt_id"] != first["attempt_id"]
    assert row["context_lazy"]["check:suite"]["check_identity"]["attempt_id"] == first["attempt_id"]
    with pytest.raises(ValueError):
        runner._review_lazy_check_resource(workspace, row, "check:suite")
    assert runner._review_check_observation_valid(workspace, "suite", row) is False
    final = runner.write_review_verdict_ledger(current_run=True)
    assert final.get("code_approval", {}).get("approved") is not True, final
    ledger = json.loads((workspace / "review-verdict-ledger.json").read_text())
    assert ledger["completeness"]["status"] != "COMPLETE"
    assert ledger["code_approval"]["approved"] is False
