#!/usr/bin/env python3
"""
Claude Code PreToolUse Hook: Workflow Enforcement Gate

Enforces MAP Framework workflow adherence by blocking Edit/Write/MultiEdit
operations until required workflow steps (Actor + Monitor) are completed.

USAGE:
  This hook runs automatically before Edit/Write/MultiEdit tool calls.
  No manual invocation needed - Claude Code handles hook execution.

ENFORCEMENT RULES:
  - Blocks Edit/Write/MultiEdit if workflow_state.json is missing
  - Blocks if current subtask hasn't completed required steps: ['actor', 'monitor']
  - Allows tools if all required steps are completed
  - Allows Read, Bash, and other non-editing tools always

WORKFLOW STATE FILE:
  Location: .map/<branch>/workflow_state.json
  Required fields:
    - current_subtask: Current subtask ID (e.g., "ST-001")
    - completed_steps: Dict mapping subtask_id -> list of completed steps
    - pending_steps: Dict mapping subtask_id -> list of pending steps

HOOK BEHAVIOR:
  - Exit code 0: Allow tool execution
  - Exit code 0 + permissionDecision=deny: Block tool execution with reason (preferred)

TESTING:
  echo '{"tool_name": "Edit", "tool_input": {"file_path": "test.py"}}' | python3 workflow-gate.py
  # Expected (no workflow state): Exit 0, stdout: {}
  # Expected (workflow active, missing steps): Exit 0, stdout: {"hookSpecificOutput":{"permissionDecision":"deny",...}}

PERFORMANCE:
  Target: <100ms per invocation
  Design: Minimal I/O, fast JSON parsing, pre-compiled checks

DESIGN RATIONALE:
  Based on LLM Council recommendation: "Reify State - Don't tell the model
  'remember to call Monitor.' Make the environment hostile to action until
  the Monitor is called." This hook implements that principle through
  filesystem-based enforcement.
"""
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, Optional

# Tools that require workflow enforcement
EDITING_TOOLS = {"Edit", "Write", "MultiEdit"}

# Required steps before allowing edits
REQUIRED_STEPS = ["actor", "monitor"]


def sanitize_branch_name(branch: str) -> str:
    """Sanitize branch name for safe filesystem paths."""
    sanitized = branch.replace("/", "-")
    sanitized = re.sub(r"[^a-zA-Z0-9_.-]", "-", sanitized)
    sanitized = re.sub(r"-+", "-", sanitized).strip("-")
    if ".." in sanitized or sanitized.startswith("."):
        return "default"
    return sanitized or "default"


def get_branch_name() -> str:
    """Get current git branch name (sanitized for filesystem)."""
    try:
        import subprocess

        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=1,
        )
        if result.returncode == 0:
            return sanitize_branch_name(result.stdout.strip())
    except Exception:
        pass
    return "default"


def load_workflow_state(branch: str) -> Optional[Dict]:
    """Load workflow state from .map/<branch>/workflow_state.json"""
    state_file = Path(f".map/{branch}/workflow_state.json")

    if not state_file.exists():
        return None

    try:
        with open(state_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def check_workflow_compliance(state: Dict) -> tuple[bool, Optional[str]]:
    """
    Check if current subtask has completed required workflow steps.

    Returns:
        (is_compliant, error_message)
    """
    current_subtask = state.get("current_subtask")
    if not current_subtask:
        return False, "No current_subtask defined in workflow_state.json"

    completed = state.get("completed_steps", {}).get(current_subtask, [])

    missing_steps = [step for step in REQUIRED_STEPS if step not in completed]

    if missing_steps:
        pending = state.get("pending_steps", {}).get(current_subtask, [])
        return False, (
            f"⛔ Workflow Enforcement: Cannot edit code for {current_subtask}\n\n"
            f"Missing required steps: {', '.join(missing_steps)}\n"
            f"Completed: {', '.join(completed) if completed else 'none'}\n"
            f"Pending: {', '.join(pending) if pending else 'none'}\n\n"
            f"Required workflow:\n"
            f"  1. Call Task(subagent_type='actor') to generate implementation\n"
            f"  2. Call Task(subagent_type='monitor') to validate\n"
            f"  3. Only then can you apply changes with Edit/Write\n\n"
            f"To fix: Complete missing steps before editing code.\n"
            f"Or update workflow_state.json if steps were completed."
        )

    return True, None


def main():
    """Main hook entry point."""
    try:
        # Read tool call from stdin
        tool_call = json.load(sys.stdin)
        tool_name = tool_call.get("tool_name", "")

        # Allow non-editing tools
        if tool_name not in EDITING_TOOLS:
            print("{}")
            sys.exit(0)

        # Get current branch
        branch = get_branch_name()

        # Load workflow state
        state = load_workflow_state(branch)

        if state is None:
            # No workflow state = not in MAP workflow mode, allow
            # (This prevents breaking non-MAP work)
            print("{}")
            sys.exit(0)

        # Check workflow compliance
        is_compliant, error_message = check_workflow_compliance(state)

        if is_compliant:
            print("{}")
            sys.exit(0)
        else:
            print(
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "PreToolUse",
                            "permissionDecision": "deny",
                            "permissionDecisionReason": error_message,
                        }
                    }
                )
            )
            sys.exit(0)

    except Exception as e:
        # On hook failure, approve (fail-open to avoid blocking work)
        print("{}")
        if os.environ.get("DEBUG_WORKFLOW_GATE"):
            print(f"[workflow-gate] ERROR: {e}", file=sys.stderr)
        sys.exit(0)


if __name__ == "__main__":
    main()
