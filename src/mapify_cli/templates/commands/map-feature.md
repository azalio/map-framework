---
description: Implement new feature using full MAP workflow
---

# MAP Feature Implementation Workflow

**CRITICAL INSTRUCTION:** This is an **automated sequential workflow**. You MUST execute ALL steps from start to finish without stopping. After calling each subagent, IMMEDIATELY proceed to the next step in the workflow. DO NOT wait for user input between steps - this is a fully autonomous multi-agent orchestration.

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

Implement the following feature using the MAP (Modular Agentic Planner) framework with ACE (Adaptive Contextual Engine) learning:

**Feature Request:** $ARGUMENTS

## Workflow Overview

You will orchestrate the MAP workflow by sequentially calling subagents using the Task tool. Follow this pattern:

```
1. DECOMPOSE → task-decomposer
2. FOR each subtask:
   3. IMPLEMENT → actor
   4. VALIDATE → monitor
   5. If invalid: provide feedback to actor, go to step 3 (max 3-5 iterations)
   6. PREDICT → predictor
   7. EVALUATE → evaluator
   8. If not approved: provide feedback to actor, go to step 3
   9. ACCEPT and apply changes
   10. REFLECT → reflector (extract lessons)
   11. CURATE → curator (update playbook)
```

**⚠️ IMPORTANT:** After each Task() call completes, immediately proceed to the next step. The workflow is SEQUENTIAL and AUTOMATED - do not stop after Actor, Monitor, Predictor, or Evaluator. Each step builds on the previous one. Continue until all subtasks are completed and reflected in the playbook.

## Step 1: Load Playbook Context

Use `mapify playbook query` or `mapify playbook search` to get relevant patterns from the playbook SQLite database.

## Step 2: Task Decomposition

Call the task-decomposer subagent to break down the feature into atomic subtasks:

```
Task(
  subagent_type="task-decomposer",
  description="Decompose feature into subtasks",
  prompt="Break down this feature into atomic subtasks (≤8):

Feature: $ARGUMENTS

Output JSON with:
- subtasks: array of {id, description, acceptance_criteria, estimated_complexity, depends_on}
- total_subtasks: number
- estimated_duration: string

Each subtask must be:
- Atomic (can't be subdivided further)
- Testable (clear acceptance criteria)
- Independent where possible (minimal dependencies)"
)
```

## Step 2.5: Create Recitation Plan (Context Engineering)

**IMPORTANT:** Create a task plan to keep goals fresh in context (Recitation pattern).

After receiving TaskDecomposer output, create the plan using Bash:

```bash
# Save subtasks to temporary variable
SUBTASKS_JSON='[TaskDecomposer output JSON array]'
TASK_ID="feat_$(date +%s)"

# Create recitation plan
mapify recitation create "$TASK_ID" "$ARGUMENTS" "$SUBTASKS_JSON"
```

This creates `.map/current_plan.md` which will be updated before each subtask to maintain focus.

**Example:**
```bash
mapify recitation create feat_1760783000 "Add user authentication" '[{"id":1,"description":"Create User model",...}]'
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

## Step 3: For Each Subtask - Implementation Loop

For each subtask from task-decomposer output:

### 3.1 Get Relevant Playbook Context

**Step A: Query Local Playbook** (project-specific patterns):

```bash
# Query playbook using FTS5 full-text search (local project patterns)
PLAYBOOK_BULLETS=$(mapify playbook query "[subtask description]" --limit 5)
```

**Why use `mapify playbook query` instead of grep/read:**
- ✅ Works with large playbooks (>256KB) - grep/read fails
- ✅ FTS5 full-text search - faster and more accurate than grep
- ✅ Ranked by relevance - best patterns first
- ✅ Quality scoring - prioritizes proven patterns

**Step B: Search Cipher** (cross-project validated patterns):

IMPORTANT: Also search cipher directly via MCP tool for broader knowledge:

```
# Call this BEFORE Actor to get cross-project patterns
mcp__cipher__cipher_memory_search(
  query="[subtask concept or pattern type]",
  top_k=5
)
```

**Why separate tools:**
- Playbook (via Bash): Project-specific conventions and lessons
- Cipher (via MCP): Cross-project validated patterns
- Bash commands can't invoke MCP tools - must call separately
- Agent combines both sources for richer context

### 3.1.5 Update Recitation Plan (BEFORE Actor)

**Mark subtask as in_progress and get fresh context:**

```bash
# Update plan status (use integer ID from TaskDecomposer output)
# TaskDecomposer returns {"id": 1, ...}, {"id": 2, ...} - use these integers directly
# Example: if current subtask has "id": 1, use: mapify recitation update 1 in_progress
mapify recitation update <subtask_id: integer from TaskDecomposer> in_progress

# Get current plan for Actor context (RECITATION PATTERN)
PLAN_CONTEXT=$(mapify recitation get-context)
# This markdown shows progress and current focus
```

The `PLAN_CONTEXT` will be included in the Actor prompt below.

### 3.2 Call Actor to Implement

**IMPORTANT:** Include plan context from step 3.1.5 in Actor prompt to maintain focus.

The Actor agent template (`.claude/agents/actor.md`) already has a `{{plan_context}}` template variable in the `<recitation_plan>` section. You just need to pass it:

```
Task(
  subagent_type="actor",
  description="Implement subtask [ID]",
  prompt="Implement this subtask:

**Subtask:** [description]
**Acceptance Criteria:** [criteria]

**Relevant Playbook Context:**
```
$PLAYBOOK_BULLETS
```

**Plan Context (for recitation):**
```
$PLAN_CONTEXT
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

**Note:** The Actor template will automatically format the plan_context in its `<recitation_plan>` section.

### 3.3 Call Monitor to Validate

```
Task(
  subagent_type="monitor",
  description="Validate actor proposal",
  prompt="Review this implementation proposal:

**Actor Output:** [paste actor JSON]

Check for:
- Code correctness
- Security issues
- Performance concerns
- Test coverage
- Documentation
- Standards compliance

Output JSON with:
- valid: boolean
- issues: array of {severity, category, description, file_path, line_range}
- verdict: 'approved' | 'needs_revision' | 'rejected'
- feedback: string (actionable guidance)"
)
```

### 3.4 Decision Point

**If monitor.valid === false:**
- **Record error in plan (Recitation):**
  ```bash
  # Update with error message for retry (use integer ID from TaskDecomposer)
  # Example: mapify recitation update 2 in_progress "Monitor feedback: missing error handling"
  mapify recitation update <subtask_id: integer> in_progress "Monitor feedback: [error details]"
  # Plan will show: "⚠️ Retry attempt 2 - review previous errors"
  ```
- Provide monitor feedback to actor
- Go back to step 3.1.5 (Actor implements fixes)
- **⚠️ CRITICAL:** After Actor applies fixes, IMMEDIATELY call Monitor again (step 3.3) to validate the corrections
- **DO NOT skip Monitor validation** - you cannot proceed to Predictor/Evaluator without Monitor approval
- Max 3-5 iterations, then escalate to user

**If monitor.valid === true:**
- Continue to step 3.5

### 3.5 Call Predictor to Analyze Impact

**⚠️ PREREQUISITE:** You can ONLY reach this step if Monitor returned `valid: true` and `verdict: "approved"`. If you just applied Actor fixes after Monitor feedback, you MUST call Monitor again (step 3.3) before proceeding to Predictor.

```
Task(
  subagent_type="predictor",
  description="Analyze implementation impact",
  prompt="Analyze the impact of this implementation:

**Actor Output:** [paste actor JSON]
**Monitor Verdict:** approved

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

### 3.6 Call Evaluator to Score Quality

```
Task(
  subagent_type="evaluator",
  description="Evaluate solution quality",
  prompt="Evaluate this solution:

**Actor Output:** [paste actor JSON]
**Monitor Verdict:** [verdict]
**Predictor Analysis:** [paste predictor JSON]

Score (0-10) on:
- code_quality
- test_coverage
- documentation_quality
- security
- performance
- maintainability

Output JSON with:
- scores: object with above metrics
- overall_score: number (average)
- recommendation: 'proceed' | 'improve' | 'reject'
- justification: string
- improvement_suggestions: array of strings"
)
```

### 3.7 Decision Point

**If evaluator.recommendation !== 'proceed':**
- Provide evaluator feedback to actor
- Go back to step 3.2

**If evaluator.recommendation === 'proceed':**
- ACCEPT the solution
- Apply code changes (use Write/Edit tools)
- **Mark subtask as completed (Recitation):**
  ```bash
  # Mark complete using integer ID from TaskDecomposer
  # Example: mapify recitation update 1 completed
  mapify recitation update <subtask_id: integer> completed
  # Plan will show: "✓ Subtask 1 completed"
  # Next subtask will see this progress
  ```
- Continue to step 3.8

### 3.8 Call Reflector to Extract Lessons

**⚠️ CRITICAL:** The Reflector agent template (`.claude/agents/reflector.md`) contains MANDATORY instructions to use MCP tools. You MUST verify the Reflector actually uses these tools by checking its output:

**REQUIRED MCP Tools:**
1. **BEFORE analysis**: `cipher_memory_search` - Check for similar past patterns
2. **FOR complex failures**: `sequential-thinking` - Deep root cause analysis

**Verification Checklist:**
- [ ] Did Reflector output show `cipher_memory_search` was called?
- [ ] Did Reflector check for duplicate patterns before suggesting new bullets?
- [ ] If no cipher search visible in output, the agent DID NOT follow its instructions

```
Task(
  subagent_type="reflector",
  description="Extract lessons from implementation",
  prompt="Extract structured lessons from this implementation:

**Actor Code:** [paste actor output]
**Monitor Results:** [paste monitor output]
**Predictor Analysis:** [paste predictor output]
**Evaluator Scores:** [paste evaluator output]
**Execution Outcome:** success

**MANDATORY FIRST STEP (per agent template):**
Before extracting patterns, you MUST:
1. Call cipher_memory_search to check if similar patterns already exist
2. Only suggest new bullets if pattern is genuinely novel
3. Reference existing cipher patterns in your analysis

Analyze:
- What worked well?
- What patterns were effective?
- What could be improved?
- What should be remembered for future tasks?

Output JSON with:
- key_insight: string (one sentence takeaway)
- patterns_used: array of strings
- patterns_discovered: array of strings
- bullet_updates: array of {bullet_id, new_helpful_count, new_harmful_count, reason}
- suggested_new_bullets: array of {section, content, code_example, initial_score}"
)
```

### 3.9 Call Curator to Update Playbook

**⚠️ CRITICAL:** The Curator agent template (`.claude/agents/curator.md`) contains MANDATORY instructions to use MCP tools for deduplication and knowledge sharing.

**REQUIRED MCP Tools:**
1. **BEFORE creating ADD operations**: `cipher_memory_search` - Check for cross-project duplicates
2. **AFTER playbook update**: `cipher_extract_and_operate_memory` - Sync high-quality bullets (helpful_count >= 5)

**Verification Checklist:**
- [ ] Did Curator output show `cipher_memory_search` was called before adding bullets?
- [ ] Did Curator output show `sync_to_cipher` operations for high-quality bullets?
- [ ] If no cipher operations visible, the agent DID NOT follow its instructions

```
Task(
  subagent_type="curator",
  description="Update playbook with learnings",
  prompt="Integrate these learnings into the playbook:

**Reflector Insights:** [paste reflector JSON]

**MANDATORY STEPS (per agent template):**
1. BEFORE creating ADD operations: cipher_memory_search to check duplicates
2. Create delta operations (ADD/UPDATE/DEPRECATE)
3. AFTER applying operations: IF any bullet has helpful_count >= 5, MUST call cipher_extract_and_operate_memory to sync to cross-project knowledge base

Output JSON with:
- operations: array of {operation: 'ADD'|'UPDATE'|'DEPRECATE', section, bullet_id, content, reason}
- deduplication_check: array of {new_bullet, similar_existing_bullets, action}
- sync_to_cipher: array of {bullet_id, content, helpful_count} (REQUIRED if helpful_count >= 5)"
)
```

### 3.10 Apply Curator Operations

**⚠️ CRITICAL - Use CLI Command:**

Apply Curator delta operations using the CLI command:

```bash
# Save Curator output to file
echo '[Curator JSON output]' > curator_operations.json

# Apply to playbook SQLite database
mapify playbook apply-delta curator_operations.json

# Or pipe directly from Curator output
echo '[Curator JSON output]' | mapify playbook apply-delta
```

- **MANDATORY**: If Curator output contains `sync_to_cipher` array with ANY entries, you MUST call:
  ```
  mcp__cipher__cipher_extract_and_operate_memory(
    interaction: [bullet content],
    memoryMetadata: {"projectId": "map-framework", "source": "curator"}
  )
  ```
- **DO NOT skip cipher sync** - high-quality patterns (helpful_count >= 5) MUST be shared across projects

### 3.11 Move to Next Subtask

Repeat steps 3.1-3.10 for each remaining subtask.

## Step 4: Final Summary

After all subtasks completed:

1. **Get final statistics from Recitation:**
   ```bash
   mapify recitation stats
   # Shows: total_subtasks, completed, total_iterations, etc.
   ```

2. **Run tests** (if applicable)

3. **Create commit** with descriptive message

4. **Summarize results**:
   - Features implemented
   - Files changed
   - New playbook bullets added
   - Overall quality score
   - **Include recitation stats** (from step 1):
     - Total subtasks
     - Iterations needed
     - Average iterations per subtask
     - Success rate

5. **Store workflow pattern in cipher** for future reuse

6. **Clean up recitation plan:**
   ```bash
   mapify recitation clear
   # Removes .map/current_plan.md and .map/current_plan.json
   ```

## MCP Tools Available

Use these MCP tools throughout the workflow:

- `mcp__cipher__cipher_memory_search` - Search for similar past implementations
- `mcp__cipher__cipher_extract_and_operate_memory` - Store successful patterns
- `mcp__sequential-thinking__sequentialthinking` - Complex decision making
- `mcp__context7__resolve-library-id` + `get-library-docs` - Get current library docs
- `mcp__deepwiki__read_wiki_structure` - Learn from other repositories
- `mcp__claude-reviewer__request_review` - Request code review at the end

## Critical Constraints

- **NEVER skip monitor validation** - always validate before proceeding
- **NEVER exceed 5 iterations** per subtask - escalate to user if stuck
- **ALWAYS apply code changes** after evaluator approves
- **ALWAYS run reflector + curator** after each subtask (learn continuously)
- **ALWAYS update playbook** with new learnings
- **Use Task tool** to call all subagents (NOT Bash or Python)

## Example Invocation

User says: `/map-feature add user authentication with JWT`

You should:
1. Query playbook context: `mapify playbook query "authentication JWT" --limit 5`
2. Call Task(subagent_type="task-decomposer", ...) to get subtasks
3. For each subtask:
   - Task(subagent_type="actor", ...)
   - Task(subagent_type="monitor", ...)
   - If approved: Task(subagent_type="predictor", ...)
   - Task(subagent_type="evaluator", ...)
   - If proceed: apply changes
   - Task(subagent_type="reflector", ...)
   - Task(subagent_type="curator", ...)
   - Apply curator operations: `mapify playbook apply-delta curator_output.json`
4. Commit and summarize

Begin now with the feature request above.
