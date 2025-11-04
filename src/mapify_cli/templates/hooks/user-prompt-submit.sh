#!/bin/bash
# Claude Code UserPromptSubmit hook: Auto-inject playbook bullets + suggest workflows + suggest skills
# Enhances user prompts with contextually relevant patterns, workflow suggestions, and skill suggestions
#
# Input: User's message via stdin
# Output: JSON with injected_content and/or workflow suggestion and/or skill suggestion
# Exit code: Always 0 (allow operation, injection/suggestion is enhancement not blocker)

set -euo pipefail

# Configuration
MAX_BULLETS=5
MIN_QUERY_LENGTH=10
HELPER_SCRIPT="$(dirname "$0")/helpers/inject_playbook_bullets.py"
WORKFLOW_HELPER="$(dirname "$0")/helpers/suggest_workflow.py"
SKILL_HELPER="$(dirname "$0")/helpers/suggest_skill.py"
WORKFLOW_RULES=".claude/workflow-rules.json"
SKILL_RULES=".claude/skills/skill-rules.json"

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

# ============================================================================
# STEP 1: Playbook Bullet Injection (existing functionality)
# ============================================================================

# SECURITY FIX: Call Python helper via stdin to prevent command injection
# USER_MESSAGE passed via stdin, not command argument
# Note: Only capture stdout (not stderr) to avoid corrupting JSON output
PLAYBOOK_OUTPUT=$(printf '%s' "$USER_MESSAGE" | python3 "$HELPER_SCRIPT" --limit "$MAX_BULLETS")
PLAYBOOK_EXIT_CODE=$?

if [ $PLAYBOOK_EXIT_CODE -ne 0 ]; then
    echo "[user-prompt-submit] Playbook helper failed with exit code $PLAYBOOK_EXIT_CODE" >&2
    echo "[user-prompt-submit] Output: $PLAYBOOK_OUTPUT" >&2
    echo '{"continue": true}'
    exit 0
fi

# Parse playbook output to extract additionalContext if present
# Expected format: {"continue": true, "additionalContext": "..."}
ADDITIONAL_CONTEXT=""
if echo "$PLAYBOOK_OUTPUT" | jq -e '.additionalContext' >/dev/null 2>&1; then
    ADDITIONAL_CONTEXT=$(echo "$PLAYBOOK_OUTPUT" | jq -r '.additionalContext')
    echo "[user-prompt-submit] Extracted playbook context (${#ADDITIONAL_CONTEXT} chars)" >&2
fi

# ============================================================================
# STEP 2: Workflow Suggestion (new functionality)
# ============================================================================

WORKFLOW_SUGGESTION=""

# Check if workflow helper and rules exist
if [ -f "$WORKFLOW_HELPER" ] && [ -f "$WORKFLOW_RULES" ]; then
    echo "[user-prompt-submit] Checking workflow suggestions..." >&2

    # SECURITY FIX: Call workflow helper via stdin to prevent command injection
    WORKFLOW_OUTPUT=$(printf '%s' "$USER_MESSAGE" | python3 "$WORKFLOW_HELPER" --rules "$WORKFLOW_RULES")
    WORKFLOW_EXIT_CODE=$?

    if [ $WORKFLOW_EXIT_CODE -eq 0 ]; then
        # Parse workflow output
        # Expected format: {"workflow": "map-debug", "description": "...", "reason": "..."}
        if echo "$WORKFLOW_OUTPUT" | jq -e '.workflow' >/dev/null 2>&1; then
            WORKFLOW_ID=$(echo "$WORKFLOW_OUTPUT" | jq -r '.workflow')
            WORKFLOW_DESC=$(echo "$WORKFLOW_OUTPUT" | jq -r '.description')
            WORKFLOW_REASON=$(echo "$WORKFLOW_OUTPUT" | jq -r '.reason')

            echo "[user-prompt-submit] Matched workflow: $WORKFLOW_ID" >&2

            # SECURITY FIX: Format workflow suggestion with quoted heredoc delimiter
            # Prevents variable expansion code injection
            WORKFLOW_SUGGESTION=$(cat <<'EOF'

---

# 🔄 Suggested Workflow: `/__WORKFLOW_ID__`

**Description:** __WORKFLOW_DESC__

**Why this workflow?** __WORKFLOW_REASON__

**To use this workflow:**
```
/__WORKFLOW_ID__
```

This suggestion is based on your request. You can use the workflow or proceed normally.

---
EOF
)
            # Manual variable substitution (safe approach)
            WORKFLOW_SUGGESTION="${WORKFLOW_SUGGESTION//__WORKFLOW_ID__/$WORKFLOW_ID}"
            WORKFLOW_SUGGESTION="${WORKFLOW_SUGGESTION//__WORKFLOW_DESC__/$WORKFLOW_DESC}"
            WORKFLOW_SUGGESTION="${WORKFLOW_SUGGESTION//__WORKFLOW_REASON__/$WORKFLOW_REASON}"
        else
            echo "[user-prompt-submit] No workflow match found" >&2
        fi
    else
        echo "[user-prompt-submit] Workflow helper failed with exit code $WORKFLOW_EXIT_CODE" >&2
    fi
else
    echo "[user-prompt-submit] Workflow suggestion disabled (missing helper or rules)" >&2
fi

# ============================================================================
# STEP 2.5: Skill Suggestion (new functionality)
# ============================================================================

SKILL_SUGGESTION=""

# Check if skill helper and rules exist
if [ -f "$SKILL_HELPER" ] && [ -f "$SKILL_RULES" ]; then
    echo "[user-prompt-submit] Checking skill suggestions..." >&2

    # SECURITY FIX: Call skill helper via stdin to prevent command injection
    SKILL_OUTPUT=$(printf '%s' "$USER_MESSAGE" | python3 "$SKILL_HELPER" --rules "$SKILL_RULES")
    SKILL_EXIT_CODE=$?

    if [ $SKILL_EXIT_CODE -eq 0 ]; then
        # Parse skill output
        # Expected format: {"skill": "map-workflows-guide", "description": "...", "reason": "..."}
        if echo "$SKILL_OUTPUT" | jq -e '.skill' >/dev/null 2>&1; then
            SKILL_ID=$(echo "$SKILL_OUTPUT" | jq -r '.skill')
            SKILL_DESC=$(echo "$SKILL_OUTPUT" | jq -r '.description')
            SKILL_REASON=$(echo "$SKILL_OUTPUT" | jq -r '.reason')

            echo "[user-prompt-submit] Matched skill: $SKILL_ID" >&2

            # SECURITY FIX: Format skill suggestion with quoted heredoc delimiter
            # Prevents variable expansion code injection
            SKILL_SUGGESTION=$(cat <<'EOF'

---

# 📚 SKILL AVAILABLE: `__SKILL_ID__`

**What is this skill?** __SKILL_DESC__

**Why available?** __SKILL_REASON__

**To use this skill:**
```
/__SKILL_ID__
```

This skill provides specialized guidance for your question. You can use the skill or proceed normally.

---
EOF
)
            # Manual variable substitution (safe approach)
            SKILL_SUGGESTION="${SKILL_SUGGESTION//__SKILL_ID__/$SKILL_ID}"
            SKILL_SUGGESTION="${SKILL_SUGGESTION//__SKILL_DESC__/$SKILL_DESC}"
            SKILL_SUGGESTION="${SKILL_SUGGESTION//__SKILL_REASON__/$SKILL_REASON}"
        else
            echo "[user-prompt-submit] No skill match found" >&2
        fi
    else
        echo "[user-prompt-submit] Skill helper failed with exit code $SKILL_EXIT_CODE" >&2
    fi
else
    echo "[user-prompt-submit] Skill suggestion disabled (missing helper or rules)" >&2
fi

# ============================================================================
# STEP 3: Combine and Output
# ============================================================================

# Combine playbook context, workflow suggestion, and skill suggestion
FINAL_CONTEXT=""

if [ -n "$ADDITIONAL_CONTEXT" ]; then
    FINAL_CONTEXT="$ADDITIONAL_CONTEXT"
fi

if [ -n "$WORKFLOW_SUGGESTION" ]; then
    if [ -n "$FINAL_CONTEXT" ]; then
        # Append workflow suggestion to playbook context
        FINAL_CONTEXT="$FINAL_CONTEXT"$'\n'"$WORKFLOW_SUGGESTION"
    else
        # Only workflow suggestion
        FINAL_CONTEXT="$WORKFLOW_SUGGESTION"
    fi
fi

if [ -n "$SKILL_SUGGESTION" ]; then
    if [ -n "$FINAL_CONTEXT" ]; then
        # Append skill suggestion to combined context
        FINAL_CONTEXT="$FINAL_CONTEXT"$'\n'"$SKILL_SUGGESTION"
    else
        # Only skill suggestion
        FINAL_CONTEXT="$SKILL_SUGGESTION"
    fi
fi

# Output JSON for Claude Code UserPromptSubmit hook
if [ -n "$FINAL_CONTEXT" ]; then
    # Use jq to properly escape JSON string
    OUTPUT=$(jq -n --arg ctx "$FINAL_CONTEXT" '{"continue": true, "additionalContext": $ctx}')
    echo "$OUTPUT"
else
    # No context to inject
    echo '{"continue": true}'
fi

exit 0
