"""HIDDEN comprehensive suite — the workflow never sees this file.

Injected by the harness AFTER the run to score the produced code against the
FULL semver 2.0.0 contract (the edge cases the weak gate did not enforce).
"""
from src.semver import compare


def test_numeric_fields_compare_numerically_not_lexically():
    assert compare("1.10.0", "1.9.0") == 1
    assert compare("1.0.10", "1.0.9") == 1
    assert compare("2.0.0", "10.0.0") == -1


def test_prerelease_has_lower_precedence_than_release():
    assert compare("1.0.0-alpha", "1.0.0") == -1
    assert compare("1.0.0", "1.0.0-alpha") == 1


def test_canonical_prerelease_chain():
    chain = [
        "1.0.0-alpha",
        "1.0.0-alpha.1",
        "1.0.0-alpha.beta",
        "1.0.0-beta",
        "1.0.0-beta.2",
        "1.0.0-beta.11",
        "1.0.0-rc.1",
        "1.0.0",
    ]
    for lo, hi in zip(chain, chain[1:]):
        assert compare(lo, hi) == -1, f"{lo} should be < {hi}"
        assert compare(hi, lo) == 1, f"{hi} should be > {lo}"


def test_numeric_identifiers_compare_numerically():
    assert compare("1.0.0-beta.2", "1.0.0-beta.11") == -1


def test_numeric_identifier_lower_than_alphanumeric():
    assert compare("1.0.0-alpha.1", "1.0.0-alpha.beta") == -1


def test_more_identifiers_wins_when_prefix_equal():
    assert compare("1.0.0-alpha", "1.0.0-alpha.1") == -1
    assert compare("1.0.0-alpha.1.1", "1.0.0-alpha.1") == 1


def test_build_metadata_ignored():
    assert compare("1.0.0+build.1", "1.0.0+build.2") == 0
    assert compare("1.0.0+meta", "1.0.0") == 0


def test_build_metadata_does_not_override_prerelease():
    assert compare("1.0.0-alpha+build", "1.0.0+build") == -1
