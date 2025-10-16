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

### Option 1: Via mapify CLI (Recommended)

```bash
# Install UV if not already installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install mapify
uv tool install --from git+https://github.com/azalio/map-framework.git mapify-cli

# Initialize in your project
cd your-project
mapify init
```

### Option 2: Clone Repository

```bash
git clone https://github.com/azalio/map-framework.git
cd map-framework

# Start Claude Code in this directory
claude
```

### Option 3: Copy Agents to Existing Project

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

### Prompt Variables

Available template variables:
- `{{project_name}}`
- `{{language}}`
- `{{framework}}`
- `{{standards_url}}`

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

## 📄 License

MIT License — see LICENSE file for details.

## 🔗 References

- [MAP Paper - Nature Communications](https://github.com/Shanka123/MAP)
- [ACE Paper - arXiv:2510.04618v1](https://arxiv.org/abs/2510.04618v1)
- [Claude Code Documentation](https://docs.anthropic.com/en/docs/claude-code)

---

**MAP is not just automation — it's systematic quality improvement through structured validation and iterative approach.**
