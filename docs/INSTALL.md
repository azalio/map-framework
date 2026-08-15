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
- ✅ Install MAP agents (including Predictor, Evaluator, ResearchAgent, FinalVerifier)
- ✅ Add skill-backed `/map-*` slash surfaces, including `/map-learn` and `/map-understand`
- ✅ Configure essential MCP servers
- ✅ Initialize git repository
- ✅ Install branch-scoped `.map/<branch>/` workflow runtime used by `/map-plan` and `/map-efficient`

**Note:** MAP Framework is designed for Claude Code. All generated agents and commands are optimized for the Claude Code CLI.

### Codex CLI Installation

```bash
mapify init . --provider codex
codex
```

After Codex starts, enable the installed hook manually:

```text
/hooks
PreToolUse
t
Esc
```

This toggles the `PreToolUse` hook on so MAP's workflow gate can run before tool calls.

If your Codex version does not support the `hooks` feature key yet, either start Codex with the deprecated hooks feature alias enabled:

```bash
codex --enable codex_hooks
```

or upgrade Codex first. Upgrading is recommended.

Codex MAP skills do not start with `/`. Type `$map-plan`, `$map-fast`, `$map-check`, or `$map-understand` instead of `/map-plan`, `/map-fast`, `/map-check`, or `/map-understand`.

### MCP Server Configuration

Choose which MCP servers to enable:

```bash
# All available MCP servers
mapify init my-project --mcp all

# Essential servers only (sequential-thinking)
mapify init my-project --mcp essential

# Specific servers
mapify init my-project --mcp "sequential-thinking"

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
   │   ├── agents/                    # 9 specialized agents
   │   │   ├── task-decomposer.md     # Decomposes tasks into subtasks
   │   │   ├── actor.md               # Implements code
   │   │   ├── monitor.md             # Validates implementations
   │   │   ├── predictor.md           # Analyzes impact and risks
   │   │   ├── evaluator.md           # Scores solution quality
   │   │   ├── reflector.md           # Extracts lessons
   │   │   ├── research-agent.md      # Isolated codebase research
   │   │   ├── final-verifier.md      # Adversarial verification (Ralph Loop)
   │   │   └── documentation-reviewer.md  # Reviews technical docs
   │   ├── commands/                  # User-custom commands + MAP skills README
   │   │   └── README.md              # Points /map-* users to skill-backed surfaces
   │   ├── skills/                    # All MAP slash surfaces ship as skills
   │   │   ├── README.md
   │   │   ├── skill-rules.json
   │   │   ├── map-plan/SKILL.md      # ARCHITECT phase (decomposition)
   │   │   ├── map-efficient/SKILL.md # Optimized workflow (recommended)
   │   │   ├── map-fast/SKILL.md      # Minimal workflow (low-risk only)
   │   │   ├── map-task/SKILL.md      # Execute one planned subtask
   │   │   ├── map-tdd/SKILL.md       # Test-first workflow
   │   │   ├── map-debug/SKILL.md     # Debug workflow
   │   │   ├── map-review/SKILL.md    # Review workflow
   │   │   ├── map-check/SKILL.md     # Quality gates & verification
   │   │   ├── map-release/SKILL.md   # Release workflow
   │   │   ├── map-resume/SKILL.md    # Resume interrupted workflows
   │   │   ├── map-learn/SKILL.md     # Persist lessons to .claude/rules/learned/
   │   │   ├── map-understand/SKILL.md # Interactive learning/quiz mode
   │   │   └── map-state/SKILL.md     # Branch-scoped planning state skill
   │   └── mcp_config.json
   ```

   *Note*: MAP may create `.claude/commands/README.md` for custom command
   guidance, but it does not ship `.claude/commands/map-*.md`. Every `/map-*`
   slash surface lives under `.claude/skills/<name>/SKILL.md`. The
   `tests/test_template_sync.py::test_no_map_command_files_remain` test
   enforces this invariant.

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
# Standard production workflow (RECOMMENDED)
/map-efficient Add user authentication with JWT tokens

# Debug an issue
/map-debug Fix API timeout on large file uploads

# Quick low-risk change
/map-fast Implement a small UI tweak

# Review changes
/map-review

# Extract lessons after workflow completion
/map-learn

# Teach and quiz until a target makes sense
/map-understand HEAD~1..HEAD
```

### Workflow Architecture

MAP Framework uses **slash commands** as entry points that coordinate specialized agents in the main Claude Code context:

- **`/map-efficient`** ⭐ - Optimized workflow (5-6 agents): task-decomposer → actor → monitor → predictor (conditional)
- **`/map-debug`** - Diagnostic and fix workflows with agent coordination
- **`/map-fast`** - Minimal workflow (3 agents) — small, low-risk changes (reduced analysis)
- **`/map-review`** - Comprehensive review with Monitor, Predictor, and Evaluator agents
- **`/map-check`** - Quality gates and verification for staged changes
- **`/map-plan`** - Architect phase only: decompose task without implementation
- **`/map-release`** - Package release workflow with validation gates
- **`/map-resume`** - Resume incomplete MAP workflow from checkpoint
- **`/map-learn`** - Extract lessons from completed workflows (implemented as a skill, not a command file)
- **`/map-understand`** - Interactive understanding checklist and quiz mode (transient, no artifact writes)

**Note:** Agents are invoked automatically by slash commands. Direct agent invocation is not the recommended approach—use the slash commands above for proper workflow orchestration.

## MCP Server Setup

If you selected MCP servers during installation, ensure they're configured:

### Sequential-Thinking (Chain-of-Thought)

- Complex problem decomposition
- Iterative refinement of solutions
- Edge case discovery

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

**Troubleshooting:** Common issues include:

- HuggingFace authentication issues (set `HF_TOKEN` if needed)
- Keras 3 compatibility (update to latest sentence-transformers)
- Model download problems (check network connectivity)

## Updating MAP Framework

### Provider-driven project updates

Every installed MAP skill except `map-upgrade` performs a silent automatic
update preflight. Automatic checks are enabled by default, throttled to one
attempt per project in a rolling 24-hour window, and apply eligible stable patch
or minor releases. A major release is offered only after the provider shows its
official release highlights and link, and it is installed only with your explicit
consent.

Control the project setting or bypass the setting and throttle with a manual
provider skill:

```text
mapify init . --no-auto-update   # persist updates.auto: false
mapify init . --auto-update      # re-enable automatic checks
/map-upgrade                     # Claude manual check/upgrade
$map-upgrade                     # Codex manual check/upgrade
```

Omitting both init flags preserves the existing `updates.auto` value. The flag
controls automatic preflights only; manual `map-upgrade` always checks. Automatic
errors are silent and non-blocking, while the manual skill reports a clear error
and recovery action.

### Installation ownership

The project updater follows the installation that owns the running `mapify`
executable:

- A `uv tool` install is updated to an exact validated release with
  `uv tool install --force mapify-cli==X.Y.Z`.
- A pip/site-packages install uses the current interpreter and
  `python -m pip install --upgrade mapify-cli==X.Y.Z`.
- A source checkout or editable install is owner-managed. Automatic mode skips it
  silently; `/map-upgrade` or `$map-upgrade` explains that you must update the
  checkout yourself and then refresh the project. MAP never runs `git pull` or
  mutates a source checkout on your behalf.

After a successful package update, MAP launches the newly installed `mapify` in a
fresh process and refreshes every provider already installed in the project. A
project containing both Claude and Codex therefore keeps both skill catalogs and
a combined install manifest.

### Public CLI self-upgrade

Upgrade the `mapify` CLI itself to the latest release:

```bash
# Self-upgrade the mapify CLI (auto-detects uv tool vs pip install)
mapify upgrade

# Then refresh an existing project's shipped MAP files with the new templates
mapify init . --force
```

`mapify upgrade` detects how the tool was installed and runs the right command
for you. The equivalent manual commands are:

```bash
uv tool upgrade mapify-cli                    # if installed via `uv tool`
python -m pip install --upgrade mapify-cli    # if installed via pip
```

> Running `mapify upgrade` from a source checkout / editable install disables
> self-upgrade — update that clone with `git pull` instead.

This public command is unchanged and distinct from `/map-upgrade` and
`$map-upgrade`: it upgrades only the CLI package, writes no project files, and
still requires the explicit `mapify init . --force` shown above to refresh a
project.

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

## Uninstalling

To remove MAP Framework:

```bash
# Remove from project
rm -rf .claude/agents/
rm -rf .claude/commands/
rm .claude/mcp_config.json
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
