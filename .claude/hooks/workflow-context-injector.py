#!/usr/bin/env python3
"""workflow-context-injector.py

Workflow Context Injector - PreToolUse Hook (Tiered)

Injects a short MAP workflow reminder ONLY for significant operations:
- Edit/Write/MultiEdit: always inject
- Bash: inject for test/build/vcs commands

Source of truth: .map/<branch>/step_state.json
(single state file used for enforcement gates and workflow context injection).

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
    "ls",
    "cat",
    "head",
    "tail",
    "grep",
    "rg",
    "find",
    "pwd",
    "echo",
    "wc",
    "diff",
    "tree",
    "file",
    "which",
    "type",
    "env",
    "printenv",
    "date",
    "whoami",
    "id",
    "uname",
    "less",
    "more",
    "stat",
    "du",
    "df",
    "free",
}

# Bash commands that ARE significant and need reminders
SIGNIFICANT_PATTERNS = [
    r"pytest",
    r"go\s+test",
    r"npm\s+test",
    r"cargo\s+test",
    r"make\s+test",
    r"git\s+commit",
    r"git\s+push",
    r"git\s+merge",
    r"git\s+rebase",
    r"npm\s+install",
    r"pip\s+install",
    r"go\s+mod",
    r"make\b",
    r"docker\b",
    r"kubectl\b",
    r"\brm\s",
    r"\bmv\s",
    r"\bcp\s+-r",
]


def sanitize_branch_name(branch: str) -> str:
    """Sanitize branch name for safe filesystem paths."""
    sanitized = branch.replace("/", "-")
    sanitized = re.sub(r"[^a-zA-Z0-9_.-]", "-", sanitized)
    sanitized = re.sub(r"-+", "-", sanitized).strip("-")
    if ".." in sanitized or sanitized.startswith("."):
        return "default"
    return sanitized or "default"


def get_branch_name() -> str:
    """Get current git branch name."""
    import subprocess

    try:
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


def load_step_state(branch: str) -> dict | None:
    """Load step state from .map/<branch>/step_state.json."""
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    state_file = project_dir / ".map" / branch / "step_state.json"

    if not state_file.exists():
        return None

    try:
        with open(state_file, encoding="utf-8") as f:
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

    # Default: don't inject for unknown commands
    return False


def required_action_for_step(step_id: str, step_phase: str, state: dict) -> str | None:
    """Return a short required-next-action hint for common steps."""
    if step_id == "1.55":
        return "Approve plan (set_plan_approved true)"
    if step_id == "1.56":
        return "Choose mode (set_execution_mode step_by_step|batch)"
    if step_id == "2.2":
        return "Run research-agent (conditional: 3+ existing files or high risk)"
    if step_id == "2.3":
        return "Run Actor"
    if step_id == "2.4":
        return "Run Monitor"

    # Fallback for unknown step ids
    if step_phase:
        return f"Complete phase {step_phase}"
    return None


def load_goal_and_title(branch: str, subtask_id: str) -> tuple[str, str]:
    """Load goal from task_plan and subtask title from blueprint.

    Returns (truncated_goal, subtask_title) or ("", "") on any error.
    Fast: single json.load + single regex — target <20ms.
    """
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    goal = ""
    title = ""

    # Goal from task_plan.md (regex pattern from map_step_runner.read_current_goal)
    plan_file = project_dir / ".map" / branch / f"task_plan_{branch}.md"
    try:
        if plan_file.exists():
            content = plan_file.read_text(encoding="utf-8")
            match = re.search(
                r"## (?:Goal|Overview)\n(.*?)(?=\n##|\Z)", content, re.DOTALL
            )
            if match:
                goal = match.group(1).strip()
                # Truncate to first sentence
                if ". " in goal:
                    goal = goal[: goal.index(". ") + 1]
                if len(goal) > 80:
                    goal = goal[:77] + "..."
    except OSError:
        pass

    # Title from blueprint.json
    blueprint_file = project_dir / ".map" / branch / "blueprint.json"
    try:
        if blueprint_file.exists():
            bp = json.loads(blueprint_file.read_text(encoding="utf-8"))
            for st in bp.get("subtasks", []):
                if st.get("id") == subtask_id:
                    title = st.get("title", "")
                    break
    except (json.JSONDecodeError, OSError):
        pass

    return (goal, title)


def format_reminder(state: dict, branch: str) -> str | None:
    """Format terse workflow reminder (aim: ≤500 chars)."""
    if not state:
        return None

    step_id = (state.get("current_step_id") or "").strip()
    step_phase = (state.get("current_step_phase") or "").strip()
    subtask_id = (state.get("current_subtask_id") or "-").strip() or "-"

    seq = state.get("subtask_sequence") or []
    idx = state.get("subtask_index")
    progress = "-"
    if isinstance(idx, int) and seq:
        progress = f"{min(idx + 1, len(seq))}/{len(seq)}"

    plan_ok = "y" if state.get("plan_approved") else "n"
    mode = (state.get("execution_mode") or "").strip() or "batch"

    # Wave progress display
    waves = state.get("execution_waves") or []
    wave_idx = state.get("current_wave_index", 0)
    wave_hint = ""
    if waves:
        wave_hint = f" | WAVE {wave_idx + 1}/{len(waves)}"
        current_wave = waves[wave_idx] if wave_idx < len(waves) else []
        if len(current_wave) > 1:
            wave_hint += f" ({', '.join(current_wave)})"
            mode = "batch:parallel"

    required = required_action_for_step(step_id, step_phase, state)

    diag_hint = ""
    diag_file = (
        Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
        / ".map"
        / branch
        / "diagnostics.json"
    )
    if diag_file.exists():
        diag_hint = " | Diag: diagnostics.json"

    # Show recently changed files for context freshness
    files_hint = ""
    files_changed = state.get("subtask_files_changed", {})
    if files_changed and subtask_id != "-":
        current_files = files_changed.get(subtask_id, [])
        if current_files:
            shown = current_files[:5]
            files_hint = " | Files: " + ", ".join(Path(f).name for f in shown)
            if len(current_files) > 5:
                files_hint += f" +{len(current_files) - 5}"

    if not step_id and not step_phase:
        return None

    # Context-aware: add goal and subtask title
    goal_hint = ""
    title_hint = ""
    if subtask_id != "-":
        goal, title = load_goal_and_title(branch, subtask_id)
        if goal:
            goal_hint = f" | Goal: {goal}"
        if title:
            title_hint = f" {title}"

    base = f"[MAP] {step_id} {step_phase}{goal_hint} | ST: {subtask_id}{title_hint} ({progress}) | plan:{plan_ok} mode:{mode}{wave_hint}{diag_hint}{files_hint}"

    # Enforce 500-char limit: trim goal first, then hard-truncate
    if len(base) > 500:
        goal_hint = ""
        base = f"[MAP] {step_id} {step_phase} | ST: {subtask_id}{title_hint} ({progress}) | plan:{plan_ok} mode:{mode}{wave_hint}{diag_hint}{files_hint}"
    if len(base) > 500:
        base = base[:497] + "..."

    if required:
        result = f"{base} | REQUIRED: {required}"
        return result[:500] if len(result) > 500 else result
    return base


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

    # Load and format workflow step state
    branch = get_branch_name()
    state = load_step_state(branch)

    if not state:
        print("{}")
        sys.exit(0)

    reminder = format_reminder(state, branch)
    if reminder:
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": reminder,
            }
        }
        print(json.dumps(output))
    else:
        print("{}")

    sys.exit(0)


if __name__ == "__main__":
    main()
