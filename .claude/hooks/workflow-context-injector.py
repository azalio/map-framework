#!/usr/bin/env python3
"""
Claude Code PreToolUse Hook: Workflow Context Injection

Injects current workflow step context into Claude's prompt before EVERY tool call
to prevent "forgetting" mandatory steps like mem0 search and self-audit.

DESIGN PATTERN:
  Borrowed from ralph-loop's build_loop_context() approach: inject ~300 char
  reminder via appended_text to keep current step top-of-mind without bloating
  the command file.

KEY INSIGHT:
  Problem: Long prompts (995 lines) cause attention dilution → Claude skips steps
  Solution: Small, frequent reminders (every tool call) > big upfront instructions

USAGE:
  This hook runs automatically before EVERY tool call during MAP workflows.
  No manual invocation needed - Claude Code handles hook execution.

INJECTION BEHAVIOR:
  - Reads .map/<branch>/step_state.json to determine current step
  - Injects ~300 char context block via appended_text (system prompt injection)
  - Shows: current step phase, completed checkpoints, mandatory next action
  - Always allows tool to proceed (non-blocking, unlike workflow-gate.py)

HOOK INTERFACE:
  - Input: JSON on stdin with tool_name, parameters
  - Output: JSON on stdout with appended_text, allow=true
  - Exit code: Always 0 (never blocks tools)

PERFORMANCE:
  Target: <100ms per invocation
  Design: Minimal I/O (single file read), fast JSON parsing, cached reminders

TESTING:
  echo '{"tool_name": "Task", "parameters": {"subagent_type": "actor"}}' | \\
    python3 workflow-context-injector.py
  # Expected: Exit 0, JSON with appended_text field

RELATIONSHIP TO OTHER HOOKS:
  - workflow-gate.py: BLOCKS Edit/Write until actor+monitor complete
  - workflow-context-injector.py: REMINDS Claude of current step (non-blocking)
  - ralph-circuit-breaker.py: BLOCKS if iteration limits exceeded
"""
import json
import os
import sys
from pathlib import Path
from typing import Dict, Optional

# Maximum length of injected context (to prevent token bloat)
MAX_CONTEXT_LENGTH = 500


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
            branch = result.stdout.strip()
            # Sanitize for filesystem (same as ralph_state.py)
            import re
            sanitized = branch.replace("/", "-")
            sanitized = re.sub(r"[^a-zA-Z0-9_.-]", "-", sanitized)
            sanitized = re.sub(r"-+", "-", sanitized).strip("-")
            if ".." in sanitized or sanitized.startswith("."):
                return "default"
            return sanitized or "default"
    except Exception:
        return "default"


def load_step_state(branch: str) -> Optional[Dict]:
    """
    Load current step state from .map/<branch>/step_state.json

    Returns:
        Dict with step state or None if no active workflow
    """
    state_file = Path(f".map/{branch}/step_state.json")

    if not state_file.exists():
        return None

    try:
        with open(state_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def get_step_reminder(phase: str) -> str:
    """
    Get step-specific reminder for current phase.

    Args:
        phase: Current step phase (e.g., "MEM0_SEARCH", "ACTOR_CALL")

    Returns:
        Concise reminder text for the phase
    """
    reminders = {
        "INITIALIZED": "Start workflow: read plan, begin first subtask",
        "XML_PACKET_CREATED": "Packet ready → proceed to mem0 search",
        "MEM0_SEARCH": "⚠️ MANDATORY: Call mcp__mem0__map_tiered_search BEFORE Actor",
        "CONTEXT_LOADED": "Context ready → call research agent if 3+ files",
        "RESEARCH_DONE": "Research complete → call Actor agent",
        "ACTOR_CALL": "⚠️ MANDATORY: Launch Task(subagent_type='actor')",
        "ACTOR_COMPLETE": "Actor done → validate with Monitor agent",
        "MONITOR_VALIDATE": "⚠️ MANDATORY: Launch Task(subagent_type='monitor')",
        "MONITOR_PASSED": "Monitor approved → apply changes with Edit/Write",
        "PREDICTOR_ANALYZE": "Launch Task(subagent_type='predictor') for impact",
        "APPLY_CHANGES": "Apply Actor's changes using Edit/Write tools",
        "CHANGES_APPLIED": "Changes applied → run tests gate",
        "TESTS_PASSED": "Tests passed → run linter gate",
        "LINTER_PASSED": "Linter passed → proceed to self-audit",
        "VERIFY_ADHERENCE": "⚠️ MANDATORY: Output self-audit before marking complete",
        "SUBTASK_COMPLETE": "Subtask done → update plan, proceed to next",
    }

    return reminders.get(phase, "Execute current step as instructed")


def build_context_injection(state: Dict) -> str:
    """
    Build workflow context block to inject into system prompt.

    Args:
        state: Step state dictionary from step_state.json

    Returns:
        Context block string (~300 chars)
    """
    current_step = state.get("current_step_id", "UNKNOWN")
    phase = state.get("current_step_phase", "INITIALIZED")
    subtask_idx = state.get("subtask_index", 0)
    total_subtasks = len(state.get("subtask_sequence", []))
    completed = state.get("completed_steps", [])[-3:]  # Last 3 for brevity

    # Get step-specific reminder
    reminder = get_step_reminder(phase)

    # Build compact context block
    context = f"""
╔═══════════════════════════════════════════════════════════╗
║ MAP WORKFLOW CHECKPOINT                                   ║
╠═══════════════════════════════════════════════════════════╣
║ Current Step:  {current_step} - {phase}
║ Progress:      Subtask {subtask_idx + 1}/{total_subtasks}
║ Completed:     {', '.join(completed) if completed else 'none'}
║
║ ⚠️  MANDATORY NEXT ACTION:
║    {reminder}
╚═══════════════════════════════════════════════════════════╝
""".strip()

    # Enforce max length (truncate if needed, should rarely happen)
    if len(context) > MAX_CONTEXT_LENGTH:
        context = context[:MAX_CONTEXT_LENGTH] + "..."

    return context


def main():
    """Main hook entry point."""
    try:
        # Read tool call from stdin
        tool_call = json.load(sys.stdin)
        tool_name = tool_call.get("tool_name", "")

        # Get current branch
        branch = get_branch_name()

        # Load step state
        state = load_step_state(branch)

        # If no workflow active, don't inject context (allows normal work)
        if state is None:
            print(json.dumps({"allow": True}))
            sys.exit(0)

        # Build context injection
        context = build_context_injection(state)

        # Inject context via appended_text (added to system prompt)
        # Always allow tool to proceed (non-blocking)
        print(
            json.dumps({
                "allow": True,
                "appended_text": context
            })
        )
        sys.exit(0)

    except Exception as e:
        # On hook failure, allow tool (fail-open to avoid blocking work)
        print(json.dumps({"allow": True}))
        if os.environ.get("DEBUG_WORKFLOW_CONTEXT"):
            print(f"[workflow-context-injector] ERROR: {e}", file=sys.stderr)
        sys.exit(0)


if __name__ == "__main__":
    main()
