#!/usr/bin/env bash
#
# show-focus.sh - Display current task plan focus (PreToolUse hook)
#
# Description:
#   Called by PreToolUse hook before Write/Edit/Bash operations.
#   Displays first 30 lines of task plan to keep agent focused on current goal.
#   Gracefully handles missing plan file (exits 0, no error).
#
# Usage:
#   ${CLAUDE_PLUGIN_ROOT}/scripts/show-focus.sh
#
# Exit codes:
#   0 - Always (even if plan file doesn't exist)

# Get script directory for calling sibling scripts
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Get the branch-specific plan file path
PLAN_FILE=$("$SCRIPT_DIR/get-plan-path.sh")

# If plan file exists, display first 30 lines
if [ -f "$PLAN_FILE" ]; then
    echo "🎯 Current Focus ($(basename "$PLAN_FILE" .md | sed 's/task_plan_//'))"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    head -30 "$PLAN_FILE"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
fi

# Always exit 0 - missing plan file is not an error
exit 0
