#!/usr/bin/env bash
#
# check-complete.sh - Verify all phases have terminal state (Stop hook)
#
# Description:
#   Called by Stop hook before agent session ends.
#   Counts phases by status and verifies all have reached terminal state.
#   Terminal states: complete, blocked, won't_do, superseded
#
# Usage:
#   ${CLAUDE_PLUGIN_ROOT}/scripts/check-complete.sh
#
# Exit codes:
#   0 - All phases in terminal state (OK to stop)
#   1 - Phases still pending/in_progress (do not stop)
#   0 - No plan file (OK to stop - planning not used)

# Get script directory for calling sibling scripts
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Get the branch-specific plan file path
PLAN_FILE=$("$SCRIPT_DIR/get-plan-path.sh")

# If no plan file exists, allow stop (planning not being used)
if [ ! -f "$PLAN_FILE" ]; then
    exit 0
fi

echo "=== Task Completion Check ==="
echo "Plan: $PLAN_FILE"
echo ""

# Count phases by status
# NOTE: grep -c outputs "0" but exits 1 on no matches, causing || to trigger
# Use: VAR=$(grep ...) || VAR=0 pattern to avoid double output
COMPLETE=$(grep -cF "**Status:** complete" "$PLAN_FILE" 2>/dev/null) || COMPLETE=0
BLOCKED=$(grep -cF "**Status:** blocked" "$PLAN_FILE" 2>/dev/null) || BLOCKED=0
WONT_DO=$(grep -cF "**Status:** won't_do" "$PLAN_FILE" 2>/dev/null) || WONT_DO=0
SUPERSEDED=$(grep -cF "**Status:** superseded" "$PLAN_FILE" 2>/dev/null) || SUPERSEDED=0
IN_PROGRESS=$(grep -cF "**Status:** in_progress" "$PLAN_FILE" 2>/dev/null) || IN_PROGRESS=0
PENDING=$(grep -cF "**Status:** pending" "$PLAN_FILE" 2>/dev/null) || PENDING=0

# TOTAL = sum of all status lines (not all ## headers, which includes Goal, Decisions, etc.)
TOTAL=$((COMPLETE + BLOCKED + WONT_DO + SUPERSEDED + IN_PROGRESS + PENDING))

# Calculate terminal states (complete + blocked + won't_do + superseded)
TERMINAL=$((COMPLETE + BLOCKED + WONT_DO + SUPERSEDED))

echo "Total phases:   $TOTAL"
echo "Terminal:       $TERMINAL (complete: $COMPLETE, blocked: $BLOCKED, won't_do: $WONT_DO, superseded: $SUPERSEDED)"
echo "In progress:    $IN_PROGRESS"
echo "Pending:        $PENDING"
echo ""

# Check completion: all phases must be in terminal state
if [ "$TERMINAL" -ge "$TOTAL" ] && [ "$TOTAL" -gt 0 ]; then
    echo "✅ ALL PHASES COMPLETE OR TERMINAL"
    exit 0
else
    echo "⚠️  TASK NOT COMPLETE"
    echo ""
    echo "Do not stop until all phases reach terminal state:"
    echo "  - complete: Phase finished successfully"
    echo "  - blocked: Waiting on external dependency"
    echo "  - won't_do: Decided not to implement"
    echo "  - superseded: Replaced by different approach"
    exit 1
fi
