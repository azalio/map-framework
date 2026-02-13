#!/usr/bin/env python3
"""
Post-Edit Reminder - PostToolUse Hook

Lightweight reminder after Edit/Write operations to run tests.
Only triggers when there's an active MAP workflow.

Trigger: Edit|Write
Exit codes: Always 0 (non-blocking)
Output: ~80 char reminder via hookSpecificOutput.appended_text
"""

import json
import os
import subprocess
import sys
from pathlib import Path


def get_branch_name() -> str:
    """Get current git branch name."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=1,
        )
        if result.returncode == 0:
            return result.stdout.strip().replace("/", "-")
    except Exception:
        pass
    return "default"


def has_active_workflow(branch: str) -> bool:
    """Check if there's an active MAP workflow."""
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    state_file = project_dir / ".map" / branch / "workflow_state.json"
    return state_file.exists()


def main() -> None:
    try:
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError:
        print("{}")
        sys.exit(0)

    tool_name = input_data.get("tool_name", "")

    # Only for Edit/Write
    if tool_name not in ("Edit", "Write", "MultiEdit"):
        print("{}")
        sys.exit(0)

    # Only when MAP workflow is active
    branch = get_branch_name()
    if not has_active_workflow(branch):
        print("{}")
        sys.exit(0)

    # Inject lightweight reminder
    reminder = "[MAP] Code changed. Run tests before committing!"
    output = {"hookSpecificOutput": {"appended_text": reminder}}
    print(json.dumps(output))
    sys.exit(0)


if __name__ == "__main__":
    main()
