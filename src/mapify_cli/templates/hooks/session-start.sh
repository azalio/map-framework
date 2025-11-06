#!/bin/bash
# Claude Code SessionStart hook: Auto-inject MAP workflow context
# Restores .map/current_plan.md checkpoint for seamless compaction recovery
#
# Input: None (triggered on session start)
# Output: JSON with additionalContext if checkpoint found and valid
# Exit code: Always 0 (non-blocking - new sessions must proceed)

set -euo pipefail

# Configuration
CHECKPOINT_FILE=".map/current_plan.md"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VALIDATOR_SCRIPT="$SCRIPT_DIR/helpers/validate_checkpoint_file.py"

# Debug logging to stderr (visible in Claude Code logs)
echo "[session-start] SessionStart hook triggered" >&2

# Check if jq is installed (required for JSON parsing)
if ! command -v jq &> /dev/null; then
    echo "[session-start] ERROR: jq not found (required for JSON parsing)" >&2
    echo '{"continue": true}'
    exit 0
fi

# Check if checkpoint file exists (new sessions won't have one)
if [ ! -f "$CHECKPOINT_FILE" ]; then
    echo "[session-start] No checkpoint found at $CHECKPOINT_FILE (new session, skipping injection)" >&2
    echo '{"continue": true}'
    exit 0
fi

# Check if validator script exists
if [ ! -f "$VALIDATOR_SCRIPT" ]; then
    echo "[session-start] ERROR: Validator script not found at $VALIDATOR_SCRIPT" >&2
    echo '{"continue": true}'
    exit 0
fi

# Call validator helper to validate and sanitize checkpoint file
# Validator returns JSON to stdout: {valid: bool, error: str|null, sanitized_content: str, metadata: {...}}
# Validator logs to stderr (we preserve that for debugging)
echo "[session-start] Validating checkpoint file via $VALIDATOR_SCRIPT" >&2
VALIDATION_OUTPUT=$(python3 "$VALIDATOR_SCRIPT" --file "$CHECKPOINT_FILE")
VALIDATOR_EXIT=$?

if [ $VALIDATOR_EXIT -ne 0 ]; then
    echo "[session-start] Validator failed with exit code $VALIDATOR_EXIT" >&2
    echo "[session-start] Validator output: $VALIDATION_OUTPUT" >&2
    echo '{"continue": true}'
    exit 0
fi

# Parse validation result using jq
VALID=$(echo "$VALIDATION_OUTPUT" | jq -r '.valid // false' 2>/dev/null || echo "false")

if [ "$VALID" != "true" ]; then
    ERROR_MSG=$(echo "$VALIDATION_OUTPUT" | jq -r '.error // "Unknown validation error"' 2>/dev/null || echo "Unknown validation error")
    echo "[session-start] Checkpoint validation failed: $ERROR_MSG" >&2
    echo '{"continue": true}'
    exit 0
fi

# Extract sanitized content
SANITIZED_CONTENT=$(echo "$VALIDATION_OUTPUT" | jq -r '.sanitized_content // ""' 2>/dev/null || echo "")

if [ -z "$SANITIZED_CONTENT" ]; then
    echo "[session-start] Sanitized content is empty after validation" >&2
    echo '{"continue": true}'
    exit 0
fi

# Build injection header
INJECTION_HEADER="# 🔄 MAP Workflow Context Restored

This context was automatically restored from your previous session's checkpoint.
The plan below reflects your current task progress and helps maintain workflow continuity after context compaction.

---

"

# Combine header with sanitized content
FULL_CONTEXT="${INJECTION_HEADER}${SANITIZED_CONTENT}"

# Get file size for logging
FILE_SIZE=$(echo "$VALIDATION_OUTPUT" | jq -r '.metadata.size_bytes // 0' 2>/dev/null || echo "0")
FILE_SIZE_KB=$((FILE_SIZE / 1024))

echo "[session-start] ✅ Successfully validated checkpoint (${FILE_SIZE_KB}KB)" >&2
echo "[session-start] Injecting context with header (${#FULL_CONTEXT} total chars)" >&2

# Output JSON with additionalContext
# Use jq to properly escape multi-line content
OUTPUT=$(jq -n \
    --arg context "$FULL_CONTEXT" \
    '{continue: true, additionalContext: $context}')

echo "$OUTPUT"
exit 0
