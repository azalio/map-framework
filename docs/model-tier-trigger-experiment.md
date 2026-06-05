# Model-Tier Trigger-Accuracy Experiment

> Empirical test of "does the model tier matter for skill **trigger routing**?"
> Motivated by Murin 2026 (arXiv:2606.05970), whose central finding is that
> **model choice dominates prompt phrasing** for structured extraction, and that
> a larger model **redistributes** agreement rather than uniformly raising it.
> Here we test the analog in the MAP domain: skill auto-activation accuracy.

## Method

- Tool: `mapify skill-eval run <skill> --eval-set <fixture> --model <tier>` (the
  `--model` flag was added for this experiment; default omits it → CLI session model).
- Skill: `map-check` (eval-set: 6 positives + 3 negatives, 9 cells).
- Models: `haiku`, `sonnet`, `opus` — same eval-set, one pass each (n=9 per model).
- Each cell = one seeded `claude -p` with heavy tools disallowed; trigger read from
  the transcript's first `Skill` tool_use. Deterministic-decoding is NOT guaranteed
  (no temp flag via `claude -p`), so single-pass results carry run noise.

## Result (2026-06-05)

| prompt | expect | haiku | sonnet | opus |
|---|---|---|---|---|
| p0 Run the quality gates — lint, types, tests | map-check | ✗ None | ✓ map-check | ✓ map-check |
| p1 Lint, type-check, and run the full test suite now | map-check | ✗ None | ✗ None | ✗ None |
| p2 Verify the MAP workflow is complete and consistent | map-check | ✓ | ✓ | ✓ |
| p3 Confirm this MAP run is actually done | map-check | ✓ | ✓ | ✓ |
| p4 Run make check and validate everything passes | map-check | ✓ | ✗ None | ✗ None |
| p5 Validate that the workflow finished correctly | map-check | ✗ None | ✓ map-check | ✗ None |
| p6 Decompose the new feature into atomic subtasks | NOT map-check | ✓ (silent) | ✓ →map-plan | ✓ →map-plan |
| p7 Implement this change end-to-end with full workflow | NOT map-check | ✓ (silent) | ✓ →map-state | ✓ (silent) |
| p8 Show me the token cost breakdown for this branch | NOT map-check | ✓ →map-tokenreport | ✓ →map-tokenreport | ✓ →map-tokenreport |
| **Accuracy** | | **6/9 (67%)** | **7/9 (78%)** | **6/9 (67%)** |
| mean latency | | **26 s** | 51 s | 51 s |

## Findings

1. **Bigger ≠ better for trigger routing.** Opus (67%) did NOT beat Sonnet (78%)
   and only tied Haiku (67%) — at 2× Haiku's latency. The model tier provides no
   reliable trigger-accuracy gain. (n=9, single-pass — treat the 67/78/67 spread
   as within noise; the *qualitative* points below are the robust signal.)
2. **Redistribution, not uniform improvement** — exactly Murin's per-field result.
   No model dominates cell-by-cell: Sonnet caught p0+p5 that Haiku missed but lost
   p4; Opus lost both p4 and p5. Changing the model *reshuffles* which prompts
   route correctly rather than monotonically improving them.
3. **The description, not the model, is the bottleneck.** p1 ("Lint, type-check,
   and run the full test suite now.") was missed by ALL THREE tiers — a routing
   gap no model size fixes. This is precisely what the **description optimizer**
   targets. The lever for trigger accuracy is the trigger `description:`, not the
   model — consistent with the project's earlier "contract/prose is the lever,
   model competence is largely fixed" lesson.
4. **Negatives are robust across all tiers** — no tier ever falsely fired
   `map-check`. Bigger models additionally route the negative prompts to the
   *correct other* skill (map-plan / map-state / map-tokenreport) instead of just
   staying silent, i.e. they are more *decisive* about positive routing, but this
   did not translate into higher map-check accuracy.

## Implications for model tiering in MAP

- **Skill trigger routing / `skill-eval` dispatcher → Haiku is sufficient.** Equal
  accuracy to Opus at half the latency. Do not pay Opus for routing. Invest in the
  `description:` instead (the optimizer sweep).
- **Execution agents are a SEPARATE question this experiment did not measure.**
  Trigger routing ≠ task-execution quality. Murin's "larger model categorizes more
  specifically" plausibly applies to the actual work (actor code-gen, decomposer
  producing many specific subtasks, verifier). The framework's current opus
  assignments (task-decomposer, final-verifier, debate-arbiter) target exactly
  those specificity/hard-reasoning roles and are NOT contradicted here.
- **Next test (if pursued):** repeat with ≥3 passes/model for significance, extend
  to 2-3 more skills for generalization, and — separately — measure execution
  quality (not just routing) for actor/monitor across tiers.

## Current framework model assignments (for reference)

opus: task-decomposer, final-verifier, debate-arbiter ·
sonnet: actor, monitor, evaluator, predictor, synthesizer, reflector, documentation-reviewer ·
haiku: research-agent ·
skill-eval dispatcher/proposer: CLI session default (no pin).
