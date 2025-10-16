# MAP Framework Claude Code Hooks

This directory contains Claude Code hooks that automate and protect MAP Framework workflows.

## What are Claude Code Hooks?

Hooks are automated scripts that execute at specific points in Claude Code's workflow. They enable you to:
- **Validate** operations before execution (PreToolUse)
- **React** to completed operations (PostToolUse)
- **Enrich** user prompts with context (UserPromptSubmit)
- **Initialize** sessions with knowledge (SessionStart)
- **Track** agent performance (SubagentStop)

## 🛡️ Available Hooks

### 1. `validate-agent-templates.sh` (P0 - Critical)

**Type**: PreToolUse (Edit/Write)
**Purpose**: Prevents accidental removal of critical Handlebars template variables from agent files
**Status**: ✅ Active

**What it checks:**
- Presence of `{{language}}`, `{{project_name}}`, `{{framework}}`
- Presence of `{{#if playbook_bullets}}...{{/if}}` (ACE learning)
- Presence of `{{#if feedback}}...{{/if}}` (Monitor retry loops)
- Presence of `{{subtask_description}}` (Task specification)
- Warns on massive deletions (>500 lines)

**How it works:**
```bash
# Claude Code calls this hook before Edit/Write on .claude/agents/*.md
# Input: JSON via stdin with tool parameters
# Output: {"decision": "allow"} or {"decision": "block", "message": "..."}
```

**Example blocked operation:**
```markdown
# ❌ BLOCKED: Agent file is missing critical template variables!

File: .claude/agents/actor.md
Missing templates:
  - {{language}}
  - {{#if playbook_bullets}}

These template variables are NOT optional - they're used by Orchestrator.
See .claude/agents/README.md for details.
```

**To bypass** (not recommended):
```bash
# Disable in .claude/settings.hooks.json
# Or use Claude Code UI to approve the blocked operation
```

### 2. `auto-store-knowledge.sh` (P1 - Important)

**Type**: PostToolUse (Edit/Write)
**Purpose**: Automatically store successful patterns in cipher MCP after file modifications
**Status**: ✅ Active

**Triggers after:**
- Successful code changes (.py, .js, .go, .rs, etc.)
- Documentation updates (.md)
- Script implementations (.sh, .bash)

**What it does:**
- Analyzes the change type and context (language, file path)
- Creates structured interaction text with code and metadata
- Calls `mcp__cipher__cipher_extract_and_operate_memory` automatically
- Stores in cipher with metadata: `{"source":"auto-store-hook","environment":"dev"}`
- No manual knowledge storage needed!

**Example output:**
```
✅ Pattern auto-stored in cipher: src/mapify_cli/__init__.py
```

### 3. `enrich-context.sh` (P1 - Important)

**Type**: UserPromptSubmit
**Purpose**: Enrich user prompts with relevant patterns from cipher before processing
**Status**: ✅ Active

**How it works:**
```bash
User: "implement JWT authentication"
  ↓
Hook: cipher search "authentication patterns"
  ↓
Enriched prompt: "implement JWT authentication
[Relevant patterns from previous implementations...]"
  ↓
Orchestrator processes enriched prompt
```

**How it works:**
- Extracts keywords from user prompt (implement, fix, refactor, etc.)
- Searches cipher for top 3 relevant patterns (similarity ≥ 0.4)
- Enriches prompt with found knowledge
- Returns enriched prompt to Claude Code

**Benefits:**
- Automatic knowledge reuse
- Consistent patterns across features
- No need to manually search cipher
- Context-aware suggestions

### 4. `session-init.sh` (P2 - Nice-to-have)

**Type**: SessionStart
**Purpose**: Load ACE playbook bullets at session start
**Status**: ✅ Active

**Triggers:**
- At the beginning of every Claude Code session
- Automatically detects MAP Framework projects

**What it does:**
- Searches cipher for high-quality patterns (top 10, similarity ≥ 0.5)
- Creates session context file: `.claude/sessions/current_context.txt`
- Lists available MAP agents and MCP servers
- Loads playbook bullets from previous sessions
- Logs session start to `.claude/sessions/session.log`

**Example output:**
```
✅ MAP Framework session initialized

Session ID: abc-123
Available commands:
  /map-feature - Implement new features
  /map-debug - Debug issues
  /map-refactor - Refactor code
  /map-review - Review changes

Context loaded: 10 playbook patterns
Session context: .claude/sessions/current_context.txt
```

### 5. `track-metrics.sh` (P2 - Nice-to-have)

**Type**: SubagentStop
**Purpose**: Track MAP agent performance metrics
**Status**: ✅ Active

**Triggers:**
- After each MAP agent completes execution
- Monitors: actor, monitor, predictor, evaluator, orchestrator, task-decomposer, reflector, curator

**What it tracks:**
- Execution time (seconds)
- Success/failure status
- Quality scores (extracted from agent output)
- Success rate (% successful over total runs)

**Output files:**
- `.claude/metrics/agent_metrics.jsonl` - JSON Lines format for analysis
- `.claude/metrics/summary.txt` - Human-readable summary

**Example output:**
```
📊 Metrics tracked: actor
- Execution: 42s
- Success: true
- Quality: 8.5
- Success rate: 85.7% (12/14 runs)
```

**Stores in cipher** for long-term analysis and trend identification.

## 📝 Configuration

Hooks are configured in `.claude/settings.hooks.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [{
          "type": "command",
          "command": ".claude/hooks/validate-agent-templates.sh",
          "timeout": 5
        }]
      }
    ]
  }
}
```

### Merging with user settings

Claude Code merges hooks from:
1. `~/.claude/settings.json` (global)
2. `.claude/settings.json` (project - committed)
3. `.claude/settings.local.json` (project - gitignored)
4. `.claude/settings.hooks.json` (MAP hooks - committed)

Users can override MAP hooks in their `.claude/settings.local.json`.

## 🧪 Testing Hooks

### Test validate-agent-templates.sh

```bash
# Create test JSON input
cat > /tmp/test-hook-input.json <<EOF
{
  "tool": "Edit",
  "parameters": {
    "file_path": ".claude/agents/actor.md",
    "new_string": "# Agent without templates\n\nThis will be blocked."
  }
}
EOF

# Run hook
cat /tmp/test-hook-input.json | .claude/hooks/validate-agent-templates.sh

# Expected output:
# {"decision": "block", "message": "❌ BLOCKED: Agent file is missing..."}
# Exit code: 1
```

### Test with valid content

```bash
cat > /tmp/test-hook-valid.json <<EOF
{
  "tool": "Edit",
  "parameters": {
    "file_path": ".claude/agents/actor.md",
    "new_string": "{{language}}\n{{project_name}}\n{{#if playbook_bullets}}{{/if}}\n{{#if feedback}}{{/if}}\n{{subtask_description}}"
  }
}
EOF

cat /tmp/test-hook-valid.json | .claude/hooks/validate-agent-templates.sh

# Expected output:
# {"decision": "allow"}
# Exit code: 0
```

## 🔧 Hook Development

### Creating a new hook

1. **Create shell script** in `.claude/hooks/`:
```bash
#!/bin/bash
set -euo pipefail

# Read JSON input
INPUT=$(cat)

# Extract parameters
TOOL=$(echo "$INPUT" | jq -r '.tool')

# Your logic here
# ...

# Return decision
echo '{"decision": "allow"}'
exit 0
```

2. **Make it executable**:
```bash
chmod +x .claude/hooks/your-hook.sh
```

3. **Add to `.claude/settings.hooks.json`**:
```json
{
  "hooks": {
    "PreToolUse": [{
      "matcher": "ToolName",
      "hooks": [{
        "type": "command",
        "command": ".claude/hooks/your-hook.sh",
        "timeout": 10
      }]
    }]
  }
}
```

4. **Test with JSON input**:
```bash
echo '{"tool": "ToolName", "parameters": {...}}' | .claude/hooks/your-hook.sh
```

### Hook contract

**Input** (via stdin):
```json
{
  "tool": "Edit",
  "parameters": {
    "file_path": "/path/to/file",
    "new_string": "content",
    "old_string": "previous"
  }
}
```

**Output** (to stdout):
```json
{
  "decision": "allow" | "block",
  "message": "Optional user-facing message"
}
```

**Exit codes:**
- `0` = Allow operation
- `1` = Block operation
- Other = Error (treated as allow with warning)

### Best practices

1. **Fast execution** - Hooks add latency, keep them <5 seconds
2. **Fail open** - If hook crashes, allow operation (don't break workflow)
3. **Clear messages** - Blocked operations should explain why and how to fix
4. **Idempotent** - Safe to run multiple times
5. **No side effects** - Don't modify files in PreToolUse hooks

## 🚨 Troubleshooting

### Hook not running

1. Check it's executable: `ls -la .claude/hooks/`
2. Check configuration: `cat .claude/settings.hooks.json`
3. Check Claude Code logs: Look for hook execution messages

### Hook blocking valid operations

1. Review hook logic: `cat .claude/hooks/your-hook.sh`
2. Test manually: `echo '{}' | .claude/hooks/your-hook.sh`
3. Temporarily disable: Edit `.claude/settings.hooks.json`
4. Approve in UI: Claude Code will prompt for approval

### Hook timeout

- Increase timeout in `.claude/settings.hooks.json`
- Optimize hook script (reduce external calls)
- Use async hooks (PostToolUse) for slow operations

## 📚 References

- [Claude Code Hooks Documentation](https://docs.claude.com/en/docs/claude-code/hooks)
- [MAP Framework Architecture](../../README.md#architecture)
- [Agent Template Variables](./../agents/README.md)

## 🤝 Contributing

To add a new hook:

1. Implement and test the hook script
2. Add configuration to `settings.hooks.json`
3. Update this README with hook documentation
4. Add tests and usage examples
5. Submit PR with clear use case explanation

Priority order:
- **P0 (Critical)**: Protects against data loss or breaking changes
- **P1 (Important)**: Improves workflow efficiency
- **P2 (Nice-to-have)**: Adds convenience features
