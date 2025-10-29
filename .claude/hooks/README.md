# MAP Framework - Claude Code Hooks

This directory contains Claude Code hooks for the MAP Framework.

## Active Hooks

### UserPromptSubmit - Playbook Auto-Injection

**Hook**: `user-prompt-submit.sh`
**Triggers**: Before user prompt is submitted to Claude Code
**Purpose**: Automatically injects relevant playbook bullets to enhance context

**How It Works**:
1. Extracts keywords from user message (filters stop words, handles unicode)
2. Queries local playbook using `mapify playbook query` CLI
3. Formats top 5 relevant bullets as markdown
4. Injects as `additionalContext` field in JSON response

**Configuration** (edit `user-prompt-submit.sh`):
```bash
MAX_BULLETS=5          # Number of bullets to inject (default: 5)
MIN_QUERY_LENGTH=10    # Minimum message length (default: 10 chars)
```

**Example Output**:
```json
{
  "continue": true,
  "additionalContext": "# Relevant Playbook Patterns\n\n## 1. [impl-0042] ...\n"
}
```

**Edge Cases Handled**:
- Short messages (<10 chars) → Skip injection
- No playbook database → Skip injection gracefully
- mapify CLI not found → Skip injection gracefully
- Query timeout (>10s) → Skip injection gracefully
- No relevant bullets → Skip injection (no additionalContext)

**Performance**: <2s typical latency (keyword extraction + FTS5 query)

**Testing**: See [TESTING.md](TESTING.md) for comprehensive test guide

---

### PreToolUse - Template Variable Validation

**Hook**: `validate-agent-templates.sh`
**Triggers**: Before `Edit` or `Write` operations on `.claude/agents/*.md` files
**Purpose**: Prevents accidental removal of critical template variables

**Template Variables Protected**:
- `{{language}}` - Programming language context
- `{{project_name}}` - Project name
- `{{framework}}` - Framework context
- `{{#if playbook_bullets}}` - ACE learning system
- `{{#if feedback}}` - Monitor→Actor retry loops
- `{{subtask_description}}` - Task specification

**How It Works**:
1. Detects when agent files are being modified
2. Checks staged content for required template variables
3. Blocks commit if variables are missing
4. Provides clear error message

**Override** (use carefully):
```bash
git commit --no-verify
```

---

### Stop - Quality Gates (#NoMessLeftBehind)

**Hook**: `stop.sh`
**Triggers**: After `Write` or `Edit` operations on code files
**Purpose**: Runs automated quality checks before response submission

**Supported Languages**:
- **Python** (.py): `python -m py_compile` + `pytest` for related tests
- **Go** (.go): `go fmt` + `go vet` for formatting and static analysis
- **TypeScript** (.ts, .tsx): `tsc --noEmit` for type checking
- **Rust** (.rs): `rustc` syntax validation

**Checks Performed**:
1. **Syntax validation**: Language-specific syntax checker
2. **Related tests** (Python only): Runs pytest on:
   - Corresponding test file (e.g., `test_foo.py` for `foo.py`)
   - Test file itself (if already a test file)
   - All tests (if file is in `src/` or `mapify_cli/`)

**Configuration**:
```bash
# Disable quality gates entirely
export QUALITY_GATES_ENABLED=false

# Adjust timeout (default: 30s)
export QUALITY_GATES_TIMEOUT=60
```

**How It Works**:
1. Detects Python file modifications (Write/Edit tools)
2. Runs syntax check with `py_compile`
3. Finds and runs related pytest tests
4. Reports results to stderr (non-blocking)
5. Always exits 0 (warnings only, never blocks)

**Example Output** (Success):
```
[stop/quality-gates] ========== Quality Gates Results ==========
File: tests/test_playbook_manager.py
Status: PASSED
Summary: All 2 check(s) passed, 0 skipped

✅ python_syntax: Syntax check passed
✅ pytest: Tests passed: tests/test_playbook_manager.py
[stop/quality-gates] ===========================================
[stop/quality-gates] ✅ All quality checks passed
```

**Example Output** (Failure - non-blocking warning):
```
[stop/quality-gates] ========== Quality Gates Results ==========
File: src/mapify_cli/example.py
Status: FAILED
Summary: 1 check(s) failed, 1 passed, 0 skipped

❌ python_syntax: Syntax error in src/mapify_cli/example.py
   SyntaxError: unterminated string literal (detected at line 2)

✅ pytest: Tests passed
[stop/quality-gates] ===========================================
[stop/quality-gates] ⚠️  Some quality checks FAILED - review output above
[stop/quality-gates] Note: This is non-blocking, response will be submitted
```

**Edge Cases Handled**:
- Non-Python files → Skipped
- Read/Glob tools → Skipped (no file modifications)
- pytest not installed → Test check skipped
- No related tests → Test check skipped
- Timeout (>30s) → Aborted gracefully
- Syntax errors → Reported, response still submitted

**Performance**: <5s for syntax check, <30s total (with tests)

**Testing**:
```bash
# Test with valid Python file
echo '{"tool": "Write", "parameters": {"file_path": "tests/test_playbook_manager.py"}}' | \
  .claude/hooks/stop.sh

# Test with syntax error
echo '{"tool": "Write", "parameters": {"file_path": "/tmp/broken.py"}}' | \
  .claude/hooks/stop.sh

# Test with quality gates disabled
QUALITY_GATES_ENABLED=false \
  echo '{"tool": "Write", "parameters": {"file_path": "test.py"}}' | \
  .claude/hooks/stop.sh
```

**Extending for Other Languages**:
Edit `.claude/hooks/helpers/quality_gates.py` to add support for TypeScript, Go, Rust, etc.
Update file extension regex in `stop.sh`:
```bash
# Current: if [[ ! "$FILE_PATH" =~ \.(py)$ ]]; then
# Add TypeScript: if [[ ! "$FILE_PATH" =~ \.(py|ts|tsx)$ ]]; then
```

## Removed Hooks

The following hooks were removed because **bash hooks cannot call MCP tools**:

- ❌ `auto-store-knowledge.sh` (PostToolUse) - Tried to call cipher MCP
- ❌ `enrich-context.sh` (UserPromptSubmit) - Tried to search cipher MCP
- ❌ `session-init.sh` (SessionStart) - Tried to load from cipher MCP
- ❌ `track-metrics.sh` (SubagentStop) - Tried to store metrics in cipher MCP

**Why Removed**: Bash hooks execute outside Claude Code's context and cannot invoke MCP tools.

**Alternative**: Call MCP tools directly within agent prompts or slash commands.

## Best Practices

**DO Use Hooks For**:
- ✅ File validation (grep, regex)
- ✅ Git operations (status, diff)
- ✅ Static analysis (linters)

**DON'T Use Hooks For**:
- ❌ MCP tool calls
- ❌ Interactive prompts
- ❌ Long operations (>10s timeout)
