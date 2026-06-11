"""Tests for map_step_runner human-readable artifact helpers."""

import json
import os
import re
import subprocess
import sys
import types
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

SCRIPTS_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "mapify_cli"
    / "templates"
    / "map"
    / "scripts"
)

sys.path.insert(0, str(SCRIPTS_PATH))

import map_step_runner  # noqa: E402  # type: ignore[import-not-found]


def _stub_compute_insight(payload: dict[str, object]):
    def _stub(*args: object, **kwargs: object) -> dict[str, object]:
        del args, kwargs
        return payload
    return _stub


def _blueprint_constraint_fields() -> dict[str, object]:
    return {
        "hard_constraints": [
            {"id": "AC-1", "description": "Timeouts must show a retryable message"},
        ],
        "soft_constraints": [
            {
                "id": "SC-1",
                "description": "Prefer concise implementation",
                "tradeoff_rationale": "Not required for the blocking user-visible contract",
            },
        ],
    }


@pytest.fixture
def branch_workspace(tmp_path, monkeypatch):
    branch = "test-branch"
    workspace = tmp_path / ".map" / branch
    workspace.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(map_step_runner, "get_branch_name", lambda: branch)
    return workspace


def _valid_run_health_payload() -> dict[str, Any]:
    artifact_entry = {
        "kind": "state",
        "path": ".map/test-branch/step_state.json",
        "present": True,
        "size_bytes": 1,
    }
    return {
        "schema_version": "1.0",
        "generated_at": "2026-05-16T10:00:00Z",
        "workflow": "map-check",
        "branch": "test-branch",
        "terminal_status": "complete",
        "current_step_id": None,
        "current_step_phase": "COMPLETE",
        "current_subtask_id": None,
        "completed_step_count": 1,
        "pending_step_count": 0,
        "artifacts": {
            key: artifact_entry
            for key in (
                "step_state",
                "artifact_manifest",
                "verification_summary",
                "qa",
                "pr_draft",
                "review_bundle",
                "learning_handoff",
                "task_plan",
                "blueprint",
                "active_issues",
                "known_issues",
                "retry_quarantine",
            )
        },
        "resiliency_signals": {
            "hook_injection": {"status": "injected"},
            "hook_injection_counts": {"injected": 1},
            "retry_count": 0,
            "max_retries": 5,
            "subtask_retry_counts": {},
            "max_subtask_retry_count": 0,
            "clean_retry_count": 0,
            "contaminated_retry_count": 0,
            "retry_isolation_status": {},
            "guard_rework_counts": {},
            "predictor_called": False,
            "predictor_skipped": False,
            "final_verifier_executed": True,
        },
    }


def test_ensure_human_artifacts_creates_defaults(branch_workspace):
    result = map_step_runner.ensure_human_artifacts()

    assert result["status"] == "success"
    assert (branch_workspace / "qa-001.md").exists()
    assert (branch_workspace / "pr-draft.md").exists()


def test_next_numbered_artifact_path_increments(branch_workspace):
    (branch_workspace / "code-review-001.md").write_text("one", encoding="utf-8")
    (branch_workspace / "code-review-002.md").write_text("two", encoding="utf-8")

    result = map_step_runner.next_numbered_artifact_path("code-review")

    assert result["status"] == "success"
    assert result["file_name"] == "code-review-003.md"


def test_write_verification_summary_creates_report(branch_workspace):
    result = map_step_runner.write_verification_summary(
        "READY FOR REVIEW",
        "Implement auth",
        "- pytest\n- ruff",
        "- no blocking issues",
        "- open PR",
    )

    assert result["status"] == "success"
    content = (branch_workspace / "verification-summary.md").read_text(encoding="utf-8")
    assert "READY FOR REVIEW" in content
    assert "Implement auth" in content
    assert "open PR" in content
    assert "## Prior-Stage Consumption" in content
    assert result["prior_stage_consumption"]["stage"] == "implementation"


def test_write_run_health_report_creates_report_and_manifest(branch_workspace):
    (branch_workspace / "step_state.json").write_text(
        json.dumps(
            {
                "workflow": "map-efficient",
                "current_step_id": "2.4",
                "current_step_phase": "MONITOR",
                "current_subtask_id": "ST-001",
                "completed_steps": ["1.0", "1.5", "2.3"],
                "pending_steps": ["2.4"],
                "retry_count": 2,
                "max_retries": 5,
                "subtask_retry_counts": {"ST-001": 1},
                "clean_retry_count": 1,
                "contaminated_retry_count": 1,
                "retry_isolation_status": {"ST-001": "clean_retry_required"},
                "hook_injection": {"status": "injected", "tool_name": "Edit"},
                "hook_injection_counts": {"injected": 3},
                "predictor_skipped": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (branch_workspace / "verification-summary.md").write_text(
        "# Verification Summary\n", encoding="utf-8"
    )

    result = map_step_runner.write_run_health_report("map-efficient", "blocked")

    assert result["status"] == "success"
    report = json.loads((branch_workspace / "run_health_report.json").read_text())
    assert report["terminal_status"] == "blocked"
    assert report["completed_step_count"] == 3
    assert report["pending_step_count"] == 1
    assert report["artifacts"]["step_state"]["present"] is True
    assert report["artifacts"]["verification_summary"]["present"] is True
    signals = report["resiliency_signals"]
    assert signals["hook_injection"]["status"] == "injected"
    assert signals["retry_count"] == 2
    assert signals["max_subtask_retry_count"] == 1
    assert signals["clean_retry_count"] == 1
    assert signals["contaminated_retry_count"] == 1
    assert signals["retry_isolation_status"] == {"ST-001": "clean_retry_required"}
    assert signals["predictor_skipped"] is True
    assert signals["final_verifier_executed"] is True

    manifest = json.loads((branch_workspace / "artifact_manifest.json").read_text())
    stage = manifest["stages"]["run_health"]
    assert stage["status"] == "ready"
    assert stage["metadata"]["terminal_status"] == "blocked"


def test_build_retry_quarantine_writes_valid_artifact(branch_workspace):
    result = map_step_runner.build_retry_quarantine(
        "ST-001", 2, "Actor repeated the rejected cache strategy."
    )

    assert result["status"] == "success"
    assert result["valid"] is True
    payload = json.loads((branch_workspace / "retry_quarantine.json").read_text())
    entry = payload["quarantines"][0]
    assert entry["subtask_id"] == "ST-001"
    assert entry["retry_count"] == 2
    assert entry["isolation_mode"] == "clean_retry"
    assert entry["preserved_constraints"]
    assert entry["required_evidence"]


def test_validate_retry_quarantine_rejects_missing_constraints(branch_workspace):
    (branch_workspace / "retry_quarantine.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "branch": "test-branch",
                "updated_at": "2026-05-20T10:00:00Z",
                "quarantines": [
                    {
                        "subtask_id": "ST-001",
                        "retry_count": 2,
                        "isolation_mode": "clean_retry",
                        "failed_attempt": "retry_2",
                        "monitor_rejection_summary": "Still broken.",
                        "rejected_assumptions": [],
                        "do_not_repeat": [],
                        "preserved_constraints": [],
                        "required_evidence": ["Run tests."],
                        "source_artifacts": [
                            {"path": ".map/test-branch/step_state.json", "kind": "step-state"},
                            {"path": ".map/test-branch/blueprint.json", "kind": "blueprint"},
                        ],
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = map_step_runner.validate_retry_quarantine()

    assert result["status"] == "error"
    assert result["valid"] is False
    assert "quarantines[0].preserved_constraints must be a non-empty array" in result[
        "errors"
    ]


def test_validate_retry_quarantine_handles_invalid_utf8(branch_workspace):
    (branch_workspace / "retry_quarantine.json").write_bytes(b"\xff\xfe")

    result = map_step_runner.validate_retry_quarantine()

    assert result["status"] == "error"
    assert result["valid"] is False
    assert any("cannot read retry quarantine" in error for error in result["errors"])


def test_validate_retry_quarantine_rejects_bool_retry_count(branch_workspace):
    result = map_step_runner.build_retry_quarantine("ST-001", 2, "Repeated failure")
    assert result["valid"] is True
    payload = json.loads((branch_workspace / "retry_quarantine.json").read_text())
    payload["quarantines"][0]["retry_count"] = True
    (branch_workspace / "retry_quarantine.json").write_text(
        json.dumps(payload) + "\n", encoding="utf-8"
    )

    result = map_step_runner.validate_retry_quarantine()

    assert result["status"] == "error"
    assert "quarantines[0].retry_count must be an integer >= 2" in result["errors"]


def test_artifact_health_entry_handles_disappearing_file():
    with patch.object(Path, "stat", side_effect=FileNotFoundError):
        entry = map_step_runner._artifact_health_entry(Path("transient.json"), "state")

    assert entry == {
        "kind": "state",
        "path": "transient.json",
        "present": False,
        "size_bytes": 0,
    }


def test_map_step_runner_cli_write_run_health_report_smoke(tmp_path):
    branch = "default"
    branch_dir = tmp_path / ".map" / branch
    branch_dir.mkdir(parents=True)
    (branch_dir / "step_state.json").write_text(
        json.dumps(
            {
                "workflow": "map-check",
                "current_step_phase": "COMPLETE",
                "completed_steps": ["1.0"],
                "pending_steps": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_PATH / "map_step_runner.py"),
            "write_run_health_report",
            "map-check",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(result.stdout)
    assert payload["status"] == "success"
    report = json.loads((tmp_path / payload["path"]).read_text())
    assert report["terminal_status"] == "complete"
    assert report["workflow"] == "map-check"


def test_write_run_health_report_derives_workflow_complete(branch_workspace):
    (branch_workspace / "step_state.json").write_text(
        json.dumps(
            {
                "workflow": "map-efficient",
                "workflow_status": "WORKFLOW_COMPLETE",
                "completed_steps": ["1.0"],
                "pending_steps": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = map_step_runner.write_run_health_report("map-efficient")

    assert result["status"] == "success"
    assert result["terminal_status"] == "complete"
    report = json.loads((branch_workspace / "run_health_report.json").read_text())
    assert report["terminal_status"] == "complete"


def test_write_run_health_report_counts_legacy_dict_steps(branch_workspace):
    (branch_workspace / "step_state.json").write_text(
        json.dumps(
            {
                "completed_steps": {"ST-001": ["1.0", "1.1"], "ST-002": ["2.0"]},
                "pending_steps": {"ST-001": [], "ST-002": ["2.1", "2.2"]},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = map_step_runner.write_run_health_report("map-efficient", "pending")

    assert result["status"] == "success"
    report = json.loads((branch_workspace / "run_health_report.json").read_text())
    assert report["completed_step_count"] == 3
    assert report["pending_step_count"] == 2


def test_validate_run_health_report_accepts_valid_complete(branch_workspace):
    (branch_workspace / "step_state.json").write_text(
        json.dumps(
            {
                "workflow": "map-efficient",
                "workflow_status": "WORKFLOW_COMPLETE",
                "completed_steps": ["1.0", "2.0"],
                "pending_steps": [],
                "retry_count": 1,
                "max_retries": 5,
                "hook_injection": {"status": "injected", "tool_name": "Bash"},
                "final_verifier_executed": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    map_step_runner.write_run_health_report("map-efficient")
    result = map_step_runner.validate_run_health_report()

    assert result["status"] == "success"
    assert result["valid"] is True
    assert result["errors"] == []


def test_validate_run_health_report_accepts_legacy_without_clean_retry_fields(
    branch_workspace,
):
    payload = _valid_run_health_payload()
    payload["artifacts"].pop("retry_quarantine")
    signals = payload["resiliency_signals"]
    signals.pop("clean_retry_count")
    signals.pop("contaminated_retry_count")
    signals.pop("retry_isolation_status")
    (branch_workspace / "run_health_report.json").write_text(
        json.dumps(payload) + "\n", encoding="utf-8"
    )

    result = map_step_runner.validate_run_health_report()

    assert result["status"] == "success"
    assert result["valid"] is True
    assert result["errors"] == []


def test_validate_run_health_report_rejects_inconsistent_complete(branch_workspace):
    (branch_workspace / "step_state.json").write_text(
        json.dumps(
            {
                "workflow": "map-efficient",
                "completed_steps": ["1.0"],
                "pending_steps": ["2.0"],
                "retry_count": 0,
                "max_retries": 5,
                "hook_injection": {"status": "injected"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    map_step_runner.write_run_health_report("map-efficient", "complete")
    result = map_step_runner.validate_run_health_report()

    assert result["status"] == "error"
    assert result["valid"] is False
    assert "complete report must not have pending steps" in result["errors"]
    assert any("verification summary" in error for error in result["errors"])


def test_validate_run_health_report_rejects_retry_and_hook_degradation(branch_workspace):
    (branch_workspace / "step_state.json").write_text(
        json.dumps(
            {
                "workflow": "map-debug",
                "completed_steps": ["1.0"],
                "pending_steps": ["2.0"],
                "retry_count": 6,
                "max_retries": 5,
                "subtask_retry_counts": {"ST-001": 7},
                "hook_injection": {"status": "skipped"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    map_step_runner.write_run_health_report("map-debug", "blocked")
    result = map_step_runner.validate_run_health_report()

    assert result["status"] == "error"
    assert "retry_count 6 exceeds max_retries 5" in result["errors"]
    assert "max_subtask_retry_count 7 exceeds max_retries 5" in result["errors"]
    assert any("hook_injection degradation" in error for error in result["errors"])


def test_validate_run_health_report_rejects_schema_drift_without_package_schema(
    branch_workspace, monkeypatch
):
    payload = _valid_run_health_payload()
    payload["terminal_status"] = "done"
    payload["extra"] = "unexpected"
    (branch_workspace / "run_health_report.json").write_text(
        json.dumps(payload) + "\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        map_step_runner, "_load_run_health_schema_validator", lambda: (None, None)
    )

    result = map_step_runner.validate_run_health_report()

    assert result["status"] == "error"
    assert "invalid terminal_status: done" in result["errors"]
    assert "unexpected field: extra" in result["errors"]


def test_validate_run_health_report_rejects_bool_retry_counts(branch_workspace):
    payload = _valid_run_health_payload()
    payload["resiliency_signals"]["clean_retry_count"] = True
    payload["completed_step_count"] = True
    payload["artifacts"]["step_state"]["size_bytes"] = False
    (branch_workspace / "run_health_report.json").write_text(
        json.dumps(payload) + "\n", encoding="utf-8"
    )

    result = map_step_runner.validate_run_health_report()

    assert result["status"] == "error"
    assert (
        "resiliency_signals.clean_retry_count must be a non-negative integer"
        in result["errors"]
    )
    assert "completed_step_count must be a non-negative integer" in result["errors"]
    assert (
        "artifacts.step_state.size_bytes must be a non-negative integer"
        in result["errors"]
    )


def test_map_step_runner_cli_validate_run_health_report_exits_nonzero(tmp_path):
    report = tmp_path / "bad-run-health.json"
    report.write_text('{"terminal_status": "complete"}\n', encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_PATH / "map_step_runner.py"),
            "validate_run_health_report",
            str(report),
        ],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["valid"] is False
    assert payload["errors"]


def test_write_pr_draft_creates_report(branch_workspace):
    result = map_step_runner.write_pr_draft(
        "- Added auth flow",
        "- pytest\n- ruff",
        "- follow up on metrics",
    )

    assert result["status"] == "success"
    content = (branch_workspace / "pr-draft.md").read_text(encoding="utf-8")
    assert "Added auth flow" in content
    assert "pytest" in content
    assert "follow up on metrics" in content


def test_record_workflow_fit_creates_decision_and_manifest(branch_workspace):
    result = map_step_runner.record_workflow_fit(
        "map-plan",
        "large",
        "true",
        "true",
        "false",
        "true",
        "New invariants and review justify planning",
    )

    assert result["status"] == "success"
    decision = json.loads((branch_workspace / "workflow-fit.json").read_text())
    assert decision["recommended_workflow"] == "map-plan"
    assert decision["needs_map"] is True
    assert decision["signals"]["test_first_required"] is True

    manifest = json.loads((branch_workspace / "artifact_manifest.json").read_text())
    stage = manifest["stages"]["workflow_fit"]
    assert stage["status"] == "recorded"
    assert stage["metadata"]["recommended_workflow"] == "map-plan"
    assert decision["updated_at"].endswith("Z")
    assert manifest["updated_at"].endswith("Z")
    assert stage["updated_at"].endswith("Z")


def test_record_workflow_fit_direct_edit_marks_needs_map_false(branch_workspace):
    result = map_step_runner.record_workflow_fit(
        "direct-edit",
        "tiny",
        "false",
        "false",
        "true",
        "false",
        "Trivial isolated edit should not use MAP orchestration",
    )

    assert result["status"] == "success"
    decision = json.loads((branch_workspace / "workflow-fit.json").read_text())
    assert decision["recommended_workflow"] == "direct-edit"
    assert decision["needs_map"] is False

    manifest = json.loads((branch_workspace / "artifact_manifest.json").read_text())
    stage = manifest["stages"]["workflow_fit"]
    assert stage["metadata"]["recommended_workflow"] == "direct-edit"
    assert stage["metadata"]["needs_map"] is False


def test_record_plan_artifacts_updates_manifest(branch_workspace):
    branch = branch_workspace.name
    (branch_workspace / f"spec_{branch}.md").write_text("# Spec\n", encoding="utf-8")
    (branch_workspace / f"task_plan_{branch}.md").write_text(
        "# Task Plan\n", encoding="utf-8"
    )
    (branch_workspace / "blueprint.json").write_text(
        '{"subtasks": [{"id": "ST-001", "aag_contract": "Service -> go() -> done", "dependencies": [], "affected_files": []}]}\n',
        encoding="utf-8",
    )
    (branch_workspace / "step_state.json").write_text(
        '{"current_step_phase": "INITIALIZED"}\n',
        encoding="utf-8",
    )

    result = map_step_runner.record_plan_artifacts()

    assert result["status"] == "success"
    manifest = json.loads((branch_workspace / "artifact_manifest.json").read_text())
    assert manifest["stages"]["spec"]["status"] == "ready"
    assert manifest["stages"]["plan"]["status"] == "ready"
    recorded_paths = {
        artifact["path"] for artifact in manifest["stages"]["plan"]["artifacts"]
    }
    assert f".map/{branch}/task_plan_{branch}.md" in recorded_paths
    assert f".map/{branch}/blueprint.json" in recorded_paths
    assert f".map/{branch}/step_state.json" in recorded_paths


def test_record_plan_artifacts_is_partial_when_only_step_state_exists(branch_workspace):
    (branch_workspace / "step_state.json").write_text(
        '{"current_step_phase": "INITIALIZED"}\n', encoding="utf-8"
    )

    result = map_step_runner.record_plan_artifacts()

    assert result["status"] == "success"
    assert result["plan_status"] == "partial"


def _write_completed_plan(branch_workspace, goal_title: str) -> None:
    """Seed a branch with a completed plan whose goal is `goal_title`."""
    branch = branch_workspace.name
    (branch_workspace / f"spec_{branch}.md").write_text(
        f"# Spec: {goal_title}\n\n## Acceptance Criteria\n- AC-1: ...\n",
        encoding="utf-8",
    )
    (branch_workspace / f"task_plan_{branch}.md").write_text(
        f"# Task Plan: {goal_title}\n\n## Overview\n- Goal: {goal_title}\n"
        f"- Source spec: .map/{branch}/spec_{branch}.md\n",
        encoding="utf-8",
    )
    (branch_workspace / "step_state.json").write_text(
        '{"current_step_phase": "COMPLETE", "workflow_status": "complete"}\n',
        encoding="utf-8",
    )


def test_check_plan_resume_no_plan_when_branch_empty(branch_workspace):
    del branch_workspace
    result = map_step_runner.check_plan_resume("implement token budget reporting")

    assert result["status"] == "ok"
    assert result["verdict"] == "no_plan"
    assert result["existing_goal"] is None
    assert result["artifacts"] == {
        "findings": False,
        "spec": False,
        "task_plan": False,
        "step_state": False,
    }


def test_check_plan_resume_resume_on_matching_goal(branch_workspace):
    _write_completed_plan(
        branch_workspace, "Implement token authentication middleware for the API"
    )

    result = map_step_runner.check_plan_resume(
        "Implement token authentication middleware"
    )

    assert result["verdict"] == "resume"
    assert result["artifacts"]["step_state"] is True
    # High overlap on the distinctive goal terms.
    assert result["containment"] >= map_step_runner.RESUME_GOAL_MISMATCH_CONTAINMENT
    assert "authentication" in result["shared_terms"]


def test_check_plan_resume_goal_mismatch_issue_166(branch_workspace):
    # Repro of issue #166: a long-lived branch already hosts a COMPLETED plan
    # for one goal; a brand-new, unrelated request must NOT be off-ramped as
    # "plan complete" nor silently clobber the prior plan.
    _write_completed_plan(branch_workspace, "Auditable Graph-Guided Incident Analysis")

    result = map_step_runner.check_plan_resume(
        "Add per-subtask token budget reporting to the statusline meter"
    )

    assert result["verdict"] == "goal_mismatch"
    assert result["existing_goal"] is not None
    assert result["containment"] < map_step_runner.RESUME_GOAL_MISMATCH_CONTAINMENT
    assert "archive" in result["recommendation"].lower()
    # The prior plan's goal is surfaced so the operator can decide.
    assert "Analysis" in result["recommendation"]


def test_check_plan_resume_empty_request_defaults_to_resume(branch_workspace):
    # A bare `/map-plan` resume (no request text) must preserve the prior
    # "step_state => complete" behavior — never divert to goal_mismatch.
    _write_completed_plan(branch_workspace, "Auditable Graph-Guided Incident Analysis")

    result = map_step_runner.check_plan_resume("")

    assert result["verdict"] == "resume"
    assert result["request"] == ""


def test_check_plan_resume_one_word_request_does_not_divert(branch_workspace):
    # Too little signal (one significant token) must never trigger a divert.
    _write_completed_plan(branch_workspace, "Auditable Graph-Guided Incident Analysis")

    result = map_step_runner.check_plan_resume("refactor")

    assert result["verdict"] == "resume"


def test_check_plan_resume_cli_smoke(tmp_path):
    branch = "test-branch"
    branch_dir = tmp_path / ".map" / branch
    branch_dir.mkdir(parents=True)
    (branch_dir / f"spec_{branch}.md").write_text(
        "# Spec: Auditable Graph-Guided Incident Analysis\n", encoding="utf-8"
    )
    (branch_dir / f"task_plan_{branch}.md").write_text(
        "# Task Plan: Auditable Graph-Guided Incident Analysis\n\n"
        "## Overview\n- Goal: Auditable Graph-Guided Incident Analysis\n",
        encoding="utf-8",
    )
    (branch_dir / "step_state.json").write_text(
        '{"current_step_phase": "COMPLETE"}\n', encoding="utf-8"
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_PATH / "map_step_runner.py"),
            "check_plan_resume",
            "Add per-subtask token budget reporting to the statusline meter",
            "--branch",
            branch,
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(result.stdout)
    assert payload["verdict"] == "goal_mismatch"
    assert payload["branch"] == branch


def test_validate_blueprint_contract_accepts_contract_sized_plan(branch_workspace):
    blueprint = {
        "summary": "Deliver a user-visible fix",
        **_blueprint_constraint_fields(),
        "subtasks": [
            {
                "id": "ST-001",
                "title": "Fix checkout timeout message",
                "aag_contract": "CheckoutService -> handle_timeout() -> user sees retryable error",
                "dependencies": [],
                "affected_files": ["src/checkout.py"],
                "expected_diff_size": "small",
                "concern_type": "runtime",
                "one_logical_step": True,
                "validation_criteria": [
                    "VC1 [AC-1]: timeout shows retryable message",
                    "VC2 [INV-1]: retry state is not corrupted",
                ],
            }
        ],
        "coverage_map": {"AC-1": "ST-001", "INV-1": "ST-001"},
    }
    (branch_workspace / "blueprint.json").write_text(json.dumps(blueprint))

    result = map_step_runner.validate_blueprint_contract()

    assert result["valid"] is True
    assert result["errors"] == []
    assert result["subtask_count"] == 1


def _blueprint_with_forward_dep_and_missing_tag() -> dict[str, object]:
    """Reproduces issue #168: ST-001 depends on ST-002 but is declared FIRST
    (forward-dependency ordering violation), and SC-1 is owned by ST-002 whose
    validation_criteria does not cite [SC-1] (coverage bracket-tag drift)."""
    return {
        "summary": "Deliver a user-visible fix with a dependency",
        "hard_constraints": [
            {"id": "AC-1", "description": "Timeouts must show a retryable message"},
        ],
        "soft_constraints": [
            {"id": "SC-1", "description": "Prefer a concise implementation"},
        ],
        "subtasks": [
            {
                "id": "ST-001",
                "title": "Wire the timeout message",
                "aag_contract": "CheckoutService -> handle_timeout() -> retryable error",
                "dependencies": ["ST-002"],
                "affected_files": ["src/checkout.py"],
                "expected_diff_size": "small",
                "concern_type": "runtime",
                "one_logical_step": True,
                "validation_criteria": ["VC1 [AC-1]: timeout shows retryable message"],
            },
            {
                "id": "ST-002",
                "title": "Build the retry helper module",
                "aag_contract": "RetryHelper -> backoff() -> bounded retries",
                "dependencies": [],
                "affected_files": ["src/retry.py"],
                "expected_diff_size": "small",
                "concern_type": "runtime",
                "one_logical_step": True,
                "validation_criteria": ["VC1: bounded exponential backoff"],
            },
        ],
        "coverage_map": {"AC-1": "ST-001", "SC-1": "ST-002"},
    }


def test_normalize_blueprint_fixes_issue_168_drift(branch_workspace):
    blueprint_path = branch_workspace / "blueprint.json"
    blueprint_path.write_text(
        json.dumps(_blueprint_with_forward_dep_and_missing_tag())
    )

    # Before normalize: validator hard-stops on BOTH drifts.
    before = map_step_runner.validate_blueprint_contract()
    assert before["valid"] is False
    assert before["forward_dep_violations"] == ["ST-001->ST-002"]
    assert any("SC-1" in str(err) for err in before["errors"])

    # Normalize: stable topo-sort + bracket-tag injection.
    norm = map_step_runner.normalize_blueprint()
    assert norm["status"] == "ok"
    assert norm["changed"] is True
    assert norm["reordered"] is True
    assert norm["subtask_order"] == ["ST-002", "ST-001"]
    assert norm["injected_coverage_tags"] == ["ST-002:[SC-1]"]
    assert norm["written"] is True

    # After normalize: validator passes and the file on disk reflects both fixes.
    after = map_step_runner.validate_blueprint_contract()
    assert after["valid"] is True
    assert after["errors"] == []

    written = json.loads(blueprint_path.read_text())
    assert [s["id"] for s in written["subtasks"]] == ["ST-002", "ST-001"]
    st002 = next(s for s in written["subtasks"] if s["id"] == "ST-002")
    assert any("[SC-1]" in c for c in st002["validation_criteria"])


def test_normalize_blueprint_is_idempotent(branch_workspace):
    blueprint_path = branch_workspace / "blueprint.json"
    blueprint_path.write_text(
        json.dumps(_blueprint_with_forward_dep_and_missing_tag())
    )

    first = map_step_runner.normalize_blueprint()
    assert first["changed"] is True

    second = map_step_runner.normalize_blueprint()
    assert second["changed"] is False
    assert second["reordered"] is False
    assert second["injected_coverage_tags"] == []
    assert second["unioned_creates_files"] == []
    assert second["written"] is False


def test_normalize_blueprint_unions_creates_files_into_affected(branch_workspace):
    """Repair #3 (issue #167): a `creates_files` path missing from
    `affected_files` is backfilled so the subset rule does not hard-stop the
    self-serve decompose->normalize->validate loop."""
    blueprint = {
        "summary": "Scaffold a new analyzer module",
        **_blueprint_constraint_fields(),
        "subtasks": [
            {
                "id": "ST-001",
                "title": "Scaffold the analyzer module",
                "aag_contract": "Analyzer -> run() -> report",
                "dependencies": [],
                "affected_files": ["src/analyzer.py"],
                # tests/test_analyzer.py is a created file but the decomposer
                # forgot to also list it in affected_files.
                "creates_files": ["src/analyzer.py", "tests/test_analyzer.py"],
                "expected_diff_size": "small",
                "concern_type": "runtime",
                "one_logical_step": True,
                "validation_criteria": ["VC1 [AC-1]: analyzer returns a report"],
            }
        ],
        "coverage_map": {"AC-1": "ST-001"},
    }
    blueprint_path = branch_workspace / "blueprint.json"
    blueprint_path.write_text(json.dumps(blueprint))

    # Before normalize: validator hard-stops on the subset rule.
    before = map_step_runner.validate_blueprint_contract()
    assert before["valid"] is False
    assert any(
        "creates_files" in str(e) and "affected_files" in str(e)
        for e in before["errors"]
    ), before["errors"]

    norm = map_step_runner.normalize_blueprint()
    assert norm["status"] == "ok"
    assert norm["changed"] is True
    assert norm["unioned_creates_files"] == ["ST-001:tests/test_analyzer.py"]
    assert norm["written"] is True

    # After normalize: validator passes; the created file is now in the
    # mutation surface on disk.
    after = map_step_runner.validate_blueprint_contract()
    assert after["valid"] is True, after["errors"]

    written = json.loads(blueprint_path.read_text())
    affected = written["subtasks"][0]["affected_files"]
    assert "tests/test_analyzer.py" in affected
    assert "src/analyzer.py" in affected


def test_normalize_blueprint_preserves_order_for_independent_subtasks(branch_workspace):
    blueprint = {
        "summary": "Two independent subtasks already in a valid order",
        **_blueprint_constraint_fields(),
        "subtasks": [
            {
                "id": "ST-001",
                "title": "First",
                "aag_contract": "A -> a() -> x",
                "dependencies": [],
                "affected_files": ["src/a.py"],
                "expected_diff_size": "small",
                "concern_type": "runtime",
                "one_logical_step": True,
                "validation_criteria": ["VC1 [AC-1]: a", "VC2 [INV-1]: b"],
            },
            {
                "id": "ST-002",
                "title": "Second",
                "aag_contract": "B -> b() -> y",
                "dependencies": [],
                "affected_files": ["src/b.py"],
                "expected_diff_size": "small",
                "concern_type": "runtime",
                "one_logical_step": True,
                "validation_criteria": ["VC1: standalone"],
            },
        ],
        "coverage_map": {"AC-1": "ST-001", "INV-1": "ST-001"},
    }
    (branch_workspace / "blueprint.json").write_text(json.dumps(blueprint))

    result = map_step_runner.normalize_blueprint()

    # No dependency edges to reorder and all tags present -> stable no-op.
    assert result["reordered"] is False
    assert result["changed"] is False
    assert result["subtask_order"] == ["ST-001", "ST-002"]


def test_normalize_blueprint_leaves_dependency_cycle_untouched(branch_workspace):
    blueprint = {
        "summary": "Cyclic dependencies cannot be topologically sorted",
        **_blueprint_constraint_fields(),
        "subtasks": [
            {
                "id": "ST-001",
                "title": "First",
                "aag_contract": "A -> a() -> x",
                "dependencies": ["ST-002"],
                "affected_files": ["src/a.py"],
                "expected_diff_size": "small",
                "concern_type": "runtime",
                "one_logical_step": True,
                "validation_criteria": ["VC1 [AC-1]: a"],
            },
            {
                "id": "ST-002",
                "title": "Second",
                "aag_contract": "B -> b() -> y",
                "dependencies": ["ST-001"],
                "affected_files": ["src/b.py"],
                "expected_diff_size": "small",
                "concern_type": "runtime",
                "one_logical_step": True,
                "validation_criteria": ["VC1: standalone"],
            },
        ],
        "coverage_map": {"AC-1": "ST-001"},
    }
    (branch_workspace / "blueprint.json").write_text(json.dumps(blueprint))

    result = map_step_runner.normalize_blueprint()

    assert result["reordered"] is False
    assert any("cycle" in str(note) for note in result["notes"])
    # A true cycle is left untouched for validate_blueprint_contract to reject.
    written = json.loads((branch_workspace / "blueprint.json").read_text())
    assert [s["id"] for s in written["subtasks"]] == ["ST-001", "ST-002"]


def test_normalize_blueprint_cli_check_does_not_write(tmp_path):
    blueprint_path = tmp_path / "blueprint.json"
    blueprint_path.write_text(
        json.dumps(_blueprint_with_forward_dep_and_missing_tag())
    )
    original = blueprint_path.read_text()

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_PATH / "map_step_runner.py"),
            "normalize_blueprint",
            str(blueprint_path),
            "--check",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["changed"] is True
    assert payload["written"] is False
    # --check must not mutate the file on disk.
    assert blueprint_path.read_text() == original


def test_normalize_blueprint_cli_writes_in_place(tmp_path):
    blueprint_path = tmp_path / "blueprint.json"
    blueprint_path.write_text(
        json.dumps(_blueprint_with_forward_dep_and_missing_tag())
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_PATH / "map_step_runner.py"),
            "normalize_blueprint",
            str(blueprint_path),
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(result.stdout)
    assert payload["written"] is True
    written = json.loads(blueprint_path.read_text())
    assert [s["id"] for s in written["subtasks"]] == ["ST-002", "ST-001"]


def test_acceptance_coverage_report_tracks_downstream_evidence(branch_workspace):
    blueprint = {
        "summary": "Deliver a user-visible fix",
        **_blueprint_constraint_fields(),
        "subtasks": [
            {
                "id": "ST-001",
                "title": "Fix checkout timeout message",
                "aag_contract": "CheckoutService -> handle_timeout() -> user sees retryable error",
                "dependencies": [],
                "affected_files": ["src/checkout.py"],
                "expected_diff_size": "small",
                "concern_type": "runtime",
                "one_logical_step": True,
                "validation_criteria": [
                    "VC1 [AC-1]: timeout shows retryable message",
                    "VC2 [INV-1]: retry state is not corrupted",
                ],
            }
        ],
        "coverage_map": {"AC-1": "ST-001", "INV-1": "ST-001"},
    }
    (branch_workspace / "blueprint.json").write_text(json.dumps(blueprint))
    (branch_workspace / "verification-summary.md").write_text(
        "# Verification Summary\n\n## Checks Run\npytest [AC-1]\n",
        encoding="utf-8",
    )

    result = map_step_runner.build_acceptance_coverage_report()

    assert result["status"] == "success"
    assert result["summary"] == {"total": 2, "covered": 1, "missing": 1}
    requirements = {item["id"]: item for item in result["requirements"]}
    assert requirements["AC-1"]["status"] == "covered"
    assert requirements["AC-1"]["evidence_artifacts"] == ["verification_summary"]
    assert requirements["INV-1"]["status"] == "missing_evidence"


def test_acceptance_coverage_report_ignores_planning_artifacts(branch_workspace):
    blueprint = {
        "summary": "Deliver a user-visible fix",
        **_blueprint_constraint_fields(),
        "subtasks": [
            {
                "id": "ST-001",
                "title": "Fix checkout timeout message",
                "aag_contract": "CheckoutService -> handle_timeout() -> user sees retryable error",
                "dependencies": [],
                "affected_files": ["src/checkout.py"],
                "expected_diff_size": "small",
                "concern_type": "runtime",
                "one_logical_step": True,
                "validation_criteria": ["VC1 [AC-1]: timeout shows retryable message"],
            }
        ],
        "coverage_map": {"AC-1": "ST-001"},
    }
    (branch_workspace / "blueprint.json").write_text(json.dumps(blueprint))
    (branch_workspace / "task_plan_test-branch.md").write_text(
        "# Plan\n\nPlanning mentions [AC-1] but does not prove it.\n",
        encoding="utf-8",
    )
    (branch_workspace / "plan-review-001.md").write_text(
        "# Plan Review\n\nPlan reviewer mentions [AC-1].\n",
        encoding="utf-8",
    )

    result = map_step_runner.build_acceptance_coverage_report()

    assert result["summary"] == {"total": 1, "covered": 0, "missing": 1}
    assert result["evidence_sources"] == []
    assert result["requirements"][0]["status"] == "missing_evidence"


def test_write_verification_summary_appends_acceptance_coverage(branch_workspace):
    blueprint = {
        **_blueprint_constraint_fields(),
        "subtasks": [
            {
                "id": "ST-001",
                "title": "Fix checkout timeout message",
                "aag_contract": "CheckoutService -> handle_timeout() -> user sees retryable error",
                "dependencies": [],
                "affected_files": ["src/checkout.py"],
                "expected_diff_size": "small",
                "concern_type": "runtime",
                "one_logical_step": True,
                "validation_criteria": ["VC1 [AC-1]: timeout shows retryable message"],
            }
        ],
        "coverage_map": {"AC-1": "ST-001"},
    }
    (branch_workspace / "blueprint.json").write_text(json.dumps(blueprint))

    result = map_step_runner.write_verification_summary(
        "ready",
        task_title="Checkout timeout",
        checks_run="pytest tests/test_checkout.py [AC-1]",
    )

    assert result["acceptance_coverage"]["summary"] == {
        "total": 1,
        "covered": 1,
        "missing": 0,
    }
    summary = (branch_workspace / "verification-summary.md").read_text(encoding="utf-8")
    assert "## Acceptance Coverage" in summary
    assert "Covered tags: 1/1" in summary
    assert "[covered] AC-1 owned by ST-001" in summary


def test_build_prior_stage_consumption_report_accepts_complete_inputs(branch_workspace):
    branch = "test-branch"
    (branch_workspace / f"spec_{branch}.md").write_text("# Spec\n", encoding="utf-8")
    (branch_workspace / f"task_plan_{branch}.md").write_text("# Plan\n", encoding="utf-8")
    (branch_workspace / "blueprint.json").write_text('{"subtasks":[]}', encoding="utf-8")
    (branch_workspace / "test_contract_ST-001.md").write_text("# Contract\n", encoding="utf-8")
    code_state = {
        "status": "success",
        "files_changed": ["src/app.py"],
        "diff_stat": "src/app.py | 1 +",
    }

    result = map_step_runner.build_prior_stage_consumption_report(
        "implementation", code_state=code_state
    )

    assert result["valid"] is True
    assert result["status"] == "ready"
    assert result["summary"] == {"required": 5, "consumed": 5, "missing": 0}


def test_validate_prior_stage_consumption_cli_exits_nonzero_on_missing(tmp_path):
    branch_dir = tmp_path / ".map" / "default"
    branch_dir.mkdir(parents=True)

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_PATH / "map_step_runner.py"),
            "validate_prior_stage_consumption",
            "review",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["valid"] is False
    assert "missing required artifact" in "\n".join(payload["errors"])


def test_validate_blueprint_contract_rejects_non_noticeable_plumbing_slice(
    branch_workspace,
):
    blueprint = {
        **_blueprint_constraint_fields(),
        "subtasks": [
            {
                "id": "ST-001",
                "title": "Add dormant helper",
                "dependencies": [],
                "affected_files": ["src/helper.py"],
                "expected_diff_size": "large",
                "concern_type": "mixed",
                "one_logical_step": False,
                "validation_criteria": [],
            }
        ],
        "coverage_map": {"AC-1": "ST-999"},
    }
    (branch_workspace / "blueprint.json").write_text(json.dumps(blueprint))

    result = map_step_runner.validate_blueprint_contract()

    assert result["valid"] is False
    joined_errors = "\n".join(result["errors"])
    assert "large subtasks require split_rationale" in joined_errors
    assert "mixed concern_type requires concern_justification" in joined_errors
    assert "one_logical_step must be true" in joined_errors
    assert "missing aag_contract" in joined_errors
    assert "validation_criteria must contain at least one item" in joined_errors
    assert "unknown subtask" in joined_errors


def test_validate_blueprint_contract_accepts_nested_decomposer_blueprint(
    branch_workspace,
):
    blueprint = {
        "schema_version": "2.0",
        "blueprint": {
            "summary": "Deliver a user-visible fix",
            **_blueprint_constraint_fields(),
            "coverage_map": {"AC-1": "ST-001"},
            "subtasks": [
                {
                    "id": "ST-001",
                    "title": "Fix checkout timeout message",
                    "aag_contract": "CheckoutService -> handle_timeout() -> user sees retryable error",
                    "dependencies": [],
                    "affected_files": ["src/checkout.py"],
                    "expected_diff_size": "small",
                    "concern_type": "runtime",
                    "one_logical_step": True,
                    "validation_criteria": ["VC1 [AC-1]: timeout shows retryable message"],
                }
            ],
        },
    }
    (branch_workspace / "blueprint.json").write_text(json.dumps(blueprint))

    result = map_step_runner.validate_blueprint_contract()

    assert result["valid"] is True


def test_validate_blueprint_contract_rejects_missing_or_invalid_subtask_id(
    branch_workspace,
):
    blueprint = {
        **_blueprint_constraint_fields(),
        "subtasks": [
            {
                "title": "Missing ID",
                "aag_contract": "Service -> do() -> done",
                "dependencies": [],
                "affected_files": [],
                "expected_diff_size": "small",
                "concern_type": "runtime",
                "one_logical_step": True,
                "validation_criteria": ["VC1 [AC-1]: check"],
            }
        ],
        "coverage_map": {"AC-1": "subtasks[0]"},
    }
    (branch_workspace / "blueprint.json").write_text(json.dumps(blueprint))

    result = map_step_runner.validate_blueprint_contract()

    assert result["valid"] is False
    assert any("id must match ST-NNN" in error for error in result["errors"])


def test_validate_blueprint_contract_rejects_non_string_coverage_owner(
    branch_workspace,
):
    blueprint = {
        **_blueprint_constraint_fields(),
        "subtasks": [
            {
                "id": "ST-001",
                "title": "Fix checkout timeout message",
                "aag_contract": "CheckoutService -> handle_timeout() -> user sees retryable error",
                "dependencies": [],
                "affected_files": ["src/checkout.py"],
                "expected_diff_size": "small",
                "concern_type": "runtime",
                "one_logical_step": True,
                "validation_criteria": ["VC1 [AC-1]: timeout shows retryable message"],
            }
        ],
        "coverage_map": {"AC-1": ["ST-001"]},
    }
    (branch_workspace / "blueprint.json").write_text(json.dumps(blueprint))

    result = map_step_runner.validate_blueprint_contract()

    assert result["valid"] is False
    assert any("must point to a single ST-NNN" in error for error in result["errors"])


def test_validate_blueprint_contract_requires_criteria_requirement_tags(
    branch_workspace,
):
    blueprint = {
        **_blueprint_constraint_fields(),
        "subtasks": [
            {
                "id": "ST-001",
                "title": "Fix checkout timeout message",
                "aag_contract": "CheckoutService -> handle_timeout() -> user sees retryable error",
                "dependencies": [],
                "affected_files": ["src/checkout.py"],
                "expected_diff_size": "small",
                "concern_type": "runtime",
                "one_logical_step": True,
                "validation_criteria": ["VC1: timeout shows retryable message"],
            }
        ],
        "coverage_map": {"AC-1": "ST-001"},
    }
    (branch_workspace / "blueprint.json").write_text(json.dumps(blueprint))

    result = map_step_runner.validate_blueprint_contract()

    assert result["valid"] is False
    assert any("must cite coverage_map requirement 'AC-1' as [AC-1]" in error for error in result["errors"])


def test_validate_blueprint_contract_requires_validation_criteria(branch_workspace):
    blueprint = {
        **_blueprint_constraint_fields(),
        "subtasks": [
            {
                "id": "ST-001",
                "title": "Fix checkout timeout message",
                "aag_contract": "CheckoutService -> handle_timeout() -> user sees retryable error",
                "dependencies": [],
                "affected_files": ["src/checkout.py"],
                "expected_diff_size": "small",
                "concern_type": "runtime",
                "one_logical_step": True,
                "acceptance_criteria": ["AC1: timeout shows retryable message"],
            }
        ],
        "coverage_map": {"AC-1": "ST-001"},
    }
    (branch_workspace / "blueprint.json").write_text(json.dumps(blueprint))

    result = map_step_runner.validate_blueprint_contract()

    assert result["valid"] is False
    assert any("validation_criteria must contain" in error for error in result["errors"])


def test_validate_blueprint_contract_rejects_duplicate_subtask_ids(branch_workspace):
    subtask = {
        "id": "ST-001",
        "title": "Fix checkout timeout message",
        "aag_contract": "CheckoutService -> handle_timeout() -> user sees retryable error",
        "dependencies": [],
        "affected_files": ["src/checkout.py"],
        "expected_diff_size": "small",
        "concern_type": "runtime",
        "one_logical_step": True,
        "validation_criteria": ["VC1 [AC-1]: timeout shows retryable message"],
    }
    blueprint = {
        **_blueprint_constraint_fields(),
        "subtasks": [subtask, {**subtask, "title": "Duplicate timeout fix"}],
        "coverage_map": {"AC-1": "ST-001"},
    }
    (branch_workspace / "blueprint.json").write_text(json.dumps(blueprint))

    result = map_step_runner.validate_blueprint_contract()

    assert result["valid"] is False
    assert any("duplicate subtask id" in error for error in result["errors"])


def test_validate_blueprint_contract_rejects_unknown_dependencies(branch_workspace):
    blueprint = {
        **_blueprint_constraint_fields(),
        "subtasks": [
            {
                "id": "ST-001",
                "title": "Fix checkout timeout message",
                "aag_contract": "CheckoutService -> handle_timeout() -> user sees retryable error",
                "dependencies": ["ST-999"],
                "affected_files": ["src/checkout.py"],
                "expected_diff_size": "small",
                "concern_type": "runtime",
                "one_logical_step": True,
                "validation_criteria": ["VC1 [AC-1]: timeout shows retryable message"],
            }
        ],
        "coverage_map": {"AC-1": "ST-001"},
    }
    (branch_workspace / "blueprint.json").write_text(json.dumps(blueprint))

    result = map_step_runner.validate_blueprint_contract()

    assert result["valid"] is False
    assert any("dependency 'ST-999' points to unknown subtask" in error for error in result["errors"])


def test_validate_blueprint_contract_requires_hard_constraint_coverage(
    branch_workspace,
):
    blueprint = {
        **_blueprint_constraint_fields(),
        "hard_constraints": [
            {"id": "HC-1", "description": "Persisted state must survive compaction"},
        ],
        "subtasks": [
            {
                "id": "ST-001",
                "title": "Fix checkout timeout message",
                "aag_contract": "CheckoutService -> handle_timeout() -> user sees retryable error",
                "dependencies": [],
                "affected_files": ["src/checkout.py"],
                "expected_diff_size": "small",
                "concern_type": "runtime",
                "one_logical_step": True,
                "validation_criteria": ["VC1 [AC-1]: timeout shows retryable message"],
            }
        ],
        "coverage_map": {"AC-1": "ST-001"},
    }
    (branch_workspace / "blueprint.json").write_text(json.dumps(blueprint))

    result = map_step_runner.validate_blueprint_contract()

    assert result["valid"] is False
    assert any("hard_constraints requirement 'HC-1' must appear in coverage_map" in error for error in result["errors"])


def test_validate_blueprint_contract_accepts_soft_constraint_tradeoff(
    branch_workspace,
):
    blueprint = {
        "hard_constraints": [
            {"id": "AC-1", "description": "Timeouts must show a retryable message"},
        ],
        "soft_constraints": [
            {
                "id": "SC-1",
                "description": "Prefer preserving existing wording",
                "tradeoff_rationale": "New wording is clearer for the retry action",
            },
        ],
        "subtasks": [
            {
                "id": "ST-001",
                "title": "Fix checkout timeout message",
                "aag_contract": "CheckoutService -> handle_timeout() -> user sees retryable error",
                "dependencies": [],
                "affected_files": ["src/checkout.py"],
                "expected_diff_size": "small",
                "concern_type": "runtime",
                "one_logical_step": True,
                "validation_criteria": ["VC1 [AC-1]: timeout shows retryable message"],
            }
        ],
        "coverage_map": {"AC-1": "ST-001"},
    }
    (branch_workspace / "blueprint.json").write_text(json.dumps(blueprint))

    result = map_step_runner.validate_blueprint_contract()

    assert result["valid"] is True


def test_validate_blueprint_contract_rejects_unexplained_soft_constraint_tradeoff(
    branch_workspace,
):
    blueprint = {
        **_blueprint_constraint_fields(),
        "soft_constraints": [
            {"id": "SC-1", "description": "Prefer preserving existing wording"},
        ],
        "subtasks": [
            {
                "id": "ST-001",
                "title": "Fix checkout timeout message",
                "aag_contract": "CheckoutService -> handle_timeout() -> user sees retryable error",
                "dependencies": [],
                "affected_files": ["src/checkout.py"],
                "expected_diff_size": "small",
                "concern_type": "runtime",
                "one_logical_step": True,
                "validation_criteria": ["VC1 [AC-1]: timeout shows retryable message"],
            }
        ],
        "coverage_map": {"AC-1": "ST-001"},
    }
    (branch_workspace / "blueprint.json").write_text(json.dumps(blueprint))

    result = map_step_runner.validate_blueprint_contract()

    assert result["valid"] is False
    # 2026-05-26: error text rewritten to disclose both branches up front
    # (path a = tradeoff_rationale, path b = coverage_map + [SC-N] tag)
    # so operators don't have to round-trip the validator twice.
    assert any(
        "soft_constraints requirement 'SC-1' must either" in error
        and "tradeoff_rationale" in error
        and "[SC-1]" in error
        for error in result["errors"]
    ), result["errors"]


def test_record_test_contract_handoff_creates_json_and_manifest(branch_workspace):
    (branch_workspace / "test_contract_ST-001.md").write_text(
        "# Test Contract\n", encoding="utf-8"
    )

    result = map_step_runner.record_test_contract_handoff(
        "ST-001",
        "pytest tests/test_auth.py -q",
        "tests/test_auth.py,tests/test_api.py",
        "Lock auth behavior before code generation",
        "Resume with /map-task",
    )

    assert result["status"] == "success"
    handoff = json.loads((branch_workspace / "test_handoff_ST-001.json").read_text())
    assert handoff["status"] == "contract_ready"
    assert handoff["subtask_id"] == "ST-001"
    assert handoff["test_files"] == ["tests/test_auth.py", "tests/test_api.py"]
    assert handoff["updated_at"].endswith("Z")

    manifest = json.loads((branch_workspace / "artifact_manifest.json").read_text())
    stage = manifest["stages"]["test_contract"]
    assert stage["status"] == "contract_ready"
    assert stage["metadata"]["subtask_id"] == "ST-001"
    assert manifest["updated_at"].endswith("Z")
    assert stage["updated_at"].endswith("Z")


def test_load_artifact_manifest_normalizes_branch_name(branch_workspace):
    (branch_workspace / "artifact_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "branch": "wrong-branch",
                "updated_at": "2026-04-12T00:00:00Z",
                "stages": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    manifest = map_step_runner.load_artifact_manifest()

    assert manifest["branch"] == branch_workspace.name


def test_build_handoff_bundle_reads_artifacts(branch_workspace):
    """Build handoff bundle reads available artifacts."""
    (branch_workspace / "verification-summary.md").write_text(
        "# Verification Summary\n\n- Verdict: READY FOR REVIEW\n",
        encoding="utf-8",
    )
    (branch_workspace / "qa-001.md").write_text(
        "# QA 001\n\n- Commands Run: pytest\n",
        encoding="utf-8",
    )
    (branch_workspace / "code-review-001.md").write_text(
        "# Code Review 001\n\n- follow up on edge case\n",
        encoding="utf-8",
    )

    result = map_step_runner.build_handoff_bundle()

    assert result["status"] == "success"
    assert "Verification summary available" in result["summary"]
    assert "READY FOR REVIEW" in result["validation"]
    assert "follow up on edge case" in result["risks_follow_up"]


def test_build_handoff_bundle_ignores_placeholder_human_artifacts(branch_workspace):
    del branch_workspace  # fixture only needed for chdir + monkeypatch side effects
    result = map_step_runner.build_handoff_bundle()

    assert result["status"] == "success"
    assert result["summary"] == "- [not recorded]"
    assert result["validation"] == "- [not recorded]"
    assert result["risks_follow_up"] == "- [not recorded]"


def test_write_learning_handoff_creates_artifacts_and_manifest(branch_workspace):
    (branch_workspace / "verification-summary.md").write_text(
        "# Verification Summary\n\n- Verdict: READY FOR REVIEW\n",
        encoding="utf-8",
    )
    (branch_workspace / "qa-001.md").write_text(
        "# QA 001\n\n- Commands Run: pytest\n",
        encoding="utf-8",
    )
    (branch_workspace / "code-review-001.md").write_text(
        "# Code Review 001\n\n- follow up on edge case\n",
        encoding="utf-8",
    )
    (branch_workspace / "workflow-fit.json").write_text(
        json.dumps({"recommended_workflow": "map-efficient"}) + "\n",
        encoding="utf-8",
    )
    (branch_workspace / "run_health_report.json").write_text(
        json.dumps({"terminal_status": "complete"}) + "\n",
        encoding="utf-8",
    )

    result = map_step_runner.write_learning_handoff(
        "map-check",
        "Implement auth",
        "READY FOR REVIEW",
        "Run /map-review next",
        "Capture auth lessons after review.",
    )

    assert result["status"] == "success"
    markdown = (branch_workspace / "learning-handoff.md").read_text(encoding="utf-8")
    assert "Run `/map-learn` with no arguments" in markdown
    assert "Implement auth" in markdown
    assert "READY FOR REVIEW" in markdown
    assert "artifact_manifest.json" in markdown

    payload = json.loads((branch_workspace / "learning-handoff.json").read_text())
    assert payload["workflow"] == "map-check"
    assert payload["task_title"] == "Implement auth"
    assert payload["outcome"] == "READY FOR REVIEW"
    assert (
        payload["artifacts"]["artifact_manifest"]["stages"]["learn_handoff"]["status"]
        == "ready"
    )
    assert payload["artifacts"]["run_health_report"]["terminal_status"] == "complete"
    assert (
        payload["artifacts"]["learning_metrics"]["counters"]["handoff_generated_count"]
        == 1
    )

    metrics = json.loads((branch_workspace / "learning-metrics.json").read_text())
    assert metrics["counters"]["handoff_generated_count"] == 1
    assert metrics["counters"]["pending_handoff_count"] == 1
    assert metrics["current_handoff"]["workflow"] == "map-check"

    manifest = json.loads((branch_workspace / "artifact_manifest.json").read_text())
    stage = manifest["stages"]["learn_handoff"]
    assert stage["status"] == "ready"
    recorded_paths = {artifact["path"] for artifact in stage["artifacts"]}
    assert f".map/{branch_workspace.name}/learning-handoff.md" in recorded_paths
    assert f".map/{branch_workspace.name}/learning-handoff.json" in recorded_paths
    assert f".map/{branch_workspace.name}/learning-metrics.json" in recorded_paths
    assert (
        stage["metadata"]["learning_metrics_counters"]["handoff_generated_count"] == 1
    )

    event_log = (
        Path(".claude/metrics/agent_metrics.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert any("learning_handoff_generated" in line for line in event_log)


def test_write_learning_handoff_marks_replaced_pending_handoff_as_never_used(
    branch_workspace,
):
    first = map_step_runner.write_learning_handoff(
        "map-check",
        "First task",
        "READY FOR REVIEW",
        "Run /map-review next",
    )
    second = map_step_runner.write_learning_handoff(
        "map-review",
        "Second task",
        "READY FOR LEARN",
        "Run /map-learn next",
    )

    assert first["status"] == "success"
    assert second["status"] == "success"

    metrics = json.loads((branch_workspace / "learning-metrics.json").read_text())
    assert metrics["counters"]["handoff_generated_count"] == 2
    assert metrics["counters"]["never_used_handoff_count"] == 1
    assert metrics["counters"]["pending_handoff_count"] == 1
    assert metrics["current_handoff"]["workflow"] == "map-review"
    event_names = [event["event"] for event in metrics["events"]]
    assert "learning_handoff_abandoned" in event_names
    assert event_names.count("learning_handoff_generated") == 2


def test_record_learning_consumption_records_immediate_usage_and_reuse(
    branch_workspace,
):
    map_step_runner.write_learning_handoff(
        "map-efficient",
        "Auth workflow",
        "READY FOR REVIEW",
        "Run /map-review next",
    )

    result = map_step_runner.record_learning_consumption("auto-handoff")

    assert result["status"] == "success"
    assert result["usage_status"] == "recorded"
    assert result["workflow"] == "map-efficient"
    assert result["consumption_mode"] == "immediate"

    metrics = json.loads((branch_workspace / "learning-metrics.json").read_text())
    assert metrics["counters"]["handoff_generated_count"] == 1
    assert metrics["counters"]["handoff_consumed_count"] == 1
    assert metrics["counters"]["immediate_learn_count"] == 1
    assert metrics["counters"]["pending_handoff_count"] == 0
    assert metrics["current_handoff"]["consumption_source"] == "auto-handoff"
    assert metrics["current_handoff"]["consumption_mode"] == "immediate"
    assert metrics["current_handoff"]["consumed_at"]

    second = map_step_runner.record_learning_consumption("auto-handoff")

    assert second["status"] == "success"
    assert second["usage_status"] == "already_recorded"

    metrics_after_reuse = json.loads(
        (branch_workspace / "learning-metrics.json").read_text()
    )
    assert metrics_after_reuse["counters"]["handoff_consumed_count"] == 1
    assert metrics_after_reuse["counters"]["immediate_learn_count"] == 1
    assert metrics_after_reuse["counters"]["pending_handoff_count"] == 0


def test_record_learning_consumption_tracks_inline_summaries(branch_workspace):
    result = map_step_runner.record_learning_consumption("inline-summary", "map-fast")

    assert result["status"] == "success"
    assert result["usage_status"] == "manual_summary"
    assert result["workflow"] == "map-fast"

    metrics = json.loads((branch_workspace / "learning-metrics.json").read_text())
    assert metrics["counters"]["manual_summary_count"] == 1
    assert metrics["counters"]["pending_handoff_count"] == 0
    assert metrics["events"][-1]["event"] == "learning_manual_summary_recorded"


def test_write_learning_handoff_records_repeated_rule_violations(branch_workspace):
    learned_rules_dir = Path(".claude/rules/learned")
    learned_rules_dir.mkdir(parents=True)
    (learned_rules_dir / "implementation-patterns.md").write_text(
        "---\n"
        "paths:\n"
        '  - "**/*.py"\n'
        "---\n\n"
        "# Implementation Patterns (Learned)\n\n"
        "- **Validation Functions Must Return None on Invalid** (2026-04-12): "
        "When validation functions receive invalid input, return None because "
        "callers rely on None as the failure signal. [workflow: map-learn]\n",
        encoding="utf-8",
    )
    (branch_workspace / "active-issues.json").write_text(
        json.dumps(
            {
                "updated_at": "2026-04-13T08:00:00Z",
                "issues": [
                    {
                        "id": "VER-001",
                        "stage": "verification",
                        "source_artifact": "verification-summary.md",
                        "status": "open",
                        "summary": "src/service.py:12 validation function returned data on invalid input",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = map_step_runner.write_learning_handoff(
        "map-check",
        "Auth validation",
        "NEEDS WORK",
        "Fix the validation contract",
    )

    assert result["status"] == "success"
    payload = json.loads((branch_workspace / "learning-handoff.json").read_text())
    repeated = payload["artifacts"]["repeated_violation_summary"]
    assert repeated["finding_count"] == 1
    assert repeated["matched_count"] == 1
    assert (
        repeated["matches"][0]["rule_title"]
        == "Validation Functions Must Return None on Invalid"
    )
    assert repeated["matches"][0]["path_match"] is True

    metrics = json.loads((branch_workspace / "learning-metrics.json").read_text())
    assert metrics["counters"]["repeated_violation_scan_count"] == 1
    assert metrics["counters"]["repeated_violation_match_count"] == 1
    assert metrics["events"][-1]["event"] == "learning_repeated_violation_detected"

    markdown = (branch_workspace / "learning-handoff.md").read_text(encoding="utf-8")
    assert "Learning Effectiveness Signals" in markdown
    assert "Validation Functions Must Return None on Invalid" in markdown


def test_write_learning_handoff_leaves_repeated_violation_summary_empty_on_non_match(
    branch_workspace,
):
    learned_rules_dir = Path(".claude/rules/learned")
    learned_rules_dir.mkdir(parents=True)
    (learned_rules_dir / "error-patterns.md").write_text(
        "# Error Patterns (Learned)\n\n"
        "- **Idempotent File Backups Need Timestamps** (2026-04-12): "
        "When creating backups, use timestamps so repeated upgrades do not overwrite "
        "customizations. [workflow: map-learn]\n",
        encoding="utf-8",
    )
    (branch_workspace / "active-issues.json").write_text(
        json.dumps(
            {
                "updated_at": "2026-04-13T08:00:00Z",
                "issues": [
                    {
                        "id": "VER-001",
                        "stage": "verification",
                        "source_artifact": "verification-summary.md",
                        "status": "open",
                        "summary": "OAuth callback misses CSRF state verification",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = map_step_runner.write_learning_handoff(
        "map-review",
        "OAuth review",
        "NEEDS WORK",
        "Add CSRF protection",
    )

    assert result["status"] == "success"
    payload = json.loads((branch_workspace / "learning-handoff.json").read_text())
    repeated = payload["artifacts"]["repeated_violation_summary"]
    assert repeated["finding_count"] == 1
    assert repeated["matched_count"] == 0
    assert repeated["matches"] == []

    metrics = json.loads((branch_workspace / "learning-metrics.json").read_text())
    assert metrics["counters"]["repeated_violation_scan_count"] == 1
    assert metrics["counters"]["repeated_violation_match_count"] == 0

    event_log = Path(".claude/metrics/agent_metrics.jsonl").read_text(encoding="utf-8")
    assert "learning_repeated_violation_detected" not in event_log


def test_map_step_runner_cli_write_learning_handoff_records_repeated_violation_smoke(
    tmp_path,
):
    (tmp_path / ".map" / "default").mkdir(parents=True)
    learned_rules_dir = tmp_path / ".claude" / "rules" / "learned"
    learned_rules_dir.mkdir(parents=True)
    (learned_rules_dir / "implementation-patterns.md").write_text(
        "# Implementation Patterns (Learned)\n\n"
        "- **Validation Functions Must Return None on Invalid** (2026-04-12): "
        "When validation functions receive invalid input, return None because "
        "callers rely on None as the failure signal. [workflow: map-learn]\n",
        encoding="utf-8",
    )
    (tmp_path / ".map" / "default" / "active-issues.json").write_text(
        json.dumps(
            {
                "updated_at": "2026-04-13T08:00:00Z",
                "issues": [
                    {
                        "id": "VER-001",
                        "stage": "verification",
                        "source_artifact": "verification-summary.md",
                        "status": "open",
                        "summary": "validation function returned data on invalid input",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_PATH / "map_step_runner.py"),
            "write_learning_handoff",
            "map-check",
            "CLI smoke task",
            "NEEDS WORK",
            "Fix validation handling",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(result.stdout)
    assert payload["status"] == "success"
    handoff = json.loads((tmp_path / payload["json_path"]).read_text())
    assert handoff["artifacts"]["repeated_violation_summary"]["matched_count"] == 1


def test_classify_learning_consumption_mode_distinguishes_immediate_vs_deferred():
    assert (
        map_step_runner._classify_learning_consumption_mode(
            "2026-04-12T10:00:00Z", "2026-04-12T10:10:00Z"
        )
        == "immediate"
    )
    assert (
        map_step_runner._classify_learning_consumption_mode(
            "2026-04-12T10:00:00Z", "2026-04-12T10:45:00Z"
        )
        == "deferred"
    )
    assert (
        map_step_runner._classify_learning_consumption_mode(
            "bad", "2026-04-12T10:45:00Z"
        )
        == "deferred"
    )


def test_write_plan_review_creates_numbered_artifact(branch_workspace):
    result = map_step_runner.write_plan_review(
        "Planning looks solid overall",
        "(None)",
        "- PR-001 Clarify retry policy",
        "(None)",
        "(None)",
        "- PR-001 Clarify retry policy",
        "needs-revision",
    )

    assert result["status"] == "success"
    content = (branch_workspace / "plan-review-001.md").read_text(encoding="utf-8")
    assert "Plan Review 001" in content
    assert "PR-001 Clarify retry policy" in content
    assert "needs-revision" in content


def test_write_stage_gate_creates_plan_gate(branch_workspace):
    result = map_step_runner.write_stage_gate(
        "plan", "ready", "plan-review-001.md", "Planning approved"
    )

    assert result["status"] == "success"
    content = (branch_workspace / "plan-gate.json").read_text(encoding="utf-8")
    assert '"verdict": "ready"' in content
    assert '"source_artifact": "plan-review-001.md"' in content


def test_active_issues_file_replace(branch_workspace):
    ensure = map_step_runner.ensure_active_issues_file()
    assert ensure["status"] == "success"

    result = map_step_runner.replace_active_issues(
        "verification",
        "verification-summary.md",
        "- fix flaky auth test\n- clarify migration rollback",
    )
    assert result["status"] == "success"

    content = (branch_workspace / "active-issues.json").read_text(encoding="utf-8")
    assert '"stage": "verification"' in content
    assert "fix flaky auth test" in content
    assert "clarify migration rollback" in content


def test_build_review_handoff_collects_branch_artifacts(branch_workspace):
    (branch_workspace / "plan-review-001.md").write_text(
        "# Plan Review 001\n\n- PR-001 tighten scope\n", encoding="utf-8"
    )
    (branch_workspace / "code-review-001.md").write_text(
        "# Code Review 001\n\n- CR-001 add null guard\n", encoding="utf-8"
    )
    (branch_workspace / "verification-summary.md").write_text(
        "# Verification Summary\n\n- Verdict: READY FOR REVIEW\n",
        encoding="utf-8",
    )
    (branch_workspace / "qa-001.md").write_text("# QA 001\n", encoding="utf-8")
    (branch_workspace / "pr-draft.md").write_text(
        "# PR Draft\n\n## Summary\n", encoding="utf-8"
    )
    (branch_workspace / "active-issues.json").write_text(
        '{"updated_at":"2026-03-19T00:00:00","issues":[{"id":"VER-001"}]}\n',
        encoding="utf-8",
    )

    result = map_step_runner.build_review_handoff()

    assert result["status"] == "success"
    assert result["plan_review_path"] == "plan-review-001.md"
    assert result["code_review_path"] == "code-review-001.md"
    assert result["verification_summary_path"] == "verification-summary.md"
    assert result["active_issues_path"] == "active-issues.json"


def test_known_issues_file_and_add_issue(branch_workspace):
    result = map_step_runner.ensure_known_issues_file()
    assert result["status"] == "success"

    add_result = map_step_runner.add_known_issue(
        "Flaky integration test", "accepted", "Track in follow-up"
    )
    assert add_result["status"] == "success"

    content = (branch_workspace / "known-issues.json").read_text(encoding="utf-8")
    assert "Flaky integration test" in content
    assert "accepted" in content


# ---------------------------------------------------------------------------
# append_session_log — deprecation stub test
# ---------------------------------------------------------------------------


class TestAppendSessionLog:
    """Focused tests for append_session_log deprecation stub."""

    def test_returns_deprecated_status(self, branch_workspace):
        """Deprecated function returns correct status and flag."""
        del branch_workspace  # fixture only needed for chdir + monkeypatch side effects
        result = map_step_runner.append_session_log("ACTOR", "success")

        assert result["status"] == "deprecated"
        assert result["deprecated"] is True
        assert result["path"] == ""

    def test_accepts_all_arguments_without_error(self, branch_workspace):
        """All original arguments are accepted (backward compat) even though ignored."""
        del branch_workspace  # fixture only needed for chdir + monkeypatch side effects
        result = map_step_runner.append_session_log(
            "MONITOR", "passed", "ST-001", "details", ["ref1", "ref2"]
        )

        assert result["status"] == "deprecated"


# ---------------------------------------------------------------------------
# write_stage_gate — focused unit tests
# ---------------------------------------------------------------------------


class TestWriteStageGate:
    """Focused tests for write_stage_gate."""

    def test_happy_path_creates_gate_file(self, branch_workspace):
        """Valid verdict creates {stage}-gate.json with correct JSON fields."""
        result = map_step_runner.write_stage_gate(
            "plan", "ready", "plan-review-001.md", "All good"
        )

        assert result["status"] == "success"
        gate_file = branch_workspace / "plan-gate.json"
        assert gate_file.exists()
        data = json.loads(gate_file.read_text(encoding="utf-8"))
        assert data["stage"] == "plan"
        assert data["verdict"] == "ready"
        assert data["source_artifact"] == "plan-review-001.md"
        assert data["notes"] == "All good"
        assert "updated_at" in data

    def test_invalid_verdict_returns_error(self, branch_workspace):
        """An unrecognised verdict returns an error dict without creating a file."""
        result = map_step_runner.write_stage_gate(
            "plan", "approved", "plan-review-001.md"
        )

        assert result["status"] == "error"
        assert "Invalid verdict" in result["message"]
        assert not (branch_workspace / "plan-gate.json").exists()

    def test_stage_name_normalised(self, branch_workspace):
        """Underscores in stage name are replaced with hyphens in file name."""
        result = map_step_runner.write_stage_gate("code_review", "ready")

        assert result["status"] == "success"
        assert (branch_workspace / "code-review-gate.json").exists()

    def test_all_valid_verdicts_accepted(self, branch_workspace):
        """All three GATE_VERDICTS are accepted without error."""
        del branch_workspace  # fixture only needed for chdir + monkeypatch side effects
        for verdict in ("ready", "needs-revision", "blocked"):
            res = map_step_runner.write_stage_gate(f"stage-{verdict}", verdict)
            assert (
                res["status"] == "success"
            ), f"Expected success for verdict={verdict!r}"

    def test_source_artifact_optional(self, branch_workspace):
        """Omitting source_artifact stores None in the JSON payload."""
        map_step_runner.write_stage_gate("plan", "ready")
        data = json.loads(
            (branch_workspace / "plan-gate.json").read_text(encoding="utf-8")
        )
        assert data["source_artifact"] is None

    def test_branch_parameter_respected(self, tmp_path, monkeypatch):
        """Passing an explicit branch writes to that branch's directory."""
        other_branch = "other-branch"
        other_dir = tmp_path / ".map" / other_branch
        other_dir.mkdir(parents=True)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(map_step_runner, "get_branch_name", lambda: "wrong-branch")

        result = map_step_runner.write_stage_gate("plan", "ready", branch=other_branch)

        assert result["status"] == "success"
        assert (other_dir / "plan-gate.json").exists()


# ---------------------------------------------------------------------------
# ensure_active_issues_file — focused unit tests
# ---------------------------------------------------------------------------


class TestEnsureActiveIssuesFile:
    """Focused tests for ensure_active_issues_file."""

    def test_happy_path_creates_file_when_missing(self, branch_workspace):
        """Creates active-issues.json and returns created=True when file absent."""
        result = map_step_runner.ensure_active_issues_file()

        assert result["status"] == "success"
        assert result["created"] is True
        issues_file = branch_workspace / "active-issues.json"
        assert issues_file.exists()
        data = json.loads(issues_file.read_text(encoding="utf-8"))
        assert "issues" in data
        assert isinstance(data["issues"], list)

    def test_returns_created_false_when_file_exists(self, branch_workspace):
        """Returns created=False when active-issues.json already present."""
        del branch_workspace  # fixture only needed for chdir + monkeypatch side effects
        # Create the file first
        map_step_runner.ensure_active_issues_file()

        result = map_step_runner.ensure_active_issues_file()

        assert result["status"] == "success"
        assert result["created"] is False

    def test_existing_file_content_not_overwritten(self, branch_workspace):
        """Pre-existing file content is preserved on second call."""
        issues_file = branch_workspace / "active-issues.json"
        custom_content = '{"updated_at": "2026-01-01", "issues": [{"id": "VER-001"}]}\n'
        issues_file.write_text(custom_content, encoding="utf-8")

        map_step_runner.ensure_active_issues_file()

        assert issues_file.read_text(encoding="utf-8") == custom_content


# ---------------------------------------------------------------------------
# replace_active_issues — focused unit tests
# ---------------------------------------------------------------------------


class TestReplaceActiveIssues:
    """Focused tests for replace_active_issues."""

    def test_happy_path_parses_bullet_lines(self, branch_workspace):
        """Bullet-prefixed lines become structured issue entries."""
        result = map_step_runner.replace_active_issues(
            "verification",
            "verification-summary.md",
            "- fix flaky auth test\n- update migration script",
        )

        assert result["status"] == "success"
        assert result["count"] == 2
        data = json.loads(
            (branch_workspace / "active-issues.json").read_text(encoding="utf-8")
        )
        ids = [issue["id"] for issue in data["issues"]]
        assert "VER-001" in ids
        assert "VER-002" in ids
        summaries = [issue["summary"] for issue in data["issues"]]
        assert "fix flaky auth test" in summaries

    def test_none_sentinel_produces_empty_issues(self, branch_workspace):
        """A single '(None)' line results in an empty issues list."""
        result = map_step_runner.replace_active_issues(
            "verification", "verification-summary.md", "(None)"
        )

        assert result["status"] == "success"
        assert result["count"] == 0
        data = json.loads(
            (branch_workspace / "active-issues.json").read_text(encoding="utf-8")
        )
        assert data["issues"] == []

    def test_issue_id_format_uses_stage_prefix(self, branch_workspace):
        """IDs use the first 3 uppercase chars of the stage name."""
        map_step_runner.replace_active_issues(
            "plan", "plan-review-001.md", "- missing acceptance criteria"
        )

        data = json.loads(
            (branch_workspace / "active-issues.json").read_text(encoding="utf-8")
        )
        assert data["issues"][0]["id"] == "PLA-001"

    def test_empty_issues_text_produces_empty_list(self, branch_workspace):
        """Completely empty issues_text results in zero issues."""
        del branch_workspace  # fixture only needed for chdir + monkeypatch side effects
        result = map_step_runner.replace_active_issues("code", "code-review-001.md", "")

        assert result["count"] == 0

    def test_replaces_previous_issues(self, branch_workspace):
        """Calling replace twice overwrites the old issues entirely."""
        map_step_runner.replace_active_issues(
            "plan", "plan-review-001.md", "- first issue"
        )
        map_step_runner.replace_active_issues(
            "plan", "plan-review-002.md", "- second issue"
        )

        data = json.loads(
            (branch_workspace / "active-issues.json").read_text(encoding="utf-8")
        )
        assert len(data["issues"]) == 1
        assert data["issues"][0]["summary"] == "second issue"


# ---------------------------------------------------------------------------
# build_review_handoff — focused unit tests
# ---------------------------------------------------------------------------


class TestBuildReviewHandoff:
    """Focused tests for build_review_handoff."""

    def test_happy_path_returns_all_paths(self, branch_workspace):
        """Returns paths for all artifacts when they exist."""
        (branch_workspace / "plan-review-001.md").write_text(
            "# Plan Review 001\n", encoding="utf-8"
        )
        (branch_workspace / "code-review-001.md").write_text(
            "# Code Review 001\n", encoding="utf-8"
        )
        (branch_workspace / "verification-summary.md").write_text(
            "# VS\n", encoding="utf-8"
        )
        (branch_workspace / "active-issues.json").write_text(
            '{"issues": []}\n', encoding="utf-8"
        )

        result = map_step_runner.build_review_handoff()

        assert result["status"] == "success"
        assert result["plan_review_path"] == "plan-review-001.md"
        assert result["code_review_path"] == "code-review-001.md"
        assert result["verification_summary_path"] == "verification-summary.md"
        assert result["active_issues_path"] == "active-issues.json"

    def test_returns_none_paths_when_no_artifacts(self, branch_workspace):
        """Returns None for paths when no numbered artifacts exist."""
        del branch_workspace  # fixture only needed for chdir + monkeypatch side effects
        result = map_step_runner.build_review_handoff()

        assert result["status"] == "success"
        assert result["plan_review_path"] is None
        assert result["code_review_path"] is None

    def test_returns_highest_numbered_review(self, branch_workspace):
        """With multiple code-review files, returns the highest-numbered one."""
        (branch_workspace / "code-review-001.md").write_text(
            "Review 1\n", encoding="utf-8"
        )
        (branch_workspace / "code-review-002.md").write_text(
            "Review 2\n", encoding="utf-8"
        )
        (branch_workspace / "code-review-003.md").write_text(
            "Review 3\n", encoding="utf-8"
        )

        result = map_step_runner.build_review_handoff()

        assert result["code_review_path"] == "code-review-003.md"

    def test_verification_summary_none_when_absent(self, branch_workspace):
        """verification_summary_path is None when file does not exist."""
        del branch_workspace  # fixture only needed for chdir + monkeypatch side effects
        result = map_step_runner.build_review_handoff()

        assert result["verification_summary_path"] is None


# ---------------------------------------------------------------------------
# build_handoff_bundle — focused unit tests
# ---------------------------------------------------------------------------


class TestBuildHandoffBundle:
    """Focused tests for build_handoff_bundle."""

    def test_happy_path_returns_summary_validation_risks(self, branch_workspace):
        """Returns non-empty summary, validation, and risks when artifacts exist."""
        (branch_workspace / "verification-summary.md").write_text(
            "# Verification Summary\n\n- Verdict: READY FOR REVIEW\n", encoding="utf-8"
        )
        (branch_workspace / "code-review-001.md").write_text(
            "# Code Review 001\n\n- follow up on edge case\n", encoding="utf-8"
        )

        result = map_step_runner.build_handoff_bundle()

        assert result["status"] == "success"
        assert "Verification summary available" in result["summary"]
        assert "READY FOR REVIEW" in result["validation"]
        assert "follow up on edge case" in result["risks_follow_up"]

    def test_empty_artifacts_returns_minimal_output(self, branch_workspace):
        """With no review/verification artifacts, summary and risks default to '[not recorded]'.

        Note: build_handoff_bundle calls ensure_human_artifacts which creates qa-001.md,
        so validation will contain at least the QA stub rather than '[not recorded]'.
        """
        del branch_workspace  # fixture only needed for chdir + monkeypatch side effects
        result = map_step_runner.build_handoff_bundle()

        assert result["status"] == "success"
        # No verification summary or code review → summary has no bullets
        assert "[not recorded]" in result["summary"]
        # risks_follow_up has no code review content
        assert "[not recorded]" in result["risks_follow_up"]
        # validation contains the auto-created qa-001.md stub at minimum
        assert "QA" in result["validation"] or "[not recorded]" in result["validation"]

    def test_branch_field_in_response(self, branch_workspace):
        """Response includes the branch name."""
        del branch_workspace  # fixture only needed for chdir + monkeypatch side effects
        result = map_step_runner.build_handoff_bundle()

        assert result["branch"] == "test-branch"


# ---------------------------------------------------------------------------
# write_pr_draft — focused unit tests
# ---------------------------------------------------------------------------


class TestWritePrDraft:
    """Focused tests for write_pr_draft."""

    def test_happy_path_creates_file_with_content(self, branch_workspace):
        """Creates pr-draft.md with all provided sections."""
        result = map_step_runner.write_pr_draft(
            "- Added login flow",
            "- All tests pass",
            "- Monitor auth latency",
        )

        assert result["status"] == "success"
        content = (branch_workspace / "pr-draft.md").read_text(encoding="utf-8")
        assert "Added login flow" in content
        assert "All tests pass" in content
        assert "Monitor auth latency" in content

    def test_defaults_to_not_recorded(self, branch_workspace):
        """Empty arguments produce '[not recorded]' placeholders in each section."""
        map_step_runner.write_pr_draft()

        content = (branch_workspace / "pr-draft.md").read_text(encoding="utf-8")
        # All three sections should show the default placeholder
        assert content.count("[not recorded]") == 3

    def test_overwrites_existing_pr_draft(self, branch_workspace):
        """Second call replaces content written by the first call."""
        map_step_runner.write_pr_draft("- First summary")
        map_step_runner.write_pr_draft("- Second summary")

        content = (branch_workspace / "pr-draft.md").read_text(encoding="utf-8")
        assert "First summary" not in content
        assert "Second summary" in content


# ---------------------------------------------------------------------------
# write_plan_review — focused unit tests
# ---------------------------------------------------------------------------


class TestWritePlanReview:
    """Focused tests for write_plan_review."""

    def test_happy_path_creates_numbered_file(self, branch_workspace):
        """Creates plan-review-001.md on first call with correct content."""
        result = map_step_runner.write_plan_review(
            summary="Looks good",
            recommendation="ready",
        )

        assert result["status"] == "success"
        assert result["file_name"] == "plan-review-001.md"
        content = (branch_workspace / "plan-review-001.md").read_text(encoding="utf-8")
        assert "Looks good" in content
        assert "ready" in content

    def test_sequential_numbering(self, branch_workspace):
        """Second call creates plan-review-002.md."""
        del branch_workspace
        map_step_runner.write_plan_review(recommendation="ready")
        result = map_step_runner.write_plan_review(recommendation="needs-revision")

        assert result["status"] == "success"
        assert result["file_name"] == "plan-review-002.md"

    def test_invalid_recommendation_returns_error(self, branch_workspace):
        """An unrecognised recommendation value returns an error dict."""
        result = map_step_runner.write_plan_review(recommendation="approve")

        assert result["status"] == "error"
        assert "Invalid recommendation" in result["message"]
        assert not (branch_workspace / "plan-review-001.md").exists()

    def test_all_valid_recommendations_accepted(self, branch_workspace):
        """All three GATE_VERDICTS are accepted as recommendation values."""
        del branch_workspace
        for verdict in ("ready", "needs-revision", "blocked"):
            res = map_step_runner.write_plan_review(
                summary=f"Review for {verdict}", recommendation=verdict
            )
            assert (
                res["status"] == "success"
            ), f"Expected success for recommendation={verdict!r}"


# ---------------------------------------------------------------------------
# ensure_known_issues_file — focused unit tests
# ---------------------------------------------------------------------------


class TestEnsureKnownIssuesFile:
    """Focused tests for ensure_known_issues_file."""

    def test_happy_path_creates_with_default_structure(self, branch_workspace):
        """Creates known-issues.json with the default empty issues list."""
        result = map_step_runner.ensure_known_issues_file()

        assert result["status"] == "success"
        assert result["created"] is True
        issues_file = branch_workspace / "known-issues.json"
        assert issues_file.exists()
        data = json.loads(issues_file.read_text(encoding="utf-8"))
        assert "issues" in data
        assert data["issues"] == []

    def test_returns_created_false_when_exists(self, branch_workspace):
        """Returns created=False when known-issues.json already present."""
        del branch_workspace
        map_step_runner.ensure_known_issues_file()
        result = map_step_runner.ensure_known_issues_file()

        assert result["status"] == "success"
        assert result["created"] is False

    def test_existing_content_preserved(self, branch_workspace):
        """Pre-existing known-issues.json content is not overwritten."""
        issues_file = branch_workspace / "known-issues.json"
        original = '{"issues": [{"title": "Already tracked"}]}\n'
        issues_file.write_text(original, encoding="utf-8")

        map_step_runner.ensure_known_issues_file()

        assert issues_file.read_text(encoding="utf-8") == original


# ---------------------------------------------------------------------------
# add_known_issue — focused unit tests
# ---------------------------------------------------------------------------


class TestAddKnownIssue:
    """Focused tests for add_known_issue."""

    def test_happy_path_appends_entry(self, branch_workspace):
        """Appends a new entry to the existing known-issues.json."""
        map_step_runner.ensure_known_issues_file()
        result = map_step_runner.add_known_issue(
            "Flaky integration test", "accepted", "Tracked in follow-up"
        )

        assert result["status"] == "success"
        assert result["count"] == 1
        data = json.loads(
            (branch_workspace / "known-issues.json").read_text(encoding="utf-8")
        )
        assert data["issues"][0]["title"] == "Flaky integration test"
        assert data["issues"][0]["status"] == "accepted"
        assert data["issues"][0]["notes"] == "Tracked in follow-up"
        assert "recorded_at" in data["issues"][0]

    def test_auto_creates_file_when_missing(self, branch_workspace):
        """Auto-creates known-issues.json if it does not yet exist."""
        assert not (branch_workspace / "known-issues.json").exists()

        result = map_step_runner.add_known_issue("Missing file test", "accepted")

        assert result["status"] == "success"
        assert (branch_workspace / "known-issues.json").exists()

    def test_multiple_issues_accumulate(self, branch_workspace):
        """Multiple add_known_issue calls accumulate entries (no overwrite)."""
        map_step_runner.ensure_known_issues_file()
        map_step_runner.add_known_issue("Issue A", "accepted")
        result = map_step_runner.add_known_issue("Issue B", "deferred")

        assert result["count"] == 2
        data = json.loads(
            (branch_workspace / "known-issues.json").read_text(encoding="utf-8")
        )
        titles = [issue["title"] for issue in data["issues"]]
        assert "Issue A" in titles
        assert "Issue B" in titles

    def test_default_status_is_accepted(self, branch_workspace):
        """Default status is 'accepted' when not supplied."""
        map_step_runner.ensure_known_issues_file()
        map_step_runner.add_known_issue("Default status issue")

        data = json.loads(
            (branch_workspace / "known-issues.json").read_text(encoding="utf-8")
        )
        assert data["issues"][0]["status"] == "accepted"


# ---------------------------------------------------------------------------
# run_test_gate — focused unit tests
# ---------------------------------------------------------------------------


class TestRunTestGate:
    """Focused tests for run_test_gate."""

    def test_no_test_runner_returns_skipped(self, tmp_path, monkeypatch):
        """Returns skipped when no test runner markers exist."""
        monkeypatch.chdir(tmp_path)

        result = map_step_runner.run_test_gate()

        assert result["status"] == "skipped"
        assert result["passed"] is True
        assert "No test runner detected" in result["reason"]

    def test_pytest_detected_and_executed(self, tmp_path, monkeypatch):
        """Detects pytest.ini and runs pytest."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")

        import subprocess as real_subprocess

        def mock_run(cmd, **kwargs):
            del kwargs
            result = real_subprocess.CompletedProcess(cmd, 0, "1 passed\n", "")
            return result

        monkeypatch.setattr("subprocess.run", mock_run)

        result = map_step_runner.run_test_gate()

        assert result["status"] == "success"
        assert result["passed"] is True
        assert "pytest" in result["test_cmd"]

    def test_failed_tests_return_passed_false(self, tmp_path, monkeypatch):
        """Failed tests return passed=False with output."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")

        import subprocess as real_subprocess

        def mock_run(cmd, **kwargs):
            del kwargs
            return real_subprocess.CompletedProcess(cmd, 1, "FAILED test_foo\n", "")

        monkeypatch.setattr("subprocess.run", mock_run)

        result = map_step_runner.run_test_gate()

        assert result["status"] == "success"
        assert result["passed"] is False
        assert result["exit_code"] == 1

    def test_timeout_returns_passed_false(self, tmp_path, monkeypatch):
        """Timeout returns passed=False with timeout status."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")

        import subprocess

        def mock_run(cmd, **kwargs):
            del kwargs
            raise subprocess.TimeoutExpired(cmd, 300)

        monkeypatch.setattr("subprocess.run", mock_run)

        result = map_step_runner.run_test_gate()

        assert result["status"] == "timeout"
        assert result["passed"] is False


# ---------------------------------------------------------------------------
# snapshot_code_state — focused unit tests
# ---------------------------------------------------------------------------


class TestSnapshotCodeState:
    """Focused tests for snapshot_code_state."""

    def test_returns_expected_structure(self, branch_workspace):
        """Returns dict with git_ref, files_changed, diff_stat, branch."""
        del branch_workspace
        result = map_step_runner.snapshot_code_state()

        assert result["status"] == "success"
        assert "git_ref" in result
        assert isinstance(result["files_changed"], list)
        assert "diff_stat" in result
        assert result["branch"] == "test-branch"

    def test_git_ref_is_truncated(self, branch_workspace):
        """git_ref is at most 12 characters."""
        del branch_workspace
        result = map_step_runner.snapshot_code_state()

        assert len(result["git_ref"]) <= 12


class TestLoadBlueprint:
    """Tests for load_blueprint function."""

    def test_returns_dict_for_valid_file(self, branch_workspace):
        blueprint = {"summary": "test", "subtasks": [{"id": "ST-001", "title": "T1"}]}
        (branch_workspace / "blueprint.json").write_text(json.dumps(blueprint))
        result = map_step_runner.load_blueprint("test-branch")
        assert result == blueprint

    def test_returns_none_for_missing_file(self, branch_workspace):
        del branch_workspace
        result = map_step_runner.load_blueprint("test-branch")
        assert result is None

    def test_returns_none_for_invalid_json(self, branch_workspace):
        (branch_workspace / "blueprint.json").write_text("not json")
        result = map_step_runner.load_blueprint("test-branch")
        assert result is None


class TestGetSubtaskFromBlueprint:
    """Tests for get_subtask_from_blueprint function."""

    def test_finds_subtask_by_id(self):
        bp = {
            "subtasks": [{"id": "ST-001", "title": "A"}, {"id": "ST-002", "title": "B"}]
        }
        result = map_step_runner.get_subtask_from_blueprint(bp, "ST-002")
        assert result is not None
        assert result["title"] == "B"

    def test_returns_none_for_missing_id(self):
        bp = {"subtasks": [{"id": "ST-001", "title": "A"}]}
        result = map_step_runner.get_subtask_from_blueprint(bp, "ST-999")
        assert result is None

    def test_returns_none_for_empty_subtasks(self):
        result = map_step_runner.get_subtask_from_blueprint({}, "ST-001")
        assert result is None


class TestGetUpstreamIds:
    """Tests for get_upstream_ids function."""

    def test_returns_dependencies(self):
        bp = {"subtasks": [{"id": "ST-002", "dependencies": ["ST-001"]}]}
        result = map_step_runner.get_upstream_ids(bp, "ST-002")
        assert result == ["ST-001"]

    def test_returns_empty_for_no_deps(self):
        bp = {"subtasks": [{"id": "ST-001", "dependencies": []}]}
        result = map_step_runner.get_upstream_ids(bp, "ST-001")
        assert result == []

    def test_returns_empty_for_missing_subtask(self):
        bp = {"subtasks": []}
        result = map_step_runner.get_upstream_ids(bp, "ST-999")
        assert result == []


class TestBuildContextBlock:
    """Tests for build_context_block function."""

    def test_returns_empty_when_no_blueprint(self, branch_workspace):
        del branch_workspace
        result = map_step_runner.build_context_block("test-branch", "ST-001")
        assert result == ""

    def test_returns_empty_when_subtask_not_found(self, branch_workspace):
        bp = {"summary": "test", "subtasks": [{"id": "ST-001", "title": "A"}]}
        (branch_workspace / "blueprint.json").write_text(json.dumps(bp))
        result = map_step_runner.build_context_block("test-branch", "ST-999")
        assert result == ""

    def test_builds_full_context_block(self, branch_workspace):
        bp = {
            "summary": "test goal",
            "subtasks": [
                {
                    "id": "ST-001",
                    "title": "First task",
                    "aag_contract": "Actor -> do() -> done",
                    "affected_files": ["a.py"],
                    "validation_criteria": ["VC1: check"],
                    "dependencies": [],
                },
                {
                    "id": "ST-002",
                    "title": "Second task",
                    "aag_contract": "Actor -> do2() -> done2",
                    "affected_files": ["b.py"],
                    "expected_diff_size": "small",
                    "concern_type": "runtime",
                    "one_logical_step": True,
                    "validation_criteria": ["VC2: check"],
                    "dependencies": ["ST-001"],
                },
            ],
        }
        (branch_workspace / "blueprint.json").write_text(json.dumps(bp))

        plan = "## Goal\nImplement the feature.\n\n## Subtasks\n..."
        (branch_workspace / "task_plan_test-branch.md").write_text(plan)

        state = {
            "subtask_phases": {"ST-001": "COMPLETE"},
            "subtask_results": {
                "ST-001": {
                    "files_changed": ["a.py"],
                    "status": "valid",
                    "summary": "done",
                }
            },
        }
        (branch_workspace / "step_state.json").write_text(json.dumps(state))

        result = map_step_runner.build_context_block("test-branch", "ST-002")

        assert "<map_context>" in result
        assert "</map_context>" in result
        assert "# Goal:" in result
        assert "Implement the feature." in result
        assert "ST-002" in result
        assert "Second task" in result
        assert "Actor -> do2() -> done2" in result
        assert "expected_diff_size=small" in result
        assert "concern_type=runtime" in result
        assert "one_logical_step=True" in result
        assert "[>>] ST-002" in result
        assert "[x] ST-001" in result
        assert "# Upstream Results" in result
        assert "ST-001: files=" in result

    def test_build_context_block_no_longer_truncates(
        self, branch_workspace, monkeypatch
    ):
        """Negative-contract regression: build_context_block must NOT clip its
        output even when MAP_CONTEXT_BLOCK_BUDGET_TOKENS is set well below the
        natural block size. The truncation feature was removed by user request
        because the visible "[TRUNCATED] see token_budget.json" marker and
        per-field ellipsis were swallowing real subtask description / research
        text. token_budget.json must still record the over-budget event so
        operators can see when blocks exceed the configured budget.
        """
        subtasks = [
            {
                "id": "ST-001",
                "title": "Current task that must stay visible",
                "aag_contract": "Actor -> bounded context -> done",
                "affected_files": [f"src/current_{i}.py" for i in range(30)],
                "validation_criteria": [
                    "VC1 [AC-1]: current acceptance contract remains visible"
                ],
                "dependencies": ["ST-002"],
            },
            {
                "id": "ST-002",
                "title": "Dependency task",
                "aag_contract": "Actor -> dependency -> done",
                "affected_files": ["src/dep.py"],
                "validation_criteria": ["VC2 [AC-2]: dependency complete"],
                "dependencies": [],
            },
        ]
        subtasks.extend(
            {
                "id": f"ST-{i:03d}",
                "title": "Long future task " + ("noise " * 20),
                "aag_contract": "Actor -> future -> done",
                "affected_files": [f"src/future_{i}.py"],
                "validation_criteria": ["later"],
                "dependencies": [],
            }
            for i in range(3, 80)
        )
        (branch_workspace / "blueprint.json").write_text(
            json.dumps({"summary": "test", "subtasks": subtasks})
        )
        (branch_workspace / "task_plan_test-branch.md").write_text(
            "## Goal\nKeep the active Actor prompt bounded for long plans.\n"
        )
        state = {
            "subtask_results": {
                "ST-002": {
                    "files_changed": [f"src/dep_{i}.py" for i in range(20)],
                    "status": "valid",
                    "summary": "dependency summary " * 100,
                }
            }
        }
        (branch_workspace / "step_state.json").write_text(json.dumps(state))
        monkeypatch.setenv("MAP_CONTEXT_BLOCK_BUDGET_TOKENS", "260")

        result = map_step_runner.build_context_block("test-branch", "ST-001")

        # XML envelope stays intact.
        assert result.startswith("<map_context>")
        assert result.endswith("</map_context>")
        # NO truncation marker — the feature is gone.
        assert "# [TRUNCATED] see" not in result
        assert "# Context Budget: truncated" not in result
        assert "[truncated]" not in result
        # Full content must remain visible regardless of the artificially-
        # low MAP_CONTEXT_BLOCK_BUDGET_TOKENS env (the budget mechanism
        # was deleted entirely; the env var no longer has any effect).
        # Current subtask details are fully present.
        assert "Current task that must stay visible" in result
        assert "Actor -> bounded context -> done" in result
        # Every affected file rendered — no "+N more" elision.
        assert "src/current_0.py" in result
        assert "src/current_29.py" in result
        assert "+" not in result.split("Affected files:", 1)[1].split("\n", 1)[0]
        # Upstream summary preserved in full (100x repetition).
        assert "# Upstream Results" in result
        assert result.count("dependency summary") >= 100
        # All 80 plan-overview entries rendered.
        for stub in ("ST-001", "ST-002", "ST-050", "ST-079"):
            assert stub in result, stub

        # Token-budget bookkeeping was removed wholesale — no decisions
        # are recorded for build_context_block any more.
        budget_file = branch_workspace / "token_budget.json"
        if budget_file.exists():
            budget_report = json.loads(budget_file.read_text(encoding="utf-8"))
            for decision in budget_report.get("decisions", []):
                assert decision.get("path_name") != "map-efficient.actor_context_block"

    def test_build_context_block_ignores_impossible_budget(
        self, branch_workspace, monkeypatch
    ):
        bp = {
            "subtasks": [
                {
                    "id": "ST-001",
                    "title": "Only task",
                    "aag_contract": "A -> B -> C",
                    "affected_files": [],
                    "validation_criteria": [],
                    "dependencies": [],
                }
            ]
        }
        (branch_workspace / "blueprint.json").write_text(json.dumps(bp))
        (branch_workspace / "task_plan_test-branch.md").write_text(
            "## Goal\nDo thing.\n"
        )
        monkeypatch.setenv("MAP_CONTEXT_BLOCK_BUDGET_TOKENS", "1")

        result = map_step_runner.build_context_block("test-branch", "ST-001")

        assert "# Context Budget: truncated" not in result
        assert "Only task" in result

    def test_upstream_results_omitted_when_no_deps(self, branch_workspace):
        bp = {
            "summary": "test",
            "subtasks": [
                {
                    "id": "ST-001",
                    "title": "Only task",
                    "aag_contract": "A -> B -> C",
                    "affected_files": [],
                    "validation_criteria": [],
                    "dependencies": [],
                },
            ],
        }
        (branch_workspace / "blueprint.json").write_text(json.dumps(bp))
        plan = "## Goal\nDo thing.\n\n## Done"
        (branch_workspace / "task_plan_test-branch.md").write_text(plan)

        result = map_step_runner.build_context_block("test-branch", "ST-001")

        assert "<map_context>" in result
        assert "# Upstream Results" not in result


class TestBuildContextBlockIncludesDescription:
    """build_context_block now emits the subtask's `description` and
    `risk_level` — Actor previously had to read blueprint.json separately
    for the long-form what/why prose."""

    def test_description_emitted_when_present(self, branch_workspace):
        bp = {
            "subtasks": [
                {
                    "id": "ST-001",
                    "title": "first",
                    "description": "Implement QuantumComponentIndex with O(1) lookup.",
                    "aag_contract": "X -> y() -> done",
                    "risk_level": "low",
                    "validation_criteria": ["VC1: ok"],
                }
            ],
        }
        (branch_workspace / "blueprint.json").write_text(json.dumps(bp))
        result = map_step_runner.build_context_block("test-branch", "ST-001")
        assert "Description: Implement QuantumComponentIndex" in result, result
        assert "risk_level=low" in result, result

    def test_no_description_line_when_field_absent(self, branch_workspace):
        bp = {
            "subtasks": [
                {
                    "id": "ST-001",
                    "title": "first",
                    "aag_contract": "X -> y() -> done",
                    "validation_criteria": ["VC1: ok"],
                }
            ],
        }
        (branch_workspace / "blueprint.json").write_text(json.dumps(bp))
        result = map_step_runner.build_context_block("test-branch", "ST-001")
        assert "Description:" not in result


class TestBuildContextBlockRepoDelta:
    """Tests for Repo Delta path in build_context_block (requires mocked compute_differential_insight)."""

    def _setup_blueprint_and_state(self, branch_workspace, last_sha=None):
        """Helper to set up blueprint + state with optional last_subtask_commit_sha."""
        bp = {
            "summary": "test",
            "subtasks": [
                {
                    "id": "ST-001",
                    "title": "First task",
                    "aag_contract": "A -> B -> C",
                    "affected_files": ["a.py"],
                    "validation_criteria": ["VC1"],
                    "dependencies": [],
                },
            ],
        }
        (branch_workspace / "blueprint.json").write_text(json.dumps(bp))
        plan = "## Goal\nDo thing.\n\n## Done"
        (branch_workspace / "task_plan_test-branch.md").write_text(plan)

        state = {"subtask_phases": {}, "subtask_results": {}}
        if last_sha is not None:
            state["last_subtask_commit_sha"] = last_sha
        (branch_workspace / "step_state.json").write_text(json.dumps(state))

    def test_includes_repo_delta_when_sha_available(self, branch_workspace):
        self._setup_blueprint_and_state(branch_workspace, last_sha="abc123")
        mock_insight = {
            "changed_files": ["src/foo.py", "src/bar.py"],
            "deleted_files": [],
            "since_sha": "abc123",
            "current_sha": "def456",
        }
        repo_insight = types.SimpleNamespace(
            compute_differential_insight=_stub_compute_insight(mock_insight)
        )
        with patch.dict("sys.modules", {"mapify_cli.repo_insight": repo_insight}):
            result = map_step_runner.build_context_block("test-branch", "ST-001")

        assert "# Repo Delta" in result
        assert "src/foo.py" in result
        assert "src/bar.py" in result

    def test_repo_delta_lists_every_changed_file_without_elision(
        self, branch_workspace
    ):
        """Negative-contract regression: build_context_block no longer caps
        repo delta at 20 files. All changed files must render, and the
        "... +N more" elision marker must be absent.
        """
        self._setup_blueprint_and_state(branch_workspace, last_sha="abc123")
        many_files = [f"file_{i}.py" for i in range(25)]
        mock_insight = {
            "changed_files": many_files,
            "deleted_files": [],
            "since_sha": "abc123",
            "current_sha": "def456",
        }
        repo_insight = types.SimpleNamespace(
            compute_differential_insight=_stub_compute_insight(mock_insight)
        )
        with patch.dict("sys.modules", {"mapify_cli.repo_insight": repo_insight}):
            result = map_step_runner.build_context_block("test-branch", "ST-001")

        assert "# Repo Delta" in result
        for i in range(25):
            assert f"file_{i}.py" in result, f"missing file_{i}.py"
        assert "... +" not in result, "elision marker must be gone"

    def test_repo_delta_omitted_on_error(self, branch_workspace):
        self._setup_blueprint_and_state(branch_workspace, last_sha="abc123")
        mock_insight = {
            "changed_files": [],
            "deleted_files": [],
            "error": "git diff failed",
        }
        repo_insight = types.SimpleNamespace(
            compute_differential_insight=_stub_compute_insight(mock_insight)
        )
        with patch.dict("sys.modules", {"mapify_cli.repo_insight": repo_insight}):
            result = map_step_runner.build_context_block("test-branch", "ST-001")

        assert "<map_context>" in result
        assert "# Repo Delta" not in result

    def test_repo_delta_omitted_when_no_sha(self, branch_workspace):
        self._setup_blueprint_and_state(branch_workspace, last_sha=None)
        result = map_step_runner.build_context_block("test-branch", "ST-001")
        assert "<map_context>" in result
        assert "# Repo Delta" not in result

    def test_repo_delta_fallback_on_import_error(self, branch_workspace):
        """When mapify_cli.repo_insight is not importable, Repo Delta is silently skipped."""
        self._setup_blueprint_and_state(branch_workspace, last_sha="abc123")
        with patch.dict(
            "sys.modules", {"mapify_cli": None, "mapify_cli.repo_insight": None}
        ):
            result = map_step_runner.build_context_block("test-branch", "ST-001")

        assert "<map_context>" in result
        assert "# Repo Delta" not in result

    def test_repo_delta_includes_deleted_files(self, branch_workspace):
        """Deleted files from compute_differential_insight are shown in context block."""
        self._setup_blueprint_and_state(branch_workspace, last_sha="abc123")
        mock_insight = {
            "changed_files": ["src/new.py"],
            "deleted_files": ["src/old.py", "src/removed.py"],
            "since_sha": "abc123",
            "current_sha": "def456",
        }
        repo_insight = types.SimpleNamespace(
            compute_differential_insight=_stub_compute_insight(mock_insight)
        )
        with patch.dict("sys.modules", {"mapify_cli.repo_insight": repo_insight}):
            result = map_step_runner.build_context_block("test-branch", "ST-001")

        assert "# Repo Delta" in result
        assert "src/new.py" in result
        assert "# Deleted since last subtask:" in result
        assert "(deleted) src/old.py" in result
        assert "(deleted) src/removed.py" in result

    def test_repo_delta_only_deleted_no_changed(self, branch_workspace):
        """When only deletions occurred, Repo Delta still appears."""
        self._setup_blueprint_and_state(branch_workspace, last_sha="abc123")
        mock_insight = {
            "changed_files": [],
            "deleted_files": ["src/gone.py"],
            "since_sha": "abc123",
            "current_sha": "def456",
        }
        repo_insight = types.SimpleNamespace(
            compute_differential_insight=_stub_compute_insight(mock_insight)
        )
        with patch.dict("sys.modules", {"mapify_cli.repo_insight": repo_insight}):
            result = map_step_runner.build_context_block("test-branch", "ST-001")

        assert "# Repo Delta" in result
        assert "# Deleted since last subtask:" in result
        assert "(deleted) src/gone.py" in result


class TestBuildContextBlockIntegration:
    """Integration test: record_subtask_result → build_context_block → upstream results."""

    def test_upstream_results_flow(self, branch_workspace):
        """Subtask results recorded in step_state appear as upstream results in context block."""
        branch = "test-branch"

        # Set up blueprint with two subtasks, ST-002 depends on ST-001
        bp = {
            "subtasks": [
                {
                    "id": "ST-001",
                    "title": "First task",
                    "aag_contract": "A -> B -> C",
                    "affected_files": ["a.py"],
                    "validation_criteria": ["VC1"],
                    "dependencies": [],
                },
                {
                    "id": "ST-002",
                    "title": "Second task",
                    "aag_contract": "D -> E -> F",
                    "affected_files": ["b.py"],
                    "validation_criteria": ["VC2"],
                    "dependencies": ["ST-001"],
                },
            ],
        }
        (branch_workspace / "blueprint.json").write_text(json.dumps(bp))

        plan = "## Goal\nBuild the feature.\n\n## Done"
        (branch_workspace / f"task_plan_{branch}.md").write_text(plan)

        # Simulate ST-001 completed with results via StepState
        sys.path.insert(0, str(SCRIPTS_PATH))
        import map_orchestrator  # noqa: E402  # type: ignore[import-not-found]

        state = map_orchestrator.StepState()
        state.current_subtask_id = "ST-002"
        state.record_subtask_result(
            "ST-001", ["a.py"], "valid", "All tests pass", commit_sha="abc123"
        )
        state_file = branch_workspace / "step_state.json"
        state.save(state_file)

        # Now build context for ST-002 — should see ST-001 upstream results
        result = map_step_runner.build_context_block(branch, "ST-002")

        assert "<map_context>" in result
        assert "# Current Subtask: ST-002" in result
        assert "# Upstream Results (dependencies of ST-002):" in result
        assert "ST-001: files=['a.py'], status=valid" in result
        assert "All tests pass" in result
        assert "[x] ST-001: First task (valid)" in result
        assert "[>>] ST-002: Second task (IN PROGRESS)" in result


class TestSubtaskTokenUsage:
    """subtask_token_usage parses ~/.claude/projects/<project>/*.jsonl and
    aggregates assistant message.usage since the last subtask transition
    (step_state.json mtime). Closes the "no cheap per-subtask token count"
    gap from the latest framework triage (#10)."""

    def _seed_state(self, branch_workspace: Path, current: str = "ST-001") -> None:
        state = {
            "workflow": "map-efficient",
            "current_subtask_id": current,
            "subtask_sequence": [current],
        }
        (branch_workspace / "step_state.json").write_text(json.dumps(state))

    def _seed_log(self, log_dir: Path, entries: list[dict]) -> Path:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "session-test.jsonl"
        with log_path.open("w", encoding="utf-8") as fh:
            for entry in entries:
                fh.write(json.dumps(entry) + "\n")
        return log_path

    def test_sums_usage_only_after_state_mtime(
        self, branch_workspace, tmp_path, monkeypatch
    ):
        import time
        from datetime import datetime, timedelta, timezone
        self._seed_state(branch_workspace)
        # Force state mtime to a known anchor.
        anchor = datetime.now(timezone.utc).replace(microsecond=0)
        os.utime(
            branch_workspace / "step_state.json",
            (anchor.timestamp(), anchor.timestamp()),
        )
        # Place a Claude Code log dir using the canonical name convention.
        proj_abs = tmp_path.resolve()
        log_dir = tmp_path / "fake-home" / ".claude" / "projects" / str(proj_abs).replace("/", "-")
        before = (anchor - timedelta(seconds=30)).isoformat().replace("+00:00", "Z")
        after_1 = (anchor + timedelta(seconds=10)).isoformat().replace("+00:00", "Z")
        after_2 = (anchor + timedelta(seconds=20)).isoformat().replace("+00:00", "Z")
        entries = [
            {  # BEFORE transition — must be ignored
                "timestamp": before,
                "message": {"role": "assistant", "usage": {
                    "input_tokens": 9999, "output_tokens": 9999,
                    "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
                }},
            },
            {  # After — counted
                "timestamp": after_1,
                "message": {"role": "assistant", "usage": {
                    "input_tokens": 100, "output_tokens": 50,
                    "cache_creation_input_tokens": 200, "cache_read_input_tokens": 300,
                }},
            },
            {  # After — counted
                "timestamp": after_2,
                "message": {"role": "assistant", "usage": {
                    "input_tokens": 5, "output_tokens": 7,
                    "cache_creation_input_tokens": 1, "cache_read_input_tokens": 0,
                }},
            },
            {  # No usage field — ignored
                "timestamp": after_2,
                "message": {"role": "user", "content": "hi"},
            },
        ]
        self._seed_log(log_dir, entries)
        monkeypatch.setenv("HOME", str(tmp_path / "fake-home"))
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj_abs))
        # avoid time-of-day flake by sleeping briefly so log mtime > state mtime
        time.sleep(0.01)
        report = map_step_runner.subtask_token_usage("test-branch")
        assert report["status"] == "success", report
        assert report["subtask_id"] == "ST-001"
        assert report["messages_counted"] == 2
        assert report["input_tokens"] == 105
        assert report["output_tokens"] == 57
        assert report["cache_creation_input_tokens"] == 201
        assert report["cache_read_input_tokens"] == 300

    def test_all_flag_via_cli_reports_whole_session(
        self, branch_workspace, tmp_path, monkeypatch
    ):
        """`--all` anchors the window at epoch so the report covers every
        message in the active jsonl, ignoring step_state.json mtime."""
        self._seed_state(branch_workspace)
        proj_abs = tmp_path.resolve()
        log_dir = tmp_path / "home" / ".claude" / "projects" / str(proj_abs).replace("/", "-")
        entries = [
            {  # Way before any plausible state mtime
                "timestamp": "2020-01-01T00:00:00Z",
                "message": {"role": "assistant", "usage": {
                    "input_tokens": 11, "output_tokens": 22,
                    "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
                }},
            },
            {
                "timestamp": "2026-05-23T00:00:00Z",
                "message": {"role": "assistant", "usage": {
                    "input_tokens": 33, "output_tokens": 44,
                    "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
                }},
            },
        ]
        self._seed_log(log_dir, entries)
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj_abs))
        runner = (
            Path(__file__).resolve().parents[1]
            / "src" / "mapify_cli" / "templates" / "map" / "scripts" / "map_step_runner.py"
        )
        env = {
            **os.environ,
            "PYTHONDONTWRITEBYTECODE": "1",
            "HOME": str(tmp_path / "home"),
            "CLAUDE_PROJECT_DIR": str(proj_abs),
        }
        result = subprocess.run(
            [sys.executable, str(runner), "subtask_token_usage", "test-branch", "--all"],
            capture_output=True, text=True, cwd=str(tmp_path), env=env,
        )
        assert result.returncode == 0, result.stderr
        report = json.loads(result.stdout)
        # Both entries counted (default-anchor would drop the 2020 one).
        assert report["messages_counted"] == 2
        assert report["input_tokens"] == 44
        assert report["output_tokens"] == 66
        assert report["since_ts"].startswith("1970-01-01")

    def test_no_logs_when_log_dir_missing(self, branch_workspace, tmp_path, monkeypatch):
        self._seed_state(branch_workspace)
        monkeypatch.setenv("HOME", str(tmp_path / "fake-empty-home"))
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path.resolve()))
        report = map_step_runner.subtask_token_usage("test-branch")
        assert report["status"] == "no_logs"
        assert report["subtask_id"] == "ST-001"

    def test_explicit_subtask_id_and_since_ts_override_defaults(
        self, branch_workspace, tmp_path, monkeypatch
    ):
        self._seed_state(branch_workspace, current="ST-001")
        proj_abs = tmp_path.resolve()
        log_dir = tmp_path / "h" / ".claude" / "projects" / str(proj_abs).replace("/", "-")
        anchor_iso = "2026-05-23T00:00:00Z"
        entries = [
            {"timestamp": "2026-05-22T23:59:59Z",
             "message": {"role": "assistant", "usage": {"input_tokens": 1, "output_tokens": 1,
                "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}}},
            {"timestamp": "2026-05-23T00:00:30Z",
             "message": {"role": "assistant", "usage": {"input_tokens": 42, "output_tokens": 1,
                "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}}},
        ]
        self._seed_log(log_dir, entries)
        monkeypatch.setenv("HOME", str(tmp_path / "h"))
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj_abs))
        report = map_step_runner.subtask_token_usage(
            "test-branch", subtask_id="ST-007", since_ts=anchor_iso
        )
        assert report["subtask_id"] == "ST-007"
        assert report["since_ts"] == anchor_iso
        assert report["input_tokens"] == 42


class TestBlueprintContractRelaxations:
    """Validator now accepts (a) `text` as a `description` alias on hard/soft
    constraints, (b) `cross-repo` concern_type, (c) suppresses oversized /
    mixed flags when justification fields are present."""

    def _write_bp(self, branch_workspace: Path, **kwargs) -> Path:
        path = branch_workspace / "blueprint.json"
        path.write_text(json.dumps(kwargs))
        return path

    def _base_bp(self) -> dict:
        return {
            "summary": "x",
            "hard_constraints": [{"id": "HC-1", "description": "must"}],
            "soft_constraints": [],
            "coverage_map": {"HC-1": "ST-001"},
            "subtasks": [{
                "id": "ST-001", "title": "x", "aag_contract": "X -> y -> done",
                "expected_diff_size": "small", "concern_type": "runtime",
                "one_logical_step": True, "dependencies": [],
                "validation_criteria": ["VC1 [HC-1]: ok"],
            }],
        }

    def test_text_alias_accepted_for_constraint(self, branch_workspace):
        bp = self._base_bp()
        # Constraint uses `text` instead of `description`.
        bp["hard_constraints"] = [{"id": "HC-1", "text": "must hold true"}]
        path = self._write_bp(branch_workspace, **bp)
        result = map_step_runner.validate_blueprint_contract(str(path))
        assert result["valid"] is True, result["errors"]

    def test_cross_repo_concern_type_accepted(self, branch_workspace):
        bp = self._base_bp()
        bp["subtasks"][0]["concern_type"] = "cross-repo"
        path = self._write_bp(branch_workspace, **bp)
        result = map_step_runner.validate_blueprint_contract(str(path))
        assert result["valid"] is True, result["errors"]

    def test_split_rationale_suppresses_too_many_vc_warning(self, branch_workspace):
        bp = self._base_bp()
        bp["subtasks"][0]["validation_criteria"] = [
            f"VC{i} [HC-1]: ok" for i in range(1, 8)  # 7 criteria > threshold 6
        ]
        bp["subtasks"][0]["split_rationale"] = "Single logical contract — splitting fragments coverage."
        path = self._write_bp(branch_workspace, **bp)
        result = map_step_runner.validate_blueprint_contract(str(path))
        assert result["valid"] is True
        # No warning text about "consider splitting" should be present.
        assert not any("consider splitting" in w for w in result["warnings"]), result["warnings"]

    def test_split_rationale_suppresses_oversized_flag(self, branch_workspace):
        bp = self._base_bp()
        bp["subtasks"][0]["expected_diff_size"] = "large"
        bp["subtasks"][0]["split_rationale"] = "Atomic config + loader unit."
        path = self._write_bp(branch_workspace, **bp)
        result = map_step_runner.validate_blueprint_contract(str(path))
        assert result["valid"] is True
        assert result["oversized_subtasks"] == [], result


class TestAcknowledgedDiagnostics:
    """Fix #5: per-branch acknowledged-diagnostics ledger so Pyright /
    Monitor noise (pre-existing `_rescore_cached_findings is not
    accessed`-style lines) can be silenced once instead of re-flagged on
    every subtask.
    """

    def test_acknowledge_persists_signature(self, branch_workspace, monkeypatch):
        repo = branch_workspace.parents[1]
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        result = map_step_runner.acknowledge_diagnostic(
            "test-branch",
            "_rescore_cached_findings is not accessed",
            reason="pre-existing helper, not load-bearing",
        )
        assert result["status"] == "success"
        assert result["already_acknowledged"] is False
        # Whitespace gets normalized.
        assert "_rescore_cached_findings" in result["signature"]
        # Ledger file exists on disk.
        assert (
            branch_workspace / "acknowledged_diagnostics.json"
        ).exists()

    def test_re_acknowledge_updates_reason(self, branch_workspace, monkeypatch):
        repo = branch_workspace.parents[1]
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        map_step_runner.acknowledge_diagnostic(
            "test-branch", "noise line", reason="first reason"
        )
        result = map_step_runner.acknowledge_diagnostic(
            "test-branch", "noise line", reason="updated reason"
        )
        assert result["status"] == "success"
        assert result["already_acknowledged"] is True
        assert result["entry"]["reason"] == "updated reason"

    def test_is_acknowledged_returns_true_after_record(
        self, branch_workspace, monkeypatch
    ):
        repo = branch_workspace.parents[1]
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        assert map_step_runner.is_diagnostic_acknowledged(
            "test-branch", "noise"
        ) is False
        map_step_runner.acknowledge_diagnostic(
            "test-branch", "noise", reason="x"
        )
        assert map_step_runner.is_diagnostic_acknowledged(
            "test-branch", "noise"
        ) is True
        # Whitespace-normalized lookup still matches.
        assert map_step_runner.is_diagnostic_acknowledged(
            "test-branch", "  noise  "
        ) is True

    def test_list_returns_newest_first(self, branch_workspace, monkeypatch):
        repo = branch_workspace.parents[1]
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        map_step_runner.acknowledge_diagnostic("test-branch", "older")
        # Force a perceptible timestamp difference (UTC iso w/ microseconds).
        import time as _t
        _t.sleep(0.01)
        map_step_runner.acknowledge_diagnostic("test-branch", "newer")
        result = map_step_runner.list_acknowledged_diagnostics("test-branch")
        assert result["status"] == "success"
        signatures = [e["signature"] for e in result["entries"]]
        assert signatures.index("newer") < signatures.index("older")

    def test_unknown_branch_returns_empty(self, branch_workspace, monkeypatch):
        del branch_workspace
        repo = monkeypatch  # silence pyright
        del repo
        # Branch with no ledger file → empty entries, no error.
        result = map_step_runner.list_acknowledged_diagnostics("nonexistent-branch")
        assert result == {
            "status": "success",
            "branch": "nonexistent-branch",
            "entries": [],
        }


class TestDetectTruncatedAgentOutput:
    """Fix #4/#5: orchestrator helper that callers (skills, CI, automation)
    use to detect truncated Monitor/Actor responses uniformly. Was
    prose-only in the skill; now a single source-of-truth predicate.
    """

    def test_well_formed_monitor_response_is_not_truncated(self):
        # Must include all required_keys from AGENT_OUTPUT_SCHEMAS["monitor"]
        text = json.dumps({
            "evidence": [],
            "valid": True,
            "summary": "all good",
            "verdict": "approved",
            "issues": [],
            "passed_checks": ["all checks pass"],
            "failed_checks": [],
        })
        report = map_step_runner.detect_truncated_agent_output(
            text, agent_kind="monitor"
        )
        assert report["truncated"] is False, report
        assert report["reasons"] == []

    def test_prose_response_is_truncated(self):
        text = "All tests pass. Now run ruff check and we're good."
        report = map_step_runner.detect_truncated_agent_output(
            text, agent_kind="monitor"
        )
        assert report["truncated"] is True
        assert any("does not parse as JSON" in r for r in report["reasons"]) or \
            any("ends mid-sentence" in r for r in report["reasons"])

    def test_missing_required_key_is_truncated(self):
        # Parseable JSON but missing the "issues" key Monitor must emit.
        # Provide all other required keys so only "issues" triggers the error.
        text = json.dumps({
            "evidence": [],
            "valid": True,
            "summary": "ok",
            "verdict": "approved",
            "passed_checks": [],
            "failed_checks": [],
            # "issues" intentionally omitted
        })
        report = map_step_runner.detect_truncated_agent_output(
            text, agent_kind="monitor"
        )
        assert report["truncated"] is True
        assert any("missing required key: issues" in r for r in report["reasons"])

    def test_mid_sentence_cutoff_detected(self):
        text = '{"valid": true, "summary": "starting work'
        report = map_step_runner.detect_truncated_agent_output(text)
        assert report["truncated"] is True
        # The mid-sentence cue must surface (either via parse error
        # OR the explicit mid-sentence reason — at least one must fire).
        assert any(
            "does not parse as JSON" in r or "ends mid-sentence" in r
            for r in report["reasons"]
        )

    def test_fenced_json_is_extracted(self):
        # ```json\n{...}\n``` wraps — extraction recovers the object but
        # flags the wrapping prose as a soft signal.
        inner = json.dumps({
            "evidence": [],
            "valid": True,
            "summary": "ok",
            "verdict": "approved",
            "issues": [],
            "passed_checks": [],
            "failed_checks": [],
        })
        text = f"```json\n{inner}\n```"
        report = map_step_runner.detect_truncated_agent_output(
            text, agent_kind="monitor"
        )
        # Fenced content with all keys present is non-fatal, but the
        # trailing/leading text wrapping is recorded as a soft reason.
        assert "trailing or leading text around JSON object" in report["reasons"]

    def test_actor_kind_required_keys(self):
        # FIX 2: actor required_keys now includes all four envelope fields.
        text = json.dumps({"files_changed": ["a.py"]})
        report = map_step_runner.detect_truncated_agent_output(
            text, agent_kind="actor"
        )
        assert report["truncated"] is True
        assert any("missing required key: tests_run" in r for r in report["reasons"])
        assert any("missing required key: validation_notes" in r for r in report["reasons"])
        assert any("missing required key: blocker" in r for r in report["reasons"])

    def test_actor_full_output_not_truncated(self):
        """FIX 2: full actor envelope with all four required keys is not truncated."""
        text = json.dumps({
            "files_changed": ["a.py"],
            "tests_run": ["pytest: 5 passed"],
            "validation_notes": "satisfies VC1 and VC2",
            "blocker": None,
        })
        report = map_step_runner.detect_truncated_agent_output(
            text, agent_kind="actor"
        )
        assert report["truncated"] is False, report

    def test_review_monitor_full_output_not_truncated(self):
        """FIX 4: review-monitor with the full review schema is not truncated."""
        text = json.dumps({
            "evidence": [],
            "valid": True,
            "summary": "all good",
            "verdict": "approved",
            "issues": [],
            "passed_checks": ["all checks pass"],
            "failed_checks": [],
        })
        report = map_step_runner.detect_truncated_agent_output(
            text, agent_kind="review-monitor"
        )
        assert report["truncated"] is False, report

    def test_review_monitor_missing_verdict_is_truncated(self):
        """FIX 4: review-monitor output missing a full-schema key (verdict) is truncated."""
        text = json.dumps({
            "evidence": [],
            "valid": True,
            "summary": "ok",
            "issues": [],
            "passed_checks": [],
            "failed_checks": [],
            # "verdict" intentionally omitted
        })
        report = map_step_runner.detect_truncated_agent_output(
            text, agent_kind="review-monitor"
        )
        assert report["truncated"] is True
        assert any("missing required key: verdict" in r for r in report["reasons"])

    def test_review_monitor_missing_passed_checks_is_truncated(self):
        """FIX 4: review-monitor output missing passed_checks is truncated."""
        text = json.dumps({
            "evidence": [],
            "valid": True,
            "summary": "ok",
            "verdict": "approved",
            "issues": [],
            # "passed_checks" intentionally omitted
            "failed_checks": [],
        })
        report = map_step_runner.detect_truncated_agent_output(
            text, agent_kind="review-monitor"
        )
        assert report["truncated"] is True
        assert any("missing required key: passed_checks" in r for r in report["reasons"])

    def test_monitor_still_accepts_efficient_output(self):
        """FIX 4: --agent monitor still accepts map-efficient Monitor output
        (no evidence/verdict/passed_checks/failed_checks) — regression guard."""
        text = json.dumps({
            "valid": True,
            "summary": "ST-001 satisfies all criteria",
            "issues": [],
            "files_changed": ["a.py"],
            "tests_run": ["pytest: 10 passed"],
            "escalation_required": False,
        })
        report = map_step_runner.detect_truncated_agent_output(
            text, agent_kind="monitor"
        )
        assert report["truncated"] is False, report

    def test_empty_response_is_truncated(self):
        report = map_step_runner.detect_truncated_agent_output("")
        assert report["truncated"] is True
        assert report["reasons"] == ["empty response"]

    def _run_truncation_cli(self, stdin_text: str, agent: str = "actor") -> dict:
        proc = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS_PATH / "map_step_runner.py"),
                "detect_truncated_agent_output",
                "--agent",
                agent,
            ],
            input=stdin_text,
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout)

    def test_cli_no_input_is_not_truncated(self):
        """Regression: a bare CLI call (nothing piped) must NOT report a
        hard-stop truncation. It returns status=='no_input' / truncated False
        so it can't masquerade as an 'empty response' truncation on every
        subtask when the caller forgot to pipe the agent response.
        """
        report = self._run_truncation_cli("")
        assert report["truncated"] is False, report
        assert report["status"] == "no_input", report

    def test_cli_piped_prose_is_truncated(self):
        """A genuinely-piped prose (non-JSON) response is still flagged."""
        report = self._run_truncation_cli("All good, shipping now.", agent="monitor")
        assert report["truncated"] is True, report
        assert report["status"] == "ok", report

    def test_cli_piped_valid_envelope_is_ok(self):
        """A piped complete envelope passes (truncated False, status ok)."""
        envelope = json.dumps({
            "files_changed": ["a.py"],
            "tests_run": ["pytest"],
            "validation_notes": "ok",
            "blocker": "",
        })
        report = self._run_truncation_cli(envelope)
        assert report["truncated"] is False, report
        assert report["status"] == "ok", report

    def test_predictor_full_output_not_truncated(self):
        """POSITIVE: full valid predictor JSON is not flagged as truncated."""
        text = json.dumps({
            "evidence": [{"file_path": "f.py", "line_range": "1", "quote": "x", "relevance": "y"}],
            "risk_assessment": "low",
            "predicted_state": {
                "affected_components": [],
                "breaking_changes": [],
                "required_updates": [],
            },
            "confidence": {"score": 0.9},
        })
        report = map_step_runner.detect_truncated_agent_output(
            text, agent_kind="predictor"
        )
        assert report["truncated"] is False, report

    def test_predictor_missing_required_key_is_truncated(self):
        """NEGATIVE: predictor output missing a required key is truncated."""
        # omit "confidence" — a required key
        text = json.dumps({
            "evidence": [],
            "risk_assessment": "low",
            "predicted_state": {"affected_components": [], "breaking_changes": [], "required_updates": []},
        })
        report = map_step_runner.detect_truncated_agent_output(
            text, agent_kind="predictor"
        )
        assert report["truncated"] is True
        assert any("missing required key: confidence" in r for r in report["reasons"])

    def test_predictor_missing_conditional_landmine_not_truncated(self):
        """CONDITIONAL: predictor output missing landmine_evidence (conditional)
        must NOT be flagged as truncated."""
        text = json.dumps({
            "evidence": [],
            "risk_assessment": "medium",
            "predicted_state": {"affected_components": [], "breaking_changes": [], "required_updates": []},
            "confidence": {"score": 0.7},
            # landmine_evidence intentionally absent — it is conditional
        })
        report = map_step_runner.detect_truncated_agent_output(
            text, agent_kind="predictor"
        )
        assert report["truncated"] is False, report

    def test_evaluator_full_output_not_truncated(self):
        """POSITIVE: full valid evaluator JSON is not flagged as truncated."""
        text = json.dumps({
            "evidence": [],
            "scores": {
                "functionality": 8, "code_quality": 7, "performance": 7,
                "security": 9, "testability": 8, "completeness": 8,
            },
            "overall_score": 7.8,
            "recommendation": "proceed",
            "strengths": ["clear tests"],
            "weaknesses": [],
            "next_steps": [],
            "monitor_severity_audit": [],
        })
        report = map_step_runner.detect_truncated_agent_output(
            text, agent_kind="evaluator"
        )
        assert report["truncated"] is False, report

    def test_evaluator_missing_required_key_is_truncated(self):
        """NEGATIVE: evaluator output missing a required key is truncated."""
        # omit "monitor_severity_audit"
        text = json.dumps({
            "evidence": [],
            "scores": {"functionality": 8, "code_quality": 7, "performance": 7,
                       "security": 9, "testability": 8, "completeness": 8},
            "overall_score": 7.8,
            "recommendation": "proceed",
            "strengths": [],
            "weaknesses": [],
            "next_steps": [],
        })
        report = map_step_runner.detect_truncated_agent_output(
            text, agent_kind="evaluator"
        )
        assert report["truncated"] is True
        assert any("missing required key: monitor_severity_audit" in r for r in report["reasons"])

    def test_monitor_missing_conditional_sibling_comparison_not_truncated(self):
        """CONDITIONAL: monitor output missing sibling_comparison (per-issue
        conditional) must NOT be flagged as truncated at the top level."""
        # sibling_comparison is a field inside each issue object — it is
        # NOT a top-level required key, so omitting it at top level is fine.
        text = json.dumps({
            "evidence": [],
            "valid": True,
            "summary": "ok",
            "verdict": "approved",
            "issues": [],
            "passed_checks": ["tests pass"],
            "failed_checks": [],
            # sibling_comparison is per-issue conditional, not top-level
        })
        report = map_step_runner.detect_truncated_agent_output(
            text, agent_kind="monitor"
        )
        assert report["truncated"] is False, report

    def test_map_efficient_monitor_output_not_truncated(self):
        """Regression (Copilot review on PR #145): the map-efficient Monitor
        gate runs `--agent monitor` against a Monitor prompted for
        valid/summary/issues/files_changed/tests_run/escalation_required — it
        does NOT emit evidence/verdict/passed_checks/failed_checks. The
        truncation detector must accept this contract (its required keys are
        the common core valid/summary/issues), otherwise the pre-verdict gate
        rejects every valid map-efficient Monitor response and loops forever.
        """
        text = json.dumps({
            "valid": True,
            "summary": "ST-001 satisfies all criteria",
            "issues": [],
            "files_changed": ["a.py"],
            "tests_run": ["pytest: 10 passed"],
            "escalation_required": False,
        })
        report = map_step_runner.detect_truncated_agent_output(
            text, agent_kind="monitor"
        )
        assert report["truncated"] is False, report
        assert report["reasons"] == []


class TestBlueprintContractAffectedFilesDrift:
    """Decomposer drift catch: when every declared affected_files path is
    missing from disk, validate_blueprint_contract warns. The canonical
    friction was the decomposer naming services/sourcecraft.py when the
    actual class lives in sourcecraft_publisher.py."""

    def _bp(self, files: list[str]) -> dict:
        return {
            "summary": "x",
            "hard_constraints": [{"id": "HC-1", "description": "must"}],
            "soft_constraints": [],
            "coverage_map": {"HC-1": "ST-001"},
            "subtasks": [{
                "id": "ST-001", "title": "x", "aag_contract": "X -> y -> done",
                "expected_diff_size": "small", "concern_type": "runtime",
                "one_logical_step": True, "dependencies": [],
                "affected_files": files,
                "validation_criteria": ["VC1 [HC-1]: ok"],
            }],
        }

    def test_warns_when_all_paths_missing(
        self, branch_workspace, monkeypatch
    ):
        repo = branch_workspace.parents[1]
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        path = branch_workspace / "blueprint.json"
        path.write_text(json.dumps(self._bp(["src/hallucinated.py", "src/also_missing.py"])))
        result = map_step_runner.validate_blueprint_contract(str(path))
        # Drift is a warning, not an error — still valid=True.
        assert result["valid"] is True, result["errors"]
        assert any("affected_files drift" in w for w in result["warnings"]), result["warnings"]

    def test_no_warning_when_any_path_exists(
        self, branch_workspace, monkeypatch
    ):
        repo = branch_workspace.parents[1]
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        (repo / "real.py").write_text("# real file")
        path = branch_workspace / "blueprint.json"
        path.write_text(json.dumps(self._bp(["real.py", "src/missing.py"])))
        result = map_step_runner.validate_blueprint_contract(str(path))
        assert result["valid"] is True
        assert not any("affected_files drift" in w for w in result["warnings"]), result["warnings"]

    def test_no_warning_when_affected_files_empty(
        self, branch_workspace, monkeypatch
    ):
        repo = branch_workspace.parents[1]
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        path = branch_workspace / "blueprint.json"
        path.write_text(json.dumps(self._bp([])))
        result = map_step_runner.validate_blueprint_contract(str(path))
        assert result["valid"] is True
        assert not any("affected_files drift" in w for w in result["warnings"])

    def test_drift_suppressed_when_all_paths_cross_repo(
        self, branch_workspace, monkeypatch
    ):
        """Regression #2 (2026-05-26): when every missing path is
        cross-repo, drift warning must NOT fire — cross-repo gets its
        own dedicated warning, and the drift message would be a false
        positive (MAP can't verify sibling repo files).
        """
        repo = branch_workspace.parents[1]
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        path = branch_workspace / "blueprint.json"
        path.write_text(json.dumps(self._bp([
            "../LLM-memory/internal/foo.go",
            "../sibling-repo/bar.py",
        ])))
        result = map_step_runner.validate_blueprint_contract(str(path))
        assert result["valid"] is True
        # Cross-repo warning fires; drift warning does NOT.
        assert any("cross-repo affected_files" in w for w in result["warnings"])
        assert not any("affected_files drift" in w for w in result["warnings"]), result["warnings"]

    def test_drift_suppressed_when_description_marks_new_file(
        self, branch_workspace, monkeypatch
    ):
        """Drift warning suppressed when subtask description signals the
        files are CREATED here (new file). The decomposer can opt out by
        naming the intent in the description prose."""
        repo = branch_workspace.parents[1]
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        bp = self._bp(["tests/test_new_module.py", "src/new_module.py"])
        bp["subtasks"][0]["description"] = (
            "Introduces new module + tests from scratch; no existing files."
        )
        path = branch_workspace / "blueprint.json"
        path.write_text(json.dumps(bp))
        result = map_step_runner.validate_blueprint_contract(str(path))
        assert result["valid"] is True
        assert not any("affected_files drift" in w for w in result["warnings"]), result["warnings"]

    def test_drift_still_fires_when_no_creation_hint_and_local_paths(
        self, branch_workspace, monkeypatch
    ):
        """Counter-test: pure hallucination (local path that doesn't exist
        AND description doesn't signal new-file) still triggers drift."""
        repo = branch_workspace.parents[1]
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        path = branch_workspace / "blueprint.json"
        path.write_text(json.dumps(self._bp(["src/hallucinated.py"])))
        result = map_step_runner.validate_blueprint_contract(str(path))
        assert result["valid"] is True
        assert any("affected_files drift" in w for w in result["warnings"]), result["warnings"]

    def test_drift_suppressed_when_creates_files_lists_all_paths(
        self, branch_workspace, monkeypatch
    ):
        """Structural opt-out (issue #167): when every missing path is declared
        in `creates_files`, the subtask creates them all — no drift warning and
        no description prose required."""
        repo = branch_workspace.parents[1]
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        files = ["src/new_module.py", "tests/test_new_module.py"]
        bp = self._bp(files)
        bp["subtasks"][0]["creates_files"] = list(files)
        path = branch_workspace / "blueprint.json"
        path.write_text(json.dumps(bp))
        result = map_step_runner.validate_blueprint_contract(str(path))
        assert result["valid"] is True, result["errors"]
        assert not any(
            "affected_files drift" in w for w in result["warnings"]
        ), result["warnings"]

    def test_drift_fires_for_missing_modify_target_with_partial_creates_files(
        self, branch_workspace, monkeypatch
    ):
        """`creates_files` names only the new file; the other affected path is a
        modify-target that is missing on disk → drift fires and names the
        missing modify-target, not the created file."""
        repo = branch_workspace.parents[1]
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        bp = self._bp(["src/new_module.py", "src/missing_modify.py"])
        bp["subtasks"][0]["creates_files"] = ["src/new_module.py"]
        path = branch_workspace / "blueprint.json"
        path.write_text(json.dumps(bp))
        result = map_step_runner.validate_blueprint_contract(str(path))
        assert result["valid"] is True, result["errors"]
        drift = [w for w in result["warnings"] if "affected_files drift" in w]
        assert drift, result["warnings"]
        assert "src/missing_modify.py" in drift[0]
        assert "src/new_module.py" not in drift[0]

    def test_structural_creates_files_overrides_description_prose(
        self, branch_workspace, monkeypatch
    ):
        """When `creates_files` is present (even empty) it is authoritative and
        the deprecated description-phrase heuristic is ignored: empty
        creates_files + 'introduces new module' prose + a missing path still
        fires drift (the path is NOT declared as a create)."""
        repo = branch_workspace.parents[1]
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        bp = self._bp(["src/hallucinated.py"])
        bp["subtasks"][0]["creates_files"] = []
        bp["subtasks"][0]["description"] = "Introduces new module from scratch."
        path = branch_workspace / "blueprint.json"
        path.write_text(json.dumps(bp))
        result = map_step_runner.validate_blueprint_contract(str(path))
        assert result["valid"] is True, result["errors"]
        assert any(
            "affected_files drift" in w for w in result["warnings"]
        ), result["warnings"]

    def test_creates_files_must_be_subset_of_affected_files(
        self, branch_workspace, monkeypatch
    ):
        """A `creates_files` path not in `affected_files` is a structural error —
        a created file must be inside the declared mutation surface."""
        repo = branch_workspace.parents[1]
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        bp = self._bp(["src/new_module.py"])
        bp["subtasks"][0]["creates_files"] = ["src/orphan_not_declared.py"]
        path = branch_workspace / "blueprint.json"
        path.write_text(json.dumps(bp))
        result = map_step_runner.validate_blueprint_contract(str(path))
        assert result["valid"] is False
        assert any(
            "creates_files" in str(e) and "affected_files" in str(e)
            for e in result["errors"]
        ), result["errors"]

    def test_creates_files_must_be_an_array(
        self, branch_workspace, monkeypatch
    ):
        """`creates_files` must be an array of path strings, not a bare string."""
        repo = branch_workspace.parents[1]
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        bp = self._bp(["src/new_module.py"])
        bp["subtasks"][0]["creates_files"] = "src/new_module.py"
        path = branch_workspace / "blueprint.json"
        path.write_text(json.dumps(bp))
        result = map_step_runner.validate_blueprint_contract(str(path))
        assert result["valid"] is False
        assert any(
            "creates_files must be an array" in str(e) for e in result["errors"]
        ), result["errors"]


class TestBlueprintContractSoftConstraintForwardDisclosure:
    """Fix #1 (2026-05-26): soft-constraint validation used to require
    two validator passes — first pass said "needs coverage_map OR
    rationale"; after fix, second pass said "owner VC must cite
    [SC-N]". Now the first error mentions both branches up front so
    the operator can plan path (b) as two-step from the start.
    """

    def _bp_with_sc(self, include_in_coverage: bool, vc_cites_sc: bool) -> dict:
        sc_id = "SC-2"
        vc = ["VC1 [HC-1]: ok"]
        if vc_cites_sc:
            vc.append(f"VC2 [{sc_id}]: cited")
        bp = {
            "summary": "x",
            "hard_constraints": [{"id": "HC-1", "description": "must"}],
            "soft_constraints": [{"id": sc_id, "description": "soft"}],
            "coverage_map": {"HC-1": "ST-001"},
            "subtasks": [{
                "id": "ST-001", "title": "x", "aag_contract": "X -> y -> done",
                "expected_diff_size": "small", "concern_type": "runtime",
                "one_logical_step": True, "dependencies": [],
                "validation_criteria": vc,
            }],
        }
        if include_in_coverage:
            bp["coverage_map"][sc_id] = "ST-001"
        return bp

    def test_first_pass_error_mentions_both_branches(
        self, branch_workspace
    ):
        path = branch_workspace / "blueprint.json"
        path.write_text(
            json.dumps(self._bp_with_sc(include_in_coverage=False, vc_cites_sc=False))
        )
        result = map_step_runner.validate_blueprint_contract(str(path))
        assert result["valid"] is False
        sc_errors = [e for e in result["errors"] if "'SC-2'" in e]
        assert sc_errors, result["errors"]
        msg = sc_errors[0]
        # Both branches must be enumerated.
        assert "tradeoff_rationale" in msg, msg
        assert "[SC-2] bracket-tag" in msg or "[SC-2]" in msg, msg
        assert "two requirements, not one" in msg, msg

    def test_path_a_tradeoff_rationale_silences_both_checks(
        self, branch_workspace
    ):
        bp = self._bp_with_sc(include_in_coverage=False, vc_cites_sc=False)
        bp["soft_constraints"][0]["tradeoff_rationale"] = "accepted tradeoff"
        path = branch_workspace / "blueprint.json"
        path.write_text(json.dumps(bp))
        result = map_step_runner.validate_blueprint_contract(str(path))
        assert result["valid"] is True, result["errors"]

    def test_path_b_requires_both_coverage_and_bracket_tag(
        self, branch_workspace
    ):
        # Coverage_map alone, no bracket tag → still error on lineage.
        bp = self._bp_with_sc(include_in_coverage=True, vc_cites_sc=False)
        path = branch_workspace / "blueprint.json"
        path.write_text(json.dumps(bp))
        result = map_step_runner.validate_blueprint_contract(str(path))
        assert result["valid"] is False
        # Both coverage AND bracket tag → clean.
        bp = self._bp_with_sc(include_in_coverage=True, vc_cites_sc=True)
        path.write_text(json.dumps(bp))
        result = map_step_runner.validate_blueprint_contract(str(path))
        assert result["valid"] is True, result["errors"]


class TestBlueprintContractCrossRepoDetection:
    """Fix #9: validate_blueprint_contract warns when affected_files
    declares paths that resolve OUTSIDE the project root (sibling-repo
    mutations). MAP cannot guarantee anything about cross-repo work, so
    operators need a heads-up before blueprint approval.
    """

    def _bp(self, files: list[str]) -> dict:
        return {
            "summary": "x",
            "hard_constraints": [{"id": "HC-1", "description": "must"}],
            "soft_constraints": [],
            "coverage_map": {"HC-1": "ST-001"},
            "subtasks": [{
                "id": "ST-001", "title": "x", "aag_contract": "X -> y -> done",
                "expected_diff_size": "small", "concern_type": "runtime",
                "one_logical_step": True, "dependencies": [],
                "affected_files": files,
                "validation_criteria": ["VC1 [HC-1]: ok"],
            }],
        }

    def test_warns_on_cross_repo_path(self, branch_workspace, monkeypatch):
        repo = branch_workspace.parents[1]
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        # Create a real file in current repo so we don't trigger drift warning.
        (repo / "real.py").write_text("# x")
        # Sibling-repo path escapes via ..
        path = branch_workspace / "blueprint.json"
        path.write_text(
            json.dumps(self._bp(["real.py", "../sibling-repo/internal/handler.go"]))
        )
        result = map_step_runner.validate_blueprint_contract(str(path))
        assert result["valid"] is True
        assert any("cross-repo affected_files" in w for w in result["warnings"]), result["warnings"]
        # Specific path is named in the warning so the operator can grep.
        assert any(
            "../sibling-repo/internal/handler.go" in w
            for w in result["warnings"]
        ), result["warnings"]

    def test_no_warning_when_all_paths_in_repo(
        self, branch_workspace, monkeypatch
    ):
        repo = branch_workspace.parents[1]
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        (repo / "real.py").write_text("# x")
        (repo / "src").mkdir(exist_ok=True)
        (repo / "src" / "real2.py").write_text("# x")
        path = branch_workspace / "blueprint.json"
        path.write_text(json.dumps(self._bp(["real.py", "src/real2.py"])))
        result = map_step_runner.validate_blueprint_contract(str(path))
        assert result["valid"] is True
        assert not any("cross-repo affected_files" in w for w in result["warnings"])


class TestBlueprintContractForwardDepsRejection:
    """Planning-stage fix: validate_blueprint_contract rejects blueprints
    where a subtask depends on another subtask declared LATER in the
    subtasks[] array. Without this gate, the runtime walker would hit the
    dependent before its dep had any chance to complete, producing a
    silent deadlock the operator had to break with manual mark_subtask_complete.
    """

    def _subtask(self, sid: str, deps: list[str]) -> dict:
        return {
            "id": sid,
            "title": f"task {sid}",
            "aag_contract": "X -> y -> done",
            "expected_diff_size": "small",
            "concern_type": "runtime",
            "one_logical_step": True,
            "dependencies": deps,
            "validation_criteria": ["VC1 [HC-1]: ok"],
        }

    def _bp(self, subtasks: list[dict]) -> dict:
        return {
            "summary": "x",
            "hard_constraints": [{"id": "HC-1", "description": "must"}],
            "soft_constraints": [],
            "coverage_map": {"HC-1": subtasks[0]["id"]},
            "subtasks": subtasks,
        }

    def test_forward_dep_is_rejected(self, branch_workspace):
        # ST-012 depends on ST-027 (declared later) — the exact friction
        # the user reported on neuro-vlad.
        subtasks = [self._subtask(f"ST-{i:03d}", []) for i in range(1, 51)]
        subtasks[11]["dependencies"] = ["ST-027"]  # ST-012 -> ST-027 (forward)
        path = branch_workspace / "blueprint.json"
        path.write_text(json.dumps(self._bp(subtasks)))
        result = map_step_runner.validate_blueprint_contract(str(path))
        assert result["valid"] is False, result
        forward_errors = [e for e in result["errors"] if "forward dependency" in e]
        assert any("ST-012" in e and "ST-027" in e for e in forward_errors), forward_errors
        assert "ST-012->ST-027" in result["forward_dep_violations"]

    def test_self_dep_is_rejected(self, branch_workspace):
        subtasks = [self._subtask("ST-001", ["ST-001"])]
        path = branch_workspace / "blueprint.json"
        path.write_text(json.dumps(self._bp(subtasks)))
        result = map_step_runner.validate_blueprint_contract(str(path))
        assert result["valid"] is False
        assert any("self-reference" in e for e in result["errors"]), result["errors"]

    def test_backward_dep_is_accepted(self, branch_workspace):
        # ST-002 depends on ST-001 (declared earlier) — the canonical case.
        subtasks = [
            self._subtask("ST-001", []),
            self._subtask("ST-002", ["ST-001"]),
            self._subtask("ST-003", ["ST-001", "ST-002"]),
        ]
        path = branch_workspace / "blueprint.json"
        path.write_text(json.dumps(self._bp(subtasks)))
        result = map_step_runner.validate_blueprint_contract(str(path))
        assert result["valid"] is True, result["errors"]
        assert result["forward_dep_violations"] == []

    def test_unknown_dep_is_rejected_separately(self, branch_workspace):
        # Unknown dep is reported as "unknown subtask", not as a forward dep.
        subtasks = [self._subtask("ST-001", ["ST-999"])]
        path = branch_workspace / "blueprint.json"
        path.write_text(json.dumps(self._bp(subtasks)))
        result = map_step_runner.validate_blueprint_contract(str(path))
        assert result["valid"] is False
        assert any("unknown subtask" in e for e in result["errors"]), result["errors"]
        # Must NOT also be reported as a forward dep (the dep doesn't exist).
        assert not any("forward dependency" in e for e in result["errors"])


class TestListPlansCli:
    """list_plans enumerates .map/<branch>/ artifacts so operators can pick
    scope from a multi-roadmap workspace without grepping."""

    def test_returns_blueprint_and_state_metadata(self, branch_workspace, monkeypatch):
        repo = branch_workspace.parents[1]
        (branch_workspace / "blueprint.json").write_text(
            json.dumps({"subtasks": [{"id": "ST-001"}, {"id": "ST-002"}]})
        )
        (branch_workspace / "task_plan_test-branch.md").write_text("# plan")
        (branch_workspace / "step_state.json").write_text(
            json.dumps({"workflow_status": "WORKFLOW_COMPLETE", "completed_at": "2026-05-23Z"})
        )
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        report = map_step_runner.list_plans()
        assert report["status"] == "success"
        rows = [p for p in report["plans"] if p["branch"] == "test-branch"]
        assert rows, report
        row = rows[0]
        assert row["has_blueprint"] and row["has_task_plan"] and row["has_step_state"]
        assert row["workflow_status"] == "WORKFLOW_COMPLETE"
        assert row["subtask_count"] == 2


class TestRecordPlanArtifactsPlanReadyWithoutStepState:
    """/map-plan stops before INIT_STATE, so plan_status should be 'ready'
    when blueprint + task_plan are both present even if step_state.json
    has not been created yet."""

    def test_plan_ready_without_step_state(self, branch_workspace, monkeypatch):
        del monkeypatch  # branch_workspace already chdirs
        (branch_workspace / "blueprint.json").write_text(json.dumps({"subtasks": []}))
        (branch_workspace / "task_plan_test-branch.md").write_text("# plan")
        result = map_step_runner.record_plan_artifacts("test-branch")
        assert result["status"] == "success", result
        assert result["plan_status"] == "ready", result


class TestRefreshBlueprintAffectedFiles:
    """refresh_blueprint_affected_files locks the planned mutation surface to
    the actual diff once Actor finishes a subtask — closes the recurring
    drift between blueprint affected_files and reality."""

    def _init_git(self, root: Path) -> None:
        subprocess.run(["git", "init"], cwd=root, capture_output=True, check=False)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=root, capture_output=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=root, capture_output=True)
        (root / "seed.txt").write_text("seed")
        subprocess.run(["git", "add", "."], cwd=root, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=root, capture_output=True)

    def test_overwrites_affected_files_with_actual_diff(
        self, branch_workspace, monkeypatch
    ):
        repo = branch_workspace.parents[1]
        self._init_git(repo)
        # Blueprint guessed wrong paths.
        bp = {"subtasks": [{
            "id": "ST-001", "title": "x",
            "affected_files": ["wrong/path.py", "stale_guess.py"],
        }]}
        (branch_workspace / "blueprint.json").write_text(json.dumps(bp))
        # Actor actually changed these:
        (repo / "real_a.py").write_text("x = 1")
        (repo / "real_b.py").write_text("y = 2")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        report = map_step_runner.refresh_blueprint_affected_files(
            "test-branch", "ST-001"
        )
        assert report["status"] == "success", report
        assert sorted(report["current"]) == ["real_a.py", "real_b.py"]
        assert report["diff"]["added"] == ["real_a.py", "real_b.py"]
        assert report["diff"]["removed"] == ["stale_guess.py", "wrong/path.py"]
        reloaded = json.loads((branch_workspace / "blueprint.json").read_text())
        assert reloaded["subtasks"][0]["affected_files"] == ["real_a.py", "real_b.py"]

    def test_dry_run_does_not_write(self, branch_workspace, monkeypatch):
        repo = branch_workspace.parents[1]
        self._init_git(repo)
        bp = {"subtasks": [{
            "id": "ST-001", "affected_files": ["wrong.py"],
        }]}
        (branch_workspace / "blueprint.json").write_text(json.dumps(bp))
        (repo / "real.py").write_text("x")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        report = map_step_runner.refresh_blueprint_affected_files(
            "test-branch", "ST-001", dry_run=True
        )
        assert report["status"] == "dry_run"
        reloaded = json.loads((branch_workspace / "blueprint.json").read_text())
        # File on disk untouched.
        assert reloaded["subtasks"][0]["affected_files"] == ["wrong.py"]

    def test_rejects_unknown_subtask(self, branch_workspace, monkeypatch):
        repo = branch_workspace.parents[1]
        (branch_workspace / "blueprint.json").write_text(json.dumps({
            "subtasks": [{"id": "ST-001", "affected_files": []}]
        }))
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        report = map_step_runner.refresh_blueprint_affected_files(
            "test-branch", "ST-999"
        )
        assert report["status"] == "error"
        assert "ST-999" in report["message"]

    def test_includes_committed_files_via_baseline_sha(
        self, branch_workspace, monkeypatch
    ):
        """Regression #1: after per-subtask commit, porcelain is empty, so
        refresh used to record current=[] and mark all prior files removed.
        Now record_subtask_baseline captures head_sha and refresh diffs
        baseline_sha..HEAD to include committed-since-baseline files.
        """
        repo = branch_workspace.parents[1]
        self._init_git(repo)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        # Capture baseline BEFORE the subtask commits.
        snap = map_step_runner.record_subtask_baseline(
            "test-branch", "ST-001"
        )
        assert snap["status"] == "success"
        assert snap.get("head_sha"), "baseline must capture HEAD SHA"
        # Subtask edits + commits two files.
        (repo / "committed_a.py").write_text("x = 1")
        (repo / "committed_b.py").write_text("y = 2")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "ST-001 work"],
            cwd=repo, capture_output=True,
        )
        # Blueprint has stale guess; refresh should write the real two files
        # even though porcelain is now empty.
        bp = {"subtasks": [{
            "id": "ST-001", "affected_files": ["wrong.py"],
        }]}
        (branch_workspace / "blueprint.json").write_text(json.dumps(bp))
        report = map_step_runner.refresh_blueprint_affected_files(
            "test-branch", "ST-001"
        )
        assert report["status"] == "success", report
        # current MUST include both committed files — NOT empty.
        assert sorted(report["current"]) == ["committed_a.py", "committed_b.py"]
        assert "wrong.py" in report["diff"]["removed"]
        assert "committed_a.py" in report["diff"]["added"]


class TestRecordDiagnosticsBaseline:
    """Fix #1 (2026-05-27): record_diagnostics_baseline snapshots
    static-analysis (pyright/ruff/mypy/golangci-lint) counts at
    INIT_STATE so subtasks can delta against each tool. Pytest-only
    baseline missed 123 pyright + 130 ruff in one production run.
    """

    def test_baseline_with_no_tools_returns_empty_results(
        self, branch_workspace, monkeypatch, tmp_path
    ):
        del tmp_path
        # Pass explicit empty tool list to bypass auto-detect.
        repo = branch_workspace.parents[1]
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        report = map_step_runner.record_diagnostics_baseline(
            "test-branch", tools=[]
        )
        assert "tools" in report
        assert report["tools"] == {}
        assert (branch_workspace / "diagnostics_baseline.json").exists()

    def test_baseline_skips_missing_binary(
        self, branch_workspace, monkeypatch, tmp_path
    ):
        del tmp_path
        repo = branch_workspace.parents[1]
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        report = map_step_runner.record_diagnostics_baseline(
            "test-branch", tools=["nonexistent-binary-xyz"]
        )
        # Unknown tool name (no command mapping) is dropped silently.
        assert report["tools"] == {}

    def test_baseline_records_known_tool_entries_with_status(
        self, branch_workspace, monkeypatch, tmp_path
    ):
        """Even when binaries are missing on the test runner, the
        function must return a status='skipped' entry per tool so
        the operator's later delta-vs-baseline check has a stable
        shape to read."""
        del tmp_path
        repo = branch_workspace.parents[1]
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        report = map_step_runner.record_diagnostics_baseline(
            "test-branch", tools=["pyright", "ruff"]
        )
        # Each requested tool produces a result entry — either
        # "skipped" (binary missing) or "success" (binary found and ran).
        for tool in ("pyright", "ruff"):
            assert tool in report["tools"], report
            entry = report["tools"][tool]
            assert "status" in entry
            assert entry["status"] in ("skipped", "success", "timeout", "error")

    def test_list_baseline_returns_no_baseline_when_absent(
        self, branch_workspace, monkeypatch
    ):
        del branch_workspace
        del monkeypatch
        report = map_step_runner.list_diagnostics_baseline("never-recorded")
        assert report["status"] == "no_baseline"


class TestRecordTestBaseline:
    """Fix #9: INIT_STATE pre-flight pytest baseline so later subtasks can
    distinguish "I introduced this regression" from "this was broken
    before plan started".
    """

    def test_baseline_records_passing_run(
        self, branch_workspace, monkeypatch, tmp_path
    ):
        del tmp_path
        repo = branch_workspace.parents[1]
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        report = map_step_runner.record_test_baseline(
            "test-branch", "true"
        )
        assert report["status"] == "success"
        assert report["returncode"] == 0
        assert report["command"] == "true"
        assert report["baseline_failures"] == []
        baseline_path = branch_workspace / "test_baseline.json"
        assert baseline_path.exists()

    def test_baseline_captures_pytest_failure_lines(
        self, branch_workspace, monkeypatch, tmp_path
    ):
        del tmp_path
        repo = branch_workspace.parents[1]
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        # Synthesize a pytest-like FAILED line via printf.
        report = map_step_runner.record_test_baseline(
            "test-branch",
            "printf 'FAILED tests/test_x.py::test_foo - assert ...\\nFAILED tests/test_y.py::test_bar\\n'; exit 1",
        )
        assert report["status"] == "baseline_failures"
        assert report["returncode"] == 1
        assert sorted(report["baseline_failures"]) == [
            "tests/test_x.py::test_foo",
            "tests/test_y.py::test_bar",
        ]

    def test_baseline_skipped_when_no_harness(
        self, branch_workspace, monkeypatch, tmp_path
    ):
        del tmp_path
        # Use a totally empty dir without any project markers.
        empty_dir = branch_workspace.parents[1] / "empty"
        empty_dir.mkdir()
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(empty_dir))
        # The branch fixture's project_dir is non-empty (has pyproject /
        # etc); we have to point CLAUDE_PROJECT_DIR at a clean dir.
        # Auto-detect must return skipped status.
        report = map_step_runner.record_test_baseline("test-branch")
        # Either skipped (no harness) or success (if test harness
        # auto-detected from pyproject.toml elsewhere). The contract:
        # the call should not raise and should write a baseline file.
        assert report["status"] in ("skipped", "success", "baseline_failures")

    def test_list_baseline_failures_returns_recorded_entries(
        self, branch_workspace, monkeypatch, tmp_path
    ):
        del tmp_path
        repo = branch_workspace.parents[1]
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        map_step_runner.record_test_baseline(
            "test-branch",
            "printf 'FAILED tests/test_x.py::test_foo\\n'; exit 1",
        )
        report = map_step_runner.list_baseline_failures("test-branch")
        assert report["status"] == "success"
        assert report["baseline_failures"] == [
            "tests/test_x.py::test_foo"
        ]

    def test_list_baseline_failures_no_baseline_path(
        self, branch_workspace, monkeypatch
    ):
        del branch_workspace
        empty = monkeypatch  # silence pyright
        del empty
        report = map_step_runner.list_baseline_failures("never-recorded")
        assert report["status"] == "no_baseline"
        assert report["baseline_failures"] == []


class TestRecordSubtaskResultFilesSeparatorParsing:
    """Fix #2 (2026-05-26): CLI must accept --files with comma OR
    space separators. The legacy comma-only parser silently treated
    "a.py b.py" as one path and emitted "file does not exist" warnings
    on every multi-file subtask whose operator forgot the comma.
    """

    def test_cli_parses_space_separated_files(self):
        # The parsing happens in the CLI dispatch (orchestrator main()).
        # Exercise the actual regex used there.
        files_arg = "a.py b.py c.py"
        files = [c.strip() for c in re.split(r"[,\s]+", files_arg) if c.strip()]
        assert files == ["a.py", "b.py", "c.py"]

    def test_cli_parses_comma_separated_files(self):
        files_arg = "a.py,b.py,c.py"
        files = [c.strip() for c in re.split(r"[,\s]+", files_arg) if c.strip()]
        assert files == ["a.py", "b.py", "c.py"]

    def test_cli_parses_mixed_separators(self):
        files_arg = "a.py, b.py c.py,  d.py"
        files = [c.strip() for c in re.split(r"[,\s]+", files_arg) if c.strip()]
        assert files == ["a.py", "b.py", "c.py", "d.py"]


class TestRecordSubtaskResultCrossRepoSiblingPrefix:
    """Fix #1 extend (2026-05-26): cross-repo detection now catches
    paths whose first segment matches a sibling directory at
    ../<segment>/ (i.e., no ../ prefix). Operator wrote
    `LLM-memory/foo.go` from a parent that contains both repos —
    previously this triggered "possible typo" because the path doesn't
    exist under project_dir and doesn't escape via ..; now it's
    recognized as cross-repo.
    """

    def test_sibling_prefix_path_is_recognized_as_cross_repo(
        self, branch_dir_orchestrator, tmp_path, monkeypatch
    ):
        del branch_dir_orchestrator
        # Create project dir + sibling repo dir under the same parent.
        parent = tmp_path / "workspace"
        parent.mkdir()
        project = parent / "neuro-vlad"
        sibling = parent / "LLM-memory"
        project.mkdir()
        sibling.mkdir()
        (sibling / "internal").mkdir()
        (sibling / "internal" / "foo.go").write_text("package x")
        (project / ".map" / "test-branch").mkdir(parents=True)
        (project / ".map" / "test-branch" / "step_state.json").write_text(
            json.dumps({"workflow": "x", "subtask_sequence": ["ST-001"], "current_subtask_id": "ST-001"})
        )
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
        monkeypatch.chdir(project)
        import importlib.util as _ilu
        spec = _ilu.spec_from_file_location(
            "map_orchestrator",
            Path(__file__).parent.parent
            / "src" / "mapify_cli" / "templates" / "map" / "scripts"
            / "map_orchestrator.py",
        )
        assert spec is not None and spec.loader is not None
        orch = _ilu.module_from_spec(spec)
        spec.loader.exec_module(orch)
        result = orch.record_subtask_result(
            "ST-001",
            "test-branch",
            ["LLM-memory/internal/foo.go"],  # sibling-name, no ../ prefix
            "valid",
            summary="x",
            commit_sha="abc",
        )
        assert result["status"] == "success"
        assert "missing_files" not in result, result
        assert "cross_repo_files" in result, result
        assert result["cross_repo_files"] == ["LLM-memory/internal/foo.go"]


class TestRecordSubtaskResultCrossRepoSuppression:
    """Regression #2: cross-repo affected_files paths (../sibling-repo/...)
    must NOT trigger the "Some recorded files do not exist on disk —
    possible typo" warning. They're legitimate, just unverifiable from
    THIS project's CLAUDE_PROJECT_DIR. validate_blueprint_contract
    already warns about cross-repo at planning time; record_subtask_result
    should not repeat the noise.
    """

    def test_cross_repo_paths_appear_in_response_not_warning(
        self, branch_dir_orchestrator, tmp_path, monkeypatch
    ):
        del branch_dir_orchestrator
        # Set up a minimal state file in cwd-relative .map/.
        project = tmp_path / "project"
        sibling = tmp_path / "sibling-repo"
        project.mkdir()
        sibling.mkdir()
        (sibling / "real_file.go").write_text("package x")
        (project / ".map" / "test-branch").mkdir(parents=True)
        (project / ".map" / "test-branch" / "step_state.json").write_text(
            json.dumps({"workflow": "x", "subtask_sequence": ["ST-001"], "current_subtask_id": "ST-001"})
        )
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
        monkeypatch.chdir(project)
        import importlib.util as _ilu
        spec = _ilu.spec_from_file_location(
            "map_orchestrator",
            Path(__file__).parent.parent
            / "src" / "mapify_cli" / "templates" / "map" / "scripts"
            / "map_orchestrator.py",
        )
        assert spec is not None and spec.loader is not None
        orch = _ilu.module_from_spec(spec)
        spec.loader.exec_module(orch)
        result = orch.record_subtask_result(
            "ST-001",
            "test-branch",
            ["../sibling-repo/real_file.go", "../sibling-repo/another.go"],
            "valid",
            summary="x",
            commit_sha="abc123",
        )
        assert result["status"] == "success", result
        # No "typo" warning text for cross-repo paths.
        assert "missing_files" not in result, result
        assert "typo" not in (result.get("warning", "") or "").lower(), result
        # cross_repo_files surfaced for audit transparency.
        assert "cross_repo_files" in result, result
        assert "../sibling-repo/real_file.go" in result["cross_repo_files"]


@pytest.fixture
def branch_dir_orchestrator(tmp_path, monkeypatch):
    """Fresh tmp .map/<branch>/ + chdir; mirrors branch_dir but for
    map_orchestrator import path (test_map_step_runner.py doesn't import
    map_orchestrator the same way test_map_orchestrator.py does, so we
    isolate the fixture here to keep the test self-contained)."""
    branch = "test-branch"
    map_dir = tmp_path / ".map" / branch
    map_dir.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    return branch


class TestRecordSubtaskBaseline:
    """record_subtask_baseline + per-subtask baseline filter in
    validate_mutation_boundary: each subtask's MONITOR check only flags
    files CHANGED during that subtask, not the cumulative branch diff."""

    def _init_git(self, root: Path) -> None:
        subprocess.run(["git", "init"], cwd=root, capture_output=True, check=False)
        subprocess.run(
            ["git", "config", "user.email", "t@t.com"], cwd=root, capture_output=True
        )
        subprocess.run(
            ["git", "config", "user.name", "t"], cwd=root, capture_output=True
        )
        (root / "seed.txt").write_text("seed")
        subprocess.run(["git", "add", "."], cwd=root, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=root, capture_output=True)

    def test_subtask_baseline_filters_prior_wave_diff(
        self, branch_workspace, monkeypatch
    ):
        repo = branch_workspace.parents[1]
        self._init_git(repo)
        # Prior wave: ST-001 created old_a.py (still uncommitted).
        (repo / "old_a.py").write_text("from prior wave")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        # ST-002 starts: snapshot its baseline (= everything dirty now).
        snap = map_step_runner.record_subtask_baseline("test-branch", "ST-002")
        assert snap["status"] == "success"
        assert "old_a.py" in (
            map_step_runner._subtask_baseline_path(
                "test-branch", "ST-002", repo
            ).parent / "ST-002.json"
        ).read_text()
        # ST-002 declares its scope = b.py; create + add.
        bp = {"subtasks": [{"id": "ST-002", "title": "x", "affected_files": ["b.py"]}]}
        (branch_workspace / "blueprint.json").write_text(json.dumps(bp))
        (repo / "b.py").write_text("x = 1")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
        report = map_step_runner.validate_mutation_boundary(
            "test-branch", "ST-002"
        )
        # old_a.py was in the baseline → filtered → status="clean".
        assert report["status"] == "clean", report
        assert "old_a.py" not in report["actual"]
        assert "b.py" in report["actual"]


class TestRecordScopeBaseline:
    """record_scope_baseline snapshots current git status into
    .map/<branch>/scope-baseline.json; validate_mutation_boundary
    subtracts that set from `actual` so warnings stop flooding when the
    branch carries pre-existing untracked artifacts."""

    def _init_git(self, root: Path) -> None:
        subprocess.run(["git", "init"], cwd=root, capture_output=True, check=False)
        subprocess.run(
            ["git", "config", "user.email", "t@t.com"], cwd=root, capture_output=True
        )
        subprocess.run(
            ["git", "config", "user.name", "t"], cwd=root, capture_output=True
        )
        (root / "seed.txt").write_text("seed")
        subprocess.run(["git", "add", "."], cwd=root, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=root, capture_output=True)

    def test_baseline_excludes_pre_existing_from_warning(
        self, branch_workspace, tmp_path, monkeypatch
    ):
        del tmp_path  # only the underlying repo dir is exercised
        repo = branch_workspace.parents[1]
        self._init_git(repo)
        # Pre-existing untracked file — would normally trigger warning.
        (repo / "old_artifact.md").write_text("from prior wave")
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        baseline = map_step_runner.record_scope_baseline("test-branch")
        assert baseline["status"] == "success"
        assert "old_artifact.md" in baseline["files"]

        bp = {"subtasks": [{"id": "ST-001", "title": "x", "affected_files": ["a.py"]}]}
        (branch_workspace / "blueprint.json").write_text(json.dumps(bp))
        (repo / "a.py").write_text("x = 1")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
        report = map_step_runner.validate_mutation_boundary("test-branch", "ST-001")
        # old_artifact.md was in the baseline → filtered → status="clean".
        assert report["status"] == "clean", report
        assert "old_artifact.md" not in report["actual"]

    def test_warning_includes_diagnostic_hint(
        self, branch_workspace, tmp_path, monkeypatch
    ):
        """Fix #7: when warnings fire and no per-subtask baseline was
        recorded, the report carries an actionable diagnostic_hint so the
        operator can see WHY the base_ref was chosen and how to filter
        prior-subtask noise. Without this, every Monitor pass reads like
        a real scope leak even when it's really stale baseline state.
        """
        del tmp_path
        repo = branch_workspace.parents[1]
        self._init_git(repo)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        bp = {"subtasks": [{"id": "ST-001", "title": "x", "affected_files": ["expected.py"]}]}
        (branch_workspace / "blueprint.json").write_text(json.dumps(bp))
        # Create an unexpected file (not in affected_files, not in baseline).
        (repo / "drifted.py").write_text("unexpected")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
        report = map_step_runner.validate_mutation_boundary("test-branch", "ST-001")
        assert report["status"] == "warning", report
        assert "drifted.py" in report["unexpected"]
        # Diagnostic must explain the operator's options.
        assert "diagnostic_hint" in report
        hint = report["diagnostic_hint"]
        assert "record_scope_baseline" in hint or "record_subtask_baseline" in hint, hint


class TestDetectAlreadyDone:
    """detect_already_done suggests whether a subtask's affected_files
    already have commits in the recent window — pragmatic, not authoritative."""

    def _init_git(self, root: Path, commit_files: list[str]) -> None:
        subprocess.run(["git", "init"], cwd=root, capture_output=True, check=False)
        subprocess.run(
            ["git", "config", "user.email", "t@t.com"], cwd=root, capture_output=True
        )
        subprocess.run(
            ["git", "config", "user.name", "t"], cwd=root, capture_output=True
        )
        (root / "seed.txt").write_text("seed")
        subprocess.run(["git", "add", "."], cwd=root, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=root, capture_output=True)
        for f in commit_files:
            (root / f).write_text(f"content of {f}")
            subprocess.run(["git", "add", "."], cwd=root, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", f"add {f}"], cwd=root, capture_output=True
            )

    def test_likely_done_when_all_affected_have_commits(
        self, branch_workspace, tmp_path, monkeypatch
    ):
        del tmp_path  # only the underlying repo dir is exercised
        repo = branch_workspace.parents[1]
        self._init_git(repo, ["mod_a.py", "mod_b.py"])
        bp = {"subtasks": [{
            "id": "ST-007", "affected_files": ["mod_a.py", "mod_b.py"],
        }]}
        (branch_workspace / "blueprint.json").write_text(json.dumps(bp))
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        # HEAD~5 doesn't resolve in a 3-commit repo; the function should
        # fall back to the entire reachable history and still find commits.
        report = map_step_runner.detect_already_done(
            "test-branch", "ST-007", since_ref="HEAD~5"
        )
        assert report["status"] == "likely_done", report
        assert sorted(report["have_commits"]) == ["mod_a.py", "mod_b.py"]

    def test_unclear_when_files_missing(self, branch_workspace, tmp_path, monkeypatch):
        del tmp_path  # only the underlying repo dir is exercised
        repo = branch_workspace.parents[1]
        self._init_git(repo, [])
        bp = {"subtasks": [{
            "id": "ST-007", "affected_files": ["never_made.py"],
        }]}
        (branch_workspace / "blueprint.json").write_text(json.dumps(bp))
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        report = map_step_runner.detect_already_done("test-branch", "ST-007")
        assert report["status"] == "unclear"
        assert "never_made.py" in report["missing_or_no_commits"]


class TestBuildContextBlockInlinesResearch:
    """build_context_block now auto-loads load_research for the current
    subtask so callers don't have to glue findings into the Actor prompt
    by hand."""

    def test_actor_research_inlined_when_present(self, branch_workspace):
        bp = {"subtasks": [{
            "id": "ST-001", "title": "x", "aag_contract": "X -> y -> done",
        }]}
        (branch_workspace / "blueprint.json").write_text(json.dumps(bp))
        # Plant research artifact via the canonical API.
        map_step_runner.save_research("test-branch", "ST-001", "Pivotal finding: foo wraps bar.")
        result = map_step_runner.build_context_block("test-branch", "ST-001")
        assert "# Research Findings (ST-001, kind=actor):" in result
        assert "Pivotal finding: foo wraps bar." in result

    def test_no_research_section_when_artifact_absent(self, branch_workspace):
        bp = {"subtasks": [{"id": "ST-001", "title": "x"}]}
        (branch_workspace / "blueprint.json").write_text(json.dumps(bp))
        result = map_step_runner.build_context_block("test-branch", "ST-001")
        assert "# Research Findings" not in result


class TestValidateMutationBoundary:
    """validate_mutation_boundary compares actual git diff vs the planned
    affected_files surface. Warn-only by default; MAP_STRICT_SCOPE=1 escalates
    to status='violation' and CLI exit 1 so callers (Monitor) can hard-fail.
    """

    def _init_git(self, root: Path) -> None:
        subprocess.run(["git", "init"], cwd=root, capture_output=True, check=False)
        subprocess.run(
            ["git", "config", "user.email", "t@t.com"], cwd=root, capture_output=True
        )
        subprocess.run(
            ["git", "config", "user.name", "t"], cwd=root, capture_output=True
        )

    def _write_blueprint(self, branch_dir: Path, subtask_id: str, files: list[str]) -> None:
        bp = {
            "summary": "test",
            "subtasks": [
                {"id": subtask_id, "title": "x", "affected_files": files}
            ],
        }
        (branch_dir / "blueprint.json").write_text(json.dumps(bp))

    def test_clean_when_diff_matches_affected_files(self, branch_workspace, monkeypatch):
        repo = branch_workspace.parents[1]
        self._init_git(repo)
        self._write_blueprint(branch_workspace, "ST-001", ["a.py"])
        (repo / "a.py").write_text("x = 1\n")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        report = map_step_runner.validate_mutation_boundary("test-branch", "ST-001")
        assert report["status"] == "clean", report
        assert report["unexpected"] == []

    def test_warning_when_diff_exceeds_affected_files(
        self, branch_workspace, monkeypatch
    ):
        repo = branch_workspace.parents[1]
        self._init_git(repo)
        self._write_blueprint(branch_workspace, "ST-001", ["a.py"])
        (repo / "a.py").write_text("x = 1\n")
        (repo / "b.py").write_text("y = 2\n")  # NOT in affected_files
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        monkeypatch.delenv("MAP_STRICT_SCOPE", raising=False)
        report = map_step_runner.validate_mutation_boundary("test-branch", "ST-001")
        assert report["status"] == "warning", report
        assert "b.py" in report["unexpected"]
        log = branch_workspace / "scope-violations.log"
        assert log.exists(), "warning must be appended to scope-violations.log"

    def test_warning_on_untracked_new_out_of_scope_file(
        self, branch_workspace, monkeypatch
    ):
        """A NEW out-of-scope file the actor creates but never ``git add``s must
        still be flagged — `git status --porcelain` '??' untracked paths count
        as actual changes. This is the real-world scope leak (e.g. the actor
        creates ``src/constants.py`` that is not in ``affected_files``); the
        committed/staged-only tests above would miss it.
        """
        repo = branch_workspace.parents[1]
        self._init_git(repo)
        self._write_blueprint(branch_workspace, "ST-001", ["a.py"])
        (repo / "a.py").write_text("x = 1\n")
        subprocess.run(["git", "add", "a.py"], cwd=repo, capture_output=True)  # in-scope, staged
        (repo / "constants.py").write_text("RATE = 15\n")  # out-of-scope, NEVER added (untracked '??')
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        monkeypatch.delenv("MAP_STRICT_SCOPE", raising=False)
        report = map_step_runner.validate_mutation_boundary("test-branch", "ST-001")
        assert report["status"] == "warning", report
        assert "constants.py" in report["unexpected"], report
        assert "a.py" not in report["unexpected"], report

    def test_violation_when_strict_mode_enabled(self, branch_workspace, monkeypatch):
        repo = branch_workspace.parents[1]
        self._init_git(repo)
        self._write_blueprint(branch_workspace, "ST-001", ["a.py"])
        (repo / "b.py").write_text("y = 2\n")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        monkeypatch.setenv("MAP_STRICT_SCOPE", "1")
        report = map_step_runner.validate_mutation_boundary("test-branch", "ST-001")
        assert report["status"] == "violation"
        assert report["strict"] is True

    def test_error_when_blueprint_missing(self, branch_workspace, monkeypatch):
        repo = branch_workspace.parents[1]
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        report = map_step_runner.validate_mutation_boundary("test-branch", "ST-001")
        assert report["status"] == "error"

    def test_error_when_subtask_unknown(self, branch_workspace, monkeypatch):
        repo = branch_workspace.parents[1]
        self._write_blueprint(branch_workspace, "ST-001", ["a.py"])
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        report = map_step_runner.validate_mutation_boundary("test-branch", "ST-999")
        assert report["status"] == "error"
        assert "ST-999" in report["message"]

    def test_error_when_not_a_git_repo(self, branch_workspace, monkeypatch):
        """git status non-zero (no .git) → error, NOT a silent 'clean'."""
        repo = branch_workspace.parents[1]
        self._write_blueprint(branch_workspace, "ST-001", ["a.py"])
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        report = map_step_runner.validate_mutation_boundary("test-branch", "ST-001")
        assert report["status"] == "error", report
        assert "git" in report["message"].lower()

    def test_cli_exits_non_zero_on_error_status(self, branch_workspace, tmp_path):
        """Monitor's mandatory gate must not silently pass when blueprint is
        missing — exit 1 is the only signal `set -e` callers can rely on."""
        del branch_workspace
        runner = (
            Path(__file__).resolve().parents[1]
            / "src" / "mapify_cli" / "templates" / "map" / "scripts" / "map_step_runner.py"
        )
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "CLAUDE_PROJECT_DIR": str(tmp_path)}
        result = subprocess.run(
            [sys.executable, str(runner), "validate_mutation_boundary", "no-such-branch", "ST-001"],
            capture_output=True, text=True, cwd=str(tmp_path), env=env,
        )
        assert result.returncode != 0, (
            f"CLI must exit non-zero on status='error'; stdout={result.stdout!r}"
        )
        report = json.loads(result.stdout)
        assert report["status"] == "error"

    def test_co_authored_test_file_not_flagged_as_scope_leak(
        self, branch_workspace, monkeypatch
    ):
        """#163: a co-authored test file beside the production module (same dir)
        is implied by the test-alongside policy — it must NOT be reported as a
        scope leak even though the decomposer only listed the production file in
        affected_files. It stays in `actual` and surfaces in `allowed_test_files`.
        """
        repo = branch_workspace.parents[1]
        self._init_git(repo)
        self._write_blueprint(branch_workspace, "ST-001", ["pipeline/foo.py"])
        (repo / "pipeline").mkdir()
        (repo / "pipeline" / "foo.py").write_text("x = 1\n")  # in affected_files
        (repo / "pipeline" / "test_foo.py").write_text("def test_x(): pass\n")  # co-authored test
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        monkeypatch.delenv("MAP_STRICT_SCOPE", raising=False)
        report = map_step_runner.validate_mutation_boundary("test-branch", "ST-001")
        assert report["status"] == "clean", report
        assert report["unexpected"] == [], report
        assert "pipeline/test_foo.py" in report["allowed_test_files"], report
        assert "pipeline/test_foo.py" in report["actual"], report  # reality preserved

    def test_co_authored_test_in_separate_tree_not_flagged(
        self, branch_workspace, monkeypatch
    ):
        """#163: the common src/ + tests/ split — affected_files lists
        ``src/foo.py`` while the test lives under a separate ``tests/`` tree.
        The test file must still be auto-allowed (a same-dir-only rule would
        wrongly flag this very repo's own layout).
        """
        repo = branch_workspace.parents[1]
        self._init_git(repo)
        self._write_blueprint(branch_workspace, "ST-001", ["src/foo.py"])
        (repo / "src").mkdir()
        (repo / "src" / "foo.py").write_text("x = 1\n")
        (repo / "tests").mkdir()
        (repo / "tests" / "test_foo.py").write_text("def test_x(): pass\n")
        (repo / "tests" / "conftest.py").write_text("import pytest\n")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        monkeypatch.delenv("MAP_STRICT_SCOPE", raising=False)
        report = map_step_runner.validate_mutation_boundary("test-branch", "ST-001")
        assert report["status"] == "clean", report
        assert report["unexpected"] == [], report
        assert set(report["allowed_test_files"]) == {
            "tests/test_foo.py",
            "tests/conftest.py",
        }, report

    def test_real_source_leak_still_flagged_when_mixed_with_test(
        self, branch_workspace, monkeypatch
    ):
        """#163 must NOT mask a genuine production scope leak: an out-of-scope
        *source* file is still `unexpected`, while a co-authored test file is
        partitioned into `allowed_test_files` — the partition is by convention,
        not a blanket suppression.
        """
        repo = branch_workspace.parents[1]
        self._init_git(repo)
        self._write_blueprint(branch_workspace, "ST-001", ["a.py"])
        (repo / "a.py").write_text("x = 1\n")  # in scope
        (repo / "b.py").write_text("y = 2\n")  # out-of-scope SOURCE — real leak
        (repo / "test_b.py").write_text("def test_y(): pass\n")  # out-of-scope TEST — allowed
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        monkeypatch.delenv("MAP_STRICT_SCOPE", raising=False)
        report = map_step_runner.validate_mutation_boundary("test-branch", "ST-001")
        assert report["status"] == "warning", report
        assert report["unexpected"] == ["b.py"], report
        assert report["allowed_test_files"] == ["test_b.py"], report

    def test_co_authored_test_not_a_violation_even_in_strict_mode(
        self, branch_workspace, monkeypatch
    ):
        """The test-alongside allowance holds under MAP_STRICT_SCOPE=1 too: a
        co-authored test file alone must not escalate to status='violation'.
        """
        repo = branch_workspace.parents[1]
        self._init_git(repo)
        self._write_blueprint(branch_workspace, "ST-001", ["a.py"])
        (repo / "a.py").write_text("x = 1\n")
        (repo / "a_test.py").write_text("def test_x(): pass\n")  # co-authored test
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        monkeypatch.setenv("MAP_STRICT_SCOPE", "1")
        report = map_step_runner.validate_mutation_boundary("test-branch", "ST-001")
        assert report["status"] == "clean", report
        assert report["unexpected"] == [], report
        assert report["allowed_test_files"] == ["a_test.py"], report

    def test_already_committed_subtask_diffs_against_parent(
        self, branch_workspace, monkeypatch
    ):
        """#162: the documented per-subtask close order is
        commit -> record_subtask_result --commit-sha -> validate_step 2.4.
        After the commit the working tree is CLEAN and last_subtask_commit_sha
        points at THIS subtask's own commit, so a diff against it is empty and
        previously mis-reported actual=[] (false-progress). The validator must
        re-base onto the commit's parent so the committed work shows up as
        actual.
        """
        repo = branch_workspace.parents[1]
        self._init_git(repo)
        self._write_blueprint(branch_workspace, "ST-001", ["a.py"])
        # Parent commit (prior history), then ST-001's actual work as its own
        # commit — exactly the per-subtask-commit lifecycle.
        (repo / "seed.txt").write_text("seed\n")
        subprocess.run(["git", "add", "seed.txt"], cwd=repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True)
        (repo / "a.py").write_text("x = 1\n")
        subprocess.run(["git", "add", "a.py"], cwd=repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "ST-001"], cwd=repo, capture_output=True)
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True
        ).stdout.strip()
        # Mimic record_subtask_result --commit-sha <SHA>: it advances
        # last_subtask_commit_sha AND records the per-subtask commit_sha.
        (branch_workspace / "step_state.json").write_text(
            json.dumps(
                {
                    "last_subtask_commit_sha": sha,
                    "subtask_results": {"ST-001": {"commit_sha": sha}},
                }
            )
        )
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        monkeypatch.delenv("MAP_STRICT_SCOPE", raising=False)
        report = map_step_runner.validate_mutation_boundary("test-branch", "ST-001")
        assert report["status"] == "clean", report
        assert report["actual"] == ["a.py"], report  # committed work IS visible
        assert report["unexpected"] == [], report
        # base_ref re-based onto the parent (the committed SHA's ^), not the
        # commit itself (which would diff to nothing).
        assert report["base_ref"] == f"{sha}^", report

    def test_genuinely_empty_subtask_still_reports_no_actual(
        self, branch_workspace, monkeypatch
    ):
        """Negative guard for #162: when the subtask has NO recorded commit and
        nothing changed in the worktree, actual must stay empty so the
        orchestrator's false-progress check still fires for a subtask that did
        nothing. The #162 re-base only kicks in when the resolved base IS the
        subtask's own recorded commit.
        """
        repo = branch_workspace.parents[1]
        self._init_git(repo)
        self._write_blueprint(branch_workspace, "ST-001", ["a.py"])
        (repo / "seed.txt").write_text("seed\n")
        subprocess.run(["git", "add", "seed.txt"], cwd=repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True)
        # No commit recorded for ST-001, no work done — base_ref falls back to
        # HEAD (the prior commit), diff is empty.
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        monkeypatch.delenv("MAP_STRICT_SCOPE", raising=False)
        report = map_step_runner.validate_mutation_boundary("test-branch", "ST-001")
        assert report["status"] == "clean", report
        assert report["actual"] == [], report  # nothing changed -> false-progress can fire


class TestDetectCrossSubtaskRegressionRisk:
    """detect_cross_subtask_regression_risk flags when the in-flight subtask
    edits files that a PRIOR subtask owned — the signal the skill uses to
    force a full test suite (vs a -k subset) so a cross-subtask regression
    can't slip past per-subtask Monitor to the final gate.
    """

    def _init_git(self, root: Path) -> None:
        subprocess.run(["git", "init"], cwd=root, capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "t@t.com"], cwd=root, capture_output=True, check=True
        )
        subprocess.run(
            ["git", "config", "user.name", "t"], cwd=root, capture_output=True, check=True
        )
        # An initial commit so HEAD resolves (base_ref). Assert it lands — a
        # swallowed commit failure would leave HEAD unresolved and let the
        # detector fall through to porcelain-only, silently weakening the tests.
        (root / ".seed").write_text("seed\n")
        subprocess.run(["git", "add", "."], cwd=root, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "init"], cwd=root, capture_output=True, check=True
        )
        head = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"],
            cwd=root, capture_output=True, text=True,
        )
        assert head.returncode == 0, "test setup: initial commit produced no resolvable HEAD"

    def _write_state(self, branch_dir: Path, subtask_results: dict) -> None:
        (branch_dir / "step_state.json").write_text(
            json.dumps({"subtask_results": subtask_results})
        )

    def test_stale_base_ref_fails_safe_to_full_suite(
        self, branch_workspace, monkeypatch
    ):
        """A stale last_subtask_commit_sha (e.g. after a rebase) makes
        `git diff <sha>` fail. The detector must fail safe to full_suite rather
        than report 'scoped' from porcelain alone on a clean worktree."""
        repo = branch_workspace.parents[1]
        self._init_git(repo)
        (branch_workspace / "step_state.json").write_text(
            json.dumps(
                {
                    "subtask_results": {"ST-001": {"files_changed": ["src/pipeline.py"]}},
                    "last_subtask_commit_sha": "0" * 40,  # nonexistent commit
                }
            )
        )
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        report = map_step_runner.detect_cross_subtask_regression_risk(
            "test-branch", "ST-002"
        )
        assert report["status"] == "unknown", report
        assert report["at_risk"] is True
        assert report["recommended_gate"] == "full_suite"

    def test_shared_source_file_is_at_risk_full_suite(
        self, branch_workspace, monkeypatch
    ):
        repo = branch_workspace.parents[1]
        self._init_git(repo)
        self._write_state(
            branch_workspace,
            {"ST-001": {"files_changed": ["src/pipeline.py"]}},
        )
        # Current subtask (ST-002) edits the SAME source file. Stage it so
        # `git status --porcelain` reports the full path (untracked-only
        # directories collapse to `src/`).
        (repo / "src").mkdir()
        (repo / "src" / "pipeline.py").write_text("x = 1\n")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        report = map_step_runner.detect_cross_subtask_regression_risk(
            "test-branch", "ST-002"
        )
        assert report["status"] == "ok", report
        assert report["at_risk"] is True
        assert report["recommended_gate"] == "full_suite"
        assert "src/pipeline.py" in report["shared_source_files"]
        assert report["prior_owners"]["src/pipeline.py"] == ["ST-001"]

    def test_disjoint_files_not_at_risk_scoped(self, branch_workspace, monkeypatch):
        repo = branch_workspace.parents[1]
        self._init_git(repo)
        self._write_state(
            branch_workspace,
            {"ST-001": {"files_changed": ["src/other.py"]}},
        )
        (repo / "src").mkdir()
        (repo / "src" / "pipeline.py").write_text("x = 1\n")  # different file
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        report = map_step_runner.detect_cross_subtask_regression_risk(
            "test-branch", "ST-002"
        )
        assert report["status"] == "ok", report
        assert report["at_risk"] is False
        assert report["recommended_gate"] == "scoped"
        assert report["shared_files"] == []

    def test_shared_test_only_file_is_not_at_risk(
        self, branch_workspace, monkeypatch
    ):
        """Two subtasks editing the same TEST file is a weak signal — it can't
        regress another subtask's production code, so stay scoped."""
        repo = branch_workspace.parents[1]
        self._init_git(repo)
        self._write_state(
            branch_workspace,
            {"ST-001": {"files_changed": ["tests/test_pipeline.py"]}},
        )
        (repo / "tests").mkdir()
        (repo / "tests" / "test_pipeline.py").write_text("def test_x(): pass\n")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        report = map_step_runner.detect_cross_subtask_regression_risk(
            "test-branch", "ST-002"
        )
        assert report["at_risk"] is False
        assert report["recommended_gate"] == "scoped"
        assert "tests/test_pipeline.py" in report["shared_test_files"]
        assert report["shared_source_files"] == []

    def test_no_prior_subtasks_not_at_risk(self, branch_workspace, monkeypatch):
        repo = branch_workspace.parents[1]
        self._init_git(repo)
        self._write_state(branch_workspace, {})
        (repo / "src").mkdir()
        (repo / "src" / "pipeline.py").write_text("x = 1\n")
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        report = map_step_runner.detect_cross_subtask_regression_risk(
            "test-branch", "ST-001"
        )
        assert report["at_risk"] is False
        assert report["recommended_gate"] == "scoped"

    def test_current_subtask_excluded_from_prior_owners(
        self, branch_workspace, monkeypatch
    ):
        """A subtask's own prior record (e.g. on a retry) must not count as a
        cross-subtask collision with itself."""
        repo = branch_workspace.parents[1]
        self._init_git(repo)
        self._write_state(
            branch_workspace,
            {"ST-002": {"files_changed": ["src/pipeline.py"]}},
        )
        (repo / "src").mkdir()
        (repo / "src" / "pipeline.py").write_text("x = 1\n")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        report = map_step_runner.detect_cross_subtask_regression_risk(
            "test-branch", "ST-002"
        )
        assert "src/pipeline.py" in report["current_changed_files"]
        assert report["at_risk"] is False
        assert report["shared_files"] == []

    def test_git_failure_fails_safe_to_full_suite(
        self, branch_workspace, monkeypatch
    ):
        """No git repo → diff can't be computed → unknown + full_suite, never a
        silent scoped pass."""
        repo = branch_workspace.parents[1]  # NOT a git repo
        self._write_state(
            branch_workspace,
            {"ST-001": {"files_changed": ["src/pipeline.py"]}},
        )
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        report = map_step_runner.detect_cross_subtask_regression_risk(
            "test-branch", "ST-002"
        )
        assert report["status"] == "unknown", report
        assert report["at_risk"] is True
        assert report["recommended_gate"] == "full_suite"

    def test_cli_exits_zero_and_emits_json(self, branch_workspace):
        """CLI is advisory: exit 0 always so shell callers branch on the
        `recommended_gate` field without `set -e` tripping."""
        self._init_git(branch_workspace.parents[1])
        self._write_state(branch_workspace, {})
        runner = (
            Path(__file__).resolve().parents[1]
            / "src" / "mapify_cli" / "templates" / "map" / "scripts" / "map_step_runner.py"
        )
        repo = branch_workspace.parents[1]
        env = {
            **os.environ,
            "PYTHONDONTWRITEBYTECODE": "1",
            "CLAUDE_PROJECT_DIR": str(repo),
        }
        result = subprocess.run(
            [sys.executable, str(runner),
             "detect_cross_subtask_regression_risk", "test-branch", "ST-001"],
            capture_output=True, text=True, cwd=str(repo), env=env,
        )
        assert result.returncode == 0, result.stderr
        report = json.loads(result.stdout)
        assert report["recommended_gate"] in {"full_suite", "scoped"}

    def test_is_test_path_heuristic(self):
        assert map_step_runner._is_test_path("tests/test_x.py")
        assert map_step_runner._is_test_path("pkg/foo_test.go")
        assert map_step_runner._is_test_path("web/button.spec.ts")
        assert map_step_runner._is_test_path("a/__tests__/b.js")
        # pytest conftest.py is test infrastructure at any depth (#163)
        assert map_step_runner._is_test_path("conftest.py")
        assert map_step_runner._is_test_path("python/pipeline/conftest.py")
        assert not map_step_runner._is_test_path("src/pipeline.py")
        assert not map_step_runner._is_test_path("contest.py")  # not "conftest"


class TestGetSubtaskCli:
    """get_subtask CLI normalizes the {flat, blueprint-wrapped} blueprint
    schema so callers don't need ad-hoc jq with two fallbacks."""

    def _runner(self) -> Path:
        return (
            Path(__file__).resolve().parents[1]
            / "src" / "mapify_cli" / "templates" / "map" / "scripts" / "map_step_runner.py"
        )

    def test_returns_subtask_json_from_flat_blueprint(self, branch_workspace, tmp_path):
        bp = {"subtasks": [{"id": "ST-001", "title": "first"}]}
        (branch_workspace / "blueprint.json").write_text(json.dumps(bp))
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        result = subprocess.run(
            [sys.executable, str(self._runner()), "get_subtask", "ST-001",
             "--branch", "test-branch"],
            capture_output=True, text=True, cwd=str(tmp_path), env=env,
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["id"] == "ST-001"
        assert payload["title"] == "first"

    def test_returns_subtask_from_blueprint_wrapped_shape(
        self, branch_workspace, tmp_path
    ):
        bp = {"blueprint": {"subtasks": [{"id": "ST-002", "title": "second"}]}}
        (branch_workspace / "blueprint.json").write_text(json.dumps(bp))
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        result = subprocess.run(
            [sys.executable, str(self._runner()), "get_subtask", "ST-002",
             "--branch", "test-branch"],
            capture_output=True, text=True, cwd=str(tmp_path), env=env,
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["id"] == "ST-002"

    def test_exits_non_zero_on_unknown_subtask(self, branch_workspace, tmp_path):
        bp = {"subtasks": [{"id": "ST-001"}]}
        (branch_workspace / "blueprint.json").write_text(json.dumps(bp))
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        result = subprocess.run(
            [sys.executable, str(self._runner()), "get_subtask", "ST-999",
             "--branch", "test-branch"],
            capture_output=True, text=True, cwd=str(tmp_path), env=env,
        )
        assert result.returncode == 1
        assert "ST-999" in result.stderr


class TestLoadResearchCliErrorChannel:
    """load_research CLI must write error JSON to STDERR, not STDOUT, so
    command substitution (`FOO=$(... load_research ...)`) is not corrupted."""

    def test_invalid_subtask_id_writes_to_stderr_keeps_stdout_empty(
        self, branch_workspace, tmp_path
    ):
        del branch_workspace
        runner = (
            Path(__file__).resolve().parents[1]
            / "src" / "mapify_cli" / "templates" / "map" / "scripts" / "map_step_runner.py"
        )
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        # ".." triggers ValueError from _research_path's sanitization.
        result = subprocess.run(
            [sys.executable, str(runner), "load_research", "test-branch", "../escape"],
            capture_output=True, text=True, cwd=str(tmp_path), env=env,
        )
        assert result.returncode == 1
        assert result.stdout == "", f"stdout must be empty; got {result.stdout!r}"
        assert "error" in result.stderr.lower()


class TestSaveLoadResearch:
    """Tests for save_research / load_research subtask-scoped artifact API.

    Provides a durable storage contract for research-agent output so Actor and
    Monitor consume findings through the same path rather than ad-hoc bash. The
    .map/<branch>/research/<subtask_id>__<kind>.md layout keeps multiple agent
    kinds (actor, monitor, decomposer, ...) side-by-side without collisions.
    """

    def test_save_then_load_round_trips_content(self, branch_workspace):
        del branch_workspace
        content = "## Findings\n\n- API surface: foo()\n- Tests live in tests/foo_test.py\n"
        path = map_step_runner.save_research("test-branch", "ST-001", content)
        assert Path(path).exists()
        loaded = map_step_runner.load_research("test-branch", "ST-001")
        assert loaded == content

    def test_load_returns_empty_string_when_missing(self, branch_workspace):
        del branch_workspace
        assert map_step_runner.load_research("test-branch", "ST-999") == ""

    def test_kind_partitions_storage(self, branch_workspace):
        del branch_workspace
        map_step_runner.save_research(
            "test-branch", "ST-001", "actor view", kind="actor"
        )
        map_step_runner.save_research(
            "test-branch", "ST-001", "monitor view", kind="monitor"
        )
        assert (
            map_step_runner.load_research("test-branch", "ST-001", kind="actor")
            == "actor view"
        )
        assert (
            map_step_runner.load_research("test-branch", "ST-001", kind="monitor")
            == "monitor view"
        )

    def test_save_overwrites_prior_content_for_same_kind(self, branch_workspace):
        del branch_workspace
        map_step_runner.save_research("test-branch", "ST-001", "v1")
        map_step_runner.save_research("test-branch", "ST-001", "v2 with new finding")
        assert map_step_runner.load_research("test-branch", "ST-001") == "v2 with new finding"

    def test_branch_is_sanitized(self, branch_workspace, tmp_path, monkeypatch):
        """`feature/x` is sanitized to `feature-x` — no literal `/` subdir."""
        del branch_workspace
        # Pre-create the sanitized branch dir so write doesn't hit a permission
        # issue if the fixture only made one branch dir.
        (tmp_path / ".map" / "feature-x").mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        path = map_step_runner.save_research("feature/x", "ST-001", "hi")
        assert "/feature-x/research/" in path, path
        # Hard contract: the literal unsanitized form must NOT appear.
        assert "/feature/x/research/" not in path, path

    def test_subtask_id_must_be_safe(self, branch_workspace):
        """Path-traversal in subtask_id is rejected."""
        del branch_workspace
        with pytest.raises(ValueError):
            map_step_runner.save_research("test-branch", "../escape", "x")
        with pytest.raises(ValueError):
            map_step_runner.load_research("test-branch", "../escape")

    def test_merge_all_kinds_concatenates_present_kinds(self, branch_workspace):
        """merge_all_kinds=True returns a section-headed concat of every kind
        on disk, ordered actor → monitor → decomposer → others. Resolves the
        recurring friction where Monitor's own research was invisible
        unless callers happened to pass kind="monitor"."""
        del branch_workspace
        map_step_runner.save_research(
            "test-branch", "ST-001", "actor findings", kind="actor"
        )
        map_step_runner.save_research(
            "test-branch", "ST-001", "monitor verdict notes", kind="monitor"
        )
        map_step_runner.save_research(
            "test-branch", "ST-001", "decomposer scoping", kind="decomposer"
        )
        merged = map_step_runner.load_research(
            "test-branch", "ST-001", merge_all_kinds=True
        )
        # All three sections present, in canonical order.
        for needle in (
            "# kind=actor",
            "actor findings",
            "# kind=monitor",
            "monitor verdict notes",
            "# kind=decomposer",
            "decomposer scoping",
        ):
            assert needle in merged, merged
        assert merged.index("# kind=actor") < merged.index("# kind=monitor")
        assert merged.index("# kind=monitor") < merged.index("# kind=decomposer")

    def test_merge_all_kinds_returns_empty_when_nothing_present(self, branch_workspace):
        del branch_workspace
        assert (
            map_step_runner.load_research(
                "test-branch", "ST-999", merge_all_kinds=True
            )
            == ""
        )

    def test_merge_all_handles_unknown_kind_after_canonical(self, branch_workspace):
        """Custom kinds get sorted lexicographically after actor/monitor/decomposer."""
        del branch_workspace
        map_step_runner.save_research("test-branch", "ST-001", "actor", kind="actor")
        map_step_runner.save_research(
            "test-branch", "ST-001", "zebra notes", kind="zebra"
        )
        merged = map_step_runner.load_research(
            "test-branch", "ST-001", merge_all_kinds=True
        )
        assert merged.index("# kind=actor") < merged.index("# kind=zebra")

    def test_kind_must_be_safe(self, branch_workspace):
        """kind must match a conservative ident pattern."""
        del branch_workspace
        with pytest.raises(ValueError):
            map_step_runner.save_research("test-branch", "ST-001", "x", kind="../foo")

    def test_cli_save_reads_stdin_load_writes_stdout(self, branch_workspace, tmp_path):
        """End-to-end CLI: save_research consumes stdin, load_research prints stdout."""
        del branch_workspace
        runner = (
            Path(__file__).resolve().parents[1]
            / "src" / "mapify_cli" / "templates" / "map" / "scripts" / "map_step_runner.py"
        )
        # Force PYTHONDONTWRITEBYTECODE so subprocess imports don't pollute
        # src/mapify_cli/templates/map/scripts/__pycache__ — the template-
        # hygiene gate fails if any .pyc is shipped under templates/.
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        content = "Research note from CLI"
        save_result = subprocess.run(
            [sys.executable, str(runner), "save_research", "test-branch", "ST-007"],
            input=content,
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            env=env,
        )
        assert save_result.returncode == 0, save_result.stderr
        load_result = subprocess.run(
            [sys.executable, str(runner), "load_research", "test-branch", "ST-007"],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            env=env,
        )
        assert load_result.returncode == 0, load_result.stderr
        assert load_result.stdout == content


class TestSanitizeForJson:
    """Regression coverage for `_sanitize_for_json` hardening (PR #105).

    Earlier version preserved ``\\t \\n \\r`` and relied on ``json.dumps`` to
    escape them. Bash command substitution (``BUNDLE=$(... step_runner ...)``)
    does not preserve byte-perfect roundtrip in all locales, so ``jq``
    received raw control bytes and aborted with::

        Invalid string: control characters from U+0000 through U+001F
        must be escaped at line N, column M

    Hardened function flattens newline variants to spaces and strips the
    full ``\\x00-\\x1f\\x7f`` range. These tests pin that contract.
    """

    @pytest.mark.parametrize(
        "control_char",
        [
            "\x00",
            "\x01",
            "\x02",
            "\x07",
            "\x08",
            "\x0b",
            "\x0c",
            "\x0e",
            "\x1f",
            "\x7f",
        ],
    )
    def test_strips_other_c0_and_del(self, control_char):
        result = map_step_runner._sanitize_for_json(f"a{control_char}b")
        assert control_char not in result
        assert result == "ab"

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("line1\r\nline2", "line1 line2"),
            ("line1\rline2", "line1 line2"),
            ("line1\nline2", "line1 line2"),
            ("col1\tcol2", "col1 col2"),
            ("multi\r\n\nlines\twith\ttabs", "multi  lines with tabs"),
        ],
    )
    def test_flattens_newlines_and_tabs_to_spaces(self, raw, expected):
        assert map_step_runner._sanitize_for_json(raw) == expected

    def test_preserves_printable_ascii_and_unicode(self):
        text = "plain ASCII + Кириллица + 中文 + 🚀"
        assert map_step_runner._sanitize_for_json(text) == text

    def test_output_round_trips_through_json_with_no_raw_controls(self):
        """End-to-end: nasty input → sanitize → json.dumps → json.loads.

        Decoded value must be free of any C0 control or DEL byte —
        otherwise a downstream bash pipeline + jq would reject it.
        """
        nasty = "header\r\n\t\x07details\x00with\x1fnoise\x7f end"
        sanitized = map_step_runner._sanitize_for_json(nasty)
        encoded = json.dumps({"k": sanitized}, indent=2, ensure_ascii=True)
        decoded = json.loads(encoded)
        for c in decoded["k"]:
            assert ord(c) >= 0x20 and c != "\x7f", (
                f"control char leaked through sanitize: {c!r}"
            )

    def test_handoff_bundle_strips_artifact_control_chars(
        self, branch_workspace
    ):
        """Integration check: bundle fields built from on-disk artifacts must
        not carry the source's raw C0/DEL bytes through to the JSON output.

        ``build_handoff_bundle`` itself uses ``"\\n".join(...)`` as a separator
        between summary/validation/risks lines — those Python newlines are
        correctly escaped by ``json.dumps`` and survive jq, so we don't
        forbid them. What we forbid is ``\\r``, ``\\t``, NUL, or other C0/DEL
        bytes that came from the artifact body before sanitisation.
        """
        nasty = "fail\r\n\tdetails\x00with\x1fnoise\x07 end\x7f"
        (branch_workspace / "verification-summary.md").write_text(
            nasty, encoding="utf-8"
        )

        bundle = map_step_runner.build_handoff_bundle()
        encoded = json.dumps(bundle, indent=2, ensure_ascii=True)
        decoded = json.loads(encoded)  # round-trip must succeed (jq would too)

        validation = decoded["validation"]
        for ch in ("\x00", "\x07", "\x1f", "\x7f", "\r", "\t"):
            assert ch not in validation, (
                f"raw {ch!r} from artifact leaked into bundle.validation"
            )
        # Words from the original artifact must still appear (just flattened)
        assert "fail" in validation
        assert "details" in validation
        assert "noise" in validation


class TestSanitizeForJsonProperty:
    """Property-based coverage for ``_sanitize_for_json`` via Hypothesis."""

    def test_strips_every_control_byte_for_arbitrary_strings(self):
        from hypothesis import given, strategies as st

        @given(st.text())
        def _prop(raw: str) -> None:
            sanitized = map_step_runner._sanitize_for_json(raw)
            # Function must never raise on arbitrary text inputs.
            # All C0 (U+0000 — U+001F) and DEL (U+007F) bytes must be absent.
            for ch in sanitized:
                code = ord(ch)
                assert not (0x00 <= code <= 0x1F), (
                    f"C0 control U+{code:04X} leaked into output: {sanitized!r}"
                )
                assert code != 0x7F, (
                    f"DEL U+007F leaked into output: {sanitized!r}"
                )

        _prop()


# ---------------------------------------------------------------------------
# create_review_bundle — focused unit tests (ST-001 / ST-002)
# ---------------------------------------------------------------------------


class TestCreateReviewBundle:
    """Focused tests for create_review_bundle."""

    def test_create_review_bundle_full_workspace(self, branch_workspace):
        """Populate workspace with every artifact kind, assert files + status."""
        branch = "test-branch"
        # Fixed artifacts
        (branch_workspace / f"spec_{branch}.md").write_text("# Spec\n", encoding="utf-8")
        (branch_workspace / f"task_plan_{branch}.md").write_text("# Task Plan\n", encoding="utf-8")
        (branch_workspace / "blueprint.json").write_text('{"waves":[]}', encoding="utf-8")
        (branch_workspace / "verification-summary.md").write_text("# Verification\n", encoding="utf-8")
        (branch_workspace / "qa-001.md").write_text("# QA\n", encoding="utf-8")
        (branch_workspace / "pr-draft.md").write_text("# PR Draft\n", encoding="utf-8")
        (branch_workspace / "active-issues.json").write_text('{"issues":[]}', encoding="utf-8")
        # Numbered artifacts
        (branch_workspace / "plan-review-001.md").write_text("# Plan Review\n", encoding="utf-8")
        (branch_workspace / "code-review-001.md").write_text("# Code Review\n", encoding="utf-8")
        # Multi-artifacts
        (branch_workspace / "test_handoff_001.json").write_text('{"tests":[]}', encoding="utf-8")
        (branch_workspace / "test_contract_001.md").write_text("# Contract\n", encoding="utf-8")

        result = map_step_runner.create_review_bundle()

        assert result["status"] == "success"
        assert (branch_workspace / "review-bundle.json").exists()
        assert (branch_workspace / "review-bundle.md").exists()
        assert result["prior_stage_consumption"]["stage"] == "review"
        # Every fixed-kind entry must be present=True
        artifacts = result["artifacts"]
        for key in ("spec", "task_plan", "blueprint", "verification_summary",
                    "qa", "pr_draft", "active_issues"):
            assert artifacts[key]["present"] is True, f"{key} should be present"

    def test_create_review_bundle_empty_workspace(self, branch_workspace):
        """Empty workspace: status==success, fixed entries present=False, files written."""
        del branch_workspace  # fixture only needed for chdir + monkeypatch side effects

        result = map_step_runner.create_review_bundle()

        assert result["status"] == "success"
        assert Path(result["bundle_path_json"]).exists()
        assert Path(result["bundle_path_md"]).exists()
        artifacts = result["artifacts"]
        for key in ("spec", "task_plan", "blueprint", "verification_summary",
                    "qa", "pr_draft", "active_issues"):
            entry = artifacts[key]
            assert entry["present"] is False, f"{key} should be absent"
            assert entry.get("reason") is not None, f"{key} should have a reason"
        # review_handoff and pr_handoff must always be present in result
        assert "review_handoff" in result
        assert "pr_handoff" in result

    def test_create_review_bundle_sanitizes_control_characters(self, branch_workspace):
        """Artifact with control characters must produce a JSON-parseable bundle."""
        nasty = "header\r\n\tdetails\x00with\x1fnoise\x07 end\x7f"
        (branch_workspace / "qa-001.md").write_text(nasty, encoding="utf-8")

        result = map_step_runner.create_review_bundle()

        bundle_path = Path(result["bundle_path_json"])
        with bundle_path.open(encoding="utf-8") as fh:
            loaded = json.load(fh)  # must not raise
        # The sanitized text must not contain raw C0/DEL bytes
        qa_text = loaded["artifacts"]["qa"]["sanitized_text"] or ""
        for ch in ("\x00", "\x07", "\x1f", "\x7f", "\r", "\t"):
            assert ch not in qa_text, f"control char {ch!r} leaked into bundle"
        assert "details" in qa_text

    def test_create_review_bundle_picks_latest_numbered_review(self, branch_workspace):
        """With plan-review-001 and plan-review-003, latest_plan_review.index == 3."""
        (branch_workspace / "plan-review-001.md").write_text("Old review\n", encoding="utf-8")
        (branch_workspace / "plan-review-003.md").write_text("Latest review\n", encoding="utf-8")

        result = map_step_runner.create_review_bundle()

        entry = result["artifacts"]["latest_plan_review"]
        assert entry["present"] is True
        assert entry["index"] == 3
        assert entry["path"].endswith("plan-review-003.md")

    def test_create_review_bundle_updates_manifest_review_stage(self, branch_workspace):
        """Manifest review stage records missing prior-stage inputs as warn."""
        del branch_workspace
        manifest = map_step_runner.default_artifact_manifest("test-branch")
        map_step_runner.save_artifact_manifest(manifest, "test-branch")

        map_step_runner.create_review_bundle()

        reloaded = map_step_runner.load_artifact_manifest("test-branch")
        stages = reloaded["stages"]
        assert isinstance(stages, dict)
        review_stage = stages["review"]
        assert review_stage["status"] == "warn"
        artifacts_list = review_stage["artifacts"]
        assert len(artifacts_list) == 2
        kinds = {a["kind"] for a in artifacts_list}
        assert kinds == {"review-bundle"}
        meta = review_stage["metadata"]
        assert "bundle_status" in meta
        assert "selected_artifacts" in meta
        assert "missing_artifacts" in meta
        assert isinstance(meta["selected_artifacts"], int)
        assert isinstance(meta["missing_artifacts"], int)

    def test_create_review_bundle_handles_manifest_write_error(
        self, monkeypatch, branch_workspace
    ):
        """OSError from save_artifact_manifest is captured; bundle files still written."""
        del branch_workspace  # fixture only needed for chdir + monkeypatch side effects

        def _raise(*args: object, **kwargs: object) -> None:
            del args, kwargs
            raise OSError("disk full")

        monkeypatch.setattr(map_step_runner, "save_artifact_manifest", _raise)

        result = map_step_runner.create_review_bundle()

        # Bundle files must still be written despite manifest failure
        assert Path(result["bundle_path_json"]).exists()
        assert Path(result["bundle_path_md"]).exists()
        assert result["manifest_status"]["status"] == "error"
        assert "disk full" in result["manifest_status"]["reason"]

    def test_create_review_bundle_creates_manifest_when_absent(self, branch_workspace):
        """No pre-existing manifest: helper creates it and records review status."""
        manifest_file = branch_workspace / "artifact_manifest.json"
        assert not manifest_file.exists()

        map_step_runner.create_review_bundle()

        assert manifest_file.exists()
        reloaded = map_step_runner.load_artifact_manifest("test-branch")
        stages = reloaded["stages"]
        assert isinstance(stages, dict)
        assert stages["review"]["status"] == "warn"

    def test_create_review_bundle_warns_on_schema_drift(
        self, monkeypatch, branch_workspace
    ):
        """Soft validation: schema failure surfaces ``schema_validation_error`` and
        downgrades the manifest stage from ``ready`` to ``warn`` without dropping the
        bundle file write.
        """
        del branch_workspace  # fixture only needed for chdir + monkeypatch side effects

        try:
            import mapify_cli.schemas as schemas_module
        except ImportError:
            pytest.skip("mapify_cli.schemas not importable in this environment")

        def _force_invalid(
            data: dict, schema: dict, *, raise_on_error: bool = False
        ) -> tuple[bool, list[str]]:
            del data, schema, raise_on_error
            return (False, ["forced-invalid: drift sentinel"])

        monkeypatch.setattr(schemas_module, "validate_artifact", _force_invalid)

        result = map_step_runner.create_review_bundle()

        assert Path(result["bundle_path_json"]).exists()
        assert result["schema_validation_error"] == ["forced-invalid: drift sentinel"]
        assert result["manifest_status"]["status"] == "warn"
        reloaded = map_step_runner.load_artifact_manifest("test-branch")
        stages = reloaded["stages"]
        assert isinstance(stages, dict)
        assert stages["review"]["status"] == "warn"

        bundle = json.loads(Path(result["bundle_path_json"]).read_text(encoding="utf-8"))
        assert bundle["schema_validation_error"] == ["forced-invalid: drift sentinel"]

    def test_create_review_bundle_marks_stub_artifacts_absent(self, branch_workspace):
        """Stub verification-summary.md and pr-draft.md must surface as ``present=False``.

        Covers both detection paths:
          * Strict ``HUMAN_ARTIFACT_DEFAULTS`` byte-match (initial stub).
          * ``_is_soft_stub_text`` fingerprint (writer-emitted placeholder body).
        """
        map_step_runner.write_pr_draft()
        map_step_runner.write_verification_summary("", "", "", "", "")
        (branch_workspace / "spec_test-branch.md").write_text(
            "# Spec\n\nReal content.\n", encoding="utf-8"
        )

        result = map_step_runner.create_review_bundle()

        artifacts = result["artifacts"]
        assert artifacts["pr_draft"]["present"] is False
        assert "stub" in (artifacts["pr_draft"].get("reason") or "")
        assert artifacts["verification_summary"]["present"] is False
        assert "stub" in (artifacts["verification_summary"].get("reason") or "")
        assert artifacts["spec"]["present"] is True

    def test_create_review_bundle_with_slash_branch(self, branch_workspace):
        """Explicit ``branch='feat/foo'`` must sanitize to ``feat-foo`` rather than nesting."""
        del branch_workspace  # fixture only needed for chdir + monkeypatch side effects

        result = map_step_runner.create_review_bundle(branch="feat/foo")

        assert result["branch"] == "feat-foo"
        bundle_json = Path(result["bundle_path_json"])
        assert "feat-foo" in str(bundle_json)
        assert "feat/foo" not in str(bundle_json)
        assert bundle_json.exists()
        assert not Path(".map/feat/foo").exists()

    def test_create_review_bundle_caps_large_diff(self, monkeypatch, branch_workspace):
        """Oversize diff_stat / files_changed snapshot must be truncated with a marker."""
        del branch_workspace  # fixture only needed for chdir + monkeypatch side effects

        huge_diff = "X" * (map_step_runner._DIFF_STAT_MAX_CHARS + 10_000)
        huge_files = [f"path/file_{i}.py" for i in range(
            map_step_runner._FILES_CHANGED_MAX_ENTRIES + 50
        )]

        def fake_snapshot(branch=None):
            return {
                "status": "success",
                "git_ref": "abcdef123456",
                "files_changed": huge_files[:map_step_runner._FILES_CHANGED_MAX_ENTRIES],
                "diff_stat": huge_diff[:map_step_runner._DIFF_STAT_MAX_CHARS] + "\n... [truncated]",
                "branch": branch or "test-branch",
                "diff_truncated": True,
            }

        monkeypatch.setattr(map_step_runner, "snapshot_code_state", fake_snapshot)

        result = map_step_runner.create_review_bundle()

        code_state = result["code_state"]
        assert code_state["diff_truncated"] is True
        assert len(code_state["diff_stat"]) <= map_step_runner._DIFF_STAT_MAX_CHARS + 32
        assert len(code_state["files_changed"]) <= map_step_runner._FILES_CHANGED_MAX_ENTRIES

    def test_snapshot_code_state_truncates_when_diff_oversize(self, monkeypatch):
        """Direct ``snapshot_code_state`` call truncates oversize git output in-place."""
        import subprocess as real_subprocess

        huge = "X" * (map_step_runner._DIFF_STAT_MAX_CHARS + 100)
        many_files = "\n".join(
            f"path/file_{i}.py"
            for i in range(map_step_runner._FILES_CHANGED_MAX_ENTRIES + 50)
        )

        def mock_run(cmd, **kwargs):
            del kwargs
            if "rev-parse" in cmd:
                return real_subprocess.CompletedProcess(cmd, 0, "deadbeef\n", "")
            if "--stat" in cmd:
                return real_subprocess.CompletedProcess(cmd, 0, huge, "")
            if "--name-only" in cmd:
                return real_subprocess.CompletedProcess(cmd, 0, many_files, "")
            return real_subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr("subprocess.run", mock_run)
        result = map_step_runner.snapshot_code_state(branch="any")
        assert result["diff_truncated"] is True
        assert result["diff_stat"].endswith("[truncated]")
        assert (
            len(result["files_changed"]) == map_step_runner._FILES_CHANGED_MAX_ENTRIES
        )

    def test_build_review_prompts_no_longer_truncates_diff_or_bundle(
        self, branch_workspace
    ):
        """Negative-contract regression: review prompts no longer clip bundle
        or diff context. Truncation infrastructure was removed by user
        directive — review prompts emit the full bundle and full diff
        regardless of the artificially-low budget_tokens.
        """
        del branch_workspace
        review_bundle = "# Review Bundle\nPRIMARY_BUNDLE_SENTINEL\n" + (
            "covered acceptance evidence\n" * 80
        )
        git_diff = "diff --git a/app.py b/app.py\n" + (
            "+ secondary diff context line\n" * 6_000
        ) + "TAIL_DIFF_SENTINEL\n"

        result = map_step_runner.build_review_prompts(
            branch="test-branch",
            review_preferences="Flag correctness and test regressions first.",
            budget_tokens=1_500,
            review_bundle_text=review_bundle,
            git_diff_text=git_diff,
        )

        assert result["status"] == "success"
        for role in ("monitor", "predictor", "evaluator"):
            prompt_info = result["prompts"][role]
            prompt = prompt_info["prompt"]
            assert prompt_info["truncated"] is False
            assert prompt_info["clipped_sections"] == []
            # Both sentinels present — bundle AND diff tail survive.
            assert "PRIMARY_BUNDLE_SENTINEL" in prompt
            assert "TAIL_DIFF_SENTINEL" in prompt
            assert "Review Prompt Budget" not in prompt  # no budget note
            assert "<documents>" in prompt
            assert "</documents>" in prompt
            assert "<expected_output>" in prompt
            assert "<format_rules>" in prompt
            assert "Return exactly one JSON object" in prompt
        # monitor schema includes "verdict" — spot-check the schema emission
        assert '"verdict"' in result["prompts"]["monitor"]["prompt"]

    def test_build_review_prompts_no_longer_truncates_preferences(
        self, branch_workspace
    ):
        """Negative-contract regression: review preferences no longer
        clipped — they reach the reviewer in full.
        """
        del branch_workspace
        review_bundle = "# Review Bundle\nPRIMARY_BUNDLE_SENTINEL\n" + (
            "covered acceptance evidence\n" * 40
        )
        review_preferences = "Prefer high-signal review.\n" + (
            "Large preference context\n" * 5_000
        ) + "TAIL_PREFERENCES_SENTINEL\n"

        result = map_step_runner.build_review_prompts(
            branch="test-branch",
            review_preferences=review_preferences,
            budget_tokens=1_500,
            review_bundle_text=review_bundle,
            git_diff_text="diff --git a/app.py b/app.py\n+small change\n",
        )

        for role in ("monitor", "predictor", "evaluator"):
            prompt_info = result["prompts"][role]
            prompt = prompt_info["prompt"]
            assert prompt_info["truncated"] is False
            assert prompt_info["clipped_sections"] == []
            assert "PRIMARY_BUNDLE_SENTINEL" in prompt
            # Tail preferences sentinel must now survive (was clipped before).
            assert "TAIL_PREFERENCES_SENTINEL" in prompt

    def test_build_review_prompts_tolerates_budget_artifact_write_error(
        self, branch_workspace, monkeypatch
    ):
        """Budget diagnostics must not block prompt generation on I/O errors."""
        del branch_workspace

        def fail_write(path, payload):
            del path, payload
            raise OSError("read-only .map")

        monkeypatch.setattr(map_step_runner, "_write_json_file", fail_write)

        result = map_step_runner.build_review_prompts(
            review_bundle_text="# Review Bundle\nPRIMARY_BUNDLE_SENTINEL\n",
            git_diff_text="diff --git a/file.py b/file.py\n",
            budget_tokens=1500,
        )

        assert result["status"] == "success"
        assert set(result["prompts"]) == {"monitor", "predictor", "evaluator"}

    def test_record_token_budget_decision_reports_nonfatal_write_error(
        self, branch_workspace, monkeypatch
    ):
        """Direct artifact writes report errors instead of raising."""
        del branch_workspace

        def fail_write(path, payload):
            del path, payload
            raise OSError("disk full")

        monkeypatch.setattr(map_step_runner, "_write_json_file", fail_write)

        result = map_step_runner.record_token_budget_decision(
            path_name="map-review.monitor_prompt",
            configured_budget_tokens=1500,
            estimated_tokens_before=2000,
            estimated_tokens_after=1400,
            budget_action="truncated",
        )

        assert result["status"] == "error"
        assert "disk full" in result["reason"]

    def test_review_prompt_no_longer_clips_unbounded_input(self, branch_workspace):
        """Negative-contract regression: truncation infra was deleted, so
        the "old vs new (budgeted)" A/B no longer applies. The new prompt
        equals the old prompt — both include the full diff tail.
        """
        del branch_workspace
        review_bundle = "# Review Bundle\nPRIMARY_BUNDLE_SENTINEL\n" + (
            "review bundle evidence\n" * 80
        )
        git_diff = "diff --git a/app.py b/app.py\n" + (
            "+ old unbounded diff context line\n" * 5_000
        ) + "TAIL_DIFF_SENTINEL\n"
        spec = map_step_runner.REVIEW_PROMPT_SPECS["monitor"]
        old_prompt = map_step_runner._render_review_prompt(
            spec,
            review_bundle,
            "Flag correctness and test regressions first.",
            git_diff,
        )

        new_prompt_info = map_step_runner.build_review_prompts(
            branch="test-branch",
            review_preferences="Flag correctness and test regressions first.",
            budget_tokens=1_500,
            review_bundle_text=review_bundle,
            git_diff_text=git_diff,
        )["prompts"]["monitor"]
        new_prompt = new_prompt_info["prompt"]

        # Truncation is gone: new prompt contains the diff tail (was
        # previously clipped) and carries no "Review Prompt Budget" note.
        assert "TAIL_DIFF_SENTINEL" in old_prompt
        assert "TAIL_DIFF_SENTINEL" in new_prompt
        assert "PRIMARY_BUNDLE_SENTINEL" in new_prompt
        assert "Review Prompt Budget" not in new_prompt
        assert new_prompt_info["truncated"] is False
        assert new_prompt_info["clipped_sections"] == []

    def test_review_prompt_skeleton_lists_all_required_fields(
        self, branch_workspace
    ):
        """AGENT_OUTPUT_SCHEMAS skeleton fields appear literally in prompts,
        and skeleton key set is a superset of required_keys for each agent.
        """
        del branch_workspace
        result = map_step_runner.build_review_prompts(
            branch="test-branch",
            review_preferences="review preferences",
            budget_tokens=4_000,
            review_bundle_text="# Review Bundle\nsome content\n",
            git_diff_text="diff --git a/app.py b/app.py\n+change\n",
        )
        assert result["status"] == "success"

        # Per-role SKILL.md field spot-checks
        role_field_checks: dict[str, list[str]] = {
            "monitor": [
                "was_present_before_pr",
                "reach_evidence",
                "sibling_comparison",
                "verdict",
            ],
            "predictor": [
                "landmine_evidence",
                "risk_assessment",
            ],
            "evaluator": [
                "monitor_severity_audit",
                "overall_score",
            ],
        }
        for role, fields in role_field_checks.items():
            prompt = result["prompts"][role]["prompt"]
            for field in fields:
                assert field in prompt, (
                    f"Expected field '{field}' for role '{role}' not found in prompt"
                )

        # skeleton key set >= required_keys for each schema role
        schemas = map_step_runner.AGENT_OUTPUT_SCHEMAS
        for role, schema in schemas.items():
            skeleton_keys = set(schema["skeleton"].keys())  # type: ignore[union-attr]
            required_keys = set(schema["required_keys"])  # type: ignore[union-attr]
            assert required_keys <= skeleton_keys, (
                f"Role '{role}': required_keys {required_keys - skeleton_keys} "
                f"not present in skeleton"
            )


# ---------------------------------------------------------------------------
# prepare_detached_review — focused unit tests (ST-004)
# ---------------------------------------------------------------------------


class TestPrepareDetachedReview:
    """Focused tests for prepare_detached_review."""

    def test_prepare_detached_review_success(self, monkeypatch, branch_workspace):
        """Happy path: rev-parse succeeds, worktree add succeeds."""
        import subprocess as real_subprocess

        def mock_run(cmd: list[str], **kwargs: object) -> real_subprocess.CompletedProcess:  # type: ignore[type-arg]
            del kwargs
            if "rev-parse" in cmd:
                return real_subprocess.CompletedProcess(cmd, 0, "abc1234\n", "")
            if "worktree" in cmd and "add" in cmd:
                return real_subprocess.CompletedProcess(cmd, 0, "", "")
            return real_subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr("subprocess.run", mock_run)
        target = branch_workspace / "detached-review"

        result = map_step_runner.prepare_detached_review(
            "bundle.json", target_dir=str(target)
        )

        assert result["status"] == "success"
        assert str(result["worktree_path"]).endswith("detached-review")
        assert result["commit"] == "abc1234"
        assert result["mutated_source"] is False

    def test_prepare_detached_review_existing_path_unavailable(
        self, monkeypatch, branch_workspace
    ):
        """Path already exists: returns unavailable without calling worktree add."""
        import subprocess as real_subprocess

        calls: list[list[str]] = []

        def mock_run(cmd: list[str], **kwargs: object) -> real_subprocess.CompletedProcess:  # type: ignore[type-arg]
            del kwargs
            calls.append(list(cmd))
            return real_subprocess.CompletedProcess(cmd, 0, "abc1234\n", "")

        monkeypatch.setattr("subprocess.run", mock_run)
        target = branch_workspace / "detached-review"
        target.mkdir()

        result = map_step_runner.prepare_detached_review(
            "bundle.json", target_dir=str(target)
        )

        assert result["status"] == "unavailable"
        assert "already exists" in result["reason"]
        assert result["mutated_source"] is False
        worktree_add_calls = [c for c in calls if "worktree" in c and "add" in c]
        assert worktree_add_calls == [], "worktree add must never be called when path exists"

    def test_prepare_detached_review_git_rev_parse_fails(
        self, monkeypatch, branch_workspace
    ):
        """rev-parse exits non-zero: returns unavailable with stderr in reason."""
        del branch_workspace  # fixture only needed for chdir + monkeypatch side effects
        import subprocess as real_subprocess

        def mock_run(cmd: list[str], **kwargs: object) -> real_subprocess.CompletedProcess:  # type: ignore[type-arg]
            del kwargs
            if "rev-parse" in cmd:
                return real_subprocess.CompletedProcess(
                    cmd, 128, "", "fatal: not a git repository"
                )
            return real_subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr("subprocess.run", mock_run)

        result = map_step_runner.prepare_detached_review("bundle.json")

        assert result["status"] == "unavailable"
        assert "fatal: not a git repository" in result["reason"]

    def test_prepare_detached_review_worktree_add_fails(
        self, monkeypatch, branch_workspace
    ):
        """worktree add exits non-zero: returns error with stderr in reason."""
        del branch_workspace  # fixture only needed for chdir + monkeypatch side effects
        import subprocess as real_subprocess

        def mock_run(cmd: list[str], **kwargs: object) -> real_subprocess.CompletedProcess:  # type: ignore[type-arg]
            del kwargs
            if "rev-parse" in cmd:
                return real_subprocess.CompletedProcess(cmd, 0, "abc1234\n", "")
            if "worktree" in cmd and "add" in cmd:
                return real_subprocess.CompletedProcess(
                    cmd, 1, "", "fatal: <path> invalid"
                )
            return real_subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr("subprocess.run", mock_run)

        result = map_step_runner.prepare_detached_review("bundle.json")

        assert result["status"] == "error"
        assert "fatal: <path> invalid" in result["reason"]

    def test_prepare_detached_review_never_calls_mutating_git_commands(
        self, monkeypatch, branch_workspace
    ):
        """No checkout, stash, reset, restore, commit, rm, or 'git add ' called."""
        del branch_workspace  # fixture only needed for chdir + monkeypatch side effects
        import subprocess as real_subprocess

        recorded_calls: list[list[str]] = []

        def mock_run(cmd: list[str], **kwargs: object) -> real_subprocess.CompletedProcess:  # type: ignore[type-arg]
            del kwargs
            recorded_calls.append(list(cmd))
            if "rev-parse" in cmd:
                return real_subprocess.CompletedProcess(cmd, 0, "abc1234\n", "")
            return real_subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr("subprocess.run", mock_run)

        map_step_runner.prepare_detached_review("bundle.json")

        # "worktree add" is the one permitted mutation (creates a new worktree entry).
        # All other staging/checkout/destructive git subcommands must never appear.
        mutating = ("checkout", "stash", "reset", "restore", "commit", "rm")
        for call in recorded_calls:
            joined = " ".join(call)
            for bad in mutating:
                assert bad not in joined, (
                    f"mutating git command {bad!r} found in call: {call}"
                )
            # bare "git add <path>" (staging) must not appear; "worktree add" is fine
            if "worktree" not in call:
                assert "add" not in call, (
                    f"bare 'git add' (staging) found in call: {call}"
                )

    def test_prepare_detached_review_rejects_path_traversal(
        self, monkeypatch, branch_workspace
    ):
        """target_dir outside .map/<branch>/ scope is rejected without git mutation."""
        del branch_workspace  # fixture only needed for chdir + monkeypatch side effects
        import subprocess as real_subprocess

        recorded_calls: list[list[str]] = []

        def mock_run(cmd: list[str], **kwargs: object) -> real_subprocess.CompletedProcess:  # type: ignore[type-arg]
            del kwargs
            recorded_calls.append(list(cmd))
            return real_subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr("subprocess.run", mock_run)

        result = map_step_runner.prepare_detached_review(
            "bundle.json", target_dir="../../tmp/evil"
        )

        assert result["status"] == "error"
        assert "escapes" in result["reason"]
        assert result["mutated_source"] is False
        # No git command of any kind must have been invoked — the guard returns before
        # rev-parse and worktree add.
        worktree_or_rev = [
            c for c in recorded_calls if "worktree" in c or "rev-parse" in c
        ]
        assert worktree_or_rev == [], (
            f"git was invoked after path-traversal rejection: {worktree_or_rev}"
        )


# ---------------------------------------------------------------------------
# Regression: build_handoff_bundle + write_learning_handoff remain compatible
# after create_review_bundle has populated the review stage (ST-005 / AC-7)
# ---------------------------------------------------------------------------


def test_build_handoff_bundle_compatible_after_review_bundle_created(
    branch_workspace,
):
    """build_handoff_bundle() still returns the expected shape after create_review_bundle()
    has written review-bundle.json and updated artifact_manifest review stage (AC-7 / INV-7)."""
    # Populate artifacts that build_handoff_bundle() reads
    (branch_workspace / "verification-summary.md").write_text(
        "# Verification Summary\n\n- Verdict: READY FOR REVIEW\n",
        encoding="utf-8",
    )
    (branch_workspace / "qa-001.md").write_text(
        "# QA 001\n\n- Commands Run: pytest\n",
        encoding="utf-8",
    )
    (branch_workspace / "code-review-001.md").write_text(
        "# Code Review 001\n\n- follow up on edge case\n",
        encoding="utf-8",
    )

    # Run create_review_bundle first — this populates review stage in the manifest
    bundle_result = map_step_runner.create_review_bundle()
    assert bundle_result["status"] == "success", (
        "create_review_bundle should succeed before the compatibility check"
    )

    # Now verify build_handoff_bundle still works and returns the expected shape
    result = map_step_runner.build_handoff_bundle()

    assert result["status"] == "success"
    # Required fields must all be present with their expected types
    for field in ("status", "branch", "summary", "validation", "risks_follow_up"):
        assert field in result, f"build_handoff_bundle result missing field '{field}'"
    # Content must still reflect the artifacts written above
    assert "READY FOR REVIEW" in result["validation"]
    assert "follow up on edge case" in result["risks_follow_up"]
    assert "Verification summary available" in result["summary"]


def test_create_review_bundle_includes_acceptance_coverage(branch_workspace):
    blueprint = {
        **_blueprint_constraint_fields(),
        "subtasks": [
            {
                "id": "ST-001",
                "title": "Fix checkout timeout message",
                "aag_contract": "CheckoutService -> handle_timeout() -> user sees retryable error",
                "dependencies": [],
                "affected_files": ["src/checkout.py"],
                "expected_diff_size": "small",
                "concern_type": "runtime",
                "one_logical_step": True,
                "validation_criteria": ["VC1 [AC-1]: timeout shows retryable message"],
            }
        ],
        "coverage_map": {"AC-1": "ST-001"},
    }
    (branch_workspace / "blueprint.json").write_text(json.dumps(blueprint))
    (branch_workspace / "verification-summary.md").write_text(
        "# Verification Summary\n\n## Checks Run\npytest [AC-1]\n",
        encoding="utf-8",
    )

    result = map_step_runner.create_review_bundle()

    assert result["acceptance_coverage"]["summary"] == {
        "total": 1,
        "covered": 1,
        "missing": 0,
    }
    bundle = json.loads((branch_workspace / "review-bundle.json").read_text())
    assert bundle["acceptance_coverage"]["requirements"][0]["id"] == "AC-1"
    markdown = (branch_workspace / "review-bundle.md").read_text(encoding="utf-8")
    assert "## Acceptance Coverage" in markdown
    assert "[covered] AC-1 owned by ST-001" in markdown
    manifest = map_step_runner.load_artifact_manifest("test-branch")
    assert manifest["stages"]["review"]["metadata"]["acceptance_coverage"] == {
        "total": 1,
        "covered": 1,
        "missing": 0,
    }


def test_write_learning_handoff_compatible_after_review_bundle_created(
    branch_workspace,
):
    """write_learning_handoff() succeeds and produces expected files after create_review_bundle()
    has updated the artifact_manifest review stage (AC-7 / INV-7)."""
    # Populate artifacts consumed by write_learning_handoff and create_review_bundle
    (branch_workspace / "verification-summary.md").write_text(
        "# Verification Summary\n\n- Verdict: READY FOR REVIEW\n",
        encoding="utf-8",
    )
    (branch_workspace / "qa-001.md").write_text(
        "# QA 001\n\n- Commands Run: pytest\n",
        encoding="utf-8",
    )
    (branch_workspace / "code-review-001.md").write_text(
        "# Code Review 001\n\n- looks good\n",
        encoding="utf-8",
    )
    (branch_workspace / "workflow-fit.json").write_text(
        json.dumps({"recommended_workflow": "map-efficient"}) + "\n",
        encoding="utf-8",
    )

    # Run create_review_bundle first — updates manifest review stage even when
    # prior-stage inputs are incomplete.
    bundle_result = map_step_runner.create_review_bundle()
    assert bundle_result["status"] == "success", (
        "create_review_bundle should succeed before the compatibility check"
    )

    # Confirm the manifest review stage was actually populated
    manifest_after_bundle = map_step_runner.load_artifact_manifest()
    assert manifest_after_bundle["stages"]["review"]["status"] == "warn"

    # Now run write_learning_handoff and verify it still succeeds
    result = map_step_runner.write_learning_handoff(
        "map-efficient",
        task_title="t",
        outcome="OK",
        next_action="run review",
    )

    assert result["status"] == "success"
    # Both output files must be produced
    assert (branch_workspace / "learning-handoff.md").exists(), (
        "learning-handoff.md was not created"
    )
    assert (branch_workspace / "learning-handoff.json").exists(), (
        "learning-handoff.json was not created"
    )
    # The markdown must reflect the passed arguments
    markdown = (branch_workspace / "learning-handoff.md").read_text(encoding="utf-8")
    assert "map-efficient" in markdown
    assert "run review" in markdown


# ---------------------------------------------------------------------------
# ST-001: deterministic section-ordering helpers
# ---------------------------------------------------------------------------

# Unit tests — get_review_section_order


def test_get_review_section_order_default():
    result = map_step_runner.get_review_section_order("default")
    assert result == list(map_step_runner.REVIEW_SECTION_IDS)


def test_get_review_section_order_reverse():
    result = map_step_runner.get_review_section_order("reverse-sections")
    assert result == list(reversed(map_step_runner.REVIEW_SECTION_IDS))


def test_get_review_section_order_shuffle_with_seed():
    result = map_step_runner.get_review_section_order("shuffle-sections", seed=42)
    # Must contain all sections
    assert sorted(result) == sorted(map_step_runner.REVIEW_SECTION_IDS)
    # Must be deterministic: second call with same seed yields same order
    result2 = map_step_runner.get_review_section_order("shuffle-sections", seed=42)
    assert result == result2


def test_get_review_section_order_invalid_raises():
    with pytest.raises(ValueError, match="unknown mode"):
        map_step_runner.get_review_section_order("bogus-mode")


def test_get_review_section_order_negative_seed_raises():
    with pytest.raises(ValueError, match="seed must be >= 0"):
        map_step_runner.get_review_section_order("shuffle-sections", seed=-1)


# Unit tests — shuffle seed stability and variation


def test_shuffle_seed_stable():
    r1 = map_step_runner.get_review_section_order("shuffle-sections", seed=99)
    r2 = map_step_runner.get_review_section_order("shuffle-sections", seed=99)
    assert r1 == r2


def test_shuffle_seed_varies():
    # Over a range of seeds, at least one pair must differ from the default order.
    # This is a probabilistic sanity check; with 4 elements and 10 seeds it is
    # astronomically unlikely to fail.
    default = list(map_step_runner.REVIEW_SECTION_IDS)
    results = [
        map_step_runner.get_review_section_order("shuffle-sections", seed=s)
        for s in range(10)
    ]
    assert any(r != default for r in results), (
        "All seeds produced the canonical order — shuffle is not functioning"
    )


# Unit tests — default_shuffle_seed


def test_default_shuffle_seed_with_sha():
    seed = map_step_runner.default_shuffle_seed("main", "abc123")
    assert isinstance(seed, int)
    # Stable for fixed inputs
    assert map_step_runner.default_shuffle_seed("main", "abc123") == seed


def test_default_shuffle_seed_detached_fallback():
    # commit_sha=None must produce sha256(branch + '|detached')[:16] interpreted as hex int.
    import hashlib

    seed_none = map_step_runner.default_shuffle_seed("main", None)
    expected = int(hashlib.sha256(b"main|detached").hexdigest()[:16], 16)
    assert seed_none == expected
    # Cross-process stability: same value any call, any process
    assert map_step_runner.default_shuffle_seed("main", None) == seed_none


# CLI integration tests


def test_cli_shuffle_sections_default_ok():
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_PATH / "map_step_runner.py"), "shuffle-sections", "default"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["mode"] == "default"
    assert len(payload["order"]) == len(map_step_runner.REVIEW_SECTION_IDS)


def test_cli_shuffle_sections_invalid_mode_errors():
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_PATH / "map_step_runner.py"), "shuffle-sections", "bad-mode"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "error"


def test_cli_shuffle_sections_non_int_seed_errors():
    # EC-16: non-int seed must be rejected by int() with exit 1
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_PATH / "map_step_runner.py"),
            "shuffle-sections",
            "shuffle-sections",
            "abc",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "error"
    assert "invalid seed" in payload["message"]


def test_cli_default_shuffle_seed_ok():
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_PATH / "map_step_runner.py"),
            "default-shuffle-seed",
            "my-branch",
            "deadbeef",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert isinstance(payload["seed"], int)
    assert payload["branch"] == "my-branch"
    assert payload["commit_sha"] == "deadbeef"


def test_cli_default_shuffle_seed_detached_when_no_sha():
    # Empty string sha argument should fall back to the detached path (commit_sha=None).
    # Verify: status ok, commit_sha is null, seed is an int, and cross-process stable
    # (sha256-based — works without PYTHONHASHSEED pinning).
    def _call() -> dict:  # type: ignore[type-arg]
        r = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS_PATH / "map_step_runner.py"),
                "default-shuffle-seed",
                "my-branch",
                "",
            ],
            capture_output=True,
            text=True,
        )
        return json.loads(r.stdout)

    p1 = _call()
    p2 = _call()
    assert p1["status"] == "ok"
    assert p1["commit_sha"] is None
    assert isinstance(p1["seed"], int)
    # Cross-process stability via sha256
    assert p1["seed"] == p2["seed"]


# ---------------------------------------------------------------------------
# ST-002: compare_review_runs unit tests (AC-5, AC-6, AC-7, EC-10, EC-11, EC-13, INV-8)
# ---------------------------------------------------------------------------

_REQUIRED_KEYS = {
    "drift_detected",
    "verdicts",
    "shared_primary_issues",
    "unique_primary_issues",
    "drift_summary",
    "final_verdict",
    "compare_status",
}


def _run(verdict: str, issues: list[str], label: str | None = None) -> dict[str, object]:
    """Build a minimal run dict for compare_review_runs."""
    r: dict[str, object] = {"verdict": verdict, "primary_issues": issues}
    if label is not None:
        r["ordering_label"] = label
    return r


# AC-5: output dict has the 7 documented fields
def test_compare_review_runs_has_all_keys():
    result = map_step_runner.compare_review_runs(
        [_run("PROCEED", ["A", "B"], "run_0"), _run("PROCEED", ["A", "B"], "run_1")]
    )
    assert _REQUIRED_KEYS == set(result.keys())


# AC-5 + EC-4: identical verdicts AND identical issues → no drift, correct verdict
def test_compare_review_runs_identical_no_drift():
    result = map_step_runner.compare_review_runs(
        [_run("REVISE", ["X", "Y"], "r0"), _run("REVISE", ["X", "Y"], "r1")]
    )
    assert result["drift_detected"] is False
    assert result["final_verdict"] == "REVISE"
    assert result["compare_status"] is None


# AC-6 / EC-6: verdict mismatch → drift_detected=True; strict-wins gives BLOCK
def test_compare_review_runs_drift_verdict_mismatch():
    result = map_step_runner.compare_review_runs(
        [_run("PROCEED", ["A"], "r0"), _run("BLOCK", ["A"], "r1")]
    )
    assert result["drift_detected"] is True
    assert result["final_verdict"] == "BLOCK"


# AC-6 / EC-5: same verdict but Jaccard overlap < 50% → drift_detected=True
def test_compare_review_runs_drift_low_overlap():
    # issues: {A} vs {B,C,D,E} → shared={}, union={A,B,C,D,E}, Jaccard=0.0
    result = map_step_runner.compare_review_runs(
        [_run("REVISE", ["A"], "r0"), _run("REVISE", ["B", "C", "D", "E"], "r1")]
    )
    assert result["drift_detected"] is True
    assert result["final_verdict"] == "REVISE"


# AC-6 / EC-4: same verdict AND Jaccard ≥ 50% → drift_detected=False
def test_compare_review_runs_no_drift_high_overlap():
    # issues: {A,B,C} vs {A,B,C,D} → shared={A,B,C}, union={A,B,C,D}, Jaccard=0.75
    result = map_step_runner.compare_review_runs(
        [_run("PROCEED", ["A", "B", "C"], "r0"), _run("PROCEED", ["A", "B", "C", "D"], "r1")]
    )
    assert result["drift_detected"] is False
    assert result["final_verdict"] == "PROCEED"


# AC-7 / INV-4: strict-wins — BLOCK beats REVISE
def test_strict_wins_block_beats_revise():
    result = map_step_runner.compare_review_runs(
        [_run("BLOCK", ["I1"], "r0"), _run("REVISE", ["I1"], "r1")]
    )
    assert result["final_verdict"] == "BLOCK"


# AC-7: strict-wins — REVISE beats PROCEED (never downgrades)
def test_strict_wins_never_downgrades():
    result = map_step_runner.compare_review_runs(
        [_run("PROCEED", ["I1"], "r0"), _run("REVISE", ["I1"], "r1")]
    )
    assert result["final_verdict"] == "REVISE"


# AC-7 / INV-5: drift must NOT auto-escalate verdict beyond strictest individual run
def test_drift_does_not_escalate():
    # Both PROCEED but disjoint issues → drift=True, but verdict stays PROCEED
    result = map_step_runner.compare_review_runs(
        [_run("PROCEED", ["A"], "r0"), _run("PROCEED", ["B"], "r1")]
    )
    assert result["drift_detected"] is True
    assert result["final_verdict"] == "PROCEED"  # INV-5: not bumped to REVISE or BLOCK


# EC-11: partial failure (single run) → provisional verdict + compare_status
def test_compare_partial_failure_single_run():
    result = map_step_runner.compare_review_runs([_run("REVISE", ["X"], "only")])
    assert result["compare_status"] == "partial_failure"
    assert result["drift_detected"] is True
    assert result["final_verdict"] == "REVISE"
    assert isinstance(result["drift_summary"], str)
    assert "provisional" in result["drift_summary"]  # type: ignore[operator]


# EC-10: intra-run issue order is irrelevant
def test_issue_order_within_run_irrelevant():
    result = map_step_runner.compare_review_runs(
        [_run("BLOCK", ["Z", "A", "M"], "r0"), _run("BLOCK", ["M", "Z", "A"], "r1")]
    )
    assert result["drift_detected"] is False
    assert result["final_verdict"] == "BLOCK"


# EC-13: drift_summary truncated at 2000 chars BEFORE sanitization
def test_drift_summary_truncation():
    # Construct two runs with disjoint huge issue lists to force a long drift summary.
    issues_a = [f"ISSUE-A-{i:04d}" for i in range(300)]
    issues_b = [f"ISSUE-B-{i:04d}" for i in range(300)]
    result = map_step_runner.compare_review_runs(
        [_run("PROCEED", issues_a, "r0"), _run("PROCEED", issues_b, "r1")]
    )
    assert result["drift_detected"] is True
    assert result["drift_summary"] is not None
    assert len(result["drift_summary"]) <= 2000  # type: ignore[arg-type]


# INV-8: drift_summary passes through _sanitize_for_json (no control chars in output)
def test_drift_summary_sanitization():
    # Embed control characters in issue IDs; they must be absent from the output.
    result = map_step_runner.compare_review_runs(
        [
            _run("REVISE", ["ID\x00X", "clean"], "r0"),
            _run("PROCEED", ["ID\nY", "other"], "r1"),
        ]
    )
    assert result["drift_detected"] is True
    summary = result["drift_summary"]
    assert summary is not None
    for ch in summary:  # type: ignore[union-attr]
        cp = ord(ch)
        assert not (0x00 <= cp <= 0x1F or cp == 0x7F), (
            f"control char U+{cp:04X} found in drift_summary"
        )


# Error cases
def test_compare_review_runs_empty_raises():
    with pytest.raises(ValueError, match="non-empty"):
        map_step_runner.compare_review_runs([])


def test_compare_review_runs_unknown_verdict_raises():
    with pytest.raises(ValueError, match="unknown verdict"):
        map_step_runner.compare_review_runs(
            [_run("WAT", ["I1"], "r0"), _run("PROCEED", ["I1"], "r1")]
        )


# ---------------------------------------------------------------------------
# ST-002: CLI integration tests
# ---------------------------------------------------------------------------

def test_cli_compare_review_runs_ok_argv():
    runs_json = json.dumps(
        [
            {"verdict": "REVISE", "primary_issues": ["A", "B"], "ordering_label": "r0"},
            {"verdict": "REVISE", "primary_issues": ["A", "B"], "ordering_label": "r1"},
        ]
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_PATH / "map_step_runner.py"), "compare-review-runs", runs_json],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert set(payload.keys()) >= _REQUIRED_KEYS | {"status"}


def test_cli_compare_review_runs_invalid_json_errors():
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_PATH / "map_step_runner.py"), "compare-review-runs", "not-json"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "error"


# ---------------------------------------------------------------------------
# ST-003: record_review_ordering + create_review_bundle integration
# ---------------------------------------------------------------------------


@pytest.fixture
def reset_pending_ordering(tmp_path, monkeypatch):
    # Run under tmp_path so the durable pending-ordering.json file lands in a
    # disposable location, not in the real .map/<branch>/ of the repo.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(map_step_runner, "get_branch_name", lambda: "test-branch")
    branch_dir = tmp_path / ".map" / "test-branch"
    branch_dir.mkdir(parents=True, exist_ok=True)
    map_step_runner._PENDING_REVIEW_ORDERING = None
    yield
    map_step_runner._PENDING_REVIEW_ORDERING = None


def test_record_review_ordering_stages_pending(reset_pending_ordering):
    del reset_pending_ordering
    result = map_step_runner.record_review_ordering(
        mode="shuffle-sections",
        seed=42,
        runs=[{"verdict": "PROCEED", "primary_issues": ["A"]}],
        drift={"drift_detected": True, "drift_summary": "x", "final_verdict": "PROCEED", "compare_status": None},
    )
    assert result["status"] == "ok"
    assert result["staged"] is True
    assert result["mode"] == "shuffle-sections"
    assert result["branch_in"] is None
    pending = map_step_runner._PENDING_REVIEW_ORDERING
    assert pending is not None
    assert pending["mode"] == "shuffle-sections"
    assert pending["seed"] == 42
    assert pending["drift_detected"] is True
    assert pending["drift_summary"] == "x"
    assert pending["final_verdict"] == "PROCEED"


def test_record_review_ordering_no_direct_manifest_write(monkeypatch, reset_pending_ordering):
    del reset_pending_ordering

    def _explode(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("INV-10 violation: record_review_ordering called manifest helper")

    monkeypatch.setattr(map_step_runner, "_set_manifest_stage", _explode)
    monkeypatch.setattr(map_step_runner, "save_artifact_manifest", _explode)
    monkeypatch.setattr(map_step_runner, "load_artifact_manifest", _explode)

    map_step_runner.record_review_ordering(
        mode="default",
        runs=[{"verdict": "PROCEED"}],
        drift={"drift_detected": False, "final_verdict": "PROCEED"},
    )


def test_bundle_consumes_pending_and_clears(branch_workspace, reset_pending_ordering):
    del branch_workspace
    del reset_pending_ordering
    payload = {
        "mode": "shuffle-sections",
        "seed": 7,
        "runs": [{"verdict": "PROCEED"}],
        "drift_detected": False,
        "drift_summary": None,
        "final_verdict": "PROCEED",
        "compare_status": None,
    }
    map_step_runner._PENDING_REVIEW_ORDERING = payload

    result = map_step_runner.create_review_bundle()

    assert result["ordering"] == payload
    assert map_step_runner._PENDING_REVIEW_ORDERING is None


def test_bundle_has_ordering_default_when_no_record(branch_workspace, reset_pending_ordering):
    del branch_workspace
    del reset_pending_ordering
    result = map_step_runner.create_review_bundle()
    assert result["ordering"] == {
        "mode": "default",
        "seed": None,
        "runs": [],
        "drift_detected": False,
        "drift_summary": None,
        "final_verdict": None,
        "compare_status": None,
    }


def test_bundle_ordering_records_compare_results(branch_workspace, reset_pending_ordering):
    del branch_workspace
    del reset_pending_ordering
    map_step_runner.record_review_ordering(
        mode="compare-orderings",
        runs=[{"verdict": "REVISE"}, {"verdict": "BLOCK"}],
        drift={
            "drift_detected": True,
            "drift_summary": "verdicts disagree",
            "final_verdict": "BLOCK",
            "compare_status": None,
        },
    )
    result = map_step_runner.create_review_bundle()
    ordering = result["ordering"]
    assert ordering["mode"] == "compare-orderings"
    assert ordering["drift_detected"] is True
    assert ordering["final_verdict"] == "BLOCK"
    assert ordering["drift_summary"] == "verdicts disagree"
    assert len(ordering["runs"]) == 2


def test_bundle_review_stage_status_warns_on_missing_prior_stage_inputs(
    branch_workspace, reset_pending_ordering
):
    del reset_pending_ordering
    map_step_runner.record_review_ordering(mode="default")
    map_step_runner.create_review_bundle()
    manifest = map_step_runner.load_artifact_manifest("test-branch")
    stages = manifest["stages"]
    assert isinstance(stages, dict)
    assert stages["review"]["status"] == "warn"
    del branch_workspace


def test_no_schema_validation_error_on_valid_ordering(branch_workspace, reset_pending_ordering):
    del branch_workspace
    del reset_pending_ordering
    map_step_runner.record_review_ordering(mode="default")
    result = map_step_runner.create_review_bundle()
    assert "schema_validation_error" not in result


def test_bundle_manifest_metadata_contains_ordering(branch_workspace, reset_pending_ordering):
    del reset_pending_ordering
    map_step_runner.record_review_ordering(
        mode="reverse-sections",
        seed=None,
        runs=[{"verdict": "PROCEED"}],
        drift={"drift_detected": False, "final_verdict": "PROCEED"},
    )
    map_step_runner.create_review_bundle()
    manifest = map_step_runner.load_artifact_manifest("test-branch")
    stages = manifest["stages"]
    assert isinstance(stages, dict)
    metadata = stages["review"]["metadata"]
    assert "ordering" in metadata
    assert metadata["ordering"]["mode"] == "reverse-sections"
    del branch_workspace


def test_record_review_ordering_unknown_mode_raises(reset_pending_ordering):
    del reset_pending_ordering
    with pytest.raises(ValueError, match="unknown mode"):
        map_step_runner.record_review_ordering(mode="xyz")


def test_record_review_ordering_drift_summary_truncated(reset_pending_ordering):
    del reset_pending_ordering
    big = "x" * 3000
    map_step_runner.record_review_ordering(
        mode="default",
        drift={"drift_detected": True, "drift_summary": big, "final_verdict": "BLOCK"},
    )
    pending = map_step_runner._PENDING_REVIEW_ORDERING
    assert pending is not None
    summary = pending["drift_summary"]
    assert isinstance(summary, str)
    assert len(summary) <= 2000


def test_record_review_ordering_drift_summary_sanitized(reset_pending_ordering):
    del reset_pending_ordering
    dirty = "before\x00\x01\x07after"
    map_step_runner.record_review_ordering(
        mode="default",
        drift={"drift_detected": True, "drift_summary": dirty, "final_verdict": "BLOCK"},
    )
    pending = map_step_runner._PENDING_REVIEW_ORDERING
    assert pending is not None
    summary = pending["drift_summary"]
    assert isinstance(summary, str)
    for ch in summary:
        assert ord(ch) >= 0x20 and ord(ch) != 0x7F, f"control char {ord(ch):#x} not sanitized"


def test_cli_record_review_ordering_ok():
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_PATH / "map_step_runner.py"), "record-review-ordering", "default"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["mode"] == "default"


def test_cli_record_review_ordering_invalid_mode_errors():
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_PATH / "map_step_runner.py"), "record-review-ordering", "xyz"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "error"


# ---------------------------------------------------------------------------
# ST-007: build_review_handoff ordering metadata (AC-13)
# ---------------------------------------------------------------------------


class TestBuildReviewHandoffWithOrdering:
    """Tests that build_review_handoff surfaces ordering metadata from review-bundle.json."""

    def test_handoff_surfaces_ordering_when_present(self, branch_workspace):
        """When bundle has ordering, all 4 fields reflect bundle values."""
        bundle = {
            "status": "ready",
            "branch": "test-branch",
            "ordering": {
                "mode": "shuffle-sections",
                "seed": 42,
                "drift_detected": True,
                "compare_status": "diverged",
            },
        }
        (branch_workspace / "review-bundle.json").write_text(
            json.dumps(bundle), encoding="utf-8"
        )

        result = map_step_runner.build_review_handoff()

        assert result["review_order_mode"] == "shuffle-sections"
        assert result["review_order_seed"] == 42
        assert result["drift_detected"] is True
        assert result["compare_status"] == "diverged"

    def test_handoff_legacy_bundle_no_ordering_returns_defaults(self, branch_workspace):
        """Legacy bundle without 'ordering' key returns safe defaults (EC-7)."""
        bundle = {
            "status": "ready",
            "branch": "test-branch",
            # intentionally no "ordering" key
        }
        (branch_workspace / "review-bundle.json").write_text(
            json.dumps(bundle), encoding="utf-8"
        )

        result = map_step_runner.build_review_handoff()

        assert result["review_order_mode"] == "default"
        assert result["review_order_seed"] is None
        assert result["drift_detected"] is False
        assert result["compare_status"] is None

    def test_handoff_no_bundle_file_returns_defaults(self, branch_workspace):
        """When review-bundle.json does not exist, safe defaults are returned."""
        del branch_workspace  # fixture only needed for chdir + monkeypatch side effects
        # No review-bundle.json written — simulates first run or missing artifact.
        result = map_step_runner.build_review_handoff()

        assert result["review_order_mode"] == "default"
        assert result["review_order_seed"] is None
        assert result["drift_detected"] is False
        assert result["compare_status"] is None

    def test_handoff_malformed_bundle_returns_defaults(self, branch_workspace):
        """Invalid JSON in bundle file is silently ignored; defaults are returned."""
        (branch_workspace / "review-bundle.json").write_text(
            "{ this is not valid json }", encoding="utf-8"
        )

        result = map_step_runner.build_review_handoff()

        assert result["review_order_mode"] == "default"
        assert result["review_order_seed"] is None
        assert result["drift_detected"] is False
        assert result["compare_status"] is None

    def test_handoff_ordering_with_null_seed_and_status(self, branch_workspace):
        """Ordering present but seed and compare_status are None — fields propagated correctly."""
        bundle = {
            "ordering": {
                "mode": "default",
                "seed": None,
                "drift_detected": False,
                "compare_status": None,
            }
        }
        (branch_workspace / "review-bundle.json").write_text(
            json.dumps(bundle), encoding="utf-8"
        )

        result = map_step_runner.build_review_handoff()

        assert result["review_order_mode"] == "default"
        assert result["review_order_seed"] is None
        assert result["drift_detected"] is False
        assert result["compare_status"] is None

    def test_handoff_does_not_modify_pr_draft_output(self, branch_workspace):
        """OOS guarantee: build_handoff_bundle output is unchanged when ordering is present."""
        bundle = {
            "ordering": {
                "mode": "shuffle-sections",
                "seed": 7,
                "drift_detected": True,
                "compare_status": "diverged",
            }
        }
        (branch_workspace / "review-bundle.json").write_text(
            json.dumps(bundle), encoding="utf-8"
        )

        # build_handoff_bundle must not expose ordering keys.
        handoff_bundle = map_step_runner.build_handoff_bundle()

        assert "review_order_mode" not in handoff_bundle
        assert "review_order_seed" not in handoff_bundle
        assert "drift_detected" not in handoff_bundle
        assert "compare_status" not in handoff_bundle

    def test_handoff_four_fields_always_present(self, branch_workspace):
        """The 4 ordering fields are present in every call regardless of bundle state."""
        del branch_workspace  # fixture only needed for chdir + monkeypatch side effects
        result = map_step_runner.build_review_handoff()

        for key in ("review_order_mode", "review_order_seed", "drift_detected", "compare_status"):
            assert key in result, f"Expected key '{key}' missing from handoff result"

    def test_handoff_status_still_success_with_ordering(self, branch_workspace):
        """Adding ordering fields must not change the top-level status field."""
        bundle = {
            "ordering": {
                "mode": "reverse-sections",
                "seed": None,
                "drift_detected": False,
                "compare_status": None,
            }
        }
        (branch_workspace / "review-bundle.json").write_text(
            json.dumps(bundle), encoding="utf-8"
        )

        result = map_step_runner.build_review_handoff()

        assert result["status"] == "success"


class TestTokenAccounting:
    """record_token_event attributes a transcript's per-turn usage to the
    active subtask and rolls it up (cache-hit ratio + est cost) into
    token_accounting.json. Dedup by msg_id keeps re-fired hooks honest.
    """

    TRANSCRIPT = (
        '{"type":"assistant","uuid":"u1","message":{"role":"assistant","id":"msg_1",'
        '"model":"claude-opus-4-7","usage":{"input_tokens":1000,"output_tokens":200,'
        '"cache_creation_input_tokens":500,"cache_read_input_tokens":8000}}}\n'
        '{"type":"user","message":{"role":"user","content":"hi"}}\n'
        '{"type":"assistant","uuid":"u2","message":{"role":"assistant","id":"msg_2",'
        '"model":"claude-opus-4-7","usage":{"input_tokens":300,"output_tokens":50,'
        '"cache_creation_input_tokens":0,"cache_read_input_tokens":9000}}}\n'
    )

    def _state(self, branch_dir: Path, subtask: str = "ST-003", phase: str = "ACTOR") -> None:
        (branch_dir / "step_state.json").write_text(
            json.dumps({"current_subtask_id": subtask, "current_step_phase": phase})
        )

    def test_records_and_attributes_usage(self, branch_workspace):
        repo = branch_workspace.parents[1]
        transcript = repo / "tr.jsonl"
        transcript.write_text(self.TRANSCRIPT)
        self._state(branch_workspace)

        result = map_step_runner.record_token_event(
            "test-branch", transcript_path=str(transcript)
        )

        assert result["status"] == "success"
        assert result["recorded"] == 2
        assert result["subtask_id"] == "ST-003"
        assert result["agent"] == "actor"  # phase ACTOR -> actor
        assert result["input"] == 1300
        assert result["output"] == 250
        assert result["cache_read"] == 17000
        assert (branch_workspace / "token_log.jsonl").exists()

        acct = json.loads((branch_workspace / "token_accounting.json").read_text())
        assert acct["aggregate"]["input"] == 1300
        assert acct["aggregate"]["cache_hit_ratio"] == round(17000 / 18300, 4)
        assert acct["aggregate"]["est_cost_usd"] > 0
        assert "ST-003" in acct["by_subtask"]
        assert "actor" in acct["by_agent"]
        assert "ACTOR" in acct["by_phase"]

    def test_dedup_on_second_call(self, branch_workspace):
        repo = branch_workspace.parents[1]
        transcript = repo / "tr.jsonl"
        transcript.write_text(self.TRANSCRIPT)
        self._state(branch_workspace)

        map_step_runner.record_token_event("test-branch", transcript_path=str(transcript))
        again = map_step_runner.record_token_event(
            "test-branch", transcript_path=str(transcript)
        )

        assert again["recorded"] == 0
        assert again["input"] == 0
        log_rows = [
            line
            for line in (branch_workspace / "token_log.jsonl").read_text().splitlines()
            if line.strip()
        ]
        assert len(log_rows) == 2, "dedup must not append the same turns twice"

    def test_incremental_offset_captures_only_new_turns(self, branch_workspace):
        """Appended turns are metered incrementally via the byte offset — old
        turns are not re-read (no O(n) re-parse) and not double-counted."""
        repo = branch_workspace.parents[1]
        transcript = repo / "tr.jsonl"
        transcript.write_text(self.TRANSCRIPT)  # 2 turns
        self._state(branch_workspace)

        first = map_step_runner.record_token_event(
            "test-branch", transcript_path=str(transcript)
        )
        assert first["recorded"] == 2

        with transcript.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "type": "assistant",
                        "uuid": "u3",
                        "message": {
                            "role": "assistant",
                            "id": "msg_3",
                            "model": "claude-opus-4-7",
                            "usage": {"input_tokens": 10, "output_tokens": 5},
                        },
                    }
                )
                + "\n"
            )

        second = map_step_runner.record_token_event(
            "test-branch", transcript_path=str(transcript)
        )
        assert second["recorded"] == 1, "only the appended turn should be recorded"
        assert second["output"] == 5
        log_rows = [
            line
            for line in (branch_workspace / "token_log.jsonl").read_text().splitlines()
            if line.strip()
        ]
        assert len(log_rows) == 3

    def test_record_dedups_repeated_msgid_in_window(self, branch_workspace):
        """One assistant turn written as 3 JSONL lines (same msg_id, as Claude
        Code does per content/tool block) is ONE event — not three. Regression
        for the ~2x est_cost inflation."""
        repo = branch_workspace.parents[1]
        transcript = repo / "tr.jsonl"
        line = (
            '{"type":"assistant","uuid":"%s","message":{"role":"assistant","id":"msg_R",'
            '"model":"claude-opus-4-7","usage":{"input_tokens":1000,"output_tokens":200,'
            '"cache_creation_input_tokens":500,"cache_read_input_tokens":8000}}}\n'
        )
        transcript.write_text((line % "a") + (line % "b") + (line % "c"))
        self._state(branch_workspace)

        result = map_step_runner.record_token_event(
            "test-branch", transcript_path=str(transcript)
        )
        assert result["recorded"] == 1
        assert result["input"] == 1000 and result["output"] == 200
        rows = [
            r
            for r in (branch_workspace / "token_log.jsonl").read_text().splitlines()
            if r.strip()
        ]
        assert len(rows) == 1, "repeated msg_id must be logged once"
        acct = json.loads((branch_workspace / "token_accounting.json").read_text())
        assert acct["aggregate"]["input"] == 1000
        assert acct["event_count"] == 1

    def test_rebuild_dedups_dup_rows_in_existing_log(self, branch_workspace):
        """A token_log written by an older runner (one turn duplicated across
        rows) still rolls up to a single correct total — rebuild dedups by
        msg_id and keeps the most complete copy of each turn."""
        base = {
            "ts": "2026-01-01T00:00:00Z",
            "subtask_id": "ST-003",
            "phase": "ACTOR",
            "agent": "actor",
            "model": "claude-opus-4-7",
            "msg_id": "msg_dup",
            "input": 1000,
            "output": 200,
            "cache_creation": 500,
            "cache_read": 8000,
        }
        partial = {**base, "output": 10, "cache_creation": 0, "cache_read": 0}
        other = {**base, "msg_id": "msg_other", "output": 50}
        (branch_workspace / "token_log.jsonl").write_text(
            "\n".join(json.dumps(r) for r in (partial, base, base, other)) + "\n"
        )

        payload = map_step_runner._rebuild_token_accounting("test-branch")

        assert payload["event_count"] == 2, "two distinct msg_ids, not four rows"
        agg = payload["aggregate"]
        assert agg["input"] == 2000  # msg_dup 1000 + msg_other 1000
        assert agg["output"] == 250, "msg_dup kept at output 200 (not the partial 10)"
        assert agg["cache_read"] == 16000

    def test_explicit_branch_is_sanitized_against_path_traversal(
        self, branch_workspace
    ):
        """A malicious explicit branch must not escape the .map tree — it is
        sanitized the same way MAP sanitizes branch names elsewhere."""
        repo = branch_workspace.parents[1]
        transcript = repo / "tr.jsonl"
        transcript.write_text(self.TRANSCRIPT)

        result = map_step_runner.record_token_event(
            "../../pwned", transcript_path=str(transcript)
        )
        assert result["status"] == "success"
        # Nothing was written outside the project's .map tree.
        assert not (repo.parent / "pwned").exists()
        assert not (repo / ".map" / ".." / ".." / "pwned").exists()
        # The traversal collapsed to the safe 'default' branch dir under .map.
        assert (repo / ".map" / "default" / "token_accounting.json").is_file()

    def test_missing_transcript_path_is_error(self, branch_workspace):
        del branch_workspace
        result = map_step_runner.record_token_event("test-branch", transcript_path="")
        assert result["status"] == "error"

    def test_unreadable_transcript_records_nothing(self, branch_workspace):
        self._state(branch_workspace)
        result = map_step_runner.record_token_event(
            "test-branch",
            transcript_path=str(branch_workspace.parents[1] / "absent.jsonl"),
        )
        assert result["status"] == "success"
        assert result["recorded"] == 0

    def test_explicit_attribution_overrides_state(self, branch_workspace):
        repo = branch_workspace.parents[1]
        transcript = repo / "tr.jsonl"
        transcript.write_text(self.TRANSCRIPT)
        self._state(branch_workspace, subtask="ST-001", phase="ACTOR")

        result = map_step_runner.record_token_event(
            "test-branch",
            transcript_path=str(transcript),
            agent="monitor",
            phase="MONITOR",
            subtask_id="ST-009",
        )
        assert result["agent"] == "monitor"
        assert result["subtask_id"] == "ST-009"
        assert result["phase"] == "MONITOR"

    def test_extract_turn_usage_only_assistant_with_usage(self):
        assert (
            map_step_runner._extract_turn_usage(
                {"type": "user", "message": {"role": "user"}}
            )
            is None
        )
        assert map_step_runner._extract_turn_usage({"no": "message"}) is None
        usage = map_step_runner._extract_turn_usage(
            json.loads(
                '{"type":"assistant","uuid":"x","message":{"role":"assistant",'
                '"id":"m","model":"claude-opus-4-7",'
                '"usage":{"input_tokens":5,"output_tokens":1}}}'
            )
        )
        assert usage is not None
        assert usage["input"] == 5
        assert usage["msg_id"] == "m"

    def test_token_cost_uses_model_price(self):
        usage = {"input": 1_000_000, "output": 0, "cache_creation": 0, "cache_read": 0}
        assert map_step_runner._token_cost(usage, "claude-opus-4-7") == 15.0

    def test_unknown_model_falls_back_to_default_price(self):
        usage = {"input": 1_000_000, "output": 0, "cache_creation": 0, "cache_read": 0}
        assert map_step_runner._token_cost(usage, "some-future-model") == 15.0

    def test_date_suffixed_model_id_resolves_to_real_price(self):
        # Real transcripts carry date-suffixed ids (e.g. a haiku sub-agent);
        # must price as haiku ($1/Mtok), NOT fall back to opus ($15/Mtok).
        usage = {"input": 1_000_000, "output": 0, "cache_creation": 0, "cache_read": 0}
        assert map_step_runner._token_cost(usage, "claude-haiku-4-5-20251001") == 1.0
        assert map_step_runner._model_price("claude-haiku-4-5-20251001")["input"] == 1.0

    def test_token_report_renders_table(self, branch_workspace):
        repo = branch_workspace.parents[1]
        transcript = repo / "tr.jsonl"
        transcript.write_text(self.TRANSCRIPT)
        self._state(branch_workspace)
        map_step_runner.record_token_event("test-branch", transcript_path=str(transcript))

        report = map_step_runner.token_report("test-branch")
        assert "ST-003" in report
        assert "TOTAL" in report
        assert "cache hit ratio" in report

    def test_cli_record_and_report_exit_zero(self, branch_workspace):
        repo = branch_workspace.parents[1]
        transcript = repo / "tr.jsonl"
        transcript.write_text(self.TRANSCRIPT)
        self._state(branch_workspace)
        runner = (
            Path(__file__).resolve().parents[1]
            / "src" / "mapify_cli" / "templates" / "map" / "scripts" / "map_step_runner.py"
        )
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        record = subprocess.run(
            [sys.executable, str(runner), "record_token_event", "test-branch",
             "--transcript", str(transcript)],
            capture_output=True, text=True, cwd=str(repo), env=env,
        )
        assert record.returncode == 0, record.stderr
        assert json.loads(record.stdout)["recorded"] == 2
        report = subprocess.run(
            [sys.executable, str(runner), "token_report", "test-branch"],
            capture_output=True, text=True, cwd=str(repo), env=env,
        )
        assert report.returncode == 0, report.stderr
        assert "cache hit ratio" in report.stdout


class TestBuildJsonRetryPrompt:
    """build_json_retry_prompt — canonical retry-prompt builder (ST-002).

    Verifies:
    - Shared-skeleton reuse: prompt contains _render_format_block output verbatim.
    - Mandated phrases present in every valid-agent response.
    - errors=None → ok, no failure section; errors=[...] → bullets + reasons echoed.
    - Unknown agent → status "error", empty prompt.
    """

    def test_build_json_retry_prompt_uses_shared_skeleton(self):
        """VC1: prompt embeds _render_format_block verbatim (single source of truth)."""
        result = map_step_runner.build_json_retry_prompt("monitor")
        assert result["status"] == "ok"
        expected_block = map_step_runner._render_format_block("monitor")
        assert expected_block in result["prompt"], (
            "prompt must contain the exact _render_format_block output"
        )

    def test_mandated_phrases_present(self):
        """VC2: prompt contains the two required literal phrases."""
        result = map_step_runner.build_json_retry_prompt("monitor")
        assert result["status"] == "ok"
        assert "Emit ONLY one JSON object matching this schema" in result["prompt"]
        assert "No markdown, no prose" in result["prompt"]

    def test_no_errors_returns_ok_no_failure_section(self):
        """VC3a: errors=None → status ok, prompt non-empty, no failure section."""
        result = map_step_runner.build_json_retry_prompt("monitor", errors=None)
        assert result["status"] == "ok"
        assert result["reasons"] == []
        assert result["prompt"] != ""
        assert "rejected for" not in result["prompt"]

    def test_empty_errors_list_returns_ok_no_failure_section(self):
        """VC3b: errors=[] → same as None (no failure section)."""
        result = map_step_runner.build_json_retry_prompt("predictor", errors=[])
        assert result["status"] == "ok"
        assert result["reasons"] == []
        assert "rejected for" not in result["prompt"]

    def test_errors_appear_in_prompt_and_reasons(self):
        """VC3c: non-empty errors → bullet list in prompt + echoed in reasons."""
        errs = ["missing key: valid", "trailing prose"]
        result = map_step_runner.build_json_retry_prompt("monitor", errors=errs)
        assert result["status"] == "ok"
        assert result["reasons"] == errs
        for err in errs:
            assert err in result["prompt"], f"error {err!r} must appear in prompt"
        assert "rejected for" in result["prompt"]

    def test_unknown_agent_returns_error_empty_prompt(self):
        """VC4: a genuinely unknown agent → status error, prompt empty."""
        result = map_step_runner.build_json_retry_prompt("reflector")
        assert result["status"] == "error"
        assert result["prompt"] == ""
        assert result["agent"] == "reflector"
        # reasons must include an 'unknown agent' entry
        assert any("unknown agent" in r for r in result["reasons"])

    def test_unknown_agent_preserves_caller_errors_in_reasons(self):
        """Unknown-agent path still echoes caller-supplied errors in reasons."""
        errs = ["some prior error"]
        result = map_step_runner.build_json_retry_prompt("reflector", errors=errs)
        assert result["status"] == "error"
        # caller errors are preserved (after the 'unknown agent' prepend)
        assert "some prior error" in result["reasons"]

    def test_actor_retry_prompt_builds(self):
        """Regression (Copilot review on PR #145): map-efficient's Actor
        truncation-recovery references `build_json_retry_prompt --agent actor`.
        Actor must therefore be a known agent that yields a real retry prompt
        (not the unknown-agent error path), embedding the shared actor skeleton
        and the mandated phrases.
        """
        result = map_step_runner.build_json_retry_prompt(
            "actor", errors=["missing required key: tests_run"]
        )
        assert result["status"] == "ok"
        assert result["agent"] == "actor"
        assert result["prompt"] != ""
        # embeds the shared actor format block (single source of truth)
        assert map_step_runner._render_format_block("actor") in result["prompt"]
        # actor-specific schema fields are present
        assert "files_changed" in result["prompt"]
        assert "tests_run" in result["prompt"]
        # mandated phrases + the caller error bullet
        assert "Emit ONLY one JSON object matching this schema" in result["prompt"]
        assert "missing required key: tests_run" in result["prompt"]

    def test_predictor_skeleton_reused(self):
        """Skeleton reuse also holds for predictor (not just monitor)."""
        result = map_step_runner.build_json_retry_prompt("predictor")
        assert result["status"] == "ok"
        expected_block = map_step_runner._render_format_block("predictor")
        assert expected_block in result["prompt"]

    def test_evaluator_skeleton_reused(self):
        """Skeleton reuse also holds for evaluator."""
        result = map_step_runner.build_json_retry_prompt("evaluator")
        assert result["status"] == "ok"
        expected_block = map_step_runner._render_format_block("evaluator")
        assert expected_block in result["prompt"]


class TestAgentFailureTelemetry:
    """ST-003: branch-scoped agent-failure telemetry with INV-8 sanitization."""

    # ------------------------------------------------------------------
    # VC1: _agent_failure_log_path is branch-scoped under get_branch_dir
    # ------------------------------------------------------------------

    def test_agent_failure_log_path_branch_scoped(self):
        """VC1: path resolves to get_branch_dir(branch) / agent_failure_events.jsonl."""
        branch = "somebranch"
        expected = map_step_runner.get_branch_dir(branch) / "agent_failure_events.jsonl"
        assert map_step_runner._agent_failure_log_path(branch) == expected

    # ------------------------------------------------------------------
    # VC2: _validate_agent_failure_event rejects bad labels / missing fields
    # ------------------------------------------------------------------

    def test_validate_good_event_returns_empty(self):
        """VC2a: fully-valid event → empty reasons list."""
        event: dict[str, object] = {
            "agent": "monitor",
            "phase": "REVIEW",
            "failure_label": "format_violation",
            "timestamp": "2026-05-27T00:00:00Z",
        }
        assert map_step_runner._validate_agent_failure_event(event) == []

    def test_validate_bad_label_returns_reason(self):
        """VC2b (HC-6): unknown failure_label → non-empty reasons."""
        event: dict[str, object] = {
            "agent": "monitor",
            "phase": "REVIEW",
            "failure_label": "exploded",
            "timestamp": "2026-05-27T00:00:00Z",
        }
        reasons = map_step_runner._validate_agent_failure_event(event)
        assert len(reasons) > 0
        assert any("exploded" in r for r in reasons)

    def test_validate_missing_field_returns_reason(self):
        """VC2c: missing required field → non-empty reasons."""
        event: dict[str, object] = {
            "phase": "REVIEW",
            "failure_label": "truncated",
            "timestamp": "2026-05-27T00:00:00Z",
            # 'agent' intentionally absent
        }
        reasons = map_step_runner._validate_agent_failure_event(event)
        assert any("agent" in r for r in reasons)

    # ------------------------------------------------------------------
    # VC3: log_agent_failure rejects bad label without writing
    # ------------------------------------------------------------------

    def test_log_agent_failure_bad_label_no_write(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """VC3 (HC-6): bad failure_label → status=error, no JSONL written."""
        monkeypatch.chdir(tmp_path)
        result = map_step_runner.log_agent_failure(
            "monitor", "REVIEW", "exploded", branch="test-branch"
        )
        assert result["status"] == "error"
        assert result["path"] is None
        log_path = map_step_runner._agent_failure_log_path("test-branch")
        assert not log_path.exists()

    # ------------------------------------------------------------------
    # VC4: log_agent_failure appends exactly one JSONL line + INV-8
    # ------------------------------------------------------------------

    def test_log_agent_failure_appends_jsonl(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """VC4a: valid call → exactly one well-formed JSONL line appended."""
        monkeypatch.chdir(tmp_path)
        result = map_step_runner.log_agent_failure(
            "monitor",
            "REVIEW",
            "format_violation",
            reasons=["output missing 'valid' key"],
            retry=True,
            schema="MonitorOutput",
            branch="test-branch",
        )
        assert result["status"] == "ok"
        log_path = map_step_runner._agent_failure_log_path("test-branch")
        assert log_path.exists()
        lines = log_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["agent"] == "monitor"
        assert parsed["phase"] == "REVIEW"
        assert parsed["failure_label"] == "format_violation"
        assert parsed["retry"] is True
        assert parsed["schema"] == "MonitorOutput"
        assert "timestamp" in parsed

    def test_log_agent_failure_inv8_sanitization(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """VC4b (INV-8): control chars in reasons are stripped; result is jq-parseable."""
        monkeypatch.chdir(tmp_path)
        dirty_reasons = ["bad\noutput", "tab\there", "null\x00byte"]
        result = map_step_runner.log_agent_failure(
            "actor",
            "ACTOR",
            "missing_field",
            reasons=dirty_reasons,
            branch="test-branch",
        )
        assert result["status"] == "ok"
        log_path = map_step_runner._agent_failure_log_path("test-branch")
        raw_line = log_path.read_text(encoding="utf-8").strip()
        # Must parse cleanly
        parsed = json.loads(raw_line)
        # No raw control characters remain in any string field
        control_re = re.compile(r"[\x00-\x1f\x7f]")
        for reason in parsed["reasons"]:
            assert control_re.search(reason) is None, (
                f"Control char found in reason: {reason!r}"
            )
        assert control_re.search(parsed["agent"]) is None
        assert control_re.search(parsed["phase"]) is None

    def test_log_agent_failure_second_call_appends(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """VC4c: two successive calls → two lines in the JSONL file."""
        monkeypatch.chdir(tmp_path)
        for label in ("format_violation", "truncated"):
            map_step_runner.log_agent_failure(
                "monitor", "REVIEW", label, branch="test-branch"
            )
        log_path = map_step_runner._agent_failure_log_path("test-branch")
        lines = log_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["failure_label"] == "format_violation"
        assert json.loads(lines[1])["failure_label"] == "truncated"


# ---------------------------------------------------------------------------
# ST-006: Tests for the three new guards
# ---------------------------------------------------------------------------


class TestChangedLineNumbersByFile:
    """VC1: _changed_line_numbers_by_file parses unified diff into
    {relative_path: set[new_file_line_number]} for added (+) lines only.
    Header lines (+++ / ---) are NOT recorded as content.
    """

    def test_vc1_parses_added_line_numbers_single_hunk(self) -> None:
        """Single hunk with @@ -10,3 +10,4 @@: one added line at new-file line 12."""
        diff = (
            "diff --git a/f.py b/f.py\n"
            "--- a/f.py\n"
            "+++ b/f.py\n"
            "@@ -10,3 +10,4 @@\n"
            " context_line\n"   # line 10 — context, new_line → 11
            " context_line2\n"  # line 11 — context, new_line → 12
            "+added_line\n"     # added at new_file line 12
            " context_line3\n"  # context, new_line → 13
        )
        result = map_step_runner._changed_line_numbers_by_file(diff)
        assert "f.py" in result
        assert 12 in result["f.py"]
        # Only the one added line is recorded.
        assert result["f.py"] == {12}

    def test_vc1_parses_added_line_numbers_multi_hunk(self) -> None:
        """Two hunks in the same file → lines from both collected under one key."""
        diff = (
            "diff --git a/src/foo.py b/src/foo.py\n"
            "--- a/src/foo.py\n"
            "+++ b/src/foo.py\n"
            "@@ -1,2 +1,3 @@\n"
            " a\n"      # line 1, new_line → 2
            "+b\n"      # added at new-file line 2
            " c\n"      # context
            "@@ -20,1 +21,2 @@\n"
            " x\n"      # line 21, new_line → 22
            "+y\n"      # added at new-file line 22
        )
        result = map_step_runner._changed_line_numbers_by_file(diff)
        assert "src/foo.py" in result
        assert 2 in result["src/foo.py"]
        assert 22 in result["src/foo.py"]

    def test_vc1_headers_not_recorded_as_content(self) -> None:
        """'+++ b/f.py' header lines must not appear as added line numbers."""
        diff = (
            "diff --git a/f.py b/f.py\n"
            "--- a/f.py\n"
            "+++ b/f.py\n"
            "@@ -1,1 +1,2 @@\n"
            " existing\n"
            "+added\n"
        )
        result = map_step_runner._changed_line_numbers_by_file(diff)
        # Only "f.py" key — no "b/f.py" header bleed-through.
        assert list(result.keys()) == ["f.py"]
        # 1 added line — the "+added" line at position 2.
        assert len(result["f.py"]) == 1

    def test_vc1_dev_null_source_ignored(self) -> None:
        """New-file diffs with '--- /dev/null' must still record added lines."""
        diff = (
            "diff --git a/new.py b/new.py\n"
            "--- /dev/null\n"
            "+++ b/new.py\n"
            "@@ -0,0 +1,2 @@\n"
            "+line_one\n"
            "+line_two\n"
        )
        result = map_step_runner._changed_line_numbers_by_file(diff)
        assert "new.py" in result
        assert result["new.py"] == {1, 2}

    def test_vc1_empty_diff_returns_empty(self) -> None:
        assert map_step_runner._changed_line_numbers_by_file("") == {}


class TestEnclosingChangedSymbols:
    """VC1: _enclosing_changed_symbols maps changed line numbers to the
    enclosing top-level symbol name.

    Rules:
    - FunctionDef, AsyncFunctionDef, ClassDef → name kept if len>=3, not dunder.
    - Assign / AnnAssign with Name target: same filter.
    - Leading underscore names (_PRIVATE) are KEPT.
    - Dunder names (__all__) and short names (ab) are EXCLUDED.
    - Nested functions → maps to the enclosing top-level symbol, NOT the nested name.
    - SyntaxError or missing file → returns None.
    """

    # Shared source fixture written to a temp file.
    _SOURCE = """\
_PRIVATE_CONST = (1, 2)

def shared_fn(x):
    # body line 4
    return x + 1

class Foo:
    def method(self):
        def _inner():
            pass
        return _inner()

__all__ = ["shared_fn"]

ab = 1
"""

    def _write_source(self, tmp_path: Path) -> Path:
        p = tmp_path / "module.py"
        p.write_text(self._SOURCE, encoding="utf-8")
        return p

    def test_vc1_body_change_maps_to_enclosing_function(self, tmp_path: Path) -> None:
        """Line inside shared_fn's body → {'shared_fn'}."""
        src = self._write_source(tmp_path)
        # Line 4 is "    # body line 4" inside shared_fn.
        result = map_step_runner._enclosing_changed_symbols(src, {4})
        assert result is not None
        assert "shared_fn" in result

    def test_vc1_underscore_const_detected(self, tmp_path: Path) -> None:
        """Leading-underscore names like _PRIVATE_CONST must be kept."""
        src = self._write_source(tmp_path)
        # Line 1 is "_PRIVATE_CONST = (1, 2)".
        result = map_step_runner._enclosing_changed_symbols(src, {1})
        assert result is not None
        assert "_PRIVATE_CONST" in result

    def test_vc1_dunder_and_short_excluded(self, tmp_path: Path) -> None:
        """__all__ (dunder) and ab (2-char) must NOT appear in result."""
        src = self._write_source(tmp_path)
        # __all__ is on line 13; ab is on line 15.
        result = map_step_runner._enclosing_changed_symbols(src, {13, 15})
        assert result is not None
        assert "__all__" not in result
        assert "ab" not in result

    def test_vc1_nested_not_surfaced(self, tmp_path: Path) -> None:
        """A line inside a nested function maps to the top-level enclosing symbol."""
        src = self._write_source(tmp_path)
        # Line 10 is "            pass" inside _inner() inside Foo.method().
        # Top-level enclosing node is class Foo.
        result = map_step_runner._enclosing_changed_symbols(src, {10})
        assert result is not None
        assert "Foo" in result
        assert "_inner" not in result

    def test_vc3_syntax_error_returns_none(self, tmp_path: Path) -> None:
        """SyntaxError in source → None (fail-safe / unknown signal)."""
        bad = tmp_path / "bad.py"
        bad.write_text("def broken(\n", encoding="utf-8")
        result = map_step_runner._enclosing_changed_symbols(bad, {1})
        assert result is None

    def test_vc3_missing_file_returns_none(self, tmp_path: Path) -> None:
        """Non-existent file → None (OSError caught)."""
        missing = tmp_path / "no_such_file.py"
        result = map_step_runner._enclosing_changed_symbols(missing, {1})
        assert result is None

    def test_is_reportable_symbol_excludes_main(self) -> None:
        """Regression: generic process entrypoint `main` is not a reportable symbol.

        A `def main()` is invoked by convention (``if __name__ == "__main__"``)
        and matches the literal word "main" in every SKILL.md / settings.json,
        flooding the blast-radius gate with false external callers.
        """
        assert map_step_runner._is_reportable_symbol("main") is False
        # Real shared helpers and private constants stay reportable.
        assert map_step_runner._is_reportable_symbol("shared_fn") is True
        assert map_step_runner._is_reportable_symbol("_MONITOR_REQUIRED_KEYS") is True
        # Existing exclusions still hold.
        assert map_step_runner._is_reportable_symbol("__all__") is False
        assert map_step_runner._is_reportable_symbol("ab") is False

    def test_generic_main_excluded_from_changed_symbols(self, tmp_path: Path) -> None:
        """Regression: a changed `def main()` body does not surface `main`."""
        src = tmp_path / "hook.py"
        src.write_text(
            "import os, sys\n"
            "\n"
            "def main() -> None:\n"
            "    if os.environ.get('MAP_INVOKED_BY'):\n"
            "        sys.exit(0)\n"
            "    print('work')\n"
            "\n"
            "def shared_helper(x):\n"
            "    return x + 1\n",
            encoding="utf-8",
        )
        # Line 4 is inside main(); line 9 is inside shared_helper().
        result = map_step_runner._enclosing_changed_symbols(src, {4, 9})
        assert result is not None
        assert "main" not in result
        assert "shared_helper" in result


class TestDetectSymbolBlastRadius:
    """VC2-VC4: detect_symbol_blast_radius end-to-end with a real temp git repo.

    Mirrors TestDetectCrossSubtaskRegressionRisk fixture pattern.
    """

    def _init_git(self, root: Path) -> None:
        subprocess.run(["git", "init"], cwd=root, capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "t@t.com"], cwd=root, capture_output=True, check=True
        )
        subprocess.run(
            ["git", "config", "user.name", "t"], cwd=root, capture_output=True, check=True
        )
        (root / ".seed").write_text("seed\n")
        subprocess.run(["git", "add", "."], cwd=root, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "init"], cwd=root, capture_output=True, check=True
        )
        head = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"],
            cwd=root, capture_output=True, text=True,
        )
        assert head.returncode == 0, "test setup: initial commit produced no resolvable HEAD"

    def _write_state(self, branch_dir: Path, last_sha: str = "") -> None:
        state: dict[str, object] = {"subtask_results": {}}
        if last_sha:
            state["last_subtask_commit_sha"] = last_sha
        (branch_dir / "step_state.json").write_text(json.dumps(state))

    def _write_blueprint(self, branch_dir: Path, affected_files: list[str]) -> None:
        bp = {"subtasks": [{"id": "ST-001", "affected_files": affected_files}]}
        (branch_dir / "blueprint.json").write_text(json.dumps(bp))

    def test_vc2_external_caller_yields_validate_callers(
        self, branch_workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """VC2: symbol changed in runner.py; .claude/skills/foo/SKILL.md references it
        externally → recommended_gate=='validate_callers'."""
        repo = branch_workspace.parents[1]
        self._init_git(repo)
        self._write_blueprint(branch_workspace, ["runner.py"])

        # Write base version of runner.py and commit it (establishes HEAD).
        (repo / "runner.py").write_text(
            "def shared_fn(x):\n    return x\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "base"], cwd=repo, capture_output=True, check=True
        )

        # Plant an external caller in .claude/skills/ (one of _GREP_SEARCH_PATHS).
        skill_dir = repo / ".claude" / "skills" / "foo"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "Uses shared_fn to do the thing.\n", encoding="utf-8"
        )
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "add skill"], cwd=repo, capture_output=True, check=True
        )

        # Record the SHA of the last subtask so the diff covers the body change.
        last_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo, capture_output=True, text=True,
        ).stdout.strip()
        self._write_state(branch_workspace, last_sha=last_sha)

        # Now body-change shared_fn (staged/uncommitted).
        (repo / "runner.py").write_text(
            "def shared_fn(x):\n    return x + 1  # changed\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)

        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        report = map_step_runner.detect_symbol_blast_radius("test-branch", "ST-001")

        assert "shared_fn" in report["changed_symbols"], report
        external_files = [c["file"] for c in report["external_callers"]]
        assert any(".claude/skills" in f for f in external_files), report
        assert report["recommended_gate"] == "validate_callers", report

    def test_vc2_no_external_caller_scoped(
        self, branch_workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """VC2: symbol referenced ONLY within affected_files → recommended_gate=='scoped'."""
        repo = branch_workspace.parents[1]
        self._init_git(repo)
        self._write_blueprint(branch_workspace, ["runner.py"])

        (repo / "runner.py").write_text(
            "def internal_fn(x):\n    return x\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
        base = subprocess.run(
            ["git", "commit", "-m", "base"], cwd=repo, capture_output=True, text=True
        )
        assert base.returncode == 0

        last_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo, capture_output=True, text=True,
        ).stdout.strip()
        self._write_state(branch_workspace, last_sha=last_sha)

        # Body-change internal_fn — no external callers anywhere.
        (repo / "runner.py").write_text(
            "def internal_fn(x):\n    return x * 2  # changed\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)

        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        report = map_step_runner.detect_symbol_blast_radius("test-branch", "ST-001")

        assert report["status"] == "ok", report
        assert report["recommended_gate"] == "scoped", report

    def test_vc3_stale_base_ref_fails_safe(
        self, branch_workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """VC3: last_subtask_commit_sha='0'*40 (nonexistent) → status=='unknown',
        recommended_gate=='validate_callers' (fail-safe, never silently 'scoped')."""
        repo = branch_workspace.parents[1]
        self._init_git(repo)
        self._write_blueprint(branch_workspace, ["runner.py"])
        self._write_state(branch_workspace, last_sha="0" * 40)

        (repo / "runner.py").write_text("def any_fn(x):\n    return x\n")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)

        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        report = map_step_runner.detect_symbol_blast_radius("test-branch", "ST-001")

        assert report["status"] == "unknown", report
        assert report["recommended_gate"] == "validate_callers", report

    def test_vc4_pr145_motivating_case(
        self, branch_workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """VC4 / PR #145 regression: runner.py has _MONITOR_REQUIRED_KEYS and
        detect_truncated(); a skill references both. Changing both symbols
        must produce changed_symbols containing both and recommended_gate=='validate_callers'.

        This is the exact failure mode PR #145 was designed to prevent:
        re-deriving a shared helper in one subtask breaks callers that are
        never re-tested in the scoped gate.
        """
        repo = branch_workspace.parents[1]
        self._init_git(repo)
        self._write_blueprint(branch_workspace, ["runner.py"])

        base_source = (
            "_MONITOR_REQUIRED_KEYS = ('severity', 'justification')\n"
            "\n"
            "def detect_truncated(output):\n"
            "    return any(k not in output for k in _MONITOR_REQUIRED_KEYS)\n"
        )
        (repo / "runner.py").write_text(base_source, encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "base"], cwd=repo, capture_output=True, check=True
        )

        # Plant skill that references BOTH symbols.
        skill_dir = repo / ".claude" / "skills" / "monitor"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "Calls detect_truncated using _MONITOR_REQUIRED_KEYS.\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "add skill"], cwd=repo, capture_output=True, check=True
        )

        last_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo, capture_output=True, text=True,
        ).stdout.strip()
        self._write_state(branch_workspace, last_sha=last_sha)

        # Mutate BOTH symbols.
        changed_source = (
            "_MONITOR_REQUIRED_KEYS = ('severity', 'justification', 'sibling_comparison')\n"
            "\n"
            "def detect_truncated(output):\n"
            "    # body changed\n"
            "    return any(k not in output for k in _MONITOR_REQUIRED_KEYS)\n"
        )
        (repo / "runner.py").write_text(changed_source, encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)

        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        report = map_step_runner.detect_symbol_blast_radius("test-branch", "ST-001")

        assert "_MONITOR_REQUIRED_KEYS" in report["changed_symbols"], report
        assert "detect_truncated" in report["changed_symbols"], report
        assert report["recommended_gate"] == "validate_callers", report

    def test_vc_cli_exits_zero(
        self, branch_workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CLI is advisory: exit 0 always; result is parseable JSON."""
        del monkeypatch
        repo = branch_workspace.parents[1]
        self._init_git(repo)
        self._write_blueprint(branch_workspace, ["runner.py"])
        self._write_state(branch_workspace)
        runner = SCRIPTS_PATH / "map_step_runner.py"
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "CLAUDE_PROJECT_DIR": str(repo)}
        result = subprocess.run(
            [sys.executable, str(runner), "detect_symbol_blast_radius", "test-branch", "ST-001"],
            capture_output=True, text=True, cwd=str(repo), env=env,
        )
        assert result.returncode == 0, result.stderr
        parsed = json.loads(result.stdout)
        assert "recommended_gate" in parsed


class TestDetectActorFilesChangedMismatch:
    """VC1-VC3: detect_actor_files_changed_mismatch catches declared-but-not-written files.

    Mirrors TestDetectCrossSubtaskRegressionRisk fixture pattern.
    """

    def _init_git(self, root: Path) -> None:
        subprocess.run(["git", "init"], cwd=root, capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "t@t.com"], cwd=root, capture_output=True, check=True
        )
        subprocess.run(
            ["git", "config", "user.name", "t"], cwd=root, capture_output=True, check=True
        )
        (root / ".seed").write_text("seed\n")
        subprocess.run(["git", "add", "."], cwd=root, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "init"], cwd=root, capture_output=True, check=True
        )
        head = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"],
            cwd=root, capture_output=True, text=True,
        )
        assert head.returncode == 0, "test setup: initial commit produced no resolvable HEAD"

    def _write_state(self, branch_dir: Path) -> None:
        (branch_dir / "step_state.json").write_text(
            json.dumps({"subtask_results": {}})
        )

    def test_vc1_declared_not_written_listed(
        self, branch_workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """VC1: declare a.py + b.py; only a.py actually changed → declared_not_written==['b.py']."""
        repo = branch_workspace.parents[1]
        self._init_git(repo)
        self._write_state(branch_workspace)

        # Only write a.py (b.py is declared but never written).
        (repo / "a.py").write_text("x = 1\n")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)

        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        report = map_step_runner.detect_actor_files_changed_mismatch(
            "test-branch", "ST-001", ["a.py", "b.py"]
        )

        assert report["declared_not_written"] == ["b.py"], report
        assert report["status_mismatch"] is True, report

    def test_vc2_mismatch_sets_recovery(
        self, branch_workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """VC2: mismatch → status_mismatch=True + non-empty recovery_instruction."""
        repo = branch_workspace.parents[1]
        self._init_git(repo)
        self._write_state(branch_workspace)

        (repo / "a.py").write_text("x = 1\n")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)

        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        report = map_step_runner.detect_actor_files_changed_mismatch(
            "test-branch", "ST-001", ["a.py", "b.py"]
        )

        assert report["status_mismatch"] is True, report
        assert report["recovery_instruction"] != "", report

    def test_vc2_clean_no_recovery(
        self, branch_workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """VC2: declared files all written → status_mismatch=False, recovery_instruction=''."""
        repo = branch_workspace.parents[1]
        self._init_git(repo)
        self._write_state(branch_workspace)

        (repo / "a.py").write_text("x = 1\n")
        (repo / "b.py").write_text("y = 2\n")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)

        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        report = map_step_runner.detect_actor_files_changed_mismatch(
            "test-branch", "ST-001", ["a.py", "b.py"]
        )

        assert report["status_mismatch"] is False, report
        assert report["recovery_instruction"] == "", report

    def test_vc3_git_error_failsafe(
        self, branch_workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """VC3: stale/nonexistent SHA → status=='unknown', status_mismatch=True,
        declared_not_written == declared (fail-safe, all files assumed unwritten)."""
        repo = branch_workspace.parents[1]
        self._init_git(repo)
        # Plant a stale SHA so git diff fails.
        (branch_workspace / "step_state.json").write_text(
            json.dumps({"subtask_results": {}, "last_subtask_commit_sha": "0" * 40})
        )

        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        report = map_step_runner.detect_actor_files_changed_mismatch(
            "test-branch", "ST-001", ["a.py", "b.py"]
        )

        assert report["status"] == "unknown", report
        assert report["status_mismatch"] is True, report
        assert report["declared_not_written"] == ["a.py", "b.py"], report

    def test_vc3_cli_exits_zero(
        self, branch_workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """VC3: CLI with --declared a.py,b.py → exit 0, JSON parseable."""
        del monkeypatch
        repo = branch_workspace.parents[1]
        self._init_git(repo)
        self._write_state(branch_workspace)
        runner = SCRIPTS_PATH / "map_step_runner.py"
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "CLAUDE_PROJECT_DIR": str(repo)}
        result = subprocess.run(
            [
                sys.executable, str(runner),
                "detect_actor_files_changed_mismatch",
                "test-branch", "ST-001",
                "--declared", "a.py,b.py",
            ],
            capture_output=True, text=True, cwd=str(repo), env=env,
        )
        assert result.returncode == 0, result.stderr
        parsed = json.loads(result.stdout)
        assert "status_mismatch" in parsed
