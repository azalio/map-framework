#!/usr/bin/env python3
"""Best-effort 'ended' marker for the session WAL. (REQUIRE_GUARD: MAP_INVOKED_BY)."""
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
        from mapify_cli.memory.capture import on_session_end
    except ImportError:
        _silent()
        return
    try:
        on_session_end(input_data, PROJECT_DIR)
    except Exception:   # noqa: BLE001, S110 — hooks must never block
        pass
    _silent()


if __name__ == "__main__":
    main()
