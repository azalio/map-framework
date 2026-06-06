"""Arithmetic expression evaluator (Python operator semantics).

ST-001: implement ``evaluate`` per the contract. The shipped gate
(tests/test_calc_basic.py) checks only trivial expressions — a correct
implementation must still honour the FULL precedence/associativity rules,
especially right-associative ``**`` and ``**`` binding tighter than unary minus.
"""
from __future__ import annotations


def evaluate(expr: str) -> float:
    """Evaluate an arithmetic expression and return its numeric value."""
    del expr  # stub: ST-001 must implement
    raise NotImplementedError
