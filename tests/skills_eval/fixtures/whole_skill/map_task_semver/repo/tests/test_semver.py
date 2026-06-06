"""Full contract for src/semver.compare (semver 2.0.0 precedence).

These tests ARE the spec. A naive implementation (string compare, or ignoring
pre-release rules) passes the easy cases but fails the edge cases below.
"""
from src.semver import compare


# --- core numeric precedence ------------------------------------------------
def test_equal_versions():
    assert compare("1.0.0", "1.0.0") == 0


def test_major_minor_patch_ordering():
    assert compare("1.0.0", "2.0.0") == -1
    assert compare("2.1.0", "2.0.9") == 1
    assert compare("1.0.1", "1.0.0") == 1


def test_numeric_fields_compare_numerically_not_lexically():
    # 1.10.0 > 1.9.0 (a naive string/char compare gets this WRONG: "10" < "9")
    assert compare("1.10.0", "1.9.0") == 1
    assert compare("1.0.10", "1.0.9") == 1
    assert compare("2.0.0", "10.0.0") == -1


def test_returns_only_minus_one_zero_one():
    for r in (compare("1.2.3", "1.2.4"), compare("1.2.3", "1.2.3"), compare("1.2.4", "1.2.3")):
        assert r in (-1, 0, 1)


# --- pre-release vs release -------------------------------------------------
def test_prerelease_has_lower_precedence_than_release():
    # 1.0.0-alpha < 1.0.0  (a naive impl that ignores pre-release gets 0 here)
    assert compare("1.0.0-alpha", "1.0.0") == -1
    assert compare("1.0.0", "1.0.0-alpha") == 1


# --- pre-release identifier ordering (the canonical semver example) ---------
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
    # beta.2 < beta.11 numerically (naive lexical compare gets "11" < "2")
    assert compare("1.0.0-beta.2", "1.0.0-beta.11") == -1


def test_numeric_identifier_lower_than_alphanumeric():
    # a field of only digits has lower precedence than one with letters
    assert compare("1.0.0-alpha.1", "1.0.0-alpha.beta") == -1


def test_more_identifiers_wins_when_prefix_equal():
    # a larger set of pre-release fields > a smaller set, if all preceding equal
    assert compare("1.0.0-alpha", "1.0.0-alpha.1") == -1
    assert compare("1.0.0-alpha.1.1", "1.0.0-alpha.1") == 1


def test_equal_prereleases():
    assert compare("1.0.0-beta.11", "1.0.0-beta.11") == 0


# --- build metadata is ignored for precedence -------------------------------
def test_build_metadata_ignored():
    assert compare("1.0.0+build.1", "1.0.0+build.2") == 0
    assert compare("1.0.0+meta", "1.0.0") == 0
    assert compare("1.0.0-alpha+x", "1.0.0-alpha+y") == 0


def test_build_metadata_does_not_override_prerelease():
    # pre-release rule still applies even with build metadata present
    assert compare("1.0.0-alpha+build", "1.0.0+build") == -1
