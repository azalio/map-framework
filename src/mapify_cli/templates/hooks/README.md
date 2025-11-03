# MAP Framework - Claude Code Hooks

This directory contains Claude Code hooks for the MAP Framework.

## Active Hooks

### UserPromptSubmit - Playbook Auto-Injection + Workflow Suggestion

**Hook**: `user-prompt-submit.sh`
**Triggers**: Before user prompt is submitted to Claude Code
**Purpose**: Automatically injects relevant playbook bullets AND suggests appropriate MAP workflows based on context

**How It Works**:
1. **Playbook Injection**: Extracts keywords from user message, queries playbook, formats top 5 relevant bullets
2. **Workflow Suggestion**: Matches user message against workflow-rules.json triggers, suggests best workflow (map-debug, map-feature, etc.)
3. Combines both outputs as `additionalContext` field in JSON response

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

### SessionStart - MAP Workflow Context Restoration

**Hook**: `session-start.sh`
**Triggers**: At session start (before first user interaction)
**Purpose**: Automatically restores `.map/current_plan.md` checkpoint to maintain workflow continuity after context compaction

**How It Works**:
1. SessionStart event triggers hook execution
2. Checks if `.map/current_plan.md` checkpoint file exists
3. Calls validator helper script (`helpers/validate_checkpoint_file.py`)
4. Validator performs 4-layer security validation (path, size, UTF-8, sanitization)
5. Strips control characters while preserving newlines and tabs
6. Returns JSON with `additionalContext` containing sanitized checkpoint
7. Claude receives restored plan automatically before first interaction

**Example Output** (Successful Injection):
```json
{
  "continue": true,
  "additionalContext": "# 🔄 MAP Workflow Context Restored\n\nThis context was automatically restored from your previous session's checkpoint.\nThe plan below reflects your current task progress and helps maintain workflow continuity after context compaction.\n\n---\n\n# Current Task: feat_auth\n## Progress: 3/5 completed\n## Subtask 3: Implement JWT token validation"
}
```

**Example Output** (No Checkpoint - New Session):
```json
{
  "continue": true
}
```

**Edge Cases Handled**:
- No checkpoint file → Skip injection gracefully (new session)
- Checkpoint >256KB → Reject, log error to stderr, skip injection
- Path traversal (`../../../etc/passwd`) → Reject, log error to stderr, skip injection
- Invalid UTF-8 encoding → Reject, log error to stderr, skip injection
- Binary files → Rejected by UTF-8 validation
- Control characters (ESC codes, NULL bytes) → Sanitized automatically (preserves \n and \t)
- Empty content after sanitization → Skip injection
- Validator script missing → Skip injection gracefully, fallback to manual Phase 1
- Validator script fails → Skip injection gracefully, log error

**Security Validations** (4 Layers - Defense-in-Depth):
1. **Path Security**: Blocks path traversal attacks (`../`, absolute paths outside `.map/`)
2. **Size Bomb Protection**: Rejects files >256KB before reading into memory
3. **UTF-8 Validation**: Ensures file is text (blocks binary files like images, executables)
4. **Content Sanitization**: Strips control characters (prevents terminal injection, escape code attacks)

**Performance**:
- Typical: <0.5s for small checkpoints (5KB)
- Maximum: <2s for large checkpoints (100KB)
- Timeout: 5s (Claude Code hook timeout limit)
- Validation overhead: ~0.1s (path + size + UTF-8 checks)

**Testing**:
- **Unit Tests**: `tests/hooks/test_validate_checkpoint_file.py` (41 test cases covering all security layers)
- **Integration Tests**: `tests/hooks/test_session_start_integration.py` (23 test cases for full hook workflow)

**Manual Testing**:
```bash
# Test with valid checkpoint
echo '{}' | .claude/hooks/session-start.sh

# Test with large file (size bomb attack)
dd if=/dev/zero of=.map/current_plan.md bs=1M count=1
echo '{}' | .claude/hooks/session-start.sh

# Test with path traversal (security)
ln -s /etc/passwd .map/current_plan.md
echo '{}' | .claude/hooks/session-start.sh

# Test with no checkpoint (new session)
rm -f .map/current_plan.md
echo '{}' | .claude/hooks/session-start.sh
```

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

## Workflow Auto-Activation System

**File**: `.claude/workflow-rules.json`
**Purpose**: Automatically suggest appropriate MAP workflows based on user prompt keywords

**How It Works**:
1. User submits prompt: "Fix the failing tests in auth.test.ts"
2. Hook matches keywords against workflow-rules.json triggers
3. Suggests `/map-debug` workflow with reason: "Keywords: fix, failing test"
4. Session tracking prevents repeated suggestions

**Supported Workflows**:
- `map-debug` - Bug fixes, test failures, debugging
- `map-feature` - New features, critical implementations
- `map-efficient` - Production code, optimizations
- `map-refactor` - Code restructuring, cleanup
- `map-fast` - Quick prototypes, throwaway code

**Customization** (edit `.claude/workflow-rules.json`):
```json
{
  "workflows": {
    "map-debug": {
      "priority": "high",
      "promptTriggers": {
        "keywords": ["bug", "error", "failing test", "fix"],
        "intentPatterns": ["(fix|debug).*?(bug|test)"]
      }
    }
  }
}
```

**Session Tracking**:
- Suggestions stored in `.claude/cache/workflow_suggestions_session.txt`
- One workflow suggested per session (avoids annoyance)
- Clear cache: `rm .claude/cache/workflow_suggestions_session.txt`

**Testing**:
```bash
# Run auto-activation tests
.claude/hooks/tests/test_auto_activation.sh
```

**Security** (P0 fixes applied):
- ✅ Stdin input (prevents command injection)
- ✅ Quoted heredoc (prevents variable expansion)
- ✅ Regex timeout protection (prevents ReDoS attacks)
