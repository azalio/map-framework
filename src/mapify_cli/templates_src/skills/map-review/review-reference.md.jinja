# /map-review Supporting Reference

This file contains lower-frequency review details. Keep `SKILL.md` focused on the active review sequence.

## Section Rubrics

- Architecture: boundaries, lifecycle, coupling, public API behavior, stage consumption.
- Code Quality: simplicity, naming, duplication, error handling, maintainability.
- Tests: changed behavior, failure cases, fixtures, coverage of acceptance tags.
- Performance: hot paths, large artifacts, prompt budgets, avoid speculative micro-optimizations.

## Compare Orderings

When `--compare-orderings` is set, collect one run with `ordering_label='default'`, collect one with `ordering_label='reverse'`, aggregate with `compare-review-runs`, then persist with `record-review-ordering`. Treat verdict drift as review evidence.

## What-To-Delete Lens

When `.map/config.yaml` sets `minimality` to `lite`, `full`, or `ultra`, `build_review_prompts` emits an additional advisory `complexity_lens` prompt. It is deliberately not emitted for `minimality: off` or missing config.

The lens hunts only over-engineering in the current diff and reports one line per finding:

```text
L<line>: <tag> <what>. <replacement>.
net: -<N> lines possible.
```

Allowed tags:
- `delete:` dead code, unused flexibility, or speculative feature; replacement is nothing.
- `stdlib:` hand-rolled behavior the standard library already ships; name the function.
- `native:` dependency or code doing what the platform already does; name the feature.
- `yagni:` abstraction with one implementation, config nobody sets, or a layer with one caller.
- `shrink:` same logic in fewer clear lines; show the shorter form.

If nothing should be cut, the entire output is:

```text
Lean already. Ship.
```

Boundaries: complexity only. Correctness, security, and performance findings stay in the normal Monitor/Evaluator pass. A single smoke test or assert-based self-check is the minimum and must not be flagged for deletion. The lens samples and verifies `map:simplification:` marker claims; the marker is evidence, not an exemption. `net: -N` is post-hoc and advisory only: do not feed it into Actor retry context, do not use it for PROCEED/REVISE/BLOCK, and do not let it incentivize deleting necessary code.

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
