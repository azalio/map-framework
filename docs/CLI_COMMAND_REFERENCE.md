# Mapify CLI Command Reference

> **Machine-readable specification**: See [CLI_REFERENCE.json](./CLI_REFERENCE.json) for complete JSON schema

> **IMPORTANT (v4.0+):** Pattern storage has migrated from playbook.db to mem0 MCP. The playbook commands below are retained for legacy compatibility and Knowledge Graph queries. For pattern storage and retrieval, use mem0 MCP tools: `mcp__mem0__map_tiered_search`, `mcp__mem0__map_add_pattern`, `mcp__mem0__map_archive_pattern`.

Complete reference for all mapify CLI commands with correct syntax, parameters, and common error corrections.

## Table of Contents

- [Playbook Commands](#playbook-commands)
  - [query](#mapify-playbook-query)
  - [search](#mapify-playbook-search)
  - [apply-delta](#mapify-playbook-apply-delta)
  - [stats](#mapify-playbook-stats)
  - [sync](#mapify-playbook-sync)
- [Validate Commands](#validate-commands)
  - [graph](#mapify-validate-graph)
- [Root Commands](#root-commands)
  - [init](#mapify-init)
  - [check](#mapify-check)
  - [upgrade](#mapify-upgrade)
- [Common Mistakes](#common-mistakes)
- [Query Syntax Guide](#query-syntax-guide)

---

## Playbook Commands

Manage and search playbook patterns.

### `mapify playbook query`

**Fast FTS5 full-text search** (recommended for most cases)

```bash
mapify playbook query [QUERY_TEXT] [OPTIONS]
```

**Parameters:**
- `QUERY_TEXT` (required): Search query (supports FTS5 syntax)
- `--section TEXT`: Filter by section (repeatable)
- `--limit INT`: Maximum results (default: 5)
- `--mode [local|cipher|hybrid]`: Search mode (default: local)
- `--format [markdown|json]`: Output format (default: markdown)
- `--min-quality INT`: Minimum quality score (default: 0)

**Examples:**

```bash
# Basic query
mapify playbook query "JWT authentication" --limit 5

# Hybrid search (playbook + cipher)
mapify playbook query "error handling" --mode hybrid --limit 10

# Filter by section
mapify playbook query "API design" --section ARCHITECTURE_PATTERNS

# Minimum quality filter
mapify playbook query "security patterns" --min-quality 3

# JSON output
mapify playbook query "testing strategies" --format json
```

**FTS5 Query Syntax:**

```bash
# Boolean operators
mapify playbook query "JWT AND authentication"
mapify playbook query "error OR exception"
mapify playbook query "testing NOT integration"

# Phrase matching
mapify playbook query "\"error handling\""

# Prefix matching
mapify playbook query "auth*"  # matches auth, authentication, authorize

# Proximity search
mapify playbook query "NEAR(JWT token, 5)"  # within 5 tokens
```

**Common Mistakes:**

❌ **WRONG**: `mapify playbook query --bullet-id test-0016`
✅ **CORRECT**: `mapify playbook query "test-0016"`
📝 Use bullet ID as query text, not as option

❌ **WRONG**: `mapify playbook get docu-0005`
✅ **CORRECT**: `mapify playbook query "docu-0005"`
📝 `get` command doesn't exist

---

### `mapify playbook search`

**Semantic search** using embeddings (slower but conceptual)

```bash
mapify playbook search [QUERY] [OPTIONS]
```

**Parameters:**
- `QUERY` (required): Natural language search query
- `--top-k INT`: Number of results (default: 5)

**Examples:**

```bash
# Semantic search
mapify playbook search "authentication patterns" --top-k 10

# Natural language query
mapify playbook search "how to handle errors in async code"
```

**Common Mistakes:**

❌ **WRONG**: `mapify playbook search --limit 3`
✅ **CORRECT**: `mapify playbook search "query" --top-k 3`
📝 Use `--top-k`, not `--limit` (different from `query` command)

**When to use query vs search:**
- **Use `query`**: Fast keyword search, known terms, exact matches
- **Use `search`**: Conceptual search, semantic similarity, synonyms

---

### `mapify playbook apply-delta`

**Apply delta operations to playbook** (ADD, UPDATE, DEPRECATE)

```bash
mapify playbook apply-delta [FILE] [OPTIONS]
```

**Parameters:**
- `FILE` (optional): JSON file with operations (or use stdin)
- `--dry-run`: Preview changes without applying

**Input Format:**

```json
{
  "operations": [
    {
      "type": "ADD",
      "section": "IMPLEMENTATION_PATTERNS",
      "content": "New pattern description",
      "code_example": "optional code snippet",
      "tags": ["tag1", "tag2"],
      "related_to": ["impl-0001"],
      "executable_scripts": ["optional runnable examples"]
    },
    {
      "type": "UPDATE",
      "bullet_id": "impl-0042",
      "increment_helpful": 1,
      "increment_harmful": 0
    },
    {
      "type": "DEPRECATE",
      "bullet_id": "impl-0001",
      "reason": "Pattern is obsolete"
    }
  ]
}
```

**Operation Fields:**

- **ADD**: `type`, `section`, `content` (required); `code_example`, `tags`, `related_to`, `executable_scripts` (optional)
- **UPDATE**: `type`, `bullet_id` (required); `increment_helpful`, `increment_harmful` (optional)
  - **Note**: UPDATE increments counters, does NOT change content
- **DEPRECATE**: `type`, `bullet_id` (required); `reason` (optional)

**Examples:**

```bash
# Apply from file
mapify playbook apply-delta operations.json

# Apply from stdin
echo '{"operations":[...]}' | mapify playbook apply-delta

# Preview changes
mapify playbook apply-delta operations.json --dry-run
```

**Critical Rules:**

⚠️ **This is the ONLY correct way to update playbook**

❌ **NEVER DO THIS** (LEGACY):
- `sqlite3 .claude/playbook.db "UPDATE bullets SET..."`
- `Edit(.claude/playbook.db, ...)`

✅ **ALWAYS USE** (LEGACY): `mapify playbook apply-delta`

> **Note (v4.0+):** For pattern storage, use mem0 MCP via Curator agent instead of playbook.db commands.

**Why?**
- Maintains database integrity
- Validates operations
- Updates FTS5 indexes
- Handles transactions correctly

---

### `mapify playbook stats`

**Show playbook statistics**

```bash
mapify playbook stats
```

No parameters. Displays:
- Total bullets by section
- Quality metrics (helpful/harmful counts)
- Most active sections

**Example:**

```bash
mapify playbook stats
```

**Common Mistakes:**

❌ **WRONG**: `mapify playbook list --sections`
✅ **CORRECT**: `mapify playbook stats`
📝 `list` command doesn't exist

---

### `mapify playbook sync`

**Show high-quality patterns ready for cross-project sync**

```bash
mapify playbook sync [OPTIONS]
```

**Parameters:**
- `--threshold INT`: Minimum helpful count (default: 5)

**Examples:**

```bash
# Default (helpful_count >= 5)
mapify playbook sync

# Higher quality threshold
mapify playbook sync --threshold 10
```

**Use Case:** Identify patterns that should be synced to cipher for cross-project reuse.

---

## Validate Commands

### `mapify validate graph`

**Validate TaskDecomposer dependency graph**

```bash
mapify validate graph [INPUT_FILE] [OPTIONS]
```

**Parameters:**
- `INPUT_FILE` (optional): JSON file to validate (or use stdin)
- `--visualize`: Show ASCII dependency tree
- `--no-color`: Disable colored output
- `--format [json|text]` / `-f`: Output format (default: json)
- `--strict`: Fail on warnings (orphaned tasks)

**Exit Codes:**
- `0`: Valid graph (no critical errors; warnings allowed unless --strict)
- `1`: Invalid graph (critical errors found, or warnings with --strict)
- `2`: Malformed input (invalid JSON or missing required fields)

**Examples:**

```bash
# Validate from file
mapify validate graph task_plan.json

# Validate from stdin
echo '{"subtasks":[...]}' | mapify validate graph

# Visualize dependencies
mapify validate graph task_plan.json --visualize

# Strict mode (fail on warnings)
mapify validate graph task_plan.json --strict

# Text output
mapify validate graph task_plan.json --format text
```

**Input Format:**

```json
{
  "subtasks": [
    {
      "id": "task-1",
      "description": "First task",
      "dependencies": []
    },
    {
      "id": "task-2",
      "description": "Second task",
      "dependencies": ["task-1"]
    }
  ]
}
```

**Validation Checks:**
- ✅ No circular dependencies
- ✅ All dependencies exist (no forward references)
- ✅ Valid JSON format
- ⚠️ No orphaned tasks (warning only, unless `--strict`)

---

## Root Commands

### `mapify init`

**Initialize a new MAP Framework project**

```bash
mapify init [PROJECT_NAME] [OPTIONS]
```

**Parameters:**
- `PROJECT_NAME` (optional): Directory name (use '.' for current directory)
- `--mcp [all|essential|docs|none|LIST]`: MCP servers to enable
- `--no-git`: Skip git initialization
- `--force`: Force merge/overwrite in non-empty directory

**Examples:**

```bash
# Create new project
mapify init my-project

# Initialize in current directory
mapify init . --mcp essential

# Force init in non-empty directory
mapify init . --force

# Skip git initialization
mapify init my-project --no-git

# Enable specific MCP servers
mapify init . --mcp cipher,context7
```

---

### `mapify check`

**Check that all required tools are installed**

```bash
mapify check [OPTIONS]
```

**Parameters:**
- `--debug`: Enable debug logging

**Examples:**

```bash
# Standard check
mapify check

# Verbose output
mapify check --debug
```

---

### `mapify upgrade`

**Upgrade MAP agents to the latest version**

```bash
mapify upgrade
```

Updates agent templates in `.claude/agents/` to latest versions.

---

## Common Mistakes

### 1. Wrong Command Name

| ❌ Wrong | ✅ Correct | Explanation |
|---------|-----------|-------------|
| `mapify playbook list --sections` | `mapify playbook stats` | `list` doesn't exist |
| `mapify playbook get docu-0005` | `mapify playbook query "docu-0005"` | `get` doesn't exist |

### 2. Wrong Parameter Name

| ❌ Wrong | ✅ Correct | Explanation |
|---------|-----------|-------------|
| `mapify playbook search --limit 3` | `mapify playbook search "query" --top-k 3` | `search` uses `--top-k` |
| `mapify playbook query --bullet-id test-0016` | `mapify playbook query "test-0016"` | No `--bullet-id` option |

### 3. Wrong Approach (LEGACY - v4.0+ uses mem0 MCP)

| ❌ Wrong | ✅ Correct | Explanation |
|---------|-----------|-------------|
| `sqlite3 .claude/playbook.db "UPDATE..."` | `mcp__mem0__map_add_pattern` via Curator | Direct DB access breaks integrity; patterns now in mem0 |
| `Edit(.claude/playbook.db, ...)` | `Task(subagent_type="curator", ...)` | Cannot edit binary DB; use Curator agent |

---

## Query Syntax Guide

### FTS5 Query Operators (for `mapify playbook query`)

| Operator | Syntax | Example | Description |
|----------|--------|---------|-------------|
| AND | `term1 AND term2` | `JWT AND authentication` | Both terms required |
| OR | `term1 OR term2` | `error OR exception` | Either term required |
| NOT | `term1 NOT term2` | `testing NOT integration` | First yes, second no |
| Phrase | `"exact phrase"` | `"error handling"` | Exact phrase match |
| Prefix | `term*` | `auth*` | Matches auth, authentication, etc. |
| Proximity | `NEAR(term1 term2, N)` | `NEAR(JWT token, 5)` | Within N tokens |

### Example Queries

```bash
# Find JWT authentication patterns
mapify playbook query "JWT AND authentication"

# Find error-related patterns
mapify playbook query "error OR exception OR failure"

# Find testing patterns (exclude integration tests)
mapify playbook query "test* AND NOT integration"

# Find REST API design patterns
mapify playbook query "\"API design\" AND REST"

# Find patterns about async error handling
mapify playbook query "NEAR(async error, 10)"
```

### Query vs Search Decision Tree

```
Need exact keyword match?
  YES → Use `mapify playbook query`
  NO ↓

Large playbook (>100 bullets)?
  YES → Use `mapify playbook query`
  NO ↓

Need semantic/conceptual search?
  YES → Use `mapify playbook search`
  NO → Use `mapify playbook query` (faster)
```

---

## Integration with MAP Workflow

### Curator Agent Usage (v4.0+)

```bash
# Curator stores patterns via mem0 MCP:
mcp__mem0__map_add_pattern(content="...", category="implementation", tier="project")

# Archive outdated patterns:
mcp__mem0__map_archive_pattern(pattern_id="impl-0042", reason="Superseded")
```

**Critical Rule**: Curator must:
- Use `mcp__mem0__map_tiered_search` to check for duplicates first
- Use `mcp__mem0__map_add_pattern` to store new patterns
- Use `mcp__mem0__map_archive_pattern` to deprecate patterns

### Reflector Agent Usage (v4.0+)

```bash
# Reflector searches for existing patterns via mem0:
mcp__mem0__map_tiered_search("error handling")
```

Searches across tiers (branch → project → org) before extracting new patterns.

---

## Related Documentation

- **Machine-readable spec**: [CLI_REFERENCE.json](./CLI_REFERENCE.json)
- **Usage examples**: [USAGE.md](./USAGE.md)
- **Architecture**: [ARCHITECTURE.md](./ARCHITECTURE.md)

---

## Version Information

**Generated from**: `src/mapify_cli/__init__.py`
**Framework version**: Based on map-framework 2.3.0
**Last updated**: 2026-01-11

For the most up-to-date command definitions, see the source code decorators:
- `@app.command()` - Root commands
- `@playbook_app.command()` - Playbook commands
- `@validate_app.command()` - Validate commands
