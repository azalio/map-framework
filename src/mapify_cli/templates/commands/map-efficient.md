---
description: Optimized workflow with batched learning (RECOMMENDED for token-conscious production work)
---

# MAP Efficient Workflow

**CRITICAL INSTRUCTION:** This is an **automated sequential workflow**. You MUST execute ALL steps from start to finish without stopping. After calling each subagent, IMMEDIATELY proceed to the next step in the workflow. DO NOT wait for user input between steps.

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

---

**✅ RECOMMENDED: Best Balance of Speed and Quality**

This workflow provides **intelligent token optimization (30-40% savings)** while **preserving MAP's core value**:

✅ **Impact Analysis** (Predictor) → Conditional on risk level
✅ **Basic Validation** (Monitor) → Always enforced
✅ **Learning** → OPTIONAL via `/map-learn` command after workflow

**Token Savings vs Full Workflow:**
- Skip Evaluator per subtask: ~8-12% savings
- Conditional Predictor: ~5-10% savings
- Optional learning (not automatic): ~15-20% savings
- **Total: 40-50% token reduction**

**When to use /map-efficient:**
- Production code where token costs matter
- Well-understood tasks with low risk
- Iterative development with frequent workflows
- Any task where /map-fast feels too risky but /map-feature too expensive

**When to use /map-feature instead:**
- First time implementing critical functionality
- High-risk changes (security, authentication, data handling)
- Complex refactoring across many files
- When maximum quality assurance is required

---

Implement the following with efficient workflow:

**Task:** $ARGUMENTS

## Workflow Overview

Optimized agent sequence (no automatic learning):

```
1. DECOMPOSE → task-decomposer
2. FOR each subtask:
   3. IMPLEMENT → actor
   4. VALIDATE → monitor
   5. If invalid: provide feedback, go to step 3 (max 3-5 iterations)
   6. If high_risk: ANALYZE → predictor
   7. ACCEPT and apply changes
8. DONE → Suggest /map-learn if user wants to preserve lessons
```

**Key Optimizations:**
- **Evaluator skipped** → Monitor provides sufficient validation for most tasks
- **Predictor conditional** → Only called when Monitor flags high risk
- **Learning optional** → User runs `/map-learn` separately if desired

## Step 1: Load Playbook Context

Use `mapify playbook query` or `mapify playbook search` to get relevant patterns from the playbook SQLite database.

## Step 2: Task Decomposition

Call the task-decomposer subagent (NOT general-purpose):

```
Task(
  subagent_type="task-decomposer",
  description="Decompose task into subtasks",
  prompt="Break down this task into atomic subtasks (≤8):

Task: $ARGUMENTS

Output JSON with:
- subtasks: array of {id, description, acceptance_criteria, estimated_complexity, risk_level, depends_on}
- total_subtasks: number
- estimated_duration: string

**IMPORTANT**: Assign risk_level ('low'|'medium'|'high') to each subtask based on:
- 'high': Security-sensitive, breaking changes, multi-file modifications
- 'medium': Moderate complexity, some dependencies
- 'low': Simple, isolated changes

Risk level determines if Predictor is called (high/medium = yes, low = no)."
)
```

## Step 3: For Each Subtask - Efficient Loop

### 3.1 Get Relevant Playbook Context

**Step A: Query Local Playbook**:

```bash
# Query playbook using FTS5 (project-specific patterns)
PLAYBOOK_BULLETS=$(mapify playbook query "[subtask description]" --limit 5)
```

**Step B: Search Cipher** (optional but recommended):

```
# Get cross-project patterns via MCP tool
mcp__cipher__cipher_memory_search(
  query="[subtask concept]",
  top_k=5
)
```

**Benefits over grep/read:**
- Works with large playbooks (>256KB)
- FTS5 full-text search with relevance ranking
- Quality-scored results
- Cipher adds cross-project validated patterns

### 3.2 Call Actor to Implement

**⚠️ MUST use subagent_type="actor"** (NOT general-purpose):

```
Task(
  subagent_type="actor",
  description="Implement subtask [ID]",
  prompt="Implement this subtask:

**Subtask:** [description]
**Acceptance Criteria:** [criteria]
**Risk Level:** [risk_level from TaskDecomposer]

**Relevant Playbook Context:**
[Include 3-5 relevant bullets from playbook]

Output JSON with:
- approach: string (implementation strategy)
- code_changes: array of {file_path, change_type, content, rationale}
- trade_offs: array of strings
- testing_approach: string
- used_bullets: array of bullet IDs that were helpful

Provide FULL file content for each change, not diffs."
)
```

### 3.3 Call Monitor to Validate

**⚠️ MUST use subagent_type="monitor"** (NOT general-purpose):

```
Task(
  subagent_type="monitor",
  description="Validate implementation",
  prompt="Review this implementation:

**Actor Output:** [paste actor JSON]

Check for:
- Code correctness
- Security issues
- Basic performance concerns
- Test coverage
- Standards compliance

**RISK ASSESSMENT**: Flag if:
- Security vulnerabilities detected
- Breaking API changes likely
- Multiple files modified (>3)
- Complex dependencies involved

Output JSON with:
- valid: boolean
- issues: array of {severity, category, description, file_path, line_range}
- verdict: 'approved' | 'needs_revision' | 'rejected'
- feedback: string (actionable guidance)
- **high_risk_detected**: boolean (if true, Predictor will be called)"
)
```

### 3.4 Decision Point

**If monitor.valid === false:**
- Provide feedback to actor
- Go back to step 3.2 (max 3-5 iterations)

**If monitor.valid === true:**
- Continue to step 3.5

### 3.5 Conditional Predictor (Token Optimization)

**Only call Predictor if:**
- `monitor.high_risk_detected === true`, OR
- `subtask.risk_level === 'high'` or `'medium'`

**Skip Predictor if:**
- `subtask.risk_level === 'low'` AND
- `monitor.high_risk_detected === false`

**⚠️ MUST use subagent_type="predictor"** (NOT general-purpose):

```
Task(
  subagent_type="predictor",
  description="Analyze implementation impact",
  prompt="Analyze the impact of this implementation:

**Actor Output:** [paste actor JSON]
**Monitor Verdict:** approved
**Risk Trigger:** [why Predictor was called: subtask.risk_level or monitor flag]

Analyze:
- Affected files and modules
- Breaking changes (API, schema, behavior)
- Dependencies that need updates
- Migration requirements
- Rollback strategy

Output JSON with:
- affected_files: array of {path, change_type, impact_level}
- breaking_changes: array of {type, description, mitigation}
- required_updates: array of strings
- risk_level: 'low' | 'medium' | 'high'
- rollback_plan: string"
)
```

**Token Savings Note:** Skipping Predictor for low-risk tasks saves ~2-3K tokens per subtask.

### 3.6 Apply Changes

- Apply code changes using Write/Edit tools
- Mark subtask completed

### 3.7 Move to Next Subtask

Repeat steps 3.1-3.6 for each remaining subtask.

## Step 4: Final Summary

Run tests (if applicable), create commit, and summarize:
- Features implemented
- Files changed
- Overall quality
- **Token efficiency:**
  - Predictor calls: [count] / [total_subtasks] subtasks ([X]% saved)
  - Learning skipped: ~15-20% additional savings
  - Estimated token savings: ~40-50% vs /map-feature

---

## 💡 Optional: Preserve Lessons Learned

**If you want to save patterns from this workflow for future use:**

```
/map-learn [workflow summary with actor outputs, monitor results, files changed]
```

This is **completely optional**. Run it when:
- You discovered valuable patterns worth preserving
- The implementation approach could help future similar tasks
- You want to update the playbook with new insights

Skip `/map-learn` when:
- The task was routine with no novel patterns
- You're iterating quickly and learning overhead isn't worth it
- Token budget is constrained

## MCP Tools Available

- `mcp__cipher__cipher_memory_search` - Search past implementations
- `mcp__cipher__cipher_extract_and_operate_memory` - Store successful patterns
- `mcp__sequential-thinking__sequentialthinking` - Complex decision making
- `mcp__context7__get-library-docs` - Get library documentation
- `mcp__claude-reviewer__request_review` - Request code review

## Comparison: /map-efficient vs Alternatives

| Feature | /map-feature (Full) | /map-efficient (YOU) | /map-fast (Minimal) |
|---------|---------------------|----------------------|---------------------|
| **Validation** | Monitor + Evaluator | Monitor only | Monitor only |
| **Impact Analysis** | Always (Predictor) | Conditional | Never |
| **Learning** | Per-subtask | Optional (/map-learn) | None |
| **Quality Gates** | All agents | Essential agents | Basic only |
| **Token Usage** | 100% (baseline) | **50-60%** | 40-50% |
| **Production Safe** | ✅ Maximum | ✅ Yes | ❌ No |
| **Knowledge Growth** | ✅ Full | 🔸 On-demand | ❌ None |
| **Best For** | Critical features | **Most tasks** | Throwaway only |

## Critical Constraints

- **Predictor conditional** on risk level (saves tokens for low-risk tasks)
- **Evaluator skipped** (Monitor provides sufficient validation)
- **Learning optional** — run `/map-learn` after workflow if desired
- **MAX 5 iterations** per subtask
- **Use /map-feature** if you need maximum quality assurance

## Example

User says: `/map-efficient implement user profile editing feature`

This workflow will:
1. Decompose into subtasks (e.g., API endpoint, database update, frontend form)
2. For each subtask:
   - Actor implements
   - Monitor validates
   - Predictor called only if high risk (e.g., database migration)
   - Apply changes
3. Done! Optionally run `/map-learn` to preserve patterns

**Token savings**: ~40-50% vs /map-feature, while maintaining:
- Essential quality gates (Monitor, conditional Predictor)
- Production readiness
- On-demand learning via `/map-learn`

---

**Why /map-efficient is RECOMMENDED:**

✅ **Maximum token savings** (40-50% vs /map-feature)
✅ **Production-ready** (essential quality gates maintained)
✅ **Learning on-demand** (run /map-learn only when needed)
✅ **Best balance** of speed and quality

Begin now with efficient workflow.
