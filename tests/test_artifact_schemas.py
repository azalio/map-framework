"""Focused tests for new artifact schemas without importing package extras."""

import importlib.util
from pathlib import Path


SCHEMAS_PATH = Path(__file__).resolve().parents[1] / "src" / "mapify_cli" / "schemas.py"
SPEC = importlib.util.spec_from_file_location("artifact_schemas", SCHEMAS_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_validate_workflow_fit_decision_schema():
    artifact = {
        "version": "1.0",
        "recommended_workflow": "map-plan",
        "needs_map": True,
        "decision_summary": "New invariants require planning.",
        "signals": {
            "expected_diff_size": "large",
            "has_new_invariants": True,
            "needs_independent_review": True,
            "has_clear_acceptance_criteria": False,
            "test_first_required": True,
        },
        "updated_at": "2026-04-12T13:30:00",
    }

    is_valid, errors = MODULE.validate_artifact(
        artifact, MODULE.WORKFLOW_FIT_DECISION_SCHEMA
    )
    assert is_valid, f"Errors: {errors}"


def test_validate_artifact_manifest_schema():
    stage = {
        "status": "ready",
        "updated_at": "2026-04-12T13:30:00",
        "artifacts": [{"path": ".map/test/spec_test.md", "kind": "spec"}],
        "metadata": {},
    }
    artifact = {
        "schema_version": "1.0",
        "branch": "test-branch",
        "updated_at": "2026-04-12T13:30:00",
        "stages": {
            "workflow_fit": stage,
            "spec": stage,
            "plan": stage,
            "test_contract": stage,
            "implementation": stage,
            "review": stage,
            "verification": stage,
            "run_health": stage,
            "learn_handoff": stage,
        },
    }

    is_valid, errors = MODULE.validate_artifact(
        artifact, MODULE.ARTIFACT_MANIFEST_SCHEMA
    )
    assert is_valid, f"Errors: {errors}"


def test_validate_artifact_manifest_schema_accepts_legacy_without_run_health():
    stage = {
        "status": "ready",
        "updated_at": "2026-04-12T13:30:00",
        "artifacts": [],
        "metadata": {},
    }
    artifact = {
        "schema_version": "1.0",
        "branch": "test-branch",
        "updated_at": "2026-04-12T13:30:00",
        "stages": {
            "workflow_fit": stage,
            "spec": stage,
            "plan": stage,
            "test_contract": stage,
            "implementation": stage,
            "review": stage,
            "verification": stage,
            "learn_handoff": stage,
        },
    }

    is_valid, errors = MODULE.validate_artifact(
        artifact, MODULE.ARTIFACT_MANIFEST_SCHEMA
    )
    assert is_valid, f"Errors: {errors}"


def test_validate_run_health_report_schema():
    artifact_entry = {
        "kind": "state",
        "path": ".map/test-branch/step_state.json",
        "present": True,
        "size_bytes": 123,
    }
    artifact = {
        "schema_version": "1.0",
        "generated_at": "2026-05-15T10:00:00Z",
        "workflow": "map-efficient",
        "branch": "test-branch",
        "terminal_status": "blocked",
        "current_step_id": "2.4",
        "current_step_phase": "MONITOR",
        "current_subtask_id": "ST-001",
        "completed_step_count": 3,
        "pending_step_count": 1,
        "artifacts": {
            "step_state": artifact_entry,
            "artifact_manifest": artifact_entry,
            "verification_summary": artifact_entry,
            "qa": artifact_entry,
            "pr_draft": artifact_entry,
            "review_bundle": artifact_entry,
            "learning_handoff": artifact_entry,
            "task_plan": artifact_entry,
            "blueprint": artifact_entry,
            "active_issues": artifact_entry,
            "known_issues": artifact_entry,
        },
        "resiliency_signals": {
            "hook_injection": {"status": "injected"},
            "hook_injection_counts": {"injected": 1},
            "retry_count": 2,
            "max_retries": 5,
            "subtask_retry_counts": {"ST-001": 1},
            "max_subtask_retry_count": 1,
            "guard_rework_counts": {},
            "predictor_called": False,
            "predictor_skipped": True,
            "final_verifier_executed": False,
        },
    }

    is_valid, errors = MODULE.validate_artifact(
        artifact, MODULE.RUN_HEALTH_REPORT_SCHEMA
    )
    assert is_valid, f"Errors: {errors}"


def test_run_health_report_schema_rejects_missing_inventory_and_hook_status():
    artifact = {
        "schema_version": "1.0",
        "generated_at": "2026-05-15T10:00:00Z",
        "workflow": "map-efficient",
        "branch": "test-branch",
        "terminal_status": "pending",
        "completed_step_count": 0,
        "pending_step_count": 0,
        "artifacts": {},
        "resiliency_signals": {
            "hook_injection": {},
            "hook_injection_counts": {},
            "retry_count": 0,
            "max_retries": 0,
            "subtask_retry_counts": {},
            "max_subtask_retry_count": 0,
            "guard_rework_counts": {},
            "predictor_called": False,
            "predictor_skipped": False,
            "final_verifier_executed": False,
        },
    }

    is_valid = MODULE.validate_artifact(artifact, MODULE.RUN_HEALTH_REPORT_SCHEMA)[0]
    assert not is_valid


def test_run_health_report_schema_rejects_invalid_terminal_status():
    artifact = {
        "schema_version": "1.0",
        "generated_at": "2026-05-15T10:00:00Z",
        "workflow": "map-efficient",
        "branch": "test-branch",
        "terminal_status": "done",
        "completed_step_count": 0,
        "pending_step_count": 0,
        "artifacts": {},
        "resiliency_signals": {
            "hook_injection": {},
            "hook_injection_counts": {},
            "retry_count": 0,
            "max_retries": 0,
            "subtask_retry_counts": {},
            "max_subtask_retry_count": 0,
            "guard_rework_counts": {},
            "predictor_called": False,
            "predictor_skipped": False,
            "final_verifier_executed": False,
        },
    }

    is_valid = MODULE.validate_artifact(artifact, MODULE.RUN_HEALTH_REPORT_SCHEMA)[0]
    assert not is_valid


def test_validate_test_handoff_schema():
    artifact = {
        "subtask_id": "ST-001",
        "status": "contract_ready",
        "contract_path": ".map/test-branch/test_contract_ST-001.md",
        "failing_test_command": "pytest tests/test_auth.py -q",
        "test_files": ["tests/test_auth.py"],
        "contract_summary": "Lock auth behavior before code generation.",
        "notes": "",
        "updated_at": "2026-04-12T13:30:00",
    }

    is_valid, errors = MODULE.validate_artifact(artifact, MODULE.TEST_HANDOFF_SCHEMA)
    assert is_valid, f"Errors: {errors}"


def test_validate_review_bundle_schema():
    """Minimal-conformant review bundle validates against REVIEW_BUNDLE_SCHEMA."""
    artifact_entry = {
        "present": True,
        "path": ".map/test-branch/spec_test-branch.md",
        "sanitized_text": "# Spec content",
        "truncated": False,
        "reason": None,
        "kind": "spec",
    }
    missing_entry = {
        "present": False,
        "path": None,
        "sanitized_text": None,
        "reason": "not found",
        "kind": "blueprint",
    }
    numbered_entry = {
        "present": True,
        "path": ".map/test-branch/plan-review-001.md",
        "sanitized_text": "Review notes",
        "truncated": False,
        "index": 1,
        "reason": None,
    }
    missing_numbered = {
        "present": False,
        "path": None,
        "sanitized_text": None,
        "index": None,
        "reason": "none recorded",
    }
    multi_entry = {
        "path": ".map/test-branch/test_handoff_ST001.json",
        "sanitized_text": '{"subtask_id": "ST-001"}',
        "truncated": False,
    }

    bundle = {
        "status": "success",
        "branch": "test-branch",
        "bundle_path_json": ".map/test-branch/review-bundle.json",
        "bundle_path_md": ".map/test-branch/review-bundle.md",
        "generated_at": "2026-05-11T12:00:00Z",
        "artifacts": {
            "spec": artifact_entry,
            "task_plan": {**artifact_entry, "kind": "task_plan", "path": ".map/test-branch/task_plan_test-branch.md"},
            "blueprint": missing_entry,
            "verification_summary": {**artifact_entry, "kind": "verification_summary", "path": ".map/test-branch/verification-summary.md"},
            "qa": {**artifact_entry, "kind": "qa", "path": ".map/test-branch/qa-001.md"},
            "pr_draft": {**artifact_entry, "kind": "pr_draft", "path": ".map/test-branch/pr-draft.md"},
            "active_issues": {**artifact_entry, "kind": "active_issues", "path": ".map/test-branch/active-issues.json"},
            "artifact_manifest": {**artifact_entry, "kind": "artifact_manifest", "path": ".map/test-branch/artifact_manifest.json"},
            "run_health_report": {**artifact_entry, "kind": "run_health_report", "path": ".map/test-branch/run_health_report.json"},
            "latest_plan_review": numbered_entry,
            "latest_code_review": missing_numbered,
            "test_handoffs": [multi_entry],
            "test_contracts": [],
        },
        "code_state": {
            "status": "success",
            "git_ref": "abc123def456",
            "files_changed": ["src/foo.py"],
            "diff_stat": "1 file changed",
            "branch": "test-branch",
        },
        "review_handoff": {
            "plan_review": "Plan looks good.",
            "code_review": None,
            "verification_summary": "All checks passed.",
            "qa": None,
            "pr_draft": None,
            "active_issues": None,
        },
        "pr_handoff": {
            "summary": "- Verification summary available",
            "validation": "All checks passed.",
            "risks_follow_up": "- [not recorded]",
        },
    }

    is_valid, errors = MODULE.validate_artifact(bundle, MODULE.REVIEW_BUNDLE_SCHEMA)
    assert is_valid, f"Errors: {errors}"


def test_validate_review_bundle_schema_with_manifest_status_ready():
    """manifest_status.status=ready with path field validates."""
    minimal = {
        "status": "success",
        "branch": "test-branch",
        "bundle_path_json": ".map/test-branch/review-bundle.json",
        "bundle_path_md": ".map/test-branch/review-bundle.md",
        "generated_at": "2026-05-11T12:00:00Z",
        "artifacts": {
            "spec": {"present": False, "path": None, "sanitized_text": None},
            "task_plan": {"present": False, "path": None, "sanitized_text": None},
            "blueprint": {"present": False, "path": None, "sanitized_text": None},
            "verification_summary": {"present": False, "path": None, "sanitized_text": None},
            "qa": {"present": False, "path": None, "sanitized_text": None},
            "pr_draft": {"present": False, "path": None, "sanitized_text": None},
            "active_issues": {"present": False, "path": None, "sanitized_text": None},
            "artifact_manifest": {"present": False, "path": None, "sanitized_text": None},
            "latest_plan_review": {"present": False, "path": None, "sanitized_text": None},
            "latest_code_review": {"present": False, "path": None, "sanitized_text": None},
            "test_handoffs": [],
            "test_contracts": [],
        },
        "code_state": {"status": "unavailable"},
        "review_handoff": {
            "plan_review": None,
            "code_review": None,
            "verification_summary": None,
            "qa": None,
            "pr_draft": None,
            "active_issues": None,
        },
        "pr_handoff": {
            "summary": "- [not recorded]",
            "validation": "- [not recorded]",
            "risks_follow_up": "- [not recorded]",
        },
        "manifest_status": {"status": "ready", "path": ".map/test-branch/artifact_manifest.json"},
    }
    is_valid, errors = MODULE.validate_artifact(minimal, MODULE.REVIEW_BUNDLE_SCHEMA)
    assert is_valid, f"Errors: {errors}"


def test_validate_review_bundle_schema_with_manifest_status_error():
    """manifest_status.status=error with reason field validates."""
    minimal = {
        "status": "success",
        "branch": "test-branch",
        "bundle_path_json": ".map/test-branch/review-bundle.json",
        "bundle_path_md": ".map/test-branch/review-bundle.md",
        "generated_at": "2026-05-11T12:00:00Z",
        "artifacts": {
            "spec": {"present": False, "path": None, "sanitized_text": None},
            "task_plan": {"present": False, "path": None, "sanitized_text": None},
            "blueprint": {"present": False, "path": None, "sanitized_text": None},
            "verification_summary": {"present": False, "path": None, "sanitized_text": None},
            "qa": {"present": False, "path": None, "sanitized_text": None},
            "pr_draft": {"present": False, "path": None, "sanitized_text": None},
            "active_issues": {"present": False, "path": None, "sanitized_text": None},
            "artifact_manifest": {"present": False, "path": None, "sanitized_text": None},
            "latest_plan_review": {"present": False, "path": None, "sanitized_text": None},
            "latest_code_review": {"present": False, "path": None, "sanitized_text": None},
            "test_handoffs": [],
            "test_contracts": [],
        },
        "code_state": {"status": "unavailable"},
        "review_handoff": {
            "plan_review": None,
            "code_review": None,
            "verification_summary": None,
            "qa": None,
            "pr_draft": None,
            "active_issues": None,
        },
        "pr_handoff": {
            "summary": "- [not recorded]",
            "validation": "- [not recorded]",
            "risks_follow_up": "- [not recorded]",
        },
        "manifest_status": {"status": "error", "reason": "disk full"},
    }
    is_valid, errors = MODULE.validate_artifact(minimal, MODULE.REVIEW_BUNDLE_SCHEMA)
    assert is_valid, f"Errors: {errors}"
