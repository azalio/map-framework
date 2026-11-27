# $map-check Supporting Reference

This file holds low-frequency command matrices, examples, and troubleshooting for `$map-check`. The active `SKILL.md` stays focused on verification flow and next actions.

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

## Mutation checks

With `$map-check --mutations PLAN.json`, run the following from the candidate Git root using the project's Python with pytest installed.

```sh
python .map/scripts/mutation_check.py PLAN.json
```

Use a plan supplied by the developer. Each replacement describes a plausible fault in the changed implementation and the selected tests exercise one public behavior. For example, given a function whose threshold is ten:

```json
{
  "criterion": "An order of exactly ten items earns the discount",
  "tests": ["tests/test_price.py::test_discount"],
  "mutations": [
    {"path": "price.py", "before": "quantity >= 10", "after": "quantity > 10",
     "effect": "deny the discount at exactly ten items"}
  ]
}
```

Select test files or pytest node IDs with repository-relative paths. Use enough context in `before` to match exactly once. `--limit` defaults to 3 changes, `--timeout` to 30 seconds per test invocation and `--total-timeout` to 180 seconds for the run. Cleanup of an owned process group can take additional time. The check uses a fresh copy of the tracked and non-ignored untracked working files for each trial. It omits Git metadata, ignored build products and `.map` state. Install dependencies in the Python environment first. Use local tests that run from a copy of the checkout. This is workspace isolation for trusted tests.

The runner prints a short summary on stderr and the full report as JSON on stdout. Each report has a unique path under `.map/mutation-checks/`. To compare its recorded inputs with the current checkout, run `python .map/scripts/mutation_check.py --check-report PATH/TO/report.json`.

- `detected` records the test and assertion line. A fresh clean run must pass and a second mutant run must fail at the same assertion. If the test calls a CLI, check its output after the command succeeds. A failed child process or an unverified exit makes the assertion inconclusive.
- `survived` identifies the change the tests missed. Report it with the criterion and the selected test. When strengthening a frozen proof, use the existing `request_acceptance_revision` and independent TEST_WRITER flow, then rerun the same plan.
- `invalid` covers an inapplicable replacement or invalid Python source. `inconclusive` covers timeout, collection/setup errors and failures that cannot be attributed to a selected test assertion. `not_run` identifies a candidate outside the budget or behind a failing baseline.
- `equivalent` records identical compiled Python code on this interpreter and a passing trial. This comparison concerns executable code. Tests that inspect source text need separate evidence.

A measurement exits with code 0 when the inputs are current, at least one mutation is detected and every other mutation is detected or equivalent. With `--check-report`, exit code 0 means the inputs still match, regardless of the recorded result. These measurements are separate from acceptance receipts.

## Docs Drift

`.map/scripts/docs_drift.py` (stdlib only) checks claims outside fenced code blocks:

| Kind | Claim | Resolved when |
|------|-------|---------------|
| `missing_path` | backticked repo path (`src/app.py`, `docs/x.md`) | exists at repo root, next to the doc, as a path suffix anywhere, or is named as a literal in source (runtime artifacts the code writes) |
| `missing_link` | relative Markdown link target | exists relative to the doc |
| `unknown_flag` | `--flag` inside backticks | the literal flag appears in the source corpus |
| `flag_default_mismatch` | `--flag` (default: `X`) | source definition (`default=`, typer `Option(X, "--flag")`) agrees, or has no literal default |
| `undefined_symbol` | backticked `snake_case`, `camelCase`, `CONST_NAME`, `dotted.key` | the identifier appears in the source corpus |

The source corpus is every non-doc text file (`*.md`, `*.rst`, `*.txt` excluded) outside VCS, virtualenv, cache, build, and `.map/` dirs.

Skipped on purpose: fenced code blocks (examples), URLs, absolute and home paths, placeholders and globs (`<path>`, `{x}`, `$VAR`, `*.py`, `...`), hyphenated names, plain lowercase words, and paths under ignored dirs.

Known false positives: flags built dynamically (`f"--{role}-file"`) and third-party names (`HF_TOKEN`). Silence a line with `<!-- drift-ignore -->` on the line itself or alone on the line above. Behavioral prose ("retries 3 times") is never decided mechanically; lines that mention a resolved code reference plus a number or behavior verb become `semantic_candidates` for the fresh-context reader.

## Active Issues

When verification finds unresolved work, keep the report read-only but record a durable handoff where the repo has active-issues helpers. The issue should name the failing command, the owning subtask when known, and the exact recommended workflow to resume.

## Examples

Success:

```text
Status: READY FOR REVIEW
Checks Run: pytest -m "not slow", ruff check ., final-verifier
Next Action: Run $map-review.
```

Failure:

```text
Status: NEEDS WORK
Findings: ST-002 still has pending monitor/test steps; pytest failed in tests/test_checkout.py.
Next Action: Resume with $map-task ST-002 or $map-efficient on the existing plan.
```

Blocked:

```text
Status: BLOCKED
Findings: Required external service was unavailable after setup was attempted.
Next Action: Restore the dependency and rerun $map-check.
```

## Troubleshooting

- Missing `step_state.json`: use standalone mode unless the user expected a MAP workflow, in which case report `BLOCKED` with the missing path.
- final-verifier rejects completion: do not fix from `$map-check`; report the rejected criteria and hand off.
- Tests fail after verifier approval: tests win. Record `NEEDS WORK` and include the failing command.
- `write_run_health_report` fails: report `BLOCKED`; the closeout is not machine-readable until the run-health artifact exists.
