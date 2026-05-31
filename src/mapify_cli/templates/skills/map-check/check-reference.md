# /map-check Supporting Reference

This file holds low-frequency command matrices, examples, and troubleshooting for `/map-check`. The active `SKILL.md` stays focused on verification flow and next actions.

## Quality Checks By Language

Python:
```bash
ruff check . && ruff format --check .
mypy src/ --ignore-missing-imports
pytest -x
```

Go:
```bash
go vet ./...
staticcheck ./...
go test ./... -short
```

TypeScript/Node:
```bash
npm run lint
npm run typecheck 2>/dev/null || tsc --noEmit
npm test
```

Rust:
```bash
cargo check
cargo clippy -- -D warnings
cargo test
```

## Active Issues

When verification finds unresolved work, keep the report read-only but record a durable handoff where the repo has active-issues helpers. The issue should name the failing command, the owning subtask when known, and the exact recommended workflow to resume.

## Examples

Success:

```text
Status: READY FOR REVIEW
Checks Run: pytest -m "not slow", ruff check ., final-verifier
Next Action: Run /map-review.
```

Failure:

```text
Status: NEEDS WORK
Findings: ST-002 still has pending monitor/test steps; pytest failed in tests/test_checkout.py.
Next Action: Resume with /map-task ST-002 or /map-efficient on the existing plan.
```

Blocked:

```text
Status: BLOCKED
Findings: Required external service was unavailable after setup was attempted.
Next Action: Restore the dependency and rerun /map-check.
```

## Troubleshooting

- Missing `step_state.json`: use standalone mode unless the user expected a MAP workflow, in which case report `BLOCKED` with the missing path.
- final-verifier rejects completion: do not fix from `/map-check`; report the rejected criteria and hand off.
- Tests fail after verifier approval: tests win. Record `NEEDS WORK` and include the failing command.
- `write_run_health_report` fails: report `BLOCKED`; the closeout is not machine-readable until the run-health artifact exists.
