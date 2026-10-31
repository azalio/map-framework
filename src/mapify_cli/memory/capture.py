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

import functools
import hashlib
import json
import logging
import os
import re
from datetime import UTC, datetime
from itertools import chain
from pathlib import Path
from typing import Any

from mapify_cli.memory.digest_schema import (
    CAPTURE_EVENT_BYTES,
    EVENT_CAPTURE_TRUNCATED,
    EVENT_ENDED,
    EVENT_TURN,
    EVENT_USER_PROMPT,
    PROMPT_PREFIX_CHARS,
    SCRATCH_ENDED_FIELDS,
    SCRATCH_TURN_FIELDS,
    bounded_text,
    redact_secret_path,
    sanitize_value,
)
from mapify_cli.memory.evidence import native_tool_events
from mapify_cli.ralph_state import sanitize_branch_name

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Branch resolution (subprocess-free)
# ---------------------------------------------------------------------------


def _sanitize_branch(name: str) -> str:
    """Sanitize *name* for filesystem use.

    Delegates to the shared ``mapify_cli.ralph_state.sanitize_branch_name`` so
    the branch->path mapping has a single authority and cannot drift from the
    rest of MAP (a path-traversal hardening applied there is inherited here).
    Behaviour: replaces every character not in [a-zA-Z0-9_.-] with '-',
    collapses consecutive '-', strips leading/trailing '-', and falls back to
    "default" on empty input or path-traversal indicators. Non-empty names
    stripped entirely by normalization use a deterministic SHA-256 scope.
    """
    return sanitize_branch_name(name)


@functools.lru_cache(maxsize=128)
def _resolve_branch(project_dir: Path) -> str:
    """Resolve the current git branch by reading .git refs directly.

    Handles both normal clones (.git is a directory) and git worktrees
    (.git is a file containing "gitdir: <abs-path>").  Falls back to
    "default" on any error so the hot path is never blocked.

    Result is memoised per *project_dir*: a hook is a short-lived one-shot
    process whose branch cannot change mid-run, and append_turn resolves the
    branch 3-4× (pointer, scratch dir, step-state, pointer write).  The cache
    collapses those to a single .git/HEAD read.  (Tests that mutate HEAD for the
    same path within one process call _resolve_branch.cache_clear().)
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


def _fallback_sid(stdin_data: dict[str, Any]) -> str:
    """Derive a stable per-session id when no session_id/pointer is available.

    Collapsing every unidentifiable session into one shared ``unknown.jsonl``
    lets finalize merge unrelated sessions into a single digest and cross-
    contaminate turn numbers.  The transcript path is unique per session and
    usually present on Stop events, so its filesystem stem is a far better
    fallback identity.  Falls back to ``"unknown"`` only when there is genuinely
    nothing to key on.
    """
    transcript = stdin_data.get("transcript_path")
    if transcript:
        stem = Path(str(transcript)).stem
        cleaned = re.sub(r"[^A-Za-z0-9_.-]", "-", sanitize_value(stem)).strip("-")
        if cleaned:
            return cleaned[:64]
    return "unknown"


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


_TAIL_READ_BYTES = 65536


def _highest_turn_number(scratch_path: Path) -> int:
    """Return the highest ``turn`` number recorded in *scratch_path*.

    Turn numbers increase monotonically, so the maximum lives in the final
    record.  We read only the file's tail (last 64 KiB) instead of re-parsing
    the whole WAL on every Stop — the previous full re-read made per-session
    capture O(n²) in turn count on the 5 s hot path.  Only :data:`EVENT_TURN`
    records count (appended ``ended`` markers and truncated lines are ignored,
    matching finalize's parse semantics).  Returns 0 when the file is absent or
    holds no turn records, so ``+ 1`` yields the next turn number.
    """
    try:
        size = scratch_path.stat().st_size
    except OSError:
        return 0
    if size == 0:
        return 0
    try:
        with open(scratch_path, "rb") as fh:
            if size > _TAIL_READ_BYTES:
                fh.seek(size - _TAIL_READ_BYTES)
            chunk = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return 0

    best = 0
    for line in chunk.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            # INV-6: skip truncated / malformed lines (incl. a partial first
            # line when the tail starts mid-record).
            continue
        if isinstance(rec, dict) and rec.get("event") == EVENT_TURN:
            turn = rec.get("turn")
            if isinstance(turn, int) and turn > best:
                best = turn
    return best


# ---------------------------------------------------------------------------
# Field derivation
# ---------------------------------------------------------------------------


_EDIT_TOOLS: frozenset[str] = frozenset({"Edit", "Write", "MultiEdit", "apply_patch"})
_PATCH_PATH_RE = re.compile(
    r"^\*\*\* (?:Add|Update|Delete) File:\s*(.+?)\s*$", re.MULTILINE
)
_PATCH_MOVE_RE = re.compile(r"^\*\*\* Move to:\s*(.+?)\s*$", re.MULTILINE)
# Runtime twin of templates_src/_partials/apply-patch-paths.py.jinja (hooks
# cannot import mapify_cli); keep the two in step.


def _apply_patch_paths(payload: object) -> list[str]:
    """Return explicit file targets from a Codex ``apply_patch`` payload.

    Codex records the call in three shapes: hook ``tool_input`` mappings
    (``{"command": <patch>}``), rollout ``custom_tool_call`` items whose
    ``input`` is the raw patch text, and ``function_call`` items whose
    ``arguments`` is a JSON string. Only explicit patch headers count.
    """
    if isinstance(payload, dict):
        payload = payload.get("command") or payload.get("input") or payload.get("patch")
    if isinstance(payload, str) and payload.lstrip().startswith("{"):
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError:
            decoded = None
        if isinstance(decoded, dict):
            return _apply_patch_paths(decoded)
    if not isinstance(payload, str):
        return []
    paths = [m.group(1).strip() for m in _PATCH_PATH_RE.finditer(payload)]
    paths += [m.group(1).strip() for m in _PATCH_MOVE_RE.finditer(payload)]
    return [path for path in paths if path]


def _redact_and_dedup(paths: list[str]) -> list[str]:
    """Apply redact_secret_path + sanitize_value to each path; dedup in order."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in paths:
        cleaned = sanitize_value(redact_secret_path(str(raw)))
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            out.append(cleaned)
    return out


def _extract_edit_paths(obj: Any, out: list[str]) -> None:
    """Recursively collect paths from Claude and Codex transcript records."""
    if isinstance(obj, dict):
        name = obj.get("tool_name") or obj.get("name")
        if name == "apply_patch":
            # Hook payloads carry tool_input; Claude-style tool_use blocks carry
            # input as a dict; Codex rollout custom_tool_call items carry the
            # raw patch in input, function_call items a JSON string in arguments.
            for key in ("tool_input", "input", "arguments"):
                if key in obj:
                    out.extend(_apply_patch_paths(obj.get(key)))
        elif obj.get("type") == "tool_use" and name in _EDIT_TOOLS:
            tool_input = obj.get("input")
            if isinstance(tool_input, dict):
                raw_path = tool_input.get("file_path") or tool_input.get("path")
                if raw_path:
                    out.append(str(raw_path))

        # `codex exec --json` emits completed file-change items with one entry
        # per changed path. Shape-tolerant: the outer envelope has changed
        # across Codex releases.
        if obj.get("type") == "file_change":
            changes = obj.get("changes")
            if isinstance(changes, list):
                for change in changes:
                    if isinstance(change, dict):
                        raw_path = change.get("path") or change.get("file_path")
                        if raw_path:
                            out.append(str(raw_path))

        for value in obj.values():
            _extract_edit_paths(value, out)
    elif isinstance(obj, list):
        for value in obj:
            _extract_edit_paths(value, out)


def _prompt_event(record: object) -> dict[str, Any] | None:
    """Select human text only, never assistant prose or user-carried results."""
    if not isinstance(record, dict):
        return None
    if record.get("isMeta") or record.get("isCompactSummary"):
        return None
    if record.get("type") == "response_item":
        message = record.get("payload")
        if not isinstance(message, dict) or message.get("type") != "message":
            return None
    elif record.get("type") == "user":
        message = record.get("message")
    else:
        return None
    if not isinstance(message, dict) or message.get("role") != "user":
        return None
    content = message.get("content")
    if isinstance(content, list):
        if any(isinstance(block, dict) and block.get("type") == "tool_result" for block in content):
            return None
        content = "\n".join(
            block["text"] for block in content
            if isinstance(block, dict) and block.get("type") in {"text", "input_text"}
            and isinstance(block.get("text"), str)
        )
    if not isinstance(content, str) or not content.strip():
        return None
    cleaned = bounded_text(content, len(content))
    return {
        "event": EVENT_USER_PROMPT,
        "prompt_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "prefix": cleaned[:PROMPT_PREFIX_CHARS],
        "truncated": len(cleaned) > PROMPT_PREFIX_CHARS,
    }


def _files_from_transcript(
    transcript_path: Path, start: int, events: list[dict[str, Any]] | None = None
) -> tuple[list[str], int]:
    """Recover files edited since transcript line *start*.

    The Stop event that drives capture carries NO tool_name/tool_input, so
    per-turn file attribution is read from the transcript JSONL that Claude
    Code references via ``transcript_path``.

    Returns ``(redacted_paths, total_lines_seen)``.  The caller persists
    ``total_lines_seen`` to the ``<sid>.offset`` sidecar ONLY AFTER the turn
    record is durably written — advancing the offset first would, on a crash
    between the two writes, permanently skip that transcript range and silently
    drop its files_touched.  Best-effort: any error yields ``([], start)`` so
    the offset is not advanced past unread content.
    """
    try:
        if not transcript_path.is_file():
            return [], start
    except OSError:
        return [], start

    start = max(start, 0)

    raw_paths: list[str] = []
    event_bytes = 0
    omitted = 0
    total = start
    try:
        with open(transcript_path, encoding="utf-8", errors="replace") as fh:
            for idx, line in enumerate(fh):
                if idx < start:
                    continue  # already consumed by a prior turn
                if not line.endswith("\n"):
                    break  # retry a partially written trailing record next time
                total = idx + 1
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                _extract_edit_paths(rec, raw_paths)
                if events is not None:
                    prompt = _prompt_event(rec)
                    candidates = chain([prompt] if prompt is not None else [], native_tool_events(rec))
                    for event in candidates:
                        size = len(json.dumps(event, ensure_ascii=True)) + 512
                        if event_bytes + size <= CAPTURE_EVENT_BYTES - 1024:
                            events.append(event)
                            event_bytes += size
                        else:
                            omitted += 1
    except OSError:
        if events is not None:
            events.clear()
        return [], start

    if omitted and events is not None:
        events.append({"event": EVENT_CAPTURE_TRUNCATED, "omitted_events": omitted})
    return _redact_and_dedup(raw_paths), total


def _derive_files_touched(
    stdin_data: dict[str, Any],
    scratch_dir: Path | None = None,
    sid: str | None = None,
    events: list[dict[str, Any]] | None = None,
) -> tuple[list[str], int | None]:
    """Extract the file paths touched this turn, from one of two sources.

    Resolution order:
      1. Inline ``tool_input`` when a PostToolUse-shaped payload carries a
         supported Claude edit tool or Codex ``apply_patch``.
      2. The session transcript referenced by ``transcript_path`` — the Stop
         event that drives capture in production carries no tool fields, so the
         turn's edits are recovered from the transcript (see
         :func:`_files_from_transcript`).

    Returns ``(files, new_offset)``.  ``new_offset`` is the transcript line
    count to persist to ``<sid>.offset`` AFTER the turn record is written, or
    ``None`` for the inline path (no offset tracking).  Each path is passed
    through redact_secret_path() then sanitize_value().
    """
    tool_name: str = stdin_data.get("tool_name", "") or ""
    if tool_name:
        if tool_name not in _EDIT_TOOLS:
            return [], None
        tool_input: dict[str, Any] = stdin_data.get("tool_input") or {}
        if tool_name == "apply_patch":
            return _redact_and_dedup(_apply_patch_paths(tool_input)), None
        raw_path = tool_input.get("file_path", "") or tool_input.get("path", "")
        if not raw_path:
            return [], None
        return _redact_and_dedup([str(raw_path)]), None

    transcript = stdin_data.get("transcript_path")
    if not transcript:
        return [], None

    start = 0
    track_offset = scratch_dir is not None and bool(sid)
    if track_offset:
        offset_file = scratch_dir / f"{sid}.offset"  # type: ignore[operator]
        try:
            start = int(offset_file.read_text(encoding="utf-8").strip() or "0")
        except (OSError, ValueError):
            start = 0

    files, total = _files_from_transcript(Path(str(transcript)), start, events)
    return files, (total if track_offset else None)


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
    return datetime.now(UTC).isoformat()


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

        # Determine the scratch file path.  When stdin carries no session_id and
        # no pointer exists, derive a stable per-session fallback from the
        # transcript path rather than collapsing every such session into one
        # shared "unknown.jsonl".
        effective_sid = sid or _fallback_sid(stdin_data)
        scratch_path = scratch_dir / f"{effective_sid}.jsonl"

        turn_number = _highest_turn_number(scratch_path) + 1

        events: list[dict[str, Any]] = []
        files_touched, new_offset = _derive_files_touched(
            stdin_data, scratch_dir, effective_sid, events
        )

        # Build the record using field names from SCRATCH_TURN_FIELDS.
        # All string values are sanitize_value()'d to strip control chars.
        record: dict[str, Any] = {
            SCRATCH_TURN_FIELDS[0]: _ts(),                         # ts
            SCRATCH_TURN_FIELDS[1]: turn_number,                   # turn
            SCRATCH_TURN_FIELDS[2]: sanitize_value(effective_sid), # session_id
            SCRATCH_TURN_FIELDS[3]: files_touched,                 # files_touched
            SCRATCH_TURN_FIELDS[4]: _derive_prompt_ref(project_dir),    # prompt_ref
            SCRATCH_TURN_FIELDS[5]: EVENT_TURN,                    # event
        }

        for event in events:
            event.update(ts=record["ts"], session_id=record["session_id"], turn=turn_number)
        batch = "".join(json.dumps(event, ensure_ascii=True) + "\n" for event in events)
        with open(scratch_path, "a", encoding="utf-8") as fh:
            fh.write(batch + json.dumps(record, ensure_ascii=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

        # Advance the transcript offset ONLY AFTER the record is durably
        # written — so a crash between the two never skips a transcript range.
        if new_offset is not None:
            try:
                (scratch_dir / f"{effective_sid}.offset").write_text(
                    str(new_offset), encoding="utf-8"
                )
            except OSError:
                pass

        # VC4: update the current-session pointer after a successful write so a
        # later turn lacking session_id can recover the same identity (skip the
        # genuinely-anonymous "unknown" bucket).
        if effective_sid != "unknown":
            write_current_session(effective_sid, project_dir)

    except Exception:  # noqa: BLE001, S110
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
        effective_sid = sid or _fallback_sid(stdin_data)

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

        # VC4: update the current-session pointer (skip the anonymous bucket).
        if effective_sid != "unknown":
            write_current_session(effective_sid, project_dir)

    except Exception:  # noqa: BLE001, S110
        # Best-effort: never block the hook.
        pass


def on_session_end(stdin_data: dict[str, Any], project_dir: Path | str) -> None:
    """SessionEnd entrypoint: best-effort 'ended' marker; never blocks/raises (AC-4).

    Thin wrapper the SessionEnd hook shim (ST-006) calls. It appends ONLY the
    ``{event: 'ended', ts, session_id}`` marker via :func:`append_end_marker` —
    NO finalize, NO LLM. SessionEnd is fire-and-forget, so this entrypoint wraps
    the call in its own broad guard (in addition to ``append_end_marker``'s
    internal one) and swallows+logs any exception, returning ``None`` cleanly.

    Reason-agnostic (EC-6): the SessionEnd ``reason`` (``clear``/``resume``/
    ``logout``/…) is read only for logging; every reason follows the same path.

    Args:
        stdin_data: Parsed SessionEnd hook stdin payload
            (``session_id``/``transcript_path``/``cwd``/``reason``).
        project_dir: Root directory of the target project (Path or str).
    """
    reason = ""
    if isinstance(stdin_data, dict):
        reason = str(stdin_data.get("reason", ""))
    try:
        append_end_marker(stdin_data, project_dir)
    except Exception:  # noqa: BLE001
        # SessionEnd must never raise to the harness — swallow and log only.
        logger.warning("on_session_end: end-marker failed (reason=%r)", reason)
