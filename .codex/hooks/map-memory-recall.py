#!/usr/bin/env python3
"""Delegate Codex memory handling to the installed mapify runtime."""

import sys

# MAP requires Python 3.11+, and this file runs under the `python3` resolved from
# PATH (see the shebang above) -- not under the interpreter that installed MAP.
# On a stock macOS that is /usr/bin/python3 (3.9), where every 3.11-only
# construct further down (`from datetime import UTC`, PEP 604 unions in
# evaluated annotations) fails with a message that never mentions the version.
# Name the real cause instead. Kept in sync with
# mapify_cli/python_runtime.MINIMUM_PYTHON.
# Compare the runtime tuple: the executing interpreter is the user's `python3`,
# not necessarily the Python version targeted by the project's static checker.
#
# FAIL-OPEN mode. Exit 1 is a non-blocking hook error for Claude Code (only
# exit 2, or a JSON deny, blocks a tool call), so the reason reaches the user
# and the session continues -- a broken interpreter is not a policy decision.
if tuple(sys.version_info) < (3, 11):
    _MAP_PYTHON_PROBLEM = (
        f"MAP requires Python 3.11 or newer, but {sys.executable} is "
        f"Python {sys.version_info[0]}.{sys.version_info[1]}.\n"
        "This file runs under the `python3` on your PATH. Install Python 3.11+\n"
        "(brew install python@3.12, uv python install 3.12, or pyenv install),\n"
        "make sure `python3 --version` reports it, then re-run `mapify check`.\n"
    )
    sys.stderr.write(_MAP_PYTHON_PROBLEM)
    sys.exit(1)

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())).resolve()
ACTION = "recall"
PROVIDER = "codex"


def _silent() -> None:
    sys.stdout.write("{}")


def _mapify_runtime() -> list[str] | None:
    """Command prefix that runs the installed mapify CLI, or None when absent.

    Resolution: ``$MAPIFY_CLI`` (explicit), then ``mapify`` on PATH, then the
    ``mapify_cli`` package importable by this interpreter (``python -m``).
    Memory hooks are best effort: with none of these the hook stays silent.
    """
    explicit = os.environ.get("MAPIFY_CLI")
    if explicit:
        return [explicit]
    on_path = shutil.which("mapify")
    if on_path:
        return [on_path]
    if importlib.util.find_spec("mapify_cli") is not None:
        return [sys.executable, "-m", "mapify_cli"]
    return None


def main() -> None:
    if os.environ.get("MAP_INVOKED_BY"):
        return
    raw_event = sys.stdin.read()
    try:
        event = json.loads(raw_event)
    except (json.JSONDecodeError, ValueError):
        _silent()
        return
    if not isinstance(event, dict):
        _silent()
        return

    runtime = _mapify_runtime()
    if runtime is None:
        _silent()
        return
    timeout = {
        "capture": 4,
        "endmark": 2,
        "finalize": 55,
        "recall": 8,
        "session": 55,
    }[ACTION]
    try:
        proc = subprocess.run(
            [
                *runtime,
                "_memory-hook",
                ACTION,
                "--project",
                str(PROJECT_DIR),
                "--provider",
                PROVIDER,
            ],
            input=raw_event,
            text=True,
            capture_output=True,
            cwd=PROJECT_DIR,
            env=os.environ.copy(),
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        _silent()
        return
    output = proc.stdout.strip()
    if proc.returncode != 0 or not output:
        _silent()
        return
    try:
        json.loads(output)
    except json.JSONDecodeError:
        _silent()
        return
    sys.stdout.write(output)


if __name__ == "__main__":
    main()

