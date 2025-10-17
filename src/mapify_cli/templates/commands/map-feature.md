---
description: Implement new feature using full MAP workflow
---

# MAP Feature Implementation Workflow

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

## Step 1: Load Playbook Context

Before starting, read `.claude/playbook.json` to get existing knowledge.

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

## Step 3: For Each Subtask - Implementation Loop

For each subtask from task-decomposer output:

### 3.1 Get Relevant Playbook Bullets

Search `.claude/playbook.json` for relevant patterns related to the current subtask (use grep/read).

### 3.2 Call Actor to Implement

```
Task(
  subagent_type="actor",
  description="Implement subtask [ID]",
  prompt="Implement this subtask:

**Subtask:** [description]
**Acceptance Criteria:** [criteria]

**Relevant Playbook Context:**
[Include 5-10 relevant bullets from playbook]

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
- Provide monitor feedback to actor
- Go back to step 3.2
- Max 3-5 iterations, then escalate to user

**If monitor.valid === true:**
- Continue to step 3.5

### 3.5 Call Predictor to Analyze Impact

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
- Continue to step 3.8

### 3.8 Call Reflector to Extract Lessons

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

```
Task(
  subagent_type="curator",
  description="Update playbook with learnings",
  prompt="Integrate these learnings into the playbook:

**Current Playbook:** [read from .claude/playbook.json]
**Reflector Insights:** [paste reflector JSON]

Output JSON with:
- operations: array of {operation: 'ADD'|'UPDATE'|'DEPRECATE', section, bullet_id, content, reason}
- deduplication_check: array of {new_bullet, similar_existing_bullets, action}
- sync_to_cipher: boolean (true if any bullets have helpful_count >= 5)"
)
```

### 3.10 Apply Curator Operations

- Read `.claude/playbook.json`
- Apply curator operations (ADD/UPDATE/DEPRECATE bullets)
- Write updated playbook back to `.claude/playbook.json`
- If sync_to_cipher is true, call cipher MCP tool to store high-quality patterns

### 3.11 Move to Next Subtask

Repeat steps 3.1-3.10 for each remaining subtask.

## Step 4: Final Summary

After all subtasks completed:

1. **Run tests** (if applicable)
2. **Create commit** with descriptive message
3. **Summarize results**:
   - Features implemented
   - Files changed
   - New playbook bullets added
   - Overall quality score
4. **Store workflow pattern in cipher** for future reuse

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
1. Read `.claude/playbook.json`
2. Call Task(subagent_type="task-decomposer", ...) to get subtasks
3. For each subtask:
   - Task(subagent_type="actor", ...)
   - Task(subagent_type="monitor", ...)
   - If approved: Task(subagent_type="predictor", ...)
   - Task(subagent_type="evaluator", ...)
   - If proceed: apply changes
   - Task(subagent_type="reflector", ...)
   - Task(subagent_type="curator", ...)
   - Update playbook
4. Commit and summarize

Begin now with the feature request above.
