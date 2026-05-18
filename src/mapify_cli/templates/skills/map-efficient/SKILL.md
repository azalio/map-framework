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

**State-Gated Prompting**: Each invocation sees exactly ONE clear next action.
State machine enforces sequencing, Python validates completion, hooks inject reminders.

## Effort and Parallelism Policy

```yaml
thinking_policy: medium/adaptive
parallel_tool_policy: guarded_wave_only
```

- Use deeper reasoning only when a subtask is risky, blocked, under-specified, or repeatedly failing Monitor; otherwise follow the state machine directly.
- Keep execution sequential by default. Parallel waves are allowed only under the existing wave rules: all dependencies satisfied, low risk, disjoint new-file writes, and the wave API is used.
- Do not parallelize state transitions, Monitor retries for the same subtask, or writes to shared branch artifacts.

## Execution Rules

1. Execute steps in order using state machine guidance
2. Use exact `subagent_type` specified — never substitute
3. Call each agent individually — no combining or skipping
4. Max 5 retry iterations per subtask (note: /map-fast uses max 3)
5. **Always batch mode, sequential by default**: execution mode is always `batch` (no pauses). After INIT_STATE, compute waves but execute subtasks **one at a time** (sequential). Parallel execution within a wave is allowed ONLY when wave has ≤3 subtasks AND all are low-risk AND all create new files (no modifications to existing files). See "Wave Computation" section.
6. After Monitor pass, record files changed in `step_state.json` for guard isolation.

## Intentional Agent Omissions

/map-efficient does NOT use these agents (by design):
- **Evaluator** — quality scoring not needed; Monitor validates correctness directly
- **Reflector** — lesson extraction is a separate step via `/map-learn`

This is NOT a violation of MAP agent rules. Learning is decoupled into `/map-learn` (optional, run after workflow completes) to reduce token usage during execution.

**Conditional agent:** Predictor is invoked only during stuck recovery (retry 3+, non-low-risk subtasks).

## State File

Single source of truth: `.map/<branch>/step_state.json`

Written/read by `map_orchestrator.py`. Tracks: current phase, subtask states, wave states,
retry counts, constraints, files changed per subtask. Used by `workflow-gate.py` for
phase-based enforcement (Edit allowed only during ACTOR/APPLY/TEST_WRITER phases).

**NEVER modify `step_state.json` directly.** Always use the orchestrator CLI
(`map_orchestrator.py`, `map_step_runner.py`). Direct writes bypass validation and
corrupt state transitions. If an orchestrator operation doesn't work — it's a bug,
ask the user.

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
- If you need a persisted clean-session handoff between tests and implementation, prefer `/map-tdd ST-001` and then resume with `/map-task ST-001`.

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

If a task plan exists from a prior `/map-plan` run, resume from it instead of re-decomposing:

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
  - Cite every owned `coverage_map` key in brackets inside the owning criterion, e.g. `VC1 [AC-1]: checkout timeout shows retryable message`
  - Include a concrete anchor per VC (endpoint/function + file path)
- Use `blueprint.subtasks[].dependencies` (array of subtask IDs)
- Include `complexity_score` (1-10) and `risk_level` (low|medium|high)
- Include `expected_diff_size` (tiny|small|medium|large), `concern_type` (api|config|data|docs|infra|observability|refactor|release|runtime|security|tests|ui|mixed), and `one_logical_step: true`
- Split large subtasks unless a concrete `split_rationale` explains why the user payoff requires that scope in one subtask
- Split mixed-concern subtasks unless a concrete `concern_justification` explains why the concerns cannot be separated without losing user value
- Include `security_critical` (true for auth/crypto/validation)
- Include `test_strategy` with unit/integration/e2e keys
  - Map every `VCn:` to ≥1 planned test case (prefer test name contains `vc<n>`)
  - Recommended format: `path/to/test_file.ext::test_name_or_symbol`
- Include `aag_contract` (one-line pseudocode: Actor -> Action -> Goal)
- Include top-level `hard_constraints` for non-negotiable requirements; every `hard_constraints[].id` must appear in `coverage_map` and as a bracket tag in the owning `validation_criteria`
- Include top-level `soft_constraints` for negotiable preferences; each `soft_constraints[].id` must either appear in `coverage_map` or include `tradeoff_rationale`
- Include top-level `coverage_map` mapping each acceptance criterion, invariant, and cross-cutting requirement to its owning subtask ID; each key must appear as a matching bracket tag in that subtask's `validation_criteria`

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
# 2. Validate contract-sized subtask metadata before execution can start:
#    python3 .map/scripts/map_step_runner.py validate_blueprint_contract
# 3. Extract subtask IDs from blueprint and register them in state:
#    python3 .map/scripts/map_orchestrator.py set_subtasks ST-001 ST-002 ST-003
# 4. Validate step completion:
#    python3 .map/scripts/map_orchestrator.py validate_step "1.0"
```

### Phase: INIT_PLAN (1.5)

Generate `.map/<branch>/task_plan_<branch>.md` from blueprint:
- Header: Goal from blueprint.summary
- For each subtask: ### ST-XXX section with `- **Status:** pending`
- Include each subtask's `expected_diff_size`, `concern_type`, and `one_logical_step` so reviewers can spot scope creep before Actor starts
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

**IMPORTANT: Always compute waves after INIT_STATE.** Waves determine execution
order from the dependency graph. Subtasks execute **sequentially by default**.

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

**Wave execution**: Subtasks execute **sequentially by default** (one at a time through
the full RESEARCH → ACTOR → MONITOR cycle). This prevents accumulated errors that are
hard to debug. Check wave status with:

```bash
WAVE=$(python3 .map/scripts/map_orchestrator.py get_wave_step)
MODE=$(echo "$WAVE" | jq -r '.mode')
```

**Two execution modes are supported:** sequential (default) and parallel (wave-based).

### Sequential execution loop (DEFAULT)

Use when waves have >3 subtasks or subtasks modify existing files:

```
loop:
  WAVE = get_wave_step()
  if WAVE.is_complete: goto final_verification

  for each subtask in WAVE.subtasks (one at a time):
    1. RESEARCH (2.2) — run research-agent
    2. ACTOR (2.3) — implement subtask
    3. MONITOR (2.4) — MANDATORY: validate + BUILD GATE. NEVER skip.
    4. validate_step / advance to next subtask

  # After ALL subtasks in wave pass: run per-wave gates
  python3 .map/scripts/map_orchestrator.py advance_wave
```

**DO NOT** write custom bash for-loops to iterate subtasks. Use the orchestrator:
call `get_next_step` after each `validate_step` — it returns the next phase/subtask
automatically. The state machine handles iteration.

### Parallel execution loop (wave-based)

Use when wave has ≤3 subtasks AND all are low-risk AND all create new files only.
Also allowed for any wave size when the user explicitly requests parallel execution.

**CRITICAL:** When running subtasks in parallel, use the **wave API** (`validate_wave_step`,
`advance_wave`), NOT the sequential API (`validate_step`, `get_next_step`).
The sequential API tracks only ONE `current_subtask_id` and will fail for parallel work.

```
loop:
  WAVE = get_wave_step()
  if WAVE.is_complete: goto final_verification

  # 1. Run ALL Research in parallel (one Agent per subtask) — MANDATORY
  for each subtask in WAVE.subtasks (in parallel):
    Agent(subagent_type="research-agent", prompt="Research subtask {subtask_id}...")

  # 2. Run ALL Actors in parallel (one Agent per subtask)
  for each subtask in WAVE.subtasks (in parallel):
    Agent(subagent_type="actor", prompt="Implement subtask {subtask_id}...")

  # 3. Run ALL Monitors in parallel (one Agent per subtask)
  for each subtask in WAVE.subtasks (in parallel):
    Agent(subagent_type="monitor", prompt="Validate subtask {subtask_id}...")

  # 4. Record results and advance phases for EACH subtask:
  for each subtask:
    echo '{"subtask_id":"ST-XXX","files":[...],"status":"valid",...}' \
      | python3 .map/scripts/map_step_runner.py record_subtask_result
    python3 .map/scripts/map_orchestrator.py validate_wave_step ST-XXX 2.2
    python3 .map/scripts/map_orchestrator.py validate_wave_step ST-XXX 2.3
    python3 .map/scripts/map_orchestrator.py validate_wave_step ST-XXX 2.4

  # 5. Run per-wave gates (build + tests + lint), then advance
  python3 .map/scripts/map_orchestrator.py advance_wave
```

**Key difference:** `validate_wave_step <subtask_id> <step_id>` works per-subtask
and does NOT require `current_subtask_id` to match. After `advance_wave`, the state
is synchronized for sequential API — you can switch back to `get_next_step` for
subsequent waves.

### Phase: RESEARCH (2.2) — MANDATORY

**CRITICAL: ALWAYS run research. Do NOT skip this phase.**

Research prevents the most common failure mode: Actor writing code that doesn't integrate
with the existing codebase (wrong imports, missing types, incompatible APIs).

```python
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
- existing import patterns and module structure
- build/compile configuration (tsconfig, setup.py, Cargo.toml, etc.)
- NO raw search output, NO full file contents
- Target: <1500 tokens in findings file
This file is the SOLE research artifact passed to Actor and future steps."""
)
```

**Re-use existing findings**: if `/map-plan` already produced a findings file for this
branch (`.map/<branch>/findings_<branch>.md` exists and has content), the research agent
should read and extend it rather than starting from scratch. RESEARCH still runs — it
just builds on prior findings.

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
7. Do NOT add temporal comments about test failure status (e.g., "currently FAILS",
   "expected to FAIL"). Tests are permanent, clean code — the Red/Green state is transient.

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

If you want to stop after the red phase and resume implementation in a clean session, persist `test_contract_<subtask>.md` + `test_handoff_<subtask>.json` via `/map-tdd ST-001`, then continue later with `/map-task ST-001`.

### Phase: ACTOR (2.3)

When TDD mode is active, Actor receives `<TDD_Mode>code_only</TDD_Mode>` and must NOT modify test files. When TDD is off, standard behavior.

```python
# Context assembly: use build_context_block() from map_step_runner.py
# to generate <map_context> when called programmatically.
# For manual invocation, construct the block from blueprint.json + step_state.json.

Task(
  subagent_type="actor",
  description="Implement subtask [ID]",
  prompt=f"""Implement and APPLY CODE with Edit/Write tools.

<MAP_Contract>
[AAG contract from decomposition: Actor -> Action -> Goal]
</MAP_Contract>

<map_context>
# Goal
[Goal from task_plan.md — one sentence]

# Current Subtask: [ID] — [title]
AAG Contract: [contract from blueprint]
Affected files: [from blueprint]
Validation criteria:
- [criteria from blueprint]

# Plan Overview ([N] subtasks):
[For each subtask in blueprint, show one-liner with status:]
- [x] ST-001: Title (complete)
- [ ] ST-002: Title (pending)
- [>>] ST-003: Title (IN PROGRESS) <- current

# Upstream Results (dependencies of current subtask):
[Only for subtasks that current depends on, from step_state.json subtask_results:]
ST-001: files=[a.py, b.py], status=valid

# Repo Delta (files changed since last subtask):
[From compute_differential_insight(), if last_subtask_commit_sha available]
[Omit this section entirely if no previous SHA (first subtask)]
</map_context>

Protocol:
1. SCOPE: Implement ONLY the Current Subtask. Do NOT modify files belonging to other subtasks.
2. Plan Overview is for orientation — do NOT implement other subtasks.
3. Upstream Results show what dependencies produced — use as input context.
4. Parse MAP_Contract — this is your compilation target.
5. Read affected files to understand current state.
6. Implement: translate MAP_Contract into code.
7. Apply code with Edit/Write tools.
8. Output: approach + files_changed + trade-offs"""
)
```

**CRITICAL: After Actor returns, do NOT debug or fix issues yourself.**
- If Actor reports diagnostics/errors — proceed directly to MONITOR.
- Monitor will verify and report real issues. If `valid=false`, retry via Actor (not manual edits).

### Phase: MONITOR (2.4) — MANDATORY

**CRITICAL: ALWAYS run Monitor after Actor. Do NOT skip this phase.**

Monitor is the ONLY validation gate between Actor output and step completion.
Even if tests already pass, Monitor checks contract compliance, code quality,
security issues, and integration correctness that tests alone cannot verify.
**Never skip Monitor because "tests pass" — passing tests is necessary but NOT sufficient.**

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
2. **BUILD GATE (MANDATORY):** Run the project build/compile command BEFORE any other checks:
   - TypeScript: `npx tsc --noEmit` (or `npm run build`)
   - Python: `python -m py_compile <files>` (or `python -m mypy <files>` if configured)
   - Go: `go build ./...`
   - Rust: `cargo check`
   - If build fails → valid=false immediately, report compilation errors
3. Check MAP_Contract compliance — does implementation satisfy the AAG assertion?
4. Run tests: pytest/npm test/go test/cargo test
5. Check inline contracts: preconditions, postconditions, invariants from packet
6. Verify: no silent failures, no bare except, no hardcoded secrets
7. Output: ONLY valid JSON per MonitorReviewOutput schema
   - If build fails: valid=false + compilation errors
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

    # Record subtask result for context-aware injection (Upstream Results + Repo Delta)
    # Uses record_subtask_result CLI dispatch via stdin JSON (injection-safe, single source of truth).
    FILES_JSON=$(echo "$SNAPSHOT" | python3 -c "import sys,json; print(json.dumps(json.load(sys.stdin).get('files_changed',[])))")
    CURRENT_SHA=$(git rev-parse HEAD 2>/dev/null || echo "")
    if [ -n "$CURRENT_SHA" ]; then
        echo "{\"files\": ${FILES_JSON}, \"status\": \"valid\", \"summary\": \"Monitor passed + tests passed\", \"commit_sha\": \"${CURRENT_SHA}\"}" | python3 .map/scripts/map_step_runner.py record_subtask_result
    else
        echo "{\"files\": ${FILES_JSON}, \"status\": \"valid\", \"summary\": \"Monitor passed + tests passed\"}" | python3 .map/scripts/map_step_runner.py record_subtask_result
    fi
fi

# After Monitor returns:
if monitor_output["valid"] == false:
    # Use orchestrator to handle retry: requeues ACTOR+MONITOR, increments retry_count,
    # switches phase so workflow-gate allows edits, persists feedback for Actor.
    RETRY_RESULT=$(python3 .map/scripts/map_orchestrator.py monitor_failed --feedback "MONITOR_FEEDBACK_TEXT")
    # RETRY_RESULT.status is "retrying" or "max_retries"
    # RETRY_RESULT.retry_count shows current attempt number
    # RETRY_RESULT.feedback_file points to .map/<branch>/monitor_feedback_retry{N}.md

    RETRY_STATUS=$(echo "$RETRY_RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))")
    RETRY_COUNT=$(echo "$RETRY_RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('retry_count',0))")

    if RETRY_STATUS == "max_retries":
        # Escalate to user (retry limit reached after 5 attempts)
        AskUserQuestion(questions=[{"question": "Monitor retry limit reached (5 attempts). How to proceed?", "header": "Retry limit", "options": [{"label": "Continue", "description": "Continue with more retries (manually edit step_state.json retry_count)"}, {"label": "Skip", "description": "Skip this subtask and move to next"}, {"label": "Abort", "description": "Stop workflow"}], "multiSelect": false}])

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
# python3 .map/scripts/map_orchestrator.py wave_monitor_failed ST-001 --feedback "feedback text"
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

After ALL subtasks in a wave have Monitor `valid=true`, run build + tests + linter ONCE for the entire wave:

```bash
# 1. BUILD GATE (MANDATORY — run FIRST)
BUILD_EXIT=0
BUILD_OUTPUT=""
if [ -f "tsconfig.json" ]; then
  BUILD_OUTPUT=$(npx tsc --noEmit 2>&1); BUILD_EXIT=$?
elif [ -f "package.json" ] && jq -e '.scripts.build' package.json > /dev/null 2>&1; then
  BUILD_OUTPUT=$(npm run build 2>&1); BUILD_EXIT=$?
elif [ -f "setup.py" ] || [ -f "pyproject.toml" ]; then
  PY_FILES=$(git diff --name-only --diff-filter=AM -- '*.py')
  if [ -n "$PY_FILES" ]; then
    BUILD_OUTPUT=$(echo "$PY_FILES" | xargs python -m py_compile 2>&1); BUILD_EXIT=$?
  fi
elif [ -f "go.mod" ]; then
  BUILD_OUTPUT=$(go build ./... 2>&1); BUILD_EXIT=$?
elif [ -f "Cargo.toml" ]; then
  BUILD_OUTPUT=$(cargo check 2>&1); BUILD_EXIT=$?
fi
echo "$BUILD_OUTPUT"

# If build fails, skip tests/lint — no point running them on code that doesn't compile
if [ "$BUILD_EXIT" -ne 0 ]; then
  echo "BUILD FAILED — fix compilation errors before proceeding"
  TESTS_EXIT=1; LINT_EXIT=1  # Force gate failure
fi

# 2. Run tests — only if build passed
TESTS_EXIT=${TESTS_EXIT:-0}
TEST_OUTPUT=""
if [ "$BUILD_EXIT" -eq 0 ] && { [ -f "pytest.ini" ] || [ -f "setup.py" ] || [ -f "pyproject.toml" ]; }; then
  TEST_OUTPUT=$(pytest 2>&1); TESTS_EXIT=$?
elif [ "$BUILD_EXIT" -eq 0 ] && [ -f "package.json" ]; then
  TEST_OUTPUT=$(npm test 2>&1); TESTS_EXIT=$?
elif [ "$BUILD_EXIT" -eq 0 ] && [ -f "go.mod" ]; then
  TEST_OUTPUT=$(go test ./... 2>&1); TESTS_EXIT=$?
elif [ "$BUILD_EXIT" -eq 0 ] && [ -f "Cargo.toml" ]; then
  TEST_OUTPUT=$(cargo test 2>&1); TESTS_EXIT=$?
elif [ "$BUILD_EXIT" -eq 0 ]; then
  echo "No tests found, skipping test gate"
fi
echo "$TEST_OUTPUT"

# 3. Run linter — only if build passed
LINT_EXIT=${LINT_EXIT:-0}
LINT_OUTPUT=""
if [ "$BUILD_EXIT" -eq 0 ] && command -v ruff &> /dev/null; then
  LINT_OUTPUT=$(ruff check . 2>&1); LINT_EXIT=$?
elif [ "$BUILD_EXIT" -eq 0 ] && command -v eslint &> /dev/null; then
  LINT_OUTPUT=$(eslint . 2>&1); LINT_EXIT=$?
elif [ "$BUILD_EXIT" -eq 0 ] && command -v golangci-lint &> /dev/null; then
  LINT_OUTPUT=$(golangci-lint run 2>&1); LINT_EXIT=$?
elif [ "$BUILD_EXIT" -eq 0 ]; then
  echo "No linter found, skipping lint gate"
fi
echo "$LINT_OUTPUT"
```

**Guard Pattern Decision (per-wave):**

```
IF BUILD_EXIT == 0 AND TESTS_EXIT == 0 AND LINT_EXIT == 0:
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

This also appends a `Prior-Stage Consumption` section that records whether the
closeout consumed the branch spec, task plan, blueprint, test contract, and code
diff. If the workflow needs to enforce the full artifact pipeline before review,
run the explicit gate and fix any reported missing inputs before claiming ready:

```bash
python3 .map/scripts/map_step_runner.py validate_prior_stage_consumption implementation
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

Then write the deferred learning handoff so `LEARN` remains part of the philosophy without paying Reflector cost inline:

```bash
python3 .map/scripts/map_step_runner.py write_learning_handoff \
  map-efficient \
  "<task title>" \
  "READY FOR REVIEW" \
  "Run /map-review next, or defer /map-learn until you want to preserve patterns" \
  "<optional implementation note>"
```

This writes `.map/<branch>/learning-handoff.md` and `.json`, updates `artifact_manifest.json`, and lets `/map-learn` auto-load the workflow context later.

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

After the final workflow decision is known, write the run health report with the matching terminal status:

```bash
# Set from the final decision above: complete, pending, blocked, won't_do, or superseded.
RUN_HEALTH_STATUS="${RUN_HEALTH_STATUS:?set RUN_HEALTH_STATUS from the final workflow decision}"
python3 .map/scripts/map_step_runner.py write_run_health_report \
  map-efficient \
  "$RUN_HEALTH_STATUS"
```

Use `complete` only when final verification passed. Use `pending` when more implementation work remains, `blocked` when an external/tooling issue prevents safe completion, `won't_do` when the workflow is intentionally stopped, and `superseded` when another workflow owns it. This writes `.map/<branch>/run_health_report.json`, updates the `run_health` stage in `artifact_manifest.json`, and preserves a machine-readable diagnosis snapshot for `/map-check`, `/map-review`, or `/map-resume`.

## Step 4: Summary

- Update Terminal State in task_plan: **Status:** complete
- Report features implemented, files changed, verification confidence
- `learning-handoff.md` / `.json` should already be written for deferred learning
- **Optional:** Run `/map-learn` now, or batch it later when the workflow is worth preserving

Begin execution now.


## Examples

```
/map-efficient <typical args>
```

## Troubleshooting

- **Issue:** Workflow doesn't behave as expected. **Fix:** Re-read the section above titled 'What this command CANNOT do' (if present) and ensure prerequisites are met. Run `/map-resume` to recover from interruptions.
