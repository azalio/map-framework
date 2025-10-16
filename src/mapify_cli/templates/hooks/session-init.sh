#!/bin/bash
# Claude Code SessionStart hook: Load ACE playbook at session startup
# Initializes context with relevant knowledge and patterns
#
# Input: JSON via stdin with session info
# Output: JSON with optional message
# Exit code: Always 0

set -euo pipefail

# Read JSON input from Claude Code
INPUT=$(cat)

# Extract session info
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty')
WORKING_DIR=$(echo "$INPUT" | jq -r '.working_directory // empty' | sed 's#^~#'"$HOME"'#')

# Use current directory if not provided
if [ -z "$WORKING_DIR" ] || [ "$WORKING_DIR" == "null" ]; then
    WORKING_DIR=$(pwd)
fi

# Create session log directory if it doesn't exist
SESSION_LOG_DIR="${WORKING_DIR}/.claude/sessions"
mkdir -p "$SESSION_LOG_DIR" 2>/dev/null || true

# Log session start
if [ -n "$SESSION_ID" ]; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Session started: $SESSION_ID" >> "$SESSION_LOG_DIR/session.log" 2>/dev/null || true
fi

# Try to load playbook from cipher (if available)
PLAYBOOK_BULLETS=""
if command -v claude &> /dev/null; then
    # Search for high-quality patterns from previous sessions
    SEARCH_RESULT=$(claude --mcp-only mcp__cipher__cipher_memory_search \
        --query "successful implementation pattern best practice" \
        --top_k 10 \
        --similarity_threshold 0.5 \
        2>/dev/null || echo "")

    if [ -n "$SEARCH_RESULT" ]; then
        # Extract and format playbook bullets
        PLAYBOOK_BULLETS=$(echo "$SEARCH_RESULT" | jq -r '.results[]?.text // empty' 2>/dev/null || echo "")
    fi
fi

# Create session context file
SESSION_CONTEXT_FILE="${SESSION_LOG_DIR}/current_context.txt"
cat > "$SESSION_CONTEXT_FILE" <<EOF
# MAP Framework Session Context
# Session ID: ${SESSION_ID:-unknown}
# Started: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
# Working Directory: $WORKING_DIR

## Available Agents
- task-decomposer: Break down complex tasks
- actor: Implement code changes
- monitor: Validate implementations
- predictor: Analyze dependencies and impact
- evaluator: Score solution quality
- orchestrator: Coordinate workflow
- reflector: Learn from successes/failures
- curator: Build knowledge base
- documentation-reviewer: Check consistency

## MCP Servers
- cipher: Knowledge & reasoning memory
- claude-reviewer: Professional code review
- sequential-thinking: Chain-of-thought reasoning
- codex-bridge: AI code generation
- context7: Library documentation
- deepwiki: GitHub repository intelligence

## Playbook Bullets (from previous sessions)
$PLAYBOOK_BULLETS

---
This context is automatically loaded at session start.
EOF

# Check if this is a MAP framework project
IS_MAP_PROJECT=false
if [ -d "${WORKING_DIR}/.claude/agents" ] && [ -f "${WORKING_DIR}/.claude/commands/map-feature.md" ]; then
    IS_MAP_PROJECT=true
fi

# Compose welcome message
if [ "$IS_MAP_PROJECT" == "true" ]; then
    MESSAGE="✅ MAP Framework session initialized

Session ID: ${SESSION_ID:-unknown}
Available commands:
  /map-feature - Implement new features
  /map-debug - Debug issues
  /map-refactor - Refactor code
  /map-review - Review changes

Context loaded: $(echo "$PLAYBOOK_BULLETS" | wc -l) playbook patterns
Session context: ${SESSION_CONTEXT_FILE}"
else
    MESSAGE="✅ Claude Code session started

Working directory: $WORKING_DIR
Session context: ${SESSION_CONTEXT_FILE}

Tip: Use 'mapify init' to enable MAP Framework in this project."
fi

echo "{\"message\": \"$MESSAGE\"}"
exit 0
