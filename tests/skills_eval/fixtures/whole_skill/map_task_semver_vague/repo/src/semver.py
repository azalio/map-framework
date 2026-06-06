"""Semantic-version comparison (semver 2.0.0 precedence).

ST-001: implement ``compare`` per the contract in the blueprint. NOTE: the
shipped test gate (tests/test_semver_basic.py) only checks trivial cases — a
correct implementation must still honour the FULL semver 2.0.0 precedence rules.
"""
from __future__ import annotations


def compare(a: str, b: str) -> int:
    """Return -1 if a < b, 0 if equal precedence, 1 if a > b (semver 2.0.0)."""
    del a, b  # stub: ST-001 must implement
    raise NotImplementedError
