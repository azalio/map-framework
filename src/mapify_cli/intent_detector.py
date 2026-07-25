"""
Intent Detection Module for Early-Finish Detection.

Detects user intent to finish/stop the current workflow based on Russian phrases.
"""

import re
from re import Pattern

# Russian finish-intent phrases (case-insensitive)
FINISH_PHRASES = [
    r"закончили",
    r"остановимся",
    r"хватит",
    r"дальше\s+не\s+делай",
    r"прекращай",
    r"закрываем",
]

# Lazily compiled regex pattern (compiled on first use)
_finish_pattern_cache: Pattern[str] | None = None


def _get_finish_pattern() -> Pattern[str]:
    """
    Get the compiled finish pattern, compiling lazily on first call.

    This avoids regex compilation at module import time, reducing startup
    overhead when the module is imported but not used.

    Returns:
        Compiled regex pattern for finish phrases.
    """
    global _finish_pattern_cache
    if _finish_pattern_cache is None:
        _finish_pattern_cache = re.compile(
            r"\b(" + "|".join(FINISH_PHRASES) + r")\b",
            re.IGNORECASE | re.UNICODE,
        )
    return _finish_pattern_cache


def detect_finish_intent(text: str | None) -> bool:
    """
    Detect if text contains Russian finish-intent phrases.

    Args:
        text: Input text to analyze. Can be None or empty string.

    Returns:
        True if any finish phrase found, False otherwise.

    Examples:
        >>> detect_finish_intent("закончили работу")
        True
        >>> detect_finish_intent("ХВАТИТ на сегодня")
        True
        >>> detect_finish_intent("продолжаем дальше")
        False
        >>> detect_finish_intent(None)
        False
        >>> detect_finish_intent("")
        False
    """
    if not text:
        return False

    pattern = _get_finish_pattern()
    return bool(pattern.search(text))
