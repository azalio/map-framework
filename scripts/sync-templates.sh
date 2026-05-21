#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

templates_root="src/mapify_cli/templates"

clean_generated_artifacts() {
    local root="$1"
    [[ -d "$root" ]] || return 0
    find "$root" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
    find "$root" \( -name '*.pyc' -o -name '.DS_Store' \) -type f -delete 2>/dev/null || true
}

mkdir -p "$templates_root/agents" "$templates_root/commands" "$templates_root/hooks" "$templates_root/references"

cp -a .claude/agents/*.md "$templates_root/agents/"
# .claude/commands/ may be empty (MAP commands moved to skills/). Use a glob
# guard so the script doesn't fail when there are no .md files to copy.
shopt -s nullglob
command_files=(.claude/commands/*.md)
shopt -u nullglob
if (( ${#command_files[@]} > 0 )); then
    cp -a "${command_files[@]}" "$templates_root/commands/"
fi
cp -a .claude/hooks/* "$templates_root/hooks/"
cp -a .claude/references/* "$templates_root/references/"
cp -a .claude/settings.json .claude/workflow-rules.json .claude/ralph-loop-config.json "$templates_root/"
clean_generated_artifacts "$templates_root/hooks"
clean_generated_artifacts "$templates_root/references"

# Sync skills directory (preserving nested structure)
if [[ -d .claude/skills ]]; then
    # Use rsync for recursive sync with nested directories
    if command -v rsync &> /dev/null; then
        rsync -a --delete --exclude '__pycache__' --exclude '*.pyc' --exclude '.DS_Store' .claude/skills/ "$templates_root/skills/"
    else
        # Fallback: copy recursively
        rm -rf "$templates_root/skills"
        cp -a .claude/skills "$templates_root/skills"
        clean_generated_artifacts "$templates_root/skills"
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
clean_generated_artifacts "$templates_root/map"

# Sync .codex/ → templates/codex/
if [[ -d .codex ]]; then
    mkdir -p "$templates_root/codex/skills" "$templates_root/codex/agents" "$templates_root/codex/hooks"

    # Skills (preserve nested structure)
    if command -v rsync &> /dev/null; then
        rsync -a --delete --exclude '__pycache__' --exclude '*.pyc' --exclude '.DS_Store' .codex/skills/ "$templates_root/codex/skills/"
    else
        rm -rf "$templates_root/codex/skills"
        cp -a .codex/skills "$templates_root/codex/skills"
        clean_generated_artifacts "$templates_root/codex/skills"
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
        clean_generated_artifacts "$templates_root/codex/hooks"
    fi

    # AGENTS.md
    [[ -f .codex/AGENTS.md ]] && cp -a .codex/AGENTS.md "$templates_root/codex/"
fi

clean_generated_artifacts "$templates_root"

echo "✅ Synced .claude/*, .codex/*, and .map/scripts/* → $templates_root/"
