---
description: Minimal workflow for throwaway code (40-50% savings, NO learning)
---

# MAP Fast Workflow

**⚠️ WARNING: For throwaway prototypes only - use /map-efficient for production**

Minimal agent sequence (40-50% token savings). Skips: Predictor, Evaluator, Reflector, Curator.

**Consequences:** No impact analysis, no quality scoring, no learning, playbook never improves.

Implement the following:

**Task:** $ARGUMENTS

## Workflow Overview

Minimal agent sequence (token-optimized, quality-compromised):

```
1. DECOMPOSE → task-decomposer
2. FOR each subtask:
   3. IMPLEMENT → actor
   4. VALIDATE → monitor
   5. If invalid: provide feedback, go to step 3 (max 3 iterations)
   6. ACCEPT and apply changes
```

**Agents INTENTIONALLY SKIPPED:**
- Predictor (no impact analysis)
- Evaluator (no quality scoring)
- Reflector (no lesson extraction)
- Curator (no playbook updates)

**⚠️ CRITICAL:** This is NOT the full MAP workflow. You are bypassing the learning cycle.

## Step 1: Task Decomposition

Break down the task into subtasks:

```
Task(
  subagent_type="general-purpose",
  description="Decompose task into subtasks",
  prompt="Break down this task into atomic subtasks (≤8):

Task: $ARGUMENTS

Output JSON with:
- subtasks: array of {id, description, acceptance_criteria, estimated_complexity, depends_on}
- total_subtasks: number
- estimated_duration: string

Each subtask must be:
- Atomic (can't be subdivided further)
- Testable (clear acceptance criteria)
- Independent where possible"
)
```

## Step 2: For Each Subtask - Minimal Loop

### 2.1 Call Actor to Implement

```
Task(
  subagent_type="general-purpose",
  description="Implement subtask [ID]",
  prompt="Implement this subtask:

**Subtask:** [description]
**Acceptance Criteria:** [criteria]

Output JSON with:
- approach: string (implementation strategy)
- code_changes: array of {file_path, change_type, content, rationale}
- trade_offs: array of strings
- testing_approach: string

Provide FULL file content for each change, not diffs."
)
```

### 2.2 Call Monitor to Validate

```
Task(
  subagent_type="general-purpose",
  description="Validate implementation",
  prompt="Review this implementation:

**Actor Output:** [paste actor JSON]

Check for:
- Basic code correctness
- Obvious errors
- Test coverage

Output JSON with:
- valid: boolean
- issues: array of {severity, category, description, file_path}
- verdict: 'approved' | 'needs_revision' | 'rejected'
- feedback: string (actionable guidance)"
)
```

### 2.3 Decision Point

**If monitor.valid === false:**
- Provide monitor feedback to actor
- Go back to step 2.1 (max 3 iterations)

**If monitor.valid === true:**
- Apply code changes using Write/Edit tools
- Move to next subtask

## Step 3: Final Summary

After all subtasks completed:

1. Run basic tests (if applicable)
2. Create commit with message
3. Summarize what was implemented

**Note:** No playbook updates, no cipher patterns stored (learning disabled).

## Critical Constraints

- MAX 3 iterations per subtask
- NO learning cycle (Reflector/Curator skipped)
- NO impact analysis (Predictor skipped)
- NO quality scoring (Evaluator skipped)

Begin now with minimal workflow.
