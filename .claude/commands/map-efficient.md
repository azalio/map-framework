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
6. Agent phases (ACTOR 2.3, MONITOR 2.4, PREDICTOR 2.6) require evidence files.
   Each agent writes `.map/<branch>/evidence/<phase>_<subtask_id>.json` after completing work.
   `validate_step` rejects the step if evidence is missing or malformed.

## Intentional Agent Omissions

/map-efficient does NOT use these agents (by design):
- **Evaluator** — quality scoring not needed; Monitor validates correctness directly
- **Reflector** — lesson extraction is a separate step via `/map-learn`

This is NOT a violation of MAP agent rules. Learning is decoupled into `/map-learn` (optional, run after workflow completes) to reduce token usage during execution.

## Dual State Files

/map-efficient uses two state files in `.map/<branch>/`:
- **`step_state.json`** — Orchestrator canonical state. Tracks current step, retry counts, circuit breaker. Written/read by `map_orchestrator.py`. This is the source of truth for workflow resumption.
- **`workflow_state.json`** — Enforcement gates. Tracks subtask completion for `workflow-gate.py` hook validation. Written by `map_step_runner.py`.

Both files must stay in sync. The orchestrator updates `step_state.json` on every step; `workflow_state.json` is updated at phase boundaries (INIT_STATE, UPDATE_STATE).

## Human-Readable Workflow Artifacts

In addition to machine-readable state/evidence, maintain these branch-scoped markdown artifacts in `.map/<branch>/`:

- `devlog-001.md` — implementation trail and notable changes across subtasks
- `session-log.md` — chronological workflow journal for the current branch/session
- `code-review-001.md`, `code-review-002.md`, ... — Monitor verdicts and required fixes per execution review iteration
- `qa-001.md` — final verification and command results in human-readable form
- `pr-draft.md` — evolving PR summary, updated as execution finishes

These files are the cook-inspired handoff layer. Keep them concise and update them during the workflow instead of deferring to a separate command.

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

Before continuing execution, ensure the branch workspace contains `session-log.md`, `devlog-001.md`, `qa-001.md`, and `pr-draft.md` by running:

```bash
python3 .map/scripts/map_step_runner.py ensure_human_artifacts
```

Create numbered execution review artifacts deterministically with:

```bash
python3 .map/scripts/map_step_runner.py next_numbered_artifact_path code-review
```

Use `session-log.md` as the high-level journal:
- append one entry when a subtask starts
- append one entry after Actor completes
- append one entry after Monitor verdict
- append one entry before final verification

Each entry should include timestamp, subtask ID, phase, outcome, and pointers to related artifacts (`code-review-XXX.md`, `devlog-001.md`, `qa-001.md`, evidence files).

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

Then use the **Write** tool to create `.map/<branch>/workflow_state.json`:

```json
{
  "workflow": "map-efficient",
  "started_at": "<current UTC timestamp in ISO 8601>",
  "current_subtask": null,
  "current_state": "INITIALIZED",
  "completed_steps": {},
  "pending_steps": {},
  "subtask_sequence": [],
  "constraints": null
}
```

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
      build XML_PACKET, run CONTEXT_SEARCH, optional RESEARCH

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
    #   Re-run actor + monitor for that subtask (serially)
    #   Track retries per subtask: validate_wave_step SUBTASK_ID STEP_ID

    # Phase E: Per-wave gates
    # Run tests + linter ONCE for the entire wave
    # pytest / npm test / etc.

    # Phase F: Advance wave
    python3 .map/scripts/map_orchestrator.py advance_wave

    # Update workflow state for all subtasks in batch:
    python3 .map/scripts/map_step_runner.py update_workflow_state_batch '[
      {"subtask_id": "ST-002", "step_name": "actor", "new_state": "ACTOR_CALLED"},
      {"subtask_id": "ST-002", "step_name": "monitor", "new_state": "MONITOR_PASSED"},
      {"subtask_id": "ST-004", "step_name": "actor", "new_state": "ACTOR_CALLED"},
      {"subtask_id": "ST-004", "step_name": "monitor", "new_state": "MONITOR_PASSED"}
    ]'
```

Linear DAGs naturally degrade to single-subtask waves (identical to current behavior).

### Phase: XML_PACKET (2.0)

```python
# Load current subtask from state
subtask = load_current_subtask()

# Build versioned, scoped XML packet with semantic brackets
# Format: <MAP_Packet subtask="ST-XXX" v="1.0" risk="low|medium|high">
xml_packet = create_xml_packet(subtask)

# Save packet to .map/<branch>/current_packet.xml for agent access
# Packet boundaries are unambiguous — agents parse by tag, not by heuristics
```

### Phase: RESEARCH (2.2)

```python
# Conditional: Call if refactoring OR touching 3+ files
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

<MAP_Packet subtask="[ID]" v="1.0" risk="[risk_level]">
[paste from .map/<branch>/current_packet.xml]
</MAP_Packet>

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

Write evidence: .map/<branch>/evidence/test_writer_<subtask_id>.json"""
)
```

### Phase: TEST_FAIL_GATE (2.26) — TDD Mode Only

Auto-skipped when TDD mode is disabled. When active:

**First:** lint-check test files (ACTOR cannot fix them later):
```bash
# Lint ONLY the test files from TEST_WRITER evidence
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

Write evidence: `.map/<branch>/evidence/test_fail_gate_<subtask_id>.json`

### Phase: ACTOR (2.3)

When TDD mode is active, Actor receives `<TDD_Mode>code_only</TDD_Mode>` and must NOT modify test files. When TDD is off, standard behavior.

```python
Task(
  subagent_type="actor",
  description="Implement subtask [ID]",
  prompt=f"""Implement and APPLY CODE with Edit/Write tools.

<MAP_Packet subtask="[ID]" v="1.0" risk="[risk_level]">
[paste from .map/<branch>/current_packet.xml]
</MAP_Packet>

<MAP_Contract>
[AAG contract from decomposition: Actor -> Action -> Goal]
</MAP_Contract>

Protocol (execute in order):
1. Parse MAP_Packet — extract scope, affected_files, validation_criteria
2. Parse MAP_Contract — this is your compilation target
3. Read affected files to understand current state
4. Implement: translate MAP_Contract into code (no reasoning about WHAT, only HOW)
5. Apply code with Edit/Write tools
6. Output: approach + files_changed + trade-offs"""
)
```

**CRITICAL: After Actor returns, do NOT debug or fix issues yourself.**
- If Actor reports diagnostics/errors — proceed directly to MONITOR.
- LSP diagnostics shown after Actor may be stale (IDE lag). Do NOT read files or attempt manual fixes.

After Actor finishes, update `.map/<branch>/devlog-001.md` with:
- subtask ID
- files changed
- implementation approach
- unresolved concerns handed to Monitor

Also append a short entry to `.map/<branch>/session-log.md` via:

```bash
python3 .map/scripts/map_step_runner.py append_session_log ACTOR implemented <subtask_id> "files changed + approach" "devlog-001.md,.map/<branch>/evidence/actor_<subtask_id>.json"
```
- Monitor will verify compilation (`go build`, `pytest`, etc.) and report real issues.
- If Monitor returns `valid=false`, retry via Actor (not manual edits).

### Phase: MONITOR (2.4)

```python
Task(
  subagent_type="monitor",
  description="Validate written code",
  prompt=f"""Validate WRITTEN CODE (Actor already applied with Edit/Write).

<MAP_Packet subtask="[ID]" v="1.0" risk="[risk_level]">
[paste from .map/<branch>/current_packet.xml]
</MAP_Packet>

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

# After Monitor returns:
if monitor_output["valid"] == false:
    # Increment retry counter
    if retry_count < 5:
        # Go back to Phase: ACTOR with Monitor feedback
        # Actor will fix issues and re-apply code

        # === STUCK RECOVERY (at retry 3) ===
        # At retry 3, intercept with intermediate recovery before retries 4-5.
        # This gives Actor better context to break out of a stuck loop.
        if retry_count == 3:
            # Step 1: Check if research-agent already ran for this subtask
            findings_file = f".map/{branch}/findings_{branch}.md"
            if findings_file exists and has content for this subtask:
                # Reuse existing findings (Edge Case 12: skip re-invocation)
                recovery_context = read(findings_file)
            else:
                # Invoke research-agent for alternative approaches
                Task(
                    subagent_type="research-agent",
                    description="Stuck recovery: find alternative approach",
                    prompt=f"""Subtask {subtask_id} failed 3 monitor retries.
Monitor feedback: {latest_monitor_feedback}
Find an ALTERNATIVE approach. Current approach is not working.
Focus on: different patterns, simpler implementations, existing utilities."""
                )
                recovery_context = research_agent_output

            # Step 2: Invoke predictor (skip for low-risk subtasks — Edge Case 7)
            if subtask.risk_level != "low":
                Task(
                    subagent_type="predictor",
                    description="Stuck recovery: analyze why approach fails",
                    prompt=f"""Subtask {subtask_id} failed 3 retries.
Research findings: {recovery_context}
Analyze: why is the current approach failing? What dependencies are missed?"""
                )
                recovery_context += predictor_output

            # Step 3: Pass recovery context to Actor for retries 4-5
            # Actor receives: original task + monitor feedback + recovery context
            # This gives Actor a fresh perspective from research-agent/predictor

            # If both research-agent and predictor found nothing useful:
            if recovery_context is empty or unhelpful:
                AskUserQuestion(questions=[{"question": "Stuck recovery: research-agent and predictor found no alternative. How to proceed?", "header": "Stuck", "options": [{"label": "Continue", "description": "Try 2 more retries with current approach"}, {"label": "Skip", "description": "Skip subtask, move to next"}, {"label": "Abort", "description": "Stop workflow"}], "multiSelect": false}])
        # === END STUCK RECOVERY ===

    else:
        # Escalate to user (retry limit reached after 5 attempts)
        AskUserQuestion(questions=[{"question": "Monitor retry limit reached (5 attempts). How to proceed?", "header": "Retry limit", "options": [{"label": "Continue", "description": "Reset retry counter and try again"}, {"label": "Skip", "description": "Skip this subtask and move to next"}, {"label": "Abort", "description": "Stop workflow"}], "multiSelect": false}])
```

### Phase: PREDICTOR (2.6)

```python
# Enhanced predictor decision:
# 1. ALWAYS call for: high risk, security_critical, or escalation_required
# 2. SKIP if: risk_level == "low"
# 3. SKIP if: risk_level == "medium" AND all affected_files are new (don't exist yet)
#    AND complexity_score <= 4 AND NOT security_critical
#    → Write minimal evidence directly via Write tool
# 4. OTHERWISE: Call predictor with tier_hint

skip_predictor = (
    not subtask.escalation_required
    and not subtask.security_critical
    and (
        subtask.risk_level == "low"
        or (
            subtask.risk_level == "medium"
            and subtask.affected_files  # guard against vacuous all()
            and all(not file_exists(f) for f in subtask.affected_files)
            and subtask.complexity_score <= 4
        )
    )
)

if skip_predictor:
    # Write minimal evidence directly (no agent call needed)
    # Use Write tool → <project_root>/.map/<branch>/evidence/predictor_<subtask_id>.json
    {
      "phase": "PREDICTOR",
      "subtask_id": "<id>",
      "timestamp": "<ISO 8601 UTC>",
      "risk_assessment": "low",
      "confidence_score": 0.95,
      "tier_selected": "skipped",
      "skip_reason": "New files only, no existing callers, complexity <= 4"
    }
else:
    # Determine tier_hint from subtask metadata:
    # - risk "medium" + complexity_score <= 3 → tier_hint: 1
    # - risk "medium" + complexity_score 4-7 → tier_hint: 2
    # - risk "high" OR security_critical → tier_hint: 3
    if subtask.risk_level == "high" or subtask.security_critical:
        tier_hint = 3
    elif subtask.complexity_score <= 3:
        tier_hint = 1
    else:
        tier_hint = 2

    Task(
      subagent_type="predictor",
      description="Analyze impact",
      prompt=f"""Analyze impact using Predictor schema.

tier_hint: {tier_hint}

<MAP_Packet subtask="[ID]" v="1.0" risk="[risk_level]">
[paste from .map/<branch>/current_packet.xml]
</MAP_Packet>

Required inputs: change_description, files_changed, diff_content
Optional: analyzer_output, user_context"""
    )
```

### Phase: UPDATE_STATE (2.7)

```bash
# Code already applied by Actor, validated by Monitor
# Update workflow state to mark subtask progress

python3 .map/scripts/map_step_runner.py update_workflow_state "ST-XXX" "validated" "VALIDATED"
python3 .map/scripts/map_step_runner.py update_plan_status "ST-XXX" "in_progress"
```

### Phase: TESTS_GATE (2.8)

```bash
# Run tests if available (do NOT install dependencies). Capture exit code + output for guard pattern.
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
# Print output so it's visible in the conversation
echo "$TEST_OUTPUT"
```

### Phase: LINTER_GATE (2.9)

```bash
# Run linter if available. Capture exit code + output for guard pattern.
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

### Phase: GUARD_DECISION (2.95)

**Guard Pattern Decision Table** — applies after TESTS_GATE and LINTER_GATE.

Guard rework counter (`guard_rework`) is **independent** of monitor retry counter.

```
IF monitor_output["valid"] == true:
  IF TESTS_EXIT == 0 AND LINT_EXIT == 0:
    → KEEP: Proceed to VERIFY_ADHERENCE (all green)

  ELSE (monitor pass + guard fail = regression detected):
    guard_rework += 1
    IF guard_rework <= 2:
      → RETRY Actor with guard failure context:
        - Pass: test/lint stderr output
        - Pass: "Monitor approved your changes but tests/linter failed (regression)"
        - Pass: "Fix the regression without breaking the new behavior"
        - After Actor retry → re-run Monitor → re-run TESTS_GATE + LINTER_GATE
    ELSE (guard_rework > 2):
      → ESCALATE to user:
        AskUserQuestion("Guard failure after 2 rework attempts. Tests/linter still failing.")
        Options: ["Skip this subtask", "Abort workflow"]

ELSE (monitor_output["valid"] == false):
  → Standard monitor retry logic (existing behavior, max 5 retries)
```

**Key invariant:** Guard rework never modifies test files — Actor must adapt implementation to pass existing tests.

### Phase: VERIFY_ADHERENCE (2.10)

Output self-audit checkpoint:

```text
═══════════════════════════════════════════════════
WORKFLOW ADHERENCE SELF-AUDIT
═══════════════════════════════════════════════════

Question 1: Did I call task-decomposer for decomposition?
Answer: [YES/NO - if NO, explain why not]

Question 2: For EACH subtask, did I:
  - Create XML packet? [YES/NO per subtask]
  - Call research-agent if 3+ files? [YES/NO/N/A per subtask]
  - Call Actor agent? [YES/NO per subtask]
  - Call Monitor agent after Actor? [YES/NO per subtask]
  - Call Predictor if medium/high risk? [YES/NO/N/A per subtask]
  - Run tests gate? [YES/NO per subtask]
  - Run linter gate? [YES/NO per subtask]
Answer: [List each subtask and answers]

Question 3: (TDD mode only) For EACH subtask, did I:
  - Call TEST_WRITER before Actor? [YES/NO/N/A per subtask]
  - Verify tests failed at TEST_FAIL_GATE? [YES/NO/N/A per subtask]
  - Use code_only mode for Actor (no test modifications)? [YES/NO/N/A]
Answer: [List answers, or N/A if TDD mode is not active]

Question 4: Did I ever write code directly without Actor?
Answer: [YES/NO - if YES, this is a VIOLATION]

Question 5: Did I output CHECKPOINT blocks before agent calls?
Answer: [YES/NO - if NO, add them now]

EVALUATION: [PASSED/FAILED]

If FAILED: DO NOT PROCEED. Go back and complete missing steps.
═══════════════════════════════════════════════════
```

### Phase: SUBTASK_APPROVAL (2.11) — Auto-skipped

Auto-skipped in batch mode (default). The orchestrator proceeds to the next subtask without pausing.

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

After writing the execution review artifact, append a matching summary line with `append_session_log` so someone resuming the branch can scan the review history without opening every file.

## Step 2a: Validate Step Completion

After executing step, validate and update state:

```bash
# Validate step completion
python3 .map/scripts/map_orchestrator.py validate_step "$STEP_ID"

# Update plan status if subtask complete
if [ "$PHASE" = "VERIFY_ADHERENCE" ]; then
  python3 .map/scripts/map_step_runner.py update_plan_status "$SUBTASK_ID" "complete"
fi
```

If `PHASE=VERIFY_ADHERENCE` succeeds, also append to `.map/<branch>/devlog-001.md`:
- subtask completed
- verification summary
- tests/lint run for that subtask

## Step 2b: Continue or Complete (Context Distillation)

```bash
# Get next step
NEXT_STEP=$(python3 .map/scripts/map_orchestrator.py get_next_step)
IS_COMPLETE=$(echo "$NEXT_STEP" | jq -r '.is_complete')

if [ "$IS_COMPLETE" = "true" ]; then
  echo "All subtasks complete. Proceeding to final verification."
  # Go to Step 3
else
  # CONTEXT DISTILLATION before recurse:
  # Do NOT pass full RESEARCH logs or Actor/Monitor transcripts.
  # Pass ONLY the distilled state to keep new context in SFT comfort zone (~4k tokens):
  #
  # 1. findings.md       — distilled research output (not raw search logs)
  # 2. workflow_state.json — current progress + completed subtask IDs
  # 3. task_plan.md       — plan with updated statuses
  # 4. aag_contract       — one-line contract for NEXT subtask only
  # 5. session-log.md / latest code-review-XXX.md / devlog-001.md — human-readable loop history
  #
  # The fresh invocation reads these files — it never inherits conversation history.

  # Recurse: Launch new context with minimal state transfer
  echo "Next step: $(echo "$NEXT_STEP" | jq -r '.step_id')"
  # Continue with Step 1 (loop back to get_next_step, or use /map-resume in a fresh session)
fi
```

Execution mode is always `batch`. The orchestrator auto-skips pause steps (2.11) between subtasks.

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

Finally append a closing entry to `.map/<branch>/session-log.md` that points to `qa-001.md`, `verification-summary.md`, and `pr-draft.md`.

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
