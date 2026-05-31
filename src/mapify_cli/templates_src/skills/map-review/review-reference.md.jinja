# /map-review Supporting Reference

This file contains lower-frequency review details. Keep `SKILL.md` focused on the active review sequence.

## Section Rubrics

- Architecture: boundaries, lifecycle, coupling, public API behavior, stage consumption.
- Code Quality: simplicity, naming, duplication, error handling, maintainability.
- Tests: changed behavior, failure cases, fixtures, coverage of acceptance tags.
- Performance: hot paths, large artifacts, prompt budgets, avoid speculative micro-optimizations.

## Compare Orderings

When `--compare-orderings` is set, collect one run with `ordering_label='default'`, collect one with `ordering_label='reverse'`, aggregate with `compare-review-runs`, then persist with `record-review-ordering`. Treat verdict drift as review evidence.

## Examples

Plain review:
```text
/map-review correctness first
```

Detached review:
```text
/map-review --detached
```

CI review:
```text
/map-review --ci
```

Ordering drift check:
```text
/map-review --compare-orderings
```

## Troubleshooting

- Detached prep unavailable: continue from the in-place review bundle; do not mutate the source branch.
- Missing bundle: rerun `create_review_bundle` before agents.
- Prompt clipping: inspect `.map/<branch>/token_budget.json`, then raise `MAP_REVIEW_PROMPT_BUDGET_TOKENS` only when the bundle evidence is actually missing.
- Monitor invalid: treat as hard stop and record `REVISE` or `BLOCK`.
