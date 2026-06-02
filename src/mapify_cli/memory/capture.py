"""Per-turn scratch WAL append for the MAP Framework memory subsystem.

This module is the LLM-free hot-path capture (INV-1).  It is called from
hook shims (ST-006) on every Stop event and writes exactly one JSONL line
per turn to .map/<branch>/sessions/scratch/<session-id>.jsonl.

NO network/LLM calls, NO subprocess calls on the hot path.
Branch is resolved by reading git refs directly (no subprocess).

Best-effort contract: append_turn and append_end_marker swallow ALL
exceptions and no-op silently — a hook must never block Claude.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mapify_cli.memory.digest_schema import (
    EVENT_ENDED,
    EVENT_TURN,
    SCRATCH_ENDED_FIELDS,
    SCRATCH_TURN_FIELDS,
    redact_secret_path,
    sanitize_value,
)

# ---------------------------------------------------------------------------
# Branch resolution (subprocess-free)
# ---------------------------------------------------------------------------

_BRANCH_SANITIZE_RE = re.compile(r"[^a-zA-Z0-9_.-]")
_COLLAPSE_DASH_RE = re.compile(r"-+")


def _sanitize_branch(name: str) -> str:
    """Sanitize *name* for filesystem use (same regex as ralph-iteration-logger).

    Replaces every character not in [a-zA-Z0-9_.-] with '-', collapses
    consecutive '-', strips leading/trailing '-'.  Falls back to "default"
    on empty result or path-traversal indicators.
    """
    sanitized = _BRANCH_SANITIZE_RE.sub("-", name)
    sanitized = _COLLAPSE_DASH_RE.sub("-", sanitized)
    sanitized = sanitized.strip("-")
    if not sanitized or ".." in sanitized or sanitized.startswith("."):
        return "default"
    return sanitized


def _resolve_branch(project_dir: Path) -> str:
    """Resolve the current git branch by reading .git refs directly.

    Handles both normal clones (.git is a directory) and git worktrees
    (.git is a file containing "gitdir: <abs-path>").  Falls back to
    "default" on any error so the hot path is never blocked.
    """
    git = project_dir / ".git"
    try:
        if git.is_file():
            # Worktree: .git file contains "gitdir: /abs/path/to/.git/worktrees/<name>"
            content = git.read_text(encoding="utf-8", errors="replace")
            raw_path = content.split("gitdir:", 1)[1].strip()
            gitdir = Path(raw_path)
            head = (gitdir / "HEAD").read_text(encoding="utf-8", errors="replace")
        else:
            head = (git / "HEAD").read_text(encoding="utf-8", errors="replace")

        if head.startswith("ref:"):
            ref = head.split("ref:", 1)[1].strip()  # refs/heads/<branch>
            # Strip the refs/heads/ prefix so that nested branches like
            # "feat/my-feature" are preserved whole, then sanitize the
            # full remainder (/ -> -).
            if ref.startswith("refs/heads/"):
                branch = ref[len("refs/heads/"):]
            elif "refs/heads/" in ref:
                branch = ref.split("refs/heads/", 1)[1]
            else:
                branch = ref.rsplit("/", 1)[-1]
        else:
            # Detached HEAD — use a short SHA
            branch = head.strip()[:12]

        return _sanitize_branch(branch)
    except Exception:  # noqa: BLE001
        return "default"


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _scratch_dir(project_dir: Path) -> Path:
    """Return .map/<branch>/sessions/scratch/ for the given project directory."""
    branch = _resolve_branch(project_dir)
    return project_dir / ".map" / branch / "sessions" / "scratch"


def _pointer_file(project_dir: Path) -> Path:
    return _scratch_dir(project_dir) / "current-session"


def _step_state_file(project_dir: Path) -> Path:
    branch = _resolve_branch(project_dir)
    return project_dir / ".map" / branch / "step_state.json"


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------


def resolve_session_id(
    stdin_data: dict[str, Any], project_dir: Path | str
) -> str | None:
    """Resolve the active session ID using two fallback sources.

    Resolution order (HC-1 — NO SessionEnd/PreCompact dependency):
      1. stdin_data.get("session_id")
      2. Read .map/<branch>/sessions/scratch/current-session (single line)
      3. None

    Args:
        stdin_data: Parsed hook stdin payload (may be empty dict).
        project_dir: Root directory of the target project.

    Returns:
        Session ID string, or None when no session can be determined.
    """
    project_dir = Path(project_dir)

    # 1. Hook stdin is the preferred source.
    sid = stdin_data.get("session_id")
    if sid and isinstance(sid, str):
        return sanitize_value(sid.strip())

    # 2. Persistent pointer written by a previous turn.
    pointer = _pointer_file(project_dir)
    try:
        text = pointer.read_text(encoding="utf-8", errors="replace").strip()
        if text:
            return sanitize_value(text)
    except OSError:
        pass

    return None


def write_current_session(session_id: str, project_dir: Path) -> None:
    """Idempotently write *session_id* to the current-session pointer file.

    Creates parent directories as needed.

    Args:
        session_id: The session ID to record.
        project_dir: Root directory of the target project.
    """
    pointer = _pointer_file(project_dir)
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(session_id, encoding="utf-8")


# ---------------------------------------------------------------------------
# Turn-count helper
# ---------------------------------------------------------------------------


def _count_existing_turns(scratch_path: Path) -> int:
    """Count non-blank lines in *scratch_path* (INV-6 resilience).

    A truncated trailing line is treated as non-blank so the count is
    at-least-conservative; the real guarantee is that we do not crash.
    Returns 0 when the file does not exist.
    """
    if not scratch_path.exists():
        return 0
    try:
        count = 0
        with open(scratch_path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.strip():
                    count += 1
        return count
    except OSError:
        return 0


# ---------------------------------------------------------------------------
# Field derivation
# ---------------------------------------------------------------------------


def _derive_files_touched(stdin_data: dict[str, Any]) -> list[str]:
    """Extract file paths from tool_input for Edit / Write / MultiEdit tools.

    Each path is passed through redact_secret_path() then sanitize_value().
    Returns an empty list for all other tools or when tool_input is absent.
    """
    tool_name: str = stdin_data.get("tool_name", "") or ""
    if tool_name not in {"Edit", "Write", "MultiEdit"}:
        return []

    tool_input: dict[str, Any] = stdin_data.get("tool_input") or {}
    raw_path: str = tool_input.get("file_path", "") or tool_input.get("path", "") or ""
    if not raw_path:
        return []

    redacted = redact_secret_path(str(raw_path))
    sanitized = sanitize_value(redacted)
    return [sanitized]


def _derive_prompt_ref(project_dir: Path) -> str | None:
    """Read the active subtask ID from step_state.json, or return None."""
    state_file = _step_state_file(project_dir)
    try:
        if not state_file.exists():
            return None
        data = json.loads(state_file.read_text(encoding="utf-8", errors="replace"))
        val = data.get("current_subtask_id")
        if val and isinstance(val, str):
            return sanitize_value(val.strip()) or None
        return None
    except (OSError, json.JSONDecodeError):
        return None


def _ts() -> str:
    """Return a timezone-aware UTC ISO timestamp."""
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def append_turn(stdin_data: dict[str, Any], project_dir: Path | str) -> None:
    """Append one LLM-free JSONL turn record to the scratch WAL.

    Builds record with fields from SCRATCH_TURN_FIELDS:
      {ts, turn, session_id, files_touched, prompt_ref, event=EVENT_TURN}

    Also updates the current-session pointer (VC4).
    Best-effort: all exceptions are swallowed silently.

    Args:
        stdin_data: Parsed Stop hook stdin payload.
        project_dir: Root directory of the target project (Path or str).
    """
    try:
        project_dir = Path(project_dir)
        sid = resolve_session_id(stdin_data, project_dir)

        scratch_dir = _scratch_dir(project_dir)
        scratch_dir.mkdir(parents=True, exist_ok=True)

        # Determine the scratch file path (even when sid is None we still write,
        # using "unknown" as a fallback so data is not lost).
        effective_sid = sid or "unknown"
        scratch_path = scratch_dir / f"{effective_sid}.jsonl"

        turn_number = _count_existing_turns(scratch_path) + 1

        # Build the record using field names from SCRATCH_TURN_FIELDS.
        # All string values are sanitize_value()'d to strip control chars.
        record: dict[str, Any] = {
            SCRATCH_TURN_FIELDS[0]: _ts(),                         # ts
            SCRATCH_TURN_FIELDS[1]: turn_number,                   # turn
            SCRATCH_TURN_FIELDS[2]: sanitize_value(effective_sid), # session_id
            SCRATCH_TURN_FIELDS[3]: _derive_files_touched(stdin_data),  # files_touched
            SCRATCH_TURN_FIELDS[4]: _derive_prompt_ref(project_dir),    # prompt_ref
            SCRATCH_TURN_FIELDS[5]: EVENT_TURN,                    # event
        }

        with open(scratch_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=True) + "\n")

        # VC4: update the current-session pointer after a successful write.
        if sid:
            write_current_session(sid, project_dir)

    except Exception:  # noqa: BLE001
        # Best-effort: never block the hook.
        pass


def append_end_marker(stdin_data: dict[str, Any], project_dir: Path | str) -> None:
    """Append an 'ended' marker to the scratch WAL for this session.

    Record shape: {event: EVENT_ENDED, ts, session_id} (SCRATCH_ENDED_FIELDS).
    Also updates the current-session pointer to the incoming sid (VC4).
    Best-effort: all exceptions are swallowed silently.

    Reused by the SessionEnd shim in ST-005.

    Args:
        stdin_data: Parsed SessionEnd hook stdin payload.
        project_dir: Root directory of the target project (Path or str).
    """
    try:
        project_dir = Path(project_dir)
        sid = resolve_session_id(stdin_data, project_dir)
        effective_sid = sid or "unknown"

        scratch_dir = _scratch_dir(project_dir)
        scratch_dir.mkdir(parents=True, exist_ok=True)
        scratch_path = scratch_dir / f"{effective_sid}.jsonl"

        record: dict[str, Any] = {
            SCRATCH_ENDED_FIELDS[0]: EVENT_ENDED,                      # event
            SCRATCH_ENDED_FIELDS[1]: _ts(),                            # ts
            SCRATCH_ENDED_FIELDS[2]: sanitize_value(effective_sid),    # session_id
        }

        with open(scratch_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=True) + "\n")

        # VC4: update the current-session pointer.
        if sid:
            write_current_session(sid, project_dir)

    except Exception:  # noqa: BLE001
        # Best-effort: never block the hook.
        pass
