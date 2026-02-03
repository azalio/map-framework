#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

templates_root="src/mapify_cli/templates"

mkdir -p "$templates_root/agents" "$templates_root/commands" "$templates_root/hooks" "$templates_root/references"

cp -a .claude/agents/*.md "$templates_root/agents/"
cp -a .claude/commands/*.md "$templates_root/commands/"
cp -a .claude/hooks/* "$templates_root/hooks/"
cp -a .claude/references/* "$templates_root/references/"
cp -a .claude/settings.json .claude/settings.hooks.json .claude/workflow-rules.json .claude/ralph-loop-config.json "$templates_root/"

# Sync skills directory (preserving nested structure)
if [[ -d .claude/skills ]]; then
    # Use rsync for recursive sync with nested directories
    if command -v rsync &> /dev/null; then
        rsync -a --delete .claude/skills/ "$templates_root/skills/"
    else
        # Fallback: copy recursively
        rm -rf "$templates_root/skills"
        cp -a .claude/skills "$templates_root/skills"
    fi
else
    # If source directory is removed, clean up templates directory
    if [[ -d "$templates_root/skills" ]]; then
        rm -rf "$templates_root/skills"
    fi
fi

echo "✅ Synced .claude/* → $templates_root/"
