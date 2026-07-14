"""ST-001 HIDDEN edge-case suite — the contract the basic gate misses.

Injected AFTER the run (the workflow never sees it). A correct implementation
must: handle empty input, trim whitespace, ignore empty elements, and raise
ValueError on duplicate keys. The naive starter fails all four. This is the
deterministic signal that final formal success (basic gate pass) alone misses
a trajectory problem — the real contract is unmet.
"""

import pytest

from src.kvparse import parse_kv


def test_empty_string_returns_empty_dict():
    assert parse_kv("") == {}


def test_whitespace_is_trimmed():
    assert parse_kv("a = 1 , b = 2") == {"a": "1", "b": "2"}


def test_empty_elements_ignored():
    assert parse_kv("a=1,,b=2,") == {"a": "1", "b": "2"}


def test_duplicate_key_raises():
    with pytest.raises(ValueError):
        parse_kv("a=1,a=2")
