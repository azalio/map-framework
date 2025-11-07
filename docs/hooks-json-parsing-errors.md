# Hooks JSON Parsing Errors - Root Cause Analysis

## Executive Summary

Both `.claude/hooks/validate-agent-templates.sh` and `.claude/hooks/stop.sh` fail when processing Claude Code Write/Edit operations that contain multiline content. The root cause is improper JSON handling: manual string concatenation creates invalid JSON, and `echo` doesn't escape control characters.

---

## Error Pattern 1: validate-agent-templates.sh

### Affected Code Locations

**Line 69** (block decision):
```bash
echo "{\"decision\": \"block\", \"message\": \"$MESSAGE\"}"
```

**Line 87** (allow decision):
```bash
echo "{\"decision\": \"allow\", \"message\": \"$MESSAGE\"}"
```

### Error Manifestation

When `$MESSAGE` contains multiline text (e.g., "Variable {{language}} is protected\nFound in file: actor.md"), the echoed JSON becomes:

```json
{"decision": "block", "message": "Variable {{language}} is protected
Found in file: actor.md"}
```

This is **invalid JSON** because JSON strings cannot contain literal newlines (U+000A).

### Root Cause Analysis

1. **Bash variable expansion**: `$MESSAGE` contains literal `\n` characters
2. **echo behavior**: `echo "$MESSAGE"` outputs the string with literal newlines
3. **jq expectation**: jq requires newlines in JSON strings to be escaped as `\\n`
4. **Result**: When Claude Code reads this output with `cat | jq`, jq fails with:
   ```
   parse error: Invalid string: control characters from U+0000 through U+001F must be escaped at line 2, column 0
   ```

### Minimal Reproducible Example

```bash
#!/bin/bash

# Create test message with newline
MESSAGE="Line 1
Line 2"

# This produces INVALID JSON
echo "{\"decision\": \"block\", \"message\": \"$MESSAGE\"}"
# Output (invalid):
# {"decision": "block", "message": "Line 1
# Line 2"}

# Parsing fails
echo "{\"decision\": \"block\", \"message\": \"$MESSAGE\"}" | jq .
# parse error: Invalid string: control characters from U+0000 through U+001F must be escaped
```

**Expected valid JSON**:
```json
{"decision": "block", "message": "Line 1\\nLine 2"}
```

---

## Error Pattern 2: stop.sh

### Affected Code Locations

**Line 30** (extract tool name):
```bash
TOOL=$(echo "$INPUT" | jq -r '.tool // empty')
```

**Line 40** (extract file path):
```bash
FILE_PATH=$(echo "$INPUT" | jq -r '.parameters.file_path // empty')
```

**Line 86** (check validation output):
```bash
if echo "$OUTPUT" | jq -e '.checks[] | select(.status == "failed")' > /dev/null 2>&1;
```

### Error Manifestation

When Claude Code calls Write tool with multiline content:

```json
{
  "tool": "Write",
  "parameters": {
    "file_path": "/path/to/file.md",
    "content": "# Title\n\nMultiline\ncontent\nhere"
  }
}
```

The hook reads this via stdin (`cat`), stores in `$INPUT`, then:
```bash
echo "$INPUT" | jq -r '.tool'
```

If the JSON string contains literal newlines (which can happen if stdin is not properly formatted), jq fails.

### Root Cause Analysis

1. **stdin reading**: `INPUT=$(cat)` reads the entire stdin as-is
2. **Assumption violation**: The code assumes `$INPUT` is valid JSON
3. **echo relay**: `echo "$INPUT"` can introduce issues if `$INPUT` has special characters
4. **jq parsing**: jq expects well-formed JSON, fails on control characters

### Minimal Reproducible Example

```bash
#!/bin/bash

# Simulate malformed JSON input (literal newline in string)
INPUT='{"tool": "Write", "parameters": {"content": "Line 1
Line 2"}}'

# This fails
echo "$INPUT" | jq -r '.tool'
# parse error: Invalid string: control characters from U+0000 through U+001F must be escaped

# Correct JSON would be:
INPUT_CORRECT='{"tool": "Write", "parameters": {"content": "Line 1\\nLine 2"}}'
echo "$INPUT_CORRECT" | jq -r '.tool'
# Write
```

### Validation Output Parsing (Line 86)

Similar issue occurs when parsing validation output from `validate-agent-templates.sh`. If the validation hook returns invalid JSON (due to Error Pattern 1), this line fails:

```bash
OUTPUT=$(bash .claude/hooks/validate-agent-templates.sh)
# OUTPUT now contains invalid JSON

if echo "$OUTPUT" | jq -e '.checks[] | select(.status == "failed")' > /dev/null 2>&1;
# jq fails to parse invalid JSON
```

---

## Root Cause Summary Table

| Hook | Line(s) | Issue | Why It Fails |
|------|---------|-------|--------------|
| validate-agent-templates.sh | 69, 87 | Manual JSON string construction | `echo` doesn't escape newlines in `$MESSAGE` |
| stop.sh | 30, 40, 86 | Piping potentially malformed JSON through echo | Assumes stdin JSON is valid; doesn't handle literal newlines |

---

## Impact Analysis

### When Failures Occur

1. **Write tool** with multiline content triggers stop.sh failure
2. **Edit tool** with multiline content triggers stop.sh failure
3. **Validation errors** with multiline messages trigger cascading failures (stop.sh can't parse validate-agent-templates.sh output)

### Symptoms Observed

- Hooks return non-zero exit codes
- Error messages: "parse error: Invalid string: control characters from U+0000 through U+001F must be escaped"
- Operations block unexpectedly when they should pass validation
- Silent failures when jq errors are redirected to `/dev/null`

---

## Test Cases for Verification

### Test Case 1: validate-agent-templates.sh with multiline message

**Setup**:
```bash
# Create temporary test hook
cat > /tmp/test_validate.sh << 'EOF'
#!/bin/bash
MESSAGE="Variable {{language}} is protected
Found in file: actor.md
Line 3: context"

echo "{\"decision\": \"block\", \"message\": \"$MESSAGE\"}"
EOF

chmod +x /tmp/test_validate.sh
```

**Execute**:
```bash
/tmp/test_validate.sh | jq .
```

**Expected Result**: jq parse error

**Actual Result**: jq parse error (confirms bug)

---

### Test Case 2: stop.sh with Write tool containing newlines

**Setup**:
```bash
# Create malformed JSON (simulating stdin with literal newlines)
cat > /tmp/input.json << 'EOF'
{"tool": "Write", "parameters": {"file_path": "/tmp/test.md", "content": "# Title
Paragraph 1

Paragraph 2"}}
EOF
```

**Execute**:
```bash
cat /tmp/input.json | bash -c 'INPUT=$(cat); echo "$INPUT" | jq -r .tool'
```

**Expected Result**: Should extract "Write"

**Actual Result**: jq parse error if JSON contains literal newlines

---

### Test Case 3: Cascading failure (stop.sh parsing validate output)

**Setup**:
```bash
# Simulate validate-agent-templates.sh returning invalid JSON
cat > /tmp/mock_validate.sh << 'EOF'
#!/bin/bash
MESSAGE="Error with
newline"
echo "{\"decision\": \"block\", \"message\": \"$MESSAGE\"}"
EOF

chmod +x /tmp/mock_validate.sh
```

**Execute**:
```bash
OUTPUT=$(/tmp/mock_validate.sh)
echo "$OUTPUT" | jq -e '.decision'
```

**Expected Result**: Should extract "block"

**Actual Result**: jq parse error (confirms cascading failure)

---

## Solution Direction (For ST-2 and ST-3)

### For validate-agent-templates.sh
Use `jq` to construct JSON instead of manual string concatenation:

```bash
# WRONG (current)
echo "{\"decision\": \"block\", \"message\": \"$MESSAGE\"}"

# RIGHT (proposed)
jq -n --arg msg "$MESSAGE" '{decision: "block", message: $msg}'
```

### For stop.sh
Avoid `echo` relay when piping to jq:

```bash
# WRONG (current)
TOOL=$(echo "$INPUT" | jq -r '.tool // empty')

# RIGHT (proposed)
TOOL=$(jq -r '.tool // empty' <<< "$INPUT")
# Or validate INPUT is well-formed before processing
```

---

## References

- [RFC 8259 (JSON Specification)](https://datatracker.ietf.org/doc/html/rfc8259#section-7): String values must escape control characters
- [jq Manual - String Interpolation](https://jqlang.github.io/jq/manual/#string-interpolation): How to safely construct JSON with variables
- Bash `echo` vs `printf`: `echo` is not safe for JSON construction

---

## Appendix: Quick Reference

### Valid vs Invalid JSON Strings

**Invalid** (literal newline U+000A):
```json
{"message": "Line 1
Line 2"}
```

**Valid** (escaped newline):
```json
{"message": "Line 1\\nLine 2"}
```

### How to Test JSON Validity

```bash
# Test if string is valid JSON
echo "$JSON_STRING" | jq empty
# Exit code 0 = valid, non-zero = invalid
```

### Recommended jq Usage Patterns

```bash
# Construct JSON safely
jq -n --arg var "$BASH_VAR" '{key: $var}'

# Parse JSON safely (avoid echo)
jq -r '.field' <<< "$JSON_STRING"

# Read JSON from file
jq -r '.field' < file.json
```

---

**Document Version**: 1.0
**Created**: 2025-11-07
**Related Tasks**: ST-1 (Identification), ST-2 (Fix validate-agent-templates.sh), ST-3 (Fix stop.sh)
