#!/usr/bin/env python3
"""workflow-context-injector.py

Workflow Context Injector - PreToolUse Hook (Tiered)

Injects a short MAP workflow reminder ONLY for significant operations:
- Edit/Write/MultiEdit: always inject
- Bash: inject for test/build/vcs commands
- Bash/Edit/Write: while a MAP worktree has unmerged git paths, inject the
  conflict-resolution discipline

Source of truth: .map/<branch>/step_state.json
(single state file used for enforcement gates and workflow context injection).

Trigger: Edit|Write|Bash
Exit codes: Always 0 (non-blocking, just adds context)
"""

import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from fnmatch import fnmatch
from pathlib import Path

# Keep in sync with map_step_runner.py GOAL_HEADING_RE
GOAL_HEADING_RE = r"## (?:Goal|Overview)\n(.*?)(?=\n##|\Z)"
REMINDER_LIMIT = 700
PERSONAL_BLOCK_BUDGET_TOTAL = 10000
PERSONAL_RULES_SEPARATOR = "\n\n"
CONFLICT_CONTEXT_LIMIT = 1200
CONFLICT_FILE_LIMIT = 8

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

# Step IDs that indicate the workflow has reached a terminal/completed state.
# When current_step_id or current_step_phase matches, format_reminder returns
# None (no active-phase reminder, and never the misleading "REQUIRED: Complete
# phase COMPLETE" banner issue #317 removed). For editing tools, main() then
# surfaces the short, low-pressure _TERMINAL_NOTICE instead of silence, so the
# agent recognizes completion and takes the clean exit (archive / review)
# rather than thrashing on a finished workflow.
_TERMINAL_STEP_IDS: frozenset[str] = frozenset({"COMPLETE"})

# Surfaced (once per turn, via the standard dedup) on an editing tool when the
# branch's workflow is terminal but the state file still lingers. Names the
# clean next steps and states plainly that completion is not an error — the
# opposite of the misleading active-pressure banner issue #317 removed. Must
# not contain "REQUIRED" or "Complete phase COMPLETE" (the #317 markers).
_TERMINAL_NOTICE = (
    "[MAP] This branch's MAP workflow is COMPLETE — editing is allowed and this "
    "is not an error to fix. For NEW work, retire the branch with "
    "`python3 .map/scripts/map_orchestrator.py archive` (the gate then "
    "fail-opens); to reopen the finished run for review fixes use `/map-review`. "
    "Do NOT edit .map/ state or the MAP runner/hooks to force it."
)

# Verification-class invocations: legitimate during ACTOR / TEST_WRITER for
# the agent to self-check before MONITOR. They count as "significant" so the
# base reminder still emits, but the closing "REQUIRED: Run Actor" pressure
# tag is suppressed — Actor verifying their own work shouldn't get nagged
# to re-enter the phase they're already in.
VERIFICATION_PATTERNS = [
    r"pytest(\s+|$)",
    r"ruff\s+check(?!\s+--fix)",
    r"ruff\s+format\s+--check",
    r"mypy(\s+|$)",
    r"pyright(\s+|$)",
    r"go\s+vet",
    r"go\s+build\b",
    r"cargo\s+check",
    r"tsc\s+--noEmit",
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
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            cwd=Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())),
            timeout=1,
            check=False,
        )
        if result.returncode == 0:
            return sanitize_branch_name(result.stdout.strip())
    except Exception:  # noqa: BLE001, S110 -- deliberate fallback/resilience boundary, must not propagate
        pass
    return "default"


def read_step_state(branch: str) -> tuple[dict | None, str | None]:
    """Load step state and return a non-throwing degradation reason on failure."""
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    state_file = project_dir / ".map" / branch / "step_state.json"

    if not state_file.exists():
        return (None, "missing step_state.json")

    try:
        with open(state_file, encoding="utf-8") as f:
            state = json.load(f)
        if isinstance(state, dict):
            return (state, None)
        return (None, "step_state.json is not an object")
    except json.JSONDecodeError:
        return (None, "invalid step_state.json")
    except (OSError, UnicodeDecodeError):
        return (None, "unreadable step_state.json")


def load_step_state(branch: str) -> dict | None:
    """Load step state from .map/<branch>/step_state.json."""
    state, _ = read_step_state(branch)
    return state


def step_state_path(branch: str) -> Path:
    """Return the branch step_state.json path."""
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    return project_dir / ".map" / branch / "step_state.json"


# Per-turn dedup: identical normalized reminder text emitted within
# DEDUP_WINDOW_SECONDS of the previous emission is squelched. We do
# NOT key on step_state.json mtime — record_hook_injection_status
# rewrites step_state on every hook call as part of accounting, so
# mtime always changes and would defeat dedup on its own side effect.
# Instead we rely on the fact that any meaningful workflow change
# (validate_step → new phase / subtask) produces different reminder
# text, which naturally lifts the squelch.
DEDUP_CACHE_NAME = ".hook-reminder-cache.json"
DEDUP_WINDOW_SECONDS = 5.0


def _dedup_cache_path(branch: str) -> Path:
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    return project_dir / ".map" / branch / DEDUP_CACHE_NAME


_REMINDER_TS_RE = re.compile(r" @ \d{2}:\d{2}:\d{2}\.\d{3}Z \(state [^)]+\)")


def _reminder_dedup_key(reminder: str) -> str:
    """Strip volatile timestamp/state-age fragments so the dedup key reflects
    semantic content only. format_reminder embeds `@ HH:MM:SS.mmmZ (state
    +X.Xs)` for lag diagnostics — without normalization every call has a
    different hash and dedup never fires.
    """
    return _REMINDER_TS_RE.sub("", reminder)


def _should_squelch_duplicate(branch: str, reminder: str) -> bool:
    """Return True if this reminder is a duplicate of the previous emission.

    Dedup axis is purely the NORMALIZED reminder text within a short wall
    clock window: when the workflow state changes (validate_step advances
    phases / subtasks), the reminder text changes automatically (different
    step_id / phase / progress) and the dedup naturally lifts. We do NOT
    look at step_state.json mtime — record_hook_injection_status writes
    the state file on every call as part of normal accounting, which
    would otherwise bust dedup on its own side effect.

    Any failure (no cache, different reminder, ancient timestamp, IO
    error) returns False so the reminder is emitted normally.
    """
    if not reminder:
        return False
    cache_file = _dedup_cache_path(branch)
    try:
        if not cache_file.is_file():
            return False
        cache = json.loads(cache_file.read_text(encoding="utf-8"))
        if not isinstance(cache, dict):
            return False
        last_hash = cache.get("reminder_hash")
        last_emit_ts = cache.get("emit_ts")
        if not isinstance(last_hash, str) or not isinstance(last_emit_ts, (int, float)):
            return False
        import hashlib  # local import; cheap on the silent path
        import time
        normalized = _reminder_dedup_key(reminder)
        current_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        if current_hash != last_hash:
            return False
        return not time.time() - last_emit_ts >= DEDUP_WINDOW_SECONDS
    except (OSError, json.JSONDecodeError):
        return False


def _write_dedup_cache(branch: str, reminder: str) -> None:
    """Persist last-emitted reminder hash for the next call."""
    cache_file = _dedup_cache_path(branch)
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        import hashlib
        import time
        normalized = _reminder_dedup_key(reminder)
        payload = {
            "reminder_hash": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
            "emit_ts": time.time(),
        }
        cache_file.write_text(
            json.dumps(payload, ensure_ascii=True), encoding="utf-8"
        )
    except OSError:
        # Best-effort: cache write must never block the hook.
        pass


def record_hook_injection_status(
    branch: str,
    state: dict,
    status: str,
    reason: str,
    tool_name: str,
    additional_context_chars: int = 0,
) -> None:
    """Best-effort status write; hook failures must never block tool execution."""
    path = step_state_path(branch)
    try:
        counts = state.get("hook_injection_counts")
        if not isinstance(counts, dict):
            counts = {}
        counts[status] = int(counts.get(status, 0) or 0) + 1
        state["hook_injection_counts"] = counts
        state["hook_injection"] = {
            "status": status,
            "reason": reason,
            "tool_name": tool_name,
            "additional_context_chars": additional_context_chars,
            "updated_at": datetime.now(UTC).isoformat().replace(
                "+00:00", "Z"
            ),
        }
        tmp_file = path.with_suffix(".tmp")
        tmp_file.write_text(
            json.dumps(state, indent=2, ensure_ascii=True), encoding="utf-8"
        )
        tmp_file.replace(path)
    except Exception:  # noqa: BLE001, S110 -- deliberate fallback/resilience boundary, must not propagate
        pass


def record_skip_if_state_available(branch: str, reason: str, tool_name: str) -> None:
    """Persist a skipped hook outcome only when existing state is safe to update."""
    state, _ = read_step_state(branch)
    if state is not None:
        record_hook_injection_status(branch, state, "skipped", reason, tool_name)


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


def is_verification_command(command: str) -> bool:
    """Return True when the bash command is an agent self-verification
    invocation (pytest, ruff check, mypy, pyright, go vet/build, ...).
    Used to suppress the "REQUIRED: Run Actor" pressure tag so Actor
    verifying their own work isn't nagged to re-enter the phase they're
    already in.
    """
    if not command:
        return False
    for pattern in VERIFICATION_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return True
    return False


def is_git_conflict_lifecycle_command(command: str) -> bool:
    """Return True for merge/rebase lifecycle commands that should not get
    a preflight conflict warning when the index is already clean.
    """
    return bool(
        re.search(
            r"\bgit\s+(?:merge\s+--(?:abort|quit|continue)|rebase\s+--(?:abort|quit|skip|continue))\b",
            command,
            re.IGNORECASE,
        )
    )


def is_git_conflict_prone_command(command: str) -> bool:
    """Return True when a Bash command is about to enter merge/rebase territory.

    This is advisory-only. Actual conflicted-file detection is driven by git's
    unmerged index state below.
    """
    if not command or is_git_conflict_lifecycle_command(command):
        return False
    return bool(re.search(r"\bgit\s+(?:merge|rebase)\b", command, re.IGNORECASE))


def get_unmerged_files(project_dir: Path) -> list[str]:
    """Return git paths with unmerged index entries, degrading to [] on error."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=U", "-z", "--"],
            cwd=project_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=False,
            timeout=2,
            check=False,
        )
    except Exception:  # noqa: BLE001 -- deliberate fallback/resilience boundary, must not propagate
        return []
    if result.returncode != 0 or not result.stdout:
        return []
    return [
        item.decode("utf-8", errors="replace")
        for item in result.stdout.split(b"\0")
        if item
    ]


def format_conflict_file_list(files: list[str]) -> str:
    shown = [_truncate_at_word(path, 80) for path in files[:CONFLICT_FILE_LIMIT]]
    suffix = ""
    if len(files) > CONFLICT_FILE_LIMIT:
        suffix = f", +{len(files) - CONFLICT_FILE_LIMIT} more"
    return ", ".join(shown) + suffix


def build_git_conflict_context(command: str, project_dir: Path) -> str:
    """Build a short conflict-resolution guardrail for conflicted MAP runs."""
    unmerged_files = get_unmerged_files(project_dir)
    command_trigger = is_git_conflict_prone_command(command)
    if not unmerged_files and not command_trigger:
        return ""

    if unmerged_files:
        heading = "[MAP-CONFLICT] Unmerged files: " + format_conflict_file_list(
            unmerged_files
        )
    else:
        heading = (
            "[MAP-CONFLICT] Merge/rebase preflight: if conflicts appear, use this discipline."
        )

    block = f"{heading}\n- Never blanket-accept ours/theirs for non-trivial files.\n- List conflicts: git diff --name-only --diff-filter=U.\n- Resolve one file or small batch at a time, preserving BOTH sides' intent.\n- After each batch: check markers, run the test gate, then stage only resolved files.\n- Continue merge/rebase only when no unmerged files remain.\n- Final check: branch current with origin/main, no conflict markers, tests green."
    if len(block) > CONFLICT_CONTEXT_LIMIT:
        return _truncate_at_word(block, CONFLICT_CONTEXT_LIMIT)
    return block


def state_string(state: dict, key: str, default: str = "") -> str:
    """Return a stripped state string without trusting persisted JSON field types."""
    value = state.get(key)
    if isinstance(value, str):
        return value.strip()
    return default


def required_action_for_step(step_id: str, step_phase: str) -> str | None:
    """Return a short required-next-action hint for common steps."""
    if step_id == "1.55":
        return "Approve plan (set_plan_approved true)"
    if step_id == "1.56":
        return "Choose mode (set_execution_mode step_by_step|batch)"
    if step_id == "2.2":
        return "Persist RESEARCH artifact (research-agent only for broad/high-risk discovery)"
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

    # Goal from task_plan.md — matches ## Goal or ## Overview headings
    plan_file = project_dir / ".map" / branch / f"task_plan_{branch}.md"
    try:
        if plan_file.exists():
            content = plan_file.read_text(encoding="utf-8")
            match = re.search(GOAL_HEADING_RE, content, re.DOTALL)
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


def _constraint_label(item: object) -> str | None:
    """Return a compact display label for a hard constraint entry."""
    if isinstance(item, str):
        return _truncate_at_word(" ".join(item.split()), 70)
    if not isinstance(item, dict):
        return None
    cid = item.get("id")
    desc = item.get("description")
    if isinstance(cid, str) and isinstance(desc, str):
        return _truncate_at_word(f"{cid}: {' '.join(desc.split())}", 70)
    if isinstance(cid, str):
        return _truncate_at_word(cid, 70)
    if isinstance(desc, str):
        return _truncate_at_word(" ".join(desc.split()), 70)
    return None


def _extract_coverage_tags(criteria: list[object]) -> list[str]:
    tags: list[str] = []
    for criterion in criteria:
        if not isinstance(criterion, str):
            continue
        for tag in re.findall(r"\[([A-Z]+-\d+)\]", criterion):
            if tag not in tags:
                tags.append(tag)
    return tags


def load_subtask_contract_hints(branch: str, subtask_id: str) -> tuple[str, str]:
    """Load compact hard-constraint and validation tag hints for edit-time reminders."""
    if not subtask_id or subtask_id == "-":
        return ("", "")

    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    blueprint_file = project_dir / ".map" / branch / "blueprint.json"
    try:
        bp = json.loads(blueprint_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return ("", "")
    if not isinstance(bp, dict):
        return ("", "")

    hard_hint = ""
    hard_constraints = bp.get("hard_constraints")
    if isinstance(hard_constraints, list):
        labels = [label for item in hard_constraints if (label := _constraint_label(item))]
        if labels:
            hard_hint = " | HC: " + "; ".join(labels[:3])

    tag_hint = ""
    subtasks = bp.get("subtasks")
    if isinstance(subtasks, list):
        for item in subtasks:
            if not isinstance(item, dict) or item.get("id") != subtask_id:
                continue
            criteria = item.get("validation_criteria")
            if isinstance(criteria, list):
                tags = _extract_coverage_tags(criteria)
                if tags:
                    tag_hint = " | VC: " + ", ".join(tags[:6])
            break

    return (hard_hint, tag_hint)


def _truncate_at_word(text: str, limit: int) -> str:
    """Truncate text at word boundary, appending '...' within limit."""
    if len(text) <= limit:
        return text
    cut = text[: limit - 3]
    # Find last space to avoid cutting mid-word
    last_space = cut.rfind(" ")
    if last_space > limit // 2:
        cut = cut[:last_space]
    return cut + "..."


def _state_is_terminal(state: dict) -> bool:
    """Return True iff step_state reflects a terminal/completed workflow.

    Honors the canonical ``workflow_status == "WORKFLOW_COMPLETE"`` flag in
    addition to the COMPLETE step_id/phase labels — the same terminal signal
    ``workflow-gate.py`` treats as permissive. Without the status check, a run
    whose completion set ``workflow_status`` but left a stale non-terminal phase
    would still be handed the active "REQUIRED: <phase>" reminder.
    """
    if not isinstance(state, dict):
        return False
    if state_string(state, "workflow_status").upper() == "WORKFLOW_COMPLETE":
        return True
    step_id = state_string(state, "current_step_id")
    step_phase = state_string(state, "current_step_phase")
    return step_id in _TERMINAL_STEP_IDS or step_phase in _TERMINAL_STEP_IDS


def format_reminder(
    state: dict, branch: str, *, suppress_required: bool = False
) -> str | None:
    """Format terse workflow reminder (aim: ≤700 chars).

    ``suppress_required`` drops the trailing ``| REQUIRED: ...`` pressure tag
    — used when the invoking command is a verification (pytest, ruff check,
    mypy, ...) so Actor running self-checks isn't told to "Run Actor".
    """
    if not state:
        return None

    step_id = state_string(state, "current_step_id")
    step_phase = state_string(state, "current_step_phase")

    # Suppress injection when the workflow is in a terminal/completed state.
    # A stale COMPLETE step_state.json on a branch (e.g. from a previous run)
    # must not surface misleading "REQUIRED: Complete phase COMPLETE" context.
    if _state_is_terminal(state):
        return None

    subtask_id = state_string(state, "current_subtask_id", "-") or "-"

    seq_value = state.get("subtask_sequence")
    seq = seq_value if isinstance(seq_value, list) else []
    idx = state.get("subtask_index")
    progress = "-"
    if isinstance(idx, int) and seq:
        progress = f"{min(idx + 1, len(seq))}/{len(seq)}"

    plan_ok = "y" if state.get("plan_approved") else "n"
    mode = state_string(state, "execution_mode") or "batch"

    # Wave progress display
    waves_value = state.get("execution_waves")
    waves = waves_value if isinstance(waves_value, list) else []
    wave_idx = state.get("current_wave_index", 0)
    wave_hint = ""
    if waves and isinstance(wave_idx, int):
        # Surface the WAVE banner when the wave-loop driver is ACTUALLY
        # in use. Previous "wave_idx > 0" check missed the very first
        # wave (wave 0 is the first wave by definition). Better signal:
        # subtask_phases is populated only by the wave-loop dispatcher
        # (get_wave_step writes per-subtask phase tracking there). So
        # if subtask_phases has any entries AND execution_waves is set,
        # the wave-loop is engaged — show the banner from wave 0 onward.
        subtask_phases_value = state.get("subtask_phases", {})
        subtask_phases_dict = subtask_phases_value if isinstance(subtask_phases_value, dict) else {}
        wave_loop_engaged = bool(subtask_phases_dict) or wave_idx > 0
        if wave_loop_engaged:
            wave_hint = f" | WAVE {wave_idx + 1}/{len(waves)}"
            current_wave = waves[wave_idx] if wave_idx < len(waves) else []
            if isinstance(current_wave, list) and len(current_wave) > 1:
                wave_hint += f" ({', '.join(str(item) for item in current_wave)})"
                mode = "batch:parallel"

    required = required_action_for_step(step_id, step_phase)

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
    files_changed_value = state.get("subtask_files_changed", {})
    files_changed = files_changed_value if isinstance(files_changed_value, dict) else {}
    if files_changed and subtask_id != "-":
        current_files = files_changed.get(subtask_id, [])
        if isinstance(current_files, list) and current_files:
            shown = current_files[:5]
            files_hint = " | Files: " + ", ".join(
                Path(f).name for f in shown if isinstance(f, str)
            )
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
    hard_hint, tag_hint = load_subtask_contract_hints(branch, subtask_id)

    authority_hint = " | Source>summary"
    # Lag diagnostics: emit hook wall-clock UTC and the age of step_state.json
    # (now - state mtime, seconds, 1 decimal). If the hook is reading stale
    # state, "state +Xs" jumps. Repros for "[MAP] still says ACTOR after I
    # validate_step'd to MONITOR" can be diffed by comparing the printed
    # state-age across consecutive reminders.
    from datetime import datetime as _dt
    now_utc = _dt.now(UTC)
    state_age_str = "?"
    try:
        state_file_age_src = (
            Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
            / ".map" / branch / "step_state.json"
        )
        if state_file_age_src.exists():
            mtime = _dt.fromtimestamp(state_file_age_src.stat().st_mtime, UTC)
            state_age_str = f"+{(now_utc - mtime).total_seconds():.1f}s"
    except OSError:
        pass
    ts_hint = f" @ {now_utc.strftime('%H:%M:%S.%f')[:-3]}Z (state {state_age_str})"
    base = f"[MAP]{ts_hint} {step_id} {step_phase}{goal_hint} | ST: {subtask_id}{title_hint} ({progress}) | plan:{plan_ok} mode:{mode}{wave_hint}{diag_hint}{files_hint}{hard_hint}{tag_hint}{authority_hint}"

    # Enforce limit: trim goal first, then constraint detail, then word-boundary truncate.
    if len(base) > REMINDER_LIMIT:
        goal_hint = ""
        base = f"[MAP]{ts_hint} {step_id} {step_phase} | ST: {subtask_id}{title_hint} ({progress}) | plan:{plan_ok} mode:{mode}{wave_hint}{diag_hint}{files_hint}{hard_hint}{tag_hint}{authority_hint}"
    if len(base) > REMINDER_LIMIT:
        hard_hint = ""
        base = f"[MAP]{ts_hint} {step_id} {step_phase} | ST: {subtask_id}{title_hint} ({progress}) | plan:{plan_ok} mode:{mode}{wave_hint}{diag_hint}{files_hint}{tag_hint}{authority_hint}"
    if len(base) > REMINDER_LIMIT:
        base = _truncate_at_word(base, REMINDER_LIMIT)

    if required and not suppress_required:
        result = f"{base} | REQUIRED: {required}"
        if len(result) > REMINDER_LIMIT:
            result = _truncate_at_word(result, REMINDER_LIMIT)
        return result
    return base


def _sanitize_fence_content(text: str) -> str:
    """Remove fence tag occurrences from user-supplied content.

    Strips case-insensitive literal ``<personal-rules`` and
    ``</personal-rules>`` so that a malicious or accidental occurrence
    inside a rules file cannot close the outer fence early (INV-6/E7).

    Postcondition: neither ``<personal-rules`` nor ``</personal-rules>``
    appears in the returned string (case-insensitive).
    """
    text = re.sub(r"(?i)</personal-rules>", "", text)
    text = re.sub(r"(?i)<personal-rules", "", text)
    return text


def _parse_rule_paths(content: str) -> list[str]:
    """Extract optional ``paths:`` frontmatter globs from a rule markdown file."""
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return []

    paths: list[str] = []
    in_paths = False
    for raw_line in lines[1:]:
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped == "---":
            break
        if stripped == "paths:":
            in_paths = True
            continue
        if not in_paths:
            continue
        if stripped.startswith("- "):
            candidate = stripped[2:].strip().strip("\"'")
            if candidate:
                paths.append(candidate)
            continue
        if stripped:
            in_paths = False
    return paths


def _paths_match_file(rule_paths: list[str], file_path: str) -> bool:
    """Return True when *file_path* matches at least one glob in *rule_paths*."""
    for pattern in rule_paths:
        if fnmatch(file_path, pattern) or fnmatch(f"./{file_path}", pattern):
            return True
    return False


def _extract_target_file(tool_name: str, tool_input: dict) -> str:
    """Extract the target file path from a tool invocation.

    For Edit/Write/MultiEdit, reads ``file_path`` directly.
    For Bash, returns empty — we cannot reliably determine which files
    a command operates on without parsing arbitrary shell syntax.
    """
    if tool_name in ("Edit", "Write", "MultiEdit"):
        file_path = tool_input.get("file_path", "")
        if isinstance(file_path, str) and file_path.strip():
            return file_path.strip()
    return ""


def _load_personal_rules(
    project_dir: Path, target_file: str = ""
) -> tuple[int, str]:
    """Load personal learned rules from ``.map/personal/rules/learned/``.

    Reads every ``*.md`` file under the directory in sorted order,
    sanitises each file's content through ``_sanitize_fence_content``,
    and returns a tuple of ``(count, joined_content)``.

    When *target_file* is non-empty, files with ``paths:`` frontmatter that
    do not match *target_file* are skipped — only unconditional rules and
    matching scoped rules are loaded.  When *target_file* is empty, all
    files are loaded (no filtering — we cannot determine relevance without
    a target).

    Returns ``(0, "")`` when the directory does not exist or contains
    no readable ``.md`` files.

    Invariants:
    - INV-1: read-only; never writes anything, never opens credential files.
    - HC-1: reads only ``*.md`` under the ``learned`` subdirectory.
    - Symlink-escape guard: any resolved path that escapes the base
      directory is silently skipped.
    """
    base = project_dir / ".map" / "personal" / "rules" / "learned"
    if not base.is_dir():
        return (0, "")

    base_resolved = base.resolve()
    sanitized_parts: list[str] = []

    for md_file in sorted(base.glob("*.md")):
        try:
            resolved = md_file.resolve()
            if not resolved.is_relative_to(base_resolved):
                continue
        except OSError:
            continue

        try:
            content = md_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        if target_file:
            rule_paths = _parse_rule_paths(content)
            if rule_paths and not _paths_match_file(rule_paths, target_file):
                continue

        sanitized_parts.append(_sanitize_fence_content(content))

    count = len(sanitized_parts)
    return (count, "\n".join(sanitized_parts))


def _build_personal_block(count: int, content: str, limit: int) -> str:
    """Assemble the ``<personal-rules>`` XML block for context injection.

    Returns ``""`` when *count* is zero or negative (HC-3).

    Otherwise assembles::

        <personal-rules>
        [personal-rules: N files]
        <content>
        </personal-rules>

    If the assembled string exceeds *limit*, the content is trimmed from
    the END and a ``[... trimmed]`` marker is inserted on its own line
    before the closing tag.  The opening line, banner, and closing tag
    are ALWAYS present (INV-4), even when content must be trimmed to
    empty.

    Raw bullet markdown in *content* is concatenated unchanged (SC-2).
    """
    if count <= 0:
        return ""

    opening = "<personal-rules>"
    banner = f"[personal-rules: {count} files]"
    closing = "</personal-rules>"

    assembled = opening + "\n" + banner + "\n" + content + "\n" + closing

    if len(assembled) <= limit:
        return assembled

    # Compute fixed overhead for the trimmed variant:
    #   opening\n  banner\n  trimmed_content\n  [... trimmed]\n  closing
    trim_marker = "[... trimmed]"
    overhead = (
        len(opening) + 1      # opening + \n
        + len(banner) + 1     # banner + \n
        + 1                   # \n before trim_marker
        + len(trim_marker) + 1  # trim_marker + \n
        + len(closing)        # closing (no trailing \n)
    )
    content_budget = max(0, limit - overhead)
    trimmed_content = content[:content_budget]
    result = (
        opening + "\n"
        + banner + "\n"
        + trimmed_content + "\n"
        + trim_marker + "\n"
        + closing
    )

    # Degenerate guard: if even the skeleton exceeds limit, emit it anyway
    # (correctness of the fence beats the cap in this edge case).
    return result


def main() -> None:
    if os.environ.get("MAP_INVOKED_BY"):
        sys.exit(0)
    branch = get_branch_name()
    try:
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError:
        record_skip_if_state_available(branch, "invalid hook input JSON", "unknown")
        print("{}")
        sys.exit(0)

    if not isinstance(input_data, dict):
        record_skip_if_state_available(branch, "hook input is not an object", "unknown")
        print("{}")
        sys.exit(0)

    tool_name_value = input_data.get("tool_name", "")
    tool_name = tool_name_value if isinstance(tool_name_value, str) else ""
    tool_input = input_data.get("tool_input", {})
    if not isinstance(tool_input, dict):
        tool_input = {}
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))

    # Determine if we should inject
    should_inject = False
    suppress_required = False
    skip_reason = ""
    command = ""
    conflict_context = ""

    if tool_name in ("Edit", "Write", "MultiEdit"):
        should_inject = True
    elif tool_name == "Bash":
        command_value = tool_input.get("command", "")
        if not isinstance(command_value, str):
            skip_reason = "bash command is not a string"
        else:
            command = command_value
            should_inject = should_inject_for_bash(command)
            if not should_inject:
                state_snapshot, _ = read_step_state(branch)
                if isinstance(state_snapshot, dict):
                    conflict_context = build_git_conflict_context(command, project_dir)
                    should_inject = bool(conflict_context)
            # Verification commands inject the base reminder but drop the
            # "REQUIRED: Run Actor" pressure tag — Actor running pytest on
            # their own work shouldn't be nagged to re-enter ACTOR.
            if should_inject and is_verification_command(command):
                suppress_required = True
            # Phase-aware smoke-test suppression: when current_step_phase
            # is ACTOR/MONITOR, every significant Bash command is some
            # form of self-check (build, smoke, lint, app boot). Pressing
            # "REQUIRED: Run Actor" on those is noise — Actor is already
            # in ACTOR. This covers smoke patterns the static
            # VERIFICATION_PATTERNS list misses (e.g., `python3 -m
            # sgr_code_review …` was tagged REQUIRED 31x in one session).
            if should_inject:
                state_snapshot, _ = read_step_state(branch)
                if isinstance(state_snapshot, dict):
                    phase_now = state_snapshot.get("current_step_phase")
                    if phase_now in ("ACTOR", "MONITOR", "TEST_WRITER"):
                        suppress_required = True

    if not should_inject:
        reason = skip_reason or "tool not configured for workflow injection"
        if tool_name == "Bash":
            reason = skip_reason or "bash command not significant"
        elif not tool_name:
            reason = "missing tool_name"
        record_skip_if_state_available(branch, reason, tool_name or "unknown")
        print("{}")
        sys.exit(0)

    # Load and format workflow step state
    state, _ = read_step_state(branch)

    if state is None:
        print("{}")
        sys.exit(0)

    if not conflict_context:
        conflict_context = build_git_conflict_context(command, project_dir)

    # Edits during a phase where editing is EXPECTED (ACTOR / TEST_WRITER)
    # don't need a trailing "REQUIRED: Run Actor" nag. The operator is
    # already doing exactly that — consecutive atomic Edits in the same
    # ACTOR turn shouldn't be lectured.
    if (
        tool_name in ("Edit", "Write", "MultiEdit")
        and isinstance(state, dict)
        and state.get("current_step_phase") in ("ACTOR", "TEST_WRITER")
    ):
        suppress_required = True
    reminder = format_reminder(state, branch, suppress_required=suppress_required)
    # Terminal/lingering workflow: format_reminder stays silent (no active
    # reminder, no misleading banner). For an editing tool, surface the clean
    # completion notice instead of nothing so the agent takes the archive /
    # review exit rather than trying to "fix" a finished workflow. Bash stays
    # silent — a verification run needs no completion nag.
    if (
        reminder is None
        and tool_name in ("Edit", "Write", "MultiEdit")
        and _state_is_terminal(state)
    ):
        reminder = _TERMINAL_NOTICE
    if reminder:
        context_parts = [reminder]
        if conflict_context:
            context_parts.append(conflict_context)
        base_context = PERSONAL_RULES_SEPARATOR.join(context_parts)
        target_file = _extract_target_file(tool_name, tool_input)
        personal_count, personal_content = _load_personal_rules(project_dir, target_file)
        personal_limit = max(
            0,
            PERSONAL_BLOCK_BUDGET_TOTAL - len(base_context) - len(PERSONAL_RULES_SEPARATOR),
        )
        personal_block = _build_personal_block(personal_count, personal_content, personal_limit)
        assembled = (
            base_context
            if not personal_block
            else base_context + PERSONAL_RULES_SEPARATOR + personal_block
        )
        assert len(assembled) <= PERSONAL_BLOCK_BUDGET_TOTAL
        # Per-turn dedup: same reminder + same state_mtime within 5s = same
        # turn; squelch to avoid the [MAP] banner repeating across every
        # Edit/Write/Bash invocation in a single agent burst.
        if _should_squelch_duplicate(branch, assembled):
            record_hook_injection_status(
                branch, state, "deduped", "duplicate reminder squelched", tool_name
            )
            print("{}")
            sys.exit(0)
        _write_dedup_cache(branch, assembled)
        record_hook_injection_status(
            branch, state, "injected", "reminder emitted", tool_name, len(assembled)
        )
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": assembled,
            }
        }
        print(json.dumps(output))
    else:
        record_hook_injection_status(
            branch, state, "skipped", "no reminder formatted", tool_name
        )
        print("{}")

    sys.exit(0)


if __name__ == "__main__":
    main()
