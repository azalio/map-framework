#!/usr/bin/env python3
"""
Ralph Loop Context Pruner + Anti-Amnesia Hook - PreCompact Hook.

Before context compaction:
1. SAVES current workflow state to restore_point.json (Anti-Amnesia)
2. Injects ~300 char recovery message with full workflow context
3. Archives old logs to preserve token budget

This ensures Claude can restore workflow context after compaction.

Exit codes:
  0 - Always (PreCompact hooks don't block)

Output:
  Side effects only (PreCompact has no decision control per docs)
"""
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Configuration
MAX_LINES = 100
MAX_AGE_HOURS = 24

# Paths - BRANCH-SCOPED
PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
MAP_DIR = PROJECT_DIR / ".map"
ARCHIVE_DIR = MAP_DIR / "logs_archive"

# Files to prune (relative to branch directory)
LOG_FILES = [".tool_history.jsonl", "iteration_log.jsonl", "thrashing_alerts.jsonl"]

# Reserved directories that are NOT branch directories
# These will never be treated as branch dirs for pruning
RESERVED_DIRS = {
    "logs_archive",  # Archive directory
    ".cache",  # Potential cache directory
    ".tmp",  # Potential temp directory
}


def sanitize_branch_name(branch: str) -> str:
    """Sanitize branch name for safe filesystem paths."""
    sanitized = branch.replace("/", "-")
    sanitized = re.sub(r"[^a-zA-Z0-9_.-]", "-", sanitized)
    sanitized = re.sub(r"-+", "-", sanitized)
    sanitized = sanitized.strip("-")
    if ".." in sanitized or sanitized.startswith("."):
        return "default"
    return sanitized or "default"


def get_branch_name() -> str:
    """Get current git branch name (sanitized) for branch-scoped artifacts."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            cwd=PROJECT_DIR,
            timeout=2,
            check=False,
        )
        if result.returncode == 0:
            return sanitize_branch_name(result.stdout.strip())
    except Exception:  # noqa: BLE001, S110 -- deliberate fallback/resilience boundary, must not propagate
        # Intentionally ignore all errors (e.g., missing git, not a repo) and fall back to default
        pass
    return "default"


def is_branch_dir(d: Path) -> bool:
    """
    Check if directory is a branch directory (not a reserved/service dir).

    Branch directories:
    - Are not in RESERVED_DIRS
    - Don't start with '.' (hidden dirs)
    - Contain at least one Ralph Loop log file
    """
    if d.name in RESERVED_DIRS:
        return False
    if d.name.startswith("."):
        return False
    # Check if it looks like a branch dir (has Ralph Loop files)
    has_ralph_files = any((d / f).exists() for f in LOG_FILES)
    return has_ralph_files


def get_all_branch_dirs() -> list[Path]:
    """Get all branch directories in .map/ for pruning."""
    try:
        if not MAP_DIR.exists():
            return []
        return [d for d in MAP_DIR.iterdir() if d.is_dir() and is_branch_dir(d)]
    except OSError:
        return []


def prune_file(file_path: Path, archive_dir: Path) -> str | None:
    """
    Prune a single log file.
    - Archive if older than MAX_AGE_HOURS
    - Truncate if more than MAX_LINES

    Returns action description or None if no action taken.
    """
    try:
        if not file_path.exists():
            return None

        stat = file_path.stat()
        age_hours = (datetime.now(UTC).timestamp() - stat.st_mtime) / 3600
        file_name = file_path.name

        # Archive old files
        if age_hours > MAX_AGE_HOURS:
            archive_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
            archive_name = f"{file_name}.{timestamp}"
            shutil.move(str(file_path), str(archive_dir / archive_name))
            return f"{file_name} (archived)"

        # Truncate large files
        lines = file_path.read_text().strip().split("\n")
        if len(lines) > MAX_LINES:
            # Keep only last MAX_LINES
            truncated_content = "\n".join(lines[-MAX_LINES:]) + "\n"
            file_path.write_text(truncated_content)
            return f"{file_name} (truncated {len(lines)} -> {MAX_LINES})"

        return None
    except OSError:
        return None


def load_workflow_state(branch: str) -> dict[str, Any] | None:
    """Load workflow state from .map/<branch>/step_state.json."""
    state_file = MAP_DIR / branch / "step_state.json"
    if not state_file.exists():
        return None
    try:
        with open(state_file) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def save_restore_point(branch: str, state: dict[str, Any]) -> bool:
    """Save workflow state to restore_point.json for post-compaction recovery."""
    branch_dir = MAP_DIR / branch
    branch_dir.mkdir(parents=True, exist_ok=True)
    restore_file = branch_dir / "restore_point.json"

    restore_data = {
        "saved_at": datetime.now(UTC).isoformat(),
        "reason": "pre_compaction",
        "workflow_state": state,
    }

    try:
        with open(restore_file, "w") as f:
            json.dump(restore_data, f, indent=2)
        return True
    except OSError:
        return False


def format_recovery_message(state: dict[str, Any], branch: str) -> str:
    """Format ~300 char recovery message for post-compaction context."""
    workflow = state.get("workflow", "unknown")

    # Handle different state formats
    current_step = state.get("current_step", {})
    if current_step:
        phase = current_step.get("phase", "unknown")
        task = current_step.get("task", "unknown")
    else:
        # Alternative format: current_state + current_subtask
        phase = state.get("current_state", "unknown")
        task = state.get("current_subtask") or "none"

    mandatory = state.get("mandatory_next_action", "")

    # Get recent completed tasks (last 2) - handle both list and dict formats
    completed = state.get("completed_steps", {})
    if isinstance(completed, dict):
        # Dict format: {"ST-001": "complete", ...}
        completed_keys = list(completed.keys())
        recent = ", ".join(completed_keys[-2:]) if completed_keys else "none"
    elif isinstance(completed, list):
        # List format: ["step1", "step2", ...]
        recent = ", ".join(completed[-2:]) if completed else "none"
    else:
        recent = "none"

    msg = f"""[MAP] CONTEXT RESTORED after compaction
Workflow: {workflow}
Phase: {phase} | Task: {task}
Done: {recent}
NEXT: {mandatory if mandatory else 'Continue current task'}
State: .map/{branch}/step_state.json"""

    return msg


def main() -> None:
    """Main hook execution logic."""
    if os.environ.get("MAP_INVOKED_BY"):
        sys.exit(0)
    # Read stdin (required by hook protocol)
    try:
        json.load(sys.stdin)
    except json.JSONDecodeError:
        # Malformed or non-JSON stdin is ignored: this hook doesn't rely on input contents
        pass

    output: dict[str, Any] = {}

    # Skip if no .map directory
    if not MAP_DIR.exists():
        print(json.dumps(output))
        sys.exit(0)

    # Get current branch for Anti-Amnesia
    branch = get_branch_name()

    # ANTI-AMNESIA: Save restore point and inject recovery message
    state = load_workflow_state(branch)
    # Save restore point
    if state and save_restore_point(branch, state):
        print(
            f"[ralph-pruner] Saved restore_point for branch: {branch}",
            file=sys.stderr,
        )

    # Note: PreCompact has no decision control per docs — additionalContext
    # is not supported. Recovery context is injected via SessionStart(compact)
    # hook (post-compact-context.py) which reads restore_point.json.

    # Prune log files in ALL branch directories
    actions = []
    for branch_dir in get_all_branch_dirs():
        for log_file in LOG_FILES:
            action = prune_file(branch_dir / log_file, ARCHIVE_DIR / branch_dir.name)
            if action:
                actions.append(f"{branch_dir.name}/{action}")

    # Report actions to stderr (informational)
    if actions:
        print(f"[ralph-pruner] Pruned: {', '.join(actions)}", file=sys.stderr)

    print(json.dumps(output))
    sys.exit(0)


if __name__ == "__main__":
    main()
