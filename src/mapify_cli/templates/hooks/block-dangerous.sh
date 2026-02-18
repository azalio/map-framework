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
#   # Expected: Exit code 0 with permissionDecision=deny in JSON output
#
# =============================================================================

set -euo pipefail

# Read JSON from stdin
INPUT=$(cat)

deny() {
    local reason="$1"

    if command -v jq >/dev/null 2>&1; then
        jq -n --arg reason "$reason" '{
          hookSpecificOutput: {
            hookEventName: "PreToolUse",
            permissionDecision: "deny",
            permissionDecisionReason: $reason
          }
        }'
        return 0
    fi

    if command -v python3 >/dev/null 2>&1; then
        python3 - "$reason" <<'PY'
import json
import sys

reason = sys.argv[1]
print(
    json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }
    )
)
PY
        return 0
    fi

    local escaped=${reason//\\/\\\\}
    escaped=${escaped//\"/\\\"}
    printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"%s"}}\n' "$escaped"
}

if command -v jq >/dev/null 2>&1; then
    TOOL_NAME=$(jq -r '.tool_name // empty' <<<"$INPUT" 2>/dev/null || true)
    COMMAND=$(jq -r '.tool_input.command // empty' <<<"$INPUT" 2>/dev/null || true)
elif command -v python3 >/dev/null 2>&1; then
    TOOL_NAME=$(
        python3 -c 'import json,sys; d=json.loads(sys.stdin.read() or "{}"); print(d.get("tool_name",""))' <<<"$INPUT" 2>/dev/null || true
    )
    COMMAND=$(
        python3 -c 'import json,sys; d=json.loads(sys.stdin.read() or "{}"); ti=d.get("tool_input") or {}; print(ti.get("command",""))' <<<"$INPUT" 2>/dev/null || true
    )
else
    TOOL_NAME=""
    COMMAND=""
fi

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
# Matches: rm -rf, rm -fr, rm -r -f, rm -f -r, rm --recursive --force, and edge
# cases where flags touch the path (e.g., rm -rf0dir).
if echo "$COMMAND_LOWER" | grep -qE '(^|[[:space:];|&()])rm[[:space:]]'; then
    # Long flags: --recursive and --force
    if echo "$COMMAND_LOWER" | grep -qE -- '--recursive' && echo "$COMMAND_LOWER" | grep -qE -- '--force'; then
        deny "Blocked: rm -rf is prohibited (recursive force delete can cause irreversible data loss)"
        exit 0
    fi

    # Combined short flags: -rf / -fr (including edge cases where the path touches flags)
    if echo "$COMMAND_LOWER" | grep -qE '(^|[[:space:];|&()])rm[[:space:]].*-[^[:space:]]*r[^[:space:]]*f'; then
        deny "Blocked: rm -rf is prohibited (recursive force delete can cause irreversible data loss)"
        exit 0
    fi
    if echo "$COMMAND_LOWER" | grep -qE '(^|[[:space:];|&()])rm[[:space:]].*-[^[:space:]]*f[^[:space:]]*r'; then
        deny "Blocked: rm -rf is prohibited (recursive force delete can cause irreversible data loss)"
        exit 0
    fi

    # Separate short flags: -r -f / -f -r
    if echo "$COMMAND_LOWER" | grep -qE '(^|[[:space:]])-r([[:space:]]|$)' && echo "$COMMAND_LOWER" | grep -qE '(^|[[:space:]])-f([[:space:]]|$)'; then
        deny "Blocked: rm -rf is prohibited (recursive force delete can cause irreversible data loss)"
        exit 0
    fi
fi

# Check for git push --force to main/master
# Matches: git push --force origin main, git push -f origin master
if echo "$COMMAND" | grep -qE 'git\s+push\s+.*(-f|--force).*\s+(origin|upstream)\s+(main|master)(\s|$)'; then
    deny "Blocked: Force push to main/master is prohibited (can overwrite team work)"
    exit 0
fi

# Also check reverse order: git push origin main --force
if echo "$COMMAND" | grep -qE 'git\s+push\s+(origin|upstream)\s+(main|master)\s+(-f|--force)'; then
    deny "Blocked: Force push to main/master is prohibited (can overwrite team work)"
    exit 0
fi

# Check for git reset --hard (without specific commit, or dangerous patterns)
# Block: git reset --hard, git reset --hard HEAD~, git reset --hard origin/
if echo "$COMMAND" | grep -qE 'git\s+reset\s+--hard(\s|$)'; then
    deny "Blocked: git reset --hard is prohibited (can cause irreversible loss of uncommitted changes)"
    exit 0
fi

# Check for dangerous chmod/chown on system directories
if echo "$COMMAND" | grep -qE '(chmod|chown)\s+(-R|--recursive)\s+.*\s+/($|\s)'; then
    deny "Blocked: Recursive chmod/chown on / is prohibited (can break system permissions)"
    exit 0
fi

# Check for dd with of=/dev/
if echo "$COMMAND" | grep -qE 'dd\s+.*of=/dev/'; then
    deny "Blocked: dd with of=/dev/* is prohibited (writing to raw devices can destroy data)"
    exit 0
fi

# Check for mkfs (format filesystem)
if echo "$COMMAND" | grep -qE 'mkfs'; then
    deny "Blocked: mkfs is prohibited (formatting filesystems can destroy data)"
    exit 0
fi

# =============================================================================
# All checks passed - allow command
# =============================================================================
echo '{}'
exit 0
