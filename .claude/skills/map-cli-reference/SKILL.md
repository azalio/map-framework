---
name: map-cli-reference
description: Use when encountering mapify CLI command errors (no such option, no such command, parameter not found) or need quick reference for correct command syntax. Provides mapify playbook/recitation/validate command corrections and common mistake patterns.
---

# MAP CLI Quick Reference

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

### Recitation Commands (MAP Workflows)

```bash
# Create execution plan
mapify recitation create task-001 "Goal" '[{"id":"...","description":"..."}]'

# Update subtask status
mapify recitation update subtask-1 completed
mapify recitation update subtask-2 failed "Error message"

# Check workflow state
mapify recitation checkpoint
mapify recitation stats
mapify recitation get-context

# Generate dev docs
mapify recitation generate-context
mapify recitation generate-tasks

# Clear plan
mapify recitation clear
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

### Error 3: Wrong Approach (CRITICAL)

❌ **WRONG**: `sqlite3 .claude/playbook.db "UPDATE bullets SET..."`
✅ **CORRECT**: `mapify playbook apply-delta operations.json`
📝 **Explanation**: Direct database access breaks integrity and bypasses validation. ALWAYS use `apply-delta`.

❌ **WRONG**: `Edit(.claude/playbook.db, ...)`
✅ **CORRECT**: `mapify playbook apply-delta operations.json`
📝 **Explanation**: Cannot edit binary SQLite database. Generate delta operations JSON and apply via CLI.

❌ **WRONG**: Using legacy JSON format for playbook
✅ **CORRECT**: `mapify playbook query "..."`
📝 **Explanation**: Playbook uses SQLite database (`playbook.db`). Use CLI commands to interact with playbook.

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

### Playbook Search Modes

```bash
# Local only (fast, default)
mapify playbook query "pattern" --mode local

# Cipher only (cross-project, requires MCP)
mapify playbook query "pattern" --mode cipher

# Hybrid (both local + cipher)
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

## Integration with MAP Workflows

### Curator Agent

**Role**: Updates playbook via delta operations

**Workflow**:
1. Curator analyzes reflector insights
2. Generates delta operations (ADD/UPDATE/DEPRECATE)
3. Outputs JSON to file
4. Main agent runs: `mapify playbook apply-delta operations.json`

**Critical Rule**: Curator must NEVER:
- ❌ Run `sqlite3` commands directly
- ❌ Use `Edit` tool on playbook.db
- ❌ Manually create/modify playbook files

**Always**: Generate delta JSON → Apply via CLI

---

### Reflector Agent

**Role**: Searches for existing patterns before extracting new ones

**Workflow**:
1. Search cipher for similar patterns: `mapify playbook query "..." --mode cipher`
2. Search local playbook: `mapify playbook query "..." --mode local`
3. Extract only novel patterns (deduplicate)

**Commands used**:
```bash
mapify playbook query "error handling" --mode hybrid --limit 10
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

### Playbook Update Failed

**Issue**: Direct database modification corrupted playbook

**Solution**:
1. Never use `sqlite3` or `Edit` tool directly
2. Always use `mapify playbook apply-delta`
3. Restore from git if corrupted: `git restore .claude/playbook.db`

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
