# MAP Framework Architecture

Deep technical documentation for MAP (Modular Agentic Planner) implementation.

> **Research Foundation:** [Nature Communications research (2025)](https://github.com/Shanka123/MAP) — 74% improvement in planning tasks
> **Learning System:** [ACE (Agentic Context Engineering)](https://arxiv.org/abs/2510.04618v1) — continuous learning from experience

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Agent Specifications](#agent-specifications)
- [MCP Integration](#mcp-integration)
- [Customization Guide](#customization-guide)
- [Template Maintenance](#template-maintenance)
- [Context Engineering](#context-engineering)

---

## Architecture Overview

### High-Level Design

MAP Framework implements cognitive architecture inspired by prefrontal cortex functions, orchestrating 8 specialized agents for software development with automatic quality validation.

```
┌──────────────────────────────────────────┐
│       SLASH COMMANDS                     │
│   /map-feature /map-debug /map-refactor │
│   (orchestrate workflow via prompts)    │
└───────────────┬──────────────────────────┘
                │
    ┌───────────▼────────────┐
    │   TASK DECOMPOSER      │
    │   (breaks into tasks)   │
    └───────────┬────────────┘
                │
    ┌───────────▼─────────────────────┐
    │   For each subtask:             │
    │                                  │
    │  ┌──────────────────────┐       │
    │  │  ACTOR ←→ MONITOR    │       │
    │  │  (code ←→ validate)  │       │
    │  └──────────┬───────────┘       │
    │             │                    │
    │  ┌──────────▼───────────┐       │
    │  │ PREDICTOR→EVALUATOR  │       │
    │  │ (impact → quality)   │       │
    │  └──────────┬───────────┘       │
    │             │                    │
    │  ┌──────────▼───────────┐       │
    │  │ REFLECTOR → CURATOR  │       │
    │  │ (learn → knowledge)  │       │
    │  └──────────────────────┘       │
    └──────────────────────────────────┘
```

### Orchestration Model

**Command-Driven Workflow:**
- Orchestration logic implemented in slash command prompts (`.claude/commands/map-*.md`)
- NOT a separate agent file
- When you run `/map-feature`, the command prompt coordinates the workflow by calling agents sequentially via the Task tool

**Workflow Stages:**

1. **Task Decomposition** (TaskDecomposer)
   - Receives high-level goal
   - Breaks into atomic subtasks
   - Estimates complexity and dependencies
   - Outputs structured task plan

2. **Implementation Loop** (per subtask)
   - **Code Generation** (Actor): Generates solution
   - **Validation** (Monitor): Checks quality, security, correctness
   - **Feedback Loop**: If validation fails, return to Actor with feedback (max 3-5 iterations)

3. **Impact Analysis** (Predictor)
   - Analyzes change ripple effects across codebase
   - Identifies affected components
   - Flags potential breaking changes

4. **Quality Scoring** (Evaluator)
   - Rates solution on multiple dimensions
   - Functionality, security, testability, maintainability
   - Scores 0-10, approval threshold >7.0

5. **Learning Cycle** (Reflector → Curator)
   - Extracts patterns from successes and failures
   - Updates knowledge base (playbook)
   - Enables continuous improvement

### Agent Coordination Protocol

**Sequential Execution:**
- Each agent receives structured input from previous agent
- Agents communicate via JSON output format
- Orchestrator enforces strict agent ordering

**Error Handling:**
- Actor-Monitor feedback loops limited to 3-5 iterations
- Infinite loop detection at orchestrator level
- Graceful degradation if agent fails

**State Management:**
- Current plan stored in `.map/current_plan.md` (Recitation Pattern)
- Workflow logs in `.map/workflow_logs/`
- Metrics tracked in `.claude/metrics/agent_metrics.jsonl`

### Workflow Variants

MAP Framework provides three workflow variants with different agent orchestration strategies:

#### 1. `/map-feature` - Full Pipeline (8 Agents)

**Agent Sequence:** TaskDecomposer → (Actor → Monitor → Predictor → Evaluator → Reflector → Curator) per subtask

**Token Usage:** Baseline (100%)
**Learning:** Per-subtask reflection and curation
**Quality Gates:** All agents (maximum QA)

**Use for:**
- Security-critical features
- First-time complex implementations
- High-risk refactoring
- Maximum quality assurance required

#### 2. `/map-efficient` - Optimized Pipeline (5-6 Agents) ⭐ RECOMMENDED

**Agent Sequence:** TaskDecomposer → (Actor → Monitor → conditional Predictor) per subtask → batch Reflector → batch Curator

**Optimizations:**

1. **Conditional Predictor** (5-10% token savings)
   - Only called if TaskDecomposer assigns `risk_level='high'/'medium'`
   - OR if Monitor sets `high_risk_detected=true`
   - Low-risk subtasks (simple CRUD, UI updates) skip impact analysis

2. **Evaluator Skipped** (8-12% token savings)
   - Monitor provides sufficient validation for most tasks
   - Evaluator's 6-dimension scoring rarely changes proceed/reject decision
   - Quality still ensured by Monitor's comprehensive checks

3. **Batched Learning** (10-15% token savings)
   - Reflector analyzes ALL subtask outputs at end (vs per-subtask)
   - Curator makes single playbook update (vs N updates for N subtasks)
   - More holistic insights (sees patterns across entire workflow)
   - Saves (N-1) × 3K tokens for N subtasks

**Token Usage:** 60-70% of baseline
**Learning:** Batched at end (full Reflector/Curator cycle preserved)
**Quality Gates:** Essential agents (Monitor, conditional Predictor)

**Technical Details:**

```python
# Conditional Predictor Logic (Orchestrator)
for subtask in subtasks:
    actor_output = call_actor(subtask)
    monitor_output = call_monitor(actor_output)

    if monitor_output.valid:
        # Only call Predictor if high risk
        if (subtask.risk_level in ['high', 'medium'] or
            monitor_output.high_risk_detected):
            predictor_output = call_predictor(actor_output)
        # Apply changes
        apply_code_changes(actor_output)

# Batched Learning (after all subtasks)
all_outputs = collect_all_subtask_outputs()
reflector_output = call_reflector(all_outputs)  # Batch analysis
curator_output = call_curator(reflector_output)  # Single update
update_playbook(curator_output)
```

**Use for:**
- Production code where token costs matter (RECOMMENDED)
- Well-understood features (standard CRUD, APIs, UI)
- Iterative development with frequent workflows
- Any task where /map-fast feels too risky but /map-feature too expensive

#### 3. `/map-fast` - Minimal Pipeline (3 Agents) ⚠️

**Agent Sequence:** TaskDecomposer → (Actor → Monitor) per subtask

**Agents SKIPPED:**
- ❌ Predictor (no impact analysis)
- ❌ Evaluator (no quality scoring)
- ❌ Reflector (no lesson extraction)
- ❌ Curator (no playbook updates)

**Token Usage:** 50-60% of baseline
**Learning:** None (defeats MAP's purpose)
**Quality Gates:** Basic only (Monitor validation)

**Architectural Consequences:**
- Playbook remains static (no continuous improvement)
- Cipher knowledge base never grows
- Breaking changes undetected (no Predictor)
- Security/performance issues may slip through (no Evaluator)
- Same mistakes repeated (no Reflector)

**Use ONLY for:**
- Throwaway prototypes
- Quick experiments
- Tutorial/learning contexts
- **NEVER for production code**

#### Token Breakdown by Agent

Typical token consumption per subtask (estimated):

| Agent | Prompt | Output | Total | Notes |
|-------|--------|--------|-------|-------|
| TaskDecomposer | 1.5K | 1K | 2.5K | One-time (not per subtask) |
| Actor | 2K | 3-4K | 5-6K | Largest consumer (full file content) |
| Monitor | 1.5K | 1K | 2.5K | Always included |
| Predictor | 1.5K | 1K | 2.5K | Conditional in /map-efficient |
| Evaluator | 2K | 1K | 3K | Skipped in /map-efficient |
| Reflector | 2K | 1K | 3K | Batched in /map-efficient |
| Curator | 1.5K | 0.5K | 2K | Batched in /map-efficient |

**Per-subtask totals:**
- /map-feature: ~15-20K tokens
- /map-efficient: ~9-12K tokens (40% savings)
- /map-fast: ~8-10K tokens (50% savings)

**For 5-subtask workflow:**
- /map-feature: ~75-100K tokens
- /map-efficient: ~45-60K tokens (batched learning saves (5-1)×5K = 20K additional)
- /map-fast: ~40-50K tokens (but no learning)

#### Workflow Variant Selection

See [USAGE.md - Workflow Variants](./USAGE.md#workflow-variants) for detailed decision guide, real-world examples, and cost analysis.

---

## Agent Specifications

### 1. TaskDecomposer

**Responsibility:** Break high-level goals into atomic, executable subtasks.

**Input:**
```json
{
  "goal": "implement user authentication with JWT tokens",
  "context": {
    "language": "Python",
    "framework": "Flask",
    "existing_files": ["app.py", "models.py"]
  }
}
```

**Output:**
```json
{
  "subtasks": [
    {
      "id": "auth_001",
      "description": "Create User model with password hashing",
      "estimated_complexity": "medium",
      "dependencies": []
    },
    {
      "id": "auth_002",
      "description": "Implement /login endpoint with JWT generation",
      "estimated_complexity": "high",
      "dependencies": ["auth_001"]
    }
  ]
}
```

**Key Behaviors:**
- Each subtask should be completable in <100 lines of code
- Explicit dependency tracking
- Complexity estimation (low/medium/high)
- Considers existing codebase structure

### 2. Actor

**Responsibility:** Generate code and solutions for subtasks.

**Input:**
```json
{
  "subtask_description": "Implement /login endpoint with JWT generation",
  "language": "Python",
  "framework": "Flask",
  "playbook_bullets": ["impl-0042: Use bcrypt for password hashing"],
  "feedback": "Missing error handling for invalid credentials"
}
```

**Output Structure:**
1. **Approach** (2-3 sentences)
2. **Code Changes** (complete implementations, no ellipsis)
3. **Trade-offs** (alternatives considered, decisions made)
4. **Testing Considerations** (critical test cases)
5. **Used Bullets** (playbook IDs applied)

**Key Behaviors:**
- ALWAYS searches cipher MCP for existing patterns first
- Fetches current docs for external libraries (via context7)
- Explicit error handling required (no silent failures)
- Complete code, not sketches or placeholders
- Security-first approach for auth/data access

**MCP Tool Usage:**
- `cipher_memory_search`: Find existing patterns before implementing
- `context7__get-library-docs`: Get current library documentation
- `codex-bridge__consult_codex`: Complex algorithm generation

### 3. Monitor

**Responsibility:** Validate code quality, security, and correctness.

**Input:** Actor's complete output (approach, code, trade-offs, tests)

**Output:**
```json
{
  "validation_passed": false,
  "issues": [
    {
      "severity": "critical",
      "category": "security",
      "description": "Password not hashed before storage",
      "suggested_fix": "Use bcrypt.hashpw() before db.session.add()"
    }
  ],
  "feedback": "Add password hashing using bcrypt library. Import bcrypt at top of file."
}
```

**Validation Criteria:**
- ✅ Error handling present (no silent failures)
- ✅ Security best practices (OWASP Top 10 compliance)
- ✅ File scope respected (no out-of-scope modifications)
- ✅ Code completeness (no ellipsis/placeholders)
- ✅ Dependency justification (if new deps added)

**Key Behaviors:**
- Uses `claude-reviewer` MCP for professional code review
- Severity classification: critical/major/minor
- Specific, actionable feedback
- Checks against project coding standards

### 4. Predictor

**Responsibility:** Analyze change impact across codebase.

**Input:** Actor's code changes

**Output:**
```json
{
  "impact_analysis": {
    "affected_files": ["app.py", "models.py", "tests/test_auth.py"],
    "breaking_changes": false,
    "risk_level": "medium",
    "ripple_effects": [
      {
        "component": "User API",
        "effect": "New endpoint requires documentation update",
        "action_required": "Update API docs"
      }
    ]
  }
}
```

**Analysis Dimensions:**
- File dependencies (imports, function calls)
- API contract changes
- Database schema modifications
- Configuration requirements
- Test coverage gaps

**Model Used:** Haiku (fast, cost-effective for analysis)

### 5. Evaluator

**Responsibility:** Score solution quality on multiple dimensions.

**Input:** Actor's output + Predictor's impact analysis

**Output:**
```json
{
  "scores": {
    "functionality": 9,
    "security": 8,
    "testability": 7,
    "maintainability": 8,
    "overall": 8.0
  },
  "approved": true,
  "rationale": "Strong implementation with proper error handling. Consider adding integration tests."
}
```

**Scoring Rubric (0-10):**
- **Functionality:** Does it solve the problem completely?
- **Security:** OWASP compliance, input validation, secure defaults
- **Testability:** Can it be easily tested? Clear test cases provided?
- **Maintainability:** Clear code, good naming, documented trade-offs

**Approval Threshold:** >7.0 overall score

**Model Used:** Haiku (fast scoring)

### 6. Reflector

**Responsibility:** Extract lessons from successes and failures.

**Input:** Complete workflow context (Actor, Monitor, Predictor, Evaluator outputs)

**Output:**
```json
{
  "patterns_extracted": [
    {
      "pattern_id": "auth_jwt_001",
      "category": "implementation",
      "content": "Use bcrypt for password hashing with work factor 12",
      "when_to_use": "User authentication with password storage",
      "trade_offs": "Slower than SHA256 but much more secure",
      "code_snippet": "hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt(12))"
    }
  ]
}
```

**Key Behaviors:**
- MUST search cipher MCP for existing patterns first (avoid duplicates)
- Extracts both successful patterns and failure lessons
- Contextualizes lessons (when to apply, when to avoid)
- Links to specific workflow outcomes

**MCP Tool Usage:**
- `cipher_memory_search`: Check for existing similar patterns
- `cipher_extract_reasoning_steps`: Extract reasoning from workflow
- `cipher_evaluate_reasoning`: Assess pattern quality

### 7. Curator

**Responsibility:** Manage knowledge base (playbook) with incremental updates.

**Input:** Reflector's extracted patterns

**Output:**
```json
{
  "operations": [
    {
      "type": "ADD",
      "bullet_id": "impl-0008",
      "content": "Use bcrypt for password hashing with work factor 12",
      "category": "implementation",
      "tags": ["security", "authentication", "passwords"]
    },
    {
      "type": "UPDATE",
      "bullet_id": "impl-0003",
      "content": "Updated JWT signature algorithm from HS256 to RS256",
      "reason": "Security improvement based on recent OWASP guidelines"
    }
  ],
  "sync_to_cipher": [
    {
      "bullet_id": "impl-0008",
      "content": "...",
      "helpful_count": 5
    }
  ]
}
```

**Operations:**
- **ADD:** New pattern not in playbook
- **UPDATE:** Improve existing pattern
- **DEPRECATE:** Mark pattern as outdated
- **NONE:** No changes needed

**Key Behaviors:**
- MUST search cipher MCP for duplicates before adding
- Semantic deduplication (>90% similarity threshold)
- Syncs high-quality patterns (helpful_count >= 5) to cipher
- Incremental updates only (no full rewrites)

**MCP Tool Usage:**
- `cipher_memory_search`: Deduplication check
- `cipher_extract_and_operate_memory`: Store successful patterns

### 8. DocumentationReviewer

**Responsibility:** Check documentation completeness and correctness.

**Input:** Documentation files + related code

**Output:**
```json
{
  "completeness_score": 8,
  "issues": [
    {
      "file": "API.md",
      "issue": "Missing error response format for 401 Unauthorized",
      "suggested_fix": "Add example JSON response for 401 errors"
    }
  ]
}
```

**Validation Criteria:**
- ✅ API endpoints documented with request/response examples
- ✅ Error codes and responses documented
- ✅ Configuration options explained
- ✅ Examples match actual code behavior

---

## MCP Integration

### Overview

MAP uses MCP (Model Context Protocol) servers for enhanced capabilities beyond base Claude Code functionality.

### Available MCP Servers

| MCP Server | Purpose | Required For | Performance Notes |
|------------|---------|--------------|-------------------|
| **cipher** | Knowledge base storage and retrieval | Reflector, Curator, Actor | Low latency (<200ms) |
| **claude-reviewer** | Professional code review | Monitor | Medium latency (~2-5s) |
| **sequential-thinking** | Chain-of-thought reasoning | Complex problem solving | Medium latency (~1-3s) |
| **codex-bridge** | Code generation for algorithms | Actor (complex tasks) | ⚠️ Requires 10-minute timeout |
| **context7** | Up-to-date library documentation | Actor (external libs) | Low latency (<500ms) |
| **deepwiki** | GitHub repository analysis | Research phase | Medium latency (~3-7s) |

### Configuration

MCP servers are configured differently depending on the usage context:

#### Project-Specific Configuration

**File:** `.claude/mcp_config.json`

```json
{
  "mcp_servers": {
    "cipher": {
      "enabled": true,
      "description": "Knowledge management system",
      "config": {
        "auto_store": true,
        "retrieval_limit": 5,
        "similarity_threshold": 0.85
      }
    },
    "claude-reviewer": {
      "enabled": true,
      "description": "Professional code review with security analysis",
      "config": {
        "focus_areas": ["security", "performance", "maintainability"]
      }
    }
  }
}
```

#### Global Configuration

**File:** `mcp_config.json` (project root)

```json
{
  "mcp_servers": {
    "cipher": {
      "enabled": true,
      "description": "Advanced knowledge and reasoning memory system",
      "config": {
        "auto_store": true,
        "retrieval_limit": 5
      }
    }
  }
}
```

### MCP Tool Usage Patterns

#### Pattern 1: Search Before Implement (Actor)

```markdown
**BEFORE implementing any solution:**

1. Search cipher for existing patterns:
   - Query: "implementation pattern [feature_type]"
   - Example: "implementation pattern JWT authentication"

2. If relevant patterns found:
   - Review code snippets and trade-offs
   - Adapt to current context
   - Track which patterns used (bullet IDs)

3. If no patterns found:
   - Proceed with fresh implementation
   - Document new pattern for Reflector
```

#### Pattern 2: Deduplication (Reflector, Curator)

```markdown
**BEFORE adding new patterns:**

1. Reflector searches cipher:
   - Query: Pattern description
   - Threshold: >0.85 similarity

2. If similar pattern exists:
   - Compare quality scores
   - Decide: update existing or create new variant

3. Curator confirms:
   - Final deduplication check
   - Semantic similarity analysis
   - Operation: ADD vs UPDATE vs NONE
```

#### Pattern 3: Current Documentation (Actor)

```markdown
**WHEN using external libraries:**

1. Resolve library ID:
   - Tool: context7__resolve-library-id
   - Input: Library name (e.g., "Flask", "Next.js")

2. Fetch current docs:
   - Tool: context7__get-library-docs
   - Parameters: library_id, topic, tokens (default: 5000)

3. Use docs for:
   - API signature verification
   - Best practices
   - Deprecation warnings
```

#### Pattern 4: Professional Review (Monitor)

```markdown
**AFTER Actor generates code:**

1. Request code review:
   - Tool: claude-reviewer__request_review
   - Parameters: summary, focus_areas, test_command

2. Parse review output:
   - Critical issues → BLOCK
   - Major issues → FEEDBACK to Actor
   - Minor issues → SUGGESTIONS

3. Iterate until approved:
   - Max 3-5 iterations
   - Track iteration count in plan
```

### Configuration Options

#### Cipher Configuration

```json
{
  "cipher": {
    "config": {
      "auto_store": true,              // Auto-save patterns after modifications
      "retrieval_limit": 5,            // Max patterns returned per search
      "similarity_threshold": 0.85,    // Deduplication threshold (0.0-1.0)
      "confidence_threshold": 0.7,     // Minimum confidence for operations
      "useLLMDecisions": false         // Use similarity logic (predictable)
    }
  }
}
```

**Key Parameters:**
- `similarity_threshold`: Higher = stricter deduplication (0.85 recommended)
- `useLLMDecisions`: `false` = predictable similarity-based logic, `true` = LLM-based (less predictable)
- `confidence_threshold`: Minimum confidence score for UPDATE operations

#### Context7 Configuration

```json
{
  "context7": {
    "config": {
      "default_tokens": 5000,          // Default doc size per request
      "cache_duration": 3600           // Cache docs for 1 hour
    }
  }
}
```

#### Claude-Reviewer Configuration

```json
{
  "claude-reviewer": {
    "config": {
      "focus_areas": ["security", "performance", "maintainability"],
      "auto_mark_complete": false      // Require manual completion
    }
  }
}
```

### MCP Server Availability

**Commonly Available:**
- cipher (knowledge base)
- claude-reviewer (code review)
- sequential-thinking (reasoning)

**May Require Installation:**
- codex-bridge (separate installation via `uv tool install`)
- context7 (check Claude Code documentation)
- deepwiki (check Claude Code documentation)

**To verify availability:**
```bash
# Inside Claude Code session
/tools list
```

### Performance Considerations

**Latency Budget (per subtask):**
- cipher searches: ~200ms each (Actor: 2-3 searches = ~600ms)
- context7 docs: ~500ms per fetch (Actor: 1-2 fetches = ~1s)
- claude-reviewer: ~2-5s per review (Monitor: 1 review)
- Total overhead: ~2-7s per subtask

**Optimization Strategies:**
- Cache cipher results (embeddings cache in `.claude/embeddings_cache/`)
- Batch similar searches where possible
- Use `retrieval_limit` to control context size
- Enable MCP caching when available (Phase 2 roadmap)

---

## Customization Guide

### Modifying Agent Prompts

Agent prompts are located in `.claude/agents/*.md` and use **Handlebars template syntax** for dynamic context injection.

#### Safe Modifications

✅ **You CAN modify:**
- Instructions and examples
- MCP tool usage guidance
- Output format specifications
- Domain-specific requirements
- Validation criteria
- Decision frameworks

**Example:**
```markdown
# Add to Monitor agent:

## Additional Security Checks

- OWASP Top 10 compliance required
- All user inputs must be sanitized
- No hardcoded credentials allowed
- SQL queries must use parameterized statements
```

#### Unsafe Modifications

❌ **You CANNOT remove:**
- Template variables: `{{language}}`, `{{project_name}}`, `{{framework}}`
- Conditional blocks: `{{#if playbook_bullets}}...{{/if}}`
- Context sections: `{{subtask_description}}`, `{{feedback}}`
- ACE learning sections: playbook bullets, used_bullets tracking

**Why they're critical:**
- Orchestrator fills these at runtime with project context
- Removing them breaks multi-language support, ACE learning, feedback loops
- Git pre-commit hook validates their presence (see Hooks Integration)

#### Template Variable Reference

**Available in all agents:**
```handlebars
{{project_name}}           # e.g., "my-web-app"
{{language}}               # e.g., "Python", "JavaScript"
{{framework}}              # e.g., "Flask", "Next.js"
{{standards_url}}          # Link to coding standards
```

**Actor-specific:**
```handlebars
{{subtask_description}}    # From TaskDecomposer
{{playbook_bullets}}       # Relevant patterns from Curator
{{#if feedback}}           # Monitor feedback (retry loop)
  {{feedback}}
{{/if}}
{{allowed_scope}}          # Files allowed to modify
```

**Monitor-specific:**
```handlebars
{{#if feedback}}           # Previous iteration feedback
  {{feedback}}
{{/if}}
```

**Reflector-specific:**
```handlebars
{{plan_context}}           # Full workflow context
```

### Model Selection Per Agent

MAP Framework uses intelligent model selection to balance quality and cost.

**Current Configuration:**

| Agent | Model | Rationale |
|-------|-------|-----------|
| Actor | sonnet-4-5 | Quality-critical: code generation |
| Monitor | sonnet-4-5 | Quality-critical: validation |
| Predictor | haiku-3-5 | Fast analysis, non-critical |
| Evaluator | haiku-3-5 | Fast scoring, structured output |
| Reflector | sonnet-4-5 | Quality-critical: pattern extraction |
| Curator | sonnet-4-5 | Quality-critical: knowledge management |

**Override Model Per Agent:**

Edit `.claude/agents/{agent}.md` frontmatter:

```yaml
---
model: claude-sonnet-4-5  # or claude-haiku-3-5
---
```

**Cost vs Quality Trade-offs:**
- **All Sonnet:** Highest quality, 2.5x cost
- **Mixed (current):** Balanced, 40-60% cost reduction
- **All Haiku:** Lowest cost, risk of quality degradation in code generation

**Recommended:** Keep Actor, Monitor, Reflector, Curator on Sonnet. Predictor and Evaluator can safely use Haiku.

### Adding Custom Agents

**Use Case:** Add domain-specific agent (e.g., SecurityAuditor, PerformanceOptimizer)

**Steps:**

1. **Create agent file:**
   ```bash
   touch .claude/agents/security-auditor.md
   ```

2. **Add YAML frontmatter:**
   ```yaml
   ---
   version: 1.0.0
   model: claude-sonnet-4-5
   last_updated: 2025-10-23
   ---
   ```

3. **Define agent role and context:**
   ```markdown
   # IDENTITY
   You are a security auditor specializing in OWASP Top 10 vulnerabilities.

   ## CONTEXT
   - **Project**: {{project_name}}
   - **Language**: {{language}}
   - **Framework**: {{framework}}
   ```

4. **Specify MCP tool usage:**
   ```markdown
   ## MCP INTEGRATION

   **CRITICAL**: ALWAYS use cipher_memory_search before auditing:
   - Query: "security vulnerability [component_type]"
   - Check for past security issues and fixes
   ```

5. **Define output format:**
   ```markdown
   ## OUTPUT FORMAT

   ```json
   {
     "vulnerabilities": [
       {
         "severity": "critical|high|medium|low",
         "owasp_category": "A01:2021 - Broken Access Control",
         "description": "...",
         "suggested_fix": "...",
         "references": ["..."]
       }
     ]
   }
   ```
   ```

6. **Update orchestration:**
   Edit `.claude/commands/map-feature.md` to call new agent:
   ```markdown
   ## After Evaluator approves:

   **6. Security Audit** (SecurityAuditor):
   - Call: Task(subagent_type="security-auditor", input=actor_output)
   - Verify no critical vulnerabilities
   ```

### Adapting to Project Conventions

**Common Customizations:**

1. **Add project-specific coding standards:**
   Edit Actor agent:
   ```markdown
   ## PROJECT STANDARDS

   - Use TypeScript strict mode
   - All functions require JSDoc comments
   - Max function length: 50 lines
   - Prefer functional programming patterns
   ```

2. **Add custom validation rules:**
   Edit Monitor agent:
   ```markdown
   ## CUSTOM VALIDATION

   - [ ] All API endpoints have rate limiting
   - [ ] Database queries use connection pooling
   - [ ] Logs use structured JSON format
   ```

3. **Integrate with CI/CD:**
   Edit Evaluator agent:
   ```markdown
   ## CI/CD INTEGRATION

   **After approval:**
   - Run: `npm run lint`
   - Run: `npm test`
   - Run: `npm run build`
   - Only approve if all checks pass
   ```

### Template Variables in Custom Agents

**Access project context:**
```handlebars
{{project_name}}    # From .claude/config.json
{{language}}        # From .claude/config.json
{{framework}}       # From .claude/config.json
{{standards_url}}   # From .claude/config.json
```

**Pass custom variables:**

In orchestrator prompt:
```markdown
Task(
  subagent_type="security-auditor",
  input={
    "code": actor_output,
    "compliance_level": "{{compliance_level}}"  # Custom variable
  }
)
```

In agent template:
```handlebars
{{compliance_level}}  # Will be filled by orchestrator
```

---

## Template Maintenance

### Template Validation

**Automated Linter:**

```bash
python scripts/lint-agent-templates.py
```

**Checks performed:**
1. ✅ YAML frontmatter completeness (version, last_updated, changelog)
2. ✅ Required sections present (mcp_integration, context, examples)
3. ✅ Template variable syntax (`{{variable}}` - no spaces)
4. ✅ XML tag matching (`<section></section>`)
5. ✅ MCP tool description consistency
6. ✅ Output format specifications

**Example output:**
```
✅ actor.md - PASSED
✅ monitor.md - PASSED
❌ predictor.md - FAILED
   - Missing section: <mcp_integration>
   - Unmatched tag: </examples>
   - Invalid template variable: {{ language }} (has spaces)
```

### Git Pre-Commit Hook

**Automatic validation before commits:**

Located at: `.git/hooks/pre-commit`

**Prevents commits if:**
- Template variables removed from agents
- Critical sections deleted (playbook, feedback, context)
- Massive deletions (>500 lines) without review

**Example block:**
```bash
❌ BLOCKED: Agent file is missing critical template variables!

File: .claude/agents/actor.md
Missing templates:
  - {{language}}
  - {{#if playbook_bullets}}

These template variables are used by Orchestrator for context injection.
See .claude/agents/README.md for details.
```

**To bypass (emergency only):**
```bash
git commit --no-verify -m "message"
```

### Template Versioning

**Version Metadata:**

All agent templates include:
```yaml
---
version: 2.0.0
last_updated: 2025-10-17
changelog: .claude/agents/CHANGELOG.md
---
```

**Version Scheme (Semantic Versioning):**
- **Major (X.0.0):** Breaking changes (template variable removal, output format changes)
- **Minor (2.X.0):** New features (new MCP tool integration, new sections)
- **Patch (2.0.X):** Bug fixes, clarifications, typo fixes

**Changelog:**

See [.claude/agents/CHANGELOG.md](.claude/agents/CHANGELOG.md) for full version history.

**Example entry:**
```markdown
## [2.0.0] - 2025-10-17

### Breaking Changes
- Actor: Changed output format to include `used_bullets` array
- Monitor: Now requires `claude-reviewer` MCP tool

### Added
- Actor: MCP integration section with tool usage patterns
- Reflector: Cipher deduplication checks before pattern extraction

### Fixed
- Monitor: Clarified validation criteria for error handling
```

### MCP Patterns Reference

**Centralized MCP guidance:**

File: [.claude/agents/MCP-PATTERNS.md](.claude/agents/MCP-PATTERNS.md)

**Contents:**
- Common MCP tool usage patterns
- Decision frameworks for tool selection
- Agent-specific MCP integration guidelines
- Best practices and anti-patterns
- Troubleshooting common issues

**Usage:**
```markdown
# In agent templates, reference patterns:

See [MCP-PATTERNS.md](MCP-PATTERNS.md#actor-patterns) for:
- How to search cipher before implementing
- When to fetch library docs
- Batch search optimization
```

### Updating Strategies

**When to update agent templates:**

1. **Research insights:** New papers on prompt engineering, context engineering
2. **Performance degradation:** Monitor approval rate drops, Evaluator scores decline
3. **New MCP tools:** Additional capabilities become available
4. **User feedback:** Agents consistently make same mistakes

**Update Process:**

1. **Analyze metrics:**
   ```bash
   python scripts/analyze-metrics.py
   # Check: approval rate, iteration count, quality scores
   ```

2. **Identify root cause:**
   - Low Monitor approval → Actor needs better guidance
   - High iteration count → Monitor giving unclear feedback
   - Low Evaluator scores → Evaluator rubric too strict/loose

3. **Update template:**
   - Add examples of correct behavior
   - Clarify ambiguous instructions
   - Update MCP tool usage patterns

4. **Validate:**
   ```bash
   python scripts/lint-agent-templates.py
   ```

5. **Test:**
   - Run `/map-feature` on known task
   - Compare metrics before/after
   - Ensure no regressions

6. **Document:**
   - Update `version` and `last_updated` in frontmatter
   - Add entry to CHANGELOG.md
   - Update MCP-PATTERNS.md if tool usage changed

**Rollback if needed:**
```bash
git checkout HEAD~1 .claude/agents/actor.md
```

---

## Context Engineering

MAP Framework applies cutting-edge context engineering principles for AI agents, based on research from Manus.im and academic papers.

### Recitation Pattern (Phase 1.1)

**Problem:** On long tasks (5+ subtasks), models lose focus and forget goals as context window fills.

**Solution:** Attention focus mechanism — `.map/current_plan.md` is updated before each step, keeping goals "fresh" in the context window.

**Mechanism:**

1. **TaskDecomposer** creates initial plan:
   ```markdown
   # Task: feat_auth
   ## Goal: Implement JWT authentication
   ## Subtasks:
   - [ ] 1/5: Create User model
   - [ ] 2/5: Implement login endpoint
   - [ ] 3/5: Add token validation middleware
   - [ ] 4/5: Add refresh token logic
   - [ ] 5/5: Write integration tests
   ```

2. **Orchestrator** updates before each subtask:
   ```markdown
   # Current Task: feat_auth
   ## Progress: 2/5 completed
   - [✓] 1/5: Create User model
   - [→] 2/5: Implement login endpoint (CURRENT, Iteration 2)
     - Last error: Missing JWT import
   - [☐] 3/5: Add token validation middleware
   - [☐] 4/5: Add refresh token logic
   - [☐] 5/5: Write integration tests
   ```

3. **Actor** receives plan in context:
   ```handlebars
   ## Current Task Plan (Recitation Pattern)

   {{plan_context}}

   **Your current subtask is marked with (CURRENT)**
   ```

**Implementation:**

- Class: `RecitationManager` (482 lines)
- Location: `scripts/utils/recitation_manager.py`
- API:
  ```python
  manager = RecitationManager(task_id="feat_auth", goal="...")
  manager.add_subtask(subtask_id, description, status="pending")
  manager.mark_current(subtask_id)
  manager.mark_completed(subtask_id)
  plan_context = manager.format_for_prompt()  # Injected into Actor
  ```

**Benefits:**
- ✅ +20-30% success rate on complex tasks (5+ subtasks)
- ✅ -20-30% token usage (prevents re-explaining context)
- ✅ +50% observability (clear progress tracking)
- ✅ Error context persistence (retry loops retain error history)

### Compaction Resilience

**Problem:** Context compaction (conversation history clearing) would normally lose workflow state, forcing restart from scratch.

**Solution:** File-based persistence architecture where all recitation state persists to disk, surviving compaction.

**Architecture:**

```
Filesystem (persists forever)           Conversation Memory (clears on compaction)
─────────────────────────────           ─────────────────────────────────────────
.map/
├── current_plan.json                   ← Structured state
│   ├── task_id, goal                   ← NEVER lost
│   ├── subtasks[]
│   │   ├── id, description
│   │   ├── status (pending/in_progress/completed)
│   │   ├── iterations, errors
│   │   └── depends_on[]
│   └── current_subtask_id
│
├── current_plan.md                     ← Human-readable format
│   └── Formatted for Claude to read    ← Injected after compaction
│
└── dev_docs/
    ├── context.md                      ← Project-specific context
    └── tasks.md                        ← Auto-generated task list
```

**Persistence Mechanism:**

1. **Automatic Saves** (every recitation update):
   ```python
   # Every time status changes, both files update
   manager.update_subtask_status(2, "in_progress")
   # → Writes to .map/current_plan.json (structured)
   # → Writes to .map/current_plan.md (readable)
   ```

2. **Checkpoint Command** (user-facing):
   ```bash
   $ mapify recitation checkpoint

   ✅ Progress Checkpointed

   Task: feat_auth_1730000000
   Progress: 3/5 subtasks completed
   Current Subtask: 4

   Files persisted:
     • .map/current_plan.md
     • .map/dev_docs/context.md
     • .map/dev_docs/tasks.md

   To resume after compaction:
     Reference these files in new session:
     @.map/current_plan.md
     @.map/dev_docs/context.md
     @.map/tasks.md
   ```

3. **Recovery Workflow** (after compaction):
   ```
   User: continue MAP workflow
         @.map/current_plan.md
         @.map/dev_docs/context.md
         @.map/dev_docs/tasks.md

   Claude: [reads files from disk]
           Resuming from saved state...
           Current task: feat_auth_1730000000
           Progress: 3/5 completed
           Current subtask: 4 - Add error handling
           [continues implementation]
   ```

**Why This Works:**

| Storage Type | Compaction Effect | MAP's Choice |
|-------------|-------------------|--------------|
| Conversation memory | ❌ Cleared | Not used for state |
| File system (.map/) | ✅ Persists | Used for all state |
| Automatic updates | ✅ Always current | No manual checkpointing |

**Comparison to Manual Approaches:**

- **Manual checkpointing** (e.g., "/update-dev-docs"): Requires user to remember command before compaction. Risk of forgetting.
- **MAP's approach**: Automatic persistence with optional checkpoint command for guidance. Zero cognitive load.

**Benefits:**
- ✅ **Zero data loss** - All progress persists across compactions
- ✅ **Automatic** - No manual checkpointing required
- ✅ **Always current** - Files update on every status change
- ✅ **Cross-session** - Resume in any new conversation
- ✅ **Observable** - Checkpoint command shows recovery paths

**Implementation:**
- Class: `RecitationManager._save_plan()` (line 238-261)
- Files: `.map/current_plan.json`, `.map/current_plan.md`
- CLI: `mapify recitation checkpoint` command

### Automatic Recovery (Phase 2)

**Problem:** Manual recovery (Phase 1) requires users to reference checkpoint files after compaction, adding cognitive load and causing 60% workflow abandonment rate.

**Solution:** SessionStart hook automatically injects `.map/current_plan.md` on session start, providing seamless zero-touch recovery.

**Architecture:**

```
SessionStart Event (Claude Code)
        ↓
.claude/hooks/session-start.sh (94 lines)
        ↓
    [Check .map/current_plan.md exists?]
        ↓ Yes
    Call validator helper
        ↓
.claude/hooks/helpers/validate_checkpoint_file.py (350 lines)
        ↓
    [4-Layer Security Validation]
    ├─ Layer 1: Path Traversal Prevention
    ├─ Layer 2: Size Bomb Protection (256KB limit)
    ├─ Layer 3: UTF-8 Validation
    └─ Layer 4: Content Sanitization
        ↓
    [All layers pass?]
        ↓ Yes
    Return JSON: {valid: true, sanitized_content: "..."}
        ↓
Hook injects content with restoration header
        ↓
Claude receives context automatically
        ↓
[Workflow continues from checkpoint]
```

**Implementation:**

| Component | Location | Size | Purpose |
|-----------|----------|------|---------|
| Hook script | `.claude/hooks/session-start.sh` | 94 lines | Orchestrates validation and injection |
| Validator helper | `.claude/hooks/helpers/validate_checkpoint_file.py` | 350 lines | 4-layer security validation |
| Unit tests | `tests/hooks/test_validate_checkpoint_file.py` | 41 tests | Validation logic coverage |
| Integration tests | `tests/hooks/test_session_start_integration.py` | 23 tests | End-to-end hook behavior |

**Execution Flow:**

1. **SessionStart event triggers** - Claude Code detects new conversation session
2. **Hook checks checkpoint existence** - Tests if `.map/current_plan.md` exists
3. **Validator performs security checks** - Python helper runs 4-layer validation (see below)
4. **Sanitization applied** - Control characters stripped, UTF-8 verified
5. **Injection with header** - Hook returns JSON with `additionalContext` field
6. **Claude receives context** - Checkpoint content appears in conversation memory automatically
7. **Workflow resumes** - No user action required, seamless continuation

**Security Validation (Defense-in-Depth):**

All validation layers use AND logic - checkpoint must pass **all 4 layers** to be injected.

**Layer 1: Path Traversal Prevention**

*Rationale:* Prevent attackers from injecting arbitrary files (e.g., `../../../etc/passwd`)

*Implementation:*
```python
# Resolve to absolute path (handles .., symlinks)
resolved = Path(file_path).resolve()
base_path = Path(".map").resolve()

# Security check: Ensure resolved path is within .map/
if not resolved.is_relative_to(base_path):
    return {"valid": False, "error": "Path traversal detected"}
```

*Rejects:*
- Absolute paths outside `.map/`
- Symlinks pointing outside `.map/`
- Relative paths with `../` escaping `.map/`

**Layer 2: Size Bomb Protection**

*Rationale:* Prevent memory exhaustion attacks via multi-GB files

*Implementation:*
```python
MAX_FILE_SIZE_BYTES = 256 * 1024  # 256KB

# Check size BEFORE reading into memory
size_bytes = file_path.stat().st_size

if size_bytes > MAX_FILE_SIZE_BYTES:
    return {"valid": False, "error": f"File too large: {size_kb}KB exceeds 256KB limit"}
```

*Performance:* File size check completes in <0.05s without loading file content

**Layer 3: UTF-8 Validation**

*Rationale:* Prevent binary file injection (executables, images, malformed text)

*Implementation:*
```python
# Strict UTF-8 decoding - raises UnicodeDecodeError on invalid bytes
content = file_path.read_text(encoding='utf-8', errors='strict')
```

*Rejects:*
- Binary files (executables, images)
- Non-UTF-8 encoded text
- Files with invalid byte sequences

**Layer 4: Content Sanitization**

*Rationale:* Prevent terminal injection via ANSI escape codes and control characters

*Implementation:*
```python
# Regex strips control characters except newlines (\n) and tabs (\t)
CONTROL_CHAR_PATTERN = re.compile(r'[\x00-\x08\x0b-\x0d\x0e-\x1f\x7f\u0080-\u009f\u2028\u2029]')

sanitized = CONTROL_CHAR_PATTERN.sub('', content)
```

*Removes:*
- NULL bytes (`\x00`)
- ANSI escape codes (`\x1b[...`)
- Carriage returns (`\r`) for terminal safety
- Unicode control characters (`\u2028`, `\u2029`)

*Preserves:*
- Newlines (`\n`) - Required for markdown formatting
- Tabs (`\t`) - Required for code indentation

**Bash Hook Limitations:**

Claude Code hooks run in subprocess with restricted capabilities:

| Capability | Available? | Workaround |
|-----------|-----------|-----------|
| MCP tool access | ❌ No | Hooks can't call `cipher_memory_search`, `sequential-thinking` |
| Python imports | ❌ No | Must call separate Python script via subprocess |
| Async operations | ❌ No | Synchronous execution only (5s timeout) |
| External scripts | ✅ Yes | Can call `python3`, `jq`, bash utilities |
| Filesystem access | ✅ Yes | Direct read/write to `.map/` directory |

**Why no MCP tools?** Hooks execute in isolated subprocess without access to Claude Code's MCP server connections. Use helpers for complex logic.

**Performance Characteristics:**

| Metric | Typical | Maximum | Notes |
|--------|---------|---------|-------|
| Total execution time | <0.5s | 5s | Hook timeout enforced by Claude Code |
| Validation overhead | ~0.1s | 0.2s | 4-layer security checks |
| File I/O | <0.05s | 0.1s | Read 256KB checkpoint file |
| JSON parsing | <0.01s | 0.02s | Parse validator output with `jq` |

**Test Results (64 total tests):**
- ✅ 41 unit tests (validation logic) - 95% coverage
- ✅ 23 integration tests (end-to-end hook) - All pass
- ✅ Security tests: Path traversal, size bombs, control characters, UTF-8 errors
- ✅ Performance tests: <0.5s for 5KB checkpoint, <1s for 256KB checkpoint

**Integration with .map/ Persistence:**

**Phase 1 (Manual)** vs **Phase 2 (Automatic)**:

```
Phase 1: User-Driven Recovery          Phase 2: Hook-Driven Recovery
─────────────────────────────          ──────────────────────────────
.map/current_plan.md                   .map/current_plan.md
        ↓                                      ↓
User runs: mapify recitation           SessionStart hook (automatic)
checkpoint                                     ↓
        ↓                              Validator validates (4 layers)
Output shows file paths:                       ↓
  @.map/current_plan.md                Auto-injects to context
        ↓                                      ↓
User copies paths manually             Claude has context immediately
        ↓                                      ↓
User pastes in new session             [Workflow continues automatically]
        ↓
Claude reads from context
        ↓
Workflow continues
```

**Key Differences:**

| Aspect | Phase 1 (Manual) | Phase 2 (Automatic) |
|--------|------------------|---------------------|
| User action required | ✅ Yes (copy/paste paths) | ❌ No (zero-touch) |
| Cognitive load | Medium (remember 3 file paths) | Zero (invisible) |
| Error prone | Yes (typos, wrong files) | No (validated automatically) |
| Workflow abandonment | ~30% (users forget) | ~5% (edge cases only) |
| Time to resume | 30-60s (manual steps) | 0s (instant) |

**Benefits:**

- ✅ **Zero cognitive load** - Users never think about compaction recovery
- ✅ **Seamless UX** - Invisible to users, "just works" experience
- ✅ **Secure by design** - 4-layer validation prevents all known attack vectors
- ✅ **Always current** - Reads latest checkpoint (auto-saved by Phase 1)
- ✅ **Non-blocking** - Hook failures don't prevent session start (exit 0)
- ✅ **Observable** - Logs to stderr for debugging (`[session-start] ...`)
- ✅ **Tested** - 64 tests with >90% coverage

**Failure Modes & Handling:**

All failures are non-blocking - hook returns `{"continue": true}` and logs error to stderr:

| Failure Scenario | Hook Behavior | User Impact |
|------------------|---------------|-------------|
| No checkpoint file | Skip injection, continue | None (new session, expected) |
| Validator script missing | Skip injection, continue | None (fallback to Phase 1 manual) |
| Path traversal detected | Reject file, continue | None (security protection) |
| File too large (>256KB) | Reject file, continue | None (size bomb protection) |
| Invalid UTF-8 encoding | Reject file, continue | None (binary file protection) |
| Control characters found | Sanitize + inject | None (transparent cleanup) |
| Validator crashes | Skip injection, continue | None (error logged to stderr) |

**Design Principle:** Session start must **always succeed**. Security validation prevents injection of malicious content, but never blocks users from starting new sessions.

**References:**

- Design document: `docs/recitation-compaction-resilience-review.md`
- User research: Reddit feedback analysis showing 60% manual recovery confusion rate
- Implementation: Phase 2 addresses Monitor finding: "Missing compaction recovery workflow docs"

### Workflow Logging (Phase 1.2)

**Problem:** Debugging failed workflows requires manual correlation of agent outputs.

**Solution:** Structured logging with workflow context in `.map/workflow_logs/`.

**Log Format:**

**Note:** `subtask_id` is an **integer** (not string) matching the `id` field from TaskDecomposer output. TaskDecomposer generates subtask IDs as sequential integers: 1, 2, 3, etc.

```json
{
  "task_id": "feat_auth_20251023_143022",
  "goal": "Implement JWT authentication",
  "start_time": "2025-10-23T14:30:22Z",
  "subtasks": [
    {
      "subtask_id": 1,
      "description": "Create User model",
      "status": "completed",
      "iterations": 1,
      "agents": {
        "actor": {
          "start_time": "2025-10-23T14:30:25Z",
          "end_time": "2025-10-23T14:31:10Z",
          "duration_seconds": 45,
          "output_summary": "Generated User model with password hashing"
        },
        "monitor": {
          "validation_passed": true,
          "issues": []
        },
        "evaluator": {
          "overall_score": 8.5,
          "approved": true
        }
      }
    }
  ]
}
```

**Implementation:**

- Class: `MapWorkflowLogger` (246 lines)
- Location: `scripts/utils/map_workflow_logger.py`
- API:
  ```python
  logger = MapWorkflowLogger(task_id, goal)
  logger.start_subtask(subtask_id, description)
  logger.log_agent_output(agent_name, output)
  logger.complete_subtask(subtask_id, status="completed")
  logger.finalize()
  ```

**Benefits:**
- ✅ Post-mortem analysis of failures
- ✅ Performance benchmarking per agent
- ✅ Audit trail for compliance
- ✅ Metrics dashboard input

### Playbook Top-K Limiting (Phase 1.3)

**Problem:** Too many playbook patterns distract model, reduce focus on most relevant patterns.

**Solution:** Limit patterns retrieved to `top_k=5` (configurable).

**Configuration:**

File: `.claude/playbook.json`
```json
{
  "metadata": {
    "top_k": 5
  }
}
```

**Behavior:**

```python
# In Actor agent context injection:
relevant_bullets = get_relevant_bullets(
    query=subtask_description,
    limit=metadata.get("top_k", 5)  # Default 5
)
```

**Benefits:**
- ✅ ~15% token reduction in Actor prompts
- ✅ Improved focus on best patterns
- ✅ Faster retrieval (fewer embeddings to compare)

**Customization:**
- `top_k=3`: Simple tasks, minimal context needed
- `top_k=5`: Balanced (recommended default)
- `top_k=7-10`: Complex tasks requiring multiple pattern references

### Template Optimization (Phase 1.4)

**Problem:** Verbose agent outputs waste tokens without adding value.

**Changes:**

1. **Monitor:** Reduced validation output verbosity (-9.6% tokens)
   - Before: Full code review with line-by-line feedback
   - After: Issue summaries with severity and category

2. **Evaluator:** Structured scoring format
   - Before: Prose explanation of scores
   - After: JSON scores + brief rationale

**Results:**
- ✅ 9.6% overall token reduction (Monitor, Evaluator)
- ✅ Maintained validation quality (no decrease in approval rates)
- ✅ Faster parsing of agent outputs

### Context Engineering Roadmap

**Phase 1 ✅ COMPLETED** (2025-10-18):
- [x] **RecitationManager** (482 lines): Recitation Pattern for focus
- [x] **MapWorkflowLogger** (246 lines): Detailed workflow logging
- [x] **Playbook top_k=5**: Limit playbook patterns
- [x] **Template Optimization**: Optimize verbose outputs (-9.6% tokens)

**Phase 1 Results:**
- ✅ 9.6% reduction in token usage (Monitor, Evaluator templates)
- ✅ 267% playbook growth (3 → 11 patterns)
- ✅ 728 lines of new infrastructure
- ✅ Documentation-driven orchestration architecture

**Phase 2** (Prioritized):
1. **Checkpoints** (high impact) — Workflow resumption after interruption
2. **MCP caching** (medium-high) — Latency reduction for cipher/context7
3. **Keyword+semantic search** (medium) — Hybrid retrieval accuracy
4. **Playbook variation** (low-medium) — Few-shot bias reduction

**Phase 3-4:** Parallelism, auto-testing, temperature per agent

**Detailed Plans:**
- [Context Engineering Improvements](docs/CONTEXT-ENGINEERING-IMPROVEMENTS.md) — Full roadmap
- [Phase 1 Completion Summary](docs/PHASE-1-COMPLETION-SUMMARY.md) — Metrics, architecture, troubleshooting
- [Recitation Integration Verification](docs/RECITATION-INTEGRATION-VERIFICATION.md) — Detailed integration verification

**Research Foundation:**
- ["Context Engineering for AI Agents" (Manus.im, 2025)](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)

---

## Success Metrics

**Target KPIs:**
- **Monitor approval rate:** >80% first try (current: varies by task complexity)
- **Evaluator scores:** average >7.0/10 (approval threshold)
- **Iteration count:** <3 per subtask (indicates clear feedback)
- **Playbook growth:** increasing high-quality patterns (helpful_count >= 5)

**Tracking:**
```bash
# View metrics dashboard
python scripts/analyze-metrics.py

# Check specific workflow
cat .map/workflow_logs/feat_auth_20251023_143022.json | jq '.subtasks[].agents.evaluator.overall_score'
```

---

## References

- [MAP Paper - Nature Communications](https://github.com/Shanka123/MAP)
- [ACE Paper - arXiv:2510.04618v1](https://arxiv.org/abs/2510.04618v1)
- [Context Engineering for AI Agents (Manus.im)](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)
- [Claude Code Documentation](https://docs.anthropic.com/en/docs/claude-code)

---

**For usage examples and best practices, see [USAGE.md](USAGE.md).**
**For installation and setup, see [README.md](README.md).**
