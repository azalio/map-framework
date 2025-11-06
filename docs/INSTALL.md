# 🚀 MAP Framework Installation Guide

The MAP Framework can be installed in any project to provide powerful AI-driven development capabilities using the Modular Agentic Planner architecture.

## Prerequisites

- Python 3.11 or higher
- Git (optional, for repository initialization)
- Claude Code CLI

## Quick Install

### Option 1: Using UV Tool (Recommended)

Install the `mapify` CLI tool globally and use it to set up projects:

```bash
# Install mapify CLI
uv tool install --from git+https://github.com/azalio/map-framework.git mapify-cli

# Create a new project with MAP Framework
mapify init my-project

# Or initialize in current directory
mapify init .
```

<details>
<summary><b>⚠️ Important: PATH Configuration</b></summary>

After installation, you may need to add UV's bin directory to your PATH.

#### Verify Installation

Check if `mapify` is accessible:

```bash
which mapify
```

**Expected output:** `/Users/your-username/.local/bin/mapify` (macOS/Linux) or `C:\Users\your-username\.local\bin\mapify` (Windows)

If the command is not found, you need to add `~/.local/bin` to your PATH.

#### Quick Fix: Automatic PATH Setup

UV provides a helper command to automatically configure your shell:

```bash
uv tool update-shell
```

This will update your shell configuration file (`.zshrc`, `.bashrc`, etc.) automatically.

#### Manual PATH Setup

If you prefer manual configuration, add the following to your shell configuration file:

**For Zsh (macOS default, Linux):**

```bash
# Add to ~/.zshrc
export PATH="$HOME/.local/bin:$PATH"
```

**For Bash (Linux, older macOS):**

```bash
# Add to ~/.bashrc or ~/.bash_profile
export PATH="$HOME/.local/bin:$PATH"
```

**For Fish:**

```fish
# Add to ~/.config/fish/config.fish
set -gx PATH $HOME/.local/bin $PATH
```

**For Windows (PowerShell):**

```powershell
# Run in PowerShell as Administrator
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
$newPath = "$env:USERPROFILE\.local\bin"
if ($userPath -notlike "*$newPath*") {
    [Environment]::SetEnvironmentVariable("Path", "$userPath;$newPath", "User")
    Write-Host "Added $newPath to user PATH"
} else {
    Write-Host "$newPath already in PATH"
}
```

#### Apply Changes

After editing your shell configuration file, apply the changes:

```bash
# For Zsh
source ~/.zshrc

# For Bash
source ~/.bashrc

# Or simply open a new terminal window
```

#### Verify PATH Configuration

Confirm `mapify` is now accessible:

```bash
mapify --version
```

**Expected output:**

```
mapify-cli version x.x.x
```

**Troubleshooting:**

- If `which mapify` shows the path but `mapify` doesn't work, check file permissions: `ls -la ~/.local/bin/mapify`
- If using a custom shell or environment, ensure `UV_TOOL_BIN_DIR` is not set to a different location
- For Docker/CI environments, consider setting `UV_TOOL_BIN_DIR=/usr/local/bin` for system-wide access

</details>

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

**Note:** MAP Framework is designed for Claude Code. All generated agents and commands are optimized for the Claude Code CLI.

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

# Force overwrite existing files in current directory
mapify init . --force
```

### Advanced Options

```bash
# Skip git initialization
mapify init my-project --no-git

# Combine options
mapify init my-project --mcp all --no-git
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
   │   │   ├── reflector.md          # ACE: Extracts lessons
   │   │   └── curator.md            # ACE: Manages playbook
   │   ├── commands/
   │   │   ├── map-feature.md        # Main workflow entry point
   │   │   ├── map-debug.md          # Debug workflow entry point
   │   │   ├── map-refactor.md       # Refactor workflow entry point
   │   │   └── map-review.md         # Review workflow entry point
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

### Workflow Architecture

MAP Framework uses **slash commands** as entry points that coordinate specialized agents in the main Claude Code context:

- **`/map-feature`** - Orchestrates task-decomposer → actor → monitor → predictor → evaluator → reflector → curator
- **`/map-debug`** - Orchestrates diagnostic and fix workflows with agent coordination
- **`/map-refactor`** - Orchestrates refactoring workflows with impact analysis
- **`/map-review`** - Comprehensive review with MAP analysis

**Note:** Agents are invoked automatically by slash commands. Direct agent invocation is not the recommended approach—use the slash commands above for proper workflow orchestration.

### Learning System (ACE Playbook)

MAP automatically learns from your work through the ACE (Agentic Context Engineering) playbook:

```bash
# View playbook statistics
mapify playbook stats

# Search for relevant patterns
mapify playbook search "JWT authentication"

# View high-quality patterns ready for sync
mapify playbook sync
```

The playbook is stored in `.claude/playbook.json` and grows as you use MAP commands.

## MCP Server Setup

If you selected MCP servers during installation, ensure they're configured:

### Cipher (Knowledge Management)

**Overview:**

- Stores successful patterns and solutions
- Retrieves relevant past implementations
- Builds institutional knowledge over time
- Enables cross-project learning through semantic search

**Quick Setup:**

```bash
# Install Cipher globally
npm install -g @byterover/cipher

# Verify installation
cipher --version
```

**Backend Infrastructure (Optional but Recommended):**

Cipher can work with in-memory storage, but for production use we recommend setting up persistent backends:

- **Qdrant**: Vector database for semantic search
- **PostgreSQL**: Relational database for structured memory data

**📚 Full Installation Guide:**
For complete setup instructions including Qdrant + PostgreSQL backend, configuration examples for different LLM providers, troubleshooting, and integration with MAP Framework:

→ **[MCP Cipher + Qdrant + PostgreSQL Setup Guide](QUICKSTART-CIPHER.md)**

This comprehensive guide includes:

- Docker infrastructure setup
- Cipher installation and configuration
- Claude Code MCP integration
- Verification checklist
- Troubleshooting guide
- Performance optimization tips

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

If you get `zsh: command not found: mapify` or `bash: mapify: command not found`, this is usually a PATH configuration issue.

**Diagnosis:**

```bash
# Check if mapify binary exists
ls ~/.local/bin/mapify

# Check if ~/.local/bin is in your PATH
echo $PATH | grep ".local/bin"
```

**Solution 1: Add UV bin directory to PATH** (Recommended)

See the [PATH Configuration section](#important-path-configuration) above for detailed shell-specific instructions, or use UV's automatic setup:

```bash
uv tool update-shell
```

Then open a new terminal or run:

```bash
source ~/.zshrc  # or ~/.bashrc for Bash
```

**Solution 2: Use full path as workaround**

```bash
~/.local/bin/mapify --version
```

**Solution 3: Check custom UV_TOOL_BIN_DIR**

If you've set a custom `UV_TOOL_BIN_DIR`, check that location instead:

```bash
echo $UV_TOOL_BIN_DIR
ls $UV_TOOL_BIN_DIR/mapify
```

**Solution 4: Reinstall mapify**

If the binary doesn't exist, reinstall:

```bash
# Ensure UV is installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Reinstall mapify
uv tool install --from git+https://github.com/azalio/map-framework.git mapify-cli
```

**Verify the fix:**

```bash
mapify --version
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
