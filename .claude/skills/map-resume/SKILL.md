---
name: map-resume
description: |
  Resume an interrupted MAP workflow from .map/<branch>/step_state.json checkpoint. Use when returning after context exhaustion, /clear, or a session crash mid-workflow. Do NOT use to start new work; use map-plan or map-efficient.
effort: low
disable-model-invocation: true
argument-hint: "[plan ID]"
---
# MAP Resume - Workflow Recovery Command

**Purpose:** Resume an interrupted or incomplete MAP workflow from the last checkpoint.

## Effort and Parallelism Policy

```yaml
thinking_policy: low/direct
parallel_tool_policy: sequential_state_machine
```

- Minimize fresh reasoning: trust the persisted briefing, step state, and next-action artifact trail unless they are missing or contradictory.
- Do not re-plan, re-decompose, or broaden the task during resume. The goal is to continue the existing workflow from the next valid state-machine step.
- Keep state-machine operations sequential. Parallelize only independent artifact reads used to prepare the resume briefing.

## When Not To Expand Scope

- Do not start unrelated work from a resume session.
- Do not re-run planning or decomposition unless the persisted artifacts are missing or contradictory.
- Do not add extra validation beyond the resumed workflow's next required gate until the current checkpoint is complete.

**When to use:**
- After context window exhaustion mid-workflow
- After accidental session termination
- After `/clear` that interrupted a workflow
- When returning to an unfinished task

**What it does:**
1. Detects `.map/<branch>/step_state.json` checkpoint (orchestrator canonical state)
2. Cross-references `.map/<branch>/step_state.json` for subtask completion
3. Displays workflow progress summary
4. Shows completed and remaining subtasks
5. Asks user confirmation before resuming
6. Continues from the last incomplete step via the state machine

**State files used:**
- **`step_state.json`** — Single source of truth. Tracks current step, retry counts, circuit breaker, subtask completion, and enforcement gates. Includes `tdd_mode` field (persisted across sessions).
- **`task_plan_<branch>.md`** — Full task decomposition with validation criteria and AAG contracts.

**TDD mode note:** If the interrupted workflow was using `/map-tdd` or `--tdd` flag, `tdd_mode: true` is preserved in `step_state.json`.

---

## Step 1: Detect Checkpoint

Check if state files exist for the current branch:

```bash
BRANCH=$(git rev-parse --abbrev-ref HEAD | sed -E 's|/|-|g; s|[^a-zA-Z0-9_.-]|-|g; s|-{2,}|-|g; s|^-||; s|-$||')
test -f ".map/${BRANCH}/step_state.json" && echo "Found incomplete workflow" || echo "No checkpoint"
```

**If no checkpoint exists:**

Display message and exit:

```markdown
## No Workflow in Progress

No checkpoint file found at `.map/<branch>/step_state.json`.

**To start a new workflow, use:**
- `/map-efficient "task description"` - Standard implementation workflow
- `/map-debug "issue description"` - Debugging workflow
- `/map-fast "task description"` - Minimal workflow

No recovery needed.
```

**Stop here if no checkpoint.**

---

## Step 2: Load and Display Progress

Read both state files, the task plan, and branch artifacts to display a briefing:

```bash
BRANCH=$(git rev-parse --abbrev-ref HEAD | sed -E 's|/|-|g; s|[^a-zA-Z0-9_.-]|-|g; s|-{2,}|-|g; s|^-||; s|-$||')

# Read state files using the Read tool
# .map/${BRANCH}/step_state.json — orchestrator state + enforcement gates
# .map/${BRANCH}/task_plan_${BRANCH}.md — full plan with AAG contracts
```

Also query orchestrator plan progress for the canonical progress payload:

```bash
PROGRESS=$(python3 .map/scripts/map_orchestrator.py get_plan_progress)
BRIEF=$(python3 .map/scripts/map_orchestrator.py build_resume_briefing)
```

Parse the state and display:

```markdown
## Found Incomplete Workflow

**Task:** [goal from task_plan]
**Branch:** ${BRANCH}
**Current Step:** [current_step from step_state.json]
**Current Phase:** [phase name from step_state.json]
**Started:** [started_at from step_state.json]

### Resume Briefing

- **Suggested next subtask:** [from `PROGRESS.suggested_next`]
- **Latest verification verdict:** [from `BRIEF.resume_briefing.latest_verification_verdict` or "none"]
- **Latest review artifact:** [from `BRIEF.resume_briefing.latest_review_path` or "none"]
- **Immediate next action:** [first item from `BRIEF.next_action[]` if present, else "resume current step"]

### Requested Fixes / Follow-ups

- [items from `BRIEF.resume_briefing.suggested_fixes[]`, if any]

### Recent Session Context

```text
[latest code-review excerpt excerpt]
```

### Progress Overview

[X/N] subtasks completed ([percentage]%)

### Completed Subtasks
- [x] **ST-001**: [description] (complete)
- [x] **ST-002**: [description] (complete)
...

### Remaining Subtasks
- [ ] **ST-003**: [description] — currently at phase: [phase]
- [ ] **ST-004**: [description] — pending
...
```

---

## Step 3: User Confirmation

Ask for user confirmation before resuming because this can continue a prior edit workflow.

```
AskUserQuestion(questions=[
  {
    "question": "Resume workflow from last checkpoint?",
    "header": "Resume",
    "options": [
      {"label": "Resume (recommended)", "description": "Continue from last checkpoint step"},
      {"label": "Start fresh", "description": "Delete state files and start over with /map-efficient"},
      {"label": "Abort", "description": "Do nothing, keep state files intact"}
    ],
    "multiSelect": false
  }
])
```

**Handle user response:**

- **Resume:** Proceed to Step 4 (resume workflow)
- **Start fresh:** Delete `step_state.json`, exit with "State cleared. Start fresh with /map-efficient."
- **Abort:** Exit without changes

---

## Step 4: Resume Workflow

Use the orchestrator to determine the next step and continue execution.

**Important context loading:**

Before resuming, read:
1. `.map/<branch>/step_state.json` — orchestrator state + enforcement gates
2. `.map/<branch>/task_plan_<branch>.md` — full task decomposition with AAG contracts
4. `python3 .map/scripts/map_orchestrator.py get_plan_progress` — canonical plan + briefing payload
5. `.map/<branch>/code-review-XXX.md` / `.map/<branch>/verification-summary.md` — extra detail if needed

**Resume via orchestrator:**

```bash
BRANCH=$(git rev-parse --abbrev-ref HEAD | sed -E 's|/|-|g; s|[^a-zA-Z0-9_.-]|-|g; s|-{2,}|-|g; s|^-||; s|-$||')

# Get next step from orchestrator (reads step_state.json internally)
NEXT_STEP=$(python3 .map/scripts/map_orchestrator.py get_next_step)
STEP_ID=$(echo "$NEXT_STEP" | jq -r '.step_id')
PHASE=$(echo "$NEXT_STEP" | jq -r '.phase')
IS_COMPLETE=$(echo "$NEXT_STEP" | jq -r '.is_complete')
```

**Then follow the same phase routing as /map-efficient:**


**For each remaining subtask:**

1. **Review the briefing first** to see latest verdict, fixes, and next action
2. **Get next step** from orchestrator
3. **Execute phase** (Actor → Monitor → Predictor → etc.)
4. **Validate step** via `map_orchestrator.py validate_step`
5. **Update state** automatically via orchestrator
6. **Continue** to next step until workflow complete

Resume should prioritize the explicit next action from the briefing. Do not improvise a new plan if the artifact trail already indicates the required fix or next subtask.

If the briefing reports `retry_isolation=clean_retry_required`, run `python3 .map/scripts/map_step_runner.py validate_retry_quarantine` and resume the Actor attempt from `.map/<branch>/retry_quarantine.json`. Do not rehydrate the raw failed context or repeat the rejected approach unless the quarantine artifact explicitly preserves it.

**If Monitor returns `valid: false`:**
- Retry Actor with feedback (max 5 iterations, tracked in step_state.json)
- State is saved after each iteration

**If Monitor returns `valid: true`:**
- Changes already applied by Actor
- Continue to next phase

---

## Step 5: Workflow Completion

After all subtasks complete:

```markdown
## Workflow Resumed and Completed

**Task:** [task from plan]
**Branch:** ${BRANCH}
**Total Subtasks:** [N]
**Subtasks Completed This Session:** [M]

### Completion Summary
[List of all completed subtasks]

### Files Modified
[List of files changed during this session]

---

**Optional next steps:**
- Run `/map-learn` to extract and preserve patterns from this workflow
- Run `/map-check` to verify all acceptance criteria
- Run tests to verify implementation
- Create a commit with your changes
```

---

## Error Handling

### State File Corrupted

If `step_state.json` parsing fails:

```markdown
## State File Corrupted

The state file at `.map/<branch>/step_state.json` could not be parsed.

**Options:**
1. View raw file contents and attempt manual recovery
2. Delete state files and start fresh

Would you like me to show the raw state contents?
```

### Task Plan File Missing

If `.map/<branch>/task_plan_<branch>.md` doesn't exist but state files do:

```markdown
## Task Plan File Missing

State files exist but the task plan is missing.

**State:** .map/<branch>/step_state.json
**Expected plan:** .map/<branch>/task_plan_<branch>.md

**Options:**
1. Create a new task plan based on state information
2. Clear state files and start fresh workflow
```

### Actor/Monitor Agent Failure

If subagent fails during resume:

1. State is preserved in step_state.json (orchestrator saves after each step)
2. Display error message with last successful state
3. Suggest retry or escalation to user

---

## Supporting Reference

The compact resume flow above is the only required context for normal recovery. If recovery is ambiguous, load [resume-reference.md](resume-reference.md) for detailed examples, integration notes, state-file shape, token-budget notes, and troubleshooting.

## Examples

See [resume-reference.md#examples](resume-reference.md#examples) when you need example transcripts for simple resume, start-fresh, or no-checkpoint outcomes.

## Troubleshooting

See [resume-reference.md#troubleshooting](resume-reference.md#troubleshooting) for low-frequency recovery cases such as checkpoint/status drift, missing task plans, missing Actor context, or out-of-sync `step_state.json`.
