#!/usr/bin/env bash
#
# get-plan-path.sh - Generate branch-scoped task plan file path
#
# Description:
#   Detects current git branch and outputs path to branch-specific task plan file.
#   Sanitizes branch names by replacing '/' with '-' for filesystem compatibility.
#   Defaults to 'main' branch when not in a git repository.
#
# Usage:
#   PLAN_PATH=$(bash .claude/skills/map-planning/scripts/get-plan-path.sh)
#
# Output:
#   .map/task_plan_<sanitized_branch_name>.md
#
# Examples:
#   Branch: feature/map-planning -> .map/task_plan_feature-map-planning.md
#   Branch: main                 -> .map/task_plan_main.md
#   Not in repo                  -> .map/task_plan_main.md

set -euo pipefail

# Detect current git branch, default to 'main' if not in git repo
BRANCH=$(git branch --show-current 2>/dev/null || echo 'main')

# Handle empty branch (detached HEAD or git issue)
if [ -z "$BRANCH" ]; then
    BRANCH="main"
fi

# Sanitize branch name: replace '/' with '-' for filesystem safety
SANITIZED_BRANCH=$(echo "$BRANCH" | tr '/' '-')

# Output the plan file path
echo ".map/task_plan_${SANITIZED_BRANCH}.md"
