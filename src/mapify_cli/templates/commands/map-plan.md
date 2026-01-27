# /map-plan — ARCHITECT Phase (Decomposition Only)

**Purpose:** Plan and decompose complex tasks into atomic subtasks. This command ONLY plans - it does NOT execute or verify.

**When to use:**
- Starting a new feature, refactoring, or complex bug fix
- Need to break down work into manageable pieces
- Want to establish clear task boundaries before execution

**What this command does:**
- Calls task-decomposer agent to break down the user's request
- Creates `.map/<branch>/task_plan_<branch>.md` with subtask list
- Initializes `workflow_state.json` with subtask sequence
- **STOPS** after planning (forces context flush)

**What this command CANNOT do:**
- ❌ Execute implementation (use /map-exec for that)
- ❌ Verify completion (use /map-check for that)
- ❌ Edit code directly

---

## Workflow Steps

### Step 1: Understand the Request

Read the user's requirements carefully. If unclear:
- Ask clarifying questions
- Request examples or references
- Confirm scope boundaries

### Step 2: Create Branch Directory

```bash
BRANCH=$(git rev-parse --abbrev-ref HEAD | sed 's/\//-/g')
mkdir -p .map/${BRANCH}
```

### Step 3: Call Task Decomposer

Use the task-decomposer agent to break down the work:

```
Task(
  subagent_type="task-decomposer",
  description="Decompose task into subtasks",
  prompt=f"""
Break down this task into atomic, testable subtasks:

{user_requirements}

Output format:
- Each subtask should be completable in one focused session
- Include acceptance criteria for each
- Identify dependencies between subtasks
- Estimate complexity (low/medium/high)
"""
)
```

### Step 4: Initialize Workflow State

Create `workflow_state.json` with the decomposition results:

```bash
BRANCH=$(git rev-parse --abbrev-ref HEAD | sed 's/\//-/g')
cat > .map/${BRANCH}/workflow_state.json <<'EOF'
{
  "workflow": "map-plan",
  "started_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "current_subtask": null,
  "current_state": "INITIALIZED",
  "completed_steps": {},
  "pending_steps": {},
  "subtask_sequence": ["ST-001", "ST-002", "ST-003"]
}
EOF
```

**IMPORTANT:** Replace the subtask_sequence array with actual IDs from the decomposition.

### Step 5: Create Human-Readable Plan

Write the plan to `.map/<branch>/task_plan_<branch>.md`:

```markdown
# Task Plan: [Brief Title]

**Created:** $(date -u +%Y-%m-%d)
**Branch:** ${BRANCH}
**Workflow:** map-plan

## Overview

[1-2 sentence description of the overall goal]

## Subtasks

### ST-001: [Subtask Title]
- **Complexity:** [low/medium/high]
- **Dependencies:** [none | ST-XXX, ST-YYY]
- **Description:** [What needs to be done]
- **Acceptance Criteria:**
  - [ ] Criterion 1
  - [ ] Criterion 2

### ST-002: [Next Subtask]
...

## Execution Order

1. ST-001 → ST-002 (ST-002 depends on ST-001)
2. ST-003 (can run in parallel)

## Notes

[Any important context, gotchas, or design decisions]
```

### Step 6: Output Checkpoint

Print a clear checkpoint showing the plan is complete:

```
═══════════════════════════════════════════════════
WORKFLOW CHECKPOINT: PLAN PHASE COMPLETE
═══════════════════════════════════════════════════
✅ Task decomposed into N subtasks
✅ workflow_state.json initialized
✅ Plan written to .map/${BRANCH}/task_plan_${BRANCH}.md

Next Steps:
1. Review the plan in task_plan_${BRANCH}.md
2. If approved, execute first subtask:
   /map-exec ST-001

3. After completing all subtasks, verify:
   /map-check

📋 Subtask Sequence: [ST-001, ST-002, ST-003]
═══════════════════════════════════════════════════
```

### Step 7: STOP

**This phase ends here.** Do NOT proceed to execution. The context should be flushed, and the next phase (/map-exec) will start fresh with focused attention on a single subtask.

---

## Design Rationale

**Why separate planning from execution?**

1. **Context Isolation:** Planning requires broad analysis; execution requires deep focus. Mixing them causes attention dilution.

2. **Forced Checkpoint:** By stopping after planning, we ensure the plan is reviewed before execution begins.

3. **Token Efficiency:** Planning context can be large (requirement analysis, codebase exploration). Execution doesn't need this context.

4. **Cognitive Load:** LLMs perform better on single-phase tasks. Multi-phase instructions get semantically compressed.

---

## Related Commands

- **/map-exec <subtask_id>** - Execute a single subtask from the plan
- **/map-check** - Verify all subtasks completed successfully
- **/map-efficient** - Monolithic workflow (all phases in one command)

---

## State Machine Integration

This command transitions workflow_state.json through these states:

```
(none) → INITIALIZED
```

Subsequent /map-exec calls will transition:
```
INITIALIZED → XML_PACKET_CREATED → CONTEXT_LOADED → ... → SUBTASK_COMPLETE
```

Final /map-check will transition:
```
SUBTASK_COMPLETE (all subtasks) → WORKFLOW_COMPLETE
```

---

## Hook Enforcement

workflow-gate.py hook does NOT apply during /map-plan because no Edit/Write operations occur in this phase.

---

## Example Usage

```bash
# User wants to add authentication to their app
User: "Add JWT authentication with refresh tokens"

# You call /map-plan (this command)
# Result:
# - .map/main/task_plan_main.md created with 5 subtasks:
#   ST-001: Add JWT library dependency
#   ST-002: Implement token generation service
#   ST-003: Add middleware for token validation
#   ST-004: Implement refresh token rotation
#   ST-005: Add integration tests

# After planning phase completes, execution begins:
User: "/map-exec ST-001"
```

---

## Troubleshooting

**Q: Task-decomposer created too many subtasks (10+)?**
A: Subtasks are too granular. Ask task-decomposer to group related work into larger chunks (aim for 3-7 subtasks).

**Q: Can I skip /map-plan and go straight to /map-exec?**
A: No. workflow_state.json must exist with subtask_sequence defined. /map-plan creates this.

**Q: User changed requirements after planning?**
A: Re-run /map-plan. It will overwrite task_plan_<branch>.md and reset workflow_state.json.

---

## Success Criteria

This command succeeds when:
- ✅ task_plan_<branch>.md exists and is readable
- ✅ workflow_state.json exists with valid subtask_sequence
- ✅ CHECKPOINT shows subtask count and IDs
- ✅ You STOPPED (did not proceed to execution)
