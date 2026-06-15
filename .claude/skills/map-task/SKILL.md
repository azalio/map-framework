---
name: map-task
description: |
  Execute a single subtask from an existing MAP plan via Actor and Monitor. Use when map-plan has decomposed work and you want fine-grained control over one subtask. Do NOT use without an existing plan; run map-plan first.
effort: medium
disable-model-invocation: true
argument-hint: "[subtask id]"
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

## Effort and Parallelism Policy

```yaml
thinking_policy: medium/adaptive
parallel_tool_policy: single_subtask_sequential
```

- Reason just enough to execute the selected subtask against its stored contract; avoid re-planning unrelated subtasks.
- Follow the shared `/map-efficient` state-machine phases for the one subtask, including persisted TDD contracts when present.
- Do not parallelize Actor, Monitor, test-gate, or state updates for the same subtask. Parallelize only independent context reads before the next state-machine command.

## When Not To Expand Scope

- Do not execute adjacent subtasks just because they are nearby in the plan.
- Do not re-plan the selected subtask unless its stored contract is missing or contradictory.
- Do not add Predictor, Evaluator, or learning work unless the shared state machine requires it for this subtask.

## Mutation Boundary Constraints

These constraints apply to the selected subtask's write-capable phases:

- Do not edit unrelated files, even if they are nearby or easy to clean up.
- Do not add, remove, or upgrade dependencies unless the selected subtask contract explicitly names that dependency change.
- Do not refactor neighboring code unless the selected subtask's validation criteria cannot pass without that exact refactor.
- If a dependency change, broad refactor, or scope expansion seems necessary, report it as a blocker/tradeoff and stop for a contract update instead of doing it silently.

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

# If a persisted TDD contract exists, resume implementation from ACTOR.
# Otherwise start normal single-subtask execution from RESEARCH.
if [ -f ".map/${BRANCH}/test_handoff_${SUBTASK_ID}.json" ] && [ -f ".map/${BRANCH}/test_contract_${SUBTASK_ID}.md" ]; then
  RESULT=$(python3 .map/scripts/map_orchestrator.py resume_from_test_contract "$SUBTASK_ID")
else
  RESULT=$(python3 .map/scripts/map_orchestrator.py resume_single_subtask "$SUBTASK_ID")
fi
STATUS=$(echo "$RESULT" | jq -r '.status')

if [ "$STATUS" = "error" ]; then
  echo "$RESULT" | jq -r '.message'
  exit 1
fi
```

**If error mentions "No plan found":** Run `/map-plan` first to create a decomposition.
**If error mentions "not found in plan":** The output lists available subtask IDs — pick one.
**If persisted TDD artifacts exist:** `/map-task` resumes at `ACTOR` using `test_contract_<subtask>.md` + `test_handoff_<subtask>.json` instead of restarting research.

## Step 2: Load Subtask Context

Read the plan to get the subtask's details:

```bash
BRANCH=$(git rev-parse --abbrev-ref HEAD | sed -E 's|/|-|g; s|[^a-zA-Z0-9_.-]|-|g; s|-{2,}|-|g; s|^-||; s|-$||')
# Read: .map/${BRANCH}/task_plan_${BRANCH}.md — find the ### ${SUBTASK_ID} section
# Read: .map/${BRANCH}/blueprint.json — get AAG contract, validation_criteria, dependencies
# If present, also read:
# - .map/${BRANCH}/test_contract_${SUBTASK_ID}.md
# - .map/${BRANCH}/test_handoff_${SUBTASK_ID}.json
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

- **RESEARCH (2.2)** — Required persisted research artifact; research-agent is conditional for broad/high-risk discovery.
- **ACTOR (2.3)** — Implement the subtask
- **MONITOR (2.4)** — Required validation before the subtask can complete.

Single-subtask execution must keep using the shared branch workspace artifacts in `.map/<branch>/`
(e.g. `code-review-00N.md`, `qa-001.md`, `pr-draft.md`) rather than creating task-local side files.
When Monitor runs during `/map-task`, append to the next `code-review-00N.md` so targeted subtask
execution stays aligned with the full workflow artifact model.

For each step:
1. Get next step from orchestrator
2. Execute the phase (same handlers as map-efficient)
3. **After Monitor valid=true:** run `python3 .map/scripts/map_step_runner.py run_test_gate` — if tests fail, treat as Monitor valid=false and feed test output back to Actor
4. Validate: `python3 .map/scripts/map_orchestrator.py validate_step "$STEP_ID"`
5. Continue to next step until complete

**If Monitor returns `valid: false`:**
- Run `python3 .map/scripts/map_orchestrator.py monitor_failed --feedback "<feedback>"` and retry Actor with feedback (max 5 iterations).
- If the result says `retry_isolation=clean_retry_required`, run `python3 .map/scripts/map_step_runner.py validate_retry_quarantine` and make the next Actor attempt use `.map/<branch>/retry_quarantine.json` as clean-room context instead of rehydrating the rejected approach.

**Termination (do not loop or fake-complete):** if the 5 Actor iterations are exhausted without Monitor `valid: true`, OR the subtask cannot be satisfied within its declared scope (it would require an out-of-scope file, a dependency change, or a contract not in the blueprint), then STOP. Do NOT mark the subtask complete and do NOT expand scope to force a pass. Emit the **BLOCKED** outcome report (Step 4) stating the reason and the exact contract change needed.

## Step 4: Outcome Report

Every `/map-task` run ends with **exactly one** outcome report — **COMPLETE** or **BLOCKED** —
carrying these required fields: `Subtask`, `Status`, `Files Modified`, `Validation` (test/Monitor
result), and (BLOCKED only) `Blocker` + `Needed`. Never end a run without one of these reports.

### Complete Outcome

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

### Blocked Outcome

When the subtask cannot complete within its declared scope (retries exhausted, an out-of-scope
change would be required, or a dependency/contract conflict): do NOT update the plan status to
`complete`. Report the blocker and stop for a contract update:

```text
═══════════════════════════════════════════════════
SUBTASK BLOCKED
═══════════════════════════════════════════════════
Subtask: ${SUBTASK_ID}
Title: <title>
Status: BLOCKED
Files Modified: <list, or "none">
Validation: <Monitor/test result that could not be satisfied>

Blocker: <why it cannot complete in scope — e.g. requires editing <file> not in
         this subtask's affected_files, or a dependency change not in the contract>
Needed:  <the exact contract change to unblock — e.g. add <file> to ST-XXX
         affected_files, or split into a new subtask>
═══════════════════════════════════════════════════
```

Then stop. Suggest `/map-plan` (to amend the decomposition) or ask the user for a contract decision —
do not silently expand scope or mark the subtask complete.

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


## Examples

```
/map-task ST-003          # execute subtask ST-003 from the existing plan
```

If a persisted TDD contract exists for the subtask (`test_contract_ST-003.md` +
`test_handoff_ST-003.json`), `/map-task ST-003` automatically resumes at ACTOR against those tests.

## Troubleshooting

- **Issue:** Workflow doesn't behave as expected. **Fix:** Confirm the **Prerequisites** (a plan must exist) and re-read the **Mutation Boundary Constraints** and **When Not To Expand Scope** sections above. Run `/map-resume` to recover from an interrupted run.
- **Issue:** The subtask can't pass validation within its allowed files. **Fix:** Don't expand scope — emit the **BLOCKED** outcome report (Step 4) and amend the contract via `/map-plan`.
