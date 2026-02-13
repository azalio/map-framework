---
name: map-cli-reference
description: >-
  Quick reference for mapify CLI and mem0 MCP usage errors. Use when
  encountering "no such command", "no such option", "parameter not found",
  or when user asks "how to use mapify", "mem0 commands", "validate graph".
  Do NOT use for workflow selection (use map-workflows-guide) or planning
  methodology (use map-planning).
metadata:
  author: azalio
  version: 3.1.0
  mcp-server: mem0
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

## Examples

### Example 1: Fixing a deprecated command error

**User says:** "I'm getting `Error: No such command 'playbook'` when running mapify"

**Actions:**
1. Identify error type — deprecated command usage
2. Explain: playbook commands removed in v4.0+
3. Provide replacement: `mcp__mem0__map_tiered_search` for reads, `Task(subagent_type="curator", ...)` for writes

**Result:** User switches to mem0 MCP tools, error resolved.

### Example 2: Validating a dependency graph

**User says:** "How do I check if my task plan has circular dependencies?"

**Actions:**
1. Show command: `mapify validate graph task_plan.json`
2. Explain exit codes: 0 = valid, 1 = invalid, 2 = malformed JSON
3. Suggest `--strict` flag for CI pipelines and `--visualize` for debugging

**Result:** User validates their task plan and fixes dependency issues before running workflow.

### Example 3: mem0 MCP not responding

**User says:** "mem0 tiered search returns empty results"

**Actions:**
1. Check mem0 MCP configuration in `.claude/mcp_config.json`
2. Verify namespace conventions (org/project/branch)
3. Test with broad query: `mcp__mem0__map_tiered_search(query="test", limit=1)`

**Result:** User identifies configuration issue and restores mem0 connectivity.

---

## Troubleshooting

| Issue | Cause | Solution |
|-------|-------|----------|
| `No such command 'playbook'` | Deprecated in v4.0+ | Use `mcp__mem0__map_tiered_search` for pattern retrieval |
| `No such option '--output'` | Wrong subcommand syntax | Check `mapify <command> --help` for valid options |
| mem0 tool invocation fails | MCP server not configured | Add mem0 to `.claude/mcp_config.json` and restart |
| `validate graph` exit code 2 | Malformed JSON input | Validate JSON with `python -m json.tool < file.json` |
| Patterns not persisting | Writing directly instead of via Curator | Always use `Task(subagent_type="curator", ...)` for pattern writes |
| `mapify init` overwrites files | Using `--force` flag | Omit `--force` to preserve existing configuration |

---

**Version**: 1.1
**Last Updated**: 2026-01-15
**Lines**: ~200 (follows 500-line skill rule)
