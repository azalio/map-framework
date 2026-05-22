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

Use [efficient-reference.md](efficient-reference.md) for wave examples, TDD details, final-verifier retry policy, examples, and troubleshooting. When a workflow step points to a reference section, read that section before executing the step; supporting files are not assumed to be in context automatically.

## Effort and Parallelism Policy

```yaml
thinking_policy: medium/adaptive
parallel_tool_policy: guarded_wave_only
```

- Use deeper reasoning only when a subtask is risky, blocked, under-specified, or repeatedly failing Monitor.
- Keep execution sequential by default. Parallel waves are allowed only under the existing wave rules: all dependencies satisfied, low risk, disjoint new-file writes, and the wave API is used.
- Do not parallelize state transitions, Monitor retries for the same subtask, or writes to shared branch artifacts.

## Execution Rules

1. Execute the next state-machine step only; never skip phases.
2. Use the exact agent type for the current phase.
3. Max 5 retry iterations per subtask.
4. Batch mode is default. Sequential subtask execution is default.
5. After Monitor pass, record files changed in `step_state.json` for guard isolation.
6. Validate planning metadata before Actor starts: `expected_diff_size`, `concern_type`, `one_logical_step`, `split_rationale`, `concern_justification`, `coverage_map`, `hard_constraints`, `soft_constraints`, `validation_criteria`, `[AC-1]` bracket tags, and `tradeoff_rationale`.

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

## Step 0: Detect Existing Plan from /map-plan

Resume from existing plan artifacts when present:

```bash
BRANCH=$(git rev-parse --abbrev-ref HEAD | sed -E 's|/|-|g; s|[^a-zA-Z0-9_.-]|-|g; s|-{2,}|-|g; s|^-||; s|-$||')
if [ -f ".map/${BRANCH}/task_plan_${BRANCH}.md" ]; then
  RESUME_RESULT=$(python3 .map/scripts/map_orchestrator.py resume_from_plan)
  RESUME_STATUS=$(echo "$RESUME_RESULT" | jq -r '.status')
  if [ "$RESUME_STATUS" = "success" ]; then
    echo "Resumed from /map-plan artifacts."
  fi
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

### Wave Computation (after INIT_STATE) - REQUIRED

```bash
BRANCH=$(git rev-parse --abbrev-ref HEAD | sed -E 's|/|-|g; s|[^a-zA-Z0-9_.-]|-|g; s|-{2,}|-|g; s|^-||; s|-$||')
if [ -f ".map/${BRANCH}/blueprint.json" ]; then
  python3 .map/scripts/map_orchestrator.py set_waves --blueprint .map/${BRANCH}/blueprint.json
else
  echo "WARNING: blueprint.json not found. Running subtasks sequentially."
fi
```

Default to sequential execution. Use wave APIs only for low-risk disjoint new-file waves or explicit user-requested parallel execution. See [efficient-reference.md](efficient-reference.md#wave-execution) for the full wave loop.

### No-op subtask short-circuit (before RESEARCH)

Some subtasks are already-done historically (rename/refactor landed in a prior PR), or are docs-only and don't need the full research→actor→monitor cycle. Skip them up-front to save tokens:

```bash
python3 .map/scripts/map_orchestrator.py mark_subtask_complete "$SUBTASK_ID" \
  --reason "rename already landed in commit <sha>; verified via git log"
```

This records a synthetic subtask_result with status="no-op", marks the phase COMPLETE, and advances the cursor (or closes the workflow if it was the last). Always pass `--reason` so audits know why the work was skipped. If unsure, run RESEARCH first and decide based on its findings.

### Phase: RESEARCH (2.2) - Required

Call `research-agent` for the current subtask, then persist its concise findings via the canonical `save_research` API so Actor and Monitor consume them from the same path. Validate the phase with the orchestrator.

```bash
# After research-agent returns findings in $RESEARCH_FINDINGS:
printf '%s' "$RESEARCH_FINDINGS" | \
  python3 .map/scripts/map_step_runner.py save_research "$BRANCH" "$SUBTASK_ID"
# (defaults kind=actor; pass a 4th arg like 'monitor' or 'decomposer' to partition)
```

Later phases read with:

```bash
RESEARCH_FINDINGS=$(python3 .map/scripts/map_step_runner.py load_research "$BRANCH" "$SUBTASK_ID")
```

The artifact lands under `.map/<branch>/research/<subtask_id>__<kind>.md`. Use `load_research` to fill the `{research_findings}` placeholder in Actor and Monitor prompts below.

### Phase: TEST_WRITER (2.25) - TDD Mode Only

Write tests from the persisted contract before implementation. Do not edit production code in this phase.

### Phase: TEST_FAIL_GATE (2.26) - TDD Mode Only

Lint and run the new tests. Passing tests before Actor indicate weak tests; return to TEST_WRITER. Expected assertion failures allow ACTOR.

### Phase: ACTOR (2.3)

Generate the bounded `<map_context>` via the `build_context_block` CLI on `map_step_runner.py` (blueprint + step state + dependency results + repo delta, budget-capped). Prefer the CLI form — it sets up `CLAUDE_PROJECT_DIR` resolution and import paths for you, so no inline `python -c` is needed.

```bash
SUBTASK_ID=$(jq -r '.current_subtask_id' ".map/${BRANCH}/step_state.json")
BOUNDED_MAP_CONTEXT=$(python3 .map/scripts/map_step_runner.py build_context_block "$BRANCH" "$SUBTASK_ID")
```

Then substitute `$BOUNDED_MAP_CONTEXT` into the Actor prompt below.

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
</task>
<expected_output>
Return files_changed, tests_run, validation_notes, and any blocker.
</expected_output>
"""
)
```

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
</task>
<expected_output>
Return JSON with valid, summary, issues, files_changed, tests_run, and escalation_required.
</expected_output>
"""
)
```

# After Monitor returns:

- If `valid=true`, run the deterministic test gate, record the subtask result, and validate/advance the state.
- If `valid=false`, write `code-review-N.md`, run `python3 .map/scripts/map_orchestrator.py monitor_failed --feedback "<feedback>"`, inspect `retry_isolation`, and invoke Predictor only when stuck/high-risk escalation rules apply.
- If `retry_isolation=clean_retry_required`, run `python3 .map/scripts/map_step_runner.py validate_retry_quarantine` before the next Actor call. The next Actor prompt must use CLEAN_RETRY mode from `.map/<branch>/retry_quarantine.json` and must not reuse the rejected approach unless the quarantine artifact preserves it.
- Treat test failures after Monitor approval as Monitor failure.

### Monitor Artifact Rule

Every Monitor failure must create a durable `code-review-N.md` with exact issue, file/path where possible, and Actor feedback.

### Per-Wave Gates (after all subtasks in wave pass Monitor)

Run build first, then tests, then linter. If build fails, skip tests/lint and reopen the owning subtask.

## Step 2a: Validate Step Completion

```bash
python3 .map/scripts/map_orchestrator.py validate_step "$STEP_ID"
```

Use `validate_wave_step` only in wave execution mode.

## Step 2b: Continue or Complete

Call `get_next_step` again. Continue until complete, then run final verification.

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
python3 .map/scripts/map_step_runner.py write_run_health_report \
  map-efficient \
  "$RUN_HEALTH_STATUS"
```

This writes `.map/<branch>/run_health_report.json`, updates `run_health`, and gives reviewers a machine-readable terminal snapshot.

## Step 4: Summary

Report completed subtasks, files changed, checks run, final status, remaining issues, and next command (`/map-review` or the owning fix workflow).

## Examples

See [efficient-reference.md](efficient-reference.md#examples) for standard, TDD, sequential, and wave examples.

## Troubleshooting

See [efficient-reference.md](efficient-reference.md#troubleshooting) for state-machine mismatch, blueprint validation failures, Monitor retry loops, and run-health closeout problems.
