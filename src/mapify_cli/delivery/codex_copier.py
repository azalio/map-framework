"""Codex CLI provider delivery module.

Copies bundled templates/codex/ into a target project's Codex discovery
locations and installs AGENTS.md at the project root.

Never touches .claude/.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from mapify_cli.delivery.file_copier import (
    _extract_requires_block,
    _get_version,
    _load_template_skill_catalog,
    _prune_catalog_entries,
    _skill_missing_dependency,
    _warn_requires_skills,
    get_templates_dir,
)
from mapify_cli.delivery.managed_file_copier import copy_managed_file


def _install_managed_file(
    src: Path,
    dst: Path,
    version: str,
    *,
    fenced: bool = True,
    executable_suffixes: frozenset[str] = frozenset(),
) -> None:
    """Install one managed Codex file, preserving executable bits.

    ``fenced=True`` (watched) wraps the managed region in fence markers so a
    downstream user may extend below it; ``fenced=False`` fully overwrites
    (MAP-owned files like .map/scripts).
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    copy_managed_file(src, dst, version, fenced=fenced)
    if executable_suffixes and src.suffix in executable_suffixes and dst.exists():
        dst.chmod(dst.stat().st_mode | 0o755)


def _copy_tree(
    src_dir: Path,
    dst_dir: Path,
    version: str,
    *,
    fenced: bool = True,
    executable_suffixes: frozenset[str] = frozenset(),
) -> int:
    """Recursively install *src_dir* into *dst_dir* managed, skipping __pycache__.

    Codex skills/hooks are watched (``fenced=True``); MAP-owned trees pass
    ``fenced=False``.  Returns the number of files installed.
    """
    count = 0
    dst_dir.mkdir(parents=True, exist_ok=True)
    ignored_names = {"__pycache__", ".DS_Store"}
    ignored_suffixes = {".pyc", ".pyo"}
    for src_file in src_dir.rglob("*"):
        if not src_file.is_file():
            continue
        if any(part in ignored_names for part in src_file.parts):
            continue
        if src_file.suffix in ignored_suffixes:
            continue
        rel = src_file.relative_to(src_dir)
        target = dst_dir / rel
        _install_managed_file(
            src_file,
            target,
            version,
            fenced=fenced,
            executable_suffixes=executable_suffixes,
        )
        count += 1
    return count


_EXEC_SUFFIXES = frozenset((".py", ".sh"))


def create_codex_files(project_path: Path) -> dict[str, int]:
    """Copy Codex template files into target project.

    Creates:
    - .agents/skills/  (map-plan, map-fast, map-check, ...)
    - .codex/agents/   (*.toml agent definitions)
    - .codex/config.toml
    - .codex/hooks.json + .codex/hooks/workflow-gate.py
    - AGENTS.md at project root (symlink to CLAUDE.md when it exists,
      standalone copy otherwise)

    Watched files (skills, agents, config, AGENTS.md, hooks) are installed
    fence-aware so a re-install preserves any user content below the fence;
    hooks.json is JSON (fully-managed via _map_managed); .map/scripts is
    MAP-owned (fenced=False, skip-if-exists).

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
    agents_dir = project_path / ".agents"
    version = _get_version()

    # ------------------------------------------------------------------
    # 1. Skills — watched (fence-aware)
    # ------------------------------------------------------------------
    skills_src = codex_templates / "skills"
    if skills_src.exists():
        # Same host-conditional requires-* gate as the Claude provider, so the
        # requires-* contract is enforced identically across providers. The
        # Codex skills tree ships no skill-rules.json today, so the catalog is
        # empty and nothing is gated — but a future Codex skill declaring
        # requires-* is honoured without re-implementing the gate here.
        skill_catalog = _load_template_skill_catalog(skills_src)
        skipped: list[str] = []
        for skill_dir in sorted(skills_src.iterdir()):
            if not skill_dir.is_dir() or skill_dir.name == "__pycache__":
                continue

            skill_name = skill_dir.name
            entry = skill_catalog.get(skill_name, {})
            requires_block = _extract_requires_block(skill_name, entry)

            req_skills = entry.get("requires-skills") if isinstance(entry, dict) else None
            if isinstance(req_skills, list) and req_skills:
                _warn_requires_skills(skill_name, req_skills)

            missing = _skill_missing_dependency(requires_block)
            if missing is not None:
                kind, dep_name = missing
                print(f"[skipped: {skill_name}: missing {kind} {dep_name}]")
                skipped.append(skill_name)
                continue

            skill_dst = agents_dir / "skills" / skill_name
            counts["skills"] += _copy_tree(skill_dir, skill_dst, version)

        _prune_catalog_entries(agents_dir / "skills" / "skill-rules.json", skipped)

    # ------------------------------------------------------------------
    # 2. Agents (*.toml) — watched (fence-aware)
    # ------------------------------------------------------------------
    agents_src = codex_templates / "agents"
    if agents_src.exists():
        agents_dst = codex_dir / "agents"
        agents_dst.mkdir(parents=True, exist_ok=True)
        for src_file in agents_src.glob("*.toml"):
            _install_managed_file(src_file, agents_dst / src_file.name, version)
            counts["agents"] += 1

    # ------------------------------------------------------------------
    # 3. config.toml — watched (fence-aware)
    # ------------------------------------------------------------------
    config_src = codex_templates / "config.toml"
    if config_src.exists():
        _install_managed_file(config_src, codex_dir / "config.toml", version)
        counts["config"] += 1

    # ------------------------------------------------------------------
    # 4. Hooks (hooks.json + hooks/*.py)
    #    hooks.json is JSON (fully-managed via _map_managed, no fence);
    #    hooks/*.py are watched (fence-aware) with exec bits preserved.
    # ------------------------------------------------------------------
    hooks_json_src = codex_templates / "hooks.json"
    if hooks_json_src.exists():
        _install_managed_file(hooks_json_src, codex_dir / "hooks.json", version)
        counts["hooks"] += 1

    hooks_dir_src = codex_templates / "hooks"
    if hooks_dir_src.exists():
        hooks_dst = codex_dir / "hooks"
        counts["hooks"] += _copy_tree(
            hooks_dir_src, hooks_dst, version, executable_suffixes=_EXEC_SUFFIXES
        )

    # ------------------------------------------------------------------
    # 5. AGENTS.md at project root
    #    - Symlink to CLAUDE.md when CLAUDE.md exists (single source of truth)
    #    - Standalone fence-aware copy from template otherwise
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
                _install_managed_file(agents_md_src, agents_md_dst, version)
            counts["docs"] += 1

    # ------------------------------------------------------------------
    # 6. .map/scripts/ — skip-if-exists (do not overwrite user scripts)
    #    MAP-owned: install fenced=False (no fence) when absent.
    # ------------------------------------------------------------------
    map_scripts_dst = project_path / ".map" / "scripts"
    if not map_scripts_dst.exists():
        map_scripts_src = templates_dir / "map" / "scripts"
        if map_scripts_src.exists():
            counts["scripts"] = _copy_tree(
                map_scripts_src,
                map_scripts_dst,
                version,
                fenced=False,
                executable_suffixes=_EXEC_SUFFIXES,
            )

    return counts
