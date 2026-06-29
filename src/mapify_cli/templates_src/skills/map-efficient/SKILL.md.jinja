---
name: map-efficient
description: |
  Token-efficient MAP workflow with state-machine orchestration over Predictor/Actor/Monitor/Evaluator/Reflector. Use when implementing a non-trivial change end-to-end. Do NOT use for tiny one-shot edits; use map-fast.
effort: medium
disable-model-invocation: true
argument-hint: "[task description]"
---
# MAP Efficient Workflow (Optimized)

## Core Design Principle

State-gated prompting: each invocation sees exactly one clear next action. The state machine enforces sequencing, Python validates completion, and hooks inject reminders.

Long subagent prompts use the shared [XML Prompt Envelope](../../references/map-xml-prompt-envelopes.md): persisted artifacts and current subtask context appear before instructions, with output contracts isolated in `<expected_output>`.

Use [efficient-reference.md](efficient-reference.md) for wave examples, TDD details, qualitative convergence, final-verifier retry policy, examples, and troubleshooting. When a workflow step points to a reference section, read that section before executing the step; supporting files are not assumed to be in context automatically.

## Effort and Parallelism Policy

```yaml
thinking_policy: medium/adaptive
parallel_tool_policy: wave_mode_aware
```

- Use deeper reasoning only when a subtask is risky, blocked, under-specified, or repeatedly failing Monitor.
- Execution strategy is determined by `select_execution_strategy`: the wave-loop engages only when `execution.wave_mode` is `on` or `auto` AND a color group has ≥2 members; otherwise the legacy sequential walker runs. With default config this is the sequential walker. See [efficient-reference.md](efficient-reference.md#wave-execution) for the decision table and dispatch mechanics.
- Do not parallelize state transitions, Monitor retries for the same subtask, or writes to shared branch artifacts.

## Execution Rules

1. Execute the next state-machine step only; never skip phases.
2. Use the exact agent type for the current phase.
3. Max 5 retry iterations per subtask.
4. Batch mode is default. Execution strategy is selected by `select_execution_strategy` (sequential walker by default; wave-loop only when wave_mode is enabled and a color group has ≥2 members).
5. After Monitor pass, record files changed in `step_state.json` for guard isolation.
6. Validate planning metadata before Actor starts: `expected_diff_size`, `concern_type`, `one_logical_step`, `split_rationale`, `concern_justification`, `coverage_map`, `hard_constraints`, `soft_constraints`, `validation_criteria`, `[AC-1]` bracket tags, and `tradeoff_rationale`.
7. Script routing: `map_orchestrator.py` owns state-machine transitions (`get_next_step`, `validate_step`, `monitor_failed`, `record_subtask_result`, `set_waves`, `resume_from_plan`, …); `map_step_runner.py` owns every `detect_*` / `build_*` / `save_*` / `load_*` / `refresh_*` / `log_*` helper plus baseline `record_*` and artifact writers. Full table + the `record_*` / `validate_*` disambiguation in [efficient-reference.md#script-routing-dispatcher-reference](efficient-reference.md#script-routing-dispatcher-reference).

## Mutation Boundary Constraints

These constraints apply to every write-capable Actor or fix phase:

- Do not edit unrelated files, even if they are nearby or easy to clean up.
- Do not add, remove, or upgrade dependencies unless the current subtask contract explicitly names that dependency change.
- Do not refactor neighboring code unless the current validation criteria cannot pass without that exact refactor.
- If a dependency change, broad refactor, or scope expansion seems necessary, report it as a blocker/tradeoff and wait for the contract to change instead of doing it silently.

## Intentional Agent Omissions

/map-efficient does not run Evaluator or Reflector during normal execution. Monitor validates correctness directly, and learning is deferred to `/map-learn`.

Predictor is conditional: invoke it during stuck recovery or high-risk/escalated subtasks as described in [efficient-reference.md](efficient-reference.md#predictor-recovery).

## State File

Single source of truth: `.map/<branch>/step_state.json`.

Do not modify it directly. Use `.map/scripts/map_orchestrator.py` and `.map/scripts/map_step_runner.py`.

## Workflow Artifacts

- `.map/<branch>/blueprint.json`
- `.map/<branch>/task_plan_<branch>.md`
- `.map/<branch>/code-review-*.md`
- `.map/<branch>/qa-*.md`
- `.map/<branch>/pr-draft.md`
- `.map/<branch>/verification-summary.md/json`
- `.map/<branch>/run_health_report.json`

## Flag Parsing

```bash
TASK_ARGS="$ARGUMENTS"
TDD_FLAG=false
if echo "$TASK_ARGS" | grep -q -- '--tdd'; then
  TDD_FLAG=true
  TASK_ARGS=$(echo "$TASK_ARGS" | sed 's/--tdd//g' | xargs)
fi
```

Use `$TASK_ARGS`, not raw `$ARGUMENTS`, in prompts.

**MANDATORY: Empty $TASK_ARGS is NOT a stop condition.** Do not bail out on an
empty `$TASK_ARGS`/`$ARGUMENTS` value alone — this skill resumes from
existing artifacts. The skill stops with a task-required message ONLY when
ALL THREE are true:

1. `$TASK_ARGS` is empty, AND
2. `.map/<branch>/step_state.json` does NOT exist, AND
3. `.map/<branch>/task_plan_<branch>.md` does NOT exist.

In every other case you MUST execute Step 0 first and let `resume_from_plan` /
`get_next_step` decide the next phase. The DECOMPOSE phase (1.0) is the only
phase that reads `$TASK_ARGS` — and resumed workflows skip it.

## Step 0: Detect Existing State or Plan

Run this BEFORE any `$TASK_ARGS` validation.

```bash
BRANCH=$(git rev-parse --abbrev-ref HEAD | sed -E 's|/|-|g; s|[^a-zA-Z0-9_.-]|-|g; s|-{2,}|-|g; s|^-||; s|-$||')
STATE_FILE=".map/${BRANCH}/step_state.json"
PLAN_FILE=".map/${BRANCH}/task_plan_${BRANCH}.md"

if [ -f "$STATE_FILE" ]; then
  echo "Existing step_state.json found — proceeding straight to Step 1 get_next_step."
elif [ -f "$PLAN_FILE" ]; then
  RESUME_RESULT=$(python3 .map/scripts/map_orchestrator.py resume_from_plan)
  RESUME_STATUS=$(echo "$RESUME_RESULT" | jq -r '.status')
  if [ "$RESUME_STATUS" = "success" ]; then
    echo "Resumed from /map-plan artifacts."
  else
    echo "resume_from_plan failed: $RESUME_RESULT" >&2
    exit 1
  fi
elif [ -z "$TASK_ARGS" ]; then
  echo "No \$TASK_ARGS, no step_state.json, and no task_plan_${BRANCH}.md." >&2
  echo "Provide a task description (e.g. '/map-efficient add retry policy')" >&2
  echo "or run /map-plan first to create a plan to resume from." >&2
  exit 1
fi
```

If `--tdd` was passed:
```bash
if [ "$TDD_FLAG" = "true" ]; then
  python3 .map/scripts/map_orchestrator.py set_tdd_mode true
fi
```

## Step 1: Get Next Step Instruction

```bash
NEXT_STEP=$(python3 .map/scripts/map_orchestrator.py get_next_step)
STEP_ID=$(echo "$NEXT_STEP" | jq -r '.step_id')
PHASE=$(echo "$NEXT_STEP" | jq -r '.phase')
INSTRUCTION=$(echo "$NEXT_STEP" | jq -r '.instruction')
IS_COMPLETE=$(echo "$NEXT_STEP" | jq -r '.is_complete')
```

If `IS_COMPLETE=true`, skip to final verification.

## Step 2: Execute Step Based on Phase

Run only the current phase returned by the state machine.

### Phase: DECOMPOSE (1.0)

```text
Task(
  subagent_type="task-decomposer",
  description="Decompose task into subtasks",
  prompt="""
<documents>
  <document source="task-arguments"><document_content>$TASK_ARGS</document_content></document>
</documents>
<task>Break down the task into no more than 20 atomic subtasks and return only JSON.</task>
<constraints>
Return blueprint JSON with expected_diff_size, concern_type, one_logical_step, split_rationale, concern_justification, validation_criteria, coverage_map, hard_constraints, soft_constraints, tradeoff_rationale where needed, dependencies, risk_level, test_strategy, and aag_contract.
Every owned coverage_map key must appear as a bracketed validation_criteria tag, e.g. VC1 [AC-1]: checkout timeout shows retryable message.
</constraints>
<expected_output>Return only JSON matching the blueprint shape.</expected_output>
"""
)
```

After decomposer returns, save `.map/<branch>/blueprint.json`, run `python3 .map/scripts/map_step_runner.py validate_blueprint_contract`, register subtasks, and validate step `1.0`.

### Phase: INIT_PLAN (1.5)

Generate `.map/<branch>/task_plan_<branch>.md` from blueprint. Include each subtask's `expected_diff_size`, `concern_type`, and `one_logical_step` so reviewers can spot scope creep before Actor starts.

### Phase: REVIEW_PLAN (1.55)

Present the generated plan and require explicit user approval before execution state is initialized.

### Phase: CHOOSE_MODE (1.56) - Auto-skipped

Execution mode is `batch`; the orchestrator skips this step.

### Phase: INIT_STATE (1.6)

State is managed by the orchestrator. Do not create `step_state.json` manually.

### Pre-flight test baseline (MANDATORY at INIT_STATE)

```bash
python3 .map/scripts/map_step_runner.py record_test_baseline "$BRANCH"
```

Snapshots pre-existing failures so later subtasks distinguish
"introduced regression" from "was broken pre-plan". Auto-detects
Make/pytest/go test/cargo. It captures the test run internally and prints a
single compact JSON report at the end — read that JSON directly; do NOT pipe it
through `head`/`tail` (per the repo bash guidelines). Overrides + narrow-target
guidance: [efficient-reference.md](efficient-reference.md#pre-flight-test-baseline).

### Wave Computation (after INIT_STATE) - REQUIRED

```bash
BRANCH=$(git rev-parse --abbrev-ref HEAD | sed -E 's|/|-|g; s|[^a-zA-Z0-9_.-]|-|g; s|-{2,}|-|g; s|^-||; s|-$||')
if [ -f ".map/${BRANCH}/blueprint.json" ]; then
  python3 .map/scripts/map_orchestrator.py set_waves --blueprint .map/${BRANCH}/blueprint.json
else
  echo "WARNING: blueprint.json not found. Running subtasks sequentially."
fi
```

**Execution strategy:** `select_execution_strategy` chooses between the legacy sequential walker and the wave-loop. The wave-loop (`get_wave_step` / `validate_wave_step` / `advance_wave`) engages only when `execution.wave_mode ∈ {on, auto}` AND a color group has ≥2 members; otherwise `get_next_step` (sequential walker) runs. Under `isolation_active` (Slice 5a), the wave-loop creates per-member worktrees, dispatches Actors **sequentially** (one per turn, `HC-3`), verifies via `concurrency_ready`, then accepts atomically via `merge_wave_worktrees`; concurrent fan-out is Slice 5b (`dispatch_mode==concurrent`). Under `dispatch_mode==concurrent` (opt-in via `execution.concurrent_dispatch: true`), call `run_concurrent_wave`: emit N `Task(actor)` blocks in **one message** per sub-batch; on any failure `abort_wave_group` discards the whole group and reruns from base (bounded by `max_wave_retries`). See [efficient-reference.md](efficient-reference.md#wave-execution) for the decision table and full wave loop.

**Note on resume:** `resume_from_plan` (Step 0) now auto-invokes `set_waves`
when `blueprint.json` is present, so resumed workflows do not need a manual
`set_waves` dispatch. The result is reported in the `waves_computed` field of
the resume response (`"success"`, `"error"`, or `"skipped"` if no blueprint).

### No-op subtask short-circuit (before RESEARCH)

Some subtasks are already-done historically (rename/refactor landed in a prior PR), or truly do not need Actor/Monitor because the requested work is already satisfied by repo state. Skip them up-front to save tokens:

```bash
SUBTASK_ID=$(jq -r '.current_subtask_id' ".map/${BRANCH}/step_state.json")
python3 .map/scripts/map_orchestrator.py mark_subtask_complete "$SUBTASK_ID" \
  --reason "rename already landed in commit <sha>; verified via git log"
```

This records a synthetic subtask_result with status="no-op", marks the phase COMPLETE, and advances the cursor (or closes the workflow if it was the last). Always pass `--reason` so audits know why the work was skipped. If unsure, run RESEARCH first and decide based on its findings.

### Phase: RESEARCH (2.2) - Required artifact; delegated agent conditional

Persist a RESEARCH artifact for every non-no-op subtask before Actor. Plan-scope discovery from `/map-plan` lives at `.map/<branch>/research/plan__discovery.md` and is automatically included in `build_context_block`; legacy `.map/<branch>/findings_<branch>.md` is a read-only fallback. Subtask research must still be saved separately as `.map/<branch>/research/<subtask_id>__actor.md` so Actor/Monitor can distinguish planner-wide context from current-subtask evidence. `research-agent` is conditional: use it for cold-start repository exploration, 3+ existing files, high risk, unclear locations, or failed direct search. If the relevant file/symbol is already known, or the subtask is greenfield/new-file work, do narrow current-session research and save those concise strict-JSON findings via the canonical `save_research` API. Validate the machine-checkable research contract before closing the phase with the orchestrator.

```bash
SUBTASK_ID=$(jq -r '.current_subtask_id' ".map/${BRANCH}/step_state.json")
# RECOMMENDED: proactive refresh_blueprint_affected_files <branch>
# <sid> [--dry-run] BEFORE delegated research (efficient-reference.md).
printf '%s' "$RESEARCH_FINDINGS" | \
  python3 .map/scripts/map_step_runner.py save_research "$BRANCH" "$SUBTASK_ID"
# (defaults kind=actor; pass a 4th arg like 'monitor' or 'decomposer' to partition)
python3 .map/scripts/map_step_runner.py validate_research "$BRANCH" "$SUBTASK_ID"
python3 .map/scripts/map_orchestrator.py validate_step 2.2
```

Later phases read with:
```bash
RESEARCH_FINDINGS=$(python3 .map/scripts/map_step_runner.py load_research "$BRANCH" "$SUBTASK_ID")
```

The artifact lands under `.map/<branch>/research/<subtask_id>__<kind>.md` and must satisfy the strict-JSON research contract: `status` ∈ {OK, PARTIAL_RESULTS, NO_RESULTS, SEARCH_FAILED}, `confidence` a number in [0,1], `search_stats` = {`files_scanned`:int, `total_matches_found`:int, `results_truncated`:bool}, and ≤5 `relevant_locations`, each {`path`, `lines`:[start,end] (≤200-line span), `relevance`} — full field table + copy-pasteable skeleton in [efficient-reference.md](efficient-reference.md) under "RESEARCH artifact schema"; `validate_research` also echoes that exact skeleton in its `skeleton` field on any failure, so the first reject self-corrects. Use `load_research` to fill the `{research_findings}` placeholder in Actor and Monitor prompts below. Actor must consume high-confidence research before re-exploring: if `confidence >= 0.7` and `relevant_locations` are present, first read 1-3 cited ranges; later repository-wide `rg`/`grep`/`find`/`git grep` needs a stated reason, such as low confidence, missing symbol, failed narrow read, changed hypothesis, or stale research. Low-confidence/location-free research may broaden sooner, but the gap must be named.

### Phase: TEST_WRITER (2.25) - TDD Mode Only

Write tests from the persisted contract before implementation. Do not edit production code in this phase.

### Phase: TEST_FAIL_GATE (2.26) - TDD Mode Only

Lint and run the new tests. Passing tests before Actor indicate weak tests; return to TEST_WRITER. Expected assertion failures allow ACTOR.

### Phase: ACTOR (2.3)

Generate the `<map_context>` via the `build_context_block` CLI on `map_step_runner.py` (blueprint + step state + dependency results + repo delta — full content; truncation infrastructure was removed, operators handle context size via `/compact` opt-in). Prefer the CLI form — it sets up `CLAUDE_PROJECT_DIR` resolution and import paths for you, so no inline `python -c` is needed.

```bash
SUBTASK_ID=$(jq -r '.current_subtask_id' ".map/${BRANCH}/step_state.json")
BOUNDED_MAP_CONTEXT=$(python3 .map/scripts/map_step_runner.py build_context_block "$BRANCH" "$SUBTASK_ID")
```

Then substitute `$BOUNDED_MAP_CONTEXT` into the Actor prompt below.

**Worktree isolation (opt-in, `worktree.isolation: true`):** when enabled, create the subtask's isolated git worktree before this dispatch and run the Actor inside it (dispatched WITHOUT harness-native isolation); the default disabled path is unchanged. Full recipe — commands, guard handling, Actor path instruction — in [efficient-reference.md](efficient-reference.md#worktree-isolation).

```text
Task(
  subagent_type="actor",
  description="Implement current subtask",
  prompt="""
<documents>
  <document source="map_context"><document_content>{bounded_map_context}</document_content></document>
  <document source="research"><document_content>{research_findings}</document_content></document>
</documents>
<task>
Implement exactly the current subtask. Preserve validation_criteria, coverage_map tags, hard_constraints, and soft_constraints tradeoffs. Do not expand scope.
Do not edit unrelated files, add or upgrade dependencies, or refactor neighboring code unless the current subtask contract explicitly requires it. Report any required scope expansion as a blocker/tradeoff.
Before re-running broad discovery (re-grep, re-read a large file, re-run the full test suite), check `.map/<branch>/compacted/MANIFEST.md` and `Read` the cited sidecar to recover the earlier output — re-run the tool only when recent edits, a new test run, an updated schema, or the task itself indicates the target has changed since capture.
</task>
<expected_output>
Return ONLY a JSON object (no markdown fences, no prose before/after) with files_changed (array of written paths), tests_run (array of "command — pass/fail"), validation_notes (string), and blocker (string or null). Write and run code via tools FIRST — this JSON is a post-work manifest; never put code, diffs, or logs inside it. Detail: [efficient-reference.md](efficient-reference.md).
</expected_output>
"""
)
```

### Actor truncated-response gate (MANDATORY — pre-MONITOR)

Before invoking Monitor, **pipe** Actor's captured response in — the detector reads stdin; a bare call returns `status:"no_input"`, NOT a pass:
`printf '%s' "$ACTOR_RESPONSE" | python3 .map/scripts/map_step_runner.py detect_truncated_agent_output --agent actor`.
If `truncated: true`, log via
`python3 .map/scripts/map_step_runner.py log_agent_failure` and re-invoke ONCE using the prompt from
`python3 .map/scripts/map_step_runner.py build_json_retry_prompt --agent actor --errors '<reasons>'`;
if still malformed, stop with CLARIFICATION_NEEDED.

**Files-changed mismatch check (MANDATORY):** Run
`python3 .map/scripts/map_step_runner.py detect_actor_files_changed_mismatch "$BRANCH" "$SUBTASK_ID" --declared "<Actor's files_changed, comma-joined>"`.
If `status_mismatch == true`, surface `recovery_instruction` and re-invoke Actor to finish `declared_not_written` files; do NOT record the subtask until clear. Full recipe: [efficient-reference.md](efficient-reference.md).

### Symbol blast-radius gate (MANDATORY — pre-dispatch)

Run `python3 .map/scripts/map_step_runner.py detect_symbol_blast_radius "$BRANCH" "$SUBTASK_ID"`. If
`recommended_gate == "validate_callers"`, append `external_callers` to the Monitor
`<documents>` context and require Monitor to validate each external caller's contract.
Full recipe: [efficient-reference.md](efficient-reference.md). Optional research-consumption advisory: pipe captured Actor shell/search commands into `python3 .map/scripts/map_step_runner.py detect_research_consumption_drift "$BRANCH" "$SUBTASK_ID"`; if it reports `advisory: true`, add the missing broad-search reason or do the cited narrow read before Monitor.

### Phase: MONITOR (2.4) - Required

```text
Task(
  subagent_type="monitor",
  description="Validate current subtask",
  prompt="""
<documents>
  <document source="map_context"><document_content>{bounded_map_context}</document_content></document>
  <document source="written_files"><document_content>{files_changed}</document_content></document>
  <document source="test_output"><document_content>{test_output}</document_content></document>
</documents>
<task>
Validate the implementation against the current subtask's AAG contract, validation_criteria, bracketed coverage_map tags, hard_constraints, and relevant soft_constraints/tradeoff_rationale.
Treat a sidecar under `.map/<branch>/compacted/` as evidence of what was checked, never as sole proof of correctness — ground every verdict in live source and a current test run.
</task>
<expected_output>
Return JSON with valid, summary, issues, files_changed, tests_run, and escalation_required.
</expected_output>
"""
)
```

# After Monitor returns:

- **Truncated-response gate (MANDATORY — pre-verdict):** Before reading
  `valid`/`recommendation`, **pipe** Monitor's response in (bare call → `status:"no_input"`, NOT a pass):
  `printf '%s' "$MONITOR_RESPONSE" | python3 .map/scripts/map_step_runner.py detect_truncated_agent_output --agent monitor`
  (JSON with `valid`, `summary`, `issues`, ends `}`). On truncation: log via
  `python3 .map/scripts/map_step_runner.py log_agent_failure` and re-invoke Monitor ONCE using the prompt from
  `python3 .map/scripts/map_step_runner.py build_json_retry_prompt --agent monitor --errors '<reasons>'`;
  if still malformed, stop with CLARIFICATION_NEEDED. Do NOT record the
  prose-response subtask as complete. Three signs:
  (a) doesn't parse as JSON, (b) missing one of
  `valid`/`summary`/`issues`, (c) ends mid-sentence with no closing `}`.
  Full recipe in [efficient-reference.md](efficient-reference.md).
- **Verdict contract (MANDATORY):** Monitor's `recommendation` field overrides
  loose `valid=true` calls. If `valid=true` AND `recommendation in {"revise",
  "block", "needs_investigation"}`, treat it as `valid=false`. Reason: a
  MEDIUM/HIGH issue with a permissive `valid` is the same broken-window
  pattern that silently merged "NOT NULL" / type-ignore mistakes. Only the
  combination `valid=true AND recommendation in {"proceed", "approve",
  null/missing}` is a clean pass.
- **Commit on clean Monitor close (ALLOWED, encouraged):** As soon as
  Monitor returns a clean verdict (`valid=true` AND
  `recommendation∈{proceed, approve, missing}`), create a per-subtask
  commit before advancing — without asking the user. Per-subtask
  commits keep the PR reviewable and lock `last_subtask_commit_sha`
  as the baseline for the next subtask's mutation-boundary check.
  Full recipe + "when NOT to commit" cases live in
  [efficient-reference.md](efficient-reference.md). Never `--no-verify`,
  never amend a published commit.
  - **Worktree isolation (`worktree.isolation: true`):** accept via
    `merge_subtask_worktree "$SUBTASK_ID"` instead of `git commit` (pre-merge
    verify + squash ONE commit; use its `merged_sha` for `--commit-sha`). On its
    `status:"error"` (treat the `kind` as a Monitor-class failure → discard +
    retry) or `no_changes:true`, follow [efficient-reference.md](efficient-reference.md#worktree-isolation); do not record the subtask.
- **Record the subtask result (REQUIRED on clean pass):**
  ```bash
  python3 .map/scripts/map_orchestrator.py record_subtask_result "$SUBTASK_ID" valid \
    --files "$FILES_CSV" --summary "$ONE_LINE" --commit-sha "$SHA"
  ```
  `record_subtask_result` is the canonical write path. Pass `--commit-sha`
  (preferred); omitting it triggers auto-detect via `git log -1 --format=%H`.
  If this subtask ever tripped an armed anti-repeat sign, also run
  `python3 .map/scripts/map_step_runner.py set_anti_repeat_subtask_status "$SUBTASK_ID" succeeded`
  so its signs are excluded from /map-learn candidates (it found a way through).
- **Auto-validate mutation boundary:** `validate_step 2.4` itself now runs
  `validate_mutation_boundary` for the current subtask and rejects on
  `status="violation"` (only when `MAP_STRICT_SCOPE=1`) or `status="error"`.
  No manual dispatch needed.
- **Refresh blueprint affected_files after each clean close (RECOMMENDED):**
  After commit + record_subtask_result, run
  `refresh_blueprint_affected_files "$BRANCH" "$SUBTASK_ID"`; default mode
  merges observed files into the approved surface. Use `--replace` only for
  intentional contract rewrite; see [efficient-reference.md](efficient-reference.md).
- If `valid=false`, write `code-review-N.md`, run `python3 .map/scripts/map_orchestrator.py monitor_failed --feedback "<feedback>"`, inspect `retry_isolation`, and invoke Predictor only when stuck/high-risk escalation rules apply. **Worktree isolation:** if enabled, run `discard_subtask_worktree "$SUBTASK_ID"` BEFORE retrying (atomic reject — a failed attempt is never merged; retry starts from a clean worktree). Recipe: [efficient-reference.md](efficient-reference.md#worktree-isolation). **If `monitor_failed` returns `status:"max_retries"` (budget exhausted), do NOT retry — run `python3 .map/scripts/map_step_runner.py build_escalation_outcome "$SUBTASK_ID" max_retries --retry-count <retry_count> --max-retries <max_retries>` and STOP with its `outcome` (surface the blocker to the user).**
- **Intra-run failure memory + bounded-effort escalation (MANDATORY on every `valid=false`):** record the rejection with `python3 .map/scripts/map_step_runner.py record_failure_signature "<monitor feedback>" "$SUBTASK_ID"`. If `armed:true`, prepend the block from `build_anti_repeat_constraint "$SUBTASK_ID"` (add `--quarantine-active` when CLEAN_RETRY is set) to the TOP of the next Actor prompt. If `escalation_recommended:true` (#255), the 3rd identical failure means the bounded recovery act did not work — do NOT retry and do NOT run the legacy retry-3 Stuck-Recovery for this identical loop; run `python3 .map/scripts/map_step_runner.py build_escalation_outcome "$SUBTASK_ID" repeated_failure` (add `--quarantine-active` on a CLEAN_RETRY iteration) and STOP with its `outcome:"BLOCKED"`. A `status:"not_escalated"` means the latest failure was a NEW signature (the Actor moved off the dead end) — resume normal retries. Full recipe: [efficient-reference.md](efficient-reference.md).
- If `retry_isolation=clean_retry_required`, validate `.map/<branch>/retry_quarantine.json` before CLEAN_RETRY. If a test/check fails inconsistently, collect repeated evidence with `run_flaky_test_triage ...` (or manually with `record_flaky_test_triage ...` if already collected), validate `.map/<branch>/flaky_test_triage.json`. Monitor must then emit `valid:false` + `disposition {kind:deferred_nondeterministic, check_id}`; close via the verdict-path route `validate_step 2.4 --disposition deferred_nondeterministic --check-id "<check-id>" --monitor-envelope -` (honored only when sidecar + envelope back it; deferral is `valid:false`+`deferred:true`, non-green, exit 0). `defer_flaky_subtask` remains the lower-level direct close. This is not a passing gate and must not weaken/skip/delete the check. Full recipe: [efficient-reference.md](efficient-reference.md).
- Treat test failures after Monitor approval as Monitor failure. **Cross-subtask regression gate (MANDATORY):** before the test gate, run `python3 .map/scripts/map_step_runner.py detect_cross_subtask_regression_risk "$BRANCH" "$SUBTASK_ID"`; if `recommended_gate == "full_suite"` you MUST run the FULL suite (never a `-k` subset) before commit / `record_subtask_result` — per-subtask Monitor is blind to regressions on prior subtasks' code. Recipe: [efficient-reference.md](efficient-reference.md).

### Phase: ADVANCE_SUBTASK (synthetic boundary)

After `validate_step 2.4` succeeds AND another subtask remains in the
sequence, the orchestrator returns `next_step: "ADVANCE_SUBTASK"`. This is
NOT a phase you execute — it just means "this subtask is done; call
`get_next_step` again to load the next subtask's RESEARCH (2.2)". The
sentinel exists so callers can tell mid-workflow advancement apart from a
real terminal `COMPLETE`. Treat it as a free transition: invoke
`get_next_step` and continue. (If you instead see `next_step: "COMPLETE"`
AND `subtask_index + 1 == len(subtask_sequence)`, the workflow is really
done — go to final verification.)

### Monitor Artifact Rule

Every Monitor failure must create a durable `code-review-N.md` with exact issue, file/path where possible, and Actor feedback.

### Per-Wave Gates (after all subtasks in wave pass Monitor)

Run build first, then tests, then linter. If build fails, skip tests/lint and reopen the owning subtask. Run the FULL test suite (not a `-k` subset) whenever any subtask in the wave tripped the cross-subtask regression gate (`recommended_gate == "full_suite"`) — a parallel wave that edits a shared file is the highest-risk case for a regression no single subtask's scoped run can see. **Worktree isolation, parallel wave:** when `worktree.isolation` is on and the wave has ≥2 isolated subtasks, accept the whole wave atomically with `merge_wave_worktrees` (never one at a time — the first merge trips `BASE_DIVERGED`); it runs this post-wave gate inside the transaction and rolls the wave back on failure — see [efficient-reference.md](efficient-reference.md#worktree-isolation).

## Step 2a: Validate Step Completion

```bash
python3 .map/scripts/map_orchestrator.py validate_step "$STEP_ID"
```

For step `2.4` (MONITOR close), ALWAYS pass `--recommendation
"$MONITOR_RECOMMENDATION"`. The orchestrator now treats
`recommendation ∈ {revise, block, needs_investigation}` as a structural
reject — silently passing `valid=true` while ignoring the
recommendation field is a known footgun the framework now refuses.

```bash
python3 .map/scripts/map_orchestrator.py validate_step 2.4 \
  --recommendation "$MONITOR_RECOMMENDATION"
```

Use `validate_wave_step` only in wave execution mode.

## Step 2b: Continue or Complete

**MANDATORY: Do NOT pause between subtasks.** After `validate_step 2.4`
returns `next_step: "ADVANCE_SUBTASK"`, immediately call `get_next_step`
again and continue executing the next subtask's RESEARCH/ACTOR/MONITOR
cycle in the SAME `/map-efficient` invocation. A subtask boundary is NOT
a checkpoint for the user — the only legitimate stops are:

1. `next_step: "COMPLETE"` with `subtask_index + 1 == len(subtask_sequence)`
   → workflow done, run Final Verification (Step 3).
2. `monitor_failed` retry quarantine requires user adjudication
   (`retry_isolation=clean_retry_required` AND clean_retry_count > max).
3. User explicitly interrupts via the conversation.
4. Circuit-breaker trips (`check_circuit_breaker` returns
   `should_stop=true`).

Per-subtask "summary report and wait for review" is the WRONG default —
it doubles round-trips and burns the operator's attention. The user
asked the skill to ship the whole plan; ship the whole plan. They can
interrupt at any time if they want a checkpoint.

Call `get_next_step` again immediately. Continue until complete, then
run final verification.

## Step 3: Final Verification (Ralph Loop)

Final verification proves the whole task, not just the last subtask.

### 3.1 Circuit Breaker Check

```bash
python3 .map/scripts/map_orchestrator.py check_circuit_breaker
```

### 3.2 Run Final Verifier

```text
Task(
  subagent_type="final-verifier",
  description="Verify workflow completion",
  prompt="Read the task plan, state file, artifact manifest, verification artifacts, code diff, and test output. Return PASS, REVISE, or BLOCK with evidence."
)
```

### 3.3 Evaluate Results

Set final status from verifier and gates:

- `complete` only when the task is implemented and verified.
- `pending` when more code work remains.
- `blocked` when an external/tooling dependency prevents verification.
- `won't_do` when intentionally abandoned.
- `superseded` when another branch/workflow owns the resolution.

```bash
RUN_HEALTH_STATUS="${RUN_HEALTH_STATUS:?set from final decision}"
python3 .map/scripts/map_step_runner.py write_run_health_report map-efficient "$RUN_HEALTH_STATUS"
python3 .map/scripts/map_step_runner.py write_learning_handoff map-efficient "" "$RUN_HEALTH_STATUS" "Run /map-learn to preserve patterns, then /map-review" ""
```

This writes `run_health_report.json` (machine-readable run snapshot) plus `learning-handoff.md`/`.json`, so a later zero-argument `/map-learn` auto-loads this run instead of reconstructing it from memory.

## Step 4: Summary

Report completed subtasks, files changed, checks run, final status, remaining issues, and next command (`/map-review`, the owning fix workflow, or optional `/map-learn` to preserve patterns).

## Examples

See [efficient-reference.md](efficient-reference.md#examples) for standard, TDD, sequential, and wave examples.

## Troubleshooting

See [efficient-reference.md](efficient-reference.md#troubleshooting) for state-machine mismatch, blueprint validation failures, Monitor retry loops, and run-health closeout problems.
