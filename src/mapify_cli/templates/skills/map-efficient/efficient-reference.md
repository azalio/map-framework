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

## Per-subtask commit recipe (full version)

Triggered by Monitor's clean verdict. Stage named files only (no `git add .`),
commit with the subtask id in the subject, then record the result and validate.

```bash
git add <files from Monitor's files_changed>
git commit -m "ST-NNN: <one-line summary>"
SHA=$(git log -1 --format=%H)
python3 .map/scripts/map_orchestrator.py record_subtask_result \
  "$SUBTASK_ID" valid --files "$FILES_CSV" --summary "$ONE_LINE" \
  --commit-sha "$SHA"
RECOMMENDATION=$(jq -r '.recommendation // empty' <<< "$MONITOR_JSON")
python3 .map/scripts/map_orchestrator.py validate_step 2.4 \
  --recommendation "$RECOMMENDATION"
python3 .map/scripts/map_step_runner.py refresh_blueprint_affected_files \
  "$BRANCH" "$SUBTASK_ID"
```

When NOT to commit per-subtask:
- Subtask is part of a wave whose other subtasks haven't closed AND the work
  doesn't independently compile/pass tests — finish the wave first.
- The user explicitly asked for a single bundled commit.
- Pre-commit hooks would block on intermediate state that's only valid after
  the wave completes. Document the deferral in the subtask summary.

Never `--no-verify`. Never amend a published commit.

## Truncated agent response detection (full recipes)

### Monitor truncated-response gate (full)

Before reading `valid`/`recommendation`, confirm Monitor returned a complete
JSON envelope (`valid`, `summary`, `issues`). Re-prompt once with "emit ONLY
the JSON object" and stop with CLARIFICATION_NEEDED if truncation repeats.

### Actor truncated-response gate (full)

Before invoking Monitor, validate Actor's response is JSON with required
keys (`files_changed`, `tests_run`):

```bash
echo "$ACTOR_OUTPUT" | python3 .map/scripts/map_step_runner.py \
    detect_truncated_agent_output --agent actor
```

If `truncated: true`:
1. Re-invoke Actor with the same prompt plus "Your previous response was cut
   off — finish the implementation and emit ONLY the JSON envelope".
2. If still truncated, stop with CLARIFICATION_NEEDED.
3. Cross-check `files_changed` against `git diff --name-only`. Files
   declared but not in the diff = Actor said it changed them but didn't.

## Pre-flight test baseline

Snapshot pre-existing failures BEFORE any subtask executes so later
subtasks distinguish "I introduced this regression" from "this was
broken before plan started". Without baseline, repo-wide red doesn't
surface until final-verifier and the operator can't tell whether to
fix or defer.

```bash
python3 .map/scripts/map_step_runner.py record_test_baseline "$BRANCH"
```

Auto-detects from project markers:
- `Makefile` with `test:` target → `make test`
- `pyproject.toml` / `pytest.ini` → `pytest`
- `go.mod` → `go test ./...`
- `Cargo.toml` → `cargo test`

Override the auto-detect when the full run is too slow for a
pre-flight (or you want a narrower target):
```bash
python3 .map/scripts/map_step_runner.py record_test_baseline "$BRANCH" \
  --command "pytest tests/smoke" --timeout 60
```

Persists to `.map/<branch>/test_baseline.json`. Parse pre-existing
failures back via:
```bash
python3 .map/scripts/map_step_runner.py list_baseline_failures "$BRANCH"
```

Each subtask's failing test now has a clean disposition: in baseline ⇒
pre-existing, route to follow-up subtask; NOT in baseline ⇒ this
plan introduced it, fix here.

## Troubleshooting

- Blueprint validation fails: fix the decomposer output before Actor starts.
- `step_state.json` disagrees with artifacts: use orchestrator commands, not manual state edits.
- Monitor loops: preserve each failure in `code-review-N.md`, then invoke Predictor when escalation rules apply.
- Final closeout lacks `run_health_report.json`: rerun the closeout command with explicit `RUN_HEALTH_STATUS`.
