"""Focused tests for new artifact schemas without importing package extras."""

import importlib.util
from pathlib import Path


SCHEMAS_PATH = Path(__file__).resolve().parents[1] / "src" / "mapify_cli" / "schemas.py"
SPEC = importlib.util.spec_from_file_location("artifact_schemas", SCHEMAS_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
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
            "learn_handoff": stage,
        },
    }

    is_valid, errors = MODULE.validate_artifact(artifact, MODULE.ARTIFACT_MANIFEST_SCHEMA)
    assert is_valid, f"Errors: {errors}"


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
