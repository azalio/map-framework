# MAP Framework Architecture

## Overview

MAP Framework is built around **12 specialized agents**, coordinated by the Orchestrator.

The **Orchestrator** is NOT an agent template. Workflow coordination logic lives in the slash commands `.claude/commands/map-*.md` (map-efficient, map-debug, map-fast, map-debate, map-review, map-check, map-plan, map-release, map-resume, map-learn).

## System Components

### 1. TaskDecomposer (867 lines)

**Model:** sonnet
**Purpose:** Translates high-level goals into atomic, testable subtasks with explicit dependencies

**MCP integrations (4 tools):**

- `mcp__mem0__map_tiered_search` — find similar decompositions from the past
- `sequential-thinking` — iterative clarification of complex requirements
- `context7__get-library-docs` — understand library-specific implementation order
- `deepwiki__read_wiki_structure + ask_question` — study architectural precedents

**Output:** JSON with subtasks, acceptance_criteria, estimated_complexity, depends_on

### 2. Actor (1,084 lines)

**Model:** sonnet
**Purpose:** Senior software engineer; writes clean, efficient, production-ready code

**MCP integrations (3 tools):**

- `mcp__mem0__map_tiered_search` — retrieve existing patterns (ALWAYS FIRST)
- `context7__resolve-library-id + get-library-docs` — up-to-date library docs
- `deepwiki__read_wiki_structure + read_wiki_contents` — learn from production code

**Critical protocol:** ALWAYS search for existing patterns BEFORE implementation; ONLY save patterns AFTER Monitor approval

**Inputs:** {{existing_patterns}} (top_k=5), {{plan_context}} (recitation pattern), {{feedback}} (if retry)

### 3. Monitor (2,521 lines)

**Model:** sonnet
**Purpose:** Meticulous code reviewer (10+ years), catches bugs, vulnerabilities, and standard violations

**MCP integrations (6 tools — most):**

- `claude-reviewer__request_review` — AI baseline review (ALWAYS FIRST for code)
- `mcp__mem0__map_tiered_search` — check known issues/anti-patterns
- `sequential-thinking` — analyze complex logic (workflows, race conditions)
- `context7__get-library-docs` — verify library best practices
- `deepwiki__ask_question` — validate security/architecture patterns
- `Fetch` — validate external URLs in docs

**Critical protocol:** request_review FIRST for all code reviews; document which MCP tools were used

**Output:** valid (boolean), issues (severity/category/description), verdict (approved/needs_revision/rejected)

### 4. Predictor (2,108 lines)

**Model:** sonnet
**Purpose:** Impact analysis specialist; predicts ripple effects BEFORE implementation

**MCP integrations (4 tools):**

- `mcp__mem0__map_tiered_search` — search past breaking changes and migration patterns
- `mcp__context7__get-library-docs` — check library version compatibility
- `mcp__deepwiki__read_wiki_structure + ask_question` — study migration patterns
- `mcp__sequential-thinking__sequentialthinking` — complex trade-off analysis for multi-system impact

**Output:** affected_files, breaking_changes, required_updates, risk_level (low/medium/high), rollback_plan

### 5. Evaluator (1,492 lines)

**Model:** sonnet
**Purpose:** Objective quality assessor with data-driven metrics

**MCP integrations (5 tools):**

- `sequential-thinking` — systematic quality analysis (ALWAYS for methodical assessment)
- `claude-reviewer__get_review_history` — consistency with prior implementations
- `mcp__mem0__map_tiered_search` — retrieve quality benchmarks and best practices
- `context7__get-library-docs` — verify adherence to library best practices
- `deepwiki__ask_question` — compare against industry-standard metrics

**Critical protocol:** ALWAYS use sequential-thinking for systematic analysis

**Output:** scores (code_quality, test_coverage, documentation, security, performance, maintainability 0–10), overall_score, recommendation

### 6. Reflector (851 lines) — ACE Learning

**Model:** sonnet
**Purpose:** Expert learning analyst; extracts reusable patterns from implementations

**MCP integrations (4 tools):**

- `sequential-thinking` — deep root-cause analysis for complex failures
- `mcp__mem0__map_tiered_search` — check similar past patterns (MANDATORY before proposing new bullets)
- `context7__resolve-library-id + get-library-docs` — verify library API usage patterns
- `deepwiki__read_wiki_structure + ask_question` — learn from production systems

**Critical protocol:**

- MANDATORY: mcp__mem0__map_tiered_search BEFORE extracting patterns (prevents duplicates)
- Extract patterns, not solutions (focus on "why", not "what")

**Output:** key_insight, patterns_used, patterns_discovered, bullet_updates (helpful/harmful count), suggested_new_bullets

### 7. Curator (1,296 lines) — ACE Learning

**Model:** sonnet
**Purpose:** Knowledge curator; evolves the playbook without context collapse

**MCP integrations (3 tools):**

- `mcp__mem0__map_tiered_search` — check cross-project duplicates BEFORE ADD operations (MANDATORY)
- `context7__resolve-library-id + get-library-docs` — verify current API syntax
- `deepwiki__read_wiki_structure + ask_question` — ground advice in battle-tested code

**Critical protocol:**

- MANDATORY: Search for duplicates before ADD
- Quality > quantity: a playbook with 50 high-quality bullets > 500 generic
- Only delta ops (ADD/UPDATE/DEPRECATE), never full overwrite

**Output:** operations (ADD/UPDATE/DEPRECATE), deduplication_check

### 8. DocumentationReviewer

**Model:** sonnet
**Purpose:** Technical documentation expert; catches missing requirements and integration gaps

**MCP integrations (4 tools):**

- `Fetch` — MANDATORY: verify EVERY external URL in docs
- `deepwiki__ask_question` — get architecture details from external projects
- `context7__resolve-library-id + get-library-docs` — verify API/integration details
- `mcp__mem0__map_tiered_search` — check known documentation anti-patterns

**Critical constraints (NEVER violate):**

- ALWAYS read the source document (tech-design.md) FIRST before reviewing a decomposition
- ALWAYS verify external URLs via Fetch
- ALWAYS verify CRD ownership and installation responsibility explicitly
- NEVER accept vague responsibility statements
- ALWAYS cite exact line numbers for inconsistencies

**Review Workflow:** Read source → Extract URLs → Fetch URLs → Check CRDs/dependencies → Verify documentation → Cross-check decomposition

### 9. Synthesizer

**Model:** sonnet
**Purpose:** Merges multiple Actor variants into a unified solution (Self-MoA in /map-efficient)

**Output:** Synthesized code combining best elements from all validated variants

### 10. DebateArbiter

**Model:** opus (highest reasoning quality)
**Purpose:** Cross-evaluates Actor variants with explicit reasoning matrix; synthesizes optimal solution in /map-debate

**Output:** comparison_matrix, decision_rationales, synthesized code

### 11. ResearchAgent

**Model:** inherit (uses parent context model)
**Purpose:** Heavy codebase reading with compressed output; prevents Actor context bloat

**Output:** Executive summary (<2K tokens) with file locations, patterns, and confidence score

### 12. FinalVerifier

**Model:** sonnet
**Purpose:** Adversarial verifier (Four-Eyes Principle); catches premature completion and hallucinated success

**Output:** verdict (PASS/FAIL), confidence score, root cause analysis if failed

## Agent Interactions

### Orchestrator Workflow (Automated sequence)

**For EACH subtask:**

```bash
1. Actor          → Implementation
2. Monitor        → Validation
   IF invalid: feedback to Actor (max 3–5 iterations), goto 1
3. Predictor      → Impact analysis
4. Evaluator      → Quality scoring
   IF not approved: feedback to Actor, goto 1
5. ACCEPT changes → Apply to files
6. Reflector      → Extract lessons (MANDATORY)
7. Curator        → Update playbook (MANDATORY)
8. Apply Curator delta operations
```

### Critical Rules Enforcement

**MANDATORY agent invocation:**

- NEVER skip Reflector: `mcp__mem0__map_tiered_search` runs ONLY when the agent is properly invoked
- NEVER skip Curator: playbook updates happen ONLY through the Curator template
- ALWAYS verify MCP tool usage in agent outputs
- Manual extraction/curation bypasses MCP tools → knowledge won't deduplicate → lessons won't be learned

**Enforcement source:** `.claude/commands/map-efficient.md` + MAP workflow enforcement rules

### Template Structure

**All agents use:**

- YAML frontmatter: name, description, model (sonnet/opus), version, last_updated
- Handlebars variables: {{project_name}}, {{language}}, {{framework}}, {{subtask_description}}, {{existing_patterns}}, {{feedback}}
- Standard sections: IDENTITY, context, mcp_integration, rationale, critical/constraints, examples, output_format

<!-- TestGenerator removed from presentation scope per request -->

### Model Strategy

- **sonnet** (quality-critical): Actor, Monitor, TaskDecomposer, Predictor, Evaluator, Reflector, Curator, DocumentationReviewer, Synthesizer, FinalVerifier
- **opus** (highest reasoning): DebateArbiter
- **inherit** (parent context): ResearchAgent
