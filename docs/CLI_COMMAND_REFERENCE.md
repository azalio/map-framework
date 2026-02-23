# Mapify CLI Command Reference

> **Machine-readable specification**: See [CLI_REFERENCE.json](./CLI_REFERENCE.json) for complete JSON schema

Complete reference for all mapify CLI commands with correct syntax, parameters, and common error corrections.

## Table of Contents

- [Validate Commands](#validate-commands)
  - [graph](#mapify-validate-graph)
- [Root Commands](#root-commands)
  - [init](#mapify-init)
  - [check](#mapify-check)
  - [upgrade](#mapify-upgrade)
- [Common Mistakes](#common-mistakes)

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
- No circular dependencies
- All dependencies exist (no forward references)
- Valid JSON format
- No orphaned tasks (warning only, unless `--strict`)

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
mapify init . --mcp context7,deepwiki
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

### 1. Using Legacy CLI Commands

| Wrong | Correct | Explanation |
|-------|---------|-------------|
| `mapify playbook ...` | Use slash commands (`/map-efficient`, etc.) | Legacy playbook CLI commands removed |

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
- `@validate_app.command()` - Validate commands
