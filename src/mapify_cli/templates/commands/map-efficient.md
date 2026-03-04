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
5. Agent phases (ACTOR 2.3, MONITOR 2.4, PREDICTOR 2.6) require evidence files.
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

**Task:** $ARGUMENTS

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

Task: $ARGUMENTS

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
  "subtask_sequence": []
}
```

### Wave Computation (after INIT_STATE)

After INIT_STATE (1.6) completes, compute execution waves from the dependency DAG:

```bash
python3 .map/scripts/map_orchestrator.py set_waves --blueprint .map/${BRANCH}/blueprint.json
```

This reads the blueprint, builds a dependency graph, computes topological waves,
and splits waves by file conflicts. The result is stored in `step_state.json`.

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

### Phase: ACTOR (2.3)

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
    else:
        # Escalate to user (retry limit reached)
        AskUserQuestion(questions=[{"question": "Monitor retry limit reached. How to proceed?", "header": "Retry limit", "options": [{"label": "Continue", "description": "Reset retry counter and try again"}, {"label": "Skip", "description": "Skip this subtask and move to next"}, {"label": "Abort", "description": "Stop workflow"}], "multiSelect": false}])
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
# Run tests if available (do NOT install dependencies)
if [ -f "pytest.ini" ] || [ -f "setup.py" ]; then
  pytest
elif [ -f "package.json" ]; then
  npm test
elif [ -f "go.mod" ]; then
  go test ./...
elif [ -f "Cargo.toml" ]; then
  cargo test
else
  echo "No tests found, skipping gate"
fi
```

### Phase: LINTER_GATE (2.9)

```bash
# Run linter if available
if command -v ruff &> /dev/null; then
  ruff check .
elif command -v eslint &> /dev/null; then
  eslint .
elif command -v golangci-lint &> /dev/null; then
  golangci-lint run
else
  echo "No linter found, skipping gate"
fi
```

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

Question 3: Did I ever write code directly without Actor?
Answer: [YES/NO - if YES, this is a VIOLATION]

Question 4: Did I output CHECKPOINT blocks before agent calls?
Answer: [YES/NO - if NO, add them now]

EVALUATION: [PASSED/FAILED]

If FAILED: DO NOT PROCEED. Go back and complete missing steps.
═══════════════════════════════════════════════════
```

### Phase: SUBTASK_APPROVAL (2.11) — Auto-skipped

Auto-skipped in batch mode (default). The orchestrator proceeds to the next subtask without pausing.

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
