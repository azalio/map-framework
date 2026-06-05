"""WEAK test gate — only trivial cases. The workflow runs ONLY this file.

A naive implementation (compare major.minor.patch as ints, ignore pre-release)
passes all of these. The full edge-case behaviour is NOT enforced here — it is
measured post-run by the hidden suite (hidden/test_semver_full.py).
"""
from src.semver import compare


def test_equal_versions():
    assert compare("1.0.0", "1.0.0") == 0


def test_basic_major_ordering():
    assert compare("1.0.0", "2.0.0") == -1
    assert compare("2.0.0", "1.0.0") == 1


def test_returns_minus_one_zero_one():
    for r in (compare("1.0.0", "1.0.1"), compare("1.0.0", "1.0.0"), compare("1.0.1", "1.0.0")):
        assert r in (-1, 0, 1)
