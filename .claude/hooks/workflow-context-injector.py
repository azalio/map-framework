#!/usr/bin/env python3
"""
Workflow Context Injector - PreToolUse Hook (Tiered)

Injects workflow state reminders ONLY for significant operations:
- Edit/Write/MultiEdit: Always inject (~150 chars)
- Bash: Only for significant commands (tests, builds, git commits)

Does NOT inject for read-only operations (ls, cat, grep, etc.)

Trigger: Edit|Write|Bash
Exit codes: Always 0 (non-blocking, just adds context)
"""

import json
import os
import re
import sys
from pathlib import Path

# Bash commands that don't need workflow reminders
READONLY_COMMANDS = {
    "ls", "cat", "head", "tail", "grep", "rg", "find", "pwd",
    "echo", "wc", "diff", "tree", "file", "which", "type",
    "env", "printenv", "date", "whoami", "id", "uname",
    "less", "more", "stat", "du", "df", "free",
}

# Bash commands that ARE significant and need reminders
SIGNIFICANT_PATTERNS = [
    r"pytest", r"go\s+test", r"npm\s+test", r"cargo\s+test", r"make\s+test",
    r"git\s+commit", r"git\s+push", r"git\s+merge", r"git\s+rebase",
    r"npm\s+install", r"pip\s+install", r"go\s+mod",
    r"make\b", r"docker\b", r"kubectl\b",
    r"\brm\s", r"\bmv\s", r"\bcp\s+-r",
]


def get_branch_name() -> str:
    """Get current git branch name."""
    import subprocess
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=2
        )
        if result.returncode == 0:
            return result.stdout.strip().replace("/", "-")
    except Exception:
        pass
    return "default"


def load_workflow_state(branch: str) -> dict | None:
    """Load workflow state from .map/<branch>/workflow_state.json."""
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    state_file = project_dir / ".map" / branch / "workflow_state.json"

    if not state_file.exists():
        return None

    try:
        with open(state_file) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def should_inject_for_bash(command: str) -> bool:
    """Determine if Bash command needs workflow reminder."""
    if not command:
        return False

    # Extract first word of command
    cmd_parts = command.strip().split()
    if not cmd_parts:
        return False

    first_word = cmd_parts[0].split("/")[-1]  # Handle full paths

    # Skip read-only commands
    if first_word in READONLY_COMMANDS:
        return False

    # Check for significant patterns
    for pattern in SIGNIFICANT_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return True

    # Default: inject for unknown commands (safer)
    return False


def format_reminder(state: dict) -> str | None:
    """Format terse workflow reminder (~150 chars)."""
    if not state:
        return None

    current_step = state.get("current_step", {})
    phase = current_step.get("phase", "")
    task = current_step.get("task", "")
    mandatory = state.get("mandatory_next_action")

    if not phase and not task:
        return None

    if mandatory:
        return f"[MAP] Phase: {phase} | Task: {task} | REQUIRED: {mandatory}"
    return f"[MAP] Phase: {phase} | Task: {task}"


def main() -> None:
    try:
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError:
        print("{}")
        sys.exit(0)

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})

    # Determine if we should inject
    should_inject = False

    if tool_name in ("Edit", "Write", "MultiEdit"):
        should_inject = True
    elif tool_name == "Bash":
        command = tool_input.get("command", "")
        should_inject = should_inject_for_bash(command)

    if not should_inject:
        print("{}")
        sys.exit(0)

    # Load and format workflow state
    branch = get_branch_name()
    state = load_workflow_state(branch)

    if not state:
        print("{}")
        sys.exit(0)

    reminder = format_reminder(state)
    if reminder:
        output = {"hookSpecificOutput": {"appended_text": reminder}}
        print(json.dumps(output))
    else:
        print("{}")

    sys.exit(0)


if __name__ == "__main__":
    main()
