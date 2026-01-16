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
cp -a .claude/settings.json .claude/settings.hooks.json .claude/workflow-rules.json "$templates_root/"

echo "✅ Synced .claude/* → $templates_root/"

