---
name: map-efficient
description: "State-machine MAP execution workflow for Codex. Use when implementing an approved MAP plan end to end, resuming from branch MAP task_plan or step_state.json artifacts, or running non-trivial multi-subtask work. Use map-fast for tiny one-shot edits."
---

# $map-efficient - MAP Execution

Execute the approved MAP plan for the current branch. This skill is the Codex
counterpart to Claude `/map-efficient`, but it uses Codex-native instructions:
skills live under `.agents/skills`, configured Codex subagents live under
`.codex/agents`, and the current Codex session is the write-capable Actor and
final verifier unless an explicit subagent dispatch is available and useful.

Use [efficient-reference.md](efficient-reference.md) for wave details, retry
recipes, TDD mode, commit policy, and troubleshooting. Read only the referenced
section when the workflow below points to it. Under `isolation_active` (Slice 5a),
the wave-loop creates per-member worktrees, dispatches actor subagents
**sequentially** (one per turn), verifies via `concurrency_ready`, then accepts
atomically via `merge_wave_worktrees`; concurrent fan-out is Slice 5b
(`dispatch_mode==concurrent`). Under `dispatch_mode==concurrent` (opt-in via
`execution.concurrent_dispatch: true`), call `run_concurrent_wave`: dispatch N
actor subagents in **one turn** per sub-batch; on any failure `abort_wave_group`
discards the whole group and reruns from base (bounded by `max_wave_retries`).

## Mutation Boundary Constraints

These constraints apply before any write-capable step:

- Do not edit unrelated files, even if they are nearby or easy to clean up.
- Do not add, remove, or upgrade dependencies unless the current subtask contract explicitly names that dependency change.
- Do not refactor neighboring code unless the current validation criteria cannot pass without that exact refactor.
- If a dependency change, broad refactor, or scope expansion seems necessary, report it as a blocker/tradeoff instead of doing it silently.

## Core Rules

1. Run only the next state-machine phase; never skip phases.
2. Treat `.map/<branch>/step_state.json` as the single source of truth.
3. Never edit `step_state.json` manually. Use `.map/scripts/map_orchestrator.py`.
4. Use `.map/scripts/map_step_runner.py` for analysis, reports, baselines, and sidecar artifacts.
5. Continue across subtask boundaries in the same invocation unless blocked, interrupted by the user, or the circuit breaker trips.
6. Use configured Codex subagents (`researcher`, `decomposer`, `monitor`) only when the workflow explicitly needs independent work. The current Codex session performs Actor edits and final verification.
7. Stop on any Monitor `valid=false` verdict and fix the issue before advancing.

## Script Routing

- `python3 .map/scripts/map_orchestrator.py <cmd>` owns state transitions:
  `resume_from_plan`, `get_next_step`, `validate_step`,
  `monitor_failed`, `record_subtask_result`, `check_circuit_breaker`,
  `mark_subtask_complete`, `set_tdd_mode`, `set_waves`.
- `python3 .map/scripts/map_step_runner.py <cmd>` owns read-only analysis and
  sidecar artifacts: `record_test_baseline`, `save_research`, `load_research`,
  `build_context_block`, `detect_truncated_agent_output`,
  `detect_actor_files_changed_mismatch`, `detect_symbol_blast_radius`,
  `detect_cross_subtask_regression_risk`, `run_flaky_test_triage`,
  `record_flaky_test_triage`,
  `validate_flaky_test_triage`, `write_run_health_report`.

## Argument Handling

Parse optional flags, but do not require a task string when a plan or state
already exists.

```bash
TASK_ARGS="$ARGUMENTS"
TDD_FLAG=false
if echo "$TASK_ARGS" | grep -q -- '--tdd'; then
  TDD_FLAG=true
  TASK_ARGS=$(echo "$TASK_ARGS" | sed 's/--tdd//g' | xargs)
fi
```

Empty `$TASK_ARGS` is a stop condition only when all of these are true:

1. `.map/<branch>/step_state.json` is missing.
2. `.map/<branch>/task_plan_<branch>.md` is missing.
3. `$TASK_ARGS` is empty.

Otherwise proceed to resume detection.

## Step 0: Resume Existing State Or Plan

Run this before validating `$TASK_ARGS`.

```bash
BRANCH=$(git rev-parse --abbrev-ref HEAD | sed -E 's|/|-|g; s|[^a-zA-Z0-9_.-]|-|g; s|-{2,}|-|g; s|^-||; s|-$||')
STATE_FILE=".map/${BRANCH}/step_state.json"
PLAN_FILE=".map/${BRANCH}/task_plan_${BRANCH}.md"

if [ -f "$STATE_FILE" ]; then
  echo "Existing step_state.json found; continuing with get_next_step."
elif [ -f "$PLAN_FILE" ]; then
  RESUME_RESULT=$(python3 .map/scripts/map_orchestrator.py resume_from_plan)
  RESUME_STATUS=$(echo "$RESUME_RESULT" | jq -r '.status')
  if [ "$RESUME_STATUS" != "success" ]; then
    echo "resume_from_plan failed: $RESUME_RESULT" >&2
    exit 1
  fi
elif [ -z "$TASK_ARGS" ]; then
  echo "No task, step_state.json, or task_plan_${BRANCH}.md found." >&2
  echo "Provide a task or run \$map-plan first." >&2
  exit 1
fi

if [ "$TDD_FLAG" = "true" ]; then
  python3 .map/scripts/map_orchestrator.py set_tdd_mode true
fi
```

## Step 1: Get The Next Phase

```bash
NEXT_STEP=$(python3 .map/scripts/map_orchestrator.py get_next_step)
STEP_ID=$(echo "$NEXT_STEP" | jq -r '.step_id')
PHASE=$(echo "$NEXT_STEP" | jq -r '.phase')
IS_COMPLETE=$(echo "$NEXT_STEP" | jq -r '.is_complete')
echo "$NEXT_STEP"
```

If `IS_COMPLETE=true`, go to final verification.

## Step 2: Execute The Current Phase

Execute only the phase returned by `get_next_step`.

### DECOMPOSE

Use the configured `decomposer` agent when available, or decompose directly in
the current session. Return blueprint JSON with atomic subtasks, dependencies,
validation criteria, hard/soft constraints, coverage_map, and AAG contracts.
Every coverage_map key owned by a subtask must appear as a bracket tag in that
subtask validation criterion, for example `VC1 [AC-1]: checkout retries`.

Save `.map/<branch>/blueprint.json`, then run:

```bash
python3 .map/scripts/map_step_runner.py validate_blueprint_contract
python3 .map/scripts/map_orchestrator.py validate_step "$STEP_ID"
```

### INIT_PLAN

Generate `.map/<branch>/task_plan_<branch>.md` from `blueprint.json`. Include
each subtask's `expected_diff_size`, `concern_type`, `one_logical_step`,
dependencies, AAG contract, acceptance criteria, and verification commands.

Then validate:

```bash
python3 .map/scripts/map_orchestrator.py validate_step "$STEP_ID"
```

### REVIEW_PLAN

Present the plan and require explicit user approval before implementation.
After approval, validate the step.

### INIT_STATE

Let the orchestrator create or update state. Do not write JSON by hand.

```bash
python3 .map/scripts/map_step_runner.py record_test_baseline "$BRANCH"
python3 .map/scripts/map_orchestrator.py validate_step "$STEP_ID"
if [ -f ".map/${BRANCH}/blueprint.json" ]; then
  python3 .map/scripts/map_orchestrator.py set_waves --blueprint ".map/${BRANCH}/blueprint.json"
fi
```

### RESEARCH

Persist a RESEARCH artifact for every non-no-op subtask before Actor. Plan-scope
discovery from `$map-plan` lives at `.map/<branch>/research/plan__discovery.md`
and is automatically included in `build_context_block`; legacy
`.map/<branch>/findings_<branch>.md` is a read-only fallback. Subtask research
must still be saved separately as `.map/<branch>/research/<subtask_id>__actor.md`
so Actor/Monitor can distinguish planner-wide context from current-subtask
evidence. Use `researcher` when independent exploration is useful: cold-start
repository exploration, 3+ existing files, high risk, unclear locations, or
failed direct search. Otherwise research in the current session and save concise
strict-JSON findings — exact field table + copy-pasteable skeleton in
[efficient-reference.md](efficient-reference.md) under "RESEARCH artifact schema"
(`validate_research` also echoes that skeleton in its `skeleton` field on any
failure). If the subtask truly needs no Actor/Monitor, use
`mark_subtask_complete --reason` instead of closing RESEARCH. Validate the
research contract, then close RESEARCH before Actor work:

```bash
SUBTASK_ID=$(jq -r '.current_subtask_id' ".map/${BRANCH}/step_state.json")
printf '%s' "$RESEARCH_FINDINGS" | \
  python3 .map/scripts/map_step_runner.py save_research "$BRANCH" "$SUBTASK_ID"
python3 .map/scripts/map_step_runner.py validate_research "$BRANCH" "$SUBTASK_ID"
python3 .map/scripts/map_orchestrator.py validate_step "$STEP_ID"
```

Actor must consume high-confidence research before re-exploring: if
`confidence >= 0.7` and `relevant_locations` are present, first read 1-3 cited
ranges that match the subtask. Any later repository-wide `rg`/`grep`/`find`/
`git grep` needs a stated reason, such as low confidence, missing symbol, failed
narrow read, changed hypothesis, or stale research. Low-confidence or
location-free research may broaden sooner, but the gap must be named.

### TEST_WRITER And TEST_FAIL_GATE

Only run these in TDD mode. Write failing tests first, run them, and proceed to
Actor only when the tests fail for the intended reason. Do not edit production
code in `TEST_WRITER`.

### ACTOR

Load the current contract and research:

```bash
SUBTASK_ID=$(jq -r '.current_subtask_id' ".map/${BRANCH}/step_state.json")
MAP_CONTEXT=$(python3 .map/scripts/map_step_runner.py build_context_block "$BRANCH" "$SUBTASK_ID")
RESEARCH_FINDINGS=$(python3 .map/scripts/map_step_runner.py load_research "$BRANCH" "$SUBTASK_ID")
```

Implement exactly the current subtask. Preserve validation criteria,
coverage_map tags, hard constraints, and documented tradeoffs. Keep edits
inside the current subtask boundary.

Before Monitor, run the required pre-dispatch gates from
[efficient-reference.md](efficient-reference.md#pre-monitor-gates):

```bash
python3 .map/scripts/map_step_runner.py detect_actor_files_changed_mismatch "$BRANCH" "$SUBTASK_ID" --declared "$FILES_CSV"
python3 .map/scripts/map_step_runner.py detect_symbol_blast_radius "$BRANCH" "$SUBTASK_ID"
```

If you captured Actor shell/search commands, optionally pipe them into
`python3 .map/scripts/map_step_runner.py detect_research_consumption_drift "$BRANCH" "$SUBTASK_ID"`.
This detector is advisory only: it reports repeated repository-wide searches
after high-confidence research without blocking normal work.

### MONITOR

Use the configured `monitor` agent when available, or run an independent review
pass in the current session. Validate implementation against the subtask AAG
contract, validation criteria, coverage tags, hard constraints, and relevant
soft constraints.

If Monitor fails:

```bash
python3 .map/scripts/map_orchestrator.py monitor_failed --feedback "$MONITOR_FEEDBACK"
```

Write a durable `.map/<branch>/code-review-N.md` with exact issues and then fix
the current subtask. Do not advance until Monitor passes.

If the failure is inconsistent across repeated identical check runs, record the
run evidence with `run_flaky_test_triage` (or `record_flaky_test_triage` if the
repeated runs were already collected) and validate
`flaky_test_triage.json` before reporting `deferred_nondeterministic`. This is
not a passing gate: do not weaken, skip, or delete the check, and do not return
a silent green. Monitor signals the defer as the third verdict outcome —
`valid:false` plus `disposition {kind:deferred_nondeterministic, check_id}`
(recommendation omitted or `needs_investigation`). Close via the verdict path:
`validate_step 2.4 --disposition deferred_nondeterministic --check-id "<check-id>" --monitor-envelope -`
(honored only when sidecar + envelope back it; deferral is `valid:false`+`deferred:true`,
non-green, exit 0). `defer_flaky_subtask "$SUBTASK_ID" --check-id "<check-id>"`
remains the lower-level direct close. Do not close this with
`validate_step 2.4 --recommendation proceed`.

On a clean pass, run the regression gate and record the subtask:

```bash
python3 .map/scripts/map_step_runner.py detect_cross_subtask_regression_risk "$BRANCH" "$SUBTASK_ID"
python3 .map/scripts/map_orchestrator.py record_subtask_result "$SUBTASK_ID" valid \
  --files "$FILES_CSV" --summary "$ONE_LINE" --commit-sha "$SHA"
python3 .map/scripts/map_orchestrator.py validate_step 2.4 \
  --recommendation "$MONITOR_RECOMMENDATION"
python3 .map/scripts/map_step_runner.py refresh_blueprint_affected_files "$BRANCH" "$SUBTASK_ID"
```

### ADVANCE_SUBTASK

This is a synthetic boundary, not a user checkpoint. Call `get_next_step`
again immediately and continue with the next subtask.

## Step 3: Final Verification

Run final verification for the whole plan, not only the last subtask.

```bash
python3 .map/scripts/map_orchestrator.py check_circuit_breaker
```

Inspect the task plan, state file, artifact manifest, final diff, tests, and
Monitor artifacts. Run the focused and full verification commands required by
the plan. Close only when the implemented behavior and tests satisfy all
subtasks.

Write terminal run health:

```bash
RUN_HEALTH_STATUS="${RUN_HEALTH_STATUS:?complete|pending|blocked|wont_do|superseded}"
python3 .map/scripts/map_step_runner.py write_run_health_report \
  map-efficient \
  "$RUN_HEALTH_STATUS"
```

## Step 4: Final Response

Report completed subtasks, files changed, checks run, final status, and any
remaining blockers. Mention the next command only when useful, such as
`$map-check` for a verification-only pass.
