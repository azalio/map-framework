"""Semantic-version comparison (semver 2.0.0 precedence).

ST-001: implement ``compare`` so the full suite in tests/test_semver.py passes.
The precedence rules are non-trivial — read the tests for the exact contract.
"""
from __future__ import annotations


def compare(a: str, b: str) -> int:
    """Return -1 if a < b, 0 if a and b have equal precedence, 1 if a > b.

    Versions follow ``MAJOR.MINOR.PATCH[-prerelease][+build]`` (semver 2.0.0).
    Not yet implemented.
    """
    del a, b  # stub: ST-001 must implement; params unused until then
    raise NotImplementedError
