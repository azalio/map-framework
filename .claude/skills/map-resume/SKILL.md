---
name: map-resume
description: |
  Resume an interrupted MAP workflow from .map/<branch>/step_state.json checkpoint. Use when returning after context exhaustion, /clear, or a session crash mid-workflow. Do NOT use to start new work; use map-plan or map-efficient.
disable-model-invocation: true
argument-hint: "[plan ID]"
---
# MAP Resume - Workflow Recovery Command

**Purpose:** Resume an interrupted or incomplete MAP workflow from the last checkpoint.

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

**CRITICAL: Always ask for user confirmation before resuming.**

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

## Examples

### Example 1: Simple Resume

User returns after session ended mid-workflow:

```
User: /map-resume

Claude: ## Found Incomplete Workflow

**Task:** Implement user authentication with JWT tokens
**Branch:** feat-user-auth
**Current Step:** 2.3
**Current Phase:** ACTOR
**Started:** 2025-01-15T10:30:00Z

### Progress Overview
3/5 subtasks completed (60%)

### Completed Subtasks
- [x] **ST-001**: Create User model with SQLite schema
- [x] **ST-002**: Implement password hashing with bcrypt
- [x] **ST-003**: Create login API endpoint

### Remaining Subtasks
- [ ] **ST-004**: Implement JWT token generation — currently at phase: ACTOR
- [ ] **ST-005**: Add logout and token refresh endpoints — pending

Resume workflow from last checkpoint?

User: Resume

Claude: Resuming workflow from ST-004 (phase: ACTOR)...
[Continues state machine execution for remaining subtasks]
```

### Example 2: User Starts Fresh

User decides to abandon current progress:

```
User: /map-resume

Claude: ## Found Incomplete Workflow
[Shows progress summary]

Resume workflow from last checkpoint?

User: Start fresh

Claude: State cleared. Start fresh with /map-efficient.
```

### Example 3: No Checkpoint

User tries to resume when nothing is in progress:

```
User: /map-resume

Claude: ## No Workflow in Progress

No checkpoint file found at `.map/feat-auth/step_state.json`.

To start a new workflow, use:
- `/map-efficient "task description"` - Standard implementation
- `/map-debug "issue description"` - Debugging
- `/map-fast "task description"` - Minimal workflow

No recovery needed.
```

---

## Integration with Other Commands

### After `/clear`

If user runs `/clear` during a workflow:
- State is preserved in `.map/<branch>/step_state.json`
- User can resume with `/map-resume`
- Fresh context starts from checkpoint state

### With `/map-efficient`

`/map-efficient` uses `map_orchestrator.py` which maintains `step_state.json`:
- State is updated after each step validation
- `/map-resume` reads this state to determine where to continue

### With `/map-learn`

After `/map-resume` completes a workflow:
- User can optionally run `/map-learn`
- Patterns extracted from entire workflow (original + resumed)

---

## Technical Notes

### State File Format

The `.map/<branch>/step_state.json` is managed by `map_orchestrator.py`:

```json
{
  "current_step": "2.3",
  "current_subtask": "ST-004",
  "subtask_sequence": ["ST-001", "ST-002", "ST-003", "ST-004", "ST-005"],
  "completed_subtasks": ["ST-001", "ST-002", "ST-003"],
  "retry_count": 0,
  "max_retries": 5,
  "execution_mode": "step_by_step",
  "plan_approved": true,
  "circuit_breaker": {
    "tool_count": 42,
    "max_iterations": 200
  }
}
```

The `.map/<branch>/step_state.json` tracks enforcement gates:

```json
{
  "workflow": "map-efficient",
  "started_at": "2025-01-15T10:30:00Z",
  "current_subtask": "ST-004",
  "current_state": "IN_PROGRESS",
  "completed_steps": ["1.0", "1.5", "1.55", "1.56", "1.6", "2.2", "2.3", "2.4"],
  "pending_steps": ["2.2", "2.3", "2.4"],
  "subtask_sequence": ["ST-001", "ST-002", "ST-003", "ST-004", "ST-005"]
}
```

### State Restoration

When resuming:
1. Read `step_state.json` for orchestrator position (current step + subtask)
2. Read `step_state.json` for completed/pending subtask list
3. Read `task_plan_<branch>.md` for AAG contracts and validation criteria
4. Read `code-review-XXX.md` for latest human-readable iteration history before resuming
5. If present, read `verification-summary.md` to understand the latest final verdict or remaining issues
4. Call `map_orchestrator.py get_next_step` to determine next action
5. Continue phase-based execution from that point

### Context Efficiency

Resume is designed for context efficiency:
- Only loads necessary state files, not full conversation history
- State files contain enough context to continue
- Fresh agent calls don't carry previous context pollution

---

## Token Budget

**Typical /map-resume execution:**
- Checkpoint detection: ~100 tokens
- Progress display: ~500 tokens
- User confirmation: ~200 tokens
- Per-subtask resume: ~4K tokens (same as normal workflow)

**Total overhead for resume:** ~1K tokens before continuing workflow.

---

## Troubleshooting

### Issue: Checkpoint shows wrong subtask status

**Symptom:** step_state.json says ST-003 is complete, but code shows incomplete implementation.

**Cause:** Session crashed between code application and state update.

**Fix:**
1. Manually verify each subtask's actual completion status
2. Update step_state.json to match reality
3. Resume from corrected state

### Issue: Resume loads but doesn't continue

**Symptom:** Progress displayed, user confirms Resume, but nothing happens.

**Cause:** Task plan file missing or invalid.

**Fix:**
1. Check for `.map/<branch>/task_plan_<branch>.md` file
2. Recreate task plan if missing
3. Ensure AAG contracts are present for remaining subtasks

### Issue: Actor context missing after resume

**Symptom:** Actor doesn't understand codebase context after resume.

**Fix:** Resume workflow includes context loading phase:
1. Read recent git diff for changed files
2. Load relevant source files for remaining subtasks
3. Provide context summary in Actor prompt

### Issue: step_state.json out of sync

**Symptom:** step_state.json shows ST-003 pending.

**Cause:** Crash between orchestrator update and workflow state update.

**Fix:**
1. Trust `step_state.json` as the canonical source
2. Update `step_state.json` to match
3. Resume from corrected state
