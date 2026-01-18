"""
Intent Detection Module for Early-Finish Detection.

Detects user intent to finish/stop the current workflow based on Russian phrases.
"""

import re
from typing import Optional


# Russian finish-intent phrases (case-insensitive)
FINISH_PHRASES = [
    r"закончили",
    r"остановимся",
    r"хватит",
    r"дальше\s+не\s+делай",
    r"прекращай",
    r"закрываем",
]

# Compile regex pattern for all finish phrases
_FINISH_PATTERN = re.compile(
    r"\b(" + "|".join(FINISH_PHRASES) + r")\b",
    re.IGNORECASE | re.UNICODE,
)


def detect_finish_intent(text: Optional[str]) -> bool:
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

    return bool(_FINISH_PATTERN.search(text))
