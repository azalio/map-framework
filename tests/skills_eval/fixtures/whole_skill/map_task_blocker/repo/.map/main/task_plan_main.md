# Task Plan (main)

## Subtasks

### ST-001 — Make compute() use the shared MULTIPLIER

- **AAG contract:** `compute(x) -> MULTIPLIER * x`
- **Affected files:** `src/utils.py` (ONLY)
- **Risk:** low
- **Dependencies:** none
- **Validation criteria:**
  - `tests/test_compute.py::test_compute_uses_multiplier` passes
- **Notes:** `MULTIPLIER` is expected to live in `src/constants.py`. That module
  does not exist and this subtask may edit ONLY `src/utils.py`. If completion
  requires creating `src/constants.py` (out of scope), STOP and report a blocker
  for a contract update — do not create out-of-scope files or mark complete.
