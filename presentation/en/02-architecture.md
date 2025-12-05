# MAP Framework Architecture

## Overview

MAP Framework is built around **8 specialized agents**, coordinated by the Orchestrator.

The **Orchestrator** is NOT an agent template. Workflow coordination logic lives in the slash commands `.claude/commands/map-*.md` (map-feature, map-debug, map-refactor, map-review).

## System Components

### 1. TaskDecomposer (1,169 lines)

**Model:** sonnet
**Purpose:** Translates high-level goals into atomic, testable subtasks with explicit dependencies

**MCP integrations (4 tools):**

- `cipher_memory_search` — find similar decompositions from the past
- `sequential-thinking` — iterative clarification of complex requirements
- `context7__get-library-docs` — understand library-specific implementation order
- `deepwiki__read_wiki_structure + ask_question` — study architectural precedents

**Output:** JSON with subtasks, acceptance_criteria, estimated_complexity, depends_on

### 2. Actor (641 lines)

**Model:** sonnet
**Purpose:** Senior software engineer; writes clean, efficient, production-ready code

**MCP integrations (4 tools):**

- `cipher_memory_search` — retrieve existing patterns (ALWAYS FIRST)
- `context7__resolve-library-id + get-library-docs` — up-to-date library docs
- `deepwiki__read_wiki_structure + read_wiki_contents` — learn from production code
- `cipher__extract_and_operate_memory` — save successful patterns (ONLY AFTER Monitor approval)

**Critical protocol:** ALWAYS search cipher BEFORE implementation; ONLY save patterns AFTER Monitor approval

**Inputs:** {{playbook_bullets}} (top_k=5), {{plan_context}} (recitation pattern), {{feedback}} (if retry)

### 3. Monitor (908 lines)

**Model:** sonnet
**Purpose:** Meticulous code reviewer (10+ years), catches bugs, vulnerabilities, and standard violations

**MCP integrations (6 tools — most):**

- `claude-reviewer__request_review` — AI baseline review (ALWAYS FIRST for code)
- `cipher_memory_search` — check known issues/anti-patterns
- `sequential-thinking` — analyze complex logic (workflows, race conditions)
- `context7__get-library-docs` — verify library best practices
- `deepwiki__ask_question` — validate security/architecture patterns
- `Fetch` — validate external URLs in docs

**Critical protocol:** request_review FIRST for all code reviews; document which MCP tools were used

**Output:** valid (boolean), issues (severity/category/description), verdict (approved/needs_revision/rejected)

### 4. Predictor (898 lines)

**Model:** haiku (cost-optimized)
**Purpose:** Impact analysis specialist; predicts ripple effects BEFORE implementation

**MCP integrations (3 tools):**

- `cipher_memory_search` — search past breaking changes and migration patterns
- `context7__get-library-docs` — check library version compatibility
- `deepwiki__read_wiki_structure + ask_question` — study migration patterns

**Output:** affected_files, breaking_changes, required_updates, risk_level (low/medium/high), rollback_plan

### 5. Evaluator (843 lines)

**Model:** haiku (cost-optimized)
**Purpose:** Objective quality assessor with data-driven metrics

**MCP integrations (5 tools):**

- `sequential-thinking` — systematic quality analysis (ALWAYS for methodical assessment)
- `claude-reviewer__get_review_history` — consistency with prior implementations
- `cipher_memory_search` — retrieve quality benchmarks and best practices
- `context7__get-library-docs` — verify adherence to library best practices
- `deepwiki__ask_question` — compare against industry-standard metrics

**Critical protocol:** ALWAYS use sequential-thinking for systematic analysis

**Output:** scores (code_quality, test_coverage, documentation, security, performance, maintainability 0–10), overall_score, recommendation

### 6. Reflector (1,004 lines) — ACE Learning

**Model:** sonnet
**Purpose:** Expert learning analyst; extracts reusable patterns from implementations

**MCP integrations (4 tools):**

- `sequential-thinking` — deep root-cause analysis for complex failures
- `cipher_memory_search` — check similar past patterns (MANDATORY before proposing new bullets)
- `context7__resolve-library-id + get-library-docs` — verify library API usage patterns
- `deepwiki__read_wiki_structure + ask_question` — learn from production systems

**Critical protocol:**

- MANDATORY: cipher_memory_search BEFORE extracting patterns (prevents duplicates)
- map-feature.md lines 263–273 enforce cipher search verification
- Extract patterns, not solutions (focus on “why”, not “what”)

**Output:** key_insight, patterns_used, patterns_discovered, bullet_updates (helpful/harmful count), suggested_new_bullets

### 7. Curator (1,145 lines) — ACE Learning

**Model:** sonnet
**Purpose:** Knowledge curator; evolves the playbook without context collapse

**MCP integrations (4 tools):**

- `cipher_memory_search` — check cross-project duplicates BEFORE ADD operations (MANDATORY)
- `context7__resolve-library-id + get-library-docs` — verify current API syntax
- `deepwiki__read_wiki_structure + ask_question` — ground advice in battle-tested code
- `cipher__extract_and_operate_memory` — sync high-quality bullets (helpful_count >= 5) to cipher

**Critical protocol:**

- MANDATORY: Search cipher for duplicates before ADD
- MANDATORY: Sync bullets with helpful_count >= 5 to cipher
- map-feature.md lines 309–355 enforce cipher integration
- Quality > quantity: a playbook with 50 high-quality bullets > 500 generic
- Only delta ops (ADD/UPDATE/DEPRECATE), never full overwrite

**Output:** operations (ADD/UPDATE/DEPRECATE), deduplication_check, sync_to_cipher

### 8. DocumentationReviewer

**Model:** sonnet
**Purpose:** Technical documentation expert; catches missing requirements and integration gaps

**MCP integrations (4 tools):**

- `Fetch` — MANDATORY: verify EVERY external URL in docs
- `deepwiki__ask_question` — get architecture details from external projects
- `context7__resolve_library_id + get-library-docs` — verify API/integration details
- `cipher_memory_search` — check known documentation anti-patterns

**Critical constraints (NEVER violate):**

- ALWAYS read the source document (tech-design.md) FIRST before reviewing a decomposition
- ALWAYS verify external URLs via Fetch
- ALWAYS verify CRD ownership and installation responsibility explicitly
- NEVER accept vague responsibility statements
- ALWAYS cite exact line numbers for inconsistencies

**Review Workflow:** Read source → Extract URLs → Fetch URLs → Check CRDs/dependencies → Verify documentation → Cross-check decomposition

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
9. Sync to cipher if helpful_count >= 5
```

### Critical Rules Enforcement

**MANDATORY agent invocation:**

- NEVER skip Reflector: `cipher_memory_search` runs ONLY when the agent is properly invoked
- NEVER skip Curator: playbook-to-cipher sync happens ONLY through the Curator template
- ALWAYS verify MCP tool usage in agent outputs
- Manual extraction/curation bypasses MCP tools → knowledge won’t deduplicate → lessons won’t be learned

**Enforcement source:** `.claude/commands/map-feature.md` lines 263–355 + MAP workflow enforcement rules

### Template Structure

**All agents use:**

- YAML frontmatter: name, description, model (sonnet/haiku), version 2.2.0
- Handlebars variables: {{project_name}}, {{language}}, {{framework}}, {{subtask_description}}, {{playbook_bullets}}, {{feedback}}
- Standard sections: IDENTITY, context, mcp_integration, rationale, critical/constraints, examples, output_format

<!-- TestGenerator removed from presentation scope per request -->

### Model Strategy

- **haiku** (cost-optimized): Predictor, Evaluator
- **sonnet** (quality-critical): Actor, Monitor, TaskDecomposer, Reflector, Curator, DocumentationReviewer
