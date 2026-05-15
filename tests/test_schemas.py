"""Tests for REVIEW_BUNDLE_SCHEMA ordering field extension (ST-004)."""

import importlib.util
from pathlib import Path

import pytest

pytest.importorskip(
    "jsonschema",
    reason="jsonschema required for type/enum/additionalProperties validation; "
    "validate_artifact falls back to required-field checking otherwise.",
)


SCHEMAS_PATH = Path(__file__).resolve().parents[1] / "src" / "mapify_cli" / "schemas.py"
SPEC = importlib.util.spec_from_file_location("artifact_schemas", SCHEMAS_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _minimal_valid_bundle() -> dict:  # type: ignore[type-arg]
    """Return a legacy-style bundle with all required top-level fields and no ordering."""
    artifact_absent = {"present": False, "path": None, "sanitized_text": None}
    return {
        "status": "success",
        "branch": "test-branch",
        "bundle_path_json": ".map/test-branch/review-bundle.json",
        "bundle_path_md": ".map/test-branch/review-bundle.md",
        "generated_at": "2026-05-13T10:00:00Z",
        "artifacts": {
            "spec": artifact_absent,
            "task_plan": artifact_absent,
            "blueprint": artifact_absent,
            "verification_summary": artifact_absent,
            "qa": artifact_absent,
            "pr_draft": artifact_absent,
            "active_issues": artifact_absent,
            "artifact_manifest": artifact_absent,
            "latest_plan_review": artifact_absent,
            "latest_code_review": artifact_absent,
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
    }


def _complete_ordering(mode: str = "default") -> dict:  # type: ignore[type-arg]
    """Return a complete ordering object with all 7 required fields."""
    return {
        "mode": mode,
        "seed": 42,
        "runs": [],
        "drift_detected": False,
        "drift_summary": None,
        "final_verdict": None,
        "compare_status": None,
    }


# ---------------------------------------------------------------------------
# AC-8a: bundle WITH ordering validates
# ---------------------------------------------------------------------------


def test_review_bundle_schema_accepts_ordering() -> None:
    """AC-8a: bundle with complete ordering object validates."""
    bundle = _minimal_valid_bundle()
    bundle["ordering"] = _complete_ordering("default")

    is_valid, errors = MODULE.validate_artifact(bundle, MODULE.REVIEW_BUNDLE_SCHEMA)
    assert is_valid, f"Errors: {errors}"


def test_review_bundle_schema_accepts_compare_orderings_mode() -> None:
    """AC-8a: fourth enum value 'compare-orderings' is accepted."""
    bundle = _minimal_valid_bundle()
    bundle["ordering"] = _complete_ordering("compare-orderings")

    is_valid, errors = MODULE.validate_artifact(bundle, MODULE.REVIEW_BUNDLE_SCHEMA)
    assert is_valid, f"Errors: {errors}"


def test_review_bundle_schema_accepts_ordering_with_runs_populated() -> None:
    """AC-8a: ordering with non-empty runs list validates."""
    bundle = _minimal_valid_bundle()
    bundle["ordering"] = {
        "mode": "shuffle-sections",
        "seed": 7,
        "runs": [{"verdict": "PROCEED", "issues": []}],
        "drift_detected": False,
        "drift_summary": None,
        "final_verdict": "PROCEED",
        "compare_status": "complete",
    }

    is_valid, errors = MODULE.validate_artifact(bundle, MODULE.REVIEW_BUNDLE_SCHEMA)
    assert is_valid, f"Errors: {errors}"


def test_review_bundle_schema_accepts_ordering_seed_null() -> None:
    """Seed may be null (default mode without explicit seed)."""
    bundle = _minimal_valid_bundle()
    bundle["ordering"] = {
        "mode": "reverse-sections",
        "seed": None,
        "runs": [],
        "drift_detected": False,
        "drift_summary": None,
        "final_verdict": None,
        "compare_status": None,
    }

    is_valid, errors = MODULE.validate_artifact(bundle, MODULE.REVIEW_BUNDLE_SCHEMA)
    assert is_valid, f"Errors: {errors}"


# ---------------------------------------------------------------------------
# INV-2: legacy bundle WITHOUT ordering validates
# ---------------------------------------------------------------------------


def test_review_bundle_schema_accepts_no_ordering() -> None:
    """INV-2: legacy bundle without ordering key validates (backward compat)."""
    bundle = _minimal_valid_bundle()
    assert "ordering" not in bundle

    is_valid, errors = MODULE.validate_artifact(bundle, MODULE.REVIEW_BUNDLE_SCHEMA)
    assert is_valid, f"Errors: {errors}"


# ---------------------------------------------------------------------------
# EC-9: mode outside enum is rejected
# ---------------------------------------------------------------------------


def test_review_bundle_schema_rejects_invalid_mode() -> None:
    """EC-9: ordering.mode value outside enum is rejected."""
    bundle = _minimal_valid_bundle()
    bundle["ordering"] = {**_complete_ordering(), "mode": "xyz"}

    is_valid = MODULE.validate_artifact(bundle, MODULE.REVIEW_BUNDLE_SCHEMA)[0]
    assert not is_valid


# ---------------------------------------------------------------------------
# Seed type validation
# ---------------------------------------------------------------------------


def test_review_bundle_schema_rejects_invalid_seed_float() -> None:
    """ordering.seed must be integer or null; float is rejected."""
    bundle = _minimal_valid_bundle()
    bundle["ordering"] = {**_complete_ordering(), "seed": 3.14}

    is_valid = MODULE.validate_artifact(bundle, MODULE.REVIEW_BUNDLE_SCHEMA)[0]
    assert not is_valid


def test_review_bundle_schema_rejects_invalid_seed_string() -> None:
    """ordering.seed must be integer or null; string is rejected."""
    bundle = _minimal_valid_bundle()
    bundle["ordering"] = {**_complete_ordering(), "seed": "42"}

    is_valid = MODULE.validate_artifact(bundle, MODULE.REVIEW_BUNDLE_SCHEMA)[0]
    assert not is_valid


# ---------------------------------------------------------------------------
# Runs type validation
# ---------------------------------------------------------------------------


def test_review_bundle_schema_rejects_non_list_runs() -> None:
    """ordering.runs must be an array; dict is rejected."""
    bundle = _minimal_valid_bundle()
    bundle["ordering"] = {**_complete_ordering(), "runs": {"verdict": "PROCEED"}}

    is_valid = MODULE.validate_artifact(bundle, MODULE.REVIEW_BUNDLE_SCHEMA)[0]
    assert not is_valid


# ---------------------------------------------------------------------------
# drift_detected type validation
# ---------------------------------------------------------------------------


def test_review_bundle_schema_rejects_invalid_drift_detected_type() -> None:
    """ordering.drift_detected must be boolean; string 'true' is rejected."""
    bundle = _minimal_valid_bundle()
    bundle["ordering"] = {**_complete_ordering(), "drift_detected": "true"}

    is_valid = MODULE.validate_artifact(bundle, MODULE.REVIEW_BUNDLE_SCHEMA)[0]
    assert not is_valid


# ---------------------------------------------------------------------------
# Partial ordering (missing required inner fields) is rejected
# ---------------------------------------------------------------------------


def test_review_bundle_schema_rejects_partial_ordering() -> None:
    """ordering present but missing required fields is rejected."""
    bundle = _minimal_valid_bundle()
    bundle["ordering"] = {"mode": "default"}

    is_valid = MODULE.validate_artifact(bundle, MODULE.REVIEW_BUNDLE_SCHEMA)[0]
    assert not is_valid


# ---------------------------------------------------------------------------
# additionalProperties enforcement inside ordering
# ---------------------------------------------------------------------------


def test_review_bundle_schema_rejects_additional_properties_in_ordering() -> None:
    """Extra key inside ordering object is rejected (additionalProperties: false)."""
    bundle = _minimal_valid_bundle()
    bundle["ordering"] = {**_complete_ordering(), "unexpected_field": "oops"}

    is_valid = MODULE.validate_artifact(bundle, MODULE.REVIEW_BUNDLE_SCHEMA)[0]
    assert not is_valid
