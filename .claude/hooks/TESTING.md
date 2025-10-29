# Testing Guide: Playbook Auto-Injection Hook

This guide explains how to test the user-prompt-submit hook that automatically injects relevant playbook bullets into Claude Code prompts.

## Overview

The hook has two components:
1. **Bash wrapper** (`.claude/hooks/user-prompt-submit.sh`) - Validates input, checks prerequisites
2. **Python helper** (`.claude/hooks/helpers/inject_playbook_bullets.py`) - Queries playbook, formats output

## Automated Tests

### Unit Tests (Python)

Tests the Python helper functions with mocked subprocess calls.

```bash
# Run all unit tests
pytest tests/test_inject_playbook_bullets.py -v

# Run specific test class
pytest tests/test_inject_playbook_bullets.py::TestExtractKeywords -v

# Run with coverage
pytest tests/test_inject_playbook_bullets.py --cov=.claude/hooks/helpers
```

**Test Coverage**:
- ✅ Keyword extraction (empty, stop words, unicode, deduplication)
- ✅ Playbook querying (success, failure, timeout, parse errors)
- ✅ Markdown formatting (empty, single, multiple bullets, code examples)
- ✅ Main integration flow (full flow, edge cases, error handling)

### Integration Tests (Bash)

Tests the end-to-end bash → Python flow.

```bash
# Run integration tests
.claude/hooks/tests/test_user_prompt_submit.sh

# Run from project root
cd /path/to/map-framework
.claude/hooks/tests/test_user_prompt_submit.sh
```

**Test Coverage**:
- ✅ Script existence and permissions
- ✅ Short message handling (MIN_QUERY_LENGTH)
- ✅ Missing playbook database
- ✅ Valid message processing
- ✅ Exit code (always 0)
- ✅ stdin reading
- ✅ JSON output format

## Manual Testing

### Test Scenario 1: Normal Flow (with playbook)

**Prerequisites**:
- Playbook database exists (`.claude/playbook.db`)
- `mapify` CLI is installed and in PATH
- Playbook contains at least 1 bullet

**Steps**:
1. Create a test message file:
   ```bash
   echo "implement JWT authentication with refresh tokens" > /tmp/test_message.txt
   ```

2. Run the hook manually:
   ```bash
   cat /tmp/test_message.txt | .claude/hooks/user-prompt-submit.sh
   ```

3. **Expected Output** (JSON):
   ```json
   {
     "continue": true,
     "additionalContext": "# Relevant Playbook Patterns\n\n*The following patterns..."
   }
   ```

4. **Verify**:
   - JSON is valid (use `jq` or `python -m json.tool`)
   - `continue` field is `true`
   - `additionalContext` contains markdown with bullet IDs
   - stderr shows debug logs (keyword extraction, query results)

### Test Scenario 2: Short Message (skipped)

**Steps**:
1. Test with short message:
   ```bash
   echo "hi" | .claude/hooks/user-prompt-submit.sh
   ```

2. **Expected Output**:
   ```json
   {
     "continue": true
   }
   ```

3. **Verify**:
   - No `additionalContext` field (injection skipped)
   - stderr shows: "Message too short (2 chars), skipping injection"

### Test Scenario 3: No Playbook Database

**Steps**:
1. Temporarily rename playbook:
   ```bash
   mv .claude/playbook.db .claude/playbook.db.backup
   ```

2. Run hook:
   ```bash
   echo "test message" | .claude/hooks/user-prompt-submit.sh
   ```

3. **Expected Output**:
   ```json
   {
     "continue": true
   }
   ```

4. **Verify**:
   - stderr shows: "No playbook database found, skipping injection"
   - Hook exits gracefully without blocking prompt

5. Restore playbook:
   ```bash
   mv .claude/playbook.db.backup .claude/playbook.db
   ```

### Test Scenario 4: mapify CLI Not Found

**Steps**:
1. Temporarily remove mapify from PATH:
   ```bash
   export PATH_BACKUP="$PATH"
   export PATH="/usr/bin:/bin"  # Minimal PATH without mapify
   ```

2. Run hook:
   ```bash
   echo "test message" | .claude/hooks/user-prompt-submit.sh
   ```

3. **Expected Output**:
   ```json
   {
     "continue": true
   }
   ```

4. **Verify**:
   - stderr shows: "mapify CLI not found in PATH, skipping injection"
   - Hook exits gracefully

5. Restore PATH:
   ```bash
   export PATH="$PATH_BACKUP"
   ```

### Test Scenario 5: Empty Playbook (no results)

**Prerequisites**:
- Empty playbook database (0 bullets)

**Steps**:
1. Create empty playbook:
   ```bash
   # Backup existing playbook
   cp .claude/playbook.db .claude/playbook.db.backup

   # Initialize empty playbook
   python3 <<EOF
   import sqlite3
   conn = sqlite3.connect('.claude/playbook.db')
   cursor = conn.cursor()
   cursor.execute("DELETE FROM bullets")
   conn.commit()
   conn.close()
   EOF
   ```

2. Run hook:
   ```bash
   echo "implement database migration" | .claude/hooks/user-prompt-submit.sh
   ```

3. **Expected Output**:
   ```json
   {
     "continue": true
   }
   ```

4. **Verify**:
   - stderr shows: "No relevant bullets found"
   - No `additionalContext` field

5. Restore playbook:
   ```bash
   mv .claude/playbook.db.backup .claude/playbook.db
   ```

## Test Helper Scripts

### Keyword Extraction Test

```bash
python3 -c "
import sys
sys.path.insert(0, '.claude/hooks/helpers')
from inject_playbook_bullets import extract_keywords

test_cases = [
    'implement JWT authentication',
    'a b c the and or',  # All stop words
    'тест unicode мир',  # Unicode
    'Test Test test',  # Deduplication
]

for msg in test_cases:
    keywords = extract_keywords(msg)
    print(f'Input: {msg!r}')
    print(f'Keywords: {keywords!r}')
    print()
"
```

### Playbook Query Test

```bash
# Direct CLI query (bypasses hook)
mapify playbook query "JWT authentication" --format json --limit 3

# Helper script test
python3 .claude/hooks/helpers/inject_playbook_bullets.py \
    --message "implement JWT authentication with refresh tokens" \
    --limit 5
```

### JSON Output Validation

```bash
# Test JSON parsing
echo "test message" | .claude/hooks/user-prompt-submit.sh | python3 -m json.tool

# Validate schema
echo "test message" | .claude/hooks/user-prompt-submit.sh | python3 -c "
import sys, json
data = json.load(sys.stdin)
assert isinstance(data['continue'], bool), 'continue must be boolean'
if 'additionalContext' in data:
    assert isinstance(data['additionalContext'], str), 'additionalContext must be string'
print('✓ JSON schema valid')
"
```

## Debugging

### Enable Verbose Logging

Edit `.claude/hooks/user-prompt-submit.sh` to add verbose logging:

```bash
# Add after line 19
set -x  # Enable bash debug output
```

### Check Hook Execution in Claude Code

Hook logs appear in Claude Code's stderr. To see them:

1. Open Claude Code developer console (if available)
2. Look for lines starting with `[user-prompt-submit]`
3. Check for error messages or warnings

### Common Issues

#### Issue: "Helper script not found"

**Cause**: Incorrect path to `inject_playbook_bullets.py`

**Fix**:
```bash
# Verify helper exists
ls -la .claude/hooks/helpers/inject_playbook_bullets.py

# Check HELPER_SCRIPT variable in bash hook
grep HELPER_SCRIPT .claude/hooks/user-prompt-submit.sh
```

#### Issue: "mapify command failed"

**Cause**: `mapify` CLI error or incorrect arguments

**Fix**:
```bash
# Test mapify directly
mapify playbook query "test" --format json --limit 5

# Check mapify version
mapify --version

# Reinstall if needed
pip install -e .
```

#### Issue: JSON parse error

**Cause**: `mapify` outputs non-JSON to stdout

**Fix**:
```bash
# Check what mapify outputs
mapify playbook query "test" --format json 2>&1 | cat -A

# Ensure --format json is specified
# Ensure stderr is not mixed with stdout
```

#### Issue: Hook blocks user prompt

**Cause**: Hook exits with non-zero code or timeout

**Fix**:
- Verify hook always exits 0 (check last line: `exit 0`)
- Reduce timeout if mapify is slow (<5s recommended)
- Add error handling around all subprocess calls

## Performance Testing

### Measure Hook Latency

```bash
# Time the hook execution
time echo "implement JWT authentication with refresh tokens" | \
    .claude/hooks/user-prompt-submit.sh > /dev/null
```

**Target**: <2 seconds for normal messages

### Profile Python Helper

```bash
# Profile keyword extraction
python3 -m cProfile -s cumulative .claude/hooks/helpers/inject_playbook_bullets.py \
    --message "implement JWT authentication with refresh tokens"
```

## CI/CD Integration

Add to `.github/workflows/test.yml`:

```yaml
- name: Test playbook injection hook
  run: |
    # Unit tests
    pytest tests/test_inject_playbook_bullets.py -v

    # Integration tests
    .claude/hooks/tests/test_user_prompt_submit.sh
```

## Troubleshooting Checklist

Before reporting issues, verify:

- [ ] Hook script is executable (`chmod +x`)
- [ ] Helper script path is correct
- [ ] Playbook database exists (`.claude/playbook.db`)
- [ ] `mapify` CLI is installed (`which mapify`)
- [ ] Unit tests pass (`pytest tests/test_inject_playbook_bullets.py`)
- [ ] Integration tests pass (`.claude/hooks/tests/test_user_prompt_submit.sh`)
- [ ] Manual test works (see Test Scenario 1)
- [ ] JSON output is valid (`| python3 -m json.tool`)
- [ ] Hook exits 0 (`echo $?` after running)

## Configuration

Edit `.claude/hooks/user-prompt-submit.sh` to customize:

```bash
MAX_BULLETS=5          # Number of bullets to inject (default: 5)
MIN_QUERY_LENGTH=10    # Minimum message length (default: 10 chars)
```

Edit `.claude/hooks/helpers/inject_playbook_bullets.py` to customize:

```python
max_keywords=10        # Maximum keywords to extract (default: 10)
timeout=10             # mapify query timeout (default: 10s)
```

## Related Documentation

- [Hook README](.claude/hooks/README.md) - Overview of all hooks
- [Playbook Query API](../../docs/PLAYBOOK_QUERY.md) - Query system documentation
- [Claude Code Hooks](https://docs.anthropic.com/claude-code/hooks) - Official hook documentation
