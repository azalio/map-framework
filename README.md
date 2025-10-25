# MAP Framework for Claude Code

Implementation of **Modular Agentic Planner (MAP)** — a cognitive architecture for AI agents inspired by prefrontal cortex functions. Orchestrates 8 specialized agents for development with automatic quality validation.

> **Based on:** [Nature Communications research (2025)](https://github.com/Shanka123/MAP) — 74% improvement in planning tasks
> **Enhanced with:** [ACE (Agentic Context Engineering)](https://arxiv.org/abs/2510.04618v1) — continuous learning from experience

## 📖 Documentation Structure

- **README** (this file) - Quick start and overview
- **[INSTALL.md](docs/INSTALL.md)** - Complete installation guide with PATH setup and troubleshooting
- **[ARCHITECTURE.md](docs/ARCHITECTURE.md)** - Technical deep dive, customization, and MCP integration
- **[USAGE.md](docs/USAGE.md)** - Practical examples, best practices, and cost optimization

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

MAP Framework works exclusively through slash commands in Claude Code:

```bash
# Start Claude Code in your project directory
cd your-project
claude

# Use slash commands inside Claude Code
/map-feature implement user authentication with JWT tokens
```

**Note:** Direct `claude --agents` syntax is not applicable to MAP Framework, as the orchestration logic is implemented in slash command prompts (`.claude/commands/map-*.md`), not as a separate agent file.

## 📦 Installation

```bash
# Install UV if not already installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install mapify
uv tool install --from git+https://github.com/azalio/map-framework.git mapify-cli

# Verify installation. If not found, see INSTALL.md for PATH setup
mapify --version

# Initialize in your project
cd your-project
mapify init
```

**Other installation methods** (clone repository, manual copy): See [INSTALL.md](docs/INSTALL.md)

## Requirements

- **Claude Code CLI** — installed and configured
- **Python 3.11+** — for mapify CLI (optional)
- **Git** — for cloning repository

## 🏗️ Architecture

MAP Framework orchestrates 8 specialized agents through slash commands:

- **TaskDecomposer** breaks goals into subtasks
- **Actor** generates code, **Monitor** validates quality
- **Predictor** analyzes impact, **Evaluator** scores solutions
- **Reflector/Curator** enable continuous learning via ACE playbook

The orchestration logic lives in `.claude/commands/map-*.md` prompts, coordinating agents via the Task tool.

**See [ARCHITECTURE.md](docs/ARCHITECTURE.md) for:**
- Detailed agent specifications and responsibilities
- MCP integration architecture and tool usage patterns
- Agent coordination protocol and workflow stages
- Template customization guide with examples
- Hooks integration (automated validation, knowledge storage, context enrichment)
- Context engineering principles and optimizations

## 🔌 MCP Integration

MAP uses MCP (Model Context Protocol) servers for enhanced capabilities:

- **cipher** - Knowledge base for storing and retrieving successful patterns
- **claude-reviewer** - Professional code review with security analysis
- **context7** - Up-to-date library documentation
- **sequential-thinking** - Chain-of-thought reasoning for complex problems
- **codex-bridge** - AI code generation (requires extended timeout)
- **deepwiki** - GitHub repository intelligence

Configuration files: `.claude/mcp_config.json` and `mcp_config.json`

**See [ARCHITECTURE.md](docs/ARCHITECTURE.md#mcp-integration) for complete setup and usage patterns**

## 📚 Usage Examples

```bash
# Feature development
/map-feature implement user profile page with avatar upload

# Bug fixing
/map-debug debug why payment processing fails for amounts over $1000

# Refactoring
/map-refactor refactor OrderService to use dependency injection
```

**See [USAGE.md](docs/USAGE.md) for:**
- Comprehensive usage examples with detailed scenarios
- Best practices for optimal results
- Cost optimization strategies (40-60% savings)
- Playbook management commands

## 🎓 ACE Playbook

Built-in learning system that improves with each task:

- **Reflector** extracts patterns from successes and failures
- **Curator** maintains structured knowledge base with quality tracking
- **Semantic search** (optional) finds patterns by meaning, not keywords
- Automatically grows high-quality pattern library

### Playbook Commands

```bash
# View statistics
mapify playbook stats

# Search patterns
mapify playbook search "JWT authentication"

# View high-quality patterns
mapify playbook sync
```

**Optional semantic search**: `pip install -r requirements-semantic.txt` for meaning-based matching. Details in [SEMANTIC_SEARCH_SETUP.md](docs/SEMANTIC_SEARCH_SETUP.md) and [ARCHITECTURE.md](docs/ARCHITECTURE.md#semantic-search).

**Playbook configuration**: See [ARCHITECTURE.md](docs/ARCHITECTURE.md#playbook-configuration) for top_k settings and optimization.

## 💰 Cost Optimization

MAP Framework uses intelligent model selection per agent:

- **Predictor & Evaluator** use **haiku** (fast analysis) → ⬇️⬇️⬇️ cost
- **Actor, Monitor, Reflector, Curator** use **sonnet** (quality-critical) → balanced cost

**Result:** 40-60% cost reduction vs all-sonnet while maintaining code quality.

**See [USAGE.md](docs/USAGE.md#cost-optimization) for detailed cost breakdown and model override strategies**

## 🔗 Hooks Integration

MAP integrates with Claude Code hooks for automated validation, knowledge storage, and context enrichment. Active hooks protect template variables, auto-store successful patterns, enrich prompts with relevant knowledge, and track performance metrics.

**See [ARCHITECTURE.md](docs/ARCHITECTURE.md#hooks-integration) and [.claude/hooks/README.md](.claude/hooks/README.md) for configuration**

## 🛠️ Troubleshooting

### Command Not Found

```
Error: Slash command not recognized
```

**Solution:**
- Ensure you're in a directory with `.claude/commands/` containing `map-*.md` files
- Use `/map-feature`, `/map-debug`, `/map-refactor`, or `/map-review`
- Run `/help` to see available commands

### Agent Not Found

```
Error: Agent file not found
```

**Solution:** Ensure `.claude/agents/` directory contains all 8 agent files (task-decomposer.md, actor.md, monitor.md, predictor.md, evaluator.md, reflector.md, curator.md, documentation-reviewer.md)

### Semantic Search Warning

```
Warning: sentence-transformers not installed
```

**Solution:** `pip install -r requirements-semantic.txt`
See [SEMANTIC_SEARCH_SETUP.md](docs/SEMANTIC_SEARCH_SETUP.md) for detailed troubleshooting

### Infinite Loops

```
Actor-Monitor loop exceeding iterations
```

**Solution:** Orchestrator limits iterations to 3-5. Clarify requirements or add constraints.

**More troubleshooting**: See [INSTALL.md](docs/INSTALL.md#troubleshooting) for PATH issues, MCP configuration, and installation problems

## 🔧 Customization

Agent prompts in `.claude/agents/*.md` use Handlebars template syntax for dynamic context injection. You can safely modify instructions, examples, and validation criteria, but **MUST NOT remove template variables** like `{{language}}`, `{{#if playbook_bullets}}`, or `{{feedback}}` — these are critical for orchestration and ACE learning.

**See [ARCHITECTURE.md](docs/ARCHITECTURE.md#customization-guide) for:**
- Safe vs unsafe modifications with examples
- Template variable reference
- Model selection per agent
- Adding custom agents
- Template validation and git hooks

## 📊 Success Metrics

- **Monitor approval rate:** >80% first try
- **Evaluator scores:** average >7.0/10
- **Iteration count:** <3 per subtask
- **Playbook growth:** increasing high-quality patterns

## 🤝 Contributing

Improvements welcome:
- Prompts for specific languages/frameworks
- New specialized agents
- CI/CD integrations
- Success story examples
- Plugin extensions for MAP Framework

## 📄 License

MIT License — see LICENSE file for details

## 🔗 References

- [MAP Paper - Nature Communications](https://github.com/Shanka123/MAP)
- [ACE Paper - arXiv:2510.04618v1](https://arxiv.org/abs/2510.04618v1)
- [Claude Code Documentation](https://docs.anthropic.com/en/docs/claude-code)

---

**MAP is not just automation — it's systematic quality improvement through structured validation and iterative refinement.**
