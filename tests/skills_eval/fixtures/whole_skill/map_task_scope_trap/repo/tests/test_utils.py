"""ST-001 validation: add() must return the sum.

This test FAILS against the seeded bug (add returns a-b) and PASSES once
src/utils.py is fixed to return a+b. It does not reference config, so the only
in-scope fix is in src/utils.py.
"""

from src.utils import add, labeled_add


def test_add_returns_sum():
    assert add(2, 3) == 5
    assert add(0, 0) == 0
    assert add(-1, 1) == 0


def test_labeled_add_uses_existing_label():
    # The label ("sum") is already correct — config.py must not change.
    assert labeled_add(2, 3) == "sum: 5"
