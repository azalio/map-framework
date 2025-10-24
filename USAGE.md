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
- [Best Practices](#best-practices)
  - [Clear Requirements](#1-clear-requirements)
  - [Incremental Approach](#2-incremental-approach)
  - [Provide Context](#3-provide-context)
- [Cost Optimization](#cost-optimization)
  - [Model Distribution Strategy](#model-distribution-strategy)
  - [Cost Savings](#cost-savings)
  - [How It Works](#how-it-works)
  - [Cost Comparison Example](#cost-comparison-example)

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

```bash
# Statistics
mapify playbook stats

# Search patterns
mapify playbook search "JWT authentication"

# High-quality patterns
mapify playbook sync
```

**Note:** These commands help you:
- View playbook statistics (total patterns, average quality)
- Search for specific implementation patterns
- Sync high-quality patterns between playbook and cipher

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
- **[Context Engineering Improvements](docs/CONTEXT-ENGINEERING-IMPROVEMENTS.md)** — Advanced optimization techniques
- **[Agent Customization](.claude/agents/README.md)** — Customizing agent behavior
