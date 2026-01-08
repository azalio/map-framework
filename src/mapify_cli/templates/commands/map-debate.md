---
description: Debate-based MAP workflow with Opus arbiter for multi-variant synthesis
---

# MAP Debate Workflow

## Execution Rules

1. Execute steps in order without pausing; only ask user if (a) `task-decomposer` returns blocking `analysis.open_questions` with no subtasks OR (b) Monitor sets `escalation_required === true`
2. Use exact `subagent_type` specified — never substitute `general-purpose`
3. Call each agent individually — no combining or skipping steps
4. Max 5 Actor→Monitor retry iterations per subtask (separate from debate-arbiter retries in 2.7)
5. **ALWAYS generate 3 variants** — no conditional check (unlike map-efficient Self-MoA)
6. Use **debate-arbiter with model=opus** for synthesis

**Task:** $ARGUMENTS

## Workflow Overview

```
1. DECOMPOSE → task-decomposer
2. FOR each subtask:
   a. CONTEXT → playbook query + cipher search
   b. RESEARCH → if existing code understanding needed
   c. 3 Actors (parallel) → security/performance/simplicity focuses
   d. 3 Monitors (parallel) → validate + extract decisions
   e. debate-arbiter (opus) → cross-evaluate + synthesize
   f. Final Monitor → validate synthesis
   g. If invalid: retry with feedback (max 5)
   h. If risk_level ∈ {high, medium}: → Predictor
   i. Apply changes
3. SUMMARY → optionally suggest /map-learn
```

## Step 1: Task Decomposition

```
Task(
  subagent_type="task-decomposer",
  description="Decompose task into subtasks",
  prompt="Break down into ≤8 atomic subtasks and RETURN ONLY JSON matching task-decomposer schema v2.0 (schema_version, analysis, blueprint{subtasks[]}).

Task: $ARGUMENTS

Hard requirements:
- Use `blueprint.subtasks[].validation_criteria` (2-4 testable, verifiable outcomes)
- Use `blueprint.subtasks[].dependencies` (array of subtask IDs) and order subtasks by dependency
- Include `blueprint.subtasks[].complexity_score` (1-10) and `risk_level` (low|medium|high)
- Include `blueprint.subtasks[].security_critical` (true for auth/crypto/validation/data access)
- Include `blueprint.subtasks[].test_strategy` with unit/integration/e2e keys"
)
```

## Step 2: Subtask Loop

### 2.0 Build AI-Friendly Subtask Packet (XML Anchors)

Before calling any agents for the subtask, build a single **AI Packet** with unique XML-like tags (NO attributes).

**Rule:** Use the subtask ID as the anchor name. Convert `-` to `_` for XML tag safety:
- `ST-001` → `ST_001`

**AI Packet template:**

```xml
<SUBTASK_ST_001>
  <SUBTASK_ST_001__ID>ST-001</SUBTASK_ST_001__ID>
  <SUBTASK_ST_001__TITLE>...</SUBTASK_ST_001__TITLE>
  <SUBTASK_ST_001__DESCRIPTION>...</SUBTASK_ST_001__DESCRIPTION>
  <SUBTASK_ST_001__RISK_LEVEL>low|medium|high</SUBTASK_ST_001__RISK_LEVEL>
  <SUBTASK_ST_001__SECURITY_CRITICAL>true|false</SUBTASK_ST_001__SECURITY_CRITICAL>
  <SUBTASK_ST_001__COMPLEXITY_SCORE>1-10</SUBTASK_ST_001__COMPLEXITY_SCORE>

  <SUBTASK_ST_001__AFFECTED_FILES>path1;path2;...</SUBTASK_ST_001__AFFECTED_FILES>
  <SUBTASK_ST_001__VALIDATION_CRITERIA>...</SUBTASK_ST_001__VALIDATION_CRITERIA>
  <SUBTASK_ST_001__CONTRACTS>...</SUBTASK_ST_001__CONTRACTS>
  <SUBTASK_ST_001__TEST_STRATEGY>...</SUBTASK_ST_001__TEST_STRATEGY>

  <SUBTASK_ST_001__CONTEXT_PATTERNS>...</SUBTASK_ST_001__CONTEXT_PATTERNS>
  <SUBTASK_ST_001__RESEARCH_SUMMARY>...</SUBTASK_ST_001__RESEARCH_SUMMARY>
</SUBTASK_ST_001>
```

Pass this packet verbatim to Actor/Monitor/debate-arbiter/Predictor. Do NOT rename tags mid-flow.

### 2.1 Get Context + Re-rank

```bash
# Query playbook (project-specific patterns)
mapify playbook query "[subtask description]" --limit 5

# Cross-project patterns
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

### 2.2 Research (Conditional)

**Call if:** refactoring, bug fixes, extending existing code, touching 3+ files
**Skip for:** new standalone features, docs, config

```
Task(
  subagent_type="research-agent",
  description="Research for subtask [ID]",
  prompt="Query: [subtask description]
File patterns: [relevant globs]
Symbols: [optional keywords]
Intent: locate
Max tokens: 1500"
)
```

Pass `executive_summary` to Actor if `confidence >= 0.7`.

### 2.3 Parallel Actors (3 Variants)

**ALWAYS call 3 Actors in parallel with different focuses:**

```
# Variant 1: Security Focus
Task(
  subagent_type="actor",
  description="Implement subtask [ID] - Security (v1)",
  prompt="Implement with SECURITY focus:
**AI Packet (XML):** [paste <SUBTASK_ST_XXX>...</SUBTASK_ST_XXX>]
**Playbook Context:** [top context_patterns + relevance_score]
approach_focus: security, variant_id: v1, self_moa_mode: true
Follow the Actor agent protocol output format. Ensure `decisions_made` is included for debate-arbiter."
)

# Variant 2: Performance Focus
Task(
  subagent_type="actor",
  description="Implement subtask [ID] - Performance (v2)",
  prompt="Implement with PERFORMANCE focus:
**AI Packet (XML):** [paste <SUBTASK_ST_XXX>...</SUBTASK_ST_XXX>]
**Playbook Context:** [top context_patterns + relevance_score]
approach_focus: performance, variant_id: v2, self_moa_mode: true
Follow the Actor agent protocol output format. Ensure `decisions_made` is included for debate-arbiter."
)

# Variant 3: Simplicity Focus
Task(
  subagent_type="actor",
  description="Implement subtask [ID] - Simplicity (v3)",
  prompt="Implement with SIMPLICITY focus:
**AI Packet (XML):** [paste <SUBTASK_ST_XXX>...</SUBTASK_ST_XXX>]
**Playbook Context:** [top context_patterns + relevance_score]
approach_focus: simplicity, variant_id: v3, self_moa_mode: true
Follow the Actor agent protocol output format. Ensure `decisions_made` is included for debate-arbiter."
)
```

### 2.4 Parallel Monitors (3 Validations)

Validate each variant in parallel:

```
Task(
  subagent_type="monitor",
  description="Validate v1",
  prompt="Review variant v1 against requirements:
**AI Packet (XML):** [paste <SUBTASK_ST_XXX>...</SUBTASK_ST_XXX>]
**Proposed Solution:** [paste v1 Actor output]
**Specification Contract (optional):** [SpecificationContract JSON or null]
variant_id: v1, self_moa_mode: true

Return ONLY valid JSON following MonitorReviewOutput schema.
When in Self-MoA mode, include extension fields: variant_id, self_moa_mode, decisions_identified, compatibility_features, strengths, weaknesses, recommended_as_base.
If `validation_criteria` present: include `contract_compliance` + `contract_compliant`.
If a SpecificationContract is provided: include `spec_contract_compliant` + `spec_contract_violations`."
)
```

Repeat for v2 and v3 in parallel.

### 2.5 debate-arbiter (Opus)

```
Task(
  subagent_type="debate-arbiter",
  model="opus",
  description="Cross-evaluate and synthesize best implementation",
  prompt="Cross-evaluate 3 variants and synthesize optimal solution:

**AI Packet (XML):** [paste <SUBTASK_ST_XXX>...</SUBTASK_ST_XXX>]
**Variants (raw Actor outputs):**
<ACTOR_V1_ST_XXX>
[paste v1 Actor output]
</ACTOR_V1_ST_XXX>
<ACTOR_V2_ST_XXX>
[paste v2 Actor output]
</ACTOR_V2_ST_XXX>
<ACTOR_V3_ST_XXX>
[paste v3 Actor output]
</ACTOR_V3_ST_XXX>
**Monitor Results (MonitorReviewOutput JSON):**
<MONITOR_V1_ST_XXX>
[paste v1 Monitor output JSON]
</MONITOR_V1_ST_XXX>
<MONITOR_V2_ST_XXX>
[paste v2 Monitor output JSON]
</MONITOR_V2_ST_XXX>
<MONITOR_V3_ST_XXX>
[paste v3 Monitor output JSON]
</MONITOR_V3_ST_XXX>
**Specification Contract (optional):** [SpecificationContract JSON or null]
**Priority Policy:** [\"correctness\", \"security\", \"maintainability\", \"performance\"]
**Evaluation Dimensions:** [\"security\", \"performance\", \"readability\", \"maintainability\"]

Return ONLY valid JSON following ArbiterOutput schema.
Include: comparison_matrix, decision_rationales, synthesis_reasoning (8 steps)."
)
```

### 2.6 Final Monitor

Validate synthesized code:

```
Task(
  subagent_type="monitor",
  description="Validate synthesized implementation",
  prompt="Review synthesized code from debate-arbiter:
**AI Packet (XML):** [paste <SUBTASK_ST_XXX>...</SUBTASK_ST_XXX>]
**Proposed Solution:** [paste debate-arbiter code output]
**Arbiter Confidence:** [confidence from debate-arbiter]

Check: correctness, security, standards, decision implementation.
Return ONLY valid JSON following MonitorReviewOutput schema."
)
```

### 2.7 Retry Loop

If Final Monitor returns `valid === false`:
1. Provide feedback including arbiter's synthesis_reasoning
2. Retry debate-arbiter with retry_context
3. Max 2 debate-arbiter retries per subtask

```python
retry_context = {
    "attempt": retry_count + 1,
    "previous_errors": monitor_issues,
    "failed_decisions": [decisions_causing_issues],
    "strategy_adjustments": ["avoid decision X", "prefer fresh_generation"]
}
```

### 2.8 Escalation Gate (AskUserQuestion)

If Monitor returns `escalation_required === true`, ask user:

```
AskUserQuestion(
  questions: [
    {
      header: "Escalation Required",
      question: "⚠️ Human review requested by Monitor.\n\nSubtask: [ST-XXX]\nReason: [escalation_reason]\nArbiter Confidence: [confidence]\n\nProceed anyway?",
      multiSelect: false,
      options: [
        { label: "YES - Proceed Anyway", description: "Continue (run Predictor if required, then apply changes)." },
        { label: "REVIEW - Show Details", description: "Show synthesis_reasoning + comparison_matrix, then ask again." },
        { label: "NO - Abort Subtask", description: "Do not apply changes; wait for human review." }
      ]
    }
  ]
)
```

### 2.9 Conditional Predictor

**Call if:** `risk_level ∈ {high, medium}` OR `escalation_required === true`

```
Task(
  subagent_type="predictor",
  description="Analyze impact",
  prompt="Analyze impact using Predictor input schema.

**AI Packet (XML):** [paste <SUBTASK_ST_XXX>...</SUBTASK_ST_XXX>]

Required inputs:
- change_description: [summary from debate-arbiter synthesis_reasoning]
- files_changed: [list of paths from synthesized code]
- diff_content: [unified diff]

Optional inputs:
- analyzer_output: [debate-arbiter output]
- user_context: [subtask requirements + arbiter confidence]

Return ONLY valid JSON following Predictor schema."
)
```

### 2.10 Apply Changes

Apply synthesized code via Write/Edit tools. Proceed to next subtask.

### 2.11 Gate 2: Tests Available / Run

After applying changes, run tests if available.

**Prefer** the commands implied by `<SUBTASK_...__TEST_STRATEGY>`. Otherwise:
- If `pytest` project: run `pytest`
- If `package.json` present: run `npm test` / `pnpm test` / `yarn test`
- If `go.mod` present: run `go test ./...`
- If `Cargo.toml` present: run `cargo test`

If no tests found: mark gate as skipped and proceed.

### 2.12 Gate 3: Formatter / Linter

After tests gate, run formatter/linter checks if available.

Prefer repo-standard commands (e.g., `make lint`, `make fmt`). Otherwise:
- Python: `ruff check`, `black --check`, `mypy`
- JS/TS: `eslint`, `prettier -c`
- Go: `gofmt` check + `golangci-lint run`
- Rust: `cargo fmt --check`, `cargo clippy`

If none found: mark gate as skipped and proceed.

---

## Step 3: Summary

- Run tests if applicable
- Create commit (if requested)
- Report: features implemented, files changed
- Include key synthesis reasoning highlights from debate-arbiter

**Optional:** Run `/map-learn [summary]` to preserve valuable patterns for future workflows.

---

## Key Differences from map-efficient

| Aspect | map-efficient | map-debate |
|--------|---------------|------------|
| Variant generation | Conditional (Self-MoA check) | Always |
| Synthesis agent | synthesizer (sonnet) | debate-arbiter (opus) |
| Output | conflict_resolutions | comparison_matrix + decision_rationales + synthesis_reasoning |
| Cost | Lower | ~3-5x higher (opus model) |
| Use case | Efficiency | Reasoning transparency |

Begin now with debate workflow.
