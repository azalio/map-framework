# Task Plan (branch: main)

## Subtasks

### ST-001 — Implement semver compare()

Implement `compare(a, b)` in `src/semver.py` to satisfy the full contract in
`tests/test_semver.py` (semver 2.0.0 precedence: numeric field comparison,
pre-release < release, pre-release identifier ordering, build-metadata ignored).

- affected_files: `src/semver.py`
- validation: `python -m pytest tests/test_semver.py -q` passes
