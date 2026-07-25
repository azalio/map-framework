"""Repository insight generation for MAP Framework.

Analyzes project structure to provide language detection, suggested checks,
and key directories for workflow initialization.
"""

import json
import subprocess
from pathlib import Path


def detect_language(project_root: Path) -> str:
    """Detect primary programming language from marker files.

    Checks in priority order:
    1. TypeScript (tsconfig.json)
    2. Python (pyproject.toml, setup.py, requirements.txt)
    3. JavaScript (package.json)
    4. Go (go.mod)
    5. Rust (Cargo.toml)

    Args:
        project_root: Path to project root directory

    Returns:
        Lowercase language name or "unknown"
    """
    # Priority order matters - TypeScript before JavaScript
    language_markers = [
        ("typescript", ["tsconfig.json"]),
        ("python", ["pyproject.toml", "setup.py", "requirements.txt"]),
        ("javascript", ["package.json"]),
        ("go", ["go.mod"]),
        ("rust", ["Cargo.toml"]),
    ]

    for language, markers in language_markers:
        for marker in markers:
            if (project_root / marker).exists():
                return language

    return "unknown"


def generate_suggested_checks(language: str, project_root: Path) -> list[str]:
    """Generate language-specific check commands.

    Filters out commands that require missing files (e.g., Makefile).

    Args:
        language: Detected language name (lowercase)
        project_root: Path to project root directory

    Returns:
        List of check commands appropriate for the language
    """
    # Language-specific command sets
    commands_by_language = {
        "python": [
            "make check",
            "pytest tests/test_template_render.py -v",
            "make render-templates",
        ],
        "javascript": ["npm run lint", "npm test"],
        "typescript": ["npm run lint", "npm test"],
        "go": ["go test ./...", "go vet ./..."],
        "rust": ["cargo test", "cargo clippy"],
    }

    # Get base commands for language
    commands = commands_by_language.get(language, [])

    # For unknown language, suggest make check if Makefile exists
    if language == "unknown" and (project_root / "Makefile").exists():
        commands = ["make check"]

    # Filter out make commands if Makefile doesn't exist
    if not (project_root / "Makefile").exists():
        commands = [cmd for cmd in commands if not cmd.startswith("make ")]

    return commands


def generate_key_dirs(project_root: Path) -> list[str]:
    """Identify key project directories.

    Scans for standard directory names and returns up to 5 existing ones.

    Args:
        project_root: Path to project root directory

    Returns:
        List of relative directory paths (no leading /), max 5 items
    """
    # Standard directory names to look for
    standard_dirs = [
        "src",
        "tests",
        "lib",
        "pkg",
        "cmd",
        "internal",
        ".claude",
        ".map",
    ]

    found_dirs = []
    for dir_name in standard_dirs:
        dir_path = project_root / dir_name
        if dir_path.is_dir():
            # Return relative path without leading /
            found_dirs.append(dir_name)

        # Stop at 5 directories
        if len(found_dirs) >= 5:
            break

    return found_dirs


def create_repo_insight(project_root: Path, branch: str) -> Path:
    """Create repository insight JSON artifact.

    Analyzes project and writes validated JSON to .map/repo_insight_<branch>.json

    Args:
        project_root: Path to project root directory
        branch: Git branch name for filename

    Returns:
        Path to created JSON file

    Raises:
        ValueError: If generated data doesn't match schema
        OSError: If file cannot be written
    """
    # Gather all insights
    language = detect_language(project_root)
    suggested_checks = generate_suggested_checks(language, project_root)
    key_dirs = generate_key_dirs(project_root)

    # Build insight dict matching schema
    insight_data = {
        "language": language,
        "suggested_checks": suggested_checks,
        "key_dirs": key_dirs,
    }

    # Validate schema compliance
    _validate_repo_insight_schema(insight_data)

    # Ensure .map/ directory exists
    map_dir = project_root / ".map"
    map_dir.mkdir(exist_ok=True)

    # Write to file
    output_path = map_dir / f"repo_insight_{branch}.json"
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(insight_data, f, indent=2, ensure_ascii=False)

    return output_path


def _validate_repo_insight_schema(data: dict) -> None:
    """Validate data against REPO_INSIGHT_SCHEMA.

    Args:
        data: Dictionary to validate

    Raises:
        ValueError: If data doesn't match schema
    """
    # Check required fields
    required_fields = ["language", "suggested_checks", "key_dirs"]
    for field in required_fields:
        if field not in data:
            raise ValueError(f"Missing required field: {field}")

    # Validate types
    if not isinstance(data["language"], str):
        raise ValueError("language must be string")

    if not isinstance(data["suggested_checks"], list):
        raise ValueError("suggested_checks must be list")

    if not isinstance(data["key_dirs"], list):
        raise ValueError("key_dirs must be list")

    # Validate list contents
    if not all(isinstance(cmd, str) for cmd in data["suggested_checks"]):
        raise ValueError("All suggested_checks must be strings")

    if not all(isinstance(dir_path, str) for dir_path in data["key_dirs"]):
        raise ValueError("All key_dirs must be strings")

    # Validate constraints
    if len(data["key_dirs"]) > 5:
        raise ValueError("key_dirs cannot exceed 5 items")

    # Validate no leading slashes in key_dirs
    for dir_path in data["key_dirs"]:
        if dir_path.startswith("/"):
            raise ValueError(f"key_dirs must be relative paths: {dir_path}")


def compute_differential_insight(project_root: Path, since_sha: str | None) -> dict:
    """Compute file changes since a given git SHA.

    Used for context-aware injection: shows Actor only files
    that changed since the last subtask completed.

    Args:
        project_root: Path to project root
        since_sha: Git SHA to diff against (None = no baseline)

    Returns:
        Dict with changed_files, deleted_files. On success also includes
        since_sha and current_sha. On error: empty lists and error key.
        When since_sha is None: empty lists and note key.
    """
    if since_sha is None:
        return {"changed_files": [], "deleted_files": [], "note": "no baseline SHA"}

    try:
        # Get changed/added/modified/renamed files
        result = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=ACMR", since_sha, "HEAD"],
            capture_output=True,
            text=True,
            cwd=project_root,
            timeout=2,
            check=False,
        )
        if result.returncode != 0:
            return {
                "changed_files": [],
                "deleted_files": [],
                "error": f"git diff failed: {result.stderr.strip()}",
            }
        changed = [f for f in result.stdout.strip().split("\n") if f]

        # Get deleted files
        result_del = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=D", since_sha, "HEAD"],
            capture_output=True,
            text=True,
            cwd=project_root,
            timeout=2,
            check=False,
        )
        deleted = (
            [f for f in result_del.stdout.strip().split("\n") if f]
            if result_del.returncode == 0
            else []
        )

        # Get current HEAD SHA
        head_result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=project_root,
            timeout=2,
            check=False,
        )
        current_sha = (
            head_result.stdout.strip() if head_result.returncode == 0 else "unknown"
        )

        return {
            "changed_files": changed,
            "deleted_files": deleted,
            "since_sha": since_sha,
            "current_sha": current_sha,
        }
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        return {
            "changed_files": [],
            "deleted_files": [],
            "error": str(e),
        }
