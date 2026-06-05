# Task Plan (branch: main)

## Subtasks

### ST-001 — Implement semver compare()

Implement `compare(a, b)` in `src/semver.py` per the full semver 2.0.0 precedence
contract (see blueprint aag_contract). The shipped gate
`tests/test_semver_basic.py` checks only trivial cases; a correct implementation
must still honour pre-release precedence, numeric identifier comparison, and
build-metadata handling.

- affected_files: `src/semver.py`
- validation: `python -m pytest tests/test_semver_basic.py -q` passes
