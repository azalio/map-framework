"""Tests for verification_recorder module.

Test coverage:
1. File creation with overall='unknown'
2. Append logic preserving existing entries
3. Overall status aggregation rules (pass/fail/unknown)
4. Schema validation before writing
5. Concurrent write safety (atomic write pattern)
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from mapify_cli.verification_recorder import (
    _atomic_write_json,
    _compute_overall_status,
    _validate_verification_results_schema,
    record_verification_result,
)


@pytest.fixture
def temp_project_root(tmp_path):
    """Create a temporary project root directory."""
    project_root = tmp_path / "test_project"
    project_root.mkdir()
    return project_root


# ============================================================================
# Test: File creation
# ============================================================================


def test_record_creates_file_if_missing(temp_project_root):
    """Test that record_verification_result creates file with overall='unknown'."""
    result_path = record_verification_result(
        temp_project_root,
        branch="main",
        recipe_id="lint",
        status="pass",
        summary="All linting checks passed",
        duration_ms=1200,
    )

    # Verify file was created
    assert result_path.exists()
    assert result_path.name == "verification_results_main.json"

    # Verify file is in .map/ directory
    assert result_path.parent.name == ".map"

    # Verify content structure
    with result_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    assert "overall" in data
    assert "recipes" in data
    assert len(data["recipes"]) == 1
    assert data["recipes"][0]["id"] == "lint"


def test_record_creates_map_directory_if_missing(temp_project_root):
    """Test that .map/ directory is created if it doesn't exist."""
    map_dir = temp_project_root / ".map"
    assert not map_dir.exists()

    record_verification_result(
        temp_project_root,
        branch="main",
        recipe_id="test",
        status="pass",
        summary="Tests passed",
    )

    assert map_dir.exists()
    assert map_dir.is_dir()


# ============================================================================
# Test: Append logic
# ============================================================================


def test_record_appends_to_existing_recipes(temp_project_root):
    """Test that new recipes are appended, preserving existing entries."""
    # First recipe
    record_verification_result(
        temp_project_root,
        branch="feat-123",
        recipe_id="lint",
        status="pass",
        summary="Linting passed",
    )

    # Second recipe
    record_verification_result(
        temp_project_root,
        branch="feat-123",
        recipe_id="test",
        status="pass",
        summary="Tests passed",
    )

    # Third recipe
    result_path = record_verification_result(
        temp_project_root,
        branch="feat-123",
        recipe_id="type-check",
        status="skipped",
        summary="Type checking skipped: mypy not installed",
    )

    # Verify all recipes are present
    with result_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    assert len(data["recipes"]) == 3
    assert data["recipes"][0]["id"] == "lint"
    assert data["recipes"][1]["id"] == "test"
    assert data["recipes"][2]["id"] == "type-check"


def test_record_handles_multiple_branches(temp_project_root):
    """Test that different branches have separate results files."""
    # Record for main branch
    main_path = record_verification_result(
        temp_project_root,
        branch="main",
        recipe_id="lint",
        status="pass",
        summary="Main branch lint",
    )

    # Record for feature branch
    feat_path = record_verification_result(
        temp_project_root,
        branch="feat-auth",
        recipe_id="lint",
        status="fail",
        summary="Feature branch lint failed",
    )

    # Verify separate files
    assert main_path != feat_path
    assert main_path.name == "verification_results_main.json"
    assert feat_path.name == "verification_results_feat-auth.json"

    # Verify independent content
    with main_path.open("r", encoding="utf-8") as f:
        main_data = json.load(f)
    with feat_path.open("r", encoding="utf-8") as f:
        feat_data = json.load(f)

    assert main_data["overall"] == "pass"
    assert feat_data["overall"] == "fail"


# ============================================================================
# Test: Overall status aggregation (CONTRACT ENFORCEMENT)
# ============================================================================


def test_overall_fail_when_any_recipe_fails(temp_project_root):
    """Test contract: overall='fail' when ANY recipe status is 'fail'."""
    # Add passing recipe
    record_verification_result(
        temp_project_root,
        branch="main",
        recipe_id="lint",
        status="pass",
        summary="Lint passed",
    )

    # Add failing recipe
    result_path = record_verification_result(
        temp_project_root,
        branch="main",
        recipe_id="test",
        status="fail",
        summary="Tests failed",
    )

    with result_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    # Contract: ANY fail → overall fail
    assert data["overall"] == "fail"


def test_overall_pass_when_all_recipes_pass(temp_project_root):
    """Test contract: overall='pass' when ALL recipes are 'pass'."""
    # Add multiple passing recipes
    record_verification_result(
        temp_project_root,
        branch="main",
        recipe_id="lint",
        status="pass",
        summary="Lint passed",
    )
    record_verification_result(
        temp_project_root,
        branch="main",
        recipe_id="test",
        status="pass",
        summary="Tests passed",
    )
    result_path = record_verification_result(
        temp_project_root,
        branch="main",
        recipe_id="type-check",
        status="pass",
        summary="Type checking passed",
    )

    with result_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    # Contract: ALL pass → overall pass
    assert data["overall"] == "pass"


def test_overall_unknown_for_mixed_pass_skipped(temp_project_root):
    """Test that overall='unknown' for mixed pass/skipped recipes."""
    record_verification_result(
        temp_project_root,
        branch="main",
        recipe_id="lint",
        status="pass",
        summary="Lint passed",
    )
    result_path = record_verification_result(
        temp_project_root,
        branch="main",
        recipe_id="test",
        status="skipped",
        summary="Tests skipped",
    )

    with result_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    # Mixed pass/skipped → unknown
    assert data["overall"] == "unknown"


def test_overall_unknown_for_all_skipped(temp_project_root):
    """Test that overall='unknown' when all recipes are skipped."""
    result_path = record_verification_result(
        temp_project_root,
        branch="main",
        recipe_id="lint",
        status="skipped",
        summary="Lint skipped",
    )

    with result_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["overall"] == "unknown"


def test_compute_overall_status_empty_recipes():
    """Test _compute_overall_status with empty recipe list."""
    assert _compute_overall_status([]) == "unknown"


def test_compute_overall_status_fail_dominates():
    """Test that 'fail' dominates even with pass and skipped."""
    recipes = [
        {"status": "pass"},
        {"status": "skipped"},
        {"status": "fail"},
        {"status": "pass"},
    ]
    assert _compute_overall_status(recipes) == "fail"  # pyright: ignore[reportArgumentType]  # intentional partial dict for status-logic test


def test_compute_overall_status_all_pass():
    """Test that all pass results in 'pass'."""
    recipes = [
        {"status": "pass"},
        {"status": "pass"},
        {"status": "pass"},
    ]
    assert _compute_overall_status(recipes) == "pass"  # pyright: ignore[reportArgumentType]  # intentional partial dict for status-logic test


def test_compute_overall_status_no_fail_with_skipped():
    """Test that no fail + some skipped results in 'unknown'."""
    recipes = [
        {"status": "pass"},
        {"status": "skipped"},
    ]
    assert _compute_overall_status(recipes) == "unknown"  # pyright: ignore[reportArgumentType]  # intentional partial dict for status-logic test


# ============================================================================
# Test: Schema validation
# ============================================================================


def test_record_validates_schema_before_writing(temp_project_root):
    """Test that schema validation catches invalid data."""
    # Invalid status should raise ValueError
    with pytest.raises(ValueError, match="Invalid status"):
        record_verification_result(
            temp_project_root,
            branch="main",
            recipe_id="lint",
            status="invalid_status",  # Invalid
            summary="Test",
        )


def test_validate_schema_missing_overall():
    """Test validation catches missing overall field."""
    data = {"recipes": []}
    with pytest.raises(ValueError, match="Missing required field: overall"):
        _validate_verification_results_schema(data)  # pyright: ignore[reportArgumentType]  # intentional invalid input for validation test


def test_validate_schema_missing_recipes():
    """Test validation catches missing recipes field."""
    data = {"overall": "pass"}
    with pytest.raises(ValueError, match="Missing required field: recipes"):
        _validate_verification_results_schema(data)  # pyright: ignore[reportArgumentType]  # intentional invalid input for validation test


def test_validate_schema_invalid_overall():
    """Test validation catches invalid overall status."""
    data = {"overall": "invalid", "recipes": []}
    with pytest.raises(ValueError, match="Invalid overall status"):
        _validate_verification_results_schema(data)  # pyright: ignore[reportArgumentType]  # intentional invalid input for validation test


def test_validate_schema_recipes_not_list():
    """Test validation catches recipes that is not a list."""
    data = {"overall": "pass", "recipes": "not a list"}
    with pytest.raises(ValueError, match="recipes must be a list"):
        _validate_verification_results_schema(data)  # pyright: ignore[reportArgumentType]  # intentional invalid input for validation test


def test_validate_schema_recipe_missing_field():
    """Test validation catches recipe missing required field."""
    data = {
        "overall": "pass",
        "recipes": [{"id": "lint", "status": "pass"}],  # Missing summary
    }
    with pytest.raises(ValueError, match="missing required field: summary"):
        _validate_verification_results_schema(data)  # pyright: ignore[reportArgumentType]  # intentional invalid input for validation test


def test_validate_schema_invalid_recipe_status():
    """Test validation catches invalid recipe status."""
    data = {
        "overall": "pass",
        "recipes": [{"id": "lint", "status": "invalid", "summary": "Test"}],
    }
    with pytest.raises(ValueError, match="invalid status"):
        _validate_verification_results_schema(data)  # pyright: ignore[reportArgumentType]  # intentional invalid input for validation test


def test_validate_schema_negative_duration():
    """Test validation catches negative duration_ms."""
    data = {
        "overall": "pass",
        "recipes": [
            {"id": "lint", "status": "pass", "summary": "Test", "duration_ms": -100}
        ],
    }
    with pytest.raises(ValueError, match="duration_ms must be >= 0"):
        _validate_verification_results_schema(data)  # pyright: ignore[reportArgumentType]  # intentional invalid input for validation test


def test_validate_schema_valid_data():
    """Test validation passes for valid data."""
    data = {
        "overall": "pass",
        "recipes": [
            {
                "id": "lint",
                "status": "pass",
                "summary": "All checks passed",
                "duration_ms": 1200,
            }
        ],
    }
    # Should not raise
    _validate_verification_results_schema(data)  # pyright: ignore[reportArgumentType]  # intentional partial dict for schema test


# ============================================================================
# Test: Optional fields
# ============================================================================


def test_record_with_duration_ms(temp_project_root):
    """Test recording with duration_ms field."""
    result_path = record_verification_result(
        temp_project_root,
        branch="main",
        recipe_id="test",
        status="pass",
        summary="Tests passed",
        duration_ms=3456,
    )

    with result_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["recipes"][0]["duration_ms"] == 3456


def test_record_with_skip_reason(temp_project_root):
    """Test recording with skip_reason field."""
    result_path = record_verification_result(
        temp_project_root,
        branch="main",
        recipe_id="type-check",
        status="skipped",
        summary="Type checking skipped",
        skip_reason="mypy not installed",
    )

    with result_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["recipes"][0]["skip_reason"] == "mypy not installed"


def test_record_without_optional_fields(temp_project_root):
    """Test recording without optional fields."""
    result_path = record_verification_result(
        temp_project_root,
        branch="main",
        recipe_id="lint",
        status="pass",
        summary="Lint passed",
    )

    with result_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    recipe = data["recipes"][0]
    assert "duration_ms" not in recipe
    assert "skip_reason" not in recipe


def test_record_with_null_duration(temp_project_root):
    """Test recording with explicit None duration_ms."""
    result_path = record_verification_result(
        temp_project_root,
        branch="main",
        recipe_id="lint",
        status="pass",
        summary="Lint passed",
        duration_ms=None,
    )

    with result_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    # None duration_ms should not be included
    recipe = data["recipes"][0]
    assert "duration_ms" not in recipe


# ============================================================================
# Test: Error handling
# ============================================================================


def test_record_negative_duration_raises(temp_project_root):
    """Test that negative duration_ms raises ValueError."""
    with pytest.raises(ValueError, match="duration_ms must be >= 0"):
        record_verification_result(
            temp_project_root,
            branch="main",
            recipe_id="test",
            status="pass",
            summary="Test",
            duration_ms=-100,
        )


def test_record_handles_corrupted_json(temp_project_root):
    """Test that corrupted JSON file is recreated."""
    # Create corrupted JSON file
    map_dir = temp_project_root / ".map"
    map_dir.mkdir()
    results_path = map_dir / "verification_results_main.json"
    results_path.write_text("{ corrupted json", encoding="utf-8")

    # Should recreate file instead of crashing
    result_path = record_verification_result(
        temp_project_root,
        branch="main",
        recipe_id="lint",
        status="pass",
        summary="Lint passed",
    )

    # Verify file is valid JSON now
    with result_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["overall"] == "pass"
    assert len(data["recipes"]) == 1


# ============================================================================
# Test: Atomic write safety
# ============================================================================


def test_atomic_write_creates_temp_file(temp_project_root):
    """Test that atomic write uses temp file pattern."""
    target_path = temp_project_root / "test.json"
    data = {"test": "data"}

    # Create a real temp file first (before patching)
    real_fd, real_path = tempfile.mkstemp(dir=temp_project_root)

    with patch("tempfile.mkstemp") as mock_mkstemp:
        mock_mkstemp.return_value = (real_fd, real_path)

        _atomic_write_json(target_path, data)  # pyright: ignore[reportArgumentType]  # intentional partial dict for atomic-write test

        # Verify mkstemp was called with correct directory
        mock_mkstemp.assert_called_once()
        call_kwargs = mock_mkstemp.call_args[1]
        assert call_kwargs["dir"] == target_path.parent


def test_atomic_write_cleans_up_on_error(temp_project_root):
    """Test that temp file is cleaned up if write fails."""
    target_path = temp_project_root / "test.json"
    data = {"test": "data"}

    # Create a real temp file to track cleanup
    temp_fd, temp_path = tempfile.mkstemp(dir=temp_project_root)

    with patch("tempfile.mkstemp") as mock_mkstemp:
        mock_mkstemp.return_value = (temp_fd, temp_path)

        # Force an error during write (os.fdopen is used now, not open)
        with patch("os.fdopen", side_effect=OSError("Write failed")), pytest.raises(OSError, match="Write failed"):
            _atomic_write_json(target_path, data)  # pyright: ignore[reportArgumentType]  # intentional partial dict for atomic-write test

        # Verify temp file was cleaned up
        assert not Path(temp_path).exists()


def test_atomic_write_successful_rename(temp_project_root):
    """Test that atomic write renames temp file to target."""
    target_path = temp_project_root / "test.json"
    data = {"test": "data", "value": 123}

    _atomic_write_json(target_path, data)  # pyright: ignore[reportArgumentType]  # intentional partial dict for atomic-write test

    # Verify target file exists and has correct content
    assert target_path.exists()
    with target_path.open("r", encoding="utf-8") as f:
        loaded_data = json.load(f)
    assert loaded_data == data


# ============================================================================
# Test: Concurrent writes (integration test)
# ============================================================================


def test_concurrent_writes_preserve_all_recipes(temp_project_root):
    """Test that concurrent writes don't corrupt data (simulated)."""
    # Simulate concurrent writes by rapidly recording multiple recipes
    # The atomic write pattern should prevent corruption

    recipes_to_add = [
        ("lint", "pass", "Lint passed"),
        ("test", "pass", "Tests passed"),
        ("type-check", "skipped", "Type check skipped"),
        ("security", "fail", "Security issues found"),
    ]

    for recipe_id, status, summary in recipes_to_add:
        record_verification_result(
            temp_project_root,
            branch="main",
            recipe_id=recipe_id,
            status=status,
            summary=summary,
        )

    # Verify all recipes are present and file is valid JSON
    results_path = temp_project_root / ".map" / "verification_results_main.json"
    with results_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    assert len(data["recipes"]) == 4
    assert data["overall"] == "fail"  # Because security failed

    # Verify recipe order is preserved
    assert data["recipes"][0]["id"] == "lint"
    assert data["recipes"][1]["id"] == "test"
    assert data["recipes"][2]["id"] == "type-check"
    assert data["recipes"][3]["id"] == "security"
