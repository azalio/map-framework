# MAP Framework for Claude Code

Implementation of **Modular Agentic Planner (MAP)** — a cognitive architecture for AI agents inspired by prefrontal cortex functions. Orchestrates 9 specialized agents for development with automatic quality validation.

> **Based on:** [Nature Communications research (2025)](https://github.com/Shanka123/MAP) — 74% improvement in planning tasks
> **Enhanced with:** [ACE (Agentic Context Engineering)](https://arxiv.org/abs/2510.04618v1) — continuous learning from experience

## 🚀 Quick Start

### Inside Claude Code (Recommended)

```bash
# Feature development
/map-feature implement user authentication with JWT tokens

# Debugging
/map-debug fix the API 500 error on login endpoint

# Refactoring
/map-refactor refactor UserService class with dependency injection

# Code review
/map-review review the recent changes in auth.py
```

### Command Line Usage

```bash
claude --agents '{"orchestrator": {"prompt": "$(cat .claude/agents/orchestrator.md)"}}' \
  --print "implement user authentication with JWT tokens"
```

## 📦 Installation

### Option 1: Via Claude Code Plugin Marketplace (Easiest)

```bash
# In Claude Code:
/plugin marketplace add https://raw.githubusercontent.com/azalio/map-framework/main/.claude-plugin/marketplace.json
/plugin install map-framework

# Then initialize in your project:
mapify init
```

### Option 2: Via mapify CLI (Recommended)

```bash
# Install UV if not already installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install mapify
uv tool install --from git+https://github.com/azalio/map-framework.git mapify-cli

# Initialize in your project
cd your-project
mapify init

# Note: The repository includes .mcp.json.example with sample MCP server configurations.
# Copy and adjust it if you need project-specific MCP settings.
```

### Option 3: Clone Repository

```bash
git clone https://github.com/azalio/map-framework.git
cd map-framework

# Start Claude Code in this directory
claude
```

### Option 4: Copy Agents to Existing Project

```bash
# Copy agents
cp -r /path/to/map-framework/.claude/agents your-project/.claude/
cp -r /path/to/map-framework/.claude/commands your-project/.claude/

# Configure MCP servers (see MCP Integration section)
```

## Requirements

- **Claude Code CLI** — installed and configured
- **Python 3.11+** — for mapify CLI (optional)
- **Git** — for cloning repository

## 🏗️ Architecture

9 specialized agents working together:

```
┌──────────────────────────────────────────┐
│          ORCHESTRATOR                    │
│    (coordinates entire workflow)         │
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

### Agents

1. **TaskDecomposer** — breaks goals into atomic subtasks
2. **Actor** — generates code and solutions
3. **Monitor** — validates quality, security, correctness
4. **Predictor** — analyzes change impact across codebase
5. **Evaluator** — scores solution quality (functionality, security, testability)
6. **Reflector** — extracts lessons from successes and failures
7. **Curator** — manages knowledge base (playbook)
8. **Orchestrator** — coordinates all agents
9. **DocumentationReviewer** — checks documentation completeness and correctness

## 🔌 MCP Integration

MAP uses MCP (Model Context Protocol) servers for enhanced capabilities:

| MCP Server | Purpose |
|------------|---------|
| **cipher** | Knowledge base — stores successful patterns and solutions |
| **claude-reviewer** | Professional code review with security analysis |
| **sequential-thinking** | Chain-of-thought reasoning for complex problems |
| **codex-bridge** | Code generation (⚠️ requires 10-minute timeout) |
| **context7** | Up-to-date library documentation |
| **deepwiki** | GitHub repository analysis |

### MCP Configuration

MCP servers are configured in `.claude/mcp_config.json`. Example:

```json
{
  "mcpServers": {
    "cipher": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-memory"]
    }
  }
}
```

**Note:** MCP server availability depends on your Claude Code installation. Some servers may be built-in, others require separate installation. Check Claude Code documentation for current information.

### Benefits

- 🧠 **Persistent Knowledge** — solutions are saved and reused
- 🔍 **Professional Review** — automatic security and quality analysis
- 🔄 **Continuous Learning** — each workflow improves future ones
- ⚡ **Faster Development** — reuse proven patterns

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

## 🎓 ACE Playbook

Built-in learning system based on ACE:

- **Reflector** extracts patterns from each task
- **Curator** updates knowledge base incrementally
- **Semantic search** finds relevant patterns by meaning
- **Quality tracking** monitors pattern effectiveness

### Semantic Search (Optional)

For meaning-based search instead of keywords:

```bash
pip install -r requirements-semantic.txt
```

**Benefits:**
- 🎯 Search by meaning: "JWT signature" ≈ "token verification"
- 🧠 Auto-deduplication of similar patterns (>90% similarity)
- ⚡ Embedding cache for fast retrieval

**Technical details:**
- Model: `all-MiniLM-L6-v2` (80MB, ~500MB on first download)
- Speed: ~3000 sentences/sec on CPU
- Cache: `.claude/embeddings_cache/`

Falls back to keyword matching if not installed.

Details in [SEMANTIC_SEARCH_SETUP.md](SEMANTIC_SEARCH_SETUP.md)

### Playbook Commands

```bash
# Statistics
python -m mapify_cli.playbook_manager stats

# Search patterns
python -m mapify_cli.playbook_manager search "JWT authentication"

# High-quality patterns
python -m mapify_cli.playbook_manager sync
```

### Playbook Configuration

The playbook behavior can be configured via `.claude/playbook.json` metadata:

**top_k** - Limits number of patterns retrieved to reduce context distraction (Phase 1.3):

```json
{
  "metadata": {
    "top_k": 5
  }
}
```

- **Default:** 5 patterns (balances context quality vs. quantity)
- **Purpose:** Reduces context distraction and saves ~15% tokens
- **Override:** Can be overridden per-call: `get_relevant_bullets(query, limit=10)`
- **Based on:** Context Engineering improvements (Phase 1.3)

**Benefits:**
- 🎯 Focused context - fewer, more relevant patterns
- 💰 Token savings - ~15% reduction in Actor prompts
- 🧠 Less distraction - model focuses on best patterns

**Customization:**
- Set to 3 for simple tasks (minimal context)
- Set to 5 for balanced approach (recommended default)
- Set to 7-10 for complex tasks requiring more patterns

## 🎯 Best Practices

### 1. Clear Requirements

```bash
# Good ✅
"Implement registration with email validation, password strength check (8+ chars, 1 number), send confirmation"

# Bad ❌
"Add registration"
```

### 2. Incremental Approach

Break large features into phases:
- Phase 1: Core functionality
- Phase 2: Edge cases and error handling
- Phase 3: Optimization

### 3. Provide Context

Always specify:
- Technology stack
- Existing patterns
- Constraints
- Performance requirements

## 💰 Cost Optimization

MAP Framework supports intelligent model selection per agent to balance capability and cost:

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
| **TestGenerator** | sonnet | Test quality is important | ➡️ |
| **Orchestrator** | opus | Critical workflow decisions | ⬆️ |

### Cost Savings

Using this optimized distribution provides:
- **40-60% cost reduction** vs using sonnet everywhere
- **Maintains quality** for critical tasks (orchestrator uses opus)
- **Fast execution** for analysis tasks (haiku for predictor/evaluator)
- **Balanced performance** for code generation (sonnet for actor/monitor)

### How It Works

Agents automatically use their configured model when invoked via slash commands:

```bash
# Slash commands use agent-specific models automatically
/map-feature implement authentication  # Uses opus orchestrator → sonnet actors
/map-debug fix login bug              # Uses opus orchestrator → sonnet actors
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

| Approach | Orchestrator | TaskDecomposer | Actor (5x) | Monitor (5x) | Predictor (5x) | Evaluator (5x) | Total Cost* |
|----------|--------------|----------------|------------|--------------|----------------|----------------|-------------|
| All Opus | opus | opus | opus | opus | opus | opus | ~$2.50 |
| All Sonnet | sonnet | sonnet | sonnet | sonnet | sonnet | sonnet | ~$0.50 |
| **Optimized** | **opus** | **sonnet** | **sonnet** | **sonnet** | **haiku** | **haiku** | **~$0.35** |

*Approximate costs based on typical token usage

**Savings: 30% vs all-sonnet, 86% vs all-opus**

## 🔗 Claude Code Hooks Integration

MAP Framework integrates with [Claude Code hooks](https://docs.claude.com/en/docs/claude-code/hooks) for automated validation and workflow protection.

### Available Hooks

#### 🛡️ Agent Template Validation (Active)

**PreToolUse hook** that prevents accidental removal of critical Handlebars template variables from agent files.

**Protects against:**
- Removing `{{language}}`, `{{project_name}}`, `{{framework}}` (breaks Orchestrator context injection)
- Removing `{{#if playbook_bullets}}` (breaks ACE learning system)
- Removing `{{#if feedback}}` (breaks Monitor→Actor retry loops)
- Massive deletions (>500 lines)

**Example:**
```bash
# Claude Code will block this operation:
❌ BLOCKED: Agent file is missing critical template variables!

File: .claude/agents/actor.md
Missing templates:
  - {{language}}
  - {{#if playbook_bullets}}

These template variables are used by Orchestrator for context injection.
See .claude/agents/README.md for details.
```

#### 🔄 Auto-Store Knowledge (Active)

**PostToolUse hook** that automatically saves successful patterns to cipher MCP after modifications.

**How it works:**
- Triggers after successful Edit/Write on code files (.py, .js, .go, etc.)
- Extracts pattern with file path, language, and content
- Stores in cipher automatically - no manual calls needed!

#### 🧠 Context Enrichment (Active)

**UserPromptSubmit hook** that enriches user prompts with relevant patterns from cipher before processing.

**How it works:**
- Extracts keywords from your prompt (implement, fix, refactor, etc.)
- Searches cipher for top 3 relevant patterns
- Enriches prompt with found knowledge before Claude processes it
- Automatic knowledge reuse without manual searches

#### 📊 Session Initialization (Active)

**SessionStart hook** that loads ACE playbook bullets at the beginning of every session.

**What it does:**
- Searches cipher for high-quality patterns (top 10)
- Creates `.claude/sessions/current_context.txt` with project info
- Lists available agents and MCP servers
- Provides welcome message with available commands

#### 📈 Metrics Tracking (Active)

**SubagentStop hook** that tracks MAP agent performance metrics.

**What it tracks:**
- Execution time, success rate, quality scores
- Stores in `.claude/metrics/agent_metrics.jsonl`
- Saves to cipher for long-term trend analysis

### Configuration

Hooks are configured in `.claude/settings.hooks.json` and automatically loaded by Claude Code.

**To disable hooks** (not recommended):
```json
// .claude/settings.local.json
{
  "hooks": {
    "PreToolUse": []
  }
}
```

**See:** [`.claude/hooks/README.md`](.claude/hooks/README.md) for detailed documentation.

## 🛠️ Troubleshooting

### Agent Not Found

```
Error: Agent 'orchestrator' not found
```

**Solution:** Ensure you're in a directory with `.claude/agents/`

### Semantic Search Warning

```
Warning: sentence-transformers not installed
```

**Solution:**
```bash
pip install -r requirements-semantic.txt
```

See [SEMANTIC_SEARCH_SETUP.md](SEMANTIC_SEARCH_SETUP.md) for detailed troubleshooting.

### Infinite Loops

```
Actor-Monitor loop exceeding iterations
```

**Solution:** Orchestrator is limited to 3-5 iterations. Clarify requirements or add constraints.

## 🔧 Customization

### Modifying Agents

Edit files in `.claude/agents/`:

```bash
# Example: make monitor stricter
edit .claude/agents/monitor.md
# Add:
# - OWASP Top 10 compliance required
# - All inputs must be sanitized
```

⚠️ **CRITICAL: Do NOT remove template variables!**

Agent prompts use **Handlebars syntax** (`{{variable}}`, `{{#if condition}}`) for dynamic context injection by Orchestrator:

```markdown
# ❌ NEVER REMOVE:
{{language}}              # Orchestrator injects project language
{{project_name}}          # Orchestrator injects project name
{{#if playbook_bullets}}  # ACE learning system (Curator → Actor)
{{#if feedback}}          # Monitor → Actor retry loops
{{subtask_description}}   # TaskDecomposer output
```

**Why they're critical:**
- Not comments or examples — functional template substitution
- Orchestrator fills these at runtime with project context
- Removing them breaks multi-language support, ACE learning, feedback loops
- Git pre-commit hook validates their presence

**Safe to modify:**
- Add new instructions or examples
- Adjust MCP tool usage guidance
- Update output format specifications
- Add domain-specific requirements

**Unsafe to modify:**
- Any `{{template}}` variables
- Any `{{#if}}...{{/if}}` blocks
- Playbook bullets section
- Feedback section
- Context section

### Prompt Variables

Available template variables:
- `{{project_name}}`
- `{{language}}`
- `{{framework}}`
- `{{standards_url}}`
- `{{playbook_bullets}}`
- `{{feedback}}`
- `{{subtask_description}}`
- `{{allowed_scope}}`

## 📊 Success Metrics

- **Monitor approval rate:** >80% first try
- **Evaluator scores:** average >7.0/10
- **Iteration count:** <3 per subtask
- **Playbook growth:** increasing high-quality patterns

## 🔌 Plugin Marketplace

MAP Framework is available as a Claude Code plugin for easy installation and distribution.

### Install via Plugin Marketplace

```bash
# Add MAP Framework marketplace
/plugin marketplace add https://raw.githubusercontent.com/azalio/map-framework/main/.claude-plugin/marketplace.json

# Install the plugin
/plugin install map-framework

# Initialize in your project
mapify init
```

### Plugin Features

- **One-command installation** — no manual file copying
- **Automatic updates** — get latest agents and hooks via marketplace
- **Team distribution** — share MAP configuration via `.claude/settings.json`
- **Version management** — control which MAP version to use

### For Plugin Developers

To create extensions for MAP Framework:

1. Create a plugin with MAP-compatible agents/skills
2. Reference MAP as a dependency in your `plugin.json`
3. Submit to MAP marketplace or create your own

See [.claude-plugin/PLUGIN.md](.claude-plugin/PLUGIN.md) for plugin documentation.

## 🛠️ Template Maintenance

### Template Linter

Validate agent template consistency:

```bash
python scripts/lint-agent-templates.py
```

The linter checks:
- YAML frontmatter completeness (version, last_updated, changelog)
- Required sections (mcp_integration, context, examples)
- Template variable syntax ({{variable}})
- XML tag matching (<section></section>)
- MCP tool description consistency

### MCP Patterns Reference

See [.claude/agents/MCP-PATTERNS.md](.claude/agents/MCP-PATTERNS.md) for:
- Common MCP tool usage patterns
- Decision frameworks for tool selection
- Agent-specific MCP integration guidelines
- Best practices and anti-patterns

### Template Versioning

All agent templates include version metadata:
```yaml
---
version: 2.0.0
last_updated: 2025-10-17
changelog: .claude/agents/CHANGELOG.md
---
```

See [.claude/agents/CHANGELOG.md](.claude/agents/CHANGELOG.md) for version history.

## 🧠 Context Engineering Improvements

MAP Framework применяет передовые принципы контекстной инженерии для AI-агентов:

### ✨ Новое: Recitation Pattern (Фаза 1.1)

**Проблема:** На длинных задачах (5+ подзадач) модель теряет фокус и забывает цели.

**Решение:** Механизм фокусировки внимания — `.map/current_plan.md` обновляется перед каждым шагом, держа цели "свежими" в контексте.

```markdown
# Current Task: feat_auth
## Progress: 2/5 completed
- [✓] 1/5: Create User model
- [→] 2/5: Implement login (CURRENT, Iteration 2)
  - Last error: Missing JWT import
- [☐] 3/5: Add token validation
...
```

**Эффект:**
- +20-30% success rate на сложных задачах
- -20-30% использование токенов
- +50% наблюдаемость прогресса

### 📚 Документация

- **[Context Engineering Improvements](docs/CONTEXT-ENGINEERING-IMPROVEMENTS.md)** — полный план (94 стр)
- **[Recitation Pattern](docs/RECITATION-PATTERN.md)** — документация паттерна (50 стр)
- **[Quick Start](docs/context-engineering/README.md)** — быстрый старт с примерами

### 🗺️ Roadmap

**Фаза 1** (в процессе):
- [x] Recitation Pattern для фокусировки
- [ ] Подробное логирование workflow
- [ ] Ограничение паттернов playbook (3-5)
- [ ] Оптимизация verbose выводов

**Фаза 2-4:** Checkpoints, кеширование MCP, параллелизм, автотесты

**Основано на:** ["Context Engineering for AI Agents" (Manus.im, 2025)](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)

## 🤝 Contributing

Improvements welcome:
- Prompts for specific languages/frameworks
- New specialized agents
- CI/CD integrations
- Success story examples
- Plugin extensions for MAP Framework
- Context engineering optimizations

## 📄 License

MIT License — see LICENSE file for details.

## 🔗 References

- [MAP Paper - Nature Communications](https://github.com/Shanka123/MAP)
- [ACE Paper - arXiv:2510.04618v1](https://arxiv.org/abs/2510.04618v1)
- [Claude Code Documentation](https://docs.anthropic.com/en/docs/claude-code)

---

**MAP is not just automation — it's systematic quality improvement through structured validation and iterative approach.**
