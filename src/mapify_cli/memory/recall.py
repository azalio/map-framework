"""Branch-scoped session recall for the MAP Framework memory subsystem.

Public API: ``build_recall(prompt, branch, project_dir) -> str``

Reads finalized digest ``.md`` files from ``.map/<branch>/sessions/*.md``
(current branch only — OQ-3 v1; cross-branch is deferred), ranks them by
keyword/ticket overlap with *prompt*, caps the assembled payload at
``MAP_MEMORY_RECALL_CAP`` characters (default 4000), logs dropped digests to
``recall-drop.log``, and returns a sanitized additionalContext string.

Usefulness boost (#343): if ``.map/<branch>/context_usefulness.json`` exists
from a prior run, digest slugs labeled "helpful" or "used" receive a +5 score
boost; slugs labeled "stale" or "ignored" receive a -3 penalty.  Missing data
preserves existing keyword/ticket/recency behavior unchanged.

Pure module: no subprocess, no LLM — file I/O + string matching only.
The hook shim (ST-006) handles stdout JSON wrapping.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeAlias

import yaml

from mapify_cli.memory.digest_schema import (
    DIGEST_FRONTMATTER_FIELDS,
    redact_text,
    sanitize_value,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Regex helpers
# ---------------------------------------------------------------------------

# Ticket-id pattern for scoring boost (e.g. ST-004, TASK-12).
_TICKET_RE = re.compile(r"[a-z]+-\d+", re.IGNORECASE)

# Date prefix in YYYY-MM-DD format from digest filenames.
_DATE_PREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")

# Type alias for ranked digest entries: (score, date, frontmatter, body, path)
_DigestEntry: TypeAlias = tuple[int, str, dict[str, object], str, Path]

# Usefulness score adjustments applied on top of keyword/ticket scores (#343).
_USEFULNESS_BOOST = {"helpful": 5, "used": 5}
_USEFULNESS_PENALTY = {"stale": -3, "ignored": -3}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _read_cap() -> int:
    """Read MAP_MEMORY_RECALL_CAP env var with safe int-parse fallback."""
    raw = os.environ.get("MAP_MEMORY_RECALL_CAP", "4000")
    try:
        cap = int(raw)
        if cap < 0:
            return 4000
        return cap
    except (ValueError, TypeError):
        return 4000


def _parse_digest(path: Path) -> tuple[dict[str, object], str] | None:
    """Parse a digest ``.md`` file into (frontmatter_dict, body_text).

    Returns None when the file has no valid YAML frontmatter block or when
    yaml.safe_load raises YAMLError.  The frontmatter must be enclosed by
    the FIRST and SECOND ``---`` lines in the file.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.debug("recall: cannot read %s: %s", path, exc)
        return None

    # Frontmatter is between the first two '---' lines.
    if not text.startswith("---"):
        return None

    # Find closing '---' (first occurrence starting after the opening marker).
    rest = text[3:]  # skip the opening '---'
    close_idx = rest.find("\n---")
    if close_idx == -1:
        return None

    fm_text = rest[:close_idx]
    # Body is everything after the closing '---\n'.
    body_start = close_idx + 4  # len("\n---") == 4
    body = rest[body_start:].lstrip("\n")

    try:
        fm: object = yaml.safe_load(fm_text)
    except yaml.YAMLError as exc:
        logger.debug("recall: YAML parse error in %s: %s", path, exc)
        return None

    if not isinstance(fm, dict):
        return None

    return fm, body  # type: ignore[return-value]


def _fm_text(fm: dict[str, object]) -> str:
    """Concatenate all string values from frontmatter into one searchable blob.

    Uses DIGEST_FRONTMATTER_FIELDS to iterate — no hardcoded field names (INV-7).
    List values (files_touched, decisions, findings, ticket_refs) are joined
    so their content is also searchable.
    """
    parts: list[str] = []
    for field in DIGEST_FRONTMATTER_FIELDS:
        val = fm.get(field)
        if val is None:
            continue
        if isinstance(val, list):
            parts.append(" ".join(str(v) for v in val))
        else:
            parts.append(str(val))
    return " ".join(parts)


def _score_digest(
    prompt_tokens: list[str],
    ticket_ids: list[str],
    fm: dict[str, object],
    body: str,
) -> int:
    """Score a digest against prompt tokens.

    Primary score: count of prompt tokens present in (fm_text + body).
    Boost: +10 for each prompt ticket-id found in the digest's ticket_refs.

    Returns 0 for an empty prompt.
    """
    if not prompt_tokens:
        return 0

    # Tokenize the searchable text with the SAME regex used for the prompt and
    # match on whole-token membership, not substring — otherwise a short prompt
    # token (e.g. "api") spuriously matches inside unrelated words ("recapture")
    # and inflates/mis-ranks scores.
    searchable = (_fm_text(fm) + " " + body).lower()
    doc_tokens = set(re.findall(r"[a-z0-9_-]+", searchable))
    score = sum(1 for tok in prompt_tokens if tok in doc_tokens)

    # Boost: ticket_id match in ticket_refs field.
    if ticket_ids:
        refs_val = fm.get("ticket_refs")
        refs_raw: list[object] = refs_val if isinstance(refs_val, list) else []
        refs_lower = " ".join(str(r) for r in refs_raw).lower()
        for tid in ticket_ids:
            if tid.lower() in refs_lower:
                score += 10

    return score


def _digest_date(fm: dict[str, object], path: Path) -> str:
    """Return the digest date string (from frontmatter or filename prefix).

    Falls back to the YYYY-MM-DD prefix in the filename, then to "0000-00-00"
    so that sort order is deterministic even for malformed files.
    """
    date_val = fm.get("date")
    if date_val and isinstance(date_val, str) and date_val.strip():
        return date_val.strip()

    m = _DATE_PREFIX_RE.match(path.name)
    if m:
        return m.group(1)

    return "0000-00-00"


def _render_block(
    date_str: str,
    fm: dict[str, object],
    body: str,
) -> str:
    """Render one digest into a readable markdown block.

    Format:
        ### <date> <slug>
        **Decisions:** ...
        **Findings:** ...
        <body excerpt>

    String values are sanitized via sanitize_value() before inclusion.
    """
    slug = fm.get("slug") or ""
    if isinstance(slug, str):
        slug = sanitize_value(slug)

    lines: list[str] = [f"### {date_str} {slug}"]

    # Decisions
    decisions = fm.get("decisions") or []
    if isinstance(decisions, list) and decisions:
        dec_text = "; ".join(sanitize_value(str(d)) for d in decisions)
        lines.append(f"**Decisions:** {dec_text}")

    # Findings
    findings = fm.get("findings") or []
    if isinstance(findings, list) and findings:
        fin_text = "; ".join(sanitize_value(str(f)) for f in findings)
        lines.append(f"**Findings:** {fin_text}")

    # Body (first 500 chars to keep blocks reasonably sized).
    body_clean = sanitize_value(body.strip())
    if body_clean:
        lines.append(body_clean[:500])

    return "\n".join(lines) + "\n"


def _append_drop_log(
    drop_log_path: Path,
    *,
    session_id: str,
    slug: str,
    dropped_chars: int,
) -> None:
    """Append one JSONL drop record to recall-drop.log."""
    record = {
        "ts": datetime.now(UTC).isoformat(),
        "session_id": session_id,
        "slug": slug,
        "dropped_chars": dropped_chars,
        "reason": "recall_cap",
    }
    try:
        drop_log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(drop_log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError as exc:
        logger.warning("recall: cannot write drop log %s: %s", drop_log_path, exc)


# ---------------------------------------------------------------------------
# Usefulness-score helpers (#343)
# ---------------------------------------------------------------------------


def _load_usefulness_scores(project_dir: Path, branch: str) -> dict[str, int]:
    """Load prior-run usefulness scores from context_usefulness.json.

    Returns a dict mapping digest slug → score delta (positive or negative).
    An absent or malformed artifact returns an empty dict, preserving existing
    ranking behaviour.
    """
    artifact = project_dir / ".map" / branch / "context_usefulness.json"
    if not artifact.exists():
        return {}
    try:
        raw = artifact.read_text(encoding="utf-8", errors="replace")
        data: object = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("recall: cannot load usefulness scores from %s: %s", artifact, exc)
        return {}

    if not isinstance(data, dict):
        return {}

    items_val = data.get("items")
    if not isinstance(items_val, list):
        return {}

    scores: dict[str, int] = {}
    for item in items_val:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        if kind != "memory_digest":
            continue
        source = item.get("source")
        if not isinstance(source, str) or not source.strip():
            continue
        slug = source.strip()
        label = str(item.get("outcome_label") or "unknown")
        delta = _USEFULNESS_BOOST.get(label) or _USEFULNESS_PENALTY.get(label) or 0
        if delta:
            scores[slug] = scores.get(slug, 0) + delta

    return scores


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_recall(prompt: str, branch: str, project_dir: Path | str) -> str:
    """Build a ranked, capped, sanitized recall payload for *branch*.

    Reads digest ``.md`` files from ``<project_dir>/.map/<branch>/sessions/``
    (current-branch only — OQ-3 v1), ranks them by keyword/ticket overlap with
    *prompt*, caps the assembled payload at ``MAP_MEMORY_RECALL_CAP`` chars,
    drops overflow digests to ``recall-drop.log``, and returns the payload.

    Each rendered block includes a per-block body excerpt bounded to the first
    500 characters (an intentional rendering bound to keep blocks compact); the
    full digest file always remains on disk. This per-block body bound is
    distinct from the SC-1 cap, which drops *whole* digests (never mid-digest)
    and logs every drop.

    Parameters
    ----------
    prompt:
        The user's current prompt text.  Empty string → recency-only ranking.
    branch:
        Current git branch (resolved by the shim via ``_resolve_branch``).
    project_dir:
        Root directory of the target project.

    Returns
    -------
    str
        Sanitized additionalContext string, or ``""`` when there is nothing to
        recall (no digests, none fit within cap).
    """
    project_dir = Path(project_dir)
    sessions_dir = project_dir / ".map" / branch / "sessions"
    drop_log_path = sessions_dir / "recall-drop.log"

    cap = _read_cap()

    # ---- Discover digest files -----------------------------------------------
    if not sessions_dir.exists():
        return ""

    try:
        md_paths = sorted(
            p for p in sessions_dir.glob("*.md") if p.is_file()
        )
    except OSError as exc:
        logger.warning("recall: cannot scan sessions dir %s: %s", sessions_dir, exc)
        return ""

    if not md_paths:
        return ""

    # ---- Tokenize prompt ------------------------------------------------------
    prompt_tokens = re.findall(r"[a-z0-9_-]+", prompt.lower())
    ticket_ids = _TICKET_RE.findall(prompt)

    # ---- Load prior usefulness scores (boost/penalty per slug) ---------------
    usefulness_scores = _load_usefulness_scores(project_dir, branch)

    # ---- Parse + score each digest -------------------------------------------
    entries: list[_DigestEntry] = []

    for path in md_paths:
        parsed = _parse_digest(path)
        if parsed is None:
            continue
        fm, body = parsed
        score = _score_digest(prompt_tokens, ticket_ids, fm, body)
        # Apply usefulness adjustment when the digest slug matches a prior record.
        slug = str(fm.get("slug") or path.stem)
        if usefulness_scores and slug in usefulness_scores:
            score = max(0, score + usefulness_scores[slug])
        date_str = _digest_date(fm, path)
        entries.append((score, date_str, fm, body, path))

    if not entries:
        return ""

    # Sort: (score desc, date desc).
    entries.sort(key=lambda e: (e[0], e[1]), reverse=True)

    # ---- Build header ---------------------------------------------------------
    header = f"## Recalled session memory (branch {branch})\n\n"
    header_len = len(header)

    # ---- Accumulate blocks until cap (rank-monotonic) ------------------------
    # entries are sorted (score desc, date desc).  Once a block does not fit we
    # STOP including and drop every remaining (lower-ranked) digest — so the
    # recalled set is always a clean prefix of the ranking.  Continuing past the
    # first overflow would let a smaller, lower-ranked digest jump ahead of a
    # larger, higher-ranked one that was dropped, violating relevance order.
    included_blocks: list[str] = []
    total_chars = header_len
    overflowed = False

    for _score, date_str, fm, body, path in entries:
        del _score  # used only as the sort key above; unused in the loop body
        block = _render_block(date_str, fm, body)

        if not overflowed:
            # Account for the "\n" separator that "\n".join inserts before every
            # block after the first, so the assembled payload length never
            # exceeds the cap (the join would otherwise add N-1 uncounted
            # newlines).
            sep = 1 if included_blocks else 0
            if total_chars + sep + len(block) <= cap:
                included_blocks.append(block)
                total_chars += sep + len(block)
                continue
            # First block that does not fit — stop including from here on.
            overflowed = True

        # Drop whole — SC-1: never mid-digest truncation.
        session_id = fm.get("session_id") or path.stem
        slug = str(fm.get("slug") or "")
        _append_drop_log(
            drop_log_path,
            session_id=str(session_id),
            slug=slug,
            dropped_chars=len(block),
        )

    if not included_blocks:
        return ""

    # ---- Assemble payload and sanitize ---------------------------------------
    payload = header + "\n".join(included_blocks)
    # Defense-in-depth: redact any secrets that slipped through at finalize time.
    payload = redact_text(payload)
    return payload
