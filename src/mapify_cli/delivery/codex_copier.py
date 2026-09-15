"""Codex CLI provider delivery module.

Copies bundled templates/codex/ into a target project's Codex discovery
locations and installs AGENTS.md at the project root.

Never touches .claude/.
"""

from __future__ import annotations

import json
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any

from mapify_cli.delivery.file_copier import (
    _IGNORED_TEMPLATE_NAMES,
    _IGNORED_TEMPLATE_SUFFIXES,
    _copy_map_path,
    _extract_requires_block,
    _get_version,
    _load_template_skill_catalog,
    _prune_catalog_entries,
    _skill_missing_dependency,
    _warn_requires_skills,
    get_templates_dir,
)
from mapify_cli.delivery.managed_file_copier import (
    _assert_safe_dest,
    _atomic_write,
    copy_managed_file,
)


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
    for src_file in src_dir.rglob("*"):
        if not src_file.is_file():
            continue
        if any(part in _IGNORED_TEMPLATE_NAMES for part in src_file.parts):
            continue
        if src_file.suffix in _IGNORED_TEMPLATE_SUFFIXES:
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


def _first_symlink_component(root: Path, dest: Path) -> Path | None:
    """Return the first component of *dest* below *root* that is a symlink.

    Checked component by component (``.map``, then ``.map/scripts``) so a
    linked ancestor cannot redirect the runtime install outside *root*.
    """
    current = root
    for part in dest.relative_to(root).parts:
        current = current / part
        if current.is_symlink():
            return current
    return None


def _managed_codex_hook_names(hooks_dir_src: Path) -> frozenset[str]:
    """Names of the scripts mapify ships into .codex/hooks/ — the MAP-owned set."""
    if not hooks_dir_src.is_dir():
        return frozenset()
    return frozenset(
        path.name for path in hooks_dir_src.iterdir() if path.suffix in _EXEC_SUFFIXES
    )


def _is_map_managed_codex_hook(hook: Any, managed_names: frozenset[str]) -> bool:
    """True when *hook* runs a script mapify ships into .codex/hooks/.

    Only shipped names match: a project-owned script that also lives in
    .codex/hooks/ (e.g. custom-policy.py) is preserved across reinstall.
    Matching MAP hooks are dropped and re-added from the template so a changed
    registration cannot accumulate a stale duplicate.
    """
    if not isinstance(hook, dict):
        return False
    command = hook.get("command")
    if not isinstance(command, str):
        return False
    return any(f".codex/hooks/{name}" in command for name in managed_names)


def _merge_codex_hook_entries(
    existing_entries: Any,
    template_entries: Any,
    managed_names: frozenset[str],
) -> list[Any]:
    """Merge MAP hook entries into existing Codex hook entries.

    Existing project hooks are preserved. MAP-owned command hooks (any script
    in *managed_names*) are refreshed from the template and de-duplicated.
    """
    merged_entries: list[Any] = []
    if isinstance(existing_entries, list):
        for raw_entry in deepcopy(existing_entries):
            if not isinstance(raw_entry, dict):
                merged_entries.append(raw_entry)
                continue

            raw_hooks = raw_entry.get("hooks")
            if not isinstance(raw_hooks, list):
                merged_entries.append(raw_entry)
                continue

            cleaned_hooks = [
                hook
                for hook in raw_hooks
                if not _is_map_managed_codex_hook(hook, managed_names)
            ]
            if not cleaned_hooks and len(cleaned_hooks) != len(raw_hooks):
                continue

            raw_entry["hooks"] = cleaned_hooks
            merged_entries.append(raw_entry)

    if not isinstance(template_entries, list):
        return merged_entries

    for template_entry in template_entries:
        if not isinstance(template_entry, dict):
            if template_entry not in merged_entries:
                merged_entries.append(deepcopy(template_entry))
            continue

        matcher = template_entry.get("matcher")
        template_hooks = template_entry.get("hooks")
        target = None
        if isinstance(matcher, str) and isinstance(template_hooks, list):
            for entry in merged_entries:
                if (
                    isinstance(entry, dict)
                    and entry.get("matcher") == matcher
                    and isinstance(entry.get("hooks"), list)
                ):
                    target = entry
                    break

        if target is None:
            if template_entry not in merged_entries:
                merged_entries.append(deepcopy(template_entry))
            continue

        assert isinstance(template_hooks, list)
        target_hooks = target["hooks"]
        assert isinstance(target_hooks, list)
        for hook in template_hooks:
            if hook not in target_hooks:
                target_hooks.append(deepcopy(hook))

    return merged_entries


def _merge_codex_hooks_json(
    existing_data: dict[str, Any] | None,
    template_data: dict[str, Any],
    managed_names: frozenset[str],
) -> dict[str, Any]:
    """Return Codex-valid hooks.json containing only the top-level hooks key."""
    existing_hooks = existing_data.get("hooks") if existing_data else None
    template_hooks = template_data.get("hooks")

    merged_hooks: dict[str, Any] = (
        deepcopy(existing_hooks) if isinstance(existing_hooks, dict) else {}
    )

    if isinstance(template_hooks, dict):
        for event_name, template_entries in template_hooks.items():
            merged_hooks[event_name] = _merge_codex_hook_entries(
                merged_hooks.get(event_name),
                template_entries,
                managed_names,
            )

    return {"hooks": merged_hooks}


def _load_json_object(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _install_codex_hooks_json(src: Path, dst: Path, hooks_dir_src: Path) -> None:
    """Install .codex/hooks.json without MAP metadata and merge project hooks."""
    template_data = _load_json_object(src)
    if template_data is None:
        raise ValueError(f"Invalid Codex hooks template JSON: {src}")

    dst.parent.mkdir(parents=True, exist_ok=True)

    existing_data: dict[str, Any] | None = None
    if dst.exists():
        _assert_safe_dest(dst)
        existing_data = _load_json_object(dst)

    merged = _merge_codex_hooks_json(
        existing_data, template_data, _managed_codex_hook_names(hooks_dir_src)
    )
    _atomic_write(dst, json.dumps(merged, indent=2, ensure_ascii=False) + "\n")


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
    hooks.json is merged without MAP metadata because Codex validates top-level
    keys strictly; .map/scripts is MAP-owned and refreshed exactly like the
    Claude provider's tree (``_copy_map_path``: shipped scripts are overwritten,
    a drifted managed copy is backed up to ``.bak.<ts>`` first, project-added
    files are left alone).

    Never creates or modifies any .claude/ path.

    Args:
        project_path: Root directory of the target project.

    Returns:
        Mapping of category name to number of files installed/created.
        Categories: skills, agents, config, hooks, docs
    """
    templates_dir = get_templates_dir()
    codex_templates = templates_dir / "codex"
    map_scripts_src = templates_dir / "map" / "scripts"
    map_scripts_dst = project_path / ".map" / "scripts"

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

    if map_scripts_src.exists():
        link = _first_symlink_component(project_path, map_scripts_dst)
        if link is not None:
            raise RuntimeError(
                f"{link} is a symbolic link; mapify will not install .map/scripts "
                "through it. Replace the link with a real directory and re-run."
            )

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

            req_skills = (
                entry.get("requires-skills") if isinstance(entry, dict) else None
            )
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

    # Provider-neutral references used by Codex skills. They intentionally live
    # under .agents/references so ../../references links from each skill resolve.
    references_src = codex_templates / "references"
    if references_src.exists():
        counts["docs"] += _copy_tree(
            references_src,
            agents_dir / "references",
            version,
        )

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
    #    hooks.json must remain Codex-schema-valid, so install it with a
    #    Codex-specific merge instead of the generic _map_managed JSON copier.
    #    hooks/*.py are watched (fence-aware) with exec bits preserved.
    # ------------------------------------------------------------------
    hooks_json_src = codex_templates / "hooks.json"
    if hooks_json_src.exists():
        _install_codex_hooks_json(
            hooks_json_src, codex_dir / "hooks.json", codex_templates / "hooks"
        )
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
    # 6. .map/scripts/ — MAP-owned, same policy as the Claude provider:
    #    shipped scripts are refreshed (.bak.<ts> on drift), project-added
    #    files are never touched.
    # ------------------------------------------------------------------
    if map_scripts_src.exists():
        counts["scripts"] = _copy_map_path(map_scripts_src, map_scripts_dst, version)

    return counts
