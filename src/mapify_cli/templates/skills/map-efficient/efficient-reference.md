# /map-efficient Supporting Reference

This file holds low-frequency MAP Efficient details so `SKILL.md` stays focused on the active state-machine path.

## Script Routing (dispatcher reference)

Two CLI scripts back the workflow; calling the wrong one fails with `invalid choice`. Route by purpose, not by name prefix:

- **`python3 .map/scripts/map_orchestrator.py <cmd>`** — state-machine transitions and step-state writes:
  `get_next_step`, `peek_current_step`, `validate_step`, `initialize`, `set_plan_approved`, `set_execution_mode`, `set_tdd_mode`, `skip_step`, `set_subtasks`, `mark_contract_ready`, `resume_from_plan`, `resume_from_test_contract`, `check_circuit_breaker`, `set_waves`, `get_wave_step`, `validate_wave_step`, `advance_wave`, `resume_single_subtask`, `get_plan_progress`, `monitor_failed`, `wave_monitor_failed`, `defer_flaky_subtask`, `reopen_for_fixes`, `mark_workflow_complete`, `archive`, `mark_subtask_complete`, `record_subtask_result`, `backfill_subtask_ids`, `finalize_plan`.

- **`python3 .map/scripts/map_step_runner.py <cmd>`** — pure analysis/persistence helpers (no state-machine side effect). The list below names ONLY commands that have a `func_name` dispatch branch in `map_step_runner.py` and are thus invocable from the shell; the module defines additional internal helpers (`save_artifact_manifest`, `save_learning_metrics`, `load_learning_metrics`, `load_blueprint`, `record_repeated_learning_violations`, `record_token_budget_decision`, …) that are used by other dispatch branches but cannot be called directly:
  - `detect_*` family: `detect_truncated_agent_output`, `detect_already_done`, `detect_cross_subtask_regression_risk`, `detect_actor_files_changed_mismatch`, `detect_symbol_blast_radius`
  - `build_*` family: `build_context_block`, `build_json_retry_prompt`, `build_acceptance_coverage_report`, `build_prior_stage_consumption_report`, `build_retry_quarantine`, `build_handoff_bundle`, `build_review_handoff`, `build_review_prompts`, `build_anti_repeat_constraint`
  - `save_*` / `load_*`: `save_research`, `load_research`, `load_artifact_manifest`
  - `refresh_*`: `refresh_blueprint_affected_files`
  - `validate_*` (non-state): `validate_blueprint_contract`, `validate_mutation_boundary`, `validate_retry_quarantine`, `validate_flaky_test_triage`, `validate_run_health_report`, `validate_checkpoint`, `validate_prior_stage_consumption`
  - `record_*` / run evidence collectors (artifacts, not state): `record_test_baseline`, `record_diagnostics_baseline`, `record_scope_baseline`, `record_subtask_baseline`, `record_token_event`, `record_learning_consumption`, `record_workflow_fit`, `record_plan_artifacts`, `record_test_contract_handoff`, `record_failure_signature`, `record_flaky_test_triage`, `run_flaky_test_triage`, `record-review-ordering` (note: this one is dispatched with a hyphen, not an underscore)
  - intra-run failure memory (#253): `record_failure_signature`, `build_anti_repeat_constraint`, `set_anti_repeat_subtask_status`, `collect_anti_repeat_learn_candidates`
  - artifact writers: `write_verification_summary`, `write_run_health_report`, `write_pr_draft`, `write_plan_review`, `write_stage_gate`, `write_learning_handoff`
  - `log_*`: `log_agent_failure`

Rule of thumb: anything that mutates `step_state.json` → orchestrator. Anything that reads the repo, writes a sidecar artifact, or returns a JSON verdict without touching `step_state.json` → step_runner. The two `record_subtask_result` (orchestrator) vs `record_test_baseline` (step_runner) cases are the most common confusion point — orchestrator advances the cursor, step_runner just persists a baseline file.

### Flaky-test triage sidecar

When a test/check fails inconsistently, have MAP repeat the exact failing command
and record the evidence instead of weakening the test or treating a later pass as
a green gate:

```bash
python3 .map/scripts/map_step_runner.py run_flaky_test_triage \
  --check-id "pytest::test_name" \
  --runs 3 \
  --timeout 120 \
  -- python -m pytest tests/test_file.py::test_name
python3 .map/scripts/map_step_runner.py validate_flaky_test_triage
# Preferred close — the verdict-path route. Monitor emits valid:false plus
# disposition {kind: deferred_nondeterministic, check_id: ...}; close 2.4 with
# the same disposition piped through. The orchestrator routes to deferral ONLY
# when the sidecar + envelope back it (see "Verdict-path route" below).
echo "$MONITOR_JSON" | python3 .map/scripts/map_orchestrator.py \
  validate_step 2.4 --disposition deferred_nondeterministic \
  --check-id "pytest::test_name" --monitor-envelope -
```

`run_flaky_test_triage` executes argv with `shell=False`; shell syntax is not
interpreted. If a shell is intentionally required, pass it explicitly as argv,
for example `-- bash -lc 'python -m pytest tests/unit && echo done'`.

Manual evidence remains available when the repeated runs were already collected:

```bash
python3 .map/scripts/map_step_runner.py record_flaky_test_triage \
  "pytest::test_name" \
  '[{"run":1,"exit_code":1,"summary":"AssertionError"},{"run":2,"exit_code":0,"summary":"passed"}]' \
  --command "pytest tests/test_file.py::test_name" \
  --reason "Mixed pass/fail outcomes across repeated runs."
python3 .map/scripts/map_step_runner.py validate_flaky_test_triage
```

Mixed pass/fail evidence is classified as `deferred_nondeterministic` and
stored in `.map/<branch>/flaky_test_triage.json` plus the `flaky_test_triage`
manifest stage. This is an explicit recorded defer, not a pass: the artifact
sets `monitor_verdict_policy=not_valid_without_explicit_triage`, and Monitor
must still report the deferred evidence rather than returning a silent green.

**Verdict-path route (preferred).** The third Monitor outcome is wired into the
2.4 close itself: `validate_step 2.4 --disposition deferred_nondeterministic
--check-id <id> --monitor-envelope -`. The deferral is honored ONLY when (a)
the Monitor envelope is `valid:false` with a non-empty `failed_checks` and a
structured `disposition` matching the flags, and (b) the sidecar holds mixed
pass/fail evidence for that `check_id` — so a deterministic failure or a green
check can never be deferred. A deferred run returns `valid:false` +
`deferred:true` (non-green, exit 0, not a hard-stop); it records
`status=deferred_nondeterministic` plus evidence metadata in `step_state.json`
and advances without requeueing Actor. `recommendation` may be omitted or
`needs_investigation`; `revise`/`block` are rejected as contradictory.

**Lower-level command.** `defer_flaky_subtask "$SUBTASK_ID" --check-id <id>`
performs the same close+advance directly (used when there is no Monitor
envelope to verify, e.g. an operator deferral); the verdict-path route above
calls it internally after the envelope/anti-gaming checks.

If a command above ever returns `Unknown function`, grep `map_step_runner.py` for `func_name ==` to confirm the dispatch branch still exists; this list is the source of truth as of the PR that added it but the underlying dispatcher is the ground truth.

## Qualitative Convergence

Use this only when the plan/user/config explicitly opts a high-risk qualitative
gate into convergence. It is for `monitor` and `self_review`; never wrap
deterministic build/test/lint commands in this loop.

Each reviewer pass is recorded as append-only evidence in
`.map/<branch>/qualitative_convergence.json`:

```bash
python3 .map/scripts/map_step_runner.py record_qualitative_convergence \
  "monitor:${SUBTASK_ID}" \
  '{"pass_number":1,"reviewer":"monitor","clean":true,"critical_findings":[],"summary":"No critical findings against VC-1/VC-2","evidence":["src/app.py:42","pytest tests/test_app.py::test_contract"]}' \
  --scope monitor \
  --required-clean-passes 2 \
  --max-passes 4 \
  --risk-ref "concern_type=security"
```

Inspect `gate_status` after every call:

- `needs_more_passes`: run the next independent qualitative pass. Pass N>1 must
  specifically verify the prior pass's findings/regression risk, not rubber-stamp
  the same answer.
- `converged`: the tail streak reached K clean passes. This means "no critical
  findings in K consecutive qualitative passes", not "proven correct"; still run
  all deterministic gates.
- `max_passes_exceeded`: hard stop/escalate. Do not record the subtask as clean
  and do not weaken findings to force convergence.

Validation always re-derives `converged` and `consecutive_clean_passes` from the
pass log. A dirty pass resets the tail streak (`clean, dirty, clean` with K=2 is
not converged), `clean=true` with critical findings is invalid, and every pass —
including clean passes — must carry concrete evidence references.

## Wave Execution

### Execution strategy decision table

`select_execution_strategy` picks between the legacy sequential walker and the wave-loop on every run. The wave-loop engages **only when ALL THREE hold**; otherwise the legacy sequential walker (`get_next_step`) runs:

1. `execution.wave_mode` ∈ {`auto`, `on`}, **AND**
2. `worktree.isolation` ≠ `off`, **AND**
3. at least one color group has ≥2 members.

| `execution.wave_mode` | `worktree.isolation` | Color group ≥2? | Dispatcher selected |
|---|---|---|---|
| any | `off` (default) | any | Legacy sequential walker (`get_next_step`) |
| `off` | any | any | Legacy sequential walker (`get_next_step`) |
| `auto` / `on` | `auto` / `required` | no (all groups size 1) | Legacy sequential walker (`get_next_step`) |
| `auto` / `on` | `auto` / `required` | yes | Wave-loop (`get_wave_step` / `validate_wave_step` / `advance_wave`) |

**Defaults (canonical MapConfig):** `execution.wave_mode=auto`, `worktree.isolation=off`. Because the isolation gate (#2) fails by default, a stock `mapify init` config always runs the legacy sequential walker — byte-identical to pre-Slice-3. Even when the wave-loop does engage, dispatch remains **sequential** in Slice 5a (`isolation_active=True`, `dispatch_mode` from `get_wave_step` keyed to `sequential`); concurrent fan-out is Slice 5b (`dispatch_mode==concurrent`, `concurrency_enabled=True`), **ACTIVE when opted in** via `execution.concurrent_dispatch: true` (gate: `dispatch_mode == 'concurrent'`).

### Sequential walker

Use `get_next_step` for all sequential (default) execution. One phase at a time, in `subtask_sequence` order. Do not mix wave APIs with the sequential cursor for the same workflow.

### Wave-loop

Use `get_wave_step`, `validate_wave_step`, and `advance_wave` when the wave-loop is active. Do not mix wave APIs with the sequential `get_next_step` cursor for the same wave unless the orchestrator response explicitly tells you to fall back.

When the wave-loop engages AND `isolation_active` is true (`worktree.isolation` ∈ {`auto`, `required`}), the Slice 5a flow applies: (a) create a worktree per wave member via `create_subtask_worktree`; (b) dispatch the member Actors **sequentially** — one per turn, each pinned to its own worktree path (`HC-3`); (c) call `concurrency_ready` (ST-003) to verify all member worktrees before merge; (d) accept the whole wave atomically via `merge_wave_worktrees` — never one-at-a-time, with whole-wave rollback on any failure. See [Parallel waves](#worktree-isolation) under Worktree isolation for the full protocol. Concurrent fan-out (dispatching all Actors in one message) is Slice 5b (`dispatch_mode==concurrent`) and is not yet active.

### Concurrent Actor dispatch — **Slice 5b** (`dispatch_mode == 'concurrent'`) — **ACTIVE when opted in**

> **IMPORTANT — read before using this section.**
> Concurrent fan-out (emitting multiple `Task(actor)` calls in a single message) is
> **ACTIVE when opted in** via `execution.concurrent_dispatch: true`
> (gate: `dispatch_mode == 'concurrent'`). With the **default config**
> (`concurrent_dispatch=false`, Slice 5a), dispatch stays **SEQUENTIAL
> even when a wave has `mode=="parallel"`** — one Actor per turn, each pinned to
> its own worktree. Act on the instructions below **only** when `get_wave_step`
> returns `dispatch_mode == 'concurrent'`.

**Runtime wiring:** when `get_wave_step` returns `dispatch_mode == 'concurrent'`,
call `run_concurrent_wave` (runner), which batch-splits the wave by `max_actors`
and merges each sub-batch atomically via `merge_wave_worktrees`. For each sub-batch,
emit all N `Task(actor)` calls in **one assistant message** — not one per turn:

```text
# CORRECT (dispatch_mode=='concurrent' only) — N Task calls in one message:
Task(
  subagent_type="actor",
  description="Implement ST-003",
  prompt="..."
)
Task(
  subagent_type="actor",
  description="Implement ST-004",
  prompt="..."
)
```

```text
# INCORRECT — one Task per turn (sequential, defeats the wave):
# Turn 1: Task(actor, ST-003)
# Turn 2: Task(actor, ST-004)   ← serial, not concurrent
```

**Self-audit before dispatch:** "I will emit {n} Task(actor) calls in one message for this wave." Confirm n matches the color group size.

**`max_actors` cap:** Default 4–8 concurrent actors per wave. Groups larger than `max_actors` are pre-split into sequential batches of `max_actors` before dispatch; do not emit more than `max_actors` Task calls in a single message.

**Retry-discard on failure:** on any actor failure, timeout, or Monitor-reject within a concurrent group, the runner calls `abort_wave_group`, which discards the **entire group** (cancels siblings, resets all worktrees to base SHA, removes group branches) and reruns from base. Retries are bounded by `max_wave_retries` (default 3); on exhaustion the runner escalates to a human and does **not** auto-restart. Never merges a successful subset — discard-all-or-merge-all (HC-4).

### Anti-patterns — Slice 5b concurrent dispatch only

> These apply **only** under Slice 5b concurrent dispatch (`dispatch_mode == 'concurrent'`). In Slice 5a and the default sequential walker, one Task per turn **is** the correct behavior — the first three below are NOT anti-patterns there.

- **One Task per turn across N turns** — serial actor loop that happens to use wave state; does not achieve concurrency. (Slice 5b only — this is the expected, correct behavior in 5a.)
- **TodoWrite between actor dispatches** — a TodoWrite call between Task calls serializes the batch; emit all Task calls in one message. (Slice 5b only.)
- **Waiting for one actor result before dispatching the next** — correct for sequential dispatch (5a), wrong for concurrent waves (5b).
- **Mixing `get_next_step` and `get_wave_step` for the same wave** — corrupts the state-machine cursor. (Applies to both 5a and 5b.)

### Actor-boundary prompt template (worktree-isolated subtasks)

When a subtask runs in its own worktree, prefix the Actor prompt with:

```text
You are working inside the isolated worktree for {SUBTASK_ID}.
Worktree path: {WT_PATH}
Frozen base SHA: {BASE_SHA}

HARD CONSTRAINTS:
- Write ONLY inside {WT_PATH}. Never touch the main tree or sibling worktrees.
- Do not commit directly. Your output is merged by merge_subtask_worktree / merge_wave_worktrees.
- On completion, return JSON: {"subtask_id": "{SUBTASK_ID}", "files_changed": [...], "tests_run": [...], "validation_notes": "...", "blocker": null}
```

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
JSON envelope (`valid`, `summary`, `issues`). Pipe the captured response in
(the detector reads stdin):
`printf '%s' "$MONITOR_OUTPUT" | python3 .map/scripts/map_step_runner.py detect_truncated_agent_output --agent monitor`.
A bare call with nothing piped returns `status: "no_input"` (`truncated: false`)
— that means the response was not piped, not that it passed. If truncated, log via
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

> **Why JSON (not prose):** Actor and this detector share one contract
> (`AGENT_OUTPUT_SCHEMAS["actor"]`), exactly as Monitor does. The JSON is a
> *post-work manifest*, never a code container — the Actor writes and runs code
> via its tools FIRST, then summarizes. Keeping the four fields short (file
> paths, test commands, a notes string, a blocker) keeps truncation
> machine-checkable without diverting the agent into serialization or escaping
> code/diffs into JSON strings. The `<expected_output>` block in `SKILL.md`
> states this; do not relax the detector to accept prose.

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

## Intra-run failure memory (#253, full recipe)

Stops the Actor from re-walking the SAME dead end across retries of ONE subtask.
It complements — never replaces — the truncation gate (`log_agent_failure`,
FORMAT failures only) and CLEAN_RETRY (`retry_quarantine`, a one-shot reset).
Branch-scoped store: `.map/<branch>/anti_repeat.json` (manifest stage
`anti_repeat`).

On EVERY Monitor `valid=false` (and on a post-approval test failure treated as a
Monitor failure), after `monitor_failed`:

```bash
# 1. Record the substantive rejection. source ∈ {monitor_rejection,
#    test_failure, gate_failure}. Exit 0 always — this is a sensor, not a gate.
REC=$(python3 .map/scripts/map_step_runner.py record_failure_signature \
  "$MONITOR_FEEDBACK" "$SUBTASK_ID" --source monitor_rejection)
ARMED=$(echo "$REC" | jq -r '.armed')
ESCALATE=$(echo "$REC" | jq -r '.escalation_recommended')

# 2. If armed (same normalized failure >= 2x), prepend the hard constraint to
#    the TOP of the next Actor prompt. Pass --quarantine-active when CLEAN_RETRY
#    is set this iteration (CLEAN_RETRY wins; the counter still ticked in step 1).
if [ "$ARMED" = "true" ]; then
  BLOCK=$(python3 .map/scripts/map_step_runner.py \
    build_anti_repeat_constraint "$SUBTASK_ID" | jq -r '.constraint')
  # Next Actor prompt = "$BLOCK" + the normal subtask prompt.
fi
```

- **Armed semantics.** The constraint is *anti-stagnation*, not *anti-approach*:
  it binds the next delta to RESOLVE the repeated failure and forbids
  resubmitting a change that would still produce it — it never bans a whole
  approach (an over-broad ban pushes the Actor off the genuinely-correct fix).
  The block is delimited `<intra_run_failure_memory>…</intra_run_failure_memory>`
  and shows the human-readable sample, not the hash.
- **Generic rejections never arm.** "tests still fail", "needs more work" carry
  no concrete anchor (file / symbol / exception / assertion); they are recorded
  with `low_specificity:true` and never produce a block, so a vague Monitor note
  cannot brick a subtask.
- **Bounded-effort escalation (#255).** At the 3rd identical failure the record
  sets `escalation_recommended:true`. The constraint armed at the 2nd failure
  was the single bounded recovery *act*; a 3rd identical rejection means it did
  not break the dead end, so STOP — do not retry, do not run the legacy retry-3
  Stuck-Recovery path for this identical loop. Emit ONE deterministic terminal
  outcome:

  ```bash
  if [ "$ESCALATE" = "true" ]; then
    OUT=$(python3 .map/scripts/map_step_runner.py \
      build_escalation_outcome "$SUBTASK_ID" repeated_failure)
    #  Pass --quarantine-active on a CLEAN_RETRY iteration: it returns
    #  status:"deferred" so the one-shot reset runs before any terminal stop.
    STATUS=$(echo "$OUT" | jq -r '.status')
    #  status:"escalated"-> surface OUT.blocker_summary + OUT.recommended_action
    #    to the user and STOP (outcome:"BLOCKED", .map/<branch>/escalation_*.md).
    #  status:"not_escalated" -> the LATEST failure was a NEW signature; the
    #    Actor moved off the dead end -> resume normal retries.
  fi
  ```

  The stop is re-derived from the store INSIDE `build_escalation_outcome`
  (latest-signature rule), so a spurious call cannot fabricate a terminal stop.
  When `monitor_failed` instead returns `status:"max_retries"`, run
  `build_escalation_outcome "$SUBTASK_ID" max_retries --retry-count <n>
  --max-retries <m>` for the same structured outcome with
  `outcome:"CLARIFICATION_NEEDED"`. The escalation is idempotent (re-running
  after `status:"escalated"` returns the prior outcome without rewriting it) and
  the subtask's anti-repeat status flips to `escalated`, so its armed signs still
  feed `/map-learn` candidates.
- **On a clean close**, if the subtask had armed signs, run
  `set_anti_repeat_subtask_status "$SUBTASK_ID" succeeded` so its signs are
  excluded from the /map-learn candidates `write_learning_handoff` collects
  (a subtask that eventually passed is positive evidence, not a rule to mine).
- **Thresholds** are env-tunable: `MAP_ANTI_REPEAT_ARM_THRESHOLD` (default 2),
  `MAP_ANTI_REPEAT_ESCALATE_THRESHOLD` (default 3).

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
- `recommended_gate == "scoped"` — no external callers affected; proceed to
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

It captures the test run internally and prints a single compact JSON report at
the end — read that JSON directly. Do NOT pipe it through `head`/`tail` (per the
repo bash guidelines); the output is one small object, not a stream, so
truncating it only hides fields.

Auto-detects from project markers:
- `Makefile` with `test:` target → `make test`
- `pyproject.toml` / `pytest.ini` → `pytest`
- `go.mod` → `go test ./...`
- `Cargo.toml` → `cargo test`

Detection probes the **repo root first**. If the root has no harness it
**shallow-scans the immediate subdirectories (one level)** for a module that
does — the common monorepo layout (e.g. `component-manager/go.mod` with no
root `go.mod`). A single matching subdir is used automatically and the command
runs from that dir; the report records `module_dir` and `run_dir` so the chosen
location is never silent.

When the root has no harness and **more than one** subdir qualifies, detection
**refuses to guess**: it returns `status="skipped"` with `candidate_module_dirs`
listing them. Re-run pointing at the right module (`--module-dir`/`--cwd` are
aliases):
```bash
python3 .map/scripts/map_step_runner.py record_test_baseline "$BRANCH" \
  --module-dir component-manager
```
A `status="skipped"` baseline is a **hard signal, not a no-op**: the
cross-subtask regression gate then has no baseline and cannot tell an introduced
regression from a pre-existing failure. Resolve it (pass `--module-dir` or
`--command`) before running subtasks — do not proceed on a silent empty baseline.

Override the auto-detect when the full run is too slow for a
pre-flight (or you want a narrower target):
```bash
python3 .map/scripts/map_step_runner.py record_test_baseline "$BRANCH" \
  --command "pytest tests/smoke" --timeout 60
```
`--module-dir` and `--command` compose: `--module-dir` sets where the command
runs, `--command` sets what runs (auto-detected within the module dir if
omitted).

Persists to `.map/<branch>/test_baseline.json`. Parse pre-existing
failures back via:
```bash
python3 .map/scripts/map_step_runner.py list_baseline_failures "$BRANCH"
```

Each subtask's failing test now has a clean disposition: in baseline ⇒
pre-existing, route to follow-up subtask; NOT in baseline ⇒ this
plan introduced it, fix here.

## RESEARCH artifact schema (exact contract)

`save_research` persists the bytes you pipe verbatim; `validate_research` then
enforces the machine-checkable contract below before Actor consumes the artifact.
Hand-author to this exact schema so the FIRST save validates — the loose prose in
`SKILL.md` only names the fields; this is the authoritative shape and types.

Top-level object — strict JSON only (no markdown, no ``` code fences, ≤ 64 KiB):

| field | type | rule |
| --- | --- | --- |
| `status` | string | exactly one of `OK`, `PARTIAL_RESULTS`, `NO_RESULTS`, `SEARCH_FAILED` (upper-case enum — NOT free text like `"complete"`/`"high"`) |
| `confidence` | number | float in `[0, 1]` (NOT a word like `"high"`) |
| `search_stats` | object | exactly `files_scanned` (int ≥ 0), `total_matches_found` (int ≥ 0), `results_truncated` (bool) — these exact field names, not `files_examined`/`patterns_searched` |
| `relevant_locations` | array | ≤ 5 entries; each is `{path, lines, relevance}` |

Each `relevant_locations[]` entry:

| field | type | rule |
| --- | --- | --- |
| `path` | string | safe relative repo path (no absolute, `~`, `\`, or `..`); must exist unless the entry is marked absent (`"exists": false`, `"absent": true`, or `"status"` ∈ `absent`/`missing`/`new`/`not_found`) |
| `lines` | array | `[start, end]` — two positive ints, `start ≤ end`, span `end - start + 1 ≤ 200`, `end` within the file's line count (NOT a `"start-end"` string) |
| `relevance` | string | non-empty; explain why the range matters. Never inline `content`/`file_contents`/`raw_code` — cite paths and ranges only |

Copy-pasteable skeleton (a valid artifact — swap in your real values):

```json
{
  "status": "OK",
  "confidence": 0.8,
  "search_stats": {
    "files_scanned": 12,
    "total_matches_found": 4,
    "results_truncated": false
  },
  "relevant_locations": [
    {
      "path": "src/example/module.py",
      "lines": [10, 42],
      "relevance": "why this range matters to the current subtask"
    }
  ]
}
```

`validate_research` echoes this exact skeleton in its `skeleton` field on ANY
failure (invalid JSON, wrong types, or a missing artifact), so the first reject is
self-correcting: copy the `skeleton`, swap your values, re-save. Extra fields beyond
the contract (e.g. `executive_summary`, `search_method`) are allowed and ignored by
the validator; only the fields above are required and type-checked.

## Proactive blueprint refresh (recommended)

Merge a subtask's observed actual diff into its approved `affected_files`
BEFORE its RESEARCH starts, so decomposer's stale path/symbol guesses from
planning time don't hide real edits from research → Actor → Monitor.
The default is additive and must not shrink the approved mutation surface;
`--replace` is the explicit destructive mode for intentional contract rewrite.

```bash
python3 .map/scripts/map_step_runner.py refresh_blueprint_affected_files \
  "$BRANCH" "$SUBTASK_ID" --dry-run   # preview the proposed write
python3 .map/scripts/map_step_runner.py refresh_blueprint_affected_files \
  "$BRANCH" "$SUBTASK_ID"             # merge observed files into affected_files
```

When to call:
- At the start of every subtask's RESEARCH phase (covers planning-time
  path drift for THIS subtask).
- After a clean Monitor close (already documented in the per-subtask
  commit section above — covers reality lock for the just-completed
  subtask).

## Worktree isolation

Per-subtask git worktree isolation (#284) is **opt-in, off by default**. Enable
with `worktree.isolation: true` in `.map/config.yaml` (`worktree.max_deletions: N`
caps the bulk-deletion guard, 0 = off). When enabled, each subtask's Actor runs
in a dedicated throwaway git worktree (stored out of the working tree under the
repo's `.git` common dir); the result is squash-merged back into the working
branch ONLY after the configured `verification_checks` pass IN the worktree
(pre-merge gate), and a rejected attempt is discarded so the working branch is
never touched. The step runner owns the lifecycle + every safety guard
(council-reviewed). Dispatch the Actor Task WITHOUT `isolation="worktree"` — the
runner owns isolation; the two mechanisms must never both be active.

**Before ACTOR — create the worktree (no-ops when disabled):**

```bash
WT_JSON=$(python3 .map/scripts/map_step_runner.py create_subtask_worktree "$SUBTASK_ID")
WT_STATUS=$(printf '%s' "$WT_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("status",""))')
WT_PATH=""
if [ "$WT_STATUS" = "success" ]; then
  WT_PATH=$(printf '%s' "$WT_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("worktree_path",""))')
fi
```

`status:"disabled"` (exit 0) → flag off, proceed normally. `status:"error"` →
STOP and surface the structured `kind`/`message` (`DIRTY_MAIN`, `PROTECTED_REF`,
`NESTED_WORKTREE`, `ACTIVE_GIT_OP`, `INVALID_SUBTASK_ID`, …); fix the cause, do
NOT silently fall back to the shared tree. When `WT_PATH` is non-empty, append to
the Actor task prompt: *"All edits and test runs for this subtask MUST happen
inside the git worktree at `$WT_PATH` — never edit the main checkout, and never
run git fetch/pull/push from the worktree."*

**Accept (after a clean Monitor + Evaluator pass)** — replaces the per-subtask
`git commit`:

```bash
python3 .map/scripts/map_step_runner.py merge_subtask_worktree "$SUBTASK_ID"
```

It commits the Actor's worktree work, runs `verification_checks` in the worktree
(pre-merge gate), then `git merge --squash` + one runner-authored commit (never
`--no-ff`; the squash commit IS this subtask's commit — pass its `merged_sha` to
`record_subtask_result --commit-sha`) and removes the worktree. Guard failures
return `status:"error"` with a `kind` and leave the working branch untouched:
`VERIFY_FAILED`, `MERGE_CONFLICT`, `BULK_DELETION`, `RUNTIME_STATE_IN_DIFF`,
`BASE_DIVERGED`, `SUBMODULE_CHANGED`, `WORKTREE_HEAD_MOVED` → discard + retry. A
`no_changes:true` success means the Actor edited the main checkout instead of the
worktree — surface it and do NOT record the subtask.

**Reject (Monitor `valid=false` / Evaluator fail)** — atomic discard before retry:

```bash
python3 .map/scripts/map_step_runner.py discard_subtask_worktree "$SUBTASK_ID" --save-patch
```

`--save-patch` keeps the rejected diff under `.map/<branch>/worktree_attempts/`.
The retry creates a fresh worktree off the current HEAD. Inspect state any time
with `worktree_isolation_status`.

### Parallel waves (≥2 worktree-isolated subtasks) — #284 Phase 2

When `get_wave_step` returns `mode:"parallel"` (a wave with ≥2 disjoint-file
subtasks) AND `isolation_active` is true, execute the **Slice 5a sequential
worktree flow**:

1. **Create** a worktree per wave member: `create_subtask_worktree` for each.
2. **Dispatch Actors sequentially** — one per turn (`HC-3`), each pinned to its
   own `$WT_PATH`. Do NOT dispatch all in one message (that is Slice 5b).
3. **Verify** all member worktrees with `concurrency_ready` (ST-003) before merge.
4. **Accept atomically** via `merge_wave_worktrees` after every subtask passes
   Monitor (+ Evaluator) — never merge one at a time.

Do NOT merge them one at a time: every worktree was cut off the same HEAD, so
the first `merge_subtask_worktree` advances the working branch and the next trips
`BASE_DIVERGED`. Accept the whole wave atomically instead — only after EVERY
subtask in the wave has passed Monitor (+ Evaluator):

```bash
python3 .map/scripts/map_step_runner.py merge_wave_worktrees "$ST_A" "$ST_B" "$ST_C"
```

The coordinator (council-reviewed, conv `c29d6fa9`): derives the wave base from
the sidecar; refuses EXTERNAL HEAD movement but allows the sibling divergence each
in-wave squash-merge creates; runs each worktree's pre-merge `verification_checks`,
then squash-merges every accepted worktree by frozen SHA in sorted id order (one
runner commit per subtask), then runs the post-wave full gate **inside the same
transaction**. It is **all-or-nothing**: any textual conflict, commit failure, or
post-wave-gate failure rolls the WHOLE wave back to the base (`reset --hard` +
`clean -fd`, never `git merge --abort` — squash leaves no `MERGE_HEAD`) and leaves
every worktree intact for retry. Pass each subtask's `merged_sha` from the result
to `record_subtask_result --commit-sha`. This **replaces** the separate Per-Wave
Gate when isolation is on — the post-wave gate runs inside `merge_wave_worktrees`.

Failure `kind`s (working branch untouched / rolled back to base, worktrees kept):
`WAVE_MERGE_CONFLICT` (with `attribution` naming the subtasks that touched each
conflicted file — fix `affected_files` or re-decompose), `WAVE_VERIFY_FAILED`
(post-wave gate red), `EXTERNAL_HEAD_MOVED` (a commit landed outside the wave —
recreate the worktrees off the new HEAD), `WAVE_BASE_MISMATCH`, `DIRTY_TARGET`,
`MERGE_IN_PROGRESS`, plus the per-worktree preflight `kind`s (`VERIFY_FAILED`,
`BULK_DELETION`, … with `phase:"preflight"`). On any Monitor `valid=false` for a
single wave subtask, `discard_subtask_worktree` THAT subtask and retry it; call
`merge_wave_worktrees` only once the whole wave is green. The `overlaps` field is
advisory telemetry (actual changed-file intersections), not a gate.

## Troubleshooting

- Blueprint validation fails: fix the decomposer output before Actor starts.
- `step_state.json` disagrees with artifacts: use orchestrator commands, not manual state edits.
- Monitor loops: preserve each failure in `code-review-N.md`, then invoke Predictor when escalation rules apply.
- Final closeout lacks `run_health_report.json`: rerun the closeout command with explicit `RUN_HEALTH_STATUS`.
