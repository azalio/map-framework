#!/bin/bash
# Claude Code UserPromptSubmit hook: Auto-inject relevant playbook bullets
# Enhances user prompts with contextually relevant patterns from playbook
#
# Input: User's message via stdin
# Output: JSON with injected_content or empty if no relevant patterns found
# Exit code: Always 0 (allow operation, injection is enhancement not blocker)

set -euo pipefail

# Configuration
MAX_BULLETS=5
MIN_QUERY_LENGTH=10
HELPER_SCRIPT="$(dirname "$0")/helpers/inject_playbook_bullets.py"

# Read user message from stdin
USER_MESSAGE=$(cat)

# Debug logging to stderr (visible in Claude Code logs)
echo "[user-prompt-submit] Received message: ${USER_MESSAGE:0:100}..." >&2

# Skip injection if message too short (likely not a meaningful task)
MSG_LENGTH=${#USER_MESSAGE}
if [ $MSG_LENGTH -lt $MIN_QUERY_LENGTH ]; then
    echo "[user-prompt-submit] Message too short ($MSG_LENGTH chars), skipping injection" >&2
    echo '{"continue": true}'
    exit 0
fi

# Check if helper script exists
if [ ! -f "$HELPER_SCRIPT" ]; then
    echo "[user-prompt-submit] Helper script not found: $HELPER_SCRIPT" >&2
    echo '{"continue": true}'
    exit 0
fi

# Check if playbook database exists (we use SQLite, not JSON)
if [ ! -f ".claude/playbook.db" ]; then
    echo "[user-prompt-submit] No playbook database found, skipping injection" >&2
    echo '{"continue": true}'
    exit 0
fi

# Check if mapify CLI is available
if ! command -v mapify >/dev/null 2>&1; then
    echo "[user-prompt-submit] mapify CLI not found in PATH, skipping injection" >&2
    echo '{"continue": true}'
    exit 0
fi

# Call Python helper to query playbook and format results
# Pass user message as argument to avoid stdin conflicts
# Note: Only capture stdout (not stderr) to avoid corrupting JSON output
OUTPUT=$(python3 "$HELPER_SCRIPT" --message "$USER_MESSAGE" --limit "$MAX_BULLETS")
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo "[user-prompt-submit] Helper script failed with exit code $EXIT_CODE" >&2
    echo "[user-prompt-submit] Output: $OUTPUT" >&2
    echo '{"continue": true}'
    exit 0
fi

# Output JSON from helper (already formatted correctly)
echo "$OUTPUT"
exit 0
