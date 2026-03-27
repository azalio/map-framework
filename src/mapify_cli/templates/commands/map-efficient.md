---
description: Token-efficient MAP workflow with state-machine orchestration
---

# MAP Efficient Workflow (Optimized)

## Core Design Principle

**State-Gated Prompting**: Each invocation sees exactly ONE clear next action.
State machine enforces sequencing, Python validates completion, hooks inject reminders.

## Execution Rules

1. Execute steps in order using state machine guidance
2. Use exact `subagent_type` specified — never substitute
3. Call each agent individually — no combining or skipping
4. Max 5 retry iterations per subtask (note: /map-fast uses max 3)
5. **Always batch mode, always parallel**: execution mode is always `batch` (no pauses). After INIT_STATE, always compute waves and execute independent subtasks in parallel (multiple `Task()` calls in one message). See "Wave Computation" section.
6. After Monitor pass, record files changed in `step_state.json` for guard isolation.

## Intentional Agent Omissions

/map-efficient does NOT use these agents (by design):
- **Evaluator** — quality scoring not needed; Monitor validates correctness directly
- **Reflector** — lesson extraction is a separate step via `/map-learn`

This is NOT a violation of MAP agent rules. Learning is decoupled into `/map-learn` (optional, run after workflow completes) to reduce token usage during execution.

## State File

Single source of truth: `.map/<branch>/step_state.json`

Written/read by `map_orchestrator.py`. Tracks: current phase, subtask states, wave states,
retry counts, constraints, files changed per subtask. Used by `workflow-gate.py` for
phase-based enforcement (Edit allowed only during ACTOR/APPLY/TEST_WRITER phases).

## Workflow Artifacts

Branch-scoped markdown artifacts in `.map/<branch>/`:

- `code-review-001.md`, `code-review-002.md`, ... — Monitor verdicts and required fixes
- `qa-001.md` — final verification results in human-readable form
- `pr-draft.md` — evolving PR summary, updated as execution finishes

## Architecture Overview

```text
┌─────────────────────────────────────────────────────────────┐
│  PreToolUse Hook (workflow-context-injector.py)             │
│  Injects: Current step, Progress, Mandatory next action     │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  map-efficient.md (THIS FILE - ~540 lines)                  │
│  1. Load state → Get next step instruction                  │
│  2. Route to appropriate executor based on step phase       │
│  3. Execute step (Actor/Monitor/tests/etc)                  │
│  4. Validate completion → Update state                      │
│  5. If more steps → Recurse; Else → Complete                │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  State Machine (map_orchestrator.py)                        │
│  Determines WHAT step to execute based on current state     │
└─────────────────────────────────────────────────────────────┘
```

## Flag Parsing

Parse optional flags from `$ARGUMENTS`:

- **`--tdd`**: Enable TDD mode (test-first workflow). Inserts TEST_WRITER and TEST_FAIL_GATE phases before ACTOR. Tests are written from spec before implementation.

```bash
# Extract flags and clean task description
TASK_ARGS="$ARGUMENTS"
TDD_FLAG=false
if echo "$TASK_ARGS" | grep -q -- '--tdd'; then
  TDD_FLAG=true
  TASK_ARGS=$(echo "$TASK_ARGS" | sed 's/--tdd//g' | xargs)
fi
```

**Task:** $TASK_ARGS

**IMPORTANT:** Use `$TASK_ARGS` (not `$ARGUMENTS`) in all agent prompts below. The `--tdd` flag has been stripped from `$TASK_ARGS` so it won't leak into task descriptions.

If `--tdd` is detected, enable TDD mode after state initialization:
```bash
if [ "$TDD_FLAG" = "true" ]; then
  python3 .map/scripts/map_orchestrator.py set_tdd_mode true
fi
```

## Step 0: Detect Existing Plan from /map-plan

Before starting the state machine, check if `/map-plan` already produced artifacts for this branch:

```bash
BRANCH=$(git rev-parse --abbrev-ref HEAD | sed -E 's|/|-|g; s|[^a-zA-Z0-9_.-]|-|g; s|-{2,}|-|g; s|^-||; s|-$||')
if [ -f ".map/${BRANCH}/task_plan_${BRANCH}.md" ] && [ ! -f ".map/${BRANCH}/step_state.json" ]; then
  # Plan exists but execution hasn't started — resume from plan
  # step_state.json is the orchestrator's canonical state (see "Dual State Files" above)
  python3 .map/scripts/map_orchestrator.py resume_from_plan
fi
```

If `resume_from_plan` succeeds, the orchestrator skips DECOMPOSE, INIT_PLAN, REVIEW_PLAN, and CHOOSE_MODE (plan already approved, batch mode auto-set) and starts from INIT_STATE.

## Step 1: Get Next Step Instruction

```bash
# Get next step from state machine
NEXT_STEP=$(python3 .map/scripts/map_orchestrator.py get_next_step)
STEP_ID=$(echo "$NEXT_STEP" | jq -r '.step_id')
PHASE=$(echo "$NEXT_STEP" | jq -r '.phase')
INSTRUCTION=$(echo "$NEXT_STEP" | jq -r '.instruction')
IS_COMPLETE=$(echo "$NEXT_STEP" | jq -r '.is_complete')

# Check if workflow complete
if [ "$IS_COMPLETE" = "true" ]; then
  echo "All subtasks complete. Running final verification..."
  # Go to Step 3: Final Verification
fi
```

## Step 2: Execute Step Based on Phase

Route to appropriate executor based on `$PHASE`:

### Phase: DECOMPOSE (1.0)

```python
Task(
  subagent_type="task-decomposer",
  description="Decompose task into subtasks",
  prompt=f"""Break down into ≤20 atomic subtasks and RETURN ONLY JSON.

Task: $TASK_ARGS

Hard requirements:
- Use `blueprint.subtasks[].validation_criteria` (2-4 testable outcomes)
  - Prefix each criterion with `VC1:`, `VC2:`, ... (stable references for Actor/Monitor)
  - Include a concrete anchor per VC (endpoint/function + file path)
- Use `blueprint.subtasks[].dependencies` (array of subtask IDs)
- Include `complexity_score` (1-10) and `risk_level` (low|medium|high)
- Include `security_critical` (true for auth/crypto/validation)
- Include `test_strategy` with unit/integration/e2e keys
  - Map every `VCn:` to ≥1 planned test case (prefer test name contains `vc<n>`)
  - Recommended format: `path/to/test_file.ext::test_name_or_symbol`
- Include `aag_contract` (one-line pseudocode: Actor -> Action -> Goal)

AAG Contract format (REQUIRED per subtask):
  "aag_contract": "AuthService -> validate(token) -> returns 401|200 with user_id"
  "aag_contract": "ProjectModel -> add_field(archived_at: DateTime?) -> migration passes"
  "aag_contract": "RateLimiter -> decorate(endpoint, 100/min) -> returns 429 when exceeded"

Purpose: Actor compiles this line into code. Monitor verifies against it.
This eliminates reasoning overhead — the contract IS the specification."""
)

# After decomposer returns:
# 1. Save the full blueprint JSON for wave computation:
#    Write the decomposer output to .map/<branch>/blueprint.json
# 2. Extract subtask IDs from blueprint and register them in state:
#    python3 .map/scripts/map_orchestrator.py set_subtasks ST-001 ST-002 ST-003
# 3. Validate step completion:
#    python3 .map/scripts/map_orchestrator.py validate_step "1.0"
```

### Phase: INIT_PLAN (1.5)

Generate `.map/<branch>/task_plan_<branch>.md` from blueprint:
- Header: Goal from blueprint.summary
- For each subtask: ### ST-XXX section with `- **Status:** pending`
- First subtask: `- **Status:** in_progress`
- Terminal State: `- **Status:** pending`

### Phase: REVIEW_PLAN (1.55)

Present the generated plan and require explicit user approval before any execution state is initialized.

1. Read the plan: `.map/<branch>/task_plan_<branch>.md`
2. Show a short summary in this format:

```text
═══════════════════════════════════════════════════
PLAN REVIEW CHECKPOINT
═══════════════════════════════════════════════════
Goal: <one line>
Subtasks:
  - ST-001: <title> (risk: <low|medium|high>)
  - ST-002: <title> (risk: <low|medium|high>)
Notes:
  - <top 1-3 risks/unknowns>
═══════════════════════════════════════════════════
```

3. Ask for approval using AskUserQuestion (example):

```
AskUserQuestion(questions=[
  {
    "question": "Approve this plan and start execution?",
    "header": "Plan approval",
    "options": [
      {"label": "Approve (recommended)", "description": "Proceed with chosen mode and start executing subtasks"},
      {"label": "Revise plan", "description": "Go back and adjust decomposition/plan before any code changes"},
      {"label": "Abort", "description": "Stop and do nothing"}
    ],
    "multiSelect": false
  }
])
```

If approved, persist it:

```bash
python3 .map/scripts/map_orchestrator.py set_plan_approved true
```

If not approved, stop (do not proceed).

### Phase: CHOOSE_MODE (1.56) — Auto-skipped

Execution mode is always `batch` (auto-set by orchestrator). No user interaction needed.
The orchestrator auto-skips this step and proceeds to INIT_STATE.

### Phase: INIT_STATE (1.6)

Get the branch name via Bash: `git rev-parse --abbrev-ref HEAD | sed -E 's|/|-|g; s|[^a-zA-Z0-9_.-]|-|g; s|-{2,}|-|g; s|^-||; s|-$||'`

State is managed by the orchestrator via `step_state.json` (created automatically by `map_orchestrator.py`). No manual state file creation needed.

### Wave Computation (after INIT_STATE) — REQUIRED

**IMPORTANT: Always compute waves and execute subtasks in parallel when possible.**
This is not optional — wave computation must run after every INIT_STATE.

After INIT_STATE (1.6) completes, compute execution waves from the dependency DAG:

```bash
BRANCH=$(git rev-parse --abbrev-ref HEAD | sed -E 's|/|-|g; s|[^a-zA-Z0-9_.-]|-|g; s|-{2,}|-|g; s|^-||; s|-$||')
if [ -f ".map/${BRANCH}/blueprint.json" ]; then
  python3 .map/scripts/map_orchestrator.py set_waves --blueprint .map/${BRANCH}/blueprint.json
else
  echo "WARNING: blueprint.json not found. Running subtasks sequentially."
  echo "To enable parallel waves, re-run /map-plan (saves blueprint.json since v3.5)."
fi
```

This reads the blueprint, builds a dependency graph, computes topological waves,
and splits waves by file conflicts. The result is stored in `step_state.json`.
If `blueprint.json` is missing (e.g., plan was created before v3.5), subtasks execute sequentially — this is safe but slower.

**Wave execution**: If waves are computed, subtasks within a wave run their Actor
and Monitor phases in parallel. Check wave status with:

```bash
WAVE=$(python3 .map/scripts/map_orchestrator.py get_wave_step)
MODE=$(echo "$WAVE" | jq -r '.mode')
```

If `mode` is `"parallel"`, launch all actors in the wave in ONE message using
multiple `Task()` calls, then all monitors in ONE message. If `mode` is
`"sequential"`, use the standard single-subtask loop below.

**Parallel wave execution loop**:

```
loop:
  WAVE = get_wave_step()
  if WAVE.is_complete: goto final_verification

  if WAVE.mode == "sequential":
    # Single subtask — same as standard behavior below
    execute_current_sequential_loop()
  else:
    # === PARALLEL WAVE ===
    # Phase A: Prep (sequential per subtask - lightweight)
    for each subtask in WAVE.subtasks:
      optional RESEARCH (if 3+ existing files or high risk)

    # Phase A.5: TDD phases (if --tdd mode)
    # When TDD is enabled, run TEST_WRITER + TEST_FAIL_GATE per subtask
    # BEFORE launching Actors. These run sequentially per subtask.
    if TDD_FLAG:
      for each subtask in WAVE.subtasks:
        run TEST_WRITER (2.25) → validate_wave_step SUBTASK_ID "2.25"
        run TEST_FAIL_GATE (2.26) → validate_wave_step SUBTASK_ID "2.26"

    # Phase B: Parallel Actors
    # Launch ALL Task(subagent_type="actor") calls in ONE message
    # Example: Task(actor, "Implement ST-002") + Task(actor, "Implement ST-004")

    # Phase C: Parallel Monitors
    # After all actors return, launch ALL monitors in ONE message
    # Example: Task(monitor, "Validate ST-002") + Task(monitor, "Validate ST-004")

    # Phase D: Retry handling
    # For each monitor that returned valid=false:
    #   RETRY=$(python3 .map/scripts/map_orchestrator.py wave_monitor_failed SUBTASK_ID "feedback")
    #   If RETRY.status == "max_retries": escalate to user
    #   Otherwise: re-run actor + monitor for that subtask (serially)

    # Phase E: Per-wave gates
    # Run tests + linter ONCE for the entire wave
    # pytest / npm test / etc.

    # Phase F: Advance wave — after all subtasks pass Monitor + per-wave gates
    python3 .map/scripts/map_orchestrator.py advance_wave
```

Linear DAGs naturally degrade to single-subtask waves (identical to current behavior).

### Phase: RESEARCH (2.2)

```python
# Conditional: Call if subtask touches 3+ existing files OR risk=high
if requires_research(subtask):
    Task(
      subagent_type="research-agent",
      description="Research for subtask [ID]",
      prompt=f"""Query: [subtask description]
File patterns: [relevant globs]
Intent: locate
Max tokens: 1500
Findings file: .map/{branch}/findings_{branch}.md

DISTILLATION RULE: Write ONLY actionable findings to the file:
- file paths + line ranges + function signatures
- NO raw search output, NO full file contents
- Target: <1500 tokens in findings file
This file is the SOLE research artifact passed to Actor and future steps."""
    )
```

### Phase: TEST_WRITER (2.25) — TDD Mode Only

Auto-skipped when TDD mode is disabled. When active:

```python
Task(
  subagent_type="actor",
  description="TDD: Write tests for subtask [ID]",
  prompt=f"""You are in TDD TEST_WRITER mode.

<MAP_Contract>
[AAG contract from decomposition]
</MAP_Contract>

<TDD_Mode>test_writer</TDD_Mode>

STRICT RULES:
1. Write ONLY test files. Do NOT create or modify implementation files.
2. Tests must be derived from the SPECIFICATION (AAG contract + validation_criteria).
3. You have NO knowledge of the implementation.
4. Each VCn: validation criterion must have at least one corresponding test.
5. Tests SHOULD fail when run (implementation doesn't exist yet).
6. Test files MUST be lint-clean. Use proper imports at the top of the file
   (not inside type annotations). Run the project linter on test files before finishing.

"""
)
```

### Phase: TEST_FAIL_GATE (2.26) — TDD Mode Only

Auto-skipped when TDD mode is disabled. When active:

**First:** lint-check test files (ACTOR cannot fix them later):
```bash
# Lint ONLY the test files from TEST_WRITER
ruff check <test_files> 2>&1 || true
# If lint errors → go back to TEST_WRITER with feedback to fix lint
```

**Then:** run the tests — they MUST fail:
```bash
# Run tests — expect failures (Red phase)
pytest --tb=short 2>&1 || true
# If tests PASS → go back to TEST_WRITER (tests are trivial)
# If tests FAIL with assertion errors → proceed to ACTOR (expected TDD state)
```

### Phase: ACTOR (2.3)

When TDD mode is active, Actor receives `<TDD_Mode>code_only</TDD_Mode>` and must NOT modify test files. When TDD is off, standard behavior.

```python
Task(
  subagent_type="actor",
  description="Implement subtask [ID]",
  prompt=f"""Implement and APPLY CODE with Edit/Write tools.

<MAP_Contract>
[AAG contract from decomposition: Actor -> Action -> Goal]
</MAP_Contract>

Subtask: [ID] [title]
Affected files: [from blueprint]
Validation criteria: [from blueprint]

Protocol:
1. Parse MAP_Contract — this is your compilation target
2. Read affected files to understand current state
3. Implement: translate MAP_Contract into code
4. Apply code with Edit/Write tools
5. Output: approach + files_changed + trade-offs"""
)
```

**CRITICAL: After Actor returns, do NOT debug or fix issues yourself.**
- If Actor reports diagnostics/errors — proceed directly to MONITOR.
- Monitor will verify and report real issues. If `valid=false`, retry via Actor (not manual edits).

### Phase: MONITOR (2.4)

```python
Task(
  subagent_type="monitor",
  description="Validate written code",
  prompt=f"""Validate WRITTEN CODE (Actor already applied with Edit/Write).

<MAP_Written files="[count]">
[list files modified by Actor]
</MAP_Written>

<MAP_Contract>
[AAG contract from decomposition: Actor -> Action -> Goal]
</MAP_Contract>

Protocol (execute in order):
1. Read each file in MAP_Written — verify code exists and compiles/parses
2. Check MAP_Contract compliance — does implementation satisfy the AAG assertion?
3. Run tests: pytest/npm test/go test/cargo test
4. Check inline contracts: preconditions, postconditions, invariants from packet
5. Verify: no silent failures, no bare except, no hardcoded secrets
6. Output: ONLY valid JSON per MonitorReviewOutput schema
   - If MAP_Contract violated: valid=false + specific contract breach
   - If tests fail: valid=false + failure output
   - If all pass: valid=true + contract_compliant=true"""
)
```

# After Monitor returns valid=true, run deterministic test gate:
TEST_GATE=$(python3 .map/scripts/map_step_runner.py run_test_gate)
# If tests fail, treat as Monitor valid=false — feed output back to Actor
if echo "$TEST_GATE" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('passed') else 1)" 2>/dev/null; then
    # Tests passed — snapshot code state for artifact verification
    SNAPSHOT=$(python3 .map/scripts/map_step_runner.py snapshot_code_state)
    # Append git ref to review artifact header (if code-review file exists)
fi

# After Monitor returns:
if monitor_output["valid"] == false:
    # Use orchestrator to handle retry: requeues ACTOR+MONITOR, increments retry_count,
    # switches phase so workflow-gate allows edits, persists feedback for Actor.
    RETRY_RESULT=$(python3 .map/scripts/map_orchestrator.py monitor_failed "MONITOR_FEEDBACK_TEXT")
    # RETRY_RESULT.status is "retrying" or "max_retries"
    # RETRY_RESULT.retry_count shows current attempt number
    # RETRY_RESULT.feedback_file points to .map/<branch>/monitor_feedback.md

    RETRY_STATUS=$(echo "$RETRY_RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))")
    RETRY_COUNT=$(echo "$RETRY_RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('retry_count',0))")

    if RETRY_STATUS == "max_retries":
        # Escalate to user (retry limit reached after 5 attempts)
        AskUserQuestion(questions=[{"question": "Monitor retry limit reached (5 attempts). How to proceed?", "header": "Retry limit", "options": [{"label": "Continue", "description": "Reset retry counter and try again"}, {"label": "Skip", "description": "Skip this subtask and move to next"}, {"label": "Abort", "description": "Stop workflow"}], "multiSelect": false}])

    # === STUCK RECOVERY (at retry 3) ===
    # At retry 3, intercept with intermediate recovery before retries 4-5.
    if RETRY_COUNT == 3:
        # Step 1: Check if research-agent already ran for this subtask
        findings_file = f".map/{branch}/findings_{branch}.md"
        if findings_file exists and has content for this subtask:
            recovery_context = read(findings_file)
        else:
            Task(
                subagent_type="research-agent",
                description="Stuck recovery: find alternative approach",
                prompt=f"""Subtask {subtask_id} failed 3 monitor retries.
Monitor feedback: {latest_monitor_feedback}
Find an ALTERNATIVE approach. Current approach is not working.
Focus on: different patterns, simpler implementations, existing utilities."""
            )
            recovery_context = research_agent_output

        # Step 2: Invoke predictor (skip for low-risk subtasks)
        if subtask.risk_level != "low":
            Task(
                subagent_type="predictor",
                description="Stuck recovery: analyze why approach fails",
                prompt=f"""Subtask {subtask_id} failed 3 retries.
Research findings: {recovery_context}
Analyze: why is the current approach failing? What dependencies are missed?"""
            )
            recovery_context += predictor_output

        if recovery_context is empty or unhelpful:
            AskUserQuestion(questions=[{"question": "Stuck recovery failed. How to proceed?", "header": "Stuck", "options": [{"label": "Continue", "description": "Try 2 more retries"}, {"label": "Skip", "description": "Skip subtask"}, {"label": "Abort", "description": "Stop workflow"}], "multiSelect": false}])
    # === END STUCK RECOVERY ===

    # Phase is now ACTOR (set by orchestrator). Proceed to get_next_step
    # which will return ACTOR instruction. Pass RETRY_RESULT.feedback_file path
    # to Actor so it can read the monitor feedback explicitly.

# For wave-based execution, use wave_monitor_failed instead:
# python3 .map/scripts/map_orchestrator.py wave_monitor_failed ST-001 "feedback text"
```

### Monitor Artifact Rule

After EVERY Monitor run, write a new execution review artifact in `.map/<branch>/code-review-XXX.md`.

- First Monitor result for the workflow: `code-review-001.md`
- Second: `code-review-002.md`
- Continue incrementing for each validation iteration, including retries

Each review artifact must include:
- subtask ID
- verdict (`valid=true/false`)
- key findings grouped by severity
- exact fixes required before retry, if any

Do not overwrite the previous review file; keep the loop history visible.

### Per-Wave Gates (after all subtasks in wave pass Monitor)

After ALL subtasks in a wave have Monitor `valid=true`, run tests + linter ONCE for the entire wave:

```bash
# Run tests — capture exit code + output
TESTS_EXIT=0
TEST_OUTPUT=""
if [ -f "pytest.ini" ] || [ -f "setup.py" ]; then
  TEST_OUTPUT=$(pytest 2>&1); TESTS_EXIT=$?
elif [ -f "package.json" ]; then
  TEST_OUTPUT=$(npm test 2>&1); TESTS_EXIT=$?
elif [ -f "go.mod" ]; then
  TEST_OUTPUT=$(go test ./... 2>&1); TESTS_EXIT=$?
elif [ -f "Cargo.toml" ]; then
  TEST_OUTPUT=$(cargo test 2>&1); TESTS_EXIT=$?
else
  echo "No tests found, skipping gate"
fi
echo "$TEST_OUTPUT"

# Run linter — capture exit code + output
LINT_EXIT=0
LINT_OUTPUT=""
if command -v ruff &> /dev/null; then
  LINT_OUTPUT=$(ruff check . 2>&1); LINT_EXIT=$?
elif command -v eslint &> /dev/null; then
  LINT_OUTPUT=$(eslint . 2>&1); LINT_EXIT=$?
elif command -v golangci-lint &> /dev/null; then
  LINT_OUTPUT=$(golangci-lint run 2>&1); LINT_EXIT=$?
else
  echo "No linter found, skipping gate"
fi
echo "$LINT_OUTPUT"
```

**Guard Pattern Decision (per-wave):**

```
IF TESTS_EXIT == 0 AND LINT_EXIT == 0:
  → Wave passed. Advance to next wave.

ELSE (regression detected):
  → Isolate: Use subtask_files_changed from step_state.json to identify
    which subtask's files cause the failure. Run failing tests per-subtask file set.
  → If single subtask isolated: retry that subtask's Actor with guard context (max 2 rework).
  → If interaction failure (no single culprit): rerun wave sequentially to identify.
  → After rework: re-run full wave gates.
  → If 2 rework attempts fail: escalate to user (Skip/Abort).
```

**Key invariant:** Guard rework never modifies test files — Actor must adapt implementation to pass existing tests.
**NOT between retries:** Gates run only after ALL subtasks in wave pass Monitor, not between Actor→Monitor retry iterations.

## Step 2a: Validate Step Completion

After executing step, validate and update state:

```bash
# Validate step completion
python3 .map/scripts/map_orchestrator.py validate_step "$STEP_ID"
```

## Step 2b: Continue or Complete

```bash
# Get next step
NEXT_STEP=$(python3 .map/scripts/map_orchestrator.py get_next_step)
IS_COMPLETE=$(echo "$NEXT_STEP" | jq -r '.is_complete')

if [ "$IS_COMPLETE" = "true" ]; then
  echo "All subtasks complete. Proceeding to final verification."
  # Go to Step 3
else
  # Context for fresh invocation comes from files only:
  # 1. step_state.json    — single source of truth for progress
  # 2. task_plan.md       — plan with subtask statuses
  # 3. findings.md        — distilled research (if discovery was done)
  # 4. code-review-XXX.md — Monitor verdicts
  echo "Next step: $(echo "$NEXT_STEP" | jq -r '.step_id')"
fi
```

## Step 3: Final Verification (Ralph Loop)

### 3.1 Circuit Breaker Check

```bash
# Get circuit breaker status
CB_DATA=$(python3 .map/scripts/map_orchestrator.py check_circuit_breaker)
TOOL_COUNT=$(echo "$CB_DATA" | jq -r '.tool_count')
MAX_ITERATIONS=$(echo "$CB_DATA" | jq -r '.max_iterations')

if [ "$TOOL_COUNT" -ge "$MAX_ITERATIONS" ]; then
  # Ask user how to proceed
  AskUserQuestion(questions=[{"question": "Circuit breaker triggered. How to proceed?", "header": "Circuit breaker", "options": [{"label": "Reset limits", "description": "Reset counters and continue workflow"}, {"label": "Abort", "description": "Stop workflow immediately"}], "multiSelect": false}])
fi
```

### 3.2 Run Final Verifier

```python
Task(
    subagent_type="final-verifier",
    description="Final verification of entire goal",
    prompt=f"""Verify ORIGINAL GOAL is fully achieved.

**Original Goal:** {goal_from_task_plan}
**Validation Criteria:** {criteria_from_decomposition}
**Completed Subtasks:** {list_of_subtask_ids}
**Branch:** {branch}

You MUST:
1. Run available tests
2. Check MCP tools for ground-truth if available
3. Verify integration between subtasks
4. If FAILED: Provide Root Cause Analysis JSON

Write results to .map/{branch}/final_verification.json"""
)
```

After final verifier returns, update `.map/<branch>/qa-001.md` with:
- commands run
- pass/fail summary
- residual risks
- rollback notes if applicable

Also write `.map/<branch>/verification-summary.md` with a compact final report using:

```bash
python3 .map/scripts/map_step_runner.py write_verification_summary "READY FOR REVIEW" "<task title>" "- pytest ...,- ruff ..." "- notable findings" "- open PR"
```

The summary should include:
- overall verdict
- key commands executed
- notable failures or warnings
- confidence / risk statement
- recommended next action (review, rework, release)

Also update `.map/<branch>/pr-draft.md` with:
- concise summary of delivered behavior
- validation commands/results
- notable risks or follow-up work

Update `.map/<branch>/pr-draft.md` with final summary and verification results.

### 3.3 Evaluate Results

```python
verification = load_verification_result()

if verification["passed"] and verification["confidence"] >= 0.7:
    # SUCCESS
    update_terminal_state("complete")
    print("✅ Workflow complete! Optional: Run /map-learn to preserve patterns.")

# NOTE: The conditions below are pseudocode representing orchestrator-level
# logic. The actual implementation uses check_circuit_breaker and retry_count
# from step_state.json to detect these conditions.

elif verification["retry_count"] > verification["max_retries"]:
    # Thrashing detected - too many retries without progress
    AskUserQuestion(questions=[{"question": "Thrashing detected (repeated failures). How to proceed?", "header": "Thrashing", "options": [{"label": "Force complete", "description": "Mark as complete despite failures"}, {"label": "Continue", "description": "Reset retry counter and try again"}, {"label": "Abort", "description": "Stop workflow"}], "multiSelect": false}])

elif check_circuit_breaker()["triggered"] == false:
    # Re-decomposition: break remaining work into new subtasks
    Task(subagent_type="task-decomposer", description="Re-decompose remaining work", prompt="...")

else:
    # Max iterations reached
    AskUserQuestion(questions=[{"question": "Max iterations reached. How to proceed?", "header": "Max iterations", "options": [{"label": "Reset limits", "description": "Reset counters and continue"}, {"label": "Abort", "description": "Stop workflow"}], "multiSelect": false}])
```

## Step 4: Summary

- Update Terminal State in task_plan: **Status:** complete
- Report features implemented, files changed, verification confidence
- **Optional:** Run `/map-learn [summary]` to preserve patterns

Begin execution now.
