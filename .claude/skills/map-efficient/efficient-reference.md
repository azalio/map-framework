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
JSON envelope (`valid`, `summary`, `issues`). Detect via
`detect_truncated_agent_output --agent monitor`; if truncated, log via
`log_agent_failure --agent monitor --phase post-invoke --failure-label truncated --reasons '<reasons>'`
and re-invoke ONCE using the prompt from
`build_json_retry_prompt --agent monitor --errors '<reasons>'`; if still
malformed, stop with CLARIFICATION_NEEDED.

### Actor truncated-response gate (full)

Before invoking Monitor, validate Actor's response is JSON with required
keys (`files_changed`, `tests_run`):

```bash
echo "$ACTOR_OUTPUT" | python3 .map/scripts/map_step_runner.py \
    detect_truncated_agent_output --agent actor
```

If `truncated: true`:
1. Log via `log_agent_failure --agent actor --phase pre-monitor --failure-label truncated --reasons '<reasons>'`
   and re-invoke Actor ONCE using the prompt from
   `build_json_retry_prompt --agent actor --errors '<reasons>'`.
2. If still malformed, stop with CLARIFICATION_NEEDED.

**Files-changed mismatch check (MANDATORY):** After the JSON envelope is
confirmed intact, run:

```bash
FILES_DECLARED=$(echo "$ACTOR_OUTPUT" | jq -r '.files_changed | join(",")')
MISMATCH=$(detect_actor_files_changed_mismatch "$BRANCH" "$SUBTASK_ID" \
  --declared "$FILES_DECLARED")
echo "$MISMATCH"
STATUS_MISMATCH=$(echo "$MISMATCH" | jq -r '.status_mismatch')
```

- `status_mismatch == true` — Actor declared files it did not write (mid-edit
  truncation). Read `recovery_instruction` from the JSON and re-invoke the
  Actor to finish the `declared_not_written` files. Do NOT record the subtask
  until the mismatch clears.
- `status_mismatch == false` — no mismatch; proceed to Monitor.

## Symbol blast-radius gate

Per-subtask Monitor validates only the files the current subtask touched — it
is structurally blind to callers of a changed symbol that live in OTHER files
(other skills, workflows, or utilities). The canonical miss: a shared helper is
renamed or its signature changes, and every caller outside `affected_files`
breaks silently.

Before dispatching Monitor, run the blast-radius detector:

```bash
BLAST=$(python3 .map/scripts/map_step_runner.py \
  detect_symbol_blast_radius "$BRANCH" "$SUBTASK_ID")
echo "$BLAST"   # inspect changed_symbols / external_callers / reason
GATE=$(echo "$BLAST" | jq -r '.recommended_gate')
```

- `recommended_gate == "validate_callers"` — the subtask changed a
  module-level symbol referenced OUTSIDE its `affected_files`. You MUST:
  1. Append the `external_callers` list to the Monitor `<documents>` context.
  2. Require Monitor to validate the contract of EACH external caller (not
     just the current subtask's files).
  3. Do NOT accept a Monitor pass that ignores the external callers — this is
     the guard that catches a shared-symbol refactor breaking another workflow.
- `recommended_gate == "none"` — no external callers affected; proceed to
  Monitor dispatch without modification.

It is read-only and exits 0 always; callers branch on `recommended_gate`.

## Cross-subtask regression gate

Per-subtask Monitor validates only the current subtask's contract and the
files it touched — it is structurally blind to regressions this change induces
on *prior* subtasks' code. The canonical miss (run `new-road-quantum`): ST-009
edited `chunked_review_pipeline.py`, a file seven earlier subtasks shared, and
broke a stub-path test that only surfaced at the final full-suite gate, eight
subtasks later.

Before the post-Monitor test gate, ask the deterministic detector whether a
scoped run is safe:

```bash
RISK=$(python3 .map/scripts/map_step_runner.py \
  detect_cross_subtask_regression_risk "$BRANCH" "$SUBTASK_ID")
echo "$RISK"   # inspect shared_source_files / prior_owners / reason
GATE=$(echo "$RISK" | jq -r '.recommended_gate')
```

- `recommended_gate == "full_suite"` — the current diff overlaps a file a
  prior subtask owned, OR the diff couldn't be computed (git error, fail-safe).
  You MUST run the FULL test suite (never a `-k`-filtered subset) before
  commit / `record_subtask_result`. A scoped run cannot catch a cross-subtask
  regression and is exactly how this bug class reaches the final gate.
- `recommended_gate == "scoped"` — no overlap with prior subtasks; a targeted
  run is sufficient. (Overlap on test-only files stays `scoped` — a shared
  test edit can't regress another subtask's production code.)

It is read-only and exits 0 always; callers branch on `recommended_gate`.

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

## Proactive blueprint refresh (recommended)

Re-sync a subtask's `affected_files` against the actual diff BEFORE
its RESEARCH starts, so decomposer's stale path/symbol guesses from
planning time don't leak into research → Actor → Monitor.

```bash
python3 .map/scripts/map_step_runner.py refresh_blueprint_affected_files \
  "$BRANCH" "$SUBTASK_ID" --dry-run   # preview the proposed write
python3 .map/scripts/map_step_runner.py refresh_blueprint_affected_files \
  "$BRANCH" "$SUBTASK_ID"             # commit the refresh
```

When to call:
- At the start of every subtask's RESEARCH phase (covers planning-time
  path drift for THIS subtask).
- After a clean Monitor close (already documented in the per-subtask
  commit section above — covers reality lock for the just-completed
  subtask).

## Troubleshooting

- Blueprint validation fails: fix the decomposer output before Actor starts.
- `step_state.json` disagrees with artifacts: use orchestrator commands, not manual state edits.
- Monitor loops: preserve each failure in `code-review-N.md`, then invoke Predictor when escalation rules apply.
- Final closeout lacks `run_health_report.json`: rerun the closeout command with explicit `RUN_HEALTH_STATUS`.
