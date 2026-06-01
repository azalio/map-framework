"""File copy/generation functions for MAP Framework delivery."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
from pathlib import Path
from typing import List

from mapify_cli.delivery.managed_file_copier import (
    DriftReport,
    copy_managed_file,
)
from mapify_cli.delivery.agent_generator import (
    create_task_decomposer_content,
    create_actor_content,
    create_monitor_content,
    create_predictor_content,
    create_evaluator_content,
    create_reflector_content,
    create_documentation_reviewer_content,
)
from mapify_cli.schemas import SKILL_REQUIREMENTS_KEYS


_IGNORED_TEMPLATE_NAMES = {"__pycache__", ".DS_Store"}
_IGNORED_TEMPLATE_SUFFIXES = {".pyc", ".pyo"}

# Ordered check dispatch for blocking requires-* keys.
# _BLOCKING_REQUIRES_KEYS is derived from SKILL_REQUIREMENTS_KEYS (schema authority).
# The module-level assertion below enforces that _REQUIRES_CHECKER covers EVERY
# blocking key derived from the schema: adding a new blocking key to
# SKILL_REQUIREMENTS_SCHEMA raises AssertionError at import time unless a
# corresponding checker is added here — the invariant is mechanically enforced,
# not just documented.
# requires-skills is warn-only (not a skip), handled separately.
_BLOCKING_REQUIRES_KEYS = {
    k for k in SKILL_REQUIREMENTS_KEYS if k != "requires-skills"
}


def _check_requires_cmd(name: str) -> bool:
    """Return True if CLI command *name* is available on PATH."""
    return shutil.which(name) is not None


def _check_requires_pip(name: str) -> bool:
    """Return True if Python module *name* is importable."""
    try:
        return importlib.util.find_spec(name) is not None
    except (ModuleNotFoundError, ValueError):
        return False


def _check_requires_env(name: str) -> bool:
    """Return True if environment variable *name* is set.

    SECURITY: reads variable NAME presence only — never reads the value,
    never accesses .env files.
    """
    return name in os.environ


_REQUIRES_CHECKER = {
    "requires-cmd": _check_requires_cmd,
    "requires-pip": _check_requires_pip,
    "requires-env": _check_requires_env,
}

# Enforced invariant: every blocking key derived from the schema must have a
# checker entry here.  Adding a new blocking key to SKILL_REQUIREMENTS_SCHEMA
# without a matching checker raises AssertionError at import time.
assert _BLOCKING_REQUIRES_KEYS == set(_REQUIRES_CHECKER), (
    f"_REQUIRES_CHECKER is out of sync with SKILL_REQUIREMENTS_KEYS; "
    f"missing checkers for: {_BLOCKING_REQUIRES_KEYS - set(_REQUIRES_CHECKER)}"
)


def _skill_missing_dependency(requires_block: dict[str, list[str]]) -> tuple[str, str] | None:
    """Return (kind, name) of the first missing blocking dependency, or None.

    Checks requires-cmd, requires-pip, requires-env in that order (dict
    insertion order — cmd first, then pip, then env — guarantees deterministic
    "first missing" reporting).  Every key in _REQUIRES_CHECKER is checked;
    the module-level assertion guarantees _REQUIRES_CHECKER == _BLOCKING_REQUIRES_KEYS,
    so no blocking key can be silently skipped.
    requires-skills is not a blocking dep; call site emits a warning instead.
    """
    for kind, checker in _REQUIRES_CHECKER.items():
        for dep_name in requires_block.get(kind, []):
            if not checker(dep_name):
                return (kind.removeprefix("requires-"), dep_name)
    return None


def _warn_requires_skills(skill_name: str, skill_names: list[str]) -> None:
    """Emit a WARNING for requires-skills entries (read-only; never a skip)."""
    for dep in skill_names:
        print(f"[warning: {skill_name}: requires skill {dep}]")


def _get_version() -> str:
    """Get current mapify-cli version for metadata injection."""
    try:
        from mapify_cli import __version__

        return __version__
    except ImportError:
        return "unknown"


def get_templates_dir() -> Path:
    """Get the path to bundled templates directory."""
    import importlib.resources

    try:
        # Python 3.11+ with importlib.resources.files
        if hasattr(importlib.resources, "files"):
            return Path(str(importlib.resources.files("mapify_cli") / "templates"))
    except Exception:
        pass

    # Fallback to module directory
    module_dir = Path(__file__).parent.parent
    templates_dir = module_dir / "templates"
    if templates_dir.exists():
        return templates_dir

    # Development mode - check parent directories
    for parent in [module_dir.parent, module_dir.parent.parent]:
        templates_dir = parent / "templates"
        if templates_dir.exists():
            return templates_dir

    raise RuntimeError("Templates directory not found. Please reinstall mapify-cli.")


def create_agent_files(
    project_path: Path,
    mcp_servers: List[str],
    drift_report: DriftReport | None = None,
) -> int:
    """Create MAP agent files in .claude/agents/."""
    agents_dir = project_path / ".claude" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)

    # Get templates directory
    templates_dir = get_templates_dir()
    agents_template_dir = templates_dir / "agents"

    if agents_template_dir.exists():
        # Files to exclude from agent directory (documentation, not agents)
        exclude_files = {"README.md", "CHANGELOG.md", "MCP-PATTERNS.md"}
        count = 0
        version = _get_version()

        for agent_template in agents_template_dir.glob("*.md"):
            # Skip documentation files - they're not agents
            if agent_template.name in exclude_files:
                continue
            dest_file = agents_dir / agent_template.name
            result = copy_managed_file(agent_template, dest_file, version)
            if drift_report is not None:
                drift_report.results.append(result)
            count += 1
        return count
    else:
        # Fallback: generate simplified versions if templates not found
        # NOTE: orchestrator removed (moved to slash commands in production architecture)
        agents = {
            "task-decomposer": create_task_decomposer_content(mcp_servers),
            "actor": create_actor_content(mcp_servers),
            "monitor": create_monitor_content(mcp_servers),
            "predictor": create_predictor_content(mcp_servers),
            "evaluator": create_evaluator_content(mcp_servers),
            "reflector": create_reflector_content(mcp_servers),
            "documentation-reviewer": create_documentation_reviewer_content(
                mcp_servers
            ),
        }

        for name, content in agents.items():
            agent_file = agents_dir / f"{name}.md"
            agent_file.write_text(content)
        return len(agents)


def create_reference_files(
    project_path: Path,
    drift_report: DriftReport | None = None,
) -> int:
    """Create MAP reference files in .claude/references/

    Returns:
        Number of reference files installed
    """
    references_dir = project_path / ".claude" / "references"
    references_dir.mkdir(parents=True, exist_ok=True)

    # Get templates directory
    templates_dir = get_templates_dir()
    references_template_dir = templates_dir / "references"

    count = 0
    if references_template_dir.exists():
        version = _get_version()
        for ref_file in references_template_dir.glob("*.md"):
            dest_file = references_dir / ref_file.name
            # References are fully MAP-owned — overwrite on update (no fence).
            result = copy_managed_file(ref_file, dest_file, version, fenced=False)
            if drift_report is not None:
                drift_report.results.append(result)
            count += 1

    return count


def create_command_files(
    project_path: Path,
    drift_report: DriftReport | None = None,
) -> int:
    """Create .claude/commands/ directory structure.

    MAP slash commands are now delivered as skills (.claude/skills/).
    This function creates only the commands directory with a README
    pointing users at the skill-backed surfaces.
    """
    del drift_report  # accepted for caller API compatibility; not used here
    create_commands_dir(project_path)
    return 0


def _load_template_skill_catalog(skills_template_dir: Path) -> dict[str, dict[str, object]]:
    """Parse the template skill-rules.json and return the skills dict.

    Returns an empty dict on any error (missing file, invalid JSON) so the
    caller falls through to unconditional install — defensive, never gate-blocks
    due to a corrupt catalog.
    """
    catalog_path = skills_template_dir / "skill-rules.json"
    try:
        raw = catalog_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        skills = data.get("skills", {})
        if isinstance(skills, dict):
            return skills  # type: ignore[return-value]
    except Exception:  # noqa: BLE001  # FileNotFoundError, JSONDecodeError, etc.
        pass
    return {}


def create_skill_files(project_path: Path) -> int:
    """Create MAP skills in .claude/skills/

    Skips any skill whose blocking runtime dependencies (requires-cmd,
    requires-pip, requires-env) are not satisfied on the current host.
    Prints ``[skipped: <skill>: missing <kind> <name>]`` to stdout for each
    skipped skill.  requires-skills is WARNING-only and never causes a skip.

    Returns:
        Number of skills actually installed (skipped skills not counted).
    """
    skills_dir = project_path / ".claude" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)

    # Get templates directory
    templates_dir = get_templates_dir()
    skills_template_dir = templates_dir / "skills"

    count = 0

    if skills_template_dir.exists():
        version = _get_version()

        # Parse catalog ONCE, defensively (missing/invalid -> empty dict -> no gate).
        skill_catalog = _load_template_skill_catalog(skills_template_dir)

        # Top-level skill catalog files (README.md, skill-rules.json).
        for top_name in ("README.md", "skill-rules.json"):
            top_src = skills_template_dir / top_name
            if top_src.exists():
                _install_managed_file(top_src, skills_dir / top_name, version)

        # Copy each skill directory, fence-aware per file (watched category).
        for skill_template in sorted(skills_template_dir.iterdir()):
            if not (skill_template.is_dir() and skill_template.name != "__pycache__"):
                continue

            skill_name = skill_template.name
            entry = skill_catalog.get(skill_name, {})
            requires_block: dict[str, list[str]] = {
                k: v  # type: ignore[assignment]
                for k, v in entry.items()
                if k in _BLOCKING_REQUIRES_KEYS and isinstance(v, list)
            }

            # Emit WARNING for requires-skills (read-only; never a skip).
            req_skills = entry.get("requires-skills")
            if isinstance(req_skills, list) and req_skills:
                _warn_requires_skills(skill_name, req_skills)

            # Check blocking deps; skip on first missing.
            missing = _skill_missing_dependency(requires_block)
            if missing is not None:
                kind, dep_name = missing
                print(f"[skipped: {skill_name}: missing {kind} {dep_name}]")
                continue

            _install_managed_tree(skill_template, skills_dir / skill_name, version)
            count += 1

    return count


def _install_managed_file(src: Path, dest: Path, version: str) -> None:
    """Install a single watched file fence-aware, preserving executable bits."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    copy_managed_file(src, dest, version)
    if src.suffix in (".sh", ".py") and dest.exists():
        dest.chmod(dest.stat().st_mode | 0o755)


def _install_managed_tree(src_dir: Path, dest_dir: Path, version: str) -> None:
    """Recursively install a directory of watched files via copy_managed_file."""
    for src in sorted(src_dir.rglob("*")):
        if not src.is_file():
            continue
        if src.name in _IGNORED_TEMPLATE_NAMES or src.suffix in _IGNORED_TEMPLATE_SUFFIXES:
            continue
        rel = src.relative_to(src_dir)
        _install_managed_file(src, dest_dir / rel, version)


def _copy_map_path(src: Path, dest: Path, version: str) -> int:
    """Install a map-tools path into .map/ fully-managed (fenced=False), +x scripts.

    MAP runtime scripts/static-analysis are MAP-owned: overwrite on update with a
    .bak.<ts> on drift (Phase B behavior), never fence them.  Executable bits are
    restored after the metadata-injecting write.
    """
    count = 0
    if src.is_dir():
        for child in sorted(src.rglob("*")):
            if not child.is_file():
                continue
            if child.name in _IGNORED_TEMPLATE_NAMES or child.suffix in _IGNORED_TEMPLATE_SUFFIXES:
                continue
            rel = child.relative_to(src)
            count += _install_map_file(child, dest / rel, version)
    else:
        count += _install_map_file(src, dest, version)
    return count


def _install_map_file(src: Path, dest: Path, version: str) -> int:
    """Install one MAP-owned file (overwrite mode) and mark scripts executable."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    copy_managed_file(src, dest, version, fenced=False)
    if src.suffix in (".sh", ".py") and dest.exists():
        dest.chmod(dest.stat().st_mode | 0o755)
        return 1
    return 0


def create_map_tools(project_path: Path) -> int:
    """Create .map/ directory with shipped MAP runtime and planning assets."""
    map_dir = project_path / ".map"
    map_dir.mkdir(parents=True, exist_ok=True)

    templates_dir = get_templates_dir()
    map_template_dir = templates_dir / "map"

    count = 0
    if map_template_dir.exists():
        version = _get_version()
        for item in map_template_dir.iterdir():
            count += _copy_map_path(item, map_dir / item.name, version)

    return count


def create_commands_dir(project_path: Path) -> None:
    """Create commands directory with README pointing at skill-backed surfaces."""
    commands_dir = project_path / ".claude" / "commands"
    commands_dir.mkdir(parents=True, exist_ok=True)

    readme = commands_dir / "README.md"
    readme.write_text(
        """# Claude Code Commands

This directory exists for **user-custom** slash commands. All MAP slash
commands now ship as Skills (`.claude/skills/map-*/SKILL.md`) which give
the same `/map-*` interface but with progressive disclosure (skill body
loads on demand instead of always living in context).

## MAP Slash Commands (skill-backed)

All of these are implemented via `.claude/skills/<name>/SKILL.md`:

- `/map-plan` - Decompose work without implementing it yet
- `/map-efficient` - Implement features with optimized workflow (recommended)
- `/map-fast` - Quick implementation with minimal validation
- `/map-task` - Execute a single subtask from an existing plan
- `/map-tdd` - Run a test-first workflow for one task or plan
- `/map-debug` - Debug issues using MAP analysis
- `/map-review` - Run a structured review workflow
- `/map-check` - Run workflow quality gates and verification
- `/map-release` - Execute MAP Framework package release workflow
- `/map-resume` - Resume an interrupted workflow from `.map/`
- `/map-learn` - Extract lessons from completed workflows

## Creating Custom Commands

Create a new `.md` file in this directory with the following format:

```markdown
---
description: Brief description of your command
---

Your command prompt here
```

The filename becomes the command name (without the `.md` extension).
Per the Claude Code docs, a skill at `.claude/skills/<name>/SKILL.md`
takes precedence over a command at `.claude/commands/<name>.md` with
the same name.
"""
    )


def create_hook_files(
    project_path: Path,
    drift_report: DriftReport | None = None,
) -> int:
    """Create MAP hook files in .claude/hooks/

    Returns:
        Number of hook files installed
    """
    hooks_dir = project_path / ".claude" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)

    # Get templates directory
    templates_dir = get_templates_dir()
    hooks_template_dir = templates_dir / "hooks"

    count = 0
    if hooks_template_dir.exists():
        version = _get_version()
        for hook_file in hooks_template_dir.iterdir():
            if hook_file.is_file():
                dest_file = hooks_dir / hook_file.name
                result = copy_managed_file(hook_file, dest_file, version)
                if drift_report is not None:
                    drift_report.results.append(result)
                # Preserve executable permissions
                if hook_file.suffix in (".sh", ".py"):
                    dest_file.chmod(0o755)
                count += 1

    return count


def create_config_files(
    project_path: Path,
    drift_report: DriftReport | None = None,
) -> int:
    """Create MAP config files in .claude/

    Copies configuration files:
    - settings.json
    - ralph-loop-config.json
    - workflow-rules.json

    Returns:
        Number of config files installed
    """
    claude_dir = project_path / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)

    # Get templates directory
    templates_dir = get_templates_dir()

    config_files = [
        "settings.json",
        "ralph-loop-config.json",
        "workflow-rules.json",
    ]

    count = 0
    version = _get_version()

    for config_file in config_files:
        template_file = templates_dir / config_file
        if template_file.exists():
            dest_file = claude_dir / config_file
            result = copy_managed_file(template_file, dest_file, version)
            if drift_report is not None:
                drift_report.results.append(result)
            count += 1

    return count


def create_rules_dir(
    project_path: Path,
    drift_report: DriftReport | None = None,
) -> int:
    """Create .claude/rules/learned/ directory with README.

    Creates the directory structure for persisting lessons extracted by
    /map-learn. The README is copied from templates and managed; existing
    user rules files are never touched.

    Returns:
        Number of files installed (0 or 1 for README).
    """
    rules_dir = project_path / ".claude" / "rules" / "learned"
    rules_dir.mkdir(parents=True, exist_ok=True)

    templates_dir = get_templates_dir()
    readme_template = templates_dir / "rules" / "learned" / "README.md"

    count = 0
    if readme_template.exists():
        dest = rules_dir / "README.md"
        if not dest.exists():
            version = _get_version()
            result = copy_managed_file(readme_template, dest, version)
            if drift_report is not None:
                drift_report.results.append(result)
            count += 1

    return count
