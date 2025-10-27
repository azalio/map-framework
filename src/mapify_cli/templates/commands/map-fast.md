---
description: Fast implementation with minimal agents (NOT RECOMMENDED - use /map-efficient instead)
---

# MAP Fast Workflow

**⚠️ WARNING: NOT RECOMMENDED FOR PRODUCTION CODE ⚠️**

This workflow is **INTENTIONALLY LIMITED** to save tokens (~40-50%) but **SACRIFICES CRITICAL CAPABILITIES**:

❌ **NO Impact Analysis** (Predictor) → Breaking changes undetected
❌ **NO Quality Scoring** (Evaluator) → Security/performance issues missed
❌ **NO Learning** (Reflector/Curator) → Knowledge never accumulates
❌ **NO Playbook Updates** → Same mistakes repeated forever
❌ **NO Cipher Integration** → Cross-project knowledge lost

**🎯 RECOMMENDED ALTERNATIVE: Use `/map-efficient` instead**
- Still saves 30-40% tokens
- Preserves learning and quality gates
- Suitable for production code

**ONLY use /map-fast for:**
- Throwaway prototypes you'll discard
- Quick experiments where quality doesn't matter
- Learning/tutorial contexts where failure is acceptable

---

Implement the following with minimal validation:

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

**⚠️ NO LEARNING STEP:** Unlike full MAP workflow, there is NO Reflector or Curator step here. You are not learning from this implementation.

## Step 3: Final Summary

After all subtasks completed:

1. **Run basic tests** (if applicable)
2. **Create commit** with message
3. **Summarize**:
   - What was implemented
   - Files changed
   - ⚠️ **NO playbook bullets added** (learning disabled)
   - ⚠️ **NO cipher patterns stored** (knowledge lost)

**REMINDER:** You used /map-fast. Consider if you should have used /map-efficient instead to preserve learning.

## Comparison: What You're Missing

| Feature | /map-feature | /map-efficient | /map-fast (YOU) |
|---------|--------------|----------------|-----------------|
| Impact Analysis (Predictor) | ✅ Always | ✅ Conditional | ❌ Never |
| Quality Scoring (Evaluator) | ✅ Always | ❌ Skipped | ❌ Never |
| Learning (Reflector) | ✅ Per-subtask | ✅ Batched | ❌ Never |
| Playbook Updates (Curator) | ✅ Per-subtask | ✅ Batched | ❌ Never |
| Token Savings | 0% | 30-40% | 40-50% |
| **Production Ready** | **✅ Yes** | **✅ Yes** | **❌ NO** |

## Critical Constraints

- **ONLY use for throwaway code** - not production
- **NO learning** means playbook stays empty
- **NO quality gates** means bugs may be missed
- **NO impact analysis** means breaking changes undetected
- **MAX 3 iterations** per subtask
- **Consider using /map-efficient** for better balance

## Example

User says: `/map-fast prototype a simple todo list API`

This is acceptable because:
- It's explicitly a prototype (throwaway)
- Quality/learning not critical for quick exploration
- Token savings matter more than robustness

User says: `/map-fast implement user authentication`

This is **DANGEROUS** because:
- Authentication is security-critical (needs Evaluator)
- Breaking changes affect many files (needs Predictor)
- Common pattern that should be learned (needs Reflector/Curator)
- **Should use /map-efficient instead**

---

**Final Warning:** By using /map-fast, you are consciously accepting:
- Higher risk of bugs and security issues
- No learning or knowledge accumulation
- No quality scoring or impact analysis
- Suitability only for non-critical throwaway code

**If any of these concerns matter to you, use `/map-efficient` instead.**

Begin now with minimal workflow.
