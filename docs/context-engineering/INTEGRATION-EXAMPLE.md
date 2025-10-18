# Recitation Pattern Integration Example

This document shows a complete example of how Recitation Pattern is integrated into the MAP workflow.

## Overview

The Recitation Pattern keeps goals "fresh" in context by updating `.map/current_plan.md` before each subtask. This markdown is then injected into the Actor's context window.

## Workflow Diagram

```
User: /map-feature add JWT authentication
    ↓
Orchestrator (.claude/commands/map-feature.md)
    ↓
1. TaskDecomposer → subtasks JSON
    ↓
2. RecitationManager.create_plan()
    → .map/current_plan.md created
    → .map/current_plan.json saved
    ↓
FOR EACH subtask:
    ↓
3. RecitationManager.update_subtask_status(id, 'in_progress')
    → .map/current_plan.md updated with → marker
    ↓
4. plan_context = RecitationManager.get_current_context()
    → Read .map/current_plan.md
    ↓
5. Actor invoked with:
    - subtask_description (from TaskDecomposer)
    - playbook_bullets (from ACE)
    - plan_context (from RecitationManager) ← NEW!
    ↓
6. Actor sees in its context:
    <recitation_plan>
    ## Current Task Plan
    # Current Task: feat_auth
    ## Progress: 2/5 completed
    - [✓] 1/5: Create User model
    - [→] 2/5: Implement login (CURRENT, Iteration 1)
    - [☐] 3/5: Add JWT generation
    ...
    </recitation_plan>
    ↓
7. Monitor validates Actor output
    ↓
8a. If approved:
    RecitationManager.update_subtask_status(id, 'completed')
    → .map/current_plan.md updated with ✓ marker
    ↓
8b. If rejected:
    RecitationManager.update_subtask_status(id, 'in_progress', error='...')
    → .map/current_plan.md updated with error info
    → Iteration count incremented
    → Go back to step 4 (Actor sees updated plan with errors)
    ↓
9. Next subtask (repeat from step 3)
```

## Code Flow

### Step 1: User Invokes /map-feature

```bash
/map-feature add user authentication with JWT tokens
```

### Step 2: Orchestrator Calls TaskDecomposer

The `/map-feature` command (orchestrator) calls TaskDecomposer:

```python
Task(
  subagent_type="task-decomposer",
  prompt="Break down this feature into atomic subtasks (≤8):

Feature: add user authentication with JWT tokens

Output JSON with:
- subtasks: array of {id, description, acceptance_criteria, ...}
- total_subtasks: number
..."
)
```

**TaskDecomposer Output:**
```json
{
  "subtasks": [
    {
      "id": 1,
      "description": "Create User model with password hashing",
      "acceptance_criteria": "Model validates email, hashes password with bcrypt",
      "estimated_complexity": "low",
      "depends_on": []
    },
    {
      "id": 2,
      "description": "Implement login endpoint",
      "acceptance_criteria": "POST /auth/login returns JWT token",
      "estimated_complexity": "medium",
      "depends_on": [1]
    },
    {
      "id": 3,
      "description": "Add JWT token generation",
      "acceptance_criteria": "Tokens expire after 1h, use HS256",
      "estimated_complexity": "low",
      "depends_on": [2]
    }
  ],
  "total_subtasks": 3
}
```

### Step 3: Initialize RecitationManager

Orchestrator creates the plan:

```python
from pathlib import Path
from mapify_cli.recitation_manager import RecitationManager

manager = RecitationManager(Path.cwd())

plan = manager.create_plan(
    task_id='feat_auth_20251018_143022',
    goal='add user authentication with JWT tokens',
    subtasks=decomposer_output['subtasks']
)
```

**Result:** `.map/current_plan.md` is created:

```markdown
# Current Task: feat_auth_20251018_143022

## Overall Goal
add user authentication with JWT tokens

## Progress: 0/3 subtasks completed

## Subtasks
- [☐] 1/3: Create User model with password hashing
- [☐] 2/3: Implement login endpoint
- [☐] 3/3: Add JWT token generation

## Current Focus
**Subtask 1:** Create User model with password hashing

**Acceptance Criteria:**
Model validates email, hashes password with bcrypt

**Complexity:** low

---
_Updated: 2025-10-18 14:30:22_

**Note:** This plan keeps goals fresh in context (Recitation pattern).
Review before each subtask.
```

### Step 4: For Each Subtask - Actor Loop

#### Subtask 1: Create User Model

**Before Actor call:**

```python
# Update status to in_progress
manager.update_subtask_status(1, 'in_progress')

# Get fresh context
plan_context = manager.get_current_context()
# plan_context now contains the updated markdown with → marker for subtask 1
```

**Updated `.map/current_plan.md`:**
```markdown
...
## Subtasks
- [→] **1/3: Create User model with password hashing** (CURRENT)
  - Iterations: 1
- [☐] 2/3: Implement login endpoint
- [☐] 3/3: Add JWT token generation

## Current Focus
**Subtask 1:** Create User model with password hashing
...
```

**Actor invocation:**

```python
Task(
  subagent_type="actor",
  description="Implement subtask 1",
  prompt=f"""Implement this subtask:

**Subtask:** Create User model with password hashing
**Acceptance Criteria:** Model validates email, hashes password with bcrypt

**Relevant Playbook Context:**
[playbook bullets about password hashing, validation, etc.]

## CURRENT TASK PLAN (Review before starting - Recitation Pattern)
{plan_context}

This plan keeps you focused on the overall goal and current progress.
Pay attention to:
- What's already completed (✓)
- Your current subtask (→)
- Iteration count (if retry)
- Previous errors (learn from them)

Output JSON with:
- approach: string
- code_changes: array
- trade_offs: array
- testing_approach: string
- used_bullets: array
"""
)
```

**Actor's View:**

The Actor sees:
1. Task description: "Create User model..."
2. Acceptance criteria
3. Playbook bullets (ACE patterns)
4. **Current plan showing it's on subtask 1/3** ← Recitation
5. Output format requirements

**Actor Output:**
```json
{
  "approach": "Create User model using SQLAlchemy with bcrypt password hashing...",
  "code_changes": [
    {
      "file_path": "models/user.py",
      "change_type": "create",
      "content": "...",
      "rationale": "..."
    }
  ],
  "trade_offs": ["bcrypt is slower but more secure..."],
  "testing_approach": "Test email validation, password hashing, uniqueness...",
  "used_bullets": ["sec-0012", "db-0034"]
}
```

**Monitor validates → Approved → Apply changes**

```python
# Mark as completed
manager.update_subtask_status(1, 'completed')
```

**Updated `.map/current_plan.md`:**
```markdown
...
## Progress: 1/3 subtasks completed

## Subtasks
- [✓] 1/3: Create User model with password hashing
- [☐] 2/3: Implement login endpoint
- [☐] 3/3: Add JWT token generation
...
```

#### Subtask 2: Implement Login (with retry)

**First Attempt:**

```python
manager.update_subtask_status(2, 'in_progress')
plan_context = manager.get_current_context()
```

Actor sees:
```markdown
## Progress: 1/3 subtasks completed

## Subtasks
- [✓] 1/3: Create User model with password hashing
- [→] **2/3: Implement login endpoint** (CURRENT)
  - Iterations: 1
- [☐] 3/3: Add JWT token generation

## Current Focus
**Subtask 2:** Implement login endpoint
...
```

Actor implements, Monitor **rejects** with feedback: "Missing JWT import"

**Retry:**

```python
manager.update_subtask_status(
    2,
    'in_progress',
    error='Missing JWT import'
)
plan_context = manager.get_current_context()
```

**Updated plan for retry:**
```markdown
## Subtasks
- [✓] 1/3: Create User model with password hashing
- [→] **2/3: Implement login endpoint** (CURRENT)
  - Iterations: 2
  - Last error: Missing JWT import
- [☐] 3/3: Add JWT token generation

## Current Focus
**Subtask 2:** Implement login endpoint

**Acceptance Criteria:**
POST /auth/login returns JWT token

**Complexity:** medium

⚠️ **Retry attempt 2** - carefully review previous errors
```

Actor now sees:
- Iteration count: 2
- Previous error: "Missing JWT import"
- Warning to review errors

**Second attempt succeeds → approved → applied**

```python
manager.update_subtask_status(2, 'completed')
```

### Step 5: Final Summary

After all subtasks completed:

```python
stats = manager.get_statistics()
# {
#   'total_subtasks': 3,
#   'completed': 3,
#   'in_progress': 0,
#   'failed': 0,
#   'pending': 0,
#   'total_iterations': 4,  # 1 + 2 + 1
#   'current_subtask': None,
#   'created_at': '2025-10-18T14:30:00',
#   'updated_at': '2025-10-18T14:45:30'
# }

print(f"""
Feature implemented successfully!

Summary:
- Total subtasks: {stats['total_subtasks']}
- Iterations needed: {stats['total_iterations']}
- Avg iterations/subtask: {stats['total_iterations'] / stats['total_subtasks']:.1f}
- Time taken: {time_delta}
""")

# Clean up
manager.clear_plan()
# Removes .map/current_plan.md and .map/current_plan.json
```

## Key Benefits Demonstrated

1. **Context Continuity**: Actor always knows what subtask it's on and what's been completed
2. **Error Learning**: Retry attempts show previous errors, preventing repeated mistakes
3. **Progress Tracking**: User and system can see real-time progress
4. **Minimal Overhead**: ~100 tokens added to context, but saves 500-1000 tokens from avoided retries

## File Locations

- **Plan Files**: `.map/current_plan.md` (human-readable), `.map/current_plan.json` (machine-readable)
- **RecitationManager**: `src/mapify_cli/recitation_manager.py`
- **Actor Template**: `.claude/agents/actor.md` with `<recitation_plan>` section
- **Orchestrator**: `.claude/commands/map-feature.md` with RecitationManager calls
- **Documentation**: `docs/RECITATION-PATTERN.md`

## Testing

See `tests/test_recitation_manager.py` for 37 comprehensive tests covering:
- Plan creation and updates
- Status transitions
- Error tracking
- Markdown generation
- Statistics API
- Edge cases

## Next Steps

- [ ] Add checkpoint integration (Phase 2)
- [ ] Create web UI for plan visualization
- [ ] Add estimated time remaining
- [ ] Parallel subtask tracking
