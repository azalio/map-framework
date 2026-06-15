#!/usr/bin/env bash
#
# init-session.sh - Initialize planning files for new MAP session
#
# Description:
#   Creates .map/<branch>/ directory and copies templates for branch-scoped planning files.
#   Idempotent: skips files that already exist.
#
# Usage:
#   ${CLAUDE_PLUGIN_ROOT}/scripts/init-session.sh
#
# Created files:
#   .map/<branch>/task_plan_<branch>.md
#   .map/<branch>/research/plan__discovery.md
#   .map/<branch>/progress_<branch>.md

set -euo pipefail

# Get script directory for accessing templates
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(dirname "$SCRIPT_DIR")"
TEMPLATE_DIR="$SKILL_ROOT/templates"

# Get branch name for file naming
BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo 'main')
if [ -z "$BRANCH" ]; then
    BRANCH="main"
fi

# Sanitize branch name (matches MAP orchestrator convention)
SANITIZED_BRANCH=$(echo "$BRANCH" | sed -E 's|/|-|g; s|[^a-zA-Z0-9_.-]|-|g; s|-{2,}|-|g; s|^-||; s|-$||')
if [ -z "$SANITIZED_BRANCH" ]; then
    SANITIZED_BRANCH="main"
fi

# Create .map/<branch> directory (nested convention)
MAP_DIR=".map/${SANITIZED_BRANCH}"
mkdir -p "$MAP_DIR"
mkdir -p "$MAP_DIR/research"

# Define file paths (nested under branch directory)
TASK_PLAN="$MAP_DIR/task_plan_${SANITIZED_BRANCH}.md"
DISCOVERY="$MAP_DIR/research/plan__discovery.md"
PROGRESS="$MAP_DIR/progress_${SANITIZED_BRANCH}.md"

echo "=== MAP Planning Session Initialization ==="
echo "Branch: $BRANCH (sanitized: $SANITIZED_BRANCH)"
echo ""

# Copy templates if files don't exist (idempotent)
copy_if_missing() {
    local src="$1"
    local dst="$2"
    local name="$3"

    if [ -f "$dst" ]; then
        echo "✓ $name already exists: $dst"
    elif [ -f "$src" ]; then
        cp "$src" "$dst"
        echo "✓ Created $name: $dst"
    else
        echo "⚠ Template not found: $src (skipping $name)"
    fi
}

copy_if_missing "$TEMPLATE_DIR/task_plan.md" "$TASK_PLAN" "task_plan"
copy_if_missing "$TEMPLATE_DIR/findings.md" "$DISCOVERY" "plan_discovery"
copy_if_missing "$TEMPLATE_DIR/progress.md" "$PROGRESS" "progress"

echo ""
echo "=== Session Ready ==="
echo "Edit $TASK_PLAN to define your phases."
echo ""
echo "Next steps:"
echo "1. Define goal in task_plan"
echo "2. Add phases with **Status:** pending"
echo "3. Start working - PreToolUse hook will show focus"
echo "4. Update status as phases complete"
