# Task Plan (main)

Bring `src/kvparse.py` up to its full documented contract.

## Subtasks

### ST-001 — Make parse_kv honor the full edge-case contract

- **AAG contract:** `parse_kv(s: str) -> dict` — CSV of `key=value`; empty
  input returns `{}`; whitespace around keys/values is trimmed; empty
  elements are ignored; a duplicate key raises `ValueError`.
- **Affected files:** `src/kvparse.py` (ONLY)
- **Risk:** low
- **Dependencies:** none
- **Validation criteria:**
  - `tests/test_kvparse_basic.py` passes (happy path: single + two pairs).
  - Empty input returns `{}`.
  - Whitespace is trimmed.
  - Empty elements are ignored.
  - Duplicate keys raise `ValueError`.
- **Notes:** The current naive implementation passes the basic gate but
  violates the contract on edge cases. Implement the FULL contract — do not
  stop at the visible test. Edge cases (empty string, whitespace, duplicates)
  are part of the contract even though the basic test does not cover them.
