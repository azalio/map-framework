---
description: Resume incomplete MAP workflow from checkpoint
---

# MAP Resume - Workflow Recovery Command

**Purpose:** Resume an interrupted or incomplete MAP workflow from the last checkpoint.

**When to use:**
- After context window exhaustion mid-workflow
- After accidental session termination
- After `/clear` that interrupted a workflow
- When returning to an unfinished task

**What it does:**
1. Detects `.map/progress.md` checkpoint file
2. Displays workflow progress summary
3. Shows completed and remaining subtasks
4. Asks user confirmation before resuming
5. Continues Actor→Monitor loop for remaining subtasks

---

## Step 1: Detect Checkpoint

Check if checkpoint file exists:

```bash
test -f .map/progress.md && echo "Found incomplete workflow" || echo "No checkpoint"
```

**If no checkpoint exists:**

Display message and exit:

```markdown
## No Workflow in Progress

No checkpoint file found at `.map/progress.md`.

**To start a new workflow, use:**
- `/map-efficient "task description"` - Standard implementation workflow
- `/map-debug "issue description"` - Debugging workflow
- `/map-fast "task description"` - Throwaway code workflow

No recovery needed.
```

**Stop here if no checkpoint.**

---

## Step 2: Load and Display Progress

Read checkpoint file and display progress summary:

```bash
cat .map/progress.md
```

Parse the YAML frontmatter and display:

```markdown
## Found Incomplete Workflow

**Task:** [task_plan from frontmatter]
**Current Phase:** [current_phase]
**Turn Count:** [turn_count]
**Started:** [started_at]
**Last Updated:** [updated_at]

### Progress Overview

[X/N] subtasks completed ([percentage]%)

### Completed Subtasks ✅
- [x] **ST-001**: [description] (completed at [timestamp])
- [x] **ST-002**: [description] (completed at [timestamp])
...

### Remaining Subtasks 📋
- [ ] **ST-003**: [description]
- [ ] **ST-004**: [description]
...
```

---

## Step 3: User Confirmation

**⚠️ CRITICAL: Always ask for user confirmation before resuming.**

Ask a simple yes/no question:

```
Resume from last checkpoint? [Y/n]
```

**Handle user response:**

- **Y or y or Enter (default):** Proceed to Step 4 (resume workflow)
- **n or N:** Delete checkpoint file and exit with message "Checkpoint cleared. Start fresh with /map-efficient."

---

## Step 4: Resume Workflow

Load remaining subtasks from checkpoint and continue Actor→Monitor loop.

**Important context loading:**

Before resuming, read:
1. `.map/progress.md` - current state
2. `.map/task_plan_*.md` - full task decomposition with validation criteria

**For each remaining subtask:**

1. **Mark subtask in_progress:**
   - Update `.map/progress.md` with current subtask status

2. **Call Actor:**
   ```
   Task(
     subagent_type="actor",
     description="Implement [subtask_id]: [description]",
     prompt="[Actor prompt with subtask details and validation criteria from task plan]"
   )
   ```

3. **Call Monitor:**
   ```
   Task(
     subagent_type="monitor",
     description="Validate [subtask_id] implementation",
     prompt="[Monitor prompt with Actor output and validation criteria]"
   )
   ```

4. **If Monitor returns `valid: false`:**
   - Retry Actor with feedback (max 5 iterations)
   - Update progress checkpoint after each iteration

5. **If Monitor returns `valid: true`:**
   - Apply changes
   - Mark subtask complete in `.map/progress.md`
   - Continue to next subtask

6. **Update checkpoint after each subtask:**
   - Save updated state to `.map/progress.md`

---

## Step 5: Workflow Completion

After all subtasks complete:

```markdown
## Workflow Resumed and Completed ✅

**Task:** [task_plan]
**Total Subtasks:** [N]
**Subtasks Completed This Session:** [M]
**Total Actor→Monitor Iterations:** [count]

### Completion Summary
[List of all completed subtasks with timestamps]

### Files Modified
[List of files changed during this session]

---

**Optional next steps:**
- Run `/map-learn` to extract and preserve patterns from this workflow
- Run tests to verify implementation
- Create a commit with your changes
```

---

## Error Handling

### Checkpoint File Corrupted

If YAML frontmatter parsing fails:

```markdown
## Checkpoint File Corrupted

The checkpoint file at `.map/progress.md` could not be parsed.

**Options:**
1. View raw file contents and attempt manual recovery
2. Delete checkpoint and start fresh

Would you like me to show the raw checkpoint contents?
```

### Task Plan File Missing

If `.map/task_plan_*.md` referenced in checkpoint doesn't exist:

```markdown
## Task Plan File Missing

The checkpoint references a task plan file that no longer exists.

**Checkpoint:** .map/progress.md
**Expected task plan:** .map/task_plan_[branch].md

**Options:**
1. Create a new task plan based on checkpoint information
2. Clear checkpoint and start fresh workflow
```

### Actor/Monitor Agent Failure

If subagent fails during resume:

1. Save current progress to checkpoint
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
**Current Phase:** implementation
**Turn Count:** 12
**Started:** 2025-01-15T10:30:00
**Last Updated:** 2025-01-15T14:45:00

### Progress Overview
3/5 subtasks completed (60%)

### Completed Subtasks ✅
- [x] **ST-001**: Create User model with SQLite schema
- [x] **ST-002**: Implement password hashing with bcrypt
- [x] **ST-003**: Create login API endpoint

### Remaining Subtasks 📋
- [ ] **ST-004**: Implement JWT token generation
- [ ] **ST-005**: Add logout and token refresh endpoints

Resume from last checkpoint? [Y/n]

User: Y

Claude: Resuming workflow from ST-004...
[Continues Actor→Monitor loop for remaining subtasks]
```

### Example 2: User Abandons Checkpoint

User decides to start fresh:

```
User: /map-resume

Claude: ## Found Incomplete Workflow
[Shows progress summary]

Resume from last checkpoint? [Y/n]

User: n

Claude: Checkpoint cleared. Start fresh with /map-efficient.
```

### Example 3: No Checkpoint

User tries to resume when nothing is in progress:

```
User: /map-resume

Claude: ## No Workflow in Progress

No checkpoint file found at `.map/progress.md`.

To start a new workflow, use:
- `/map-efficient "task description"` - Standard implementation
- `/map-debug "issue description"` - Debugging
- `/map-fast "task description"` - Throwaway code

No recovery needed.
```

---

## Integration with Other Commands

### After `/clear`

If user runs `/clear` during a workflow:
- Checkpoint is preserved in `.map/progress.md`
- User can resume with `/map-resume`
- Fresh context starts from checkpoint state

### With `/map-efficient`

`/map-efficient` automatically saves checkpoints:
- After decomposition phase
- After each subtask completion
- Before each Actor call

`/map-resume` can continue from any of these checkpoints.

### With `/map-learn`

After `/map-resume` completes a workflow:
- User can optionally run `/map-learn`
- Patterns extracted from entire workflow (original + resumed)

---

## Technical Notes

### Checkpoint File Format

The `.map/progress.md` file uses YAML frontmatter:

```yaml
---
task_plan: "Task description"
current_phase: implementation
turn_count: 12
started_at: 2025-01-15T10:30:00
updated_at: 2025-01-15T14:45:00
branch_name: feat/user-auth
completed_subtasks:
  - ST-001
  - ST-002
  - ST-003
subtasks:
  - id: ST-001
    description: Create User model
    status: complete
    completed_at: 2025-01-15T11:00:00
  - id: ST-002
    description: Implement password hashing
    status: complete
    completed_at: 2025-01-15T12:30:00
  - id: ST-004
    description: Implement JWT generation
    status: pending
---

# MAP Workflow Progress
[Human-readable markdown body]
```

### State Restoration

When resuming:
1. Parse YAML frontmatter for machine state
2. Use human-readable body for context summary
3. Load full task plan from referenced file
4. Continue from last incomplete subtask

### Context Efficiency

Resume is designed for context efficiency:
- Only loads necessary state, not full conversation history
- Checkpoint contains enough context to continue
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

**Symptom:** Checkpoint says ST-003 is complete, but code shows incomplete implementation.

**Cause:** Session crashed between code application and checkpoint update.

**Fix:**
1. Manually verify each subtask's actual completion status
2. Update checkpoint to match reality
3. Resume from corrected state

### Issue: Resume loads but doesn't continue

**Symptom:** Progress displayed, user confirms Continue, but nothing happens.

**Cause:** Task plan file missing or invalid.

**Fix:**
1. Check for `.map/task_plan_*.md` file
2. Recreate task plan if missing
3. Ensure validation criteria are present for remaining subtasks

### Issue: Actor context missing after resume

**Symptom:** Actor doesn't understand codebase context after resume.

**Fix:** Resume workflow includes context loading phase:
1. Read recent git diff for changed files
2. Load relevant source files for remaining subtasks
3. Provide context summary in Actor prompt
