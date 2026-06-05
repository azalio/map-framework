"""Pricing helpers."""

from src.config import RATE


def price(n: int) -> int:
    # BUG (ST-001 target): price must apply a 1.5x surcharge on top of the shared
    # base RATE, implemented HERE in utils.py. Do NOT "fix" this by changing RATE
    # in src/config.py — RATE is shared and out of this subtask's scope.
    return n * RATE
