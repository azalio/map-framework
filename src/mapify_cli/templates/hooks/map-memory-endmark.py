#!/usr/bin/env python3
"""Best-effort 'ended' marker for the session WAL. (REQUIRE_GUARD: MAP_INVOKED_BY)."""

import sys

# MAP requires Python 3.11+, and this file runs under the `python3` resolved from
# PATH (see the shebang above) -- not under the interpreter that installed MAP.
# On a stock macOS that is /usr/bin/python3 (3.9), where every 3.11-only
# construct further down (`from datetime import UTC`, PEP 604 unions in
# evaluated annotations) fails with a message that never mentions the version.
# Name the real cause instead. Kept in sync with
# mapify_cli/python_runtime.MINIMUM_PYTHON.
# UP036 is suppressed on purpose: the project targets 3.11, but the interpreter
# executing this shipped file is the user's `python3`, not the project's.
#
# FAIL-OPEN mode. Exit 1 is a non-blocking hook error for Claude Code (only
# exit 2, or a JSON deny, blocks a tool call), so the reason reaches the user
# and the session continues -- a broken interpreter is not a policy decision.
if sys.version_info < (3, 11):  # noqa: UP036
    _MAP_PYTHON_PROBLEM = (
        f"MAP requires Python 3.11 or newer, but {sys.executable} is "
        f"Python {sys.version_info[0]}.{sys.version_info[1]}.\n"
        "This file runs under the `python3` on your PATH. Install Python 3.11+\n"
        "(brew install python@3.12, uv python install 3.12, or pyenv install),\n"
        "make sure `python3 --version` reports it, then re-run `mapify check`.\n"
    )
    sys.stderr.write(_MAP_PYTHON_PROBLEM)
    sys.exit(1)

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
