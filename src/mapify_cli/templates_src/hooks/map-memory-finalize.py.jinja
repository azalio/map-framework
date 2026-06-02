#!/usr/bin/env python3
"""Finalize prior dirty session scratches into digests (claude -p). (REQUIRE_GUARD: MAP_INVOKED_BY)."""
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
        from mapify_cli.memory.capture import resolve_session_id
        from mapify_cli.memory.finalize import finalize_dirty
    except ImportError:
        _silent()
        return
    try:
        timeout = int(os.environ.get("MAP_MEMORY_FINALIZE_TIMEOUT", "60"))
    except (ValueError, TypeError):
        timeout = 60
    try:
        incoming = resolve_session_id(input_data, PROJECT_DIR)
        finalize_dirty(incoming, PROJECT_DIR, timeout)
    except Exception:   # noqa: BLE001 — hooks must never block
        pass
    _silent()


if __name__ == "__main__":
    main()
