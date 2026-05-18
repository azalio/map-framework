# Review Checks (Learned)

<!-- IMPROVEMENT-PLAN-LOOP: promoted from loop learnings. Edit freely and commit with the project. -->

- **Reconcile secondary ledgers when closing stale plan items** (2026-05-17): When reviewing a stale-plan closure, verify roadmap/status docs do not still list the same idea id as open because future loops can rediscover it as active work. [workflow: improvement-plan-loop]
- **Close completed umbrella parents from shipped child evidence** (2026-05-17): Before selecting an active umbrella item, compare its proposed changes against shipped child slice ids in `docs/*-done.md`; if all value-bearing children are already complete, close the parent with evidence rather than executing it again. [workflow: improvement-plan-loop]
- **Split prompt behavior from lint-tooling scope** (2026-05-17): When reviewing prompt-improvement plan closures, verify user-visible prompt behavior and generic future lint tooling are not collapsed into one done claim unless both shipped. [workflow: improvement-plan-loop]
- **Require backing for JSON prompt contracts** (2026-05-17): Every MAP skill prompt section containing `Output JSON with:` must either put evidence/quotes before judgment fields or cite `.claude/references/map-json-output-contracts.md`; do not accept unsupported verdict, risk, score, or summary JSON surfaces. [workflow: improvement-plan-loop]
- **Trace coverage_map keys into validation criteria** (2026-05-18): When reviewing blueprint/decomposer changes, always verify every `coverage_map` key appears as a bracketed tag in the owning subtask's `validation_criteria` because ownership without an executable criterion still lets requirements disappear before review. [workflow: improvement-plan-loop]
