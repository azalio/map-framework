#!/usr/bin/env bash
# =============================================================================
# Claude Code PreToolUse Hook: Block Dangerous Commands
# =============================================================================
#
# Intercepts Bash tool calls and blocks destructive commands like:
# - rm -rf (recursive force delete)
# - git push --force to main/master branches
# - git reset --hard
#
# USAGE:
#   This hook runs automatically before Bash tool calls.
#   Claude Code passes JSON via stdin with tool_name and tool_input.
#
# EXIT CODES:
#   0 - Allow command execution
#   0 + permissionDecision=deny - Block command execution (preferred)
#
# TESTING:
#   echo '{"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}}' | bash block-dangerous.sh
#   # Expected: Exit code 2
#
# =============================================================================

set -euo pipefail

# Read JSON from stdin
INPUT=$(cat)

# Extract tool_name and command using jq (or fallback to grep)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null || echo "")
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null || echo "")

# Only intercept Bash tool
if [[ "$TOOL_NAME" != "Bash" ]]; then
    echo '{}'
    exit 0
fi

# If no command, allow
if [[ -z "$COMMAND" ]]; then
    echo '{}'
    exit 0
fi

# Normalize command for pattern matching (lowercase for case-insensitive)
COMMAND_LOWER=$(echo "$COMMAND" | tr '[:upper:]' '[:lower:]')

# =============================================================================
# Dangerous Pattern Checks
# =============================================================================

# Check for rm -rf (recursive force delete)
# Matches: rm -rf, rm -fr, rm -r -f, rm -f -r, rm --recursive --force
if echo "$COMMAND" | grep -qE 'rm\s+(-rf|-fr)\s'; then
    jq -n '{
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: "deny",
        permissionDecisionReason: "Blocked: rm -rf is prohibited (recursive force delete can cause irreversible data loss)"
      }
    }'
    exit 0
fi

# Catch rm -rf at end of command or with path immediately after
if echo "$COMMAND" | grep -qE 'rm\s+(-rf|-fr)\s*(/|~|\.|[a-zA-Z])'; then
    jq -n '{
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: "deny",
        permissionDecisionReason: "Blocked: rm -rf is prohibited (recursive force delete can cause irreversible data loss)"
      }
    }'
    exit 0
fi

# Catch separated flags: rm -r -f or rm -f -r
if echo "$COMMAND" | grep -qE 'rm\s+(-r\s+-f|-f\s+-r)\s'; then
    jq -n '{
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: "deny",
        permissionDecisionReason: "Blocked: rm -rf is prohibited (recursive force delete can cause irreversible data loss)"
      }
    }'
    exit 0
fi

# Check for git push --force to main/master
# Matches: git push --force origin main, git push -f origin master
if echo "$COMMAND" | grep -qE 'git\s+push\s+.*(-f|--force).*\s+(origin|upstream)\s+(main|master)(\s|$)'; then
    jq -n '{
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: "deny",
        permissionDecisionReason: "Blocked: Force push to main/master is prohibited (can overwrite team work)"
      }
    }'
    exit 0
fi

# Also check reverse order: git push origin main --force
if echo "$COMMAND" | grep -qE 'git\s+push\s+(origin|upstream)\s+(main|master)\s+(-f|--force)'; then
    jq -n '{
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: "deny",
        permissionDecisionReason: "Blocked: Force push to main/master is prohibited (can overwrite team work)"
      }
    }'
    exit 0
fi

# Check for git reset --hard (without specific commit, or dangerous patterns)
# Block: git reset --hard, git reset --hard HEAD~, git reset --hard origin/
if echo "$COMMAND" | grep -qE 'git\s+reset\s+--hard(\s|$)'; then
    jq -n '{
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: "deny",
        permissionDecisionReason: "Blocked: git reset --hard is prohibited (can cause irreversible loss of uncommitted changes)"
      }
    }'
    exit 0
fi

# Check for dangerous chmod/chown on system directories
if echo "$COMMAND" | grep -qE '(chmod|chown)\s+(-R|--recursive)\s+.*\s+/($|\s)'; then
    jq -n '{
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: "deny",
        permissionDecisionReason: "Blocked: Recursive chmod/chown on / is prohibited (can break system permissions)"
      }
    }'
    exit 0
fi

# Check for dd with of=/dev/
if echo "$COMMAND" | grep -qE 'dd\s+.*of=/dev/'; then
    jq -n '{
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: "deny",
        permissionDecisionReason: "Blocked: dd with of=/dev/* is prohibited (writing to raw devices can destroy data)"
      }
    }'
    exit 0
fi

# Check for mkfs (format filesystem)
if echo "$COMMAND" | grep -qE 'mkfs'; then
    jq -n '{
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: "deny",
        permissionDecisionReason: "Blocked: mkfs is prohibited (formatting filesystems can destroy data)"
      }
    }'
    exit 0
fi

# =============================================================================
# All checks passed - allow command
# =============================================================================
echo '{}'
exit 0
