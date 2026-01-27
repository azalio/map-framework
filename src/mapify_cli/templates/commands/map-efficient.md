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
4. Max 5 retry iterations per subtask

## Architecture Overview

```text
┌─────────────────────────────────────────────────────────────┐
│  PreToolUse Hook (workflow-context-injector.py)             │
│  Injects: Current step, Progress, Mandatory next action     │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  map-efficient.md (THIS FILE - ~150 lines)                  │
│  1. Load state → Get next step instruction                  │
│  2. Route to appropriate executor based on step phase       │
│  3. Execute step (Actor/Monitor/mem0/tests/etc)             │
│  4. Validate completion → Update state                      │
│  5. If more steps → Recurse; Else → Complete                │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  State Machine (map_orchestrator.py)                        │
│  Determines WHAT step to execute based on current state     │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  Workflow Gate (workflow-gate.py)                           │
│  BLOCKS Edit/Write until actor+monitor completed            │
└─────────────────────────────────────────────────────────────┘
```

**Task:** $ARGUMENTS

## Step 1: Get Next Step Instruction

```bash
# Get next step from state machine
NEXT_STEP=$(python3 scripts/map_orchestrator.py get_next_step)
STEP_ID=$(echo "$NEXT_STEP" | jq -r '.step_id')
PHASE=$(echo "$NEXT_STEP" | jq -r '.phase')
INSTRUCTION=$(echo "$NEXT_STEP" | jq -r '.instruction')
IS_COMPLETE=$(echo "$NEXT_STEP" | jq -r '.is_complete')

# Check if workflow complete
if [ "$IS_COMPLETE" = "true" ]; then
  echo "✅ All subtasks complete. Running final verification..."
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
- Use `blueprint.subtasks[].dependencies` (array of subtask IDs)
- Include `complexity_score` (1-10) and `risk_level` (low|medium|high)
- Include `security_critical` (true for auth/crypto/validation)
- Include `test_strategy` with unit/integration/e2e keys"""
)

# After decomposer returns: extract subtask sequence, save to state
# Update state: python3 scripts/map_orchestrator.py validate_step "1.0"
```

### Phase: INIT_PLAN (1.5)

Generate `.map/task_plan_<branch>.md` from blueprint:
- Header: Goal from blueprint.summary
- For each subtask: ## ST-XXX section with **Status:** pending
- First subtask: **Status:** in_progress
- Terminal State: **Status:** pending

### Phase: INIT_STATE (1.6)

```bash
# Create workflow_state.json
BRANCH=$(git rev-parse --abbrev-ref HEAD | sed 's/\//-/g')
cat > .map/${BRANCH}/workflow_state.json <<'EOF'
{
  "workflow": "map-efficient",
  "started_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "current_subtask": null,
  "current_state": "INITIALIZED",
  "completed_steps": {},
  "pending_steps": {},
  "subtask_sequence": []
}
EOF
```

### Phase: XML_PACKET (2.0)

```python
# Load current subtask from state
subtask = load_current_subtask()

# Build XML packet
xml_packet = create_xml_packet(subtask)

# Save packet to .map/<branch>/current_packet.xml for agent access
```

### Phase: MEM0_SEARCH (2.1)

```bash
# Tiered search: branch → project → org
mcp__mem0__map_tiered_search(
  query="[subtask description]",
  top_k=5,
  user_id="[branch_name]",
  agent_id="map-efficient"
)

# Re-rank by relevance, pass top 3 to Actor
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
Findings file: .map/findings_{branch}.md"""
    )
```

### Phase: ACTOR (2.3)

```python
Task(
  subagent_type="actor",
  description="Implement subtask [ID]",
  prompt=f"""Implement:
**AI Packet (XML):** [paste from .map/<branch>/current_packet.xml]
**Risk Level:** [risk_level]
**Playbook Context:** [top context_patterns from mem0 + relevance_score]

Follow Actor agent protocol output format."""
)
```

### Phase: MONITOR (2.4)

```python
Task(
  subagent_type="monitor",
  description="Validate implementation",
  prompt=f"""Review against requirements:
**AI Packet (XML):** [paste from .map/<branch>/current_packet.xml]
**Proposed Solution:** [paste Actor output]
**Specification Contract:** [SpecificationContract JSON or null]

Check: correctness, security, standards, tests.
If human review required: set `escalation_required` + `escalation_reason`.

Return ONLY valid JSON following MonitorReviewOutput schema.
If validation_criteria present: include contract_compliance + contract_compliant."""
)

# After Monitor returns:
if monitor_output["valid"] == false:
    # Increment retry counter
    if retry_count < 5:
        # Go back to Phase: ACTOR with Monitor feedback
    else:
        # Escalate to user (3-strike protocol)
        AskUserQuestion: CONTINUE / SKIP / ABORT
```

### Phase: PREDICTOR (2.6)

```python
# Conditional: Call if risk_level ∈ {high, medium} OR escalation_required
if requires_predictor(subtask):
    Task(
      subagent_type="predictor",
      description="Analyze impact",
      prompt=f"""Analyze impact using Predictor schema.
**AI Packet (XML):** [paste]
Required inputs: change_description, files_changed, diff_content
Optional: analyzer_output, user_context"""
    )
```

### Phase: APPLY_CHANGES (2.7)

```bash
# GATE CHECK: Monitor.valid === true (enforced by workflow-gate.py hook)
# Apply changes using Edit/Write tools
# Hook will BLOCK if actor+monitor not in completed_steps

# After applying:
python3 scripts/map_step_runner.py update_workflow_state "ST-XXX" "changes_applied" "CHANGES_APPLIED"
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
  - Call mem0 search? [YES/NO per subtask]
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

## Step 2.5: Validate Step Completion

After executing step, validate and update state:

```bash
# Validate step completion
python3 scripts/map_orchestrator.py validate_step "$STEP_ID"

# Update plan status if subtask complete
if [ "$PHASE" = "VERIFY_ADHERENCE" ]; then
  python3 scripts/map_step_runner.py update_plan_status "$SUBTASK_ID" "complete"
fi
```

## Step 2.6: Continue or Complete

```bash
# Get next step
NEXT_STEP=$(python3 scripts/map_orchestrator.py get_next_step)
IS_COMPLETE=$(echo "$NEXT_STEP" | jq -r '.is_complete')

if [ "$IS_COMPLETE" = "true" ]; then
  echo "All subtasks complete. Proceeding to final verification."
  # Go to Step 3
else
  # Recurse: Launch new Task(subagent_type="map-efficient-step") for next step
  # This provides fresh context and prevents token bloat
  echo "Next step: $(echo "$NEXT_STEP" | jq -r '.step_id')"
  # Continue with Step 1 (fresh invocation)
fi
```

## Step 3: Final Verification (Ralph Loop)

### 3.1 Circuit Breaker Check

```bash
# Get circuit breaker status
CB_DATA=$(python3 scripts/map_orchestrator.py check_circuit_breaker)
TOOL_COUNT=$(echo "$CB_DATA" | jq -r '.tool_count')
MAX_ITERATIONS=$(echo "$CB_DATA" | jq -r '.max_iterations')

if [ "$TOOL_COUNT" -ge "$MAX_ITERATIONS" ]; then
  AskUserQuestion: "Circuit breaker triggered. RESET_LIMITS or ABORT?"
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

elif thrashing_detected():
    AskUserQuestion: "Thrashing detected. FORCE_COMPLETE / CONTINUE / ABORT?"

elif plan_iteration < max_redecompositions:
    # Re-decomposition
    Task(subagent_type="task-decomposer", mode="re_decomposition", ...)

else:
    # Max iterations reached
    AskUserQuestion: "Max iterations reached. RESET_LIMITS / ABORT?"
```

## Step 4: Summary

- Update Terminal State in task_plan: **Status:** complete
- Report features implemented, files changed, verification confidence
- **Optional:** Run `/map-learn [summary]` to preserve patterns

Begin execution now.
