"""Token budget tracking for context compression.

This module computes the input-token cost of the next conversation turn by
reading the last assistant entry of a Claude Code transcript JSONL file. It
also produces the human-readable warning string that the context-meter hook
injects into the assistant's context (see
``.claude/hooks/context-meter.py``) when the configured threshold is crossed.

The numbers come straight from the model's own ``usage`` block, so no
networked tokenizer call is required and the count is exact for past turns.

See ``docs/context-compression-plan.md`` for the design rationale.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


# Multiplier applied to ``compression_threshold_tokens`` when policy is
# ``aggressive``. Locked at 0.4 by the design doc. Keep the constant here so
# tests can import it instead of duplicating a magic number.
AGGRESSIVE_MULTIPLIER = 0.4

# Valid policy values. ``unknown`` policies are treated as ``never`` (fail
# safe — never inject the nudge if config is wrong).
VALID_POLICIES = ("never", "auto", "aggressive")


@dataclass(frozen=True)
class TokenUsage:
    """Token usage reported by the API for a single assistant turn.

    The three fields together represent the full input cost the next assistant
    response will be billed against. ``output_tokens`` is intentionally
    excluded — it is the *previous* response, not the next-turn input.
    """

    input_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0

    @property
    def total(self) -> int:
        return (
            self.input_tokens
            + self.cache_read_input_tokens
            + self.cache_creation_input_tokens
        )


def _extract_usage(entry: dict) -> TokenUsage | None:
    """Pull a TokenUsage out of a transcript JSONL entry, if present.

    Returns ``None`` if the entry is not an assistant message or has no
    ``usage`` block.
    """
    message = entry.get("message")
    if not isinstance(message, dict):
        return None
    role = message.get("role")
    entry_type = entry.get("type")
    if role != "assistant" and entry_type != "assistant":
        return None
    usage = message.get("usage")
    if not isinstance(usage, dict):
        return None
    # Defensive int() — some transcripts store these as strings.
    try:
        return TokenUsage(
            input_tokens=int(usage.get("input_tokens", 0) or 0),
            cache_read_input_tokens=int(
                usage.get("cache_read_input_tokens", 0) or 0
            ),
            cache_creation_input_tokens=int(
                usage.get("cache_creation_input_tokens", 0) or 0
            ),
        )
    except (TypeError, ValueError):
        return None


def count_last_turn_tokens(transcript_path: Path) -> int:
    """Return the total input tokens reported by the most recent assistant turn.

    Walks the JSONL file from the end and returns the first assistant entry
    that carries a ``usage`` block. Returns ``0`` for any of:

    - missing or empty file
    - file with no assistant entries yet (e.g. session just started)
    - assistant entries with no ``usage`` block (older Claude Code versions)
    - malformed JSON lines (those are skipped, not fatal)

    This conservative behaviour means the meter never triggers spuriously when
    it cannot determine the real count — quality wins over false positives.
    """
    transcript_path = Path(transcript_path)
    if not transcript_path.is_file():
        return 0

    try:
        # Read all lines into memory: transcripts are bounded by Claude Code's
        # own auto-compact at ~83.5%, so worst case is a few MB. Streaming
        # backwards through arbitrary-length lines is more complex than the
        # size warrants.
        lines = transcript_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        logger.debug("token_budget: cannot read %s: %s", transcript_path, exc)
        return 0

    for raw in reversed(lines):
        raw = raw.strip()
        if not raw:
            continue
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        usage = _extract_usage(entry)
        if usage is not None:
            return usage.total

    return 0


def effective_threshold(policy: str, threshold: int) -> int | None:
    """Compute the token threshold that should trigger a compaction nudge.

    ``never`` returns ``None`` to signal "do not nudge under any
    circumstances". ``aggressive`` multiplies the configured threshold by
    ``AGGRESSIVE_MULTIPLIER`` (0.4 by design). ``auto`` and any unrecognised
    value default to the threshold as-is; an unknown value is logged at debug
    level so misconfiguration is recoverable.
    """
    if policy == "never":
        return None
    if threshold <= 0:
        # Defensive: a misconfigured 0 / negative threshold disables the nudge
        # rather than firing on every prompt.
        logger.debug("token_budget: non-positive threshold %s disables nudge", threshold)
        return None
    if policy == "aggressive":
        return max(1, int(threshold * AGGRESSIVE_MULTIPLIER))
    if policy not in VALID_POLICIES:
        logger.debug("token_budget: unknown policy %r, treating as 'auto'", policy)
    return threshold


def should_nudge(used: int, threshold: int | None) -> bool:
    """Return True when the meter should inject the compaction nudge.

    Centralised so the hook, the orchestrator, and the tests all use the same
    comparison. ``threshold is None`` means policy=never → always False.
    """
    if threshold is None:
        return False
    return used >= threshold


def format_compact_instruction(used: int, threshold: int, focus: str) -> str:
    """Produce the assistant-facing nudge string.

    The hook embeds this in ``hookSpecificOutput.additionalContext``. The
    leading ``[MAP context-meter]`` tag matches the convention used by
    ``ralph-context-pruner`` and ``post-compact-context``, so the assistant
    can recognise where the message came from.
    """
    pct = int(round(100 * used / threshold)) if threshold > 0 else 0
    focus_clean = (focus or "").strip() or (
        "MAP step state, last 2 monitor verdicts, pending subtasks"
    )
    return (
        f"[MAP context-meter] Context is at {used:,} / {threshold:,} tokens "
        f"({pct}% of MAP threshold). Before continuing, run:\n"
        f"/compact {focus_clean}"
    )
