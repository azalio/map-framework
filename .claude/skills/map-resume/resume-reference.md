# MAP Resume Supporting Reference

This file holds low-frequency examples, integration notes, and troubleshooting details for `/map-resume`. Load it only when the compact resume flow in `SKILL.md` is not enough to recover the workflow.

## Examples

### Example 1: Simple Resume

User returns after session ended mid-workflow:

```text
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

```text
User: /map-resume

Claude: ## Found Incomplete Workflow
[Shows progress summary]

Resume workflow from last checkpoint?

User: Start fresh

Claude: State cleared. Start fresh with /map-efficient.
```

### Example 3: No Checkpoint

User tries to resume when nothing is in progress:

```text
User: /map-resume

Claude: ## No Workflow in Progress

No checkpoint file found at `.map/<branch>/step_state.json`.

To start a new workflow, use:
- `/map-efficient "task description"` - Standard implementation
- `/map-debug "issue description"` - Debugging
- `/map-fast "task description"` - Minimal workflow

No recovery needed.
```

## Integration With Other Commands

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
6. Call `map_orchestrator.py get_next_step` to determine next action
7. Continue phase-based execution from that point

### Context Efficiency

Resume is designed for context efficiency:

- Only loads necessary state files, not full conversation history
- State files contain enough context to continue
- Fresh agent calls don't carry previous context pollution

## Token Budget

Typical `/map-resume` execution:

- Checkpoint detection: ~100 tokens
- Progress display: ~500 tokens
- User confirmation: ~200 tokens
- Per-subtask resume: ~4K tokens (same as normal workflow)

Total overhead for resume: ~1K tokens before continuing workflow.

## Troubleshooting

### Issue: Checkpoint Shows Wrong Subtask Status

**Symptom:** `step_state.json` says ST-003 is complete, but code shows incomplete implementation.

**Cause:** Session crashed between code application and state update.

**Fix:**

1. Manually verify each subtask's actual completion status from the task plan, git diff, and latest review/verification artifacts
2. Do not hand-edit `step_state.json`; direct writes bypass orchestrator validation
3. If the current subtask must be redone, ask the user to confirm restarting that subtask and run `python3 .map/scripts/map_orchestrator.py resume_single_subtask ST-003`
4. Otherwise leave state unchanged and resume from the orchestrator's next step

### Issue: Resume Loads But Does Not Continue

**Symptom:** Progress displayed, user confirms Resume, but nothing happens.

**Cause:** Task plan file missing or invalid.

**Fix:**

1. Check for `.map/<branch>/task_plan_<branch>.md` file
2. Recreate task plan if missing
3. Ensure AAG contracts are present for remaining subtasks

### Issue: Actor Context Missing After Resume

**Symptom:** Actor does not understand codebase context after resume.

**Fix:** Resume workflow includes context loading phase:

1. Read recent git diff for changed files
2. Load relevant source files for remaining subtasks
3. Provide context summary in Actor prompt

### Issue: `step_state.json` Out Of Sync

**Symptom:** `step_state.json` shows ST-003 pending.

**Cause:** Crash between orchestrator update and workflow state update.

**Fix:**

1. Trust `step_state.json` as the canonical source unless repo evidence proves it is stale
2. Do not hand-edit `step_state.json`; direct writes bypass orchestrator validation
3. If one subtask needs to be restarted, ask the user to confirm and run `python3 .map/scripts/map_orchestrator.py resume_single_subtask ST-003`
4. If the whole plan state is unusable, ask the user whether to clear the checkpoint and restart with `/map-efficient`
