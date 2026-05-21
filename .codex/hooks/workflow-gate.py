#!/usr/bin/env python3
"""
MAP Workflow Enforcement Gate (PreToolUse Hook)

Provider-agnostic: works with both Claude Code and Codex CLI.

Blocks Edit/Write/MultiEdit outside of Actor-related phases.
Uses step_state.json (orchestrator canonical state) as single source of truth.

ENFORCEMENT:
  - Edit allowed during phases: ACTOR, APPLY, TEST_WRITER
  - Edit blocked during all other phases (DECOMPOSE, MONITOR, PREDICTOR, etc.)
  - Fail-open: missing or unreadable step_state.json → allow
  - Always allows: .map/ artifacts, non-editing tools

CONSTRAINTS (from step_state.json):
  - scope_glob: restrict edits to matching file patterns

Exit code 0 always (fail-open on errors).
"""
import json
import os
import re
import sys
from fnmatch import fnmatch
from pathlib import Path
from typing import Optional

EDITING_TOOLS = {"Edit", "Write", "MultiEdit"}
PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())).resolve()

# Phases where Edit/Write is expected (Actor applies code)
EDITING_PHASES = {"ACTOR", "APPLY", "TEST_WRITER"}

# TERMINAL_PHASES contains phases where the workflow is considered closed.
# Edits during COMPLETE are intentionally permissive because:
#   1. Post-workflow polish (doc tweaks, follow-up review fixes) must not be gated —
#      blocking them would force users to flip the workflow state back to ACTOR for every
#      tiny edit after merge readiness.
#   2. The orchestrator (``.map/scripts/map_orchestrator.py:mark_workflow_complete``)
#      is the sole authorised writer of ``current_step_phase=COMPLETE`` /
#      ``workflow_status=WORKFLOW_COMPLETE``. The atomic-completion invariant guarantees
#      that COMPLETE is set only when ``pending_steps`` is empty.
#
# TRUST BOUNDARY: any code path that sets ``current_step_phase=COMPLETE`` outside
# ``mark_workflow_complete`` (or its sanctioned equivalents) silently widens this gate
# for every editing tool. Treat any ad-hoc mutation of ``current_step_phase`` (jq, manual
# JSON edit, third-party tool) as a security regression on this gate.
TERMINAL_PHASES = {"COMPLETE"}  # Workflow closed — gate is permissive.
ALLOWED_PHASES = EDITING_PHASES | TERMINAL_PHASES

# Map step IDs (used in subtask_phases parallel dict) to phase names
STEP_ID_TO_PHASE = {
    "1.0": "DECOMPOSE",
    "1.5": "INIT_PLAN",
    "1.55": "REVIEW_PLAN",
    "1.56": "CHOOSE_MODE",
    "1.6": "INIT_STATE",
    "2.2": "RESEARCH",
    "2.25": "TEST_WRITER",
    "2.26": "TEST_FAIL_GATE",
    "2.3": "ACTOR",
    "2.4": "MONITOR",
}


def extract_target_file_paths(tool_call: dict) -> list[str]:
    """Extract file paths from tool call payload."""
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
            if isinstance(edit, dict):
                fp = edit.get("file_path")
                if isinstance(fp, str) and fp.strip():
                    paths.append(fp)

    return paths


def is_exempt_path(file_path: str) -> bool:
    """Return True if path is exempt from enforcement (.map/, .claude/rules/learned/, ~/.claude/projects/*/memory/)."""
    if not isinstance(file_path, str) or not file_path.strip():
        return False

    candidate = Path(file_path)
    resolved = (
        candidate.resolve(strict=False)
        if candidate.is_absolute()
        else (PROJECT_DIR / candidate).resolve(strict=False)
    )

    # Allow ~/.claude/projects/*/memory/
    claude_memory_dir = Path.home() / ".claude" / "projects"
    try:
        rel = resolved.relative_to(claude_memory_dir.resolve())
        if "memory" in rel.parts:
            return True
    except ValueError:
        pass

    # Allow .map/ and .claude/rules/learned/ (MAP-generated artifacts)
    try:
        rel = resolved.relative_to(PROJECT_DIR)
    except ValueError:
        return False

    parts = rel.parts
    if not parts:
        return False
    if parts[0] == ".map":
        return True
    # POLICY: ``.claude/rules/learned/`` is the destination for MAP-generated learned
    # rules written by ``/map-learn``. The exemption is restricted to ``*.md`` files to
    # prevent the directory from quietly broadening into a general bypass for arbitrary
    # file types (executables, configs, secrets-bearing JSON, etc.).
    if (
        len(parts) >= 4
        and parts[:3] == (".claude", "rules", "learned")
        and parts[-1].endswith(".md")
    ):
        return True
    return False


def sanitize_branch_name(branch: str) -> str:
    """Sanitize branch name for filesystem paths."""
    sanitized = branch.replace("/", "-")
    sanitized = re.sub(r"[^a-zA-Z0-9_.-]", "-", sanitized)
    sanitized = re.sub(r"-+", "-", sanitized).strip("-")
    if ".." in sanitized or sanitized.startswith("."):
        return "default"
    return sanitized or "default"


def get_branch_name() -> str:
    """Get current git branch name (sanitized)."""
    try:
        import subprocess

        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            cwd=PROJECT_DIR,
            timeout=1,
        )
        if result.returncode == 0:
            return sanitize_branch_name(result.stdout.strip())
    except Exception:
        pass
    return "default"


def is_editing_phase(branch: str) -> tuple[bool, Optional[str]]:
    """Check step_state.json: is current phase one where Edit is allowed?

    Returns (allowed, error_message).
    """
    step_file = PROJECT_DIR / ".map" / branch / "step_state.json"
    if not step_file.exists():
        return True, None  # No step state → fail-open

    try:
        with open(step_file, "r", encoding="utf-8") as f:
            state = json.load(f)
    except (json.JSONDecodeError, OSError):
        return True, None  # Corrupt/unreadable → fail-open

    # Parallel wave mode: check subtask_phases dict
    # Values are step IDs (e.g. "2.3") — translate to phase names before comparing
    subtask_phases = state.get("subtask_phases", {})
    if subtask_phases:
        for step_id in subtask_phases.values():
            phase = STEP_ID_TO_PHASE.get(step_id, step_id)
            if phase in ALLOWED_PHASES:
                return True, None

    # Sequential mode: check current_step_phase
    current_phase = state.get("current_step_phase", "")
    if current_phase in ALLOWED_PHASES:
        return True, None

    # Not in an editing phase → block
    subtask = state.get("current_subtask_id", "?")
    return False, (
        f"Workflow gate: Edit blocked during phase '{current_phase}' "
        f"(subtask {subtask}).\n"
        f"Edit is only allowed during: {', '.join(sorted(EDITING_PHASES))}.\n"
        "Call the Actor agent first — it will apply code changes."
    )


def check_constraints(branch: str, target_paths: list[str]) -> Optional[str]:
    """Check constraints from step_state.json. Returns error or None."""
    state_file = PROJECT_DIR / ".map" / branch / "step_state.json"
    if not state_file.exists():
        return None

    try:
        with open(state_file, "r", encoding="utf-8") as f:
            state = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    constraints = state.get("constraints")
    if not constraints:
        return None

    # scope_glob
    scope_glob = constraints.get("scope_glob")
    if scope_glob and "{" in scope_glob:
        print(
            f"[workflow-gate] WARNING: scope_glob contains '{{' which fnmatch treats as literal. "
            f"Brace expansion is not supported. Ignoring scope_glob='{scope_glob}'.",
            file=sys.stderr,
        )
        scope_glob = None
    if scope_glob and target_paths:
        repo_root = PROJECT_DIR
        for tp in target_paths:
            candidate = Path(tp)
            resolved = (
                candidate.resolve(strict=False)
                if candidate.is_absolute()
                else (repo_root / candidate).resolve(strict=False)
            )
            try:
                rel = str(resolved.relative_to(repo_root))
            except ValueError:
                return (
                    f"Constraint: scope_glob='{scope_glob}'\n"
                    f"File '{resolved}' resolves outside repository root."
                )
            if not fnmatch(rel, scope_glob):
                return (
                    f"Constraint: scope_glob='{scope_glob}'\n"
                    f"File '{rel}' is outside allowed scope."
                )

    return None


def deny(reason: str) -> None:
    """Print deny response and exit."""
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
    )
    sys.exit(0)


def allow() -> None:
    """Print allow response and exit."""
    print("{}")
    sys.exit(0)


def main() -> None:
    try:
        tool_call = json.load(sys.stdin)
        tool_name = tool_call.get("tool_name", "")

        # Non-editing tools → always allow
        if tool_name not in EDITING_TOOLS:
            allow()

        # Exempt paths (.map/, ~/.claude/memory/) → always allow
        target_paths = extract_target_file_paths(tool_call)
        if target_paths and all(is_exempt_path(p) for p in target_paths):
            allow()

        branch = get_branch_name()

        # Phase check (step_state.json)
        allowed, error = is_editing_phase(branch)
        if not allowed:
            deny(error or "Edit blocked: not in an editing phase.")

        # Constraint check (step_state.json)
        constraint_error = check_constraints(branch, target_paths)
        if constraint_error:
            deny(constraint_error)

        allow()

    except Exception as e:
        # Fail-open on any error
        if os.environ.get("DEBUG_WORKFLOW_GATE"):
            print(f"[workflow-gate] ERROR: {e}", file=sys.stderr)
        print("{}")
        sys.exit(0)


if __name__ == "__main__":
    main()
