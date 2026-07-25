#!/usr/bin/env python3
"""
Context Meter - UserPromptSubmit Hook.

Reads the live transcript_path, sums token usage from the most recent
assistant turn, and - when the configured threshold is crossed - injects an
``additionalContext`` block telling Claude to run ``/compact <focus>`` before
continuing.

Behaviour summary:
    policy=never      : silent no-op
    policy=auto       : nudge when used >= compression_threshold_tokens
    policy=aggressive : nudge at 0.4 x threshold (see token_budget.py)

Cooldown:
    Skips the nudge if .map/<branch>/last-compact.marker is younger than
    COOLDOWN_SECONDS so that the meter does not double-fire immediately after
    Claude Code's built-in 83.5% auto-compact has already run.

Exit codes:
    0 - Always (UserPromptSubmit hooks should never block).

Output:
    Either ``{}`` (silent) or
    ``{"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
       "additionalContext": "<warning + /compact line>"}}``.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# Cooldown after a recent compaction. Five minutes is comfortably longer than
# any single MAP step but short enough that a stuck workflow recovers fast.
COOLDOWN_SECONDS = 5 * 60


PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
MAP_DIR = PROJECT_DIR / ".map"


def _sanitize_branch(branch: str) -> str:
    sanitized = branch.replace("/", "-")
    sanitized = re.sub(r"[^a-zA-Z0-9_.-]", "-", sanitized)
    sanitized = re.sub(r"-+", "-", sanitized).strip("-")
    if ".." in sanitized or sanitized.startswith("."):
        return "default"
    return sanitized or "default"


def _get_branch() -> str:
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
            return _sanitize_branch(result.stdout.strip())
    except Exception:  # noqa: BLE001, S110 -- deliberate fallback/resilience boundary, must not propagate
        pass
    return "default"


def _recent_compact_marker(branch: str) -> bool:
    """Return True if last-compact.marker is younger than COOLDOWN_SECONDS."""
    marker = MAP_DIR / branch / "last-compact.marker"
    if not marker.is_file():
        return False
    try:
        age = time.time() - marker.stat().st_mtime
        return age < COOLDOWN_SECONDS
    except OSError:
        return False


def _silent() -> None:
    sys.stdout.write("{}")
    sys.exit(0)


def main() -> None:
    if os.environ.get("MAP_INVOKED_BY"):
        sys.exit(0)
    # Read input strictly as JSON. Anything malformed -> silent no-op.
    try:
        input_data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        _silent()
        return

    transcript_path = input_data.get("transcript_path", "")
    if not transcript_path:
        _silent()
        return

    # Lazy imports - keep startup fast and let the hook degrade gracefully if
    # the project's mapify_cli is not on PYTHONPATH (e.g. in unusual sandbox
    # configurations). In that case we silently no-op rather than crash.
    sys.path.insert(0, str(PROJECT_DIR / "src"))
    try:
        from mapify_cli.config.project_config import load_map_config
        from mapify_cli.token_budget import (
            count_last_turn_tokens,
            effective_threshold,
            format_compact_instruction,
            should_nudge,
        )
    except ImportError:
        _silent()
        return

    config = load_map_config(PROJECT_DIR)
    threshold = effective_threshold(
        config.compression_policy, config.compression_threshold_tokens
    )
    if threshold is None:
        # policy=never or invalid threshold -> no nudge.
        _silent()
        return

    branch = _get_branch()
    if _recent_compact_marker(branch):
        _silent()
        return

    used = count_last_turn_tokens(Path(transcript_path))
    if not should_nudge(used, threshold):
        _silent()
        return

    message = format_compact_instruction(
        used=used,
        threshold=threshold,
        focus=config.compression_focus,
    )

    output = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": message,
        }
    }
    sys.stdout.write(json.dumps(output))
    sys.exit(0)


if __name__ == "__main__":
    main()
