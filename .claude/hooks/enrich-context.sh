#!/bin/bash
# Claude Code UserPromptSubmit hook: Enrich user prompts with cipher knowledge
# Automatically searches cipher for relevant patterns before processing user input
#
# Input: JSON via stdin with user prompt
# Output: JSON with enriched prompt
# Exit code: Always 0

set -euo pipefail

# Read JSON input from Claude Code
INPUT=$(cat)

# Extract user prompt
USER_PROMPT=$(echo "$INPUT" | jq -r '.prompt // empty')

if [ -z "$USER_PROMPT" ]; then
    # No prompt to enrich
    echo "$INPUT"
    exit 0
fi

# Skip enrichment for very short prompts (commands, not tasks)
PROMPT_LENGTH=$(echo "$USER_PROMPT" | wc -c)
if [ "$PROMPT_LENGTH" -lt 20 ]; then
    echo "$INPUT"
    exit 0
fi

# Extract keywords for cipher search
# Look for: "implement X", "fix Y", "add Z", "create W"
KEYWORDS=""
if echo "$USER_PROMPT" | grep -qiE "(implement|create|add|build)"; then
    KEYWORDS=$(echo "$USER_PROMPT" | grep -oiE "(implement|create|add|build) [a-zA-Z ]+" | head -1)
elif echo "$USER_PROMPT" | grep -qiE "(fix|debug|solve)"; then
    KEYWORDS=$(echo "$USER_PROMPT" | grep -oiE "(fix|debug|solve) [a-zA-Z ]+" | head -1)
elif echo "$USER_PROMPT" | grep -qiE "(refactor|improve|optimize)"; then
    KEYWORDS=$(echo "$USER_PROMPT" | grep -oiE "(refactor|improve|optimize) [a-zA-Z ]+" | head -1)
fi

# If no keywords found, use first few words
if [ -z "$KEYWORDS" ]; then
    KEYWORDS=$(echo "$USER_PROMPT" | cut -d' ' -f1-5)
fi

# Search cipher for relevant patterns (if CLI available)
RELEVANT_KNOWLEDGE=""
if command -v claude &> /dev/null; then
    # Try cipher search (silently fail if not available)
    SEARCH_RESULT=$(claude --mcp-only mcp__cipher__cipher_memory_search \
        --query "$KEYWORDS" \
        --top_k 3 \
        --similarity_threshold 0.4 \
        2>/dev/null || echo "")

    if [ -n "$SEARCH_RESULT" ]; then
        # Extract relevant patterns from search result
        RELEVANT_KNOWLEDGE=$(echo "$SEARCH_RESULT" | jq -r '.results[]?.text // empty' | head -5)
    fi
fi

# Enrich prompt if we found relevant knowledge
if [ -n "$RELEVANT_KNOWLEDGE" ]; then
    ENRICHED_PROMPT="$USER_PROMPT

---
[Auto-enriched with relevant patterns from cipher]

$RELEVANT_KNOWLEDGE
---"

    # Return enriched prompt
    ENRICHED_INPUT=$(echo "$INPUT" | jq --arg prompt "$ENRICHED_PROMPT" '.prompt = $prompt')
    echo "$ENRICHED_INPUT"
else
    # No enrichment, return original
    echo "$INPUT"
fi

exit 0
