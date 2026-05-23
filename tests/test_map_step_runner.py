"""Tests for map_step_runner human-readable artifact helpers."""

import json
import os
import subprocess
import sys
import types
from pathlib import Path
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


def _valid_run_health_payload() -> dict[str, object]:
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
    assert any("soft_constraints requirement 'SC-1' must either appear in coverage_map" in error for error in result["errors"])


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

    def test_build_context_block_enforces_budget(
        self, branch_workspace, monkeypatch
    ):
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

        assert map_step_runner._estimate_tokens(result) <= 260
        assert result.startswith("<map_context>")
        assert result.endswith("</map_context>")
        # Truncation marker replaced "# Context Budget: truncated..." with the
        # compact "# [TRUNCATED] see .map/<branch>/token_budget.json" so the
        # warning itself doesn't blow the budget. Either signal proves a clip
        # happened — assert the new in-band marker.
        assert "# [TRUNCATED] see .map/<branch>/token_budget.json" in result
        assert "Current task that must stay visible" in result
        assert "Actor -> bounded context -> done" in result
        assert "# Upstream Results" in result
        assert "dependency summary" in result

        budget_report = json.loads(
            (branch_workspace / "token_budget.json").read_text(encoding="utf-8")
        )
        decision = budget_report["decisions"][-1]
        assert decision["path_name"] == "map-efficient.actor_context_block"
        assert decision["budget_action"] == "truncated"
        assert decision["configured_budget_tokens"] == 260
        assert decision["estimated_tokens_after"] <= 260
        assert "plan_overview" in decision["clipped_sections"]

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

    def test_repo_delta_capped_at_20_files(self, branch_workspace):
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
        assert "file_19.py" in result
        assert "file_20.py" not in result
        assert "... +5 more" in result

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

    def test_build_review_prompts_budgets_secondary_diff_before_bundle(
        self, branch_workspace
    ):
        """Oversized review prompts keep primary bundle context and clip raw diff first."""
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
        assert result["budget_tokens"] == 1_500
        for role in ("monitor", "predictor", "evaluator"):
            prompt_info = result["prompts"][role]
            prompt = prompt_info["prompt"]
            assert prompt_info["estimated_tokens"] <= 1_500
            assert prompt_info["truncated"] is True
            assert "git diff" in prompt_info["clipped_sections"]
            assert "review-bundle.md" not in prompt_info["clipped_sections"]
            assert "PRIMARY_BUNDLE_SENTINEL" in prompt
            assert "TAIL_DIFF_SENTINEL" not in prompt
            assert "Review Prompt Budget" in prompt
            assert "<documents>" in prompt
            assert "</documents>" in prompt
            assert "<expected_output>" in prompt
            assert "Output JSON with:" in prompt

        budget_report = json.loads(
            (branch_workspace / "token_budget.json").read_text(encoding="utf-8")
        )
        decisions = budget_report["decisions"][-3:]
        assert [decision["path_name"] for decision in decisions] == [
            "map-review.monitor_prompt",
            "map-review.predictor_prompt",
            "map-review.evaluator_prompt",
        ]
        assert all(decision["budget_action"] == "truncated" for decision in decisions)
        assert all("git diff" in decision["clipped_sections"] for decision in decisions)
        manifest = json.loads(
            (branch_workspace / "artifact_manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["stages"]["token_budget"]["status"] == "ready"

    def test_build_review_prompts_budgets_large_review_preferences(
        self, branch_workspace
    ):
        """Oversized review preferences must not break the prompt budget."""
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
            assert prompt_info["estimated_tokens"] <= 1_500
            assert prompt_info["truncated"] is True
            assert "review-preferences" in prompt_info["clipped_sections"]
            assert "PRIMARY_BUNDLE_SENTINEL" in prompt
            assert "TAIL_PREFERENCES_SENTINEL" not in prompt

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

    def test_review_prompt_ab_reduces_old_unbounded_prompt_size(self, branch_workspace):
        """A/B: new budgeted reviewer prompt is smaller than old inline prompt."""
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

        assert map_step_runner._estimate_tokens(old_prompt) > 1_500
        assert new_prompt_info["estimated_tokens"] <= 1_500
        assert new_prompt_info["estimated_tokens"] < map_step_runner._estimate_tokens(
            old_prompt
        )
        assert "TAIL_DIFF_SENTINEL" in old_prompt
        assert "TAIL_DIFF_SENTINEL" not in new_prompt
        assert "PRIMARY_BUNDLE_SENTINEL" in new_prompt
        assert "Review Prompt Budget" in new_prompt


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
