name: map-cli-reference
description: Use when encountering mapify CLI or MCP usage errors (no such command, no such option, parameter not found). Provides mem0 MCP and validate command corrections with common mistake patterns.
---

# MAP CLI Quick Reference

> **Note (v4.0+):** Pattern storage and retrieval uses mem0 MCP (tiered namespaces). Legacy playbook subcommands are not the source of truth for patterns.

Fast lookup for commands, parameters, and common error corrections.

**For comprehensive documentation**, see:
- [CLI_REFERENCE.json](../../../docs/CLI_REFERENCE.json)
- [CLI_COMMAND_REFERENCE.md](../../../docs/CLI_COMMAND_REFERENCE.md)

---

## Quick Command Index

### Pattern Search (mem0 MCP)

```bash
# Tiered search across namespaces (branch → project → org)
mcp__mem0__map_tiered_search(query="JWT authentication", limit=5)

# Use section_filter when you know the category
mcp__mem0__map_tiered_search(query="input validation", section_filter="SECURITY_PATTERNS", limit=10)
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

### Error 1: Using Deprecated Playbook Commands

**Issue**: `Error: No such command 'playbook'` or docs/examples mention `mapify playbook ...`

**Solution**:
- For pattern retrieval: use `mcp__mem0__map_tiered_search`
- For pattern writes: use `Task(subagent_type="curator", ...)`

---

### Error 2: MCP Tool Not Available

**Issue**: mem0 calls return empty results or tool invocation fails.

**Solution**:
- Verify mem0 MCP is configured and enabled in `.claude/mcp_config.json` (or Claude settings)
- Confirm the org/project/branch namespaces match your workflow conventions

---

### Error 3: Wrong Approach (CRITICAL)

❌ **WRONG**: Writing patterns directly (ad-hoc scripts / manual storage)

✅ **CORRECT**: Use Curator agent:

```bash
Task(subagent_type="curator", ...)
```

Curator must:
- Search duplicates first via `mcp__mem0__map_tiered_search`
- Store new patterns via `mcp__mem0__map_add_pattern`
- Archive outdated patterns via `mcp__mem0__map_archive_pattern`

---

## Integration with MAP Workflows (v4.0+)

### Curator Agent

**Role**: Stores patterns in mem0 MCP

**Workflow**:
1. Curator analyzes reflector insights
2. Checks for duplicates via `mcp__mem0__map_tiered_search`
3. Stores new patterns via `mcp__mem0__map_add_pattern`
4. Archives outdated patterns via `mcp__mem0__map_archive_pattern`

### Reflector Agent

**Role**: Searches for existing patterns before extracting new ones

**MCP tool used**:
```bash
mcp__mem0__map_tiered_search(query="error handling", limit=5)
```

---

## Exit Codes (validate graph)

- **0**: Valid graph (no critical errors)
- **1**: Invalid graph (critical errors or warnings with `--strict`)
- **2**: Malformed input (invalid JSON)

---

## See Also

**Related Skills**:
- [map-workflows-guide](../map-workflows-guide/SKILL.md)

**Source Code**:
- `src/mapify_cli/__init__.py`

---

**Version**: 1.1
**Last Updated**: 2026-01-15
**Lines**: ~200 (follows 500-line skill rule)
