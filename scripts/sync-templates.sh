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
cp -a .claude/settings.json .claude/workflow-rules.json .claude/ralph-loop-config.json "$templates_root/"

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

# Sync .map/scripts/ → templates/map/scripts/
mkdir -p "$templates_root/map/scripts"
cp -a .map/scripts/*.py "$templates_root/map/scripts/"

# Sync .codex/ → templates/codex/
if [[ -d .codex ]]; then
    mkdir -p "$templates_root/codex/skills" "$templates_root/codex/agents" "$templates_root/codex/hooks"

    # Skills (preserve nested structure)
    if command -v rsync &> /dev/null; then
        rsync -a --delete --exclude '__pycache__' .codex/skills/ "$templates_root/codex/skills/"
    else
        rm -rf "$templates_root/codex/skills"
        cp -a .codex/skills "$templates_root/codex/skills"
        find "$templates_root/codex/skills" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
    fi

    # Agents
    if compgen -G ".codex/agents/*.toml" > /dev/null; then
        cp -a .codex/agents/*.toml "$templates_root/codex/agents/"
    fi

    # Config
    [[ -f .codex/config.toml ]] && cp -a .codex/config.toml "$templates_root/codex/"
    [[ -f .codex/hooks.json ]] && cp -a .codex/hooks.json "$templates_root/codex/"

    # Hooks directory
    if [[ -d .codex/hooks ]]; then
        find .codex/hooks -maxdepth 1 -type f | xargs -I{} cp -a {} "$templates_root/codex/hooks/"
    fi

    # AGENTS.md
    [[ -f .codex/AGENTS.md ]] && cp -a .codex/AGENTS.md "$templates_root/codex/"
fi

echo "✅ Synced .claude/*, .codex/*, and .map/scripts/* → $templates_root/"
