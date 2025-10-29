---
description: Refactor code with MAP impact analysis
---

# MAP Refactoring Workflow

**🚨 ABSOLUTELY FORBIDDEN 🚨**

You are **STRICTLY PROHIBITED** from:

❌ **"Optimizing" the workflow due to token limits** - Token constraints are NOT a valid reason to skip agents
❌ **"Combining steps to save time"** - Each agent MUST be called individually
❌ **"Doing Reflector/Curator work manually"** - This breaks cipher integration
❌ **"Creating a comprehensive document instead"** - This is NOT the MAP workflow
❌ **"Skipping reflection for simple tasks"** - EVERY subtask requires Reflector + Curator
❌ **Any variation of "I'll optimize by..."** - NO OPTIMIZATION ALLOWED

**IF YOU VIOLATE THESE RULES:**
- cipher_memory_search won't be called → duplicate knowledge
- cipher_extract_and_operate_memory won't be called → knowledge won't be shared
- The ENTIRE PURPOSE of MAP Framework will be defeated

**YOU MUST:**
✅ Call EVERY agent in sequence for EVERY subtask
✅ Verify each agent used required MCP tools (check output)
✅ Complete the FULL workflow even if it takes 100K+ tokens
✅ Ask user to continue if you hit token limit, but NEVER skip agents

Refactor the following code using the MAP framework with comprehensive impact analysis:

**Refactor Request:** $ARGUMENTS

## Workflow Overview

Refactoring requires careful analysis to ensure no behavioral changes:

```
1. PREDICT → predictor (analyze all dependencies FIRST)
2. DECOMPOSE → task-decomposer (break into refactoring steps)
3. FOR each refactoring step:
   4. IMPLEMENT → actor (refactor code)
   5. VALIDATE → monitor (ensure no logic changes)
   6. PREDICT → predictor (verify no breaking changes)
   7. EVALUATE → evaluator (check quality improvement)
   8. Apply changes and test
```

## Step 1: Initial Impact Analysis (Critical!)

**Query playbook for refactoring patterns:**

```bash
# Search for refactoring best practices
REFACTOR_PATTERNS=$(mapify playbook query "refactor [component type]" --limit 5 --section ARCHITECTURE_PATTERNS --section CODE_QUALITY_RULES)
```

**ALWAYS run predictor FIRST** before any refactoring:

```
Task(
  subagent_type="predictor",
  description="Analyze refactoring scope and dependencies",
  prompt="Analyze the scope and dependencies for this refactoring:

**Refactoring Request:** $ARGUMENTS

Before making ANY changes, identify:
- All files that import/use the code to be refactored
- All tests that depend on this code
- All public APIs that might be affected
- All configuration files that reference this code
- Database schemas, migrations, or data structures involved

Output JSON with:
- affected_files: array of {path, relationship, impact_level}
- public_apis: array of {name, type, usage_locations}
- dependencies: array of {type, description, must_update}
- risk_assessment: {level: 'low'|'medium'|'high', reasoning: string}
- recommended_approach: string
- testing_strategy: string"
)
```

**If predictor.risk_assessment.level === 'high':**
- Ask user for confirmation before proceeding
- Consider breaking into smaller refactoring steps

## Step 2: Decompose Refactoring

```
Task(
  subagent_type="task-decomposer",
  description="Decompose refactoring into safe steps",
  prompt="Break down this refactoring into atomic, safe steps:

**Refactoring Goal:** $ARGUMENTS

**Predictor Analysis:** [paste predictor JSON]

Create subtasks that:
- Minimize risk (each step should be independently testable)
- Maintain backward compatibility where possible
- Allow for incremental rollback if issues occur

Output JSON with:
- subtasks: array of {id, description, refactor_type, risk_level, rollback_plan}
- dependency_order: array of subtask IDs in execution order
- critical_checkpoints: array of {after_subtask_id, verification_required}

Refactor types:
- rename: changing names only
- extract: moving code to new location
- restructure: changing organization
- simplify: reducing complexity"
)
```

### 🔄 Handling Context Compaction

> **IMPORTANT:** If context compaction occurs during workflow, your plan survives on filesystem!
>
> **Recovery Steps:**
> 1. Run `mapify recitation checkpoint` to see current state
> 2. Copy the @-mention paths shown in output
> 3. Paste recovery message to Claude:
>    ```
>    Continue MAP workflow from checkpoint:
>    @.map/current_plan.md
>    @.map/dev_docs/context.md
>    @.map/dev_docs/tasks.md
>    ```
> 4. Resume from current subtask (all progress preserved)
>
> Files in `.map/` directory persist forever—conversation memory clears but filesystem doesn't.

## Step 3: For Each Refactoring Step

### Actor: Implement Refactoring

```
Task(
  subagent_type="actor",
  description="Refactor [component]",
  prompt="Perform this refactoring step:

**Step:** [description]
**Type:** [refactor_type]
**Affected Files:** [from predictor]

Output JSON with:
- approach: string (refactoring strategy)
- code_changes: array of {file_path, change_type, content, before_snippet, after_snippet}
- behavior_unchanged_proof: string (explain why behavior is identical)
- updated_imports: array of {file, old_import, new_import}
- updated_tests: array of {file, changes_needed}

**CRITICAL:** For refactoring, provide side-by-side comparison showing behavior is unchanged."
)
```

### Monitor: Validate No Behavior Changes

```
Task(
  subagent_type="monitor",
  description="Validate refactoring preserves behavior",
  prompt="Review this refactoring to ensure NO behavioral changes:

**Actor Refactoring:** [paste actor JSON]

Check:
- Is the logic exactly the same? (only structure changed)
- Are all imports/exports updated correctly?
- Are tests still valid or properly updated?
- Are there any subtle behavior changes?
- Is error handling unchanged?
- Are edge cases still handled the same way?

**CRITICAL:** Reject if ANY behavior changes detected.

Output JSON with:
- behavior_preserved: boolean
- issues: array of {severity, category, description}
- test_updates_needed: array of strings
- verdict: 'approved'|'needs_revision'|'rejected'
- feedback: string"
)
```

### Predictor: Verify No Breaking Changes

After monitor approval:

```
Task(
  subagent_type="predictor",
  description="Verify no breaking changes introduced",
  prompt="Verify this refactoring introduces no breaking changes:

**Refactoring:** [paste actor JSON]
**Monitor Verdict:** approved

Check:
- Are all public APIs unchanged?
- Are all usages still valid?
- Are there any import/export breakages?
- Does this affect any external consumers?

Output JSON with:
- breaking_changes: array (should be empty for pure refactoring!)
- compatibility_check: {backward_compatible: boolean, forward_compatible: boolean}
- verification_tests: array of tests that must pass
- risk_level: 'low' (should always be low for pure refactoring)"
)
```

### Evaluator: Assess Quality Improvement

```
Task(
  subagent_type="evaluator",
  description="Evaluate refactoring quality improvement",
  prompt="Evaluate the quality improvement from this refactoring:

**Before:** [code before refactoring]
**After:** [paste actor JSON]

Score improvement (0-10) in:
- readability: is code easier to understand?
- maintainability: is code easier to modify?
- testability: is code easier to test?
- modularity: is structure better organized?
- complexity: is complexity reduced?

Output JSON with:
- improvement_scores: object
- overall_improvement: number
- recommendation: 'proceed'|'improve'|'revert'
- justification: string
- was_it_worth_it: boolean"
)
```

### Apply Refactoring

If all checks pass:
- Apply code changes
- Update all imports/references
- **Run ALL tests** (critical for refactoring!)
- Verify behavior unchanged

### Reflect on Refactoring

```
Task(
  subagent_type="reflector",
  description="Extract refactoring lessons",
  prompt="Extract lessons from this refactoring:

**Refactoring:** [what was changed]
**Quality Improvement:** [evaluator scores]
**Issues Encountered:** [if any]

Analyze:
- What refactoring patterns were effective?
- What should be refactored next?
- What made this refactoring safe/risky?
- How could we prevent the need for such refactoring?

Output JSON with refactoring insights."
)
```

### Update Playbook

```
Task(
  subagent_type="curator",
  description="Store refactoring patterns",
  prompt="Store refactoring patterns in playbook:

**Reflector Insights:** [paste JSON]

Focus on:
- Safe refactoring techniques
- Risk mitigation strategies
- Quality improvement patterns

Output curator operations."
)
```

## Step 4: Final Verification

After all refactoring steps complete:

1. **Run complete test suite** (all tests must pass!)
2. **Compare before/after behavior** (should be identical)
3. **Check performance** (should not degrade)
4. **Verify all usages** (nothing should break)
5. **Create detailed commit** explaining what was refactored and why

## Step 5: Store Refactoring Pattern

```
mcp__cipher__cipher_extract_and_operate_memory({
  "interaction": "Refactored [component]. Approach: [summary]. Quality improvement: [scores]. Lessons: [key insights]."
})
```

## MCP Tools for Refactoring

- `mcp__cipher__cipher_memory_search` - Find successful refactoring patterns
- `mcp__sequential-thinking__sequentialthinking` - Plan complex refactorings
- `mcp__deepwiki__ask_question` - See how others refactored similar code

## Critical Constraints for Refactoring

- **ALWAYS run predictor FIRST** before any changes
- **NEVER change behavior** - only structure
- **ALWAYS run ALL tests** after each step
- **NEVER skip backward compatibility** checks
- **ALWAYS have rollback plan** for each step
- **Use Task tool** to call all subagents

## Example

User says: `/map-refactor extract authentication logic into separate module`

You should:
1. Task(subagent_type="predictor") → analyze all dependencies FIRST
2. Task(subagent_type="task-decomposer") → break into safe steps
3. For each step:
   - actor → refactor code
   - monitor → verify no behavior changes
   - predictor → verify no breaking changes
   - evaluator → assess quality improvement
   - Apply changes and **run tests**
4. Reflect + curate refactoring patterns
5. Final verification (all tests pass, behavior unchanged)

Begin refactoring now.
