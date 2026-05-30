#!/usr/bin/env bash
#
# get-plan-path.sh - Generate branch-scoped task plan file path
#
# Description:
#   Detects current git branch and outputs path to branch-specific task plan file.
#   Sanitizes branch names for filesystem compatibility.
#   Defaults to 'main' branch when not in a git repository.
#
# Usage:
#   PLAN_PATH=$(bash .claude/skills/map-state/scripts/get-plan-path.sh)
#
# Output:
#   .map/<sanitized_branch>/task_plan_<sanitized_branch>.md
#
# Examples:
#   Branch: feature/auth -> .map/feature-auth/task_plan_feature-auth.md
#   Branch: main         -> .map/main/task_plan_main.md
#   Not in repo          -> .map/main/task_plan_main.md

set -euo pipefail

# Detect current git branch, default to 'main' if not in git repo
BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo 'main')

# Handle empty branch (detached HEAD or git issue)
if [ -z "$BRANCH" ]; then
    BRANCH="main"
fi

# Sanitize branch name for filesystem safety (matches MAP orchestrator convention)
SANITIZED_BRANCH=$(echo "$BRANCH" | sed -E 's|/|-|g; s|[^a-zA-Z0-9_.-]|-|g; s|-{2,}|-|g; s|^-||; s|-$||')

# Fallback if sanitization produced empty string
if [ -z "$SANITIZED_BRANCH" ]; then
    SANITIZED_BRANCH="main"
fi

# Output the plan file path (nested directory convention)
echo ".map/${SANITIZED_BRANCH}/task_plan_${SANITIZED_BRANCH}.md"
