# 🚀 MAP Framework Installation Guide

The MAP Framework can be installed in any project to provide powerful AI-driven development capabilities using the Modular Agentic Planner architecture.

## Prerequisites

- Python 3.11 or higher
- Git (optional, for repository initialization)
- Claude Code CLI or another supported AI assistant

## Quick Install

### Option 1: Using UV Tool (Recommended)

Install the `mapify` CLI tool globally and use it to set up projects:

```bash
# Install mapify CLI
uv tool install mapify-cli --from git+https://github.com/azalio/map-framework.git

# Create a new project with MAP Framework
mapify init my-project

# Or initialize in current directory
mapify init .
```

### Option 2: Direct UV Execution

Run without installing:

```bash
# One-time usage
uvx --from git+https://github.com/azalio/map-framework.git mapify init my-project
```

## Installation Options

### Basic Installation

```bash
mapify init my-project
```

This will:

- ✅ Create project directory
- ✅ Install 9 MAP agents (including ACE Reflector & Curator)
- ✅ Add 4 slash commands
- ✅ Configure essential MCP servers
- ✅ Initialize git repository
- ✅ Create ACE playbook structure

### Custom AI Assistant

```bash
# For Claude Code (default)
mapify init my-project --ai claude

# For Cursor
mapify init my-project --ai cursor

# For Windsurf
mapify init my-project --ai windsurf

# For any AI assistant
mapify init my-project --ai generic
```

### MCP Server Configuration

Choose which MCP servers to enable:

```bash
# All available MCP servers
mapify init my-project --mcp all

# Essential servers only (cipher, claude-reviewer, sequential-thinking)
mapify init my-project --mcp essential

# Documentation servers (context7, deepwiki)
mapify init my-project --mcp docs

# Specific servers
mapify init my-project --mcp "cipher,context7,deepwiki"

# No MCP servers
mapify init my-project --mcp none
```

### Current Directory Installation

```bash
# Initialize in current directory
mapify init .

# Or use --here flag
mapify init --here

# Force overwrite existing files
mapify init --here --force
```

### Advanced Options

```bash
# Skip git initialization
mapify init my-project --no-git

# Combine options
mapify init my-project --ai claude --mcp all --no-git
```

## Manual Installation

If you prefer manual setup:

1. **Download the latest release:**

   ```bash
   wget https://github.com/azalio/map-framework/releases/latest/download/map-kit-template-claude.zip
   ```

2. **Extract to your project:**

   ```bash
   unzip map-kit-template-claude.zip -d your-project/
   cd your-project
   ```

3. **The structure will be:**

   ```
   your-project/
   ├── .claude/
   │   ├── agents/
   │   │   ├── task-decomposer.md
   │   │   ├── actor.md
   │   │   ├── monitor.md
   │   │   ├── predictor.md
   │   │   ├── evaluator.md
   │   │   ├── orchestrator.md
   │   │   ├── reflector.md          # ACE: Extracts lessons
   │   │   └── curator.md            # ACE: Manages playbook
   │   ├── commands/
   │   │   ├── map-feature.md
   │   │   ├── map-debug.md
   │   │   ├── map-refactor.md
   │   │   └── map-review.md
   │   ├── mcp_config.json
   │   └── playbook.json              # ACE: Knowledge base
   ```

## Verify Installation

Check that everything is installed correctly:

```bash
mapify check
```

Output should show:

```
Check Available Tools
● Git version control       (available)
● Claude Code CLI          (available)

✅ All tools are installed! MAP Framework is ready to use.
```

## Using MAP Framework

After installation, you can use MAP commands in Claude Code:

### Slash Commands

```bash
# Implement a new feature
/map-feature Add user authentication with JWT tokens

# Debug an issue
/map-debug Fix API timeout on large file uploads

# Refactor code
/map-refactor Convert callbacks to async/await

# Review changes
/map-review
```

### Direct Agent Usage

```bash
# Use the orchestrator directly
claude "Use the orchestrator agent to implement a caching layer"

# Use specific agents
claude "Use task-decomposer to break down: Add payment processing"
claude "Use monitor agent to review the recent changes"
```

### Learning System (ACE Playbook)

MAP automatically learns from your work through the ACE (Agentic Context Engineering) playbook:

```bash
# View playbook statistics
python -m mapify_cli.playbook_manager stats

# Search for relevant patterns
python -m mapify_cli.playbook_manager search "JWT authentication"

# View high-quality patterns ready for sync
python -m mapify_cli.playbook_manager sync
```

The playbook is stored in `.claude/playbook.json` and grows as you use MAP commands.

## MCP Server Setup

If you selected MCP servers during installation, ensure they're configured:

### Cipher (Knowledge Management)

- Stores successful patterns and solutions
- Retrieves relevant past implementations
- Builds institutional knowledge over time

### Claude-Reviewer (Professional Review)

- Automated security and quality analysis
- Historical review tracking
- Focused review on specific areas

### Sequential-Thinking (Chain-of-Thought)

- Complex problem decomposition
- Iterative refinement of solutions
- Edge case discovery

### Context7 (Library Documentation)

- Current API references for any library
- Version-specific documentation
- Migration guides

### Deepwiki (GitHub Intelligence)

- Read documentation from any GitHub repo
- Analyze architectural patterns
- Learn from production implementations

## ACE Playbook (Knowledge Management)

The MAP Framework includes an ACE-style playbook that learns from every task:

- **Reflector agent**: Extracts lessons from successes and failures
- **Curator agent**: Maintains structured knowledge base with delta updates
- **Playbook storage**: `.claude/playbook.json` with 9 pattern categories:
  - ARCHITECTURE_PATTERNS
  - IMPLEMENTATION_PATTERNS
  - SECURITY_PATTERNS
  - PERFORMANCE_PATTERNS
  - ERROR_PATTERNS
  - TESTING_STRATEGIES
  - CODE_QUALITY_RULES
  - TOOL_USAGE
  - DEBUGGING_TECHNIQUES

The playbook automatically grows as you use MAP commands and validates patterns with helpful/harmful counters.

## Optional: Semantic Search

For enhanced pattern retrieval using semantic similarity instead of keyword matching:

```bash
# Install semantic search dependencies
pip install -r requirements-semantic.txt
```

**What you get:**
- 🎯 Meaning-based search (not just keywords)
- 🧠 Synonym understanding: "JWT signature" ≈ "token verification"
- ⚡ Automatic deduplication of similar patterns (90% threshold)
- 💾 Fast embedding cache (`.claude/embeddings_cache/`)

**Technical Details:**
- Model: `all-MiniLM-L6-v2` (80MB, 384 dimensions)
- Speed: ~3000 sentences/second on CPU
- First run downloads ~500MB model (works offline afterwards)

**Fallback:** If not installed, MAP uses keyword matching automatically.

**Troubleshooting:** See [SEMANTIC_SEARCH_SETUP.md](SEMANTIC_SEARCH_SETUP.md) for:
- HuggingFace authentication issues
- Keras 3 compatibility fixes
- Model download problems

## Updating MAP Framework

To update to the latest version:

```bash
# Reinstall mapify with latest version
uv tool upgrade mapify-cli

# Update agents in existing project
mapify init . --force
```

## Troubleshooting

### Issue: Command not found

```bash
# Ensure UV is installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Reinstall mapify
uv tool install mapify-cli --from git+https://github.com/azalio/map-framework.git
```

### Issue: Claude Code not detected

```bash
# Check Claude installation
which claude

# If using local installation after migrate-installer
ls ~/.claude/local/claude
```

### Issue: MCP servers not working

Check that MCP servers are properly configured in your Claude Code settings. The configuration file is at `.claude/mcp_config.json`.

### Issue: Semantic search not working

```bash
# Check if dependencies are installed
pip list | grep sentence-transformers

# Install if missing
pip install -r requirements-semantic.txt

# Verify installation
python -c "from mapify_cli.playbook_manager import PlaybookManager; m = PlaybookManager(); print('✓' if m.semantic_engine else '✗')"
```

Should output `✓ Semantic search enabled`.

For detailed troubleshooting, see [SEMANTIC_SEARCH_SETUP.md](SEMANTIC_SEARCH_SETUP.md).

## Uninstalling

To remove MAP Framework:

```bash
# Remove from project
rm -rf .claude/agents/
rm -rf .claude/commands/
rm .claude/mcp_config.json
rm .claude/playbook.json
rm -rf .claude/embeddings_cache/

# Uninstall mapify CLI
uv tool uninstall mapify-cli
```

## Support

- GitHub Issues: <https://github.com/azalio/map-framework/issues>
- Documentation: <https://github.com/azalio/map-framework>
- Community: Discussions on GitHub

## License

MIT License - See LICENSE file for details
