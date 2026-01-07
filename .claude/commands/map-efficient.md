---
description: Token-efficient MAP workflow with conditional optimizations
---

# MAP Efficient Workflow

## Execution Rules

1. Execute ALL steps sequentially without stopping for user input
2. Use exact `subagent_type` specified — never substitute `general-purpose`
3. Call each agent individually — no combining or skipping steps
4. Max 5 retry iterations per subtask

**Task:** $ARGUMENTS

## Workflow Overview

```
1. DECOMPOSE → task-decomposer
2. FOR each subtask:
   a. CONTEXT → playbook query + optional cipher search
   b. RESEARCH → if existing code understanding needed
   c. IF Self-MoA (--self-moa OR risk_level:high):
      → 3 Actors (security/performance/simplicity)
      → 3 Monitors → Synthesizer → Final Monitor
   ELSE:
      → Actor → Monitor
   d. If invalid: retry with feedback (max 5)
   e. If risk_level ∈ {high, medium} OR high_risk_detected: → Predictor
   f. Apply changes
3. SUMMARY → optionally suggest /map-learn
```

## Step 1: Task Decomposition

```
Task(
  subagent_type="task-decomposer",
  description="Decompose task into subtasks",
  prompt="Break down into ≤8 atomic subtasks:

Task: $ARGUMENTS

Output JSON:
{
  subtasks: [{id, description, acceptance_criteria, estimated_complexity, risk_level, depends_on}],
  total_subtasks: number
}

risk_level assignment:
- high: Security-sensitive, breaking changes, multi-file modifications
- medium: Moderate complexity, dependencies
- low: Simple, isolated changes"
)
```

## Step 2: Subtask Loop

### 2.1 Get Context + Re-rank

```bash
# Query playbook (project-specific patterns)
mapify playbook query "[subtask description]" --limit 5

# Optional: cross-project patterns
mcp__cipher__cipher_memory_search(query="[concept]", top_k=5)
```

**Re-rank retrieved patterns** by relevance to current subtask:

```
FOR each pattern in retrieved_patterns:
  relevance_score = evaluate:
    - Domain match: Does pattern's domain match subtask? (+2)
    - Technology overlap: Same language/framework? (+1)
    - Recency: Created within 30 days? (+1)
    - Success indicator: Marked validated/production? (+1)
    - Complexity alignment: Similar complexity_score? (+1)

  SORT patterns by relevance_score DESC
  PASS top 3 patterns to Actor as "context_patterns"
```

Pass `context_patterns` with relevance scores to Actor for informed decision-making.

### 2.2 Research (Conditional)

**Call if:** refactoring, bug fixes, extending existing code, touching 3+ files
**Skip for:** new standalone features, docs, config

```
Task(
  subagent_type="research-agent",
  description="Research for subtask [ID]",
  prompt="Query: [subtask description]
File patterns: [relevant globs]
Intent: locate
Max tokens: 1500"
)
```

Pass `executive_summary` to Actor if `confidence >= 0.7`.

### 2.3 Self-MoA Check

```python
self_moa_enabled = (
    "--self-moa" in user_command OR
    subtask.risk_level == "high" OR
    subtask.estimated_complexity == "high"
)
```

**If Self-MoA enabled:** Execute Self-MoA Path
**Else:** Execute Standard Path

---

## Self-MoA Path

### 2.3a Parallel Actors

Call 3 Actors in parallel with different focuses:

```
# Variant 1: Security Focus
Task(
  subagent_type="actor",
  description="Implement subtask [ID] - Security (v1)",
  prompt="Implement with SECURITY focus:
**Subtask:** [description]
**Criteria:** [acceptance_criteria]
approach_focus: security, variant_id: v1, self_moa_mode: true

Output JSON: {approach, code_changes, trade_offs, testing_approach, used_bullets,
  decisions_made: [{category, statement, rationale, priority_class}]}"
)

# Variant 2: Performance Focus
Task(subagent_type="actor", prompt="... approach_focus: performance, variant_id: v2")

# Variant 3: Simplicity Focus
Task(subagent_type="actor", prompt="... approach_focus: simplicity, variant_id: v3")
```

### 2.3b Parallel Monitors

Validate each variant:

```
Task(
  subagent_type="monitor",
  description="Validate v1",
  prompt="Review variant v1:
**Actor Output:** [v1 output]
variant_id: v1, self_moa_mode: true

Output JSON: {valid, issues, verdict, feedback,
  decisions_identified, compatibility_features, strengths, weaknesses, recommended_as_base}"
)
```

### 2.3c Synthesizer

```
Task(
  subagent_type="synthesizer",
  description="Synthesize best implementation",
  prompt="Combine best parts from v1, v2, v3:

**Variants:** [v1, v2, v3 outputs]
**Monitor Results:** [m1, m2, m3 with compatibility_features]
**Priority:** correctness > security > maintainability > performance

Output JSON: {code, decisions_implemented, decisions_rejected, strategy_used, conflict_resolutions, confidence}"
)
```

### 2.3d Final Monitor

Validate synthesized code. If invalid: retry synthesis (max 2 iterations).

---

## Standard Path

### 2.3 Actor

```
Task(
  subagent_type="actor",
  description="Implement subtask [ID]",
  prompt="Implement:
**Subtask:** [description]
**Criteria:** [acceptance_criteria]
**Risk Level:** [risk_level]
**Playbook Context:** [relevant bullets]

Output JSON: {approach, code_changes: [{file_path, change_type, content, rationale}], trade_offs, testing_approach, used_bullets}

Provide FULL file content for each change."
)
```

### 2.4 Monitor (with Contract Validation)

```
Task(
  subagent_type="monitor",
  description="Validate implementation",
  prompt="Review:
**Actor Output:** [actor output]
**Validation Contracts:** [validation_criteria from task-decomposer]

Check: correctness, security, standards, tests.
Flag high_risk_detected if: security issues, breaking changes, >3 files.

**Contract Validation**: Verify each validation_criterion as testable contract.

Output JSON: {valid, issues, verdict, feedback, high_risk_detected,
  contract_compliance: {total_contracts, passed, failed, details[]},
  contract_compliant: boolean}"
)
```

### 2.5 Retry Loop

If `valid === false`: provide feedback, retry Actor (max 5 iterations).

### 2.6 Conditional Predictor

**Call if:** `risk_level ∈ {high, medium}` OR `high_risk_detected === true`

```
Task(
  subagent_type="predictor",
  description="Analyze impact",
  prompt="Analyze:
**Actor Output:** [actor output]
**Risk Trigger:** [reason]

Output JSON: {affected_files, breaking_changes, required_updates, risk_level, rollback_plan}"
)
```

### 2.7 Apply Changes

Apply via Write/Edit tools. Proceed to next subtask.

---

## Step 3: Summary

- Run tests if applicable
- Create commit
- Report: features implemented, files changed

**Optional:** Run `/map-learn [summary]` to preserve valuable patterns for future workflows.

Begin now with efficient workflow.
