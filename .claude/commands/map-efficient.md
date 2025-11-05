---
description: Optimized workflow with batched learning (RECOMMENDED for token-conscious production work)
---

# MAP Efficient Workflow

**✅ RECOMMENDED: Best Balance of Speed and Quality**

This workflow provides **intelligent token optimization (30-40% savings)** while **preserving MAP's core value**:

✅ **Impact Analysis** (Predictor) → Conditional on risk level
✅ **Basic Validation** (Monitor) → Always enforced
✅ **Learning Preserved** (Reflector/Curator) → Batched at end
✅ **Playbook Updates** → Single update after all subtasks
✅ **Cipher Integration** → Cross-project knowledge maintained

**Token Savings vs Full Workflow:**
- Skip Evaluator per subtask: ~8-12% savings
- Conditional Predictor: ~5-10% savings
- Batched Reflector/Curator: ~10-15% savings
- **Total: 30-40% token reduction**

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

Optimized agent sequence (batched learning, conditional analysis):

```
1. DECOMPOSE → task-decomposer
2. FOR each subtask:
   3. IMPLEMENT → actor
   4. VALIDATE → monitor
   5. If invalid: provide feedback, go to step 3 (max 3-5 iterations)
   6. If high_risk: ANALYZE → predictor
   7. ACCEPT and apply changes
8. BATCH REFLECT → reflector (analyze ALL subtasks together)
9. BATCH CURATE → curator (single playbook update)
```

**Key Optimizations:**
- **Evaluator skipped** → Monitor provides sufficient validation for most tasks
- **Predictor conditional** → Only called when Monitor flags high risk
- **Reflector batched** → Analyzes all subtasks at end (more holistic insights)
- **Curator batched** → Single playbook update (vs per-subtask updates)

## Step 1: Load Playbook Context

Use `mapify playbook query` or `mapify playbook search` to get relevant patterns from the playbook SQLite database.

## Step 2: Task Decomposition

```
Task(
  subagent_type="general-purpose",
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

## Step 2.5: Create Recitation Plan

```bash
SUBTASKS_JSON='[TaskDecomposer output JSON array]'
TASK_ID="feat_$(date +%s)"

mapify recitation create "$TASK_ID" "$ARGUMENTS" "$SUBTASKS_JSON"
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

### 3.1.5 Update Recitation Plan

```bash
# Use the string ID from JSON subtasks (e.g., "ST-001", "ST-002", etc.)
mapify recitation update "ST-001" in_progress
PLAN_CONTEXT=$(mapify recitation get-context)
```

### 3.2 Call Actor to Implement

```
Task(
  subagent_type="general-purpose",
  description="Implement subtask [ID]",
  prompt="Implement this subtask:

**Subtask:** [description]
**Acceptance Criteria:** [criteria]
**Risk Level:** [risk_level from TaskDecomposer]

**Relevant Playbook Context:**
[Include 3-5 relevant bullets from playbook]

**Plan Context:**
```
[Insert output from: mapify recitation get-context]
```

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

```
Task(
  subagent_type="general-purpose",
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
```bash
# Use the same subtask ID that was marked as in_progress earlier
mapify recitation update "ST-001" in_progress "Monitor feedback: [error details]"
```
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

```
Task(
  subagent_type="general-purpose",
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
- Mark subtask completed:

```bash
# Mark the current subtask as completed (use its string ID from JSON)
mapify recitation update "ST-001" completed
```

### 3.7 Move to Next Subtask

Repeat steps 3.1-3.6 for each remaining subtask.

**Note:** We are NOT calling Reflector/Curator per subtask. They will be batched at the end (Step 4).

## Step 4: Batched Learning (Key Optimization)

After ALL subtasks completed, perform batched reflection and curation:

### 4.1 Batch Reflector Analysis

```
Task(
  subagent_type="general-purpose",
  description="Extract lessons from all subtasks",
  prompt="Extract structured lessons from this ENTIRE workflow:

**All Subtask Outputs:**
[Paste Actor outputs for ALL subtasks]

**All Monitor Results:**
[Paste Monitor outputs for ALL subtasks]

**All Predictor Analyses (if any):**
[Paste Predictor outputs where called]

**Workflow Summary:**
- Total subtasks: [N]
- High-risk subtasks: [count]
- Iterations required: [total across all subtasks]
- Files changed: [list]

**MANDATORY FIRST STEP:**
1. Call mcp__cipher__cipher_memory_search to check if similar patterns already exist
2. Only suggest new bullets if pattern is genuinely novel
3. Reference existing cipher patterns in your analysis

Analyze holistically:
- What patterns emerged across multiple subtasks?
- What worked well consistently?
- What could be improved for future similar tasks?
- What knowledge should be preserved?

Output JSON with:
- key_insight: string (one sentence takeaway for entire workflow)
- patterns_used: array of strings
- patterns_discovered: array of strings
- bullet_updates: array of {bullet_id, new_helpful_count, new_harmful_count, reason}
- suggested_new_bullets: array of {section, content, code_example, initial_score}
- workflow_efficiency: {total_iterations, avg_per_subtask, bottlenecks: array}"
)
```

**Token Savings Note:** One batched reflection vs per-subtask reflection saves ~(N-1) * 3K tokens for N subtasks.

### 4.2 Batch Curator Update

```
Task(
  subagent_type="general-purpose",
  description="Update playbook with workflow learnings",
  prompt="Integrate batched learnings into playbook:

**Reflector Insights:** [paste reflector JSON from step 4.1]

**MANDATORY STEPS:**
1. BEFORE creating ADD operations: call mcp__cipher__cipher_memory_search to check duplicates
2. Create delta operations (ADD/UPDATE/DEPRECATE) for playbook
3. AFTER applying operations: IF any bullet has helpful_count >= 5, MUST call mcp__cipher__cipher_extract_and_operate_memory to sync to cross-project knowledge base

Output JSON with:
- operations: array of {operation: 'ADD'|'UPDATE'|'DEPRECATE', section, bullet_id, content, reason}
- deduplication_check: array of {new_bullet, similar_existing_bullets, action}
- sync_to_cipher: array of {bullet_id, content, helpful_count} (REQUIRED if helpful_count >= 5)"
)
```

### 4.3 Apply Curator Operations

Apply Curator delta operations using the CLI command:

```bash
# Save Curator output to file
echo '[Curator JSON output]' > curator_operations.json

# Apply to playbook SQLite database
mapify playbook apply-delta curator_operations.json
```

- **If `sync_to_cipher` array has entries:**
  ```
  mcp__cipher__cipher_extract_and_operate_memory(
    interaction: [bullet content],
    memoryMetadata: {"projectId": "map-framework", "source": "curator"}
  )
  ```

**Token Savings Note:** One batched curator vs per-subtask curator saves ~(N-1) * 2K tokens.

## Step 5: Final Summary

```bash
mapify recitation stats  # Get workflow metrics
```

Run tests (if applicable), create commit, and summarize:
- Features implemented
- Files changed
- Playbook bullets added
- Overall quality
- **Token efficiency:**
  - Predictor calls: [count] / [total_subtasks] subtasks ([X]% saved)
  - Batched learning: [N-1] reflection cycles saved
  - Estimated token savings: ~[X]% vs /map-feature

```bash
mapify recitation clear
```

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
| **Learning** | Per-subtask | Batched (end) | None |
| **Quality Gates** | All agents | Essential agents | Basic only |
| **Token Usage** | 100% (baseline) | **60-70%** | 50-60% |
| **Production Safe** | ✅ Maximum | ✅ Yes | ❌ No |
| **Knowledge Growth** | ✅ Full | ✅ Full | ❌ None |
| **Best For** | Critical features | **Most tasks** | Throwaway only |

## Critical Constraints

- **Predictor conditional** on risk level (saves tokens for low-risk tasks)
- **Evaluator skipped** (Monitor provides sufficient validation)
- **Reflector/Curator batched** (single learning cycle at end)
- **Learning preserved** (playbook and cipher still updated)
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
3. After all subtasks:
   - Batch Reflector analyzes entire feature
   - Batch Curator updates playbook once
   - Cipher receives high-quality patterns

**Token savings**: ~35% vs /map-feature, while maintaining:
- Full learning (playbook + cipher updated)
- Essential quality gates (Monitor, conditional Predictor)
- Production readiness

---

**Why /map-efficient is RECOMMENDED:**

✅ **Preserves MAP's core value** (continuous learning)
✅ **Significant token savings** (30-40%)
✅ **Production-ready** (essential quality gates maintained)
✅ **Holistic insights** (batched reflection sees patterns across subtasks)
✅ **Best balance** of speed, quality, and learning

Begin now with efficient workflow.
