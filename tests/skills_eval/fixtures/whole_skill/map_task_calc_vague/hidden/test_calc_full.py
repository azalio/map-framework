"""HIDDEN suite (vague-contract variant) — the workflow never sees this file.

Drops the language-AMBIGUOUS -2**2 case; keeps only UNAMBIGUOUS-but-hard cases.
The contract does NOT spell out associativity, so passing right-associative **
(2**3**2 == 512, standard math) requires the model to KNOW it — the model-
competence probe. Expected values are unambiguous across mainstream languages.
"""
import pytest

from src.calc import evaluate


def test_precedence_mul_over_add():
    assert evaluate("2+3*4") == 14


def test_exponent_is_right_associative():
    # standard math: 2**(3**2) = 512, NOT (2**3)**2 = 64
    assert evaluate("2**3**2") == 512


def test_parenthesized_negation_then_power():
    assert evaluate("(-2)**2") == 4


def test_unary_minus_after_binary_op():
    assert evaluate("2*-3") == -6
    assert evaluate("3+-2") == 1


def test_double_unary_minus():
    assert evaluate("--2") == 2


def test_negative_exponent():
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
