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
  - [doctor](#mapify-doctor)
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
- `--mcp [all|essential|none|LIST]`: MCP servers to enable
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
mapify init . --mcp sequential-thinking
```

**Also creates:**
- `.map/scripts/` workflow runtime helpers
- `.map/static-analysis/` language-specific analysis helpers
- branch-scoped workflow state under `.map/<branch>/` as MAP commands run

---

### `mapify check`

**Quick environment check for tools, MAP initialization, bundled templates, and supported MCP servers**

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

**Upgrade the `mapify` CLI itself to the latest released version**

```bash
mapify upgrade
```

Self-upgrades the installed `mapify-cli` package (the tool) — it does **not**
touch the files inside a project and is provider-agnostic:

- Auto-detects the install method and runs `uv tool upgrade mapify-cli`
  (uv tool installs) or `python -m pip install --upgrade mapify-cli`
  (pip installs).
- When already on the latest release, it does nothing.
- When running from a source checkout / editable install, self-upgrade is
  disabled (update that clone with `git pull`).

To refresh a project's shipped MAP files with the new templates after
upgrading, run:

```bash
mapify init . --force
```

---

### `mapify doctor`

**Run a detailed MAP project readiness diagnosis**

```bash
mapify doctor [OPTIONS]
```

**Parameters:**
- `--debug`: Enable debug logging

**Checks include:**
- Required tools (`git`, `claude`)
- Core MAP paths (`.claude/...`, `.map/scripts`)
- Installed agent/command counts vs bundled templates
- Current branch workspace availability in `.map/<branch>/`
- `.mcp.json` readability

**Examples:**

```bash
# Diagnose current project state
mapify doctor

# Diagnose with debug logging
mapify doctor --debug
```

---

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
**Framework version**: Based on map-framework 3.5.0
**Last updated**: 2026-03-19

For the most up-to-date command definitions, see the source code decorators:
- `@app.command()` - Root commands
- `@validate_app.command()` - Validate commands
