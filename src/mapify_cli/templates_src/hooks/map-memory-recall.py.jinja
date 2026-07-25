#!/usr/bin/env python3
"""Inject ranked recalled session memory (additionalContext). (REQUIRE_GUARD: MAP_INVOKED_BY)."""
import json
import os
import sys
from pathlib import Path

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))


def _silent() -> None:
    sys.stdout.write("{}")
    sys.exit(0)


def main() -> None:
    if os.environ.get("MAP_INVOKED_BY"):   # FIRST statement — recursion guard
        sys.exit(0)
    try:
        input_data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        _silent()
        return
    # src/ first (dogfood), falls back to installed mapify_cli; no-op if absent.
    sys.path.insert(0, str(PROJECT_DIR / "src"))
    try:
        from mapify_cli.memory.capture import _resolve_branch
        from mapify_cli.memory.recall import build_recall
    except ImportError:
        _silent()
        return
    try:
        prompt = str(input_data.get("prompt", ""))
        branch = _resolve_branch(PROJECT_DIR)
        event = input_data.get("hook_event_name") or "SessionStart"
        ctx = build_recall(prompt, branch, PROJECT_DIR)
    except Exception:   # noqa: BLE001 — hooks must never block
        _silent()
        return
    if ctx:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": ctx}}))
    else:
        _silent()


if __name__ == "__main__":
    main()
