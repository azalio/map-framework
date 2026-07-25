"""Lazy LLM digest finalization for the MAP Framework memory subsystem.

Public API: ``finalize_dirty(incoming_sid, project_dir, timeout)``

Called from the SessionStart hook shim (ST-006) to checkpoint all prior
dirty scratch WAL files.  Each candidate scratch is finalized under a
per-branch flock (double-checked locking → exactly one digest per session).

Ordering invariant (INV-4 — LOAD-BEARING):
  1. write  scratch/<sid>.md.tmp
  2. rename tmp  →  sessions/YYYY-MM-DD-<slug>.md   (atomic)
  3. create scratch/<sid>.finalized
  4. append cost record  →  sessions/memory-cost.log
  5. delete scratch/<sid>.jsonl

On any failure the tmp is cleaned up and scratch is left unfinalized so
the next SessionStart retries automatically.

NO modification to token_accounting.json (deferred, spec:90-92).
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mapify_cli._locking import LockState, LockTimeoutError, flock_with_state
from mapify_cli.memory.capture import _resolve_branch
from mapify_cli.memory.digest_schema import (
    DIGEST_FRONTMATTER_FIELDS,
    EVENT_TURN,
    redact_secret_path,
    redact_text,
    sanitize_value,
)
from mapify_cli.token_budget import TokenUsage

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_SLUG_COLLAPSE_RE = re.compile(r"-+")
_SLUG_NON_ALNUM_RE = re.compile(r"[^a-z0-9]")


def _make_slug(title: str) -> str:
    """Derive a ≤32-char URL-safe slug from the first four words of *title*.

    Algorithm (spec LOW-11 / lines 153-156):
      1. Take first 4 words (whitespace-split).
      2. Lowercase.
      3. Replace every non-alnum char with '-'.
      4. Collapse consecutive '-' runs.
      5. Strip leading/trailing '-'.
      6. Truncate to 32 chars.
    """
    words = title.split()[:4]
    raw = " ".join(words).lower()
    slugged = _SLUG_NON_ALNUM_RE.sub("-", raw)
    slugged = _SLUG_COLLAPSE_RE.sub("-", slugged)
    slugged = slugged.strip("-")
    return slugged[:32]


def _digest_owned_by(dest_path: Path, sid: str) -> bool:
    """Return True iff the digest at *dest_path* already belongs to *sid*.

    Matches the EXACT frontmatter owner line, not a loose substring, so a file
    path / body / ticket that merely contains this sid does not falsely claim
    ownership.  session_id is persisted un-redacted (it is an identifier, not a
    secret), so the reconstructed line reproduces what _build_frontmatter wrote.
    """
    try:
        existing = dest_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    owner_line = f'{DIGEST_FRONTMATTER_FIELDS[0]}: "{sanitize_value(sid)}"'
    return owner_line in existing


def _disambiguate_slug(slug: str, sid: str, date_iso: str, sessions_dir: Path) -> str:
    """Return a slug whose `<date>-<slug>.md` path won't clobber another session.

    If the natural path is free or already owned by *sid*, the slug is returned
    unchanged.  Otherwise a `-<sid[:8]>` suffix is appended; crucially the base
    is truncated to RESERVE room for that suffix within the 32-char budget — a
    naive append-then-truncate drops the suffix when the base is already 32
    chars, re-colliding and overwriting the other session's digest.  A numeric
    tail is added if the suffixed slug still collides with yet another session.
    """
    dest = sessions_dir / f"{date_iso}-{slug}.md"
    if not dest.exists() or _digest_owned_by(dest, sid):
        return slug

    suffix = f"-{sid[:8]}"
    base = slug[: max(1, 32 - len(suffix))]
    n = 0
    while True:
        tail = "" if n == 0 else f"-{n}"
        # Keep the whole candidate within the 32-char budget.
        trimmed_base = base[: max(1, 32 - len(suffix) - len(tail))]
        candidate = f"{trimmed_base}{suffix}{tail}"
        dest = sessions_dir / f"{date_iso}-{candidate}.md"
        if not dest.exists() or _digest_owned_by(dest, sid):
            return candidate
        n += 1


def _lock_name(branch: str) -> str:
    """Return a valid flock name for *branch* (must match ^[a-zA-Z0-9_-]{1,64}$)."""
    # Branch sanitizer (capture._sanitize_branch) already allows '.' for
    # conventional names like "feat/v1.2"; '.' is NOT allowed in lock names.
    raw = f"memory-finalize-{branch}"
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "-", raw)
    return cleaned[:64]


def _build_frontmatter(
    *,
    session_id: str,
    branch: str,
    date_iso: str,
    slug: str,
    files_touched: list[str],
    decisions: list[object],
    findings: list[object],
    ticket_refs: list[str],
) -> str:
    """Render YAML frontmatter using DIGEST_FRONTMATTER_FIELDS order."""
    # Build a mapping in the canonical field order.
    # sanitize_value each string value; lists are serialised as YAML inline.

    def _yaml_str(v: str) -> str:
        # Escape backslashes FIRST, then double-quotes, so the emitted scalar
        # round-trips through yaml.safe_load (recall._parse_digest).  Without
        # the backslash escape a value like a Windows path corrupts the YAML
        # and the whole digest is silently dropped on recall.
        escaped = v.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'

    def _yaml_list(items: list[object]) -> str:
        if not items:
            return "[]"
        parts = []
        for item in items:
            if isinstance(item, str):
                parts.append(f"  - {_yaml_str(item)}")
            else:
                parts.append(f"  - {json.dumps(item)}")
        return "\n" + "\n".join(parts)

    def _clean(v: str) -> str:
        # Redact per-field on the RAW value, BEFORE YAML escaping — the «redacted»
        # token has no quotes/backslashes so escaping stays correct.  Identifier
        # fields (session_id/branch/date/slug) are intentionally NOT redacted:
        # they are not secrets, and redacting a long hex session_id to «redacted»
        # would break the owner-line dedup check (_digest_owned_by).
        return redact_text(sanitize_value(v))

    # DIGEST_FRONTMATTER_FIELDS order:
    # session_id, branch, date, slug, files_touched, decisions, findings, ticket_refs
    lines: list[str] = ["---"]
    lines.append(f"{DIGEST_FRONTMATTER_FIELDS[0]}: {_yaml_str(sanitize_value(session_id))}")
    lines.append(f"{DIGEST_FRONTMATTER_FIELDS[1]}: {_yaml_str(sanitize_value(branch))}")
    lines.append(f"{DIGEST_FRONTMATTER_FIELDS[2]}: {_yaml_str(date_iso)}")
    lines.append(f"{DIGEST_FRONTMATTER_FIELDS[3]}: {_yaml_str(sanitize_value(slug))}")
    lines.append(f"{DIGEST_FRONTMATTER_FIELDS[4]}: {_yaml_list([_clean(str(f)) for f in files_touched])}")
    # decisions/findings are LLM output — sanitize+redact string items the same
    # way as every other content field so embedded newlines are flattened (a raw
    # newline in a value would otherwise corrupt the frontmatter boundary and
    # make recall._parse_digest drop the whole digest) and any leaked secret is
    # stripped at the value level.
    lines.append(f"{DIGEST_FRONTMATTER_FIELDS[5]}: {_yaml_list([_clean(d) if isinstance(d, str) else d for d in decisions])}")
    lines.append(f"{DIGEST_FRONTMATTER_FIELDS[6]}: {_yaml_list([_clean(f) if isinstance(f, str) else f for f in findings])}")
    lines.append(f"{DIGEST_FRONTMATTER_FIELDS[7]}: {_yaml_list([_clean(str(r)) for r in ticket_refs])}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def _build_prompt(turns: list[dict[str, object]]) -> str:
    """Build the claude -p prompt from scratch turn records.

    Security: NEVER reads secret-file bodies; files_touched paths are already
    redacted at capture time (redact_secret_path was applied then).
    """
    lines = [
        "You are summarizing a MAP Framework session from its scratch WAL records.",
        "Produce a concise session digest.",
        "",
        "Return a JSON object as your response with exactly these keys:",
        '  {"title": "<4-word summary>", "body": "<markdown summary>",',
        '   "decisions": ["<decision1>", ...], "findings": ["<finding1>", ...]}',
        "",
        "Session turn records (JSONL):",
    ]
    for turn in turns:
        lines.append(json.dumps(turn))
    return "\n".join(lines)


def _strip_code_fence(text: str) -> str:
    """Strip a single leading/trailing Markdown code fence from *text*.

    Models frequently wrap a requested JSON object in ```json … ``` fences even
    when asked for raw JSON.  Without stripping, json.loads on the fenced string
    raises and the structured {title, decisions, findings} are lost (the digest
    then carries an empty decisions/findings list and a slug derived from the
    literal ``` fence line).  Returns *text* unchanged when no fence is present.
    """
    stripped = text.strip()
    if not stripped.startswith("```"):
        return text
    lines = stripped.splitlines()
    # Drop the opening fence line (``` or ```json).
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    # Drop the closing fence line if present.
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines)


def _parse_claude_output(
    stdout: str,
) -> tuple[str, str, list[object], list[object]]:
    """Parse the claude -p JSON envelope defensively.

    Returns (title, body_text, decisions, findings).
    Falls back to ("", stdout, [], []) on parse failure.
    """
    try:
        parsed = json.loads(stdout)
        raw_result = parsed.get("result", stdout)
    except (json.JSONDecodeError, AttributeError):
        return "", stdout, [], []

    # Try to parse result as structured {title, body, decisions, findings},
    # tolerating a ```json fence the model may have wrapped it in.
    try:
        inner = json.loads(_strip_code_fence(str(raw_result)))
        if isinstance(inner, dict):
            title = str(inner.get("title") or "")
            body = str(inner.get("body") or inner.get("title") or raw_result)
            decisions: list[object] = list(inner.get("decisions") or [])
            findings: list[object] = list(inner.get("findings") or [])
            return title, body, decisions, findings
    except (json.JSONDecodeError, TypeError):
        pass

    # Fallback: treat result as plain body text.
    return "", str(raw_result), [], []


def _append_cost_log(
    cost_log_path: Path,
    *,
    session_id: str,
    usage: dict[str, Any],
    duration_s: float,
) -> None:
    """Append one JSONL cost record to memory-cost.log.

    Shape: {ts, session_id, input_tokens, cache_read_input_tokens,
            cache_creation_input_tokens, output_tokens, duration_s}
    """
    # Shape the input part via TokenUsage (token_budget.py:44).
    tu = TokenUsage(
        input_tokens=int(usage.get("input_tokens", 0) or 0),
        cache_read_input_tokens=int(usage.get("cache_read_input_tokens", 0) or 0),
        cache_creation_input_tokens=int(usage.get("cache_creation_input_tokens", 0) or 0),
    )
    output_tokens = int(usage.get("output_tokens", 0) or 0)

    record = {
        "ts": datetime.now(UTC).isoformat(),
        "session_id": session_id,
        "input_tokens": tu.input_tokens,
        "cache_read_input_tokens": tu.cache_read_input_tokens,
        "cache_creation_input_tokens": tu.cache_creation_input_tokens,
        "output_tokens": output_tokens,
        "duration_s": round(duration_s, 3),
    }
    cost_log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cost_log_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


# ---------------------------------------------------------------------------
# Per-candidate finalization
# ---------------------------------------------------------------------------


def _finalize_one(
    sid: str,
    scratch_dir: Path,
    sessions_dir: Path,
    branch: str,
    timeout: int,
    lock_timeout_s: float = 10.0,
) -> bool:
    """Finalize a single dirty scratch candidate.

    Returns True iff a digest was written (False for empty-scratch no-ops and
    all failure paths).
    """
    scratch_jsonl = scratch_dir / f"{sid}.jsonl"
    finalized_marker = scratch_dir / f"{sid}.finalized"
    tmp_path = scratch_dir / f"{sid}.md.tmp"
    cost_log = sessions_dir / "memory-cost.log"

    lock_name = _lock_name(branch)
    try:
        with flock_with_state(lock_name, timeout_s=lock_timeout_s, initial_state=LockState.IN_PROGRESS):
            # ---- Double-checked locking (VC3/INV-5): re-read inside the lock ----
            if finalized_marker.exists():
                # Another process finalized this sid while we waited for the lock.
                return False

            # ---- Read scratch tolerantly (INV-6/VC5) -------------------------
            turns: list[dict[str, object]] = []
            files_set: list[str] = []
            seen_files: set[str] = set()
            ticket_refs: list[str] = []
            seen_refs: set[str] = set()

            try:
                with open(scratch_jsonl, encoding="utf-8", errors="replace") as fh:
                    for raw_line in fh:
                        raw_line = raw_line.strip()
                        if not raw_line:
                            continue
                        try:
                            rec = json.loads(raw_line)
                        except json.JSONDecodeError:
                            # INV-6: skip truncated / malformed lines silently.
                            continue
                        if not isinstance(rec, dict):
                            continue
                        if rec.get("event") == EVENT_TURN:
                            turns.append(rec)
                            # Aggregate files_touched (dedup, each via redact_secret_path).
                            for fpath in rec.get("files_touched") or []:
                                redacted_f = redact_secret_path(str(fpath))
                                if redacted_f not in seen_files:
                                    seen_files.add(redacted_f)
                                    files_set.append(redacted_f)
                            # Collect unique ticket_refs (prompt_ref values).
                            ref = rec.get("prompt_ref")
                            if ref and isinstance(ref, str) and ref not in seen_refs:
                                seen_refs.add(ref)
                                ticket_refs.append(ref)
            except OSError as exc:
                logger.warning("finalize: cannot read %s: %s", scratch_jsonl, exc)
                return False

            # ---- Empty scratch (VC6/SC-2/EC-5): no digest, still finalize ----
            if not turns:
                # Write .finalized + delete scratch (and its offset sidecar) so
                # it's never reprocessed.
                finalized_marker.touch()
                for stale in (scratch_jsonl, scratch_dir / f"{sid}.offset"):
                    try:
                        stale.unlink()
                    except OSError:
                        pass
                return False

            # ---- Build prompt (security: scratch turns only, no file bodies) --
            prompt_text = _build_prompt(turns)

            # ---- Invoke claude -p (VC4/HC-5/AC-13) ----------------------------
            argv = ["claude", "-p", "--output-format", "json"]
            env = {**os.environ, "MAP_INVOKED_BY": "memory-finalize"}

            t_start = time.monotonic()
            try:
                result = subprocess.run(
                    argv,
                    input=prompt_text,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    env=env,
                    check=False,
                )
                duration_s = time.monotonic() - t_start
            except subprocess.TimeoutExpired:
                # HC-5: leave scratch unfinalized for retry; clean up any tmp.
                logger.warning("finalize: claude -p timed out for sid=%s", sid)
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass
                return False
            except Exception as exc:  # noqa: BLE001
                logger.warning("finalize: subprocess error for sid=%s: %s", sid, exc)
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass
                return False

            if result.returncode != 0:
                logger.warning(
                    "finalize: claude -p returned %d for sid=%s", result.returncode, sid
                )
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass
                return False

            # ---- Parse output (VC4) -------------------------------------------
            stdout = result.stdout or ""
            usage: dict[str, Any]
            try:
                outer = json.loads(stdout)
                usage = dict(outer.get("usage") or {})
            except (json.JSONDecodeError, AttributeError):
                usage = {}

            title, body, decisions, findings = _parse_claude_output(stdout)

            # ---- Derive slug (spec LOW-11) ------------------------------------
            # Prefer the dedicated `title` key the prompt asks for; fall back to
            # the body's first line, then the sid.  (Using the body's first line
            # unconditionally produced slugs like "summary" from a "## Summary"
            # heading, inflating collisions.)
            date_iso = datetime.now(UTC).date().isoformat()
            if title.strip():
                title_line = title.strip()
            elif body.strip():
                title_line = body.strip().splitlines()[0]
            else:
                title_line = sid
            slug = _make_slug(title_line)
            if not slug:
                slug = sid[:32]

            # Collision check: never overwrite a DIFFERENT session's digest.
            # _disambiguate_slug reserves room for the sid suffix BEFORE the
            # 32-char truncation (a naive `f"{slug}-{sid[:8]}"[:32]` chops the
            # suffix back off when slug is already 32 chars, re-colliding and
            # letting os.replace clobber the other session's digest).
            slug = _disambiguate_slug(slug, sid, date_iso, sessions_dir)
            candidate_name = f"{date_iso}-{slug}.md"
            dest_path = sessions_dir / candidate_name

            # ---- Build digest text -------------------------------------------
            frontmatter = _build_frontmatter(
                session_id=sid,
                branch=branch,
                date_iso=date_iso,
                slug=slug,
                files_touched=files_set,
                decisions=decisions,
                findings=findings,
                ticket_refs=ticket_refs,
            )
            # Redaction is applied PER-FIELD (in _build_frontmatter) and to the
            # body here, on raw values before assembly — never as a single pass
            # over the serialized digest, which would also rewrite the structural
            # session_id identifier and break the owner-line dedup check.
            body_clean = redact_text(sanitize_value(body))
            digest_text = frontmatter + "\n" + body_clean + "\n"

            # ---- Atomic write protocol (INV-4 — ORDER IS LOAD-BEARING) -------
            # Step 1: write tmp.
            try:
                sessions_dir.mkdir(parents=True, exist_ok=True)
                tmp_path.write_text(digest_text, encoding="utf-8")
            except OSError as exc:
                logger.warning("finalize: cannot write tmp for sid=%s: %s", sid, exc)
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass
                return False

            # Steps 2-3 are the ATOMIC COMMIT: the digest must exist on disk
            # (os.replace) BEFORE the .finalized marker is created, so a session
            # is never marked finalized without a digest.  If either fails, the
            # scratch is left unfinalized and the next SessionStart retries.
            try:
                # Step 2: atomic rename to final location.
                os.replace(str(tmp_path), str(dest_path))
                # Step 3: create .finalized marker (the dedup guard).
                finalized_marker.touch()
            except OSError as exc:
                logger.warning(
                    "finalize: write protocol failed for sid=%s: %s", sid, exc
                )
                # Clean up tmp if it still exists (rename may have succeeded
                # but the touch failed).
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass
                # Do NOT create .finalized — leave scratch for retry.
                return False

            # Steps 4-5 are BEST-EFFORT cleanup: the session is already
            # finalized (digest written + marker created), so a failure here
            # must NOT flip the verdict to False — that would orphan the scratch
            # (never reprocessed, since .finalized now exists) and undercount the
            # digest that was in fact written.  Swallow and continue to True.
            try:
                # Step 4: append cost record.
                _append_cost_log(
                    cost_log,
                    session_id=sid,
                    usage=usage,
                    duration_s=duration_s,
                )
            except OSError as exc:
                logger.warning("finalize: cost-log failed for sid=%s: %s", sid, exc)
            # Step 5: delete scratch WAL and its offset sidecar.
            for stale in (scratch_jsonl, scratch_dir / f"{sid}.offset"):
                try:
                    stale.unlink()
                except OSError:
                    pass

    except LockTimeoutError:
        # HC-6: skip this candidate; it will be retried on the next SessionStart.
        logger.debug("finalize: lock timeout for sid=%s; skipping", sid)
        return False
    except ValueError as exc:
        # Invalid lock name — should not happen given _lock_name() sanitizes.
        logger.warning("finalize: invalid lock name for sid=%s: %s", sid, exc)
        return False

    return True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def finalize_dirty(
    incoming_sid: str | None,
    project_dir: Path | str,
    timeout: int = 60,
) -> int:
    """Finalize all dirty prior-session scratch WAL files.

    Scans ``.map/<branch>/sessions/scratch/*.jsonl``.  A scratch file is a
    candidate iff its stem != *incoming_sid* AND no sibling ``.finalized``
    marker exists (EC-7 / HC-2 — NO SessionEnd dependency).

    For each candidate: acquires a per-branch flock, double-checks the marker
    inside the lock (VC3 concurrent safety), reads the scratch tolerantly
    (INV-6), invokes ``claude -p`` in argv-list form with
    ``MAP_INVOKED_BY=memory-finalize`` (AC-13), writes the digest atomically,
    and appends a cost record.

    Parameters
    ----------
    incoming_sid:
        Session ID of the session that is starting.  Its scratch file (if any)
        is excluded from finalization — it is still being written.
    project_dir:
        Root of the target project (must contain ``.git``).
    timeout:
        Seconds passed to ``subprocess.run(..., timeout=timeout)`` for the
        ``claude -p`` call.  The hook shim reads ``MAP_MEMORY_FINALIZE_TIMEOUT``
        env and passes it here; this module stays pure (EC-4 fallback lives in
        the shim).

    Returns
    -------
    int
        Number of digests written (empty scratches are finalized but not
        counted).
    """
    project_dir = Path(project_dir)
    branch = _resolve_branch(project_dir)
    sessions_dir = project_dir / ".map" / branch / "sessions"
    scratch_dir = sessions_dir / "scratch"

    if not scratch_dir.exists():
        return 0

    # ---- Candidate selection (EC-7) -----------------------------------------
    candidates: list[str] = []
    try:
        for jsonl_path in sorted(scratch_dir.glob("*.jsonl")):
            sid = jsonl_path.stem
            # Skip the incoming (currently active) session.
            if incoming_sid and sid == incoming_sid:
                continue
            # Skip already-finalized.
            if (scratch_dir / f"{sid}.finalized").exists():
                continue
            candidates.append(sid)
    except OSError as exc:
        logger.warning("finalize: cannot scan scratch dir %s: %s", scratch_dir, exc)
        return 0

    count = 0
    for sid in candidates:
        if _finalize_one(
            sid,
            scratch_dir=scratch_dir,
            sessions_dir=sessions_dir,
            branch=branch,
            timeout=timeout,
        ):
            count += 1

    return count
