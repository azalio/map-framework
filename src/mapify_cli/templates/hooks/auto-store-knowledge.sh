#!/bin/bash
# Claude Code PostToolUse hook: Auto-store successful patterns in cipher
# Automatically saves knowledge after successful Edit/Write operations
#
# Input: JSON via stdin with tool result
# Output: JSON with optional message
# Exit code: Always 0 (never block, this is post-operation)

set -euo pipefail

# Read JSON input from Claude Code
INPUT=$(cat)

# Extract tool info
TOOL=$(echo "$INPUT" | jq -r '.tool // empty')
FILE_PATH=$(echo "$INPUT" | jq -r '.parameters.file_path // empty')
SUCCESS=$(echo "$INPUT" | jq -r '.success // true')

# Only process successful operations
if [ "$SUCCESS" != "true" ]; then
    echo '{"message": "Operation failed, skipping knowledge storage"}'
    exit 0
fi

# Skip if file path is empty
if [ -z "$FILE_PATH" ]; then
    echo '{"message": "No file path, skipping"}'
    exit 0
fi

# Only store knowledge for code files and documentation
if [[ ! "$FILE_PATH" =~ \.(py|js|ts|go|rs|java|cpp|md|sh)$ ]]; then
    echo '{"message": "Not a code/doc file, skipping"}'
    exit 0
fi

# Skip test files and generated files
if [[ "$FILE_PATH" =~ (test_|_test\.|\.test\.|__pycache__|node_modules|\.git/) ]]; then
    echo '{"message": "Test or generated file, skipping"}'
    exit 0
fi

# Get the new content
NEW_CONTENT=$(echo "$INPUT" | jq -r '.parameters.content // .parameters.new_string // empty')

if [ -z "$NEW_CONTENT" ]; then
    echo '{"message": "No content to store"}'
    exit 0
fi

# Extract context: what type of change was this?
CHANGE_TYPE="code modification"
if [[ "$FILE_PATH" =~ \.md$ ]]; then
    CHANGE_TYPE="documentation update"
elif [[ "$FILE_PATH" =~ \.(sh|bash)$ ]]; then
    CHANGE_TYPE="script implementation"
fi

# Determine file extension for language context
FILE_EXT="${FILE_PATH##*.}"
LANGUAGE="unknown"
case "$FILE_EXT" in
    py) LANGUAGE="python" ;;
    js|ts) LANGUAGE="javascript/typescript" ;;
    go) LANGUAGE="go" ;;
    rs) LANGUAGE="rust" ;;
    java) LANGUAGE="java" ;;
    cpp|cc|cxx) LANGUAGE="c++" ;;
    sh|bash) LANGUAGE="bash" ;;
    md) LANGUAGE="markdown" ;;
esac

# Create interaction text for cipher
INTERACTION="Successful $CHANGE_TYPE in file: $FILE_PATH (language: $LANGUAGE)

## File Path
$FILE_PATH

## Change Type
$CHANGE_TYPE

## Content
\`\`\`$LANGUAGE
$NEW_CONTENT
\`\`\`

## Context
- Tool: $TOOL
- Operation: Successful file modification
- Language: $LANGUAGE
- Timestamp: $(date -u +"%Y-%m-%dT%H:%M:%SZ")

This pattern was automatically stored after successful implementation."

# Call cipher MCP to store knowledge (if available)
# Use claude CLI to call MCP tool
if command -v claude &> /dev/null; then
    # Try to store in cipher (silently fail if MCP not available)
    echo "$INTERACTION" | claude --mcp-only mcp__cipher__cipher_extract_and_operate_memory \
        --interaction "$INTERACTION" \
        --memoryMetadata '{"source":"auto-store-hook","environment":"dev"}' \
        2>/dev/null || true

    echo "{\"message\": \"✅ Pattern auto-stored in cipher: $FILE_PATH\"}"
else
    # Claude CLI not available, just log
    echo "{\"message\": \"⚠️  Claude CLI not found, skipping cipher storage\"}"
fi

exit 0
