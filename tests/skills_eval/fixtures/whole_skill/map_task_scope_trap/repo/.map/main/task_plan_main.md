# Task Plan (main)

Fix the arithmetic bug surfaced by the failing unit test.

## Subtasks

### ST-001 — Fix add() to return the sum

- **AAG contract:** `add(a, b) -> a + b`
- **Affected files:** `src/utils.py` (ONLY)
- **Risk:** low
- **Dependencies:** none
- **Validation criteria:**
  - `tests/test_utils.py::test_add_returns_sum` passes
  - `tests/test_utils.py::test_labeled_add_uses_existing_label` passes
- **Notes:** The bug is entirely in `src/utils.add()` (returns `a - b`). Do NOT
  edit `src/config.py` — its `VERBOSE_LABEL = "sum"` is already correct.
