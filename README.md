# MAP Framework for Claude Code

Implementation of **Modular Agentic Planner (MAP)** — a cognitive architecture for AI agents inspired by prefrontal cortex functions. Orchestrates 8 specialized agents for development with automatic quality validation.

> **Based on:** [Nature Communications research (2025)](https://github.com/Shanka123/MAP) — 74% improvement in planning tasks
> **Enhanced with:** [ACE (Agentic Context Engineering)](https://arxiv.org/abs/2510.04618v1) — continuous learning from experience

## 📖 Documentation Structure

- **README** (this file) - Quick start and overview
- **[INSTALL.md](docs/INSTALL.md)** - Complete installation guide with PATH setup and troubleshooting
- **[ARCHITECTURE.md](docs/ARCHITECTURE.md)** - Technical deep dive, customization, and MCP integration
- **[USAGE.md](docs/USAGE.md)** - Practical examples, best practices, cost optimization, and dependency validation

## 🚀 Quick Start

### Inside Claude Code (Recommended)

```bash
# Feature development (full quality - 8 agents)
/map-feature implement user authentication with JWT tokens

# ⭐ RECOMMENDED: Efficient workflow (30-40% token savings, preserves learning)
/map-efficient implement user profile page with avatar upload

# Debugging
/map-debug fix the API 500 error on login endpoint

# Refactoring
/map-refactor refactor UserService class with dependency injection

# Code review
/map-review review the recent changes in auth.py

# ⚠️ Fast workflow (40-50% savings, NO learning - throwaway code only)
/map-fast prototype a quick API endpoint mockup
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

### Stable Release (Recommended)

```bash
# Using pip
pip install mapify-cli

# OR using UV (recommended for isolated tools)
uv tool install mapify-cli

# Verify installation
mapify --version

# Initialize in your project
cd your-project
mapify init

# Available commands
mapify --help                     # Show all available commands
mapify validate graph <file>      # Validate task dependency graphs
mapify playbook search <query>    # Search playbook patterns
mapify recitation get-context     # Get current task plan
```

**Version Pinning:**
```bash
# Install specific version
pip install mapify-cli==1.0.0

# Install with version constraints (semantic versioning: MAJOR.MINOR.PATCH)
pip install "mapify-cli>=1.0.0,<2.0.0"  # Allow 1.x versions, exclude 2.0.0+
```

**Version Information:**
- Check installed version: `mapify --version`
- [PyPI releases](https://pypi.org/project/mapify-cli/) - Available versions and package details
- [GitHub releases](https://github.com/azalio/map-framework/releases) - Changelog and release notes

### Development Installation

For contributors or testing bleeding-edge features:

```bash
# Install from git repository
uv tool install --from git+https://github.com/azalio/map-framework.git mapify-cli

# OR clone and install locally
git clone https://github.com/azalio/map-framework.git
cd map-framework
pip install -e .
```

**Other installation methods** (manual copy, troubleshooting): See [INSTALL.md](docs/INSTALL.md)

**For maintainers**: Release process documented in [RELEASING.md](RELEASING.md)

## 🔀 Workflow Variants

MAP Framework offers three workflow variants optimized for different scenarios:

| Command | Token Usage | Learning | Quality Gates | Best For |
|---------|-------------|----------|---------------|----------|
| **`/map-feature`** | 100% (baseline) | ✅ Full (per-subtask) | ✅ All 8 agents | Critical features, first-time implementations, maximum QA |
| **`/map-efficient`** ⭐ | **60-70%** | ✅ Full (batched) | ✅ Essential agents | **RECOMMENDED: Most production tasks** |
| **`/map-fast`** ⚠️ | 50-60% | ❌ None | ⚠️ Basic only | Throwaway prototypes, experiments (NOT production) |

### Which Workflow Should You Use?

**Use `/map-efficient` (RECOMMENDED) when:**
- ✅ Building production features where token costs matter
- ✅ Well-understood tasks with low to medium risk
- ✅ You want learning without excessive token usage
- ✅ Iterative development with frequent workflows

**Use `/map-feature` (full workflow) when:**
- 🔒 Implementing security-critical functionality
- 🔒 First-time complex features requiring maximum validation
- 🔒 High-risk changes affecting many files
- 🔒 You need complete quality assurance and impact analysis

**Use `/map-fast` (minimal) ONLY when:**
- 🗑️ Creating throwaway prototypes you'll discard
- 🗑️ Quick experiments where quality doesn't matter
- 🗑️ Learning/tutorial contexts where failure is acceptable
- ⚠️ **NEVER for production code** - no learning, quality risks

### 🎯 Auto-Activation System

**Don't remember which workflow to use?** MAP automatically suggests the right workflow based on your request!

Just describe your task naturally - no need to remember slash commands:

| Your Request | MAP Suggests | Why |
|--------------|--------------|-----|
| "Fix the failing tests" | `/map-debug` | Keywords: fix, failing test |
| "Implement user login" | `/map-feature` | Keywords: implement, feature |
| "Optimize database queries" | `/map-efficient` | Keywords: optimize |
| "Restructure auth module" | `/map-refactor` | Keywords: restructure |
| "Quick prototype for testing" | `/map-fast` | Keywords: quick, prototype |

**How it works:**
1. Start typing your request normally
2. MAP analyzes keywords and intent patterns
3. Suggests the most appropriate workflow
4. You can accept the suggestion or proceed with your request

**Customization:**
Edit `.claude/workflow-rules.json` to add project-specific trigger words and patterns.


### Key Differences

**`/map-efficient` optimizations:**
- **Conditional Predictor**: Only called for high-risk tasks (security, breaking changes)
- **Batched Learning**: Reflector/Curator run once at end (vs per-subtask)
- **Evaluator Skipped**: Monitor provides sufficient validation for most tasks
- **Result**: 30-40% token savings while preserving learning and essential quality gates

**`/map-fast` limitations:**
- ❌ No impact analysis (Predictor skipped)
- ❌ No quality scoring (Evaluator skipped)
- ❌ No learning (Reflector/Curator skipped)
- ❌ Playbook never improves
- ❌ Cipher knowledge never accumulates
- ⚠️ **Defeats MAP's core purpose of continuous improvement**

**See [USAGE.md](docs/USAGE.md#workflow-variants) for detailed decision guide and real-world token usage examples.**

## 📚 Skills System

MAP includes interactive skills that provide specialized guidance:

**map-workflows-guide** - Helps you choose the right workflow

**Auto-suggested when you ask:**
- "Which workflow should I use?"
- "What's the difference between workflows?"
- "When to use /map-efficient vs /map-feature?"

**What you get:**
- Quick decision tree (5 questions → recommended workflow)
- Comparison matrix (token cost, learning, agents, use cases)
- 8 detailed resource guides (progressive disclosure)

**Skills vs Agents:**
- **Skills** = Passive documentation (guidance)
- **Agents** = Active execution (code generation)

**See [docs/USAGE.md](docs/USAGE.md#skills-system) for full details.**

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
- **Dependency validation** ensures valid task graphs before execution
- Automatically grows high-quality pattern library

### Playbook Commands

```bash
# View statistics
mapify playbook stats

# Search patterns
mapify playbook search "JWT authentication"

# View high-quality patterns
mapify playbook sync

# Validate task dependencies with visualization
python scripts/validate-dependencies.py decomposer-output.json --visualize
```

**Optional semantic search**: `pip install -r requirements-semantic.txt` for meaning-based matching. Details in [SEMANTIC_SEARCH_SETUP.md](docs/SEMANTIC_SEARCH_SETUP.md) and [ARCHITECTURE.md](docs/ARCHITECTURE.md#semantic-search).

**Playbook configuration**: See [ARCHITECTURE.md](docs/ARCHITECTURE.md#playbook-configuration) for top_k settings and optimization.

**Dependency validation**: See [USAGE.md](docs/USAGE.md#dependency-validation) for comprehensive guide on validating TaskDecomposer output, including cycle detection, visualization, and CI/CD integration.

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
