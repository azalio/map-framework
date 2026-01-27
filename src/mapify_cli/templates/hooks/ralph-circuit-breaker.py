#!/usr/bin/env python3
"""
Ralph Loop Circuit Breaker - PreToolUse Hook.

Detects tool thrashing and enforces iteration limits.

FOLLOWS EXISTING PATTERN from block-secrets.py:
- Block: exit 2 + JSON to stderr
- Allow: exit 0 (no output)

Exit codes:
  0 - Allow tool execution
  2 - Block tool execution (limit exceeded)
"""

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Tuple

# Paths - BRANCH-SCOPED
PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
MAP_DIR = PROJECT_DIR / ".map"

DEBUG_MODE = os.environ.get("RALPH_DEBUG", "").lower() in ("1", "true", "yes")


def load_limits(project_dir: Path) -> Tuple[int, int, int]:
    """Return (max_same_file_edits, max_total_iterations, warning_threshold)."""
    defaults = (5, 50, 2)
    config_file = project_dir / ".claude" / "ralph-loop-config.json"
    if config_file.exists():
        try:
            cfg = json.loads(config_file.read_text()).get("ralph_loop", {})
            cb = cfg.get("circuit_breaker", {})
            defaults = (
                int(cb.get("max_same_file_edits", defaults[0])),
                int(cb.get("max_total_iterations", defaults[1])),
                defaults[2],
            )
        except Exception:
            # Ignore invalid or unreadable config and fall back to default limits
            pass

    # Override via env vars if present
    max_same_file_edits = int(os.environ.get("RALPH_MAX_FILE_EDITS", str(defaults[0])))
    max_total_iterations = int(os.environ.get("RALPH_MAX_ITERATIONS", str(defaults[1])))
    warning_threshold = int(os.environ.get("RALPH_WARNING_THRESHOLD", str(defaults[2])))
    return max_same_file_edits, max_total_iterations, warning_threshold


MAX_SAME_FILE_EDITS, MAX_TOTAL_ITERATIONS, WARNING_THRESHOLD = load_limits(PROJECT_DIR)


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
    import subprocess

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            cwd=PROJECT_DIR,
        )
        if result.returncode == 0:
            return sanitize_branch_name(result.stdout.strip())
    except Exception:
        # If git is unavailable or not a repo, fall back to default branch name
        pass
    return "default"


def get_history_file() -> Path:
    """Get branch-scoped history file path."""
    branch = get_branch_name()
    branch_dir = MAP_DIR / branch
    branch_dir.mkdir(parents=True, exist_ok=True)
    return branch_dir / ".tool_history.jsonl"


def get_reset_marker_file() -> Path:
    """Get branch-scoped reset marker file path."""
    branch = get_branch_name()
    branch_dir = MAP_DIR / branch
    branch_dir.mkdir(parents=True, exist_ok=True)
    return branch_dir / ".ralph_reset_limits"


def normalize_requested_path(p: str) -> str:
    """Normalize tool file paths for stable comparisons (relative/absolute)."""
    if not p:
        return ""
    try:
        pp = Path(p)
        if not pp.is_absolute():
            pp = PROJECT_DIR / pp
        return str(pp.resolve())
    except Exception:
        return p


def perform_reset_limits() -> None:
    """
    Reset limits by archiving/removing tool history and logs.

    This is triggered via marker file `.map/<branch>/.ralph_reset_limits`.
    User action is minimal: select RESET_LIMITS; orchestrator writes marker.
    """
    marker = get_reset_marker_file()
    if not marker.exists():
        return

    branch = get_branch_name()
    branch_dir = MAP_DIR / branch
    archive_root = MAP_DIR / "logs_archive" / branch
    archive_root.mkdir(parents=True, exist_ok=True)

    # Files that affect enforcement/observability
    reset_files = [
        branch_dir / ".tool_history.jsonl",  # ENFORCEMENT SOURCE OF TRUTH
        branch_dir / "iteration_log.jsonl",
        branch_dir / "thrashing_alerts.jsonl",
    ]

    # IMPORTANT: Do NOT delete final verification artifacts.
    # - `.map/<branch>/final_verification.json` is the source of truth for verification.
    # - `.map/progress_<branch>.md` contains human-readable verification history.
    # Recovery only resets limits/logs; it does not erase evidence.

    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    for p in reset_files:
        if not p.exists():
            continue
        try:
            p.rename(archive_root / f"{p.name}.{timestamp}")
        except Exception:
            try:
                p.unlink()
            except Exception:
                # Best-effort cleanup: ignore failures to delete archived files
                pass

    # Best-effort: remove marker
    try:
        marker.unlink()
    except Exception:
        # Best-effort cleanup: ignore failures to remove marker file
        pass


def load_history() -> list:
    """
    Load recent tool history from JSONL file.

    IMPORTANT: Skips malformed lines instead of returning empty list.
    Returning [] on any error would disable limits entirely.
    """
    history_file = get_history_file()
    try:
        if not history_file.exists():
            return []
        lines = history_file.read_text().strip().split("\n")
        # Keep enough history to honor configured limits (dynamic cap)
        max_entries = max(100, MAX_TOTAL_ITERATIONS, MAX_SAME_FILE_EDITS)
        entries = []
        for line in lines[-max_entries:]:
            if not line.strip():
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                # Skip malformed line, continue with others
                continue
        return entries
    except IOError:
        return []  # File access error - return empty (rare)


def save_entry(entry: dict) -> None:
    """Append entry to tool history (atomic on POSIX)."""
    history_file = get_history_file()
    try:
        # Single write() in append mode is atomic on POSIX
        with open(history_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=True) + "\n")
    except IOError:
        # Best-effort logging: failures to persist history must not block tool execution
        pass


def check_limits(tool_name: str, tool_input: dict) -> dict:
    """Check if tool use should be blocked. Returns {blocked, reason, warning}."""
    # Load history BEFORE saving current entry (avoid off-by-one)
    history = load_history()
    # Use normalized file path if available to avoid relative/absolute mismatches.
    file_path = (
        tool_input.get("_normalized_file_path")
        or tool_input.get("file_path", "")
        or tool_input.get("path", "")
    )

    result: dict[str, bool | str | None] = {
        "blocked": False,
        "reason": None,
        "warning": None,
    }

    # Check 1: Same file edited too many times
    if file_path and tool_name in ("Edit", "Write"):
        # Count PREVIOUS edits to this file (not including current)
        file_edits = sum(
            1
            for h in history
            if h.get("file") == file_path and h.get("tool") in ("Edit", "Write")
        )

        # Warning before hitting limit
        if file_edits >= MAX_SAME_FILE_EDITS - WARNING_THRESHOLD:
            remaining = MAX_SAME_FILE_EDITS - file_edits
            if remaining > 0:
                result["warning"] = (
                    f"[ralph-cb] File '{Path(file_path).name}' edited {file_edits} times, "
                    f"{remaining} remaining before limit"
                )

        if file_edits >= MAX_SAME_FILE_EDITS:
            result["blocked"] = True
            result["reason"] = (
                f"Circuit Breaker: File '{Path(file_path).name}' edited {file_edits} times. "
                "Consider different approach or select RESET_LIMITS to reset limits."
            )
            return result

    # Check 2: Total iterations (not including current)
    total_iterations = len(history)

    # Warning before hitting limit
    if total_iterations >= MAX_TOTAL_ITERATIONS - WARNING_THRESHOLD:
        remaining = MAX_TOTAL_ITERATIONS - total_iterations
        if remaining > 0 and not result["warning"]:
            result["warning"] = (
                f"[ralph-cb] {total_iterations} tool calls, {remaining} remaining before limit"
            )

    if total_iterations >= MAX_TOTAL_ITERATIONS:
        result["blocked"] = True
        result["reason"] = (
            f"Circuit Breaker: {total_iterations} tool calls reached limit. "
            "Select RESET_LIMITS to reset limits and continue."
        )
        return result

    return result


def block_access(reason: str, tool_name: str) -> None:
    """Block tool execution - follows block-secrets.py pattern."""
    error_output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "error": f"Blocked: {reason}",
            "details": f"Tool '{tool_name}' blocked by Ralph Loop Circuit Breaker",
            "suggestion": "Select RESET_LIMITS to reset limits or try different approach",
        }
    }
    print(json.dumps(error_output, ensure_ascii=True), file=sys.stderr)
    sys.exit(2)


def main() -> None:
    """Main hook execution logic."""
    try:
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError:
        print("{}")
        sys.exit(0)  # Allow on parse error

    # Debug mode: log raw input for schema verification
    if DEBUG_MODE:
        debug_file = MAP_DIR / get_branch_name() / "raw_hook_inputs.jsonl"
        debug_file.parent.mkdir(parents=True, exist_ok=True)
        with open(debug_file, "a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {"hook": "circuit-breaker", "input": input_data}, ensure_ascii=True
                )
                + "\n"
            )

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})
    session_id = input_data.get("session_id", "")

    # Normalize file paths once for consistent counting + marker comparisons.
    raw_file_path = tool_input.get("file_path", "") or tool_input.get("path", "")
    normalized_file_path = normalize_requested_path(raw_file_path)
    tool_input = dict(tool_input)
    tool_input["_normalized_file_path"] = normalized_file_path

    # Allow reset marker write to always pass (recovery must be possible).
    marker_path = str(get_reset_marker_file().resolve())
    if tool_name in ("Write", "Edit") and normalized_file_path == marker_path:
        print("{}")
        sys.exit(0)

    # If reset marker exists, perform reset before enforcing limits.
    perform_reset_limits()

    # Only check Edit, Write, Bash tools
    if tool_name not in ("Edit", "Write", "Bash"):
        print("{}")
        sys.exit(0)

    # Check limits BEFORE logging
    check = check_limits(tool_name, tool_input)

    # Output warning to stderr (informational, doesn't block)
    if check["warning"]:
        print(check["warning"], file=sys.stderr)

    if check["blocked"]:
        # Log blocked call separately for observability
        file_path = (
            tool_input.get("_normalized_file_path")
            or tool_input.get("file_path", "")
            or tool_input.get("path", "")
        )
        save_entry(
            {
                "ts": datetime.now().isoformat(),
                "tool": tool_name,
                "file": file_path,
                "session_id": session_id,
                "blocked": True,
                "reason": check["reason"],
            }
        )
        block_access(check["reason"], tool_name)

    # Log this call (after check)
    file_path = (
        tool_input.get("_normalized_file_path")
        or tool_input.get("file_path", "")
        or tool_input.get("path", "")
    )
    save_entry(
        {
            "ts": datetime.now().isoformat(),
            "tool": tool_name,
            "file": file_path,
            "session_id": session_id,
        }
    )

    print("{}")
    sys.exit(0)  # Allow


if __name__ == "__main__":
    main()
