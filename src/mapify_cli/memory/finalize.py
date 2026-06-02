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
from datetime import datetime, timezone
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
        escaped = v.replace('"', '\\"')
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

    # DIGEST_FRONTMATTER_FIELDS order:
    # session_id, branch, date, slug, files_touched, decisions, findings, ticket_refs
    lines: list[str] = ["---"]
    lines.append(f"{DIGEST_FRONTMATTER_FIELDS[0]}: {_yaml_str(sanitize_value(session_id))}")
    lines.append(f"{DIGEST_FRONTMATTER_FIELDS[1]}: {_yaml_str(sanitize_value(branch))}")
    lines.append(f"{DIGEST_FRONTMATTER_FIELDS[2]}: {_yaml_str(date_iso)}")
    lines.append(f"{DIGEST_FRONTMATTER_FIELDS[3]}: {_yaml_str(sanitize_value(slug))}")
    lines.append(f"{DIGEST_FRONTMATTER_FIELDS[4]}: {_yaml_list([sanitize_value(str(f)) for f in files_touched])}")
    lines.append(f"{DIGEST_FRONTMATTER_FIELDS[5]}: {_yaml_list(decisions)}")
    lines.append(f"{DIGEST_FRONTMATTER_FIELDS[6]}: {_yaml_list(findings)}")
    lines.append(f"{DIGEST_FRONTMATTER_FIELDS[7]}: {_yaml_list([sanitize_value(str(r)) for r in ticket_refs])}")
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


def _parse_claude_output(stdout: str) -> tuple[str, list[object], list[object]]:
    """Parse the claude -p JSON envelope defensively.

    Returns (body_text, decisions, findings).
    Falls back to (stdout, [], []) on parse failure.
    """
    try:
        parsed = json.loads(stdout)
        raw_result = parsed.get("result", stdout)
    except (json.JSONDecodeError, AttributeError):
        return stdout, [], []

    # Try to parse result as structured {title, body, decisions, findings}.
    try:
        inner = json.loads(str(raw_result))
        if isinstance(inner, dict):
            body = str(inner.get("body") or inner.get("title") or raw_result)
            decisions: list[object] = list(inner.get("decisions") or [])
            findings: list[object] = list(inner.get("findings") or [])
            return body, decisions, findings
    except (json.JSONDecodeError, TypeError):
        pass

    # Fallback: treat result as plain body text.
    return str(raw_result), [], []


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
        "ts": datetime.now(timezone.utc).isoformat(),
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
                # Write .finalized + delete scratch so it's never reprocessed.
                finalized_marker.touch()
                try:
                    scratch_jsonl.unlink()
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

            body, decisions, findings = _parse_claude_output(stdout)

            # ---- Derive slug (spec LOW-11) ------------------------------------
            date_iso = datetime.now(timezone.utc).date().isoformat()
            title_line = body.strip().splitlines()[0] if body.strip() else sid
            slug = _make_slug(title_line)
            if not slug:
                slug = sid[:32]

            # Collision check: different sid already has this slug.
            candidate_name = f"{date_iso}-{slug}.md"
            dest_path = sessions_dir / candidate_name
            if dest_path.exists():
                # Check if it belongs to a different sid (read frontmatter minimally).
                existing_text = ""
                try:
                    existing_text = dest_path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    pass
                if f'"{sid}"' not in existing_text and sid not in existing_text:
                    # Different sid owns this file — disambiguate.
                    slug = f"{slug}-{sid[:8]}"
                    slug = slug[:32]
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
            # Apply redact_text over body and sanitize (defense-in-depth spec:283-287).
            body_clean = redact_text(sanitize_value(body))
            digest_text = frontmatter + "\n" + body_clean + "\n"
            # Final redaction pass over the full digest (spec:283-287).
            digest_text = redact_text(digest_text)

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

            try:
                # Step 2: atomic rename to final location.
                os.replace(str(tmp_path), str(dest_path))
                # Step 3: create .finalized marker.
                finalized_marker.touch()
                # Step 4: append cost record.
                _append_cost_log(
                    cost_log,
                    session_id=sid,
                    usage=usage,
                    duration_s=duration_s,
                )
                # Step 5: delete scratch WAL.
                try:
                    scratch_jsonl.unlink()
                except OSError:
                    pass
            except OSError as exc:
                logger.warning(
                    "finalize: write protocol failed for sid=%s: %s", sid, exc
                )
                # Clean up tmp if it still exists (rename may have succeeded
                # but a later step failed).
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass
                # Do NOT create .finalized — leave scratch for retry.
                return False

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
