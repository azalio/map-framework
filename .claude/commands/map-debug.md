---
description: Debug issue using MAP analysis
---

# MAP Debugging Workflow

**🚨 ABSOLUTELY FORBIDDEN 🚨**

You are **STRICTLY PROHIBITED** from:

❌ **"Optimizing" the workflow by skipping agents** - Each agent MUST be called
❌ **"Using general-purpose instead of specialized agents"** - USE the correct subagent_type
❌ **"Combining steps to save time"** - Each agent MUST be called individually
❌ **Any variation of "I'll optimize by..."** - NO ADDITIONAL OPTIMIZATION ALLOWED

**YOU MUST:**
✅ Call task-decomposer FIRST (not general-purpose)
✅ Call actor for EACH subtask (not general-purpose)
✅ Call monitor after EACH actor (not general-purpose)
✅ Verify each agent used required MCP tools (check output)

Debug the following issue using the MAP framework:

**Debug Request:** $ARGUMENTS

## Workflow Overview

Debugging workflow focuses on analysis before implementation:

```
1. DECOMPOSE → task-decomposer (break down debugging steps)
2. FOR each debugging step:
   3. IMPLEMENT → actor (create fix)
   4. VALIDATE → monitor (check fix correctness)
   5. PREDICT → predictor (assess impact of fix)
   6. EVALUATE → evaluator (verify fix quality)
   7. Apply fix
3. DONE → Suggest /map-learn if user wants to preserve patterns
```

## Step 1: Analyze the Issue

Before calling task-decomposer, gather context and query playbook:

```bash
# Search for similar debugging patterns
PLAYBOOK_CONTEXT=$(mapify playbook query "debug [issue type]" --limit 5 --section ERROR_PATTERNS --section DEBUGGING_TECHNIQUES)
```

1. **Read error logs/stack traces** (if provided in $ARGUMENTS)
2. **Search cipher for similar issues**: `mcp__cipher__cipher_memory_search("debug pattern [error_type]")`
3. **Identify affected files**: Use Grep/Glob to find relevant code
4. **Reproduce the issue** (if possible): Read test files or run commands

## Step 2: Decompose Debugging Process

```
Task(
  subagent_type="task-decomposer",
  description="Decompose debugging steps",
  prompt="Break down this debugging process into atomic steps:

**Issue:** $ARGUMENTS

**Context:**
- Error logs: [if available]
- Affected files: [from analysis]
- Similar past issues: [from cipher search]

Output JSON with:
- subtasks: array of {id, description, debug_type: 'investigation'|'fix'|'verification', acceptance_criteria}
- root_cause_hypothesis: string
- estimated_complexity: 'low'|'medium'|'high'

Debug types:
- investigation: analyze code, logs, reproduce issue
- fix: implement solution
- verification: test fix, check for regressions"
)
```

## Step 3: For Each Debugging Step

### Investigation Steps

For subtasks with `debug_type: 'investigation'`:

```
Task(
  subagent_type="actor",
  description="Investigate issue",
  prompt="Investigate this debugging step:

**Step:** [description]
**Goal:** [acceptance_criteria]

Perform analysis and provide:
- findings: array of observations
- root_cause: string (if identified)
- next_steps: array of recommended actions
- code_locations: array of {file, line_range, issue_description}

Use Read, Grep tools to analyze code. Do NOT make changes yet."
)
```

### Fix Steps

For subtasks with `debug_type: 'fix'`:

```
Task(
  subagent_type="actor",
  description="Implement fix for [issue]",
  prompt="Implement a fix for this issue:

**Issue:** [from investigation]
**Root Cause:** [identified root cause]

Output JSON with:
- approach: string (fix strategy)
- code_changes: array of {file_path, change_type, content, rationale}
- why_this_fixes_it: string (explain the fix)
- potential_side_effects: array of strings
- testing_approach: string

Provide FULL file content for changes."
)
```

### Monitor Validation

After each fix:

```
Task(
  subagent_type="monitor",
  description="Validate fix",
  prompt="Review this debugging fix:

**Original Issue:** [description]
**Actor Fix:** [paste actor JSON]

Check:
- Does the fix address the root cause?
- Are there any security issues introduced?
- Are there proper error handling?
- Is the fix testable?
- Are there any edge cases missed?

Output JSON with:
- valid: boolean
- issues: array of {severity, category, description}
- verdict: 'approved'|'needs_revision'|'rejected'
- feedback: string"
)
```

### Predictor Impact Analysis

For approved fixes:

```
Task(
  subagent_type="predictor",
  description="Analyze fix impact",
  prompt="Analyze the impact of this debugging fix:

**Fix:** [paste actor JSON]
**Monitor Verdict:** approved

Analyze:
- Could this fix introduce new bugs?
- Are there other places with similar issues?
- Does this require updating tests?
- Are there performance implications?

Output JSON with:
- similar_issues: array of {file, line, description}
- risk_level: 'low'|'medium'|'high'
- recommended_additional_changes: array of strings
- regression_test_requirements: array of strings"
)
```

### Evaluator Quality Check

```
Task(
  subagent_type="evaluator",
  description="Evaluate fix quality",
  prompt="Evaluate this debugging fix:

**Fix:** [paste actor JSON]
**Monitor Verdict:** [verdict]
**Predictor Analysis:** [paste predictor JSON]

Score (0-10):
- correctness: does it fix the issue?
- completeness: are all edge cases covered?
- clarity: is the fix understandable?
- testing: is it properly tested?

Output JSON with:
- scores: object
- overall_score: number
- recommendation: 'proceed'|'improve'|'reject'
- justification: string"
)
```

### Apply Fix

If evaluator recommends proceeding:
- Apply code changes using Write/Edit tools
- Run tests to verify fix
- Check that original issue is resolved

## Step 4: Verification

After all fixes applied:

1. **Run full test suite** to check for regressions
2. **Verify original issue is resolved**
3. **Check predictor's similar_issues** - fix those too if relevant
4. **Create commit** with clear description of fix and root cause

---

## 💡 Optional: Preserve Debugging Lessons

**If you want to save debugging patterns for future use:**

```
/map-learn Debugged [issue description]. Root cause: [cause].
Fix: [summary]. Prevention strategies: [list].
Files changed: [files]. Iterations: [count].
```

This is **completely optional**. Run it when debugging patterns are valuable for future reference.

## MCP Tools for Debugging

- `mcp__cipher__cipher_memory_search` - Find similar past debugging sessions
- `mcp__sequential-thinking__sequentialthinking` - Complex root cause analysis
- `mcp__context7__get-library-docs` - Check library documentation for known issues
- `mcp__deepwiki__ask_question` - Learn from how others solved similar issues

## Critical Constraints

- **ALWAYS identify root cause** before implementing fixes
- **NEVER skip testing** after applying fixes
- **ALWAYS check for similar issues** in other parts of codebase
- **Use Task tool** to call all subagents

## Example

User says: `/map-debug TypeError in authentication middleware`

You should:
1. Gather context (read error logs, find middleware file)
2. Search cipher for similar authentication errors
3. Task(subagent_type="task-decomposer") → get investigation + fix steps
4. For investigation steps: Task(subagent_type="actor") to analyze
5. For fix steps: actor → monitor → predictor → evaluator → apply
6. Run tests, verify fix
7. Done! Optionally run `/map-learn` to preserve debugging patterns

Begin debugging now.
