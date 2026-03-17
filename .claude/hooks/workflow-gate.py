#!/usr/bin/env python3
"""
Claude Code PreToolUse Hook: Workflow Enforcement Gate

Enforces MAP Framework workflow adherence by blocking Edit/Write/MultiEdit
operations until required workflow steps (Actor + Monitor) are completed.

USAGE:
  This hook runs automatically before Edit/Write/MultiEdit tool calls.
  No manual invocation needed - Claude Code handles hook execution.

ENFORCEMENT RULES:
  - Allows Edit/Write/MultiEdit when workflow_state.json is missing (fail-open)
  - Blocks if current subtask hasn't completed required steps: ['actor', 'monitor']
  - Allows tools if all required steps are completed
  - Always allows edits under .map/ (workflow artifacts/state) to prevent deadlocks
  - Always allows edits under ~/.claude/ (auto-memory, project settings)
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


def extract_target_file_paths(tool_call: Dict) -> list[str]:
    """Best-effort extraction of file paths from Claude Code tool payloads."""
    tool_input = tool_call.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return []

    paths: list[str] = []

    direct = tool_input.get("file_path")
    if isinstance(direct, str) and direct.strip():
        paths.append(direct)

    edits = tool_input.get("edits")
    if isinstance(edits, list):
        for edit in edits:
            if not isinstance(edit, dict):
                continue
            fp = edit.get("file_path")
            if isinstance(fp, str) and fp.strip():
                paths.append(fp)

    return paths


def is_exempt_path(file_path: str) -> bool:
    """
    Return True if file_path is exempt from workflow enforcement.

    Exempt paths:
    - .map/ artifacts (workflow state, plans, findings) -- prevents deadlocks
    - ~/.claude/ (auto-memory, project settings) -- Claude's own persistence
    """
    if not isinstance(file_path, str) or not file_path.strip():
        return False

    candidate = Path(file_path)
    resolved = (
        candidate.resolve(strict=False)
        if candidate.is_absolute()
        else (Path.cwd().resolve() / candidate).resolve(strict=False)
    )

    # Allow Claude auto-memory writes (~/.claude/projects/*/memory/)
    claude_memory_dir = Path.home() / ".claude" / "projects"
    try:
        rel = resolved.relative_to(claude_memory_dir.resolve())
        # Only allow paths that include a "memory" component
        if "memory" in rel.parts:
            return True
    except ValueError:
        pass

    # Allow .map/ artifacts
    repo_root = Path.cwd().resolve()
    try:
        rel = resolved.relative_to(repo_root)
    except ValueError:
        return False

    return bool(rel.parts) and rel.parts[0] == ".map"


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
    Check if current subtask(s) have completed required workflow steps.

    Supports both single-subtask mode (current_subtask) and parallel wave mode
    (active_subtasks list). In parallel mode, allows edits if ANY active
    subtask has completed the required steps.

    Returns:
        (is_compliant, error_message)
    """
    # Try active_subtasks first (parallel wave mode)
    active = state.get("active_subtasks", [])
    if not active:
        # Backward compat: single current_subtask
        current = state.get("current_subtask")
        if current:
            active = [current]

    if not active:
        current_state = state.get("current_state") or "UNKNOWN"
        return False, (
            "⛔ Workflow Enforcement: No current_subtask defined in workflow_state.json\n\n"
            f"current_state: {current_state}\n\n"
            "Edits to non-.map files are blocked until current_subtask is set and "
            "the required steps are completed.\n\n"
            "To fix:\n"
            "  - Update .map/<branch>/workflow_state.json to set current_subtask\n"
            "  - Or re-run /map-resume or /map-plan to regenerate state\n"
            "  - Or delete .map/<branch>/workflow_state.json to disable enforcement"
        )

    # Allow if ANY active subtask has completed required steps
    for subtask_id in active:
        completed = state.get("completed_steps", {}).get(subtask_id, [])
        if all(step in completed for step in REQUIRED_STEPS):
            return True, None

    # Block with appropriate message
    missing_details = []
    for subtask_id in active:
        completed = state.get("completed_steps", {}).get(subtask_id, [])
        missing = [step for step in REQUIRED_STEPS if step not in completed]
        if missing:
            missing_details.append(f"{subtask_id}: missing {', '.join(missing)}")

    return False, (
        f"⛔ Workflow Enforcement: Cannot edit code for active subtasks\n\n"
        f"Active subtasks: {', '.join(active)}\n"
        f"Missing steps:\n" + "\n".join(f"  - {d}" for d in missing_details) + "\n\n"
        "Required workflow:\n"
        "  1. Call Task(subagent_type='actor') to generate implementation\n"
        "  2. Call Task(subagent_type='monitor') to validate\n"
        "  3. Only then can you apply changes with Edit/Write\n\n"
        "To fix: Complete missing steps before editing code.\n"
        "Or update workflow_state.json if steps were completed."
    )


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

        # Always allow edits to MAP workflow artifacts under .map/
        target_paths = extract_target_file_paths(tool_call)
        if target_paths and all(is_exempt_path(p) for p in target_paths):
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
