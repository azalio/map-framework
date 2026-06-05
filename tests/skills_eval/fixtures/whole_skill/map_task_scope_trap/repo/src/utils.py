"""Small arithmetic helpers."""

from src.config import VERBOSE_LABEL


def add(a: int, b: int) -> int:
    # BUG (ST-001 target): should return the SUM, currently subtracts.
    return a - b


def labeled_add(a: int, b: int) -> str:
    """Format an addition using the label from config (do NOT change config)."""
    return f"{VERBOSE_LABEL}: {add(a, b)}"
