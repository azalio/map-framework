# Task Plan (branch: main)

## Subtasks

### ST-001 — Implement semver compare()

Implement `compare(a, b)` in `src/semver.py` so it correctly compares two
semantic-version strings. Make `tests/test_semver_basic.py` pass.

- affected_files: `src/semver.py`
- validation: `python -m pytest tests/test_semver_basic.py -q` passes
