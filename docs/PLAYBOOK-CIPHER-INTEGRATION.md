# Playbook + Cipher Integration Guide

## Problem Statement

Claude Code agents struggle with dual-memory system (playbook + cipher) because they don't understand that these are **separate tools** that must be called independently.

### The Confusion

❌ **Wrong mental model**: "I can use `mapify playbook query --mode hybrid` to search both"

✅ **Correct model**: "I must call TWO separate tools and combine results myself"

## Why `--mode hybrid` Doesn't Work in Workflows

When agents execute:
```bash
mapify playbook query "pattern" --mode hybrid
```

**What happens**:
1. Bash spawns separate Python process
2. That process has NO access to MCP tools
3. `_query_cipher()` returns empty list (graceful degradation)
4. Result: only local playbook searched

**From playbook_manager.py:1267-1271**:
```python
else:
    # In production, this would be called via MCP tool invocation
    # by Claude's orchestration layer. For library usage without
    # MCP, return empty results gracefully.
    return []
```

## Correct Approach: Two-Step Pattern

### Step 1: Query Local Playbook (via Bash)

```bash
PLAYBOOK_RESULTS=$(mapify playbook query "[task description]" --limit 5)
```

**Why this works**:
- CLI tool, fast (<50ms)
- FTS5 full-text search
- Quality-scored results
- Project-specific patterns

### Step 2: Query Cipher (via MCP Tool)

```
mcp__cipher__cipher_memory_search(
  query="[task description similar pattern]",
  top_k=5
)
```

**Why this works**:
- Direct MCP tool call (Claude can invoke it)
- Cross-project validated patterns
- Semantic search
- Broader knowledge base

### Step 3: Agent Combines Results

Agent receives:
- Local playbook patterns (project-specific)
- Cipher patterns (cross-project, validated)
- Combines both to inform implementation

## Updated Workflow Pattern

### Before (Incorrect)

```bash
# This doesn't actually search cipher!
PLAYBOOK_BULLETS=$(mapify playbook query "auth" --mode hybrid)
```

### After (Correct)

```bash
# Step 1: Get local project patterns
PLAYBOOK_BULLETS=$(mapify playbook query "JWT authentication" --limit 5)
```

```
# Step 2: Get cross-project patterns (separate MCP call)
Task(
  subagent_type="general-purpose",
  prompt="Before implementing, search cipher for similar patterns:

Call mcp__cipher__cipher_memory_search with query='JWT authentication pattern' and top_k=5

Then review both:
- Local playbook results: $PLAYBOOK_BULLETS
- Cipher results: [from MCP call]

Identify best practices from both sources."
)
```

## When to Use Each Source

| Source | Use When | Tool |
|--------|----------|------|
| **Local Playbook** | Project-specific patterns, conventions, past lessons from THIS project | `mapify playbook query` (Bash) |
| **Cipher** | Cross-project validated patterns, general best practices, similar solutions from OTHER projects | `mcp__cipher__cipher_memory_search` (MCP) |

## Example: Actor Implementation

**Correct pattern**:

```markdown
### 3.1 Get Relevant Context

**Step 1 - Local Playbook**:
```bash
PLAYBOOK_BULLETS=$(mapify playbook query "[subtask description]" --limit 5)

**Step 2 - Cipher Cross-Project Patterns**:
Before implementing, call:
- `mcp__cipher__cipher_memory_search(query="[subtask concept]", top_k=5)`

**Step 3 - Combine Insights**:
Review both sources:
- Playbook shows project-specific conventions
- Cipher shows validated cross-project patterns
- Use playbook for "how we do it HERE"
- Use cipher for "how it's done WELL elsewhere"
```

## CLI Modes Documentation (Clarified)

The `--mode` parameter in `mapify playbook query` is for:

1. **Testing/development**: When playbook_manager has `_cipher_callback` registered
2. **Future standalone mode**: When cipher backend runs as separate service
3. **Currently**: Has NO effect in MAP workflows (always returns empty for cipher)

**For MAP workflows, ignore `--mode` parameter** and use two-step pattern above.

## Implementation Checklist

To fix agent confusion:

- [ ] Remove mentions of `--mode hybrid` from workflow commands
- [ ] Keep `--mode local` or no mode (they're equivalent)
- [ ] Add explicit "Search cipher" step AFTER playbook query
- [ ] Show examples of combining both sources
- [ ] Update USAGE.md to clarify mode limitations
- [ ] Update workflow commands (map-feature, map-efficient, etc.)

## Summary

✅ **Do**: Use `mapify playbook query` (local) + `mcp__cipher__cipher_memory_search` (MCP)

❌ **Don't**: Use `mapify playbook query --mode hybrid` and expect cipher results

**Why**: Bash commands can't invoke MCP tools. Claude agents must call MCP tools directly.
