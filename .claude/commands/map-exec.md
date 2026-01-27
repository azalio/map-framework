# /map-exec — BUILDER Phase (Single Subtask Execution)

**Purpose:** Execute ONE subtask from the plan created by /map-plan. This command ONLY builds - it does NOT plan or verify full completion.

**When to use:**
- After running /map-plan successfully
- Ready to implement one specific subtask
- Need focused execution context for a single piece of work

**What this command does:**
- Takes subtask ID as argument (e.g., `/map-exec ST-001`)
- Executes the full workflow for that subtask: actor → monitor → apply changes
- Updates `workflow_state.json` with completion status
- **STOPS** after subtask completion (forces context flush)

**What this command CANNOT do:**
- ❌ Plan or decompose tasks (use /map-plan for that)
- ❌ Verify full project completion (use /map-check for that)
- ❌ Execute multiple subtasks in one session

---

## Usage

```bash
/map-exec <subtask_id>
```

**Examples:**
```bash
/map-exec ST-001
/map-exec ST-003
```

---

## Workflow Steps

### Step 0: Validate Preconditions

Before starting, verify:

1. **workflow_state.json exists:**
   ```bash
   BRANCH=$(git rev-parse --abbrev-ref HEAD | sed 's/\//-/g')
   test -f .map/${BRANCH}/workflow_state.json || echo "❌ Run /map-plan first"
   ```

2. **Subtask ID is valid:**
   ```bash
   cat .map/${BRANCH}/workflow_state.json | jq -e '.subtask_sequence[] | select(. == "ST-001")' || echo "❌ Invalid subtask ID"
   ```

3. **Subtask is not blocked:**
   Check task_plan_<branch>.md for dependencies. If subtask depends on others, ensure they're completed first.

If any precondition fails, **STOP** and notify the user.

### Step 1: Load Subtask Context

Read the subtask details from task_plan_<branch>.md:

```bash
BRANCH=$(git rev-parse --abbrev-ref HEAD | sed 's/\//-/g')
cat .map/${BRANCH}/task_plan_${BRANCH}.md
```

Extract:
- Subtask description
- Acceptance criteria
- Dependencies
- Complexity level

### Step 2: Update Workflow State (Start)

Mark subtask as active:

```bash
BRANCH=$(git rev-parse --abbrev-ref HEAD | sed 's/\//-/g')
STATE_FILE=".map/${BRANCH}/workflow_state.json"

# Update using jq
jq --arg st "${SUBTASK_ID}" \
   '.current_subtask = $st | .current_state = "XML_PACKET_CREATED"' \
   "$STATE_FILE" > "${STATE_FILE}.tmp" && mv "${STATE_FILE}.tmp" "$STATE_FILE"
```

### Step 3: Create XML Packet

Generate AI-friendly subtask packet:

```xml
<subtask id="${SUBTASK_ID}">
  <description>${subtask_description}</description>
  <acceptance_criteria>
    ${criteria_from_plan}
  </acceptance_criteria>
  <context>
    <dependencies>${dep_list}</dependencies>
    <complexity>${complexity_level}</complexity>
  </context>
</subtask>
```

Update state:
```bash
jq '.completed_steps["'${SUBTASK_ID}'"] += ["xml_packet"]' "$STATE_FILE" > "${STATE_FILE}.tmp" && mv "${STATE_FILE}.tmp" "$STATE_FILE"
```

### Step 4: Load Context (mem0 Search)

Search for relevant patterns in mem0:

```
ToolSearch("select:mcp__mem0__map_tiered_search")
mcp__mem0__map_tiered_search(
  query="${subtask_description}",
  entity_type="project_pattern",
  min_tier=1,
  max_results=5
)
```

Update state:
```bash
jq '.current_state = "CONTEXT_LOADED" | .completed_steps["'${SUBTASK_ID}'"] += ["mem0_search"]' "$STATE_FILE" > "${STATE_FILE}.tmp" && mv "${STATE_FILE}.tmp" "$STATE_FILE"
```

### Step 5: Research Phase (Conditional)

**If subtask will modify 3+ files OR has high complexity:**

Call research-agent to gather context:

```
Task(
  subagent_type="research-agent",
  description="Research codebase for subtask context",
  prompt=f"""
Analyze the codebase to understand how to implement:

{subtask_description}

Focus on:
- Existing patterns and conventions
- Files that will need modification
- Integration points and dependencies
- Potential risks or conflicts
"""
)
```

Update state:
```bash
jq '.current_state = "RESEARCH_DONE" | .completed_steps["'${SUBTASK_ID}'"] += ["research"]' "$STATE_FILE" > "${STATE_FILE}.tmp" && mv "${STATE_FILE}.tmp" "$STATE_FILE"
```

**If subtask is simple (1-2 files, low complexity):**
Skip research, update state to mark as skipped:
```bash
jq '.pending_steps["'${SUBTASK_ID}'"] |= . - ["research"]' "$STATE_FILE" > "${STATE_FILE}.tmp" && mv "${STATE_FILE}.tmp" "$STATE_FILE"
```

### Step 6: Call Actor

**MANDATORY:** Call actor agent to generate implementation:

```
Task(
  subagent_type="actor",
  description="Generate implementation for ${SUBTASK_ID}",
  prompt=f"""
Implement this subtask:

{xml_packet}

Context from mem0:
{mem0_patterns}

Research findings:
{research_output_if_available}

Generate ONLY the implementation plan. Do NOT edit code.
Output format:
- Files to create/modify
- Code changes with line numbers
- Integration steps
"""
)
```

**CRITICAL:** Actor output must be saved for monitor to review.

Update state:
```bash
jq '.current_state = "ACTOR_CALLED" | .completed_steps["'${SUBTASK_ID}'"] += ["actor"]' "$STATE_FILE" > "${STATE_FILE}.tmp" && mv "${STATE_FILE}.tmp" "$STATE_FILE"
```

### Step 7: Call Monitor

**MANDATORY:** Call monitor agent to validate actor's proposal:

```
Task(
  subagent_type="monitor",
  description="Validate implementation for ${SUBTASK_ID}",
  prompt=f"""
Review this implementation proposal from Actor:

{actor_output}

Check for:
- Correctness (meets acceptance criteria)
- Code quality (follows project standards)
- Security (no vulnerabilities)
- Testability (can be tested)

Output: APPROVED or REJECTED with specific feedback
"""
)
```

**If REJECTED:**
- Return to Step 6 with monitor's feedback
- Update actor prompt with corrections needed
- Re-run actor → monitor loop

**If APPROVED:**
Update state:
```bash
jq '.current_state = "MONITOR_PASSED" | .completed_steps["'${SUBTASK_ID}'"] += ["monitor"]' "$STATE_FILE" > "${STATE_FILE}.tmp" && mv "${STATE_FILE}.tmp" "$STATE_FILE"
```

### Step 8: Apply Changes

**NOW workflow-gate.py will allow Edit/Write** because both "actor" and "monitor" are in completed_steps.

Apply the changes approved by monitor:

```
Edit(file_path=..., old_string=..., new_string=...)
Write(file_path=..., content=...)
```

### Step 9: Run Tests

If project has tests configured:

```bash
# Check ralph-loop-config.json for test command
TEST_CMD=$(jq -r '.test_command // "pytest"' .claude/ralph-loop-config.json)
eval "$TEST_CMD"
```

If tests fail:
- Analyze failure
- Fix issue
- Re-run tests

Update state when passing:
```bash
jq '.current_state = "TESTS_PASSED" | .completed_steps["'${SUBTASK_ID}'"] += ["tests"]' "$STATE_FILE" > "${STATE_FILE}.tmp" && mv "${STATE_FILE}.tmp" "$STATE_FILE"
```

### Step 10: Run Linter

```bash
# Check ralph-loop-config.json for lint command
LINT_CMD=$(jq -r '.lint_command // "make lint"' .claude/ralph-loop-config.json)
eval "$LINT_CMD"
```

If linting fails:
- Fix issues
- Re-run linter

Update state when passing:
```bash
jq '.current_state = "LINTER_PASSED" | .completed_steps["'${SUBTASK_ID}'"] += ["linter"]' "$STATE_FILE" > "${STATE_FILE}.tmp" && mv "${STATE_FILE}.tmp" "$STATE_FILE"
```

### Step 11: Mark Subtask Complete

Update state to mark subtask done:

```bash
jq '.current_state = "SUBTASK_COMPLETE" | .pending_steps["'${SUBTASK_ID}'"] = []' "$STATE_FILE" > "${STATE_FILE}.tmp" && mv "${STATE_FILE}.tmp" "$STATE_FILE"
```

### Step 12: Output Checkpoint

Print a clear checkpoint showing subtask completion:

```
═══════════════════════════════════════════════════
WORKFLOW CHECKPOINT: ${SUBTASK_ID} COMPLETE
═══════════════════════════════════════════════════
✅ Actor generated implementation
✅ Monitor validated changes
✅ Code applied successfully
✅ Tests passed
✅ Linter passed

Completed Steps: [xml_packet, mem0_search, actor, monitor, tests, linter]

Next Steps:
1. Check remaining subtasks:
   cat .map/${BRANCH}/task_plan_${BRANCH}.md

2. Execute next subtask:
   /map-exec ST-002

3. After all subtasks complete:
   /map-check
═══════════════════════════════════════════════════
```

### Step 13: STOP

**This phase ends here.** Do NOT proceed to next subtask or verification. The context should be flushed, and the next subtask execution will start fresh.

---

## Design Rationale

**Why execute one subtask at a time?**

1. **Context Focus:** Each subtask gets full attention without distraction from other work.

2. **Clean State:** Starting fresh for each subtask prevents context pollution from previous work.

3. **Incremental Progress:** Clear completion signals after each subtask provide psychological checkpoints.

4. **Error Isolation:** If something fails, impact is limited to current subtask.

---

## Enforcement Mechanisms

**workflow-gate.py Hook:**
- Blocks Edit/Write until "actor" and "monitor" are in completed_steps[${SUBTASK_ID}]
- Ensures you cannot skip required agents
- Fail-open: allows work if workflow_state.json missing (non-MAP workflows)

**Ralph Circuit Breaker:**
- Prevents infinite loops during implementation
- Tracks edit attempts and blocks after threshold
- Requires explicit reset if thrashing detected

---

## Related Commands

- **/map-plan** - Create task decomposition (must run first)
- **/map-check** - Verify all subtasks complete (run after all /map-exec calls)
- **/map-efficient** - Monolithic workflow (all phases in one command)

---

## Example Usage

```bash
# After running /map-plan which created 3 subtasks:

# Execute first subtask
User: "/map-exec ST-001"
# Result: JWT library added, tests pass, linter clean

# Execute second subtask
User: "/map-exec ST-002"
# Result: Token service implemented, validated by monitor

# Execute third subtask
User: "/map-exec ST-003"
# Result: Middleware added, integration complete

# Verify full completion
User: "/map-check"
```

---

## Troubleshooting

**Q: workflow-gate.py blocked my Edit call?**
A: You skipped actor or monitor. Check workflow_state.json to see completed_steps for current subtask.

**Q: Can I execute multiple subtasks in one session?**
A: No. This violates the phase isolation principle. Complete one, flush context, then start next.

**Q: Subtask depends on ST-001 but it's not complete yet?**
A: Execute dependencies first. Check task_plan_<branch>.md for dependency graph.

**Q: Tests are failing but weren't before?**
A: Previous subtask may have introduced regression. Use `git diff` to review recent changes.

---

## Success Criteria

This command succeeds when:
- ✅ Actor and Monitor both called for subtask
- ✅ Monitor approved implementation
- ✅ Code changes applied successfully
- ✅ Tests passed (if configured)
- ✅ Linter passed (if configured)
- ✅ workflow_state.json shows SUBTASK_COMPLETE
- ✅ CHECKPOINT printed with completion summary
- ✅ You STOPPED (did not proceed to next subtask)
