---
description: Token-efficient MAP workflow with conditional optimizations
---

# MAP Efficient Workflow

## Execution Rules

1. Execute steps in order without pausing; only ask user if (a) `task-decomposer` returns blocking `analysis.open_questions` with no subtasks OR (b) Monitor sets `escalation_required === true` (sub-steps explicitly marked "parallel" may run concurrently)
2. Use exact `subagent_type` specified — never substitute `general-purpose`
3. Call each agent individually — no combining or skipping steps
4. Max 5 retry iterations per subtask

**Task:** $ARGUMENTS

## Workflow Overview

```
1. DECOMPOSE → task-decomposer
2. FOR each subtask:
   a. CONTEXT → playbook query (Actor will run `cipher_memory_search` per protocol; orchestrator MAY run extra cipher search to augment context)
   b. RESEARCH → if existing code understanding needed
   c. IF Self-MoA (--self-moa OR risk_level:high OR complexity_score>=7 OR security_critical:true):
      → 3 Actors (security/performance/simplicity)
      → 3 Monitors → Synthesizer → Final Monitor
   ELSE:
      → Actor → Monitor
   d. If invalid: retry with feedback (max 5)
   e. If risk_level ∈ {high, medium} OR escalation_required === true: → Predictor
   f. Apply changes
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

Pass this packet verbatim to Actor/Monitor/Predictor/Synthesizer. Do NOT rename tags mid-flow.

### 2.1 Get Context + Re-rank

```bash
# Query playbook (project-specific patterns)
mapify playbook query "[subtask description]" --limit 5

# Optional: cross-project patterns (Actor still runs its own `cipher_memory_search` per Actor protocol)
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
Symbols: [optional keywords]
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
    subtask.security_critical == true OR
    subtask.complexity_score >= 7
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
**AI Packet (XML):** [paste <SUBTASK_ST_XXX>...</SUBTASK_ST_XXX>]
**Playbook Context:** [top context_patterns + relevance_score]
approach_focus: security, variant_id: v1, self_moa_mode: true
Follow the Actor agent protocol output format. Ensure `decisions_made` is included for Synthesizer."
)

# Variant 2: Performance Focus
Task(
  subagent_type="actor",
  description="Implement subtask [ID] - Performance (v2)",
  prompt="Implement with PERFORMANCE focus:
**AI Packet (XML):** [paste <SUBTASK_ST_XXX>...</SUBTASK_ST_XXX>]
**Playbook Context:** [top context_patterns + relevance_score]
approach_focus: performance, variant_id: v2, self_moa_mode: true
Follow the Actor agent protocol output format. Ensure `decisions_made` is included for Synthesizer."
)

# Variant 3: Simplicity Focus
Task(
  subagent_type="actor",
  description="Implement subtask [ID] - Simplicity (v3)",
  prompt="Implement with SIMPLICITY focus:
**AI Packet (XML):** [paste <SUBTASK_ST_XXX>...</SUBTASK_ST_XXX>]
**Playbook Context:** [top context_patterns + relevance_score]
approach_focus: simplicity, variant_id: v3, self_moa_mode: true
Follow the Actor agent protocol output format. Ensure `decisions_made` is included for Synthesizer."
)
```

### 2.3b Parallel Monitors

Validate each variant:

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

### 2.3c Synthesizer

```
Task(
  subagent_type="synthesizer",
  description="Synthesize best implementation",
  prompt="Combine best parts from v1, v2, v3:

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

Return ONLY valid JSON following SynthesizerOutput schema."
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
**AI Packet (XML):** [paste <SUBTASK_ST_XXX>...</SUBTASK_ST_XXX>]
**Risk Level:** [risk_level]
**Playbook Context:** [top context_patterns + relevance_score]

Follow the Actor agent protocol output format."
)
```

### 2.4 Monitor (with Contract Validation)

```
Task(
  subagent_type="monitor",
  description="Validate implementation",
  prompt="Review against requirements:
**AI Packet (XML):** [paste <SUBTASK_ST_XXX>...</SUBTASK_ST_XXX>]
**Proposed Solution:** [paste Actor output]
**Specification Contract (optional):** [SpecificationContract JSON or null]

Check: correctness, security, standards, tests.
If human review is required, set `escalation_required` + `escalation_reason` (per Monitor escalation protocol).

**Contract Validation**: Verify each validation_criterion as testable contract.

Return ONLY valid JSON following MonitorReviewOutput schema.
If validation_criteria present, include contract_compliance + contract_compliant fields."
)
```

### 2.5 Retry Loop

If `valid === false`: provide feedback, retry Actor (max 5 iterations).

### 2.5b Escalation Gate (AskUserQuestion)

If Monitor returns `escalation_required === true`, you MUST ask user for confirmation before proceeding (Predictor and/or Apply).

```
AskUserQuestion(
  questions: [
    {
      header: "Escalation Required",
      question: "⚠️ Human review requested by Monitor.\n\nSubtask: [ST-XXX]\nReason: [escalation_reason]\n\nProceed anyway?",
      multiSelect: false,
      options: [
        { label: "YES - Proceed Anyway", description: "Continue (run Predictor if required, then apply changes)." },
        { label: "REVIEW - Show Details", description: "Show Actor output + Monitor JSON + affected files, then ask again." },
        { label: "NO - Abort Subtask", description: "Do not apply changes; wait for human review." }
      ]
    }
  ]
)
```

### 2.6 Conditional Predictor

**Call if:** `risk_level ∈ {high, medium}` OR `escalation_required === true`

```
Task(
  subagent_type="predictor",
  description="Analyze impact",
  prompt="Analyze impact using Predictor input schema.

**AI Packet (XML):** [paste <SUBTASK_ST_XXX>...</SUBTASK_ST_XXX>]

Required inputs:
- change_description: [1-3 sentence summary of what the Actor change does]
- files_changed: [list of paths inferred from Actor output OR actual modified files]
- diff_content: [unified diff; if not available pre-apply, provide best-effort diff derived from proposed changes, and cap confidence]

Optional inputs:
- analyzer_output: [Actor output]
- user_context: [subtask requirements + risk trigger]

Return ONLY valid JSON following Predictor schema."
)
```

### 2.7 Apply Changes

Apply via Write/Edit tools. Proceed to next subtask.

### 2.8 Gate 2: Tests Available / Run

After applying changes for a subtask, run tests if available (do NOT install dependencies during this gate).

**Prefer** the commands implied by `<SUBTASK_...__TEST_STRATEGY>`. Otherwise:
- If `pytest` project: run `pytest` (or targeted tests if known)
- If `package.json` present: run `npm test` / `pnpm test` / `yarn test` (whichever is used in repo)
- If `go.mod` present: run `go test ./...`
- If `Cargo.toml` present: run `cargo test`

If no tests found: mark gate as skipped and proceed.

### 2.9 Gate 3: Formatter / Linter

After tests gate, run formatter/linter checks if available (do NOT install dependencies during this gate).

Prefer repo-standard commands first (e.g., `make lint`, `make fmt`, `make check`). Otherwise:
- Python: `ruff check`, `black --check`, `mypy` (if configured)
- JS/TS: `eslint`, `prettier -c` (if configured)
- Go: `gofmt` check + `golangci-lint run` (if configured)
- Rust: `cargo fmt --check`, `cargo clippy`

If none found: mark gate as skipped and proceed.

---

## Step 3: Summary

- Run tests if applicable
- Create commit (if requested)
- Report: features implemented, files changed

**Optional:** Run `/map-learn [summary]` to preserve valuable patterns for future workflows.

Begin now with efficient workflow.
