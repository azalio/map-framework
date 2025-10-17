# MAP Framework - Claude Code Hooks

This directory contains Claude Code hooks for the MAP Framework.

## Active Hooks

### PreToolUse - Template Variable Validation

**Hook**: `validate-agent-templates.sh`
**Triggers**: Before `Edit` or `Write` operations on `.claude/agents/*.md` files
**Purpose**: Prevents accidental removal of critical template variables

**Template Variables Protected**:
- `{{language}}` - Programming language context
- `{{project_name}}` - Project name
- `{{framework}}` - Framework context
- `{{#if playbook_bullets}}` - ACE learning system
- `{{#if feedback}}` - Monitor→Actor retry loops
- `{{subtask_description}}` - Task specification

**How It Works**:
1. Detects when agent files are being modified
2. Checks staged content for required template variables
3. Blocks commit if variables are missing
4. Provides clear error message

**Override** (use carefully):
```bash
git commit --no-verify
```

## Removed Hooks

The following hooks were removed because **bash hooks cannot call MCP tools**:

- ❌ `auto-store-knowledge.sh` (PostToolUse) - Tried to call cipher MCP
- ❌ `enrich-context.sh` (UserPromptSubmit) - Tried to search cipher MCP
- ❌ `session-init.sh` (SessionStart) - Tried to load from cipher MCP
- ❌ `track-metrics.sh` (SubagentStop) - Tried to store metrics in cipher MCP

**Why Removed**: Bash hooks execute outside Claude Code's context and cannot invoke MCP tools.

**Alternative**: Call MCP tools directly within agent prompts or slash commands.

## Best Practices

**DO Use Hooks For**:
- ✅ File validation (grep, regex)
- ✅ Git operations (status, diff)
- ✅ Static analysis (linters)

**DON'T Use Hooks For**:
- ❌ MCP tool calls
- ❌ Interactive prompts
- ❌ Long operations (>10s timeout)
