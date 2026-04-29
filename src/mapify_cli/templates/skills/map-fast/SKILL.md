---
name: map-fast
description: |
  Minimal MAP workflow for small low-risk changes (40-50% token savings, no Predictor/Reflector). Use when the change is small, low-risk, and learning is not needed. Do NOT use for risky or complex work; use map-efficient.
disable-model-invocation: true
argument-hint: "[task description]"
---
# MAP Fast Workflow

**⚠️ WARNING: Use for small, low-risk production changes only. Do not skip tests.**

Minimal agent sequence (40-50% token savings). Skips: Predictor, Reflector.

**Consequences:** No impact analysis, no quality scoring, no learning.

Implement the following:

**Task:** $ARGUMENTS

## Workflow Overview

Minimal agent sequence (token-optimized, reduced analysis depth):

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
- Reflector (no lesson extraction)

**⚠️ CRITICAL:** This is NOT the full MAP workflow. Learning and impact analysis are disabled.

## Step 1: Task Decomposition

Break down the task into subtasks:

```
Task(
  subagent_type="task-decomposer",
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
  subagent_type="actor",
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
  subagent_type="monitor",
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

**Note:** Learning disabled (Reflector skipped).

## Critical Constraints

- MAX 3 iterations per subtask
- NO learning cycle (Reflector skipped)
- NO impact analysis (Predictor skipped)
- NO quality scoring

Begin now with minimal workflow.


## Examples

```
/map-fast <typical args>
```

## Troubleshooting

- **Issue:** Workflow doesn't behave as expected. **Fix:** Re-read the section above titled 'What this command CANNOT do' (if present) and ensure prerequisites are met. Run `/map-resume` to recover from interruptions.
