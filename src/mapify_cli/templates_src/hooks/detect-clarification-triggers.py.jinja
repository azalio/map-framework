#!/usr/bin/env python3
"""detect-clarification-triggers.py

UserPromptSubmit hook — inspects each user prompt before Claude processes
it, and injects guidance via `hookSpecificOutput.additionalContext` when
either of two trigger classes is present:

1. **Explicit clarification-invitation language** ("ask if unclear",
   "do not assume", "если что-то непонятно", "спрашивай", ...)
   → reminds the planner that /map-plan Step 1 Override is in effect:
     the deep interview is REQUIRED.

2. **Long-running / async / durability language** ("5 minutes",
   "long-running", "background job", "webhook", "polling",
   "асинхронн", "в фоне", ...)
   → reminds the planner that Devil's Advocate review must run and the
     decomposer's Durability Audit checklist applies.

Both signals are non-blocking. The hook always exits 0 (per docs, only
exit code 2 blocks the action; this hook is informational).

Detects English and Russian patterns.

Trigger: UserPromptSubmit
Exit codes: Always 0
Output: JSON to stdout if either signal matched, otherwise empty.
"""

from __future__ import annotations

import json
import os
import re
import sys

# Bilingual clarification-invitation patterns. Case-insensitive.
# Keep these tight to avoid false positives — these phrases must sound
# like the user is explicitly opening the door for questions.
CLARIFICATION_PATTERNS = [
    # English
    r"\bask if (?:un)?clear\b",
    r"\bask if not clear\b",
    r"\bask if anything\b",
    r"\bask before\b",
    r"\bdo(?:n['’]t| not) assume\b",
    r"\bclarify\b",
    r"\bfeel free to ask\b",
    r"\bif (?:anything|something) (?:is )?(?:un)?clear\b",
    r"\bif (?:anything|something) is not clear\b",
    r"\bask any questions\b",
    # Russian
    r"если что[-\s]*то непонятно",
    r"если не ясно",
    r"если что не ясно",
    r"\bспрашивай\b",
    r"\bуточняй\b",
    r"задавай вопросы",
    r"не предполагай",
    r"не додумывай",
]

# Bilingual async / long-running / durability language.
# Either a "kind" word (async, webhook, polling, ...) OR a significant
# duration (>=30 s, any minutes/hours) is sufficient to trigger.
KIND_PATTERNS = [
    # English
    r"\basync\b",
    r"\blong[\s-]?running\b",
    r"\bbackground\s+(?:job|task|process|worker)\b",
    r"\bwebhook\b",
    r"\bcallback\b",
    r"\bpolling\b",
    r"\bpoll\s+(?:for|the|until)\b",
    r"\b(?:durable|durability|persist(?:ence|ent)?)\b",
    r"\brun_id\b|\bjob_id\b|\btask_id\b",
    r"\bbatch\s+job\b",
    r"\bqueue(?:d|ing)?\b",
    r"\bretry\s+(?:logic|policy|on\s+failure)\b",
    # Russian
    r"асинхронн",
    r"\bдолго\s+(?:работа|выполня|идёт|идет)",
    r"\bв\s+фоне\b",
    r"\bвебхук",
    r"\bколлбек|\bколбек",
    r"\bочеред",
    r"\bретра",
    r"\bдлительн(?:ая|ое|ый)\s+операц",
]

# Significant durations: any operation that the docs would call "long-running".
# Threshold rationale: 30 seconds is roughly when you can no longer assume
# in-memory state survives a single request boundary (autoscaler eviction
# and process restart timeframes start being relevant).
SIGNIFICANT_DURATION_PATTERNS = [
    # English: minutes (any number) — always significant
    r"\b\d+\s*(?:minute|min)s?\b",
    # English: hours (any number) — always significant
    r"\b\d+\s*(?:hour|hr)s?\b",
    # English: seconds >=30
    r"\b(?:[3-9]\d|\d{3,})\s*(?:second|sec)s?\b",
    # Russian: minutes (any number)
    r"\b\d+\s*(?:минут|мин)\b",
    # Russian: hours (any number)
    r"\b\d+\s*(?:час|часов|часа)",
    # Russian: seconds >=30
    r"\b(?:[3-9]\d|\d{3,})\s*(?:секунд|сек)",
]

CLARIFICATION_RE = re.compile("|".join(CLARIFICATION_PATTERNS), re.IGNORECASE)
KIND_RE = re.compile("|".join(KIND_PATTERNS), re.IGNORECASE)
SIGNIFICANT_DURATION_RE = re.compile(
    "|".join(SIGNIFICANT_DURATION_PATTERNS), re.IGNORECASE
)


def detect_clarification(prompt: str) -> bool:
    return bool(CLARIFICATION_RE.search(prompt))


def detect_durability(prompt: str) -> bool:
    """Fire if any async/long-running 'kind' word is present, OR if there
    is any duration on a scale where state must survive a request boundary
    (≥30 seconds, or any number of minutes/hours).
    """
    if KIND_RE.search(prompt):
        return True
    return bool(SIGNIFICANT_DURATION_RE.search(prompt))


def build_message(clar: bool, dura: bool) -> str:
    lines = ["[MAP framework — clarification-trigger detector]"]
    if clar:
        lines.append(
            "- User explicitly invited clarification. /map-plan Step 1 Override "
            "is in effect: the deep interview (Step 2) is REQUIRED, not optional. "
            "Do not skip the interview on heuristic grounds."
        )
    if dura:
        lines.append(
            "- User prompt indicates an async / long-running / durability-sensitive "
            "operation. Apply: (a) /map-plan Step 2b Devil's Advocate review is "
            "REQUIRED (length/subtask-count skip does not apply), (b) the "
            "task-decomposer Durability Audit checklist MUST run for any subtask "
            "that touches state. Default answer to 'where does state live?' is "
            "NEVER 'in-process memory'."
        )
    return "\n".join(lines)


def main() -> int:
    if os.environ.get("MAP_INVOKED_BY"):
        sys.exit(0)
    try:
        payload = json.load(sys.stdin)
    except Exception:  # noqa: BLE001 -- deliberate fallback/resilience boundary, must not propagate
        # Malformed input: never block the user. Best-effort exit.
        return 0

    # Field name varies across Claude Code versions: prompt | user_prompt | userPrompt
    prompt = (
        payload.get("prompt")
        or payload.get("user_prompt")
        or payload.get("userPrompt")
        or ""
    )
    if not isinstance(prompt, str) or not prompt.strip():
        return 0

    clar = detect_clarification(prompt)
    dura = detect_durability(prompt)

    if not (clar or dura):
        return 0

    out = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": build_message(clar, dura),
        }
    }
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
