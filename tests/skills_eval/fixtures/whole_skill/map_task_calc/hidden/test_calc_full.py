"""HIDDEN comprehensive suite — the workflow never sees this file.

Injected by the harness AFTER the run to score the produced evaluator against the
classic precedence/associativity traps that violate left-to-right intuition.
Expected values follow Python operator semantics.
"""
import pytest

from src.calc import evaluate


def test_precedence_mul_over_add():
    assert evaluate("2+3*4") == 14


def test_exponent_is_right_associative():
    # 2**(3**2) = 2**9 = 512, NOT (2**3)**2 = 64
    assert evaluate("2**3**2") == 512


def test_exponent_binds_tighter_than_unary_minus():
    # Python: -2**2 == -(2**2) == -4, NOT (-2)**2 == 4
    assert evaluate("-2**2") == -4


def test_parenthesized_negation_then_power():
    assert evaluate("(-2)**2") == 4


def test_unary_minus_after_binary_op():
    assert evaluate("2*-3") == -6
    assert evaluate("3+-2") == 1


def test_double_unary_minus():
    assert evaluate("--2") == 2


def test_negative_exponent():
    # 2**(-1) == 0.5
    assert evaluate("2**-1") == 0.5


def test_nested_parentheses():
    assert evaluate("((1+2)*(3+4))") == 21


def test_true_division_is_float():
    assert evaluate("10/4") == 2.5


def test_whitespace_tolerant():
    assert evaluate("  2 +  3 ") == 5


def test_division_by_zero_raises():
    with pytest.raises(ZeroDivisionError):
        evaluate("1/0")


def test_malformed_raises_value_error():
    for bad in ("2+", "(1+2", "", "1 2"):
        with pytest.raises(ValueError):
            evaluate(bad)
