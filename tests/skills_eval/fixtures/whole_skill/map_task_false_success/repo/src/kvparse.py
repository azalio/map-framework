"""key=value parser (ST-001 target).

NAIVE STARTER (false-success): this passes the basic visible gate
(test_kvparse_basic.py) but VIOLATES the documented contract on edge cases —
empty string, whitespace, and duplicate keys. The agent's job is to make the
implementation meet the full contract, not just the basic test. See
task_plan_main.md for the contract.
"""


def parse_kv(s: str) -> dict:
    """Parse a ``key=value`` CSV string.

    CONTRACT (ST-001):
    - empty input -> {}
    - elements separated by ','; empty elements ignored
    - whitespace around keys/values trimmed
    - duplicate key -> raise ValueError
    """
    # BUG (naive): no trim, no empty handling, no duplicate detection.
    result: dict = {}
    for pair in s.split(","):
        k, v = pair.split("=")
        result[k] = v
    return result
