---
name: map-cli-reference
description: >-
  Quick reference for mapify CLI usage errors. Use when
  encountering "no such command", "no such option", "parameter not found",
  or when user asks "how to use mapify", "validate graph".
  Do NOT use for workflow selection (use map-workflows-guide) or planning
  methodology (use map-planning).
metadata:
  author: azalio
  version: 3.1.0
---

# MAP CLI Quick Reference

Fast lookup for commands, parameters, and common error corrections.

**For comprehensive documentation**, see:
- [CLI_REFERENCE.json](../../../docs/CLI_REFERENCE.json)
- [CLI_COMMAND_REFERENCE.md](../../../docs/CLI_COMMAND_REFERENCE.md)

---

## Quick Command Index

---

## Common Errors & Corrections

### Error 1: Using Removed Commands

**Issue**: `Error: No such command 'playbook'` or docs/examples mention `mapify playbook ...`

**Solution**: The `playbook` command was removed in v4.0+.

---

### Error 2: MCP Tool Not Available

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
1. Identify error type — removed command usage
2. Explain: `playbook` command was removed in v4.0+

**Result:** Error resolved.

### Example 2: Validating a dependency graph

**User says:** "How do I check if my task plan has circular dependencies?"

**Actions:**
1. Show command: `mapify validate graph task_plan.json`
2. Explain exit codes: 0 = valid, 1 = invalid, 2 = malformed JSON
3. Suggest `--strict` flag for CI pipelines and `--visualize` for debugging

**Result:** User validates their task plan and fixes dependency issues before running workflow.

## Troubleshooting

| Issue | Cause | Solution |
|-------|-------|----------|
| `No such option '--output'` | Wrong subcommand syntax | Check `mapify <command> --help` for valid options |
| `validate graph` exit code 2 | Malformed JSON input | Validate JSON with `python -m json.tool < file.json` |
| `mapify init` overwrites files | Using `--force` flag | Omit `--force` to preserve existing configuration |

---

**Version**: 1.1
**Last Updated**: 2026-01-15
**Lines**: ~200 (follows 500-line skill rule)
