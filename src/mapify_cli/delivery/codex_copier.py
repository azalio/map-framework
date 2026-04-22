"""Codex CLI provider delivery module.

Copies bundled templates/codex/ into a target project's .codex/ directory
and installs AGENTS.md at the project root.

Never touches .claude/.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from mapify_cli.delivery.file_copier import get_templates_dir


def _copy_tree(
    src_dir: Path,
    dst_dir: Path,
    *,
    executable_suffixes: frozenset[str] = frozenset(),
) -> int:
    """Recursively copy *src_dir* into *dst_dir*, skipping __pycache__.

    Returns the number of files copied.
    """
    count = 0
    dst_dir.mkdir(parents=True, exist_ok=True)
    for src_file in src_dir.rglob("*"):
        if not src_file.is_file():
            continue
        if "__pycache__" in src_file.parts:
            continue
        rel = src_file.relative_to(src_dir)
        target = dst_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_file, target)
        if executable_suffixes and src_file.suffix in executable_suffixes:
            target.chmod(target.stat().st_mode | 0o755)
        count += 1
    return count


_EXEC_SUFFIXES = frozenset((".py", ".sh"))


def create_codex_files(project_path: Path) -> dict[str, int]:
    """Copy Codex template files into target project.

    Creates:
    - .codex/skills/   (map-plan, map-fast, map-check, …)
    - .codex/agents/   (*.toml agent definitions)
    - .codex/config.toml
    - .codex/hooks.json + .codex/hooks/workflow-gate.py
    - AGENTS.md at project root (symlink to CLAUDE.md when it exists,
      standalone copy otherwise)

    Skips .map/scripts/ if the directory already exists.
    Never creates or modifies any .claude/ path.

    Args:
        project_path: Root directory of the target project.

    Returns:
        Mapping of category name to number of files installed/created.
        Categories: skills, agents, config, hooks, docs
    """
    templates_dir = get_templates_dir()
    codex_templates = templates_dir / "codex"

    empty_counts: dict[str, int] = {
        "skills": 0,
        "agents": 0,
        "config": 0,
        "hooks": 0,
        "docs": 0,
        "scripts": 0,
    }

    if not codex_templates.exists():
        return empty_counts

    counts: dict[str, int] = dict(empty_counts)
    codex_dir = project_path / ".codex"

    # ------------------------------------------------------------------
    # 1. Skills
    # ------------------------------------------------------------------
    skills_src = codex_templates / "skills"
    if skills_src.exists():
        for skill_dir in skills_src.iterdir():
            if not skill_dir.is_dir():
                continue
            skill_dst = codex_dir / "skills" / skill_dir.name
            counts["skills"] += _copy_tree(skill_dir, skill_dst)

    # ------------------------------------------------------------------
    # 2. Agents (*.toml)
    # ------------------------------------------------------------------
    agents_src = codex_templates / "agents"
    if agents_src.exists():
        agents_dst = codex_dir / "agents"
        agents_dst.mkdir(parents=True, exist_ok=True)
        for src_file in agents_src.glob("*.toml"):
            shutil.copy2(src_file, agents_dst / src_file.name)
            counts["agents"] += 1

    # ------------------------------------------------------------------
    # 3. config.toml
    # ------------------------------------------------------------------
    config_src = codex_templates / "config.toml"
    if config_src.exists():
        codex_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(config_src, codex_dir / "config.toml")
        counts["config"] += 1

    # ------------------------------------------------------------------
    # 4. Hooks (hooks.json + hooks/*.py)
    # ------------------------------------------------------------------
    hooks_json_src = codex_templates / "hooks.json"
    if hooks_json_src.exists():
        codex_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(hooks_json_src, codex_dir / "hooks.json")
        counts["hooks"] += 1

    hooks_dir_src = codex_templates / "hooks"
    if hooks_dir_src.exists():
        hooks_dst = codex_dir / "hooks"
        counts["hooks"] += _copy_tree(
            hooks_dir_src, hooks_dst, executable_suffixes=_EXEC_SUFFIXES
        )

    # ------------------------------------------------------------------
    # 5. AGENTS.md at project root
    #    - Symlink to CLAUDE.md when CLAUDE.md exists (single source of truth)
    #    - Standalone copy from template otherwise
    #    - Skip entirely when AGENTS.md already exists
    # ------------------------------------------------------------------
    agents_md_src = codex_templates / "AGENTS.md"
    if agents_md_src.exists():
        agents_md_dst = project_path / "AGENTS.md"
        if not agents_md_dst.exists():
            claude_md = project_path / "CLAUDE.md"
            if claude_md.exists() and not claude_md.is_symlink():
                try:
                    agents_md_dst.symlink_to("CLAUDE.md")
                except OSError:
                    # Symlinks unavailable (Windows/restricted fs) — copy instead
                    shutil.copy2(claude_md, agents_md_dst)
            else:
                shutil.copy2(agents_md_src, agents_md_dst)
            counts["docs"] += 1

    # ------------------------------------------------------------------
    # 6. .map/scripts/ — skip-if-exists (do not overwrite user scripts)
    # ------------------------------------------------------------------
    map_scripts_dst = project_path / ".map" / "scripts"
    if not map_scripts_dst.exists():
        map_scripts_src = templates_dir / "map" / "scripts"
        if map_scripts_src.exists():
            counts["scripts"] = _copy_tree(
                map_scripts_src,
                map_scripts_dst,
                executable_suffixes=_EXEC_SUFFIXES,
            )

    return counts
