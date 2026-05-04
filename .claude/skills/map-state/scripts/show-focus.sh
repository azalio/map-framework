#!/usr/bin/env bash
#
# show-focus.sh - Display current task plan focus (PreToolUse hook)
#
# Description:
#   Called by PreToolUse hook before Write/Edit/Bash operations.
#   Extracts ONLY the in_progress section (~200 tokens) to prevent goal drift.
#   Shows: Goal + Current in_progress phase details.
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

# If no plan file, exit silently
[ ! -f "$PLAN_FILE" ] && exit 0

# Extract goal (line after "## Goal")
GOAL=$(awk '/^## Goal/{getline; if(!/^#/ && !/^$/) print; exit}' "$PLAN_FILE")

# Extract ONLY the current in_progress phase section.
# Stop at the next phase (###) OR next top-level section (##) to avoid token bloat.
# Cap output by lines as a simple proxy for token budget.
FOCUS_MAX_LINES="${FOCUS_MAX_LINES:-40}"
IN_PROGRESS_SECTION=$(
    awk '
        /^### / {
            if (in_section) exit
            header = $0
            next
        }
        /^## / {
            if (in_section) exit
        }
        /\*\*Status:\*\* in_progress/ {
            in_section = 1
            if (header != "") print header
            print
            next
        }
        in_section { print }
    ' "$PLAN_FILE" | head -n "$FOCUS_MAX_LINES"
)

# Only output if we found an in_progress section
if [ -n "$IN_PROGRESS_SECTION" ]; then
    BRANCH=$(basename "$PLAN_FILE" .md | sed 's/task_plan_//')
    echo "───── MAP FOCUS ($BRANCH) ─────"
    [ -n "$GOAL" ] && echo "Goal: $GOAL"
    echo ""
    echo "$IN_PROGRESS_SECTION"
    echo "─────────────────────────────────"
fi

exit 0
