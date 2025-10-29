# MAP Framework Usage Guide

Complete usage examples, best practices, and optimization strategies for the MAP Framework.

## Navigation

- [Usage Examples](#usage-examples)
  - [Feature Development](#feature-development)
  - [Bug Fixing](#bug-fixing)
  - [Refactoring](#refactoring)
  - [Library Integration](#library-integration)
  - [Learning from Open Source](#learning-from-open-source)
- [Playbook Commands](#playbook-commands)
- [Dependency Validation](#dependency-validation)
  - [Basic Usage](#basic-usage)
  - [Visualization Mode](#visualization-mode)
  - [Exit Codes](#exit-codes)
  - [Integration with TaskDecomposer](#integration-with-taskdecomposer)
  - [Sample TaskDecomposer JSON](#sample-taskdecomposer-json)
  - [Validation Output Examples](#validation-output-examples)
  - [Command-Line Flags Reference](#command-line-flags-reference)
  - [Validation Best Practices](#validation-best-practices)
- [Best Practices](#best-practices)
  - [Clear Requirements](#1-clear-requirements)
  - [Incremental Approach](#2-incremental-approach)
  - [Provide Context](#3-provide-context)
- [Cost Optimization](#cost-optimization)
  - [Model Distribution Strategy](#model-distribution-strategy)
  - [Cost Savings](#cost-savings)
  - [How It Works](#how-it-works)
  - [Cost Comparison Example](#cost-comparison-example)
- [Additional Resources](#additional-resources)

---

## 📚 Usage Examples

### Feature Development

```bash
/map-feature implement user profile page with avatar upload.
Include validation, error handling, and tests.
```

### Bug Fixing

```bash
/map-debug debug why payment processing fails for amounts over $1000
```

### Refactoring

```bash
/map-refactor refactor OrderService to use dependency injection.
Maintain all existing functionality.
```

### Library Integration

```bash
/map-feature integrate Stripe payment processing.
Use context7 to get latest Stripe docs.
```

### Learning from Open Source

```bash
/map-feature implement rate limiter.
Study express-rate-limit via deepwiki, then create optimized version.
```

## 🛠️ Playbook Commands

The playbook manager CLI provides tools to analyze and manage learned patterns:

### Querying Playbook (NEW - FTS5 Full-Text Search)

**Recommended:** Use `mapify playbook query` instead of `mapify playbook search` for better performance with large playbooks.

```bash
# Basic query (local playbook only)
mapify playbook query "JWT authentication" --limit 5

# With cipher integration (broader knowledge)
mapify playbook query "error handling patterns" --mode hybrid --limit 10

# Filter by sections
mapify playbook query "API design" --section ARCHITECTURE_PATTERNS --section IMPLEMENTATION_PATTERNS

# Minimum quality filter
mapify playbook query "security patterns" --min-quality 3

# JSON output (for scripts)
mapify playbook query "testing strategies" --format json
```

**Query modes:**
- `--mode local` (default) - Search local playbook only (fast, <50ms)
- `--mode hybrid` - Search both playbook and cipher (comprehensive)
- `--mode cipher` - Search cipher only (cross-project patterns)

**Why use `query` instead of `search`:**
- ✅ **Works with large playbooks** - Handles >256KB (current playbook: 270KB)
- ✅ **FTS5 full-text search** - 10x faster than grep
- ✅ **Relevance ranking** - Best patterns first
- ✅ **Quality scoring** - Prioritizes proven patterns (helpful_count - harmful_count)
- ✅ **Cipher integration** - Optional cross-project knowledge

### Apply Delta Operations (MAP Workflow Integration)

**Purpose:** Apply Curator agent output to update the playbook database.

```bash
# Apply operations from file
mapify playbook apply-delta curator_output.json

# Preview changes without applying (dry-run)
mapify playbook apply-delta operations.json --dry-run

# Pipe from Curator agent (recommended in MAP workflows)
cat curator_output.json | mapify playbook apply-delta
echo '{"operations": [{"type": "UPDATE", "bullet_id": "impl-0001", "increment_helpful": 1}]}' | mapify playbook apply-delta
```

**Operation Types:**

1. **ADD** - Add new bullet to playbook
   ```json
   {
     "type": "ADD",
     "section": "IMPLEMENTATION_PATTERNS",
     "content": "Use async/await for I/O operations",
     "code_example": "async def fetch(): ...",
     "tags": ["python", "async"]
   }
   ```

2. **UPDATE** - Increment helpful/harmful counters
   ```json
   {
     "type": "UPDATE",
     "bullet_id": "impl-0042",
     "increment_helpful": 1
   }
   ```

3. **DEPRECATE** - Mark bullet as deprecated
   ```json
   {
     "type": "DEPRECATE",
     "bullet_id": "impl-0099",
     "reason": "Superseded by impl-0105"
   }
   ```

**Input Format:**

```json
{
  "operations": [
    {"type": "ADD", "section": "...", "content": "..."},
    {"type": "UPDATE", "bullet_id": "...", "increment_helpful": 1},
    {"type": "DEPRECATE", "bullet_id": "...", "reason": "..."}
  ]
}
```

**When to Use:**

- ✅ **After Curator agent** in MAP workflows (/map-feature, /map-debug, etc.)
- ✅ **Batch updates** from CI/CD pipelines
- ✅ **Automated playbook maintenance**

**Exit Codes:**
- `0` - Success (operations applied or dry-run completed)
- `1` - Validation error or application failure

### Statistics

```bash
# Statistics
mapify playbook stats

# High-quality patterns ready for sync
mapify playbook sync
```

### Legacy Search (deprecated for large playbooks)

```bash
# Search patterns (works for small playbooks <256KB)
mapify playbook search "JWT authentication"
```

**Note:** `search` command uses simple keyword matching and may fail on large playbooks. Use `query` instead.

## 🔄 Handling Context Compaction

MAP workflows automatically save progress to the `.map/` directory, which persists across context compactions. This ensures your work is never lost, even if the conversation context is cleared.

### What is Context Compaction?

Context compaction occurs when Claude's conversation memory reaches its limit. When this happens:
- The conversation history is cleared to free up space
- But your work files on disk remain intact
- You can seamlessly resume from where you left off

### Recovery Workflow

**1. Before Compaction (Optional):**

If you notice context getting low, checkpoint your progress:

```bash
mapify recitation checkpoint
```

This will display:
- Current task status
- Absolute file paths to your work
- Instructions for recovery

**Example output:**
```
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
  @.map/context.md
  @.map/tasks.md
```

**2. After Compaction:**

In the new conversation session, reference the saved files:

```
User: continue MAP workflow
      @.map/current_plan.md
      @.map/dev_docs/context.md
      @.map/dev_docs/tasks.md

Claude: [reads files]
        Resuming subtask 4: "Add error handling to API routes"
        [continues implementation from saved state]
```

### Key Points

- ✅ **Progress auto-saves** - Every `mapify recitation update` saves to disk
- ✅ **No manual checkpointing required** - Files update automatically during workflow
- ✅ **Files persist forever** - They're on your filesystem, not in conversation memory
- ✅ **Cross-session recovery** - Resume in any new conversation by referencing files

### Architecture

MAP's recitation system uses file-based persistence:
- `.map/current_plan.json` - Structured plan data
- `.map/current_plan.md` - Human-readable plan for Claude
- `.map/dev_docs/context.md` - Project context
- `.map/dev_docs/tasks.md` - Task checklist

These files survive compaction because they're stored on disk, not in conversation memory.

## 🔍 Dependency Validation

The dependency validation utility (`scripts/validate-dependencies.py`) ensures TaskDecomposer output has valid dependency graphs before execution. It prevents workflow failures by detecting:

- **Circular dependencies** — Tasks that create impossible execution loops (A → B → C → A)
- **Forward references** — Dependencies on non-existent tasks
- **Self-dependencies** — Tasks that depend on themselves
- **Orphaned tasks** — Isolated tasks with no incoming or outgoing dependencies

### Basic Usage

**Recommended (after `pip install mapify-cli`):**

```bash
# Validate from file
mapify validate graph decomposer-output.json

# Output in text format (human-readable)
mapify validate graph decomposer-output.json -f text

# JSON format (default, for CI/CD)
mapify validate graph decomposer-output.json -f json

# Validate from stdin
cat decomposer-output.json | mapify validate graph
```

**For development (using script directly):**

```bash
# Validate from stdin
cat decomposer-output.json | python scripts/validate-dependencies.py

# Validate from file
python scripts/validate-dependencies.py decomposer-output.json

# Output in text format (human-readable)
python scripts/validate-dependencies.py -f text decomposer-output.json

# JSON format (default, for CI/CD)
python scripts/validate-dependencies.py -f json decomposer-output.json
```

### Visualization Mode

Display ASCII dependency tree to understand task execution order:

**Recommended (mapify CLI):**

```bash
# Show dependency tree with colors
mapify validate graph decomposer-output.json --visualize

# Show tree without colors (for logs/CI)
mapify validate graph decomposer-output.json --visualize --no-color
```

**For development (direct script):**

```bash
# Show dependency tree with colors
python scripts/validate-dependencies.py --visualize decomposer-output.json

# Show tree without colors (for logs/CI)
python scripts/validate-dependencies.py --visualize --no-color decomposer-output.json
```

**Example visualization output:**

```
Task Dependency Tree:
Task 1: Setup environment
├─ Task 2: Install dependencies
│  └─ Task 4: Run tests
└─ Task 3: Configure database
   └─ Task 4: Run tests
```

### Exit Codes

The validator uses standard exit codes for automation:

| Exit Code | Meaning | CI/CD Action |
|-----------|---------|--------------|
| `0` | Valid graph (no critical errors) | Continue workflow |
| `1` | Invalid graph (critical errors found) OR warnings with `--strict` flag | Fail build |
| `2` | Invalid input (malformed JSON or missing required fields) | Fix input format |

> **Note**: By default, **warnings** (e.g., orphaned tasks) result in exit code `0` and **do not** fail CI/CD builds. Only **critical errors** (circular dependencies, forward references, self-dependencies) cause exit code `1`. To enforce strict validation where warnings also fail the build, use the `--strict` flag. Use `--format text` to see issue severity levels.

**CI/CD Integration Examples:**

```bash
# Default mode: Only critical errors fail the build
mapify validate graph plan.json || exit 1
echo "✓ Task graph has no critical errors"

# Strict mode: Warnings also fail the build
mapify validate graph --strict plan.json || exit 1
echo "✓ Task graph is perfect (no warnings or errors)"

# Alternative: using direct script (for development/testing)
python scripts/validate-dependencies.py plan.json || exit 1
echo "✓ Task graph validated successfully"
```

### Integration with TaskDecomposer

Validate TaskDecomposer output before starting workflow:

```bash
# Step 1: Decompose task
/map-feature implement user authentication

# Step 2: Review TaskDecomposer output
# (orchestrator saves to .claude/decomposer-output.json)

# Step 3: Validate before execution (recommended)
mapify validate graph .claude/decomposer-output.json

# Alternative (for development): use direct script
python scripts/validate-dependencies.py .claude/decomposer-output.json

# Step 4: If valid, orchestrator proceeds automatically
```

**Note:** MAP Framework orchestrators can integrate this validation step to prevent execution of invalid task graphs.

### Sample TaskDecomposer JSON

```json
{
  "subtasks": [
    {
      "id": 1,
      "title": "Setup authentication middleware",
      "description": "Create Express middleware for JWT validation",
      "dependencies": []
    },
    {
      "id": 2,
      "title": "Implement login endpoint",
      "description": "POST /api/login with email/password",
      "dependencies": [1]
    },
    {
      "id": 3,
      "title": "Add refresh token logic",
      "description": "Implement token refresh endpoint",
      "dependencies": [1, 2]
    }
  ]
}
```

### Validation Output Examples

**Valid graph (JSON format):**

```json
{
  "valid": true,
  "issues": [],
  "summary": {
    "total_tasks": 3,
    "critical_issues": 0,
    "warnings": 0
  }
}
```

**Invalid graph with circular dependency (JSON format):**

```json
{
  "valid": false,
  "issues": [
    {
      "type": "circular_dependency",
      "severity": "critical",
      "affected_tasks": [1, 2, 3],
      "message": "Circular dependency detected: 1 → 2 → 3 → 1"
    }
  ],
  "summary": {
    "total_tasks": 3,
    "critical_issues": 1,
    "warnings": 0
  }
}
```

**Text format output:**

```
⚠️  Validation Failed

Issues Found:
  [CRITICAL] Circular dependency detected: 1 → 2 → 3 → 1
    Affected tasks: 1, 2, 3

Summary:
  Total tasks: 3
  Critical issues: 1
  Warnings: 0
```

### Command-Line Flags Reference

| Flag | Short | Values | Default | Description |
|------|-------|--------|---------|-------------|
| `--format` | `-f` | `json`, `text` | `json` | Output format for validation results |
| `--visualize` | — | — | — | Display ASCII dependency tree |
| `--no-color` | — | — | — | Disable ANSI colors in visualization |
| `--strict` | — | — | — | Fail on warnings (e.g., orphaned tasks), not just critical errors |
| `--help` | `-h` | — | — | Show help message and examples |

### Validation Best Practices

1. **Always validate in CI/CD** — Add validation step before task execution
2. **Use JSON format for automation** — Machine-readable output for scripts
3. **Use text format for debugging** — Human-readable output for investigation
4. **Visualize complex graphs** — Use `--visualize` to understand execution order
5. **Check exit codes** — Use `$?` in shell scripts for automated validation

## 🔀 Workflow Variants

MAP Framework offers three workflow variants with different trade-offs between token usage, quality assurance, and learning:

### Comparison Table

| Feature | /map-feature | /map-efficient ⭐ | /map-fast ⚠️ |
|---------|--------------|-------------------|--------------|
| **Agents Used** | 8 (full pipeline) | 5-6 (optimized) | 3 (minimal) |
| **Token Savings** | 0% (baseline) | **30-40%** | 40-50% |
| **Learning Enabled** | ✅ Per-subtask | ✅ Batched at end | ❌ None |
| **Quality Gates** | All agents | Essential agents | Basic only |
| **Impact Analysis** | ✅ Always (Predictor) | ✅ Conditional | ❌ Never |
| **Quality Scoring** | ✅ Yes (Evaluator) | ❌ Skipped | ❌ Never |
| **Playbook Updates** | ✅ Per-subtask | ✅ End of workflow | ❌ None |
| **Cipher Integration** | ✅ Per-subtask | ✅ End of workflow | ❌ None |
| **Best For** | Critical features | **Most tasks** | Throwaway only |
| **Production Ready** | ✅ Maximum QA | ✅ Yes | ❌ NO |

### Decision Guide: Which Workflow Should I Use?

#### Use `/map-efficient` (RECOMMENDED) ⭐

**When:**
- ✅ Production code where token costs matter
- ✅ Well-understood features with low-medium risk
- ✅ Iterative development with frequent workflows
- ✅ You want learning without excessive token usage
- ✅ Standard CRUD operations, UI components
- ✅ Refactoring with clear scope

**Why it's better than /map-fast:**
- Still preserves full learning (Reflector/Curator)
- Conditional Predictor catches high-risk issues
- Only 10% less token savings but much safer

**Example use cases:**
```bash
# Standard feature development
/map-efficient implement user profile editing with form validation

# API development
/map-efficient create REST API endpoints for product management

# UI components
/map-efficient build responsive navigation menu with mobile support
```

#### Use `/map-feature` (Full Workflow)

**When:**
- 🔒 Security-critical functionality (authentication, authorization)
- 🔒 First-time implementation of complex features
- 🔒 High-risk changes affecting many files/modules
- 🔒 Database schema migrations
- 🔒 Breaking API changes
- 🔒 You need maximum quality assurance

**Why it's worth the extra tokens:**
- Evaluator scores quality across 6 dimensions
- Predictor always analyzes breaking changes
- Per-subtask learning captures more nuanced patterns
- Maximum safety for critical code

**Example use cases:**
```bash
# Security-critical
/map-feature implement JWT authentication with refresh tokens

# Complex first-time feature
/map-feature build real-time chat system with WebSocket support

# High-risk refactoring
/map-refactor migrate entire codebase from REST to GraphQL
```

#### Use `/map-fast` (Minimal) ⚠️

**ONLY when:**
- 🗑️ Creating throwaway prototypes you'll discard
- 🗑️ Quick experiments to test feasibility
- 🗑️ Learning/tutorial contexts where failure is acceptable
- 🗑️ Mockups for demonstrations

**⚠️ NEVER use for:**
- ❌ Production code
- ❌ Code you'll commit to repository
- ❌ Features that others will depend on
- ❌ Security-sensitive functionality

**Why it's dangerous:**
- No impact analysis → Breaking changes undetected
- No learning → Playbook stays empty, same mistakes repeated
- No quality scoring → Security/performance issues missed
- No cipher integration → Knowledge lost forever

**Example use cases (acceptable):**
```bash
# Quick prototype to show stakeholder
/map-fast prototype a dashboard layout with mock data

# Feasibility experiment
/map-fast test if library X can integrate with our stack

# Tutorial/learning
/map-fast follow the React tutorial to learn hooks
```

### Real-World Token Usage Examples

**Small Task (1-2 subtasks):**
- `/map-feature`: ~20-30K tokens
- `/map-efficient`: ~12-20K tokens (40% savings)
- `/map-fast`: ~10-15K tokens (50% savings)

**Medium Task (3-5 subtasks):**
- `/map-feature`: ~75-100K tokens
- `/map-efficient`: ~45-60K tokens (40% savings)
- `/map-fast`: ~30-40K tokens (60% savings)

**Large Task (6-8 subtasks):**
- `/map-feature`: ~150-200K tokens
- `/map-efficient`: ~90-120K tokens (40% savings)
- `/map-fast`: ~60-80K tokens (60% savings)

**Cost at $3/M input, $15/M output (Claude Sonnet 3.5):**

| Task Size | /map-feature | /map-efficient | Savings |
|-----------|--------------|----------------|---------|
| Small | $0.30-0.45 | $0.18-0.30 | $0.12-0.15 |
| Medium | $1.13-1.50 | $0.68-0.90 | $0.45-0.60 |
| Large | $2.25-3.00 | $1.35-1.80 | $0.90-1.20 |

**For teams running 10 workflows/day:**
- /map-feature: ~$22.50/day
- /map-efficient: ~$13.50/day
- **Monthly savings: $270** (12 fewer dollars/day × 30 days)

### How /map-efficient Works

**Key Optimizations:**

1. **Conditional Predictor** (5-10% savings)
   - TaskDecomposer assigns risk_level to each subtask
   - Predictor only called if risk_level='high' or Monitor flags issues
   - Low-risk tasks (simple CRUD, UI updates) skip impact analysis

2. **Batched Learning** (10-15% savings)
   - Reflector analyzes ALL subtasks together at end
   - Curator makes single playbook update
   - More holistic insights (sees patterns across subtasks)
   - Saves (N-1) × 3K tokens for N subtasks

3. **Evaluator Skipped** (8-12% savings)
   - Monitor provides sufficient validation for most tasks
   - Evaluator's 6-dimension scoring rarely changes decisions
   - Quality still ensured by Monitor's comprehensive checks

**What's Preserved:**
- ✅ Full learning cycle (Reflector + Curator)
- ✅ Playbook updates (batched but complete)
- ✅ Cipher integration (high-quality patterns stored)
- ✅ Essential quality gates (Monitor validation)
- ✅ Impact analysis (when needed)

### Workflow Selection Flowchart

```
START: I need to implement a feature
  |
  ├─ Is it throwaway/prototype code?
  |    └─ YES → /map-fast (but consider if learning would help)
  |    └─ NO → Continue
  |
  ├─ Is it security-critical or first-time complex feature?
  |    └─ YES → /map-feature (maximum QA)
  |    └─ NO → Continue
  |
  ├─ Do I care about token costs?
  |    └─ NO → /map-feature (best quality)
  |    └─ YES → /map-efficient ⭐ (RECOMMENDED)
```

### Migration Guide

**Switching from /map-feature to /map-efficient:**

No code changes needed! Just use `/map-efficient` instead:

```bash
# Old
/map-feature implement user dashboard

# New (saves 30-40% tokens, same learning)
/map-efficient implement user dashboard
```

**When to keep using /map-feature:**
- First implementation of authentication/authorization
- Database migrations affecting multiple tables
- Breaking API changes
- Any feature where failure is costly

### Common Misconceptions

**❌ Misconception:** "/map-fast is 50% cheaper, so it's always better for saving money"
**✅ Reality:** /map-fast defeats MAP's purpose (no learning = repeat mistakes = waste tokens long-term). Use /map-efficient instead.

**❌ Misconception:** "/map-efficient skips quality checks"
**✅ Reality:** Monitor still validates everything. Only Evaluator's scoring is skipped (rarely changes decisions).

**❌ Misconception:** "Batched learning in /map-efficient is inferior to per-subtask learning"
**✅ Reality:** Batched learning sees patterns ACROSS subtasks, often producing better insights than isolated per-subtask analysis.

## 🎯 Best Practices

### 1. Clear Requirements

Always provide specific, detailed requirements to get the best results.

```bash
# Good ✅
"Implement registration with email validation, password strength check (8+ chars, 1 number), send confirmation"

# Bad ❌
"Add registration"
```

**Why it matters:**

- Clear requirements lead to better task decomposition
- Reduces Actor-Monitor retry cycles
- Produces more maintainable code

### 2. Incremental Approach

Break large features into phases to maintain focus and quality:

- **Phase 1:** Core functionality
- **Phase 2:** Edge cases and error handling
- **Phase 3:** Optimization

**Example workflow:**

```bash
# Phase 1: Core implementation
/map-feature implement basic user authentication with login/logout

# Phase 2: Enhanced security
/map-feature add password reset and email verification to authentication

# Phase 3: Performance tuning
/map-refactor optimize authentication to use Redis session caching
```

### 3. Provide Context

Always specify relevant project context to improve solution quality:

**Include:**

- Technology stack (e.g., "using Express.js with TypeScript")
- Existing patterns (e.g., "follow the service-repository pattern used in UserService")
- Constraints (e.g., "must work with PostgreSQL 12+")
- Performance requirements (e.g., "handle 1000 requests/second")

**Example:**

```bash
/map-feature implement product search using Elasticsearch.
Stack: Node.js + Express + PostgreSQL.
Follow existing repository pattern in ProductRepository.
Must handle 500 concurrent searches with <200ms response time.
```

## 💰 Cost Optimization

MAP Framework supports intelligent model selection per agent to balance capability and cost.

### Model Distribution Strategy

| Agent | Model | Reason | Cost Impact |
|-------|-------|--------|-------------|
| **Predictor** | haiku | Fast analysis, simple dependency tracking | ⬇️⬇️⬇️ |
| **Evaluator** | haiku | Scoring doesn't need complex reasoning | ⬇️⬇️⬇️ |
| **Actor** | sonnet | Code generation quality is critical | ➡️ |
| **Monitor** | sonnet | Quality validation requires thoroughness | ➡️ |
| **TaskDecomposer** | sonnet | Requires good understanding of requirements | ➡️ |
| **Reflector** | sonnet | Pattern extraction needs reasoning | ➡️ |
| **Curator** | sonnet | Knowledge management requires care | ➡️ |
| **DocumentationReviewer** | sonnet | Documentation analysis needs thoroughness | ➡️ |

### Cost Savings

Using this optimized distribution provides:

- **40-60% cost reduction** vs using sonnet everywhere
- **Maintains quality** for critical tasks (sonnet for actor/monitor/reflector)
- **Fast execution** for analysis tasks (haiku for predictor/evaluator)
- **Balanced performance** for code generation (sonnet for actor/monitor)

### How It Works

Agents automatically use their configured model when invoked via slash commands:

```bash
# Slash commands coordinate workflow and call agents with specific models
/map-feature implement authentication  # Calls: sonnet (actor/monitor) → haiku (predictor/evaluator)
/map-debug fix login bug              # Calls: sonnet (actor/monitor) → haiku (predictor/evaluator)
```

To override model for specific agent:

```bash
# Use haiku for quick prototype
claude --model haiku --agents '{"actor": {"prompt": "$(cat .claude/agents/actor.md)"}}'

# Use opus for critical refactoring
claude --model opus --agents '{"actor": {"prompt": "$(cat .claude/agents/actor.md)"}}'
```

### Cost Comparison Example

**Scenario:** Implement a feature with 5 subtasks

| Approach | TaskDecomposer | Actor (5x) | Monitor (5x) | Predictor (5x) | Evaluator (5x) | Reflector (5x) | Curator (5x) | Total Cost* |
|----------|----------------|------------|--------------|----------------|----------------|----------------|--------------|-------------|
| All Opus | opus | opus | opus | opus | opus | opus | opus | ~$3.00 |
| All Sonnet | sonnet | sonnet | sonnet | sonnet | sonnet | sonnet | sonnet | ~$0.60 |
| **Optimized** | **sonnet** | **sonnet** | **sonnet** | **haiku** | **haiku** | **sonnet** | **sonnet** | **~$0.40** |

*Approximate costs based on typical token usage

**Savings: 33% vs all-sonnet, 87% vs all-opus**

---

## Additional Resources

- **[README.md](README.md)** — Project overview and installation
- **[INSTALL.md](INSTALL.md)** — Detailed installation instructions
- **[Sequential Thinking Integration Guide](docs/SEQUENTIAL_THINKING_GUIDE.md)** — When and how MAP agents use structured reasoning for complex analysis
- **[Context Engineering Improvements](docs/CONTEXT-ENGINEERING-IMPROVEMENTS.md)** — Advanced optimization techniques
- **[Agent Customization](.claude/agents/README.md)** — Customizing agent behavior
