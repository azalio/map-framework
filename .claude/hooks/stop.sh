#!/bin/bash
# Claude Code Stop hook: Quality gates after code modifications
# Runs automated checks (syntax, tests) after Write/Edit operations
#
# Input: JSON via stdin with tool parameters
# Output: Check results to stderr (logging only), JSON to stdout
# Exit code: Always 0 (non-blocking, warnings only)

set -euo pipefail

# Configuration
QUALITY_GATES_ENABLED="${QUALITY_GATES_ENABLED:-true}"
QUALITY_GATES_TIMEOUT="${QUALITY_GATES_TIMEOUT:-30}"
HELPER_SCRIPT="$(dirname "$0")/helpers/quality_gates.py"

# Read JSON input from Claude Code
INPUT=$(cat)

# Debug logging to stderr
echo "[stop/quality-gates] Hook triggered" >&2

# Check if quality gates are enabled
if [ "$QUALITY_GATES_ENABLED" != "true" ]; then
    echo "[stop/quality-gates] Quality gates disabled via QUALITY_GATES_ENABLED" >&2
    echo '{"continue": true}'
    exit 0
fi

# Extract tool name from JSON
TOOL=$(echo "$INPUT" | jq -r '.tool // empty')

# Only run quality gates for Write and Edit operations
if [[ "$TOOL" != "Write" && "$TOOL" != "Edit" ]]; then
    echo "[stop/quality-gates] Tool '$TOOL' does not modify files, skipping checks" >&2
    echo '{"continue": true}'
    exit 0
fi

# Extract file path that was modified
FILE_PATH=$(echo "$INPUT" | jq -r '.parameters.file_path // empty')

if [ -z "$FILE_PATH" ]; then
    echo "[stop/quality-gates] No file_path in parameters, skipping checks" >&2
    echo '{"continue": true}'
    exit 0
fi

# Check if modified file is code (Python/Go/TypeScript/Rust)
if [[ ! "$FILE_PATH" =~ \.(py|go|ts|tsx|rs)$ ]]; then
    echo "[stop/quality-gates] File '$FILE_PATH' is not a supported code file, skipping checks" >&2
    echo '{"continue": true}'
    exit 0
fi

echo "[stop/quality-gates] Running quality checks for: $FILE_PATH" >&2

# Check if helper script exists
if [ ! -f "$HELPER_SCRIPT" ]; then
    echo "[stop/quality-gates] Helper script not found: $HELPER_SCRIPT" >&2
    echo '{"continue": true}'
    exit 0
fi

# Run Python helper with timeout
# Pass file path as argument, capture JSON output
if OUTPUT=$(timeout "$QUALITY_GATES_TIMEOUT" python3 "$HELPER_SCRIPT" --file "$FILE_PATH" 2>&1); then
    EXIT_CODE=0
else
    EXIT_CODE=$?
fi

# Check for timeout (exit code 124)
if [ $EXIT_CODE -eq 124 ]; then
    echo "[stop/quality-gates] ⚠️  Quality checks timed out after ${QUALITY_GATES_TIMEOUT}s" >&2
    echo "[stop/quality-gates] Consider increasing QUALITY_GATES_TIMEOUT or optimizing tests" >&2
    echo '{"continue": true}'
    exit 0
fi

# Output results to stderr for visibility
echo "[stop/quality-gates] ========== Quality Gates Results ==========" >&2
echo "$OUTPUT" >&2
echo "[stop/quality-gates] ===========================================" >&2

# Parse JSON output to check for failures
if echo "$OUTPUT" | jq -e '.checks[] | select(.status == "failed")' > /dev/null 2>&1; then
    echo "[stop/quality-gates] ⚠️  Some quality checks FAILED - review output above" >&2
    echo "[stop/quality-gates] Note: This is non-blocking, response will be submitted" >&2
else
    echo "[stop/quality-gates] ✅ All quality checks passed" >&2
fi

# Always allow operation (non-blocking mode)
echo '{"continue": true}'
exit 0
