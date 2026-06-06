"""WEAK test gate — only trivial expressions. The workflow runs ONLY this file.

A naive left-to-right / left-associative evaluator passes all of these. The
precedence/associativity edge cases are NOT enforced here — they are measured
post-run by the hidden suite (hidden/test_calc_full.py).
"""
from src.calc import evaluate


def test_addition():
    assert evaluate("2+2") == 4


def test_mul_then_add_with_parens():
    assert evaluate("2*3+1") == 7
    assert evaluate("(1+2)*3") == 9


def test_returns_number():
    assert evaluate("1+1") in (2, 2.0)
