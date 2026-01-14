---
name: map-cli-reference
description: Use when encountering mapify CLI command errors (no such option, no such command, parameter not found) or need quick reference for correct command syntax. Provides mapify playbook/validate command corrections and common mistake patterns.
---

# MAP CLI Quick Reference

> **Note (v4.0+):** Pattern storage has migrated from playbook.db to mem0 MCP. Playbook commands below are retained for legacy compatibility. For pattern storage/retrieval, use mem0 MCP tools: `mcp__mem0__map_tiered_search`, `mcp__mem0__map_add_pattern`, `mcp__mem0__map_archive_pattern`.

Fast lookup for mapify commands, parameters, and common error corrections.

**For comprehensive documentation**, see:
- [CLI_REFERENCE.json](../../../docs/CLI_REFERENCE.json) - Complete JSON schema
- [CLI_COMMAND_REFERENCE.md](../../../docs/CLI_COMMAND_REFERENCE.md) - Full guide with examples

---

## Quick Command Index

### Playbook Commands

```bash
# Fast keyword search (FTS5)
mapify playbook query "JWT AND authentication" --limit 5
mapify playbook query "test-0016"  # Search by bullet ID

# Semantic search (slower, conceptual)
mapify playbook search "authentication patterns" --top-k 10

# Apply delta operations (ONLY correct way to update playbook)
mapify playbook apply-delta operations.json
echo '{"operations":[...]}' | mapify playbook apply-delta

# Statistics and sync
mapify playbook stats
mapify playbook sync --threshold 5
```

### Validate Commands

```bash
# Validate dependency graph
mapify validate graph task_plan.json
echo '{"subtasks":[...]}' | mapify validate graph

# Visualize dependencies
mapify validate graph task_plan.json --visualize

# Strict mode (fail on warnings)
mapify validate graph task_plan.json --strict
```

### Root Commands

```bash
# Initialize project
mapify init my-project
mapify init . --mcp essential --force

# System checks
mapify check
mapify check --debug

# Upgrade agents
mapify upgrade
```

---

## Common Errors & Corrections

### Error 1: Wrong Command Name

❌ **WRONG**: `mapify playbook list --sections`
✅ **CORRECT**: `mapify playbook stats`
📝 **Explanation**: Command `list` doesn't exist. Use `stats` to see section overview.

❌ **WRONG**: `mapify playbook get docu-0005`
✅ **CORRECT**: `mapify playbook query "docu-0005"`
📝 **Explanation**: Command `get` doesn't exist. Use `query` with bullet ID as search text.

---

### Error 2: Wrong Parameter Name

❌ **WRONG**: `mapify playbook search --limit 3`
✅ **CORRECT**: `mapify playbook search "query text" --top-k 3`
📝 **Explanation**: `search` command uses `--top-k`, not `--limit` (different from `query` command).

❌ **WRONG**: `mapify playbook query --bullet-id test-0016`
✅ **CORRECT**: `mapify playbook query "test-0016"`
📝 **Explanation**: Option `--bullet-id` doesn't exist. Use bullet ID as query text argument.

---

### Error 3: Wrong Approach (CRITICAL) - v4.0+ uses mem0 MCP

❌ **WRONG**: `sqlite3 .claude/playbook.db "UPDATE bullets SET..."`
✅ **CORRECT**: `mcp__mem0__map_add_pattern` via Curator agent
📝 **Explanation**: Pattern storage migrated to mem0 MCP. Use Curator agent to store patterns.

❌ **WRONG**: Direct playbook updates without Curator
✅ **CORRECT**: `Task(subagent_type="curator", ...)`
📝 **Explanation**: Curator validates quality, checks duplicates via `mcp__mem0__map_tiered_search`.

❌ **WRONG**: Using legacy playbook for new patterns
✅ **CORRECT**: mem0 MCP tools
📝 **Explanation**: As of v4.0, patterns stored in mem0 with tiered namespaces (branch → project → org).

---

### Error 4: Missing Query Text

❌ **WRONG**: `mapify playbook search --top-k 3` (no query)
✅ **CORRECT**: `mapify playbook search "authentication patterns" --top-k 3`
📝 **Explanation**: Query text is a required positional argument, not optional.

---

## Quick Parameter Reference

### Query vs Search

**When to use `query`**:
- ✅ Fast keyword search (indexed FTS5)
- ✅ Known exact terms
- ✅ Boolean operators (AND, OR, NOT)
- ✅ Large playbooks (>100 bullets)

**When to use `search`**:
- ✅ Semantic/conceptual search
- ✅ Natural language queries
- ✅ Finding similar patterns
- ⚠️ Slower (requires embeddings)

---

### FTS5 Query Syntax (for `query` command)

```bash
# Boolean operators
mapify playbook query "JWT AND authentication"
mapify playbook query "error OR exception OR failure"
mapify playbook query "testing NOT integration"

# Phrase matching
mapify playbook query '"error handling"'

# Prefix matching
mapify playbook query "auth*"  # matches auth, authentication, authorize

# Proximity search
mapify playbook query "NEAR(JWT token, 5)"  # within 5 tokens
```

---

### Pattern Search (v4.0+ - mem0 MCP)

```bash
# Tiered search across namespaces (recommended)
mcp__mem0__map_tiered_search("pattern query")

# Add new patterns via Curator
mcp__mem0__map_add_pattern(content="...", category="implementation", tier="project")

# Archive outdated patterns
mcp__mem0__map_archive_pattern(pattern_id="impl-0042", reason="...")
```

### Legacy Playbook Search Modes

```bash
# Local only (fast, default) - LEGACY
mapify playbook query "pattern" --mode local

# Hybrid mode - LEGACY
mapify playbook query "pattern" --mode hybrid
```

---

## Apply-Delta Operation Format

**ADD Operation**:
```json
{
  "type": "ADD",
  "section": "IMPLEMENTATION_PATTERNS",
  "content": "Pattern description",
  "code_example": "optional code snippet",
  "tags": ["tag1", "tag2"],
  "related_to": ["impl-0001"]
}
```

**UPDATE Operation** (increments counters only):
```json
{
  "type": "UPDATE",
  "bullet_id": "impl-0042",
  "increment_helpful": 1,
  "increment_harmful": 0
}
```

**DEPRECATE Operation**:
```json
{
  "type": "DEPRECATE",
  "bullet_id": "impl-0001",
  "reason": "Pattern obsolete due to library update"
}
```

**Complete example**:
```json
{
  "operations": [
    {"type": "ADD", "section": "SECURITY_PATTERNS", "content": "..."},
    {"type": "UPDATE", "bullet_id": "sec-0012", "increment_helpful": 1},
    {"type": "DEPRECATE", "bullet_id": "impl-0001", "reason": "..."}
  ]
}
```

---

## Integration with MAP Workflows (v4.0+)

### Curator Agent

**Role**: Stores patterns in mem0 MCP

**Workflow**:
1. Curator analyzes reflector insights
2. Checks for duplicates via `mcp__mem0__map_tiered_search`
3. Stores new patterns via `mcp__mem0__map_add_pattern`
4. Archives outdated patterns via `mcp__mem0__map_archive_pattern`

**Critical Rule**: Curator must:
- ✅ Use `mcp__mem0__map_tiered_search` to check duplicates first
- ✅ Use `mcp__mem0__map_add_pattern` to store patterns
- ✅ Use `mcp__mem0__map_archive_pattern` to deprecate patterns

---

### Reflector Agent

**Role**: Searches for existing patterns before extracting new ones

**Workflow**:
1. Search mem0 for similar patterns: `mcp__mem0__map_tiered_search("query")`
2. Searches across tiers: branch → project → org
3. Extract only novel patterns (deduplicate via fingerprint)

**MCP tool used**:
```bash
mcp__mem0__map_tiered_search("error handling")
```

---

## Troubleshooting Tips

### Command Not Found

**Issue**: `Error: No such command 'list'`

**Solution**: Check [Quick Command Index](#quick-command-index) for correct command names. Common mistakes:
- `list` → use `stats`
- `get` → use `query`

---

### Parameter Mismatch

**Issue**: `Error: No such option: '--limit'` (in `search` command)

**Solution**: Different commands use different parameter names:
- `query` uses `--limit`
- `search` uses `--top-k`

---

### Pattern Storage Issues (v4.0+)

**Issue**: Patterns not being stored correctly

**Solution**:
1. Use mem0 MCP tools via Curator agent
2. Check for duplicates with `mcp__mem0__map_tiered_search`
3. Use `mcp__mem0__map_add_pattern` to store new patterns

---

## Exit Codes (validate graph)

- **0**: Valid graph (no critical errors)
- **1**: Invalid graph (critical errors or warnings with `--strict`)
- **2**: Malformed input (invalid JSON)

---

## See Also

**Comprehensive Documentation**:
- [CLI_REFERENCE.json](../../../docs/CLI_REFERENCE.json) - Complete machine-readable spec
- [CLI_COMMAND_REFERENCE.md](../../../docs/CLI_COMMAND_REFERENCE.md) - Full guide with examples
- [PLAYBOOK-USAGE-GUIDE.md](../../../docs/PLAYBOOK-USAGE-GUIDE.md) - Playbook workflows
- [CLI_TESTING_GUIDE.md](../../../docs/CLI_TESTING_GUIDE.md) - Testing reference

**Related Skills**:
- [map-workflows-guide](../map-workflows-guide/SKILL.md) - Choose right MAP workflow

**Source Code**:
- `src/mapify_cli/__init__.py` - Command definitions

---

**Version**: 1.0
**Last Updated**: 2025-11-07
**Lines**: ~250 (follows 500-line skill rule)
