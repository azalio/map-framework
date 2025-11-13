# Playbook Usage Guide for Agents

## Common Mistakes to Avoid

### ❌ Mistake #1: Looking for playbook.json

**Wrong mental model**: "I need to read .claude/playbook.db"

**Reality**: Playbook migrated to SQLite in 2024. The file `.claude/playbook.json` no longer exists.

**Correct approach**:
```bash
# Query playbook via CLI (reads from playbook.db)
mapify playbook query "pattern description" --limit 5
```

### ❌ Mistake #2: Direct SQLite Modifications

**Wrong mental model**: "I'll update playbook directly with sqlite3"

**Example of what NOT to do**:
```bash
# ❌ NEVER DO THIS
sqlite3 .claude/playbook.db "UPDATE bullets SET helpful_count = 10 WHERE id = 'impl-0001'"
```

**Why this is dangerous**:
- Bypasses quality validation
- No deduplication check
- Breaks helpful_count integrity (supposed to be incremented via Curator)
- No audit trail
- Can corrupt database schema

**Correct approach**:
```bash
# ✅ Always use Curator agent + CLI
# 1. Curator creates delta operations (JSON)
# 2. Apply via CLI:
mapify playbook apply-delta curator_operations.json
```

### ❌ Mistake #3: Using Edit Tool on Binary Files

**Wrong mental model**: "I'll use Edit tool to update playbook.db"

**Reality**: `.claude/playbook.db` is a binary SQLite database, not a text file. Edit tool will corrupt it.

**Correct approach**: Never edit playbook.db directly. Always use `mapify playbook` CLI commands.

## Correct Playbook Workflow

### Reading from Playbook

**Step 1: Query local playbook** (via Bash):
```bash
PLAYBOOK_RESULTS=$(mapify playbook query "[task description]" --limit 5)
```

**Step 2: Search cipher for cross-project patterns** (via MCP tool):
```
mcp__cipher__cipher_memory_search(
  query="[pattern type]",
  top_k=5
)
```

**Step 3: Combine both sources** in your analysis/implementation.

### Writing to Playbook

**ONLY via Curator Agent**:

```
1. Reflector extracts lessons → JSON output
2. Curator processes lessons → delta operations JSON:
   {
     "operations": [
       {"operation": "ADD", "section": "...", "content": "...", ...},
       {"operation": "UPDATE", "bullet_id": "impl-0001", "field": "helpful_count", ...}
     ]
   }
3. Orchestrator applies: mapify playbook apply-delta curator_output.json
```

**Curator's role**:
- Validates quality (content length, code examples, specificity)
- Checks for duplicates (via cipher search)
- Assigns proper sections and IDs
- Maintains helpful_count integrity
- Creates audit trail

## Quick Reference

| Task | Correct Tool | Wrong Approach |
|------|-------------|----------------|
| **Read playbook** | `mapify playbook query` | Reading .claude/playbook.db |
| **Search patterns** | `mapify playbook query` + `cipher_memory_search` (MCP) | Using `--mode hybrid` flag |
| **Update playbook** | Curator agent → `mapify playbook apply-delta` | Direct sqlite3 commands |
| **Add new bullet** | Curator agent → ADD operation | Manually editing JSON/DB |
| **Increment helpful_count** | Curator agent → UPDATE operation | sqlite3 UPDATE command |

## File Locations

- **Playbook Database**: `.claude/playbook.db` (SQLite, binary, DO NOT EDIT)
- **Playbook Bullets Summary**: Generated on-the-fly by `mapify playbook query`
- **Delta Operations**: Temporary JSON files (e.g., `curator_operations.json`)
- **Legacy playbook.json**: Removed in 2024 migration (DO NOT create)

## CLI Commands Reference

```bash
# Query playbook (most common)
mapify playbook query "error handling" --limit 5

# Query with filters
mapify playbook query "JWT auth" --section SECURITY_PATTERNS --min-quality 3

# Apply Curator operations
mapify playbook apply-delta curator_output.json

# Validate playbook integrity (for debugging)
mapify playbook validate

# Export for backup (JSON format)
mapify playbook export --output backup.json
```

## When to Update This Guide

Update this guide when:
- New common mistakes are observed in agent behavior
- Playbook schema changes
- New CLI commands added
- Migration patterns change

## See Also

- [PLAYBOOK-CIPHER-INTEGRATION.md](PLAYBOOK-CIPHER-INTEGRATION.md) - How to use playbook + cipher together
- [docs/USAGE.md](USAGE.md) - Full mapify CLI documentation
- [.claude/agents/curator.md](../.claude/agents/curator.md) - Curator agent details
