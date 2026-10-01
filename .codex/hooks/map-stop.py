#!/usr/bin/env python3
"""Run MAP Stop handlers in a deterministic, mutation-safe order for Codex."""

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

import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
HOOK_DIR = Path(__file__).resolve().parent
STOP_HANDLERS = (
    ("python", "scrub-internal-ids.py", 120),
    ("shell", "end-of-turn.sh", 30),
    ("python", "map-token-meter.py", 5),
    ("python", "map-memory-capture.py", 5),
)


def main() -> None:
    if os.environ.get("MAP_INVOKED_BY"):
        return
    raw_event = sys.stdin.read()
    try:
        json.loads(raw_event or "{}")
    except json.JSONDecodeError:
        raw_event = "{}"

    first_output = ""
    first_error_code = 0
    first_error = ""
    child_env = os.environ.copy()
    child_env["CLAUDE_PROJECT_DIR"] = str(PROJECT_DIR)

    for runtime, filename, timeout in STOP_HANDLERS:
        path = HOOK_DIR / filename
        argv = [sys.executable, str(path)] if runtime == "python" else ["bash", str(path)]
        try:
            proc = subprocess.run(
                argv,
                input=raw_event,
                text=True,
                capture_output=True,
                cwd=PROJECT_DIR,
                env=child_env,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            if not first_error_code:
                first_error_code = 1
                first_error = f"MAP Stop handler {filename} failed: {exc}"
            continue
        output = proc.stdout.strip()
        if output and output != "{}" and not first_output:
            first_output = output
        if proc.returncode and not first_error_code:
            first_error_code = proc.returncode
            first_error = proc.stderr.strip()

    if first_output:
        print(first_output)
    elif not first_error_code:
        print("{}")
    if first_error:
        print(first_error, file=sys.stderr)
    raise SystemExit(first_error_code)


if __name__ == "__main__":
    main()
