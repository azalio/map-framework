# /map-efficient Supporting Reference

This file holds low-frequency MAP Efficient details so `SKILL.md` stays focused on the active state-machine path.

## Wave Execution

Sequential is default. Parallel execution is allowed only when a wave has satisfied dependencies, low risk, and disjoint new-file writes, or when the user explicitly requests it. Use `get_wave_step`, `validate_wave_step`, and `advance_wave`; do not mix wave APIs with the single-current-subtask API.

## Predictor Recovery

Invoke Predictor after repeated Monitor failures, medium/high-risk subtasks, or explicit `escalation_required=true`. Predictor output should guide the next Actor attempt, not replace Monitor validation.

## TDD Details

`--tdd` inserts TEST_WRITER and TEST_FAIL_GATE before ACTOR. Tests must fail for the right reason before implementation starts. For clean-session TDD handoff, prefer `/map-tdd ST-001` then `/map-task ST-001`.

## Final Verifier Retry Policy

If final-verifier returns REVISE, fix only the missing contract evidence or failing behavior and rerun verification. If the same class of failure repeats, check the circuit breaker before another loop.

## Examples

Standard:
```text
/map-efficient implement approved checkout plan
```

TDD:
```text
/map-efficient --tdd implement token refresh
```

Resume existing plan:
```text
/map-efficient continue current branch plan
```

## Troubleshooting

- Blueprint validation fails: fix the decomposer output before Actor starts.
- `step_state.json` disagrees with artifacts: use orchestrator commands, not manual state edits.
- Monitor loops: preserve each failure in `code-review-N.md`, then invoke Predictor when escalation rules apply.
- Final closeout lacks `run_health_report.json`: rerun the closeout command with explicit `RUN_HEALTH_STATUS`.
