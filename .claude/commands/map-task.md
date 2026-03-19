---
description: Execute a single subtask from an existing plan
---

# /map-task — Single Subtask Execution

**Purpose:** Execute one specific subtask from an existing plan, without running the full workflow.

**When to use:**
- After `/map-plan` has created a decomposition — pick and run one subtask
- When you want fine-grained control over execution order
- When resuming work on a specific subtask after context reset
- When parallelizing subtasks across multiple sessions

**Prerequisites:** A plan must exist (`.map/<branch>/task_plan_<branch>.md`). Run `/map-plan` first if needed.

**Task:** $ARGUMENTS

---

## Step 0: Parse Arguments

Extract the subtask ID from `$ARGUMENTS`:

```bash
SUBTASK_ID=$(echo "$ARGUMENTS" | grep -oE 'ST-[0-9]+' | head -1)
if [ -z "$SUBTASK_ID" ]; then
  echo "ERROR: No subtask ID found. Usage: /map-task ST-001"
  exit 1
fi
```

## Step 1: Initialize Single Subtask

```bash
BRANCH=$(git rev-parse --abbrev-ref HEAD | sed -E 's|/|-|g; s|[^a-zA-Z0-9_.-]|-|g; s|-{2,}|-|g; s|^-||; s|-$||')

# Set up state for single subtask execution
RESULT=$(python3 .map/scripts/map_orchestrator.py resume_single_subtask "$SUBTASK_ID")
STATUS=$(echo "$RESULT" | jq -r '.status')

if [ "$STATUS" = "error" ]; then
  echo "$RESULT" | jq -r '.message'
  exit 1
fi
```

**If error mentions "No plan found":** Run `/map-plan` first to create a decomposition.
**If error mentions "not found in plan":** The output lists available subtask IDs — pick one.

## Step 2: Load Subtask Context

Read the plan to get the subtask's details:

```bash
BRANCH=$(git rev-parse --abbrev-ref HEAD | sed -E 's|/|-|g; s|[^a-zA-Z0-9_.-]|-|g; s|-{2,}|-|g; s|^-||; s|-$||')
# Read: .map/${BRANCH}/task_plan_${BRANCH}.md — find the ### ${SUBTASK_ID} section
# Read: .map/${BRANCH}/blueprint.json — get AAG contract, validation_criteria, dependencies
```

Display a brief summary:

```text
═══════════════════════════════════════════════════
SINGLE SUBTASK EXECUTION
═══════════════════════════════════════════════════
Subtask: ${SUBTASK_ID}
Title: <from plan>
AAG Contract: <from blueprint>
Risk: <from blueprint>
Dependencies: <from blueprint>
═══════════════════════════════════════════════════
```

## Step 3: State Machine Loop

Follow the same state machine loop as `/map-efficient`. Call `get_next_step` and execute based on the returned phase.

```bash
NEXT_STEP=$(python3 .map/scripts/map_orchestrator.py get_next_step)
PHASE=$(echo "$NEXT_STEP" | jq -r '.phase')
```

Route to the appropriate executor based on `$PHASE`. All phases from `/map-efficient` work identically:

- **XML_PACKET (2.0)** — Build XML packet for this subtask
- **CONTEXT_SEARCH (2.1)** — Search for relevant patterns
- **RESEARCH (2.2)** — Call research-agent if needed
- **ACTOR (2.3)** — Implement the subtask
- **MONITOR (2.4)** — Validate implementation
- **PREDICTOR (2.6)** — Impact analysis (conditional)
- **UPDATE_STATE (2.7)** — Mark progress
- **TESTS_GATE (2.8)** — Run tests
- **LINTER_GATE (2.9)** — Run linter
- **VERIFY_ADHERENCE (2.10)** — Self-audit

Single-subtask execution must keep using the shared branch workspace artifacts rather than creating task-local side files:

- `session-log.md`
- `devlog-001.md`
- `code-review-00N.md`
- `qa-001.md`
- `pr-draft.md`

When Monitor runs during `/map-task`, append to the next `code-review-00N.md` so targeted subtask execution stays aligned with the full workflow artifact model.

For each step:
1. Get next step from orchestrator
2. Execute the phase (same handlers as map-efficient)
3. Validate: `python3 .map/scripts/map_orchestrator.py validate_step "$STEP_ID"`
4. Continue to next step until complete

**If Monitor returns `valid: false`:**
- Retry Actor with feedback (max 5 iterations)

## Step 4: Completion and Progress Report

When `get_next_step` returns `is_complete: true`:

1. Update the plan status:
```bash
python3 .map/scripts/map_step_runner.py update_plan_status "${SUBTASK_ID}" "complete"
```

2. Get overall plan progress:
```bash
PROGRESS=$(python3 .map/scripts/map_orchestrator.py get_plan_progress)
TOTAL=$(echo "$PROGRESS" | jq -r '.total')
DONE=$(echo "$PROGRESS" | jq -r '.completed_count')
REMAINING=$(echo "$PROGRESS" | jq -r '.pending_count')
SUGGESTED=$(echo "$PROGRESS" | jq -r '.suggested_next')
```

3. Display completion report with remaining subtasks:

```text
═══════════════════════════════════════════════════
SUBTASK COMPLETE
═══════════════════════════════════════════════════
Subtask: ${SUBTASK_ID}
Title: <title>
Status: COMPLETE

Files Modified:
  - <list of changed files>

───────────────────────────────────────────────────
PLAN PROGRESS: ${DONE}/${TOTAL} subtasks complete
───────────────────────────────────────────────────

Completed:
  ✓ ST-001: <title>
  ✓ ST-002: <title>  ← just completed

Remaining:
  ○ ST-003: <title> (pending)
  ○ ST-004: <title> (pending)

═══════════════════════════════════════════════════
```

4. **Suggest next subtask** using AskUserQuestion:

```
AskUserQuestion(questions=[
  {
    "question": "What would you like to do next?",
    "header": "Next subtask",
    "options": [
      {"label": "/map-task ${SUGGESTED}", "description": "Execute next subtask: <title>"},
      {"label": "/map-tdd ${SUGGESTED}", "description": "TDD for next subtask: <title>"},
      {"label": "Done for now", "description": "Stop here, continue later with /map-task"}
    ],
    "multiSelect": false
  }
])
```

**If all subtasks are complete** (REMAINING == 0), skip the question and show:

```text
═══════════════════════════════════════════════════
ALL SUBTASKS COMPLETE (${TOTAL}/${TOTAL})
═══════════════════════════════════════════════════

Run /map-check for final verification, or /map-learn to extract patterns.
```

---

## Error Handling

### No Plan Exists

```text
No plan found. Run /map-plan first to create a task decomposition,
then use /map-task ST-001 to execute individual subtasks.
```

### Subtask Not in Plan

```text
Subtask ST-999 not found in plan.
Available subtasks: ST-001, ST-002, ST-003
```

### Dependencies Not Met

Check blueprint for dependencies. If the subtask depends on unfinished work, warn:

```text
WARNING: ${SUBTASK_ID} depends on ${DEP_ID} which may not be complete.
Proceed anyway? (The Actor will work with whatever state exists.)
```

---

## Related Commands

- **/map-plan** — Create task decomposition (prerequisite)
- **/map-efficient** — Run full workflow (all subtasks)
- **/map-tdd ST-001** — Write tests for a specific subtask (TDD mode)
- **/map-resume** — Resume interrupted workflow from checkpoint
- **/map-check** — Verify all acceptance criteria
