"""Verification results recorder for MAP Framework.

Records verification results to .map/verification_results_<sanitized_branch>.json
with atomic writes to prevent concurrent write corruption.
"""

import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import TypedDict, cast

# Maximum number of recipes to retain (older entries are trimmed)
MAX_RECIPES = 1000


class RecipeResult(TypedDict, total=False):
    """Type definition for a verification recipe result."""

    id: str  # Required
    status: str  # Required: 'pass', 'fail', or 'skipped'
    summary: str  # Required
    duration_ms: int  # Optional
    skip_reason: str  # Optional


class VerificationResults(TypedDict):
    """Type definition for verification results file."""

    overall: str  # 'pass', 'fail', or 'unknown'
    recipes: list[RecipeResult]


def _sanitize_branch_name(branch: str) -> str:
    """Sanitize branch name for use in filenames.

    Replaces characters that could cause path issues with dashes,
    consistent with MAP framework branch sanitization elsewhere.

    Args:
        branch: Git branch name (e.g., 'feature/foo', 'main')

    Returns:
        Sanitized branch name safe for filenames (e.g., 'feature-foo', 'main')
    """
    sanitized = branch.replace("/", "-")
    sanitized = re.sub(r"[^a-zA-Z0-9_.-]", "-", sanitized)
    sanitized = re.sub(r"-+", "-", sanitized).strip("-")
    if ".." in sanitized or sanitized.startswith("."):
        return "default"
    return sanitized or "default"


def _log_warning(message: str) -> None:
    """Log a warning message to stderr.

    Args:
        message: Warning message to log
    """
    print(f"[verification_recorder] WARNING: {message}", file=sys.stderr)


def record_verification_result(
    project_root: Path,
    branch: str,
    recipe_id: str,
    status: str,
    summary: str,
    duration_ms: int | None = None,
    skip_reason: str | None = None,
) -> Path:
    """Record a verification recipe result to branch-specific results file.

    Appends recipe result to .map/verification_results_<branch>.json and updates
    overall verification status. Creates file if it doesn't exist.

    Overall status aggregation rules (CONTRACT):
    - overall = 'fail' WHEN ANY recipe.status == 'fail'
    - overall = 'pass' WHEN ALL recipe.status == 'pass'
    - overall = 'unknown' otherwise (pending, mixed pass/skipped, or no recipes)

    Uses atomic write pattern (write to .tmp, rename) to prevent concurrent
    write corruption. Limits recipes to MAX_RECIPES entries (oldest trimmed).

    Args:
        project_root: Path to project root directory
        branch: Git branch name for filename
        recipe_id: Unique identifier for this verification recipe
        status: Recipe status ('pass', 'fail', or 'skipped')
        summary: Human-readable summary of verification result
        duration_ms: Duration of check in milliseconds (optional)
        skip_reason: Reason for skipping (only for status='skipped')

    Returns:
        Path to the results JSON file

    Raises:
        ValueError: If status is invalid or data doesn't match schema
        OSError: If file cannot be written
    """
    # Validate status
    valid_statuses = {"pass", "fail", "skipped"}
    if status not in valid_statuses:
        raise ValueError(f"Invalid status '{status}'. Must be one of: {valid_statuses}")

    # Build recipe object with proper typing
    recipe: RecipeResult = {
        "id": recipe_id,
        "status": status,
        "summary": summary,
    }

    # Add optional fields
    if duration_ms is not None:
        if duration_ms < 0:
            raise ValueError(f"duration_ms must be >= 0, got {duration_ms}")
        recipe["duration_ms"] = duration_ms

    if skip_reason is not None:
        recipe["skip_reason"] = skip_reason

    # Ensure .map/ directory exists
    map_dir = project_root / ".map"
    map_dir.mkdir(exist_ok=True)

    # Sanitize branch name to avoid nested paths (e.g., feature/foo -> feature_foo)
    safe_branch = _sanitize_branch_name(branch)
    results_path = map_dir / f"verification_results_{safe_branch}.json"

    # Load existing results or create new structure
    results_data: VerificationResults
    if results_path.exists():
        try:
            with results_path.open("r", encoding="utf-8") as f:
                results_data = json.load(f)
        except json.JSONDecodeError as e:
            # Log warning about corruption, start fresh
            _log_warning(
                f"Corrupted JSON in {results_path}, starting fresh. Error: {e}"
            )
            results_data = {"overall": "unknown", "recipes": []}
        except OSError as e:
            # Log warning about read error, start fresh
            _log_warning(f"Could not read {results_path}, starting fresh. Error: {e}")
            results_data = {"overall": "unknown", "recipes": []}
    else:
        # Create new results file
        results_data = {"overall": "unknown", "recipes": []}

    # Append new recipe result (preserving existing entries)
    results_data["recipes"].append(recipe)

    # Trim old recipes if exceeding limit (keep most recent)
    if len(results_data["recipes"]) > MAX_RECIPES:
        trimmed_count = len(results_data["recipes"]) - MAX_RECIPES
        results_data["recipes"] = results_data["recipes"][-MAX_RECIPES:]
        _log_warning(
            f"Trimmed {trimmed_count} old recipes to stay under {MAX_RECIPES} limit"
        )

    # Update overall status based on aggregation rules
    results_data["overall"] = _compute_overall_status(results_data["recipes"])

    # Validate schema before writing
    _validate_verification_results_schema(results_data)

    # Atomic write: write to temp file, then rename
    _atomic_write_json(results_path, results_data)

    return results_path


def _compute_overall_status(recipes: list[RecipeResult]) -> str:
    """Compute overall verification status from recipe list.

    Contract enforcement:
    - Returns 'fail' if ANY recipe status is 'fail'
    - Returns 'pass' if ALL recipe statuses are 'pass'
    - Returns 'unknown' otherwise (empty, mixed pass/skipped, etc.)

    Args:
        recipes: List of recipe dictionaries with 'status' field

    Returns:
        Overall status ('pass', 'fail', or 'unknown')
    """
    if not recipes:
        return "unknown"

    statuses = [recipe.get("status") for recipe in recipes]

    # Contract: ANY fail → overall fail
    if "fail" in statuses:
        return "fail"

    # Contract: ALL pass → overall pass
    if all(status == "pass" for status in statuses):
        return "pass"

    # Otherwise: unknown (mixed pass/skipped, all skipped, etc.)
    return "unknown"


def _validate_verification_results_schema(data: VerificationResults) -> None:
    """Validate data against VERIFICATION_RESULTS_SCHEMA.

    Args:
        data: Dictionary to validate

    Raises:
        ValueError: If data doesn't match schema
    """
    # Check required fields
    if "overall" not in data:
        raise ValueError("Missing required field: overall")
    if "recipes" not in data:
        raise ValueError("Missing required field: recipes")

    # Validate overall status
    valid_overall = {"pass", "fail", "unknown"}
    if data["overall"] not in valid_overall:
        raise ValueError(
            f"Invalid overall status '{data['overall']}'. Must be one of: {valid_overall}"
        )

    # Validate recipes is a list
    if not isinstance(data["recipes"], list):
        raise ValueError("recipes must be a list")

    # Validate each recipe
    for idx, recipe in enumerate(data["recipes"]):
        if not isinstance(recipe, dict):
            raise ValueError(f"Recipe {idx} must be a dictionary")

        typed_recipe = cast(RecipeResult, recipe)

        # Check required fields in recipe
        required_fields = ["id", "status", "summary"]
        for field in required_fields:
            if field not in typed_recipe:
                raise ValueError(f"Recipe {idx} missing required field: {field}")

        # Validate recipe status (presence already checked above via required_fields loop)
        valid_statuses = {"pass", "fail", "skipped"}
        recipe_status = typed_recipe.get("status", "")
        if recipe_status not in valid_statuses:
            raise ValueError(
                f"Recipe {idx} has invalid status '{recipe_status}'. "
                f"Must be one of: {valid_statuses}"
            )

        # Validate duration_ms if present
        if "duration_ms" in recipe:
            duration = recipe["duration_ms"]
            if duration is not None:
                if not isinstance(duration, (int, float)):
                    raise ValueError(
                        f"Recipe {idx} duration_ms must be a number, got {type(duration).__name__}"
                    )
                if duration < 0:
                    raise ValueError(
                        f"Recipe {idx} duration_ms must be >= 0, got {duration}"
                    )


def _atomic_write_json(file_path: Path, data: VerificationResults) -> None:
    """Write JSON data to file atomically using temp file + rename pattern.

    Prevents concurrent write corruption by writing to a temporary file first,
    then atomically renaming it to the target path. Uses os.fdopen to avoid
    race conditions between close and reopen.

    Args:
        file_path: Target file path
        data: Dictionary to write as JSON

    Raises:
        OSError: If file cannot be written
    """
    # Create temp file in same directory as target (ensures same filesystem)
    # This is critical for atomic rename operation
    temp_fd, temp_path = tempfile.mkstemp(
        dir=file_path.parent, prefix=f".{file_path.name}.", suffix=".tmp"
    )

    try:
        # Use os.fdopen to wrap the file descriptor directly
        # This avoids the race condition of close + reopen by path
        with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        # Atomic rename (overwrites target on same filesystem)
        Path(temp_path).replace(file_path)
    except Exception:
        # Clean up temp file on error
        try:
            Path(temp_path).unlink(missing_ok=True)
        except Exception:  # noqa: BLE001, S110 -- deliberate fallback/resilience boundary, must not propagate
            pass  # Best-effort cleanup
        raise


# =============================================================================
# CLI Entry Point
# =============================================================================


def main() -> int:
    """CLI entry point for verification recorder.

    Usage:
        python -m mapify_cli.verification_recorder <branch> <recipe_id> <status> <summary> [duration_ms]

    Args (positional):
        branch: Git branch name
        recipe_id: Verification recipe identifier
        status: Recipe status (pass|fail|skipped)
        summary: Human-readable summary
        duration_ms: Optional duration in milliseconds

    Returns:
        Exit code (0 = success, 1 = error)
    """
    if len(sys.argv) < 5:
        print(
            "Usage: python -m mapify_cli.verification_recorder <branch> <recipe_id> <status> <summary> [duration_ms]",
            file=sys.stderr,
        )
        return 1

    branch = sys.argv[1]
    recipe_id = sys.argv[2]
    status = sys.argv[3]
    summary = sys.argv[4]

    # Parse optional duration_ms with validation
    duration_ms: int | None = None
    if len(sys.argv) > 5:
        try:
            duration_ms = int(sys.argv[5])
        except ValueError:
            print(
                f"Error: duration_ms must be an integer, got '{sys.argv[5]}'",
                file=sys.stderr,
            )
            return 1

    try:
        # Project root is current working directory
        project_root = Path.cwd()

        # Record verification result
        record_verification_result(
            project_root=project_root,
            branch=branch,
            recipe_id=recipe_id,
            status=status,
            summary=summary,
            duration_ms=duration_ms,
        )

        # Success (silent on success for hook integration)
        return 0

    except Exception as e:  # noqa: BLE001 -- deliberate fallback/resilience boundary, must not propagate
        print(f"Error recording verification result: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
