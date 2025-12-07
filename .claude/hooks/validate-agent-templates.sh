#!/bin/bash
# Claude Code PreToolUse hook: Validate agent template integrity
# Prevents accidental removal of critical Handlebars template variables
#
# Input: JSON via stdin with tool parameters
# Output: JSON with decision (block/allow) and optional message
# Exit code: 0 = allow, 1 = block

set -euo pipefail

# Read JSON input from Claude Code
INPUT=$(cat)

# Extract tool name and file path from JSON
TOOL=$(echo "$INPUT" | jq -r '.tool // empty')
FILE_PATH=$(echo "$INPUT" | jq -r '.parameters.file_path // empty')

# Only validate agent files
if [[ ! "$FILE_PATH" =~ \.claude/agents/.*\.md$ ]]; then
    # Not an agent file - allow
    echo '{"decision": "allow"}'
    exit 0
fi

# Get the new content that will be written
NEW_CONTENT=$(echo "$INPUT" | jq -r '.parameters.content // .parameters.new_string // empty')

if [ -z "$NEW_CONTENT" ]; then
    # No content to validate - allow (might be a read operation)
    echo '{"decision": "allow"}'
    exit 0
fi

# Critical patterns that MUST exist in agent files
REQUIRED_PATTERNS=(
    "{{language}}"
    "{{project_name}}"
    "{{#if playbook_bullets}}"
    "{{#if feedback}}"
    "{{subtask_description}}"
)

MISSING_PATTERNS=()

for pattern in "${REQUIRED_PATTERNS[@]}"; do
    if ! echo "$NEW_CONTENT" | grep -qF "$pattern"; then
        MISSING_PATTERNS+=("$pattern")
    fi
done

if [ ${#MISSING_PATTERNS[@]} -gt 0 ]; then
    # Build error message
    MESSAGE="❌ BLOCKED: Agent file is missing critical template variables!\\n\\n"
    MESSAGE+="File: $FILE_PATH\\n"
    MESSAGE+="Missing templates:\\n"
    for pattern in "${MISSING_PATTERNS[@]}"; do
        MESSAGE+="  - $pattern\\n"
    done
    MESSAGE+="\\nThese template variables are NOT optional - they're used by Orchestrator:\\n"
    MESSAGE+="  • {{language}}, {{project_name}} - Context injection\\n"
    MESSAGE+="  • {{#if playbook_bullets}} - ACE learning system\\n"
    MESSAGE+="  • {{#if feedback}} - Monitor→Actor retry loops\\n"
    MESSAGE+="  • {{subtask_description}} - Task specification\\n"
    MESSAGE+="\\nSee .claude/agents/README.md for details.\\n"
    MESSAGE+="\\nTo bypass this check (NOT recommended):\\n"
    MESSAGE+="  Disable the PreToolUse hook in .claude/settings.hooks.json"

    # Return blocking decision with message
    echo "{\"decision\": \"block\", \"message\": \"$MESSAGE\"}"
    exit 1
fi

# Check for massive deletions
if [ -f "$FILE_PATH" ]; then
    OLD_CONTENT=$(cat "$FILE_PATH")
    OLD_LINES=$(echo "$OLD_CONTENT" | wc -l)
    NEW_LINES=$(echo "$NEW_CONTENT" | wc -l)
    LINES_REMOVED=$((OLD_LINES - NEW_LINES))

    if [ $LINES_REMOVED -gt 500 ]; then
        # Warn about massive deletions but allow (might be intentional refactoring)
        MESSAGE="⚠️  WARNING: $FILE_PATH has $LINES_REMOVED lines removed (>500)\\n"
        MESSAGE+="\\nAre you sure you want to remove significant content from this agent?\\n"
        MESSAGE+="This might include critical Handlebars templates or instructions.\\n"
        MESSAGE+="\\nIf this is intentional, proceed. Otherwise, review the changes carefully."

        echo "{\"decision\": \"allow\", \"message\": \"$MESSAGE\"}"
        exit 0
    fi
fi

# All checks passed - allow the operation
echo '{"decision": "allow"}'
exit 0
