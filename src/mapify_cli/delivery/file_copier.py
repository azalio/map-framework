"""File copy/generation functions for MAP Framework delivery."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from mapify_cli.delivery.agent_generator import (
    create_actor_content,
    create_documentation_reviewer_content,
    create_evaluator_content,
    create_monitor_content,
    create_predictor_content,
    create_reflector_content,
    create_task_decomposer_content,
)
from mapify_cli.delivery.managed_file_copier import (
    DriftReport,
    copy_managed_file,
)
from mapify_cli.schemas import (
    SKILL_REQUIREMENTS_KEYS,
    SKILL_REQUIREMENTS_SCHEMA,
    validate_artifact,
)

_IGNORED_TEMPLATE_NAMES = {"__pycache__", ".DS_Store"}
_IGNORED_TEMPLATE_SUFFIXES = {".pyc", ".pyo"}

# Ordered check dispatch for blocking requires-* keys.
# _BLOCKING_REQUIRES_KEYS is derived from SKILL_REQUIREMENTS_KEYS (schema authority).
# The module-level check below enforces that _REQUIRES_CHECKER covers EVERY
# blocking key derived from the schema: adding a new blocking key to
# SKILL_REQUIREMENTS_SCHEMA raises RuntimeError at import time unless a
# corresponding checker is added here — the invariant is mechanically enforced,
# not just documented. (A bare ``assert`` would be stripped under ``python -O``,
# silently turning the guarantee into a no-op, so we raise explicitly.)
# requires-skills is warn-only (not a skip), handled separately.
_BLOCKING_REQUIRES_KEYS = {
    k for k in SKILL_REQUIREMENTS_KEYS if k != "requires-skills"
}


def _check_requires_cmd(name: str) -> bool:
    """Return True if CLI command *name* is available on PATH.

    Mirrors ``check_tool()`` in ``mapify_cli.__init__``: the Claude CLI may be
    installed only at ``~/.claude/local/claude`` (not on PATH), so that location
    counts as present. Kept deliberately in sync — importing ``check_tool`` here
    would create a circular import (``mapify_cli.__init__`` imports this module).
    """
    if name == "claude":
        claude_local = Path.home() / ".claude" / "local" / "claude"
        if claude_local.is_file():
            return True
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
# without a matching checker raises RuntimeError at import time.  Uses an
# explicit raise (not ``assert``) so the guarantee survives ``python -O``.
if _BLOCKING_REQUIRES_KEYS != set(_REQUIRES_CHECKER):
    raise RuntimeError(
        "_REQUIRES_CHECKER is out of sync with SKILL_REQUIREMENTS_KEYS; "
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


def _extract_requires_block(skill_name: str, entry: object) -> dict[str, list[str]]:
    """Return the blocking requires-* sub-block (list-valued) for a skill entry.

    Defensive against a malformed catalog so a single bad entry never corrupts
    the install:
    - a non-dict entry yields ``{}`` (no requirements; never raises);
    - the requires-* sub-block is validated against SKILL_REQUIREMENTS_SCHEMA and
      any violation is surfaced as a ``[warning: ...]`` (never silently dropped),
      so a typo'd scalar like ``"requires-cmd": "git"`` cannot quietly disable the
      gate. This is where the schema earns its keep at install time.

    Only well-formed list-of-strings blocking keys are returned for enforcement.
    """
    if not isinstance(entry, dict):
        return {}
    sub_block = {k: entry[k] for k in SKILL_REQUIREMENTS_KEYS if k in entry}
    if sub_block:
        valid, errors = validate_artifact(sub_block, SKILL_REQUIREMENTS_SCHEMA)
        if not valid:
            print(
                f"[warning: {skill_name}: malformed requires-* in skill-rules.json: "
                f"{'; '.join(errors)}]"
            )
    return {
        k: v
        for k, v in sub_block.items()
        if k in _BLOCKING_REQUIRES_KEYS
        and isinstance(v, list)
        and all(isinstance(item, str) for item in v)
    }


def _prune_catalog_entries(catalog_path: Path, skill_names: list[str]) -> None:
    """Remove *skill_names* from the INSTALLED skill-rules.json.

    Keeps the installed catalog consistent with the on-disk skill set: a skill
    skipped for a missing host dependency must not remain advertised in
    skill-rules.json (a listed-but-absent skill would dangle when its triggers
    fire). Preserves the ``_map_managed`` sentinel and JSON formatting written by
    the managed-file copier. No-op on read/parse error or if nothing matched.
    """
    if not skill_names or not catalog_path.exists():
        return
    try:
        data = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    skills = data.get("skills") if isinstance(data, dict) else None
    if not isinstance(skills, dict):
        return
    changed = False
    for name in skill_names:
        if name in skills:
            del skills[name]
            changed = True
    if changed:
        catalog_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )


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
    except Exception:  # noqa: BLE001, S110 -- deliberate fallback/resilience boundary, must not propagate
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
    mcp_servers: list[str],
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
    except Exception:  # noqa: BLE001, S110# FileNotFoundError, JSONDecodeError, etc.
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
        skipped: list[str] = []
        for skill_template in sorted(skills_template_dir.iterdir()):
            if not (skill_template.is_dir() and skill_template.name != "__pycache__"):
                continue

            skill_name = skill_template.name
            entry = skill_catalog.get(skill_name, {})
            requires_block = _extract_requires_block(skill_name, entry)

            # Emit WARNING for requires-skills (read-only; never a skip).
            req_skills = entry.get("requires-skills") if isinstance(entry, dict) else None
            if isinstance(req_skills, list) and req_skills:
                _warn_requires_skills(skill_name, req_skills)

            # Check blocking deps; skip on first missing.
            missing = _skill_missing_dependency(requires_block)
            if missing is not None:
                kind, dep_name = missing
                print(f"[skipped: {skill_name}: missing {kind} {dep_name}]")
                skipped.append(skill_name)
                continue

            _install_managed_tree(skill_template, skills_dir / skill_name, version)
            count += 1

        # Keep the installed catalog consistent with the on-disk skill set:
        # a skill skipped above must not stay advertised in skill-rules.json.
        _prune_catalog_entries(skills_dir / "skill-rules.json", skipped)

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


_SOFA_GITIGNORE_MARKER = "# map:sofa"
_SOFA_GITIGNORE_BLOCK = (
    "# map:sofa — SOFA credential dir (opt-in); never commit. See docs/USAGE.md\n"
    ".sofa/\n"
)


def merge_sofa_gitignore(project_path: Path) -> int:
    """Idempotently add .sofa/ entry to the repo-root .gitignore.

    Operates on ``project_path / ".gitignore"`` (NOT ``.claude/.gitignore``).
    Returns 1 when the file was created or modified, 0 when already up-to-date
    (no-op / idempotent).
    """
    gitignore = project_path / ".gitignore"

    if not gitignore.exists():
        gitignore.write_text(_SOFA_GITIGNORE_BLOCK)
        return 1

    existing = gitignore.read_text()

    # Idempotency: skip if our marker OR an active `.sofa/` line is already
    # present. The OR is deliberate (not AND): if the user already ignores
    # `.sofa/` without our marker, appending the block would create a duplicate
    # entry. Skipping on either signal keeps `.sofa/` present exactly once. The
    # stripped-line-set check is symmetric with ensure_sofa_gitignore in the
    # shipped sofa_client.py (avoids false matches on comments/path fragments).
    ignored_lines = {line.strip() for line in existing.splitlines()}
    if _SOFA_GITIGNORE_MARKER in existing or ".sofa/" in ignored_lines:
        return 0

    # Append with a separating newline if the file does not end with one.
    separator = "" if existing.endswith("\n") else "\n"
    gitignore.write_text(existing + separator + _SOFA_GITIGNORE_BLOCK)
    return 1


_AGENT_MEMORY_LOCAL_GITIGNORE_MARKER = "# map:agent-memory-local"
_AGENT_MEMORY_LOCAL_GITIGNORE_BLOCK = (
    "# map:agent-memory-local — user-local agent memory (opt-in); never commit.\n"
    ".claude/agent-memory-local/\n"
)


def merge_agent_memory_gitignore(project_path: Path) -> int:
    """Idempotently add .claude/agent-memory-local/ to the repo-root .gitignore.

    Only called when ``--agent-memory local`` is used. The project-scoped level
    (``--agent-memory project``) writes to ``.claude/agent-memory/`` which IS
    intended to be committed, so no gitignore entry is needed for it.

    Returns 1 when the file was created or modified, 0 when already up-to-date.
    """
    gitignore = project_path / ".gitignore"

    if not gitignore.exists():
        gitignore.write_text(_AGENT_MEMORY_LOCAL_GITIGNORE_BLOCK)
        return 1

    existing = gitignore.read_text()

    # OR-not-AND idempotency guard: skip if our marker OR the exact path is
    # already present (prevents duplicates when user already has the line).
    ignored_lines = {line.strip() for line in existing.splitlines()}
    if (
        _AGENT_MEMORY_LOCAL_GITIGNORE_MARKER in existing
        or ".claude/agent-memory-local/" in ignored_lines
    ):
        return 0

    separator = "" if existing.endswith("\n") else "\n"
    gitignore.write_text(existing + separator + _AGENT_MEMORY_LOCAL_GITIGNORE_BLOCK)
    return 1


def apply_reflector_memory_field(project_path: Path, level: str) -> int:
    """Add or update the ``memory:`` frontmatter field in the installed reflector.md.

    Called post-install when ``--agent-memory`` is ``"local"`` or ``"project"``.
    Idempotent: if the field already exists with the correct value it is left
    unchanged; if it exists with a different value it is replaced.

    Args:
        project_path: root of the target project (installed ``.claude/`` lives here).
        level: ``"local"`` or ``"project"`` (caller is responsible for validation;
               ``"off"`` callers must not invoke this function).

    Returns:
        1 if the file was modified, 0 if already up-to-date or not found.
    """
    import re

    reflector_path = project_path / ".claude" / "agents" / "reflector.md"
    if not reflector_path.exists():
        return 0

    text = reflector_path.read_text(encoding="utf-8")

    # Determine the correct memory field value based on level.
    # "local"   → memory: user_local   (maps to .claude/agent-memory-local/)
    # "project" → memory: project      (maps to .claude/agent-memory/)
    memory_value = "user_local" if level == "local" else "project"
    new_field_line = f"memory: {memory_value}"

    # If a `memory:` line already exists in the frontmatter, replace it.
    existing_memory_re = re.compile(r"(?m)^memory\s*:.*$")
    if existing_memory_re.search(text):
        updated = existing_memory_re.sub(new_field_line, text, count=1)
        if updated == text:
            return 0  # already up-to-date
        reflector_path.write_text(updated, encoding="utf-8")
        return 1

    # Inject the `memory:` line into the YAML frontmatter, just before the
    # closing `---` delimiter. This preserves the existing frontmatter structure.
    # Match the opening `---\n ... \n---` block.
    frontmatter_re = re.compile(r"^(---\n.*?\n)(---)", re.DOTALL)
    m = frontmatter_re.match(text)
    if not m:
        # No frontmatter — prepend a minimal one.
        updated = f"---\n{new_field_line}\n---\n{text}"
    else:
        # Insert before the closing `---`.
        updated = text[: m.start(2)] + new_field_line + "\n" + text[m.start(2) :]

    reflector_path.write_text(updated, encoding="utf-8")
    return 1


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


@dataclass
class StatuslineResult:
    """Outcome of :func:`ensure_map_statusline`.

    ``wired`` is True only when a fresh ``statusLine`` entry was written.
    ``reason`` is ``"wired"`` on success, or ``"existing:<scope>"`` when an
    existing status line in the ``user`` / ``project`` / ``local`` scope was
    detected and left untouched.
    """

    wired: bool
    reason: str
    settings_path: Path | None = None


def _read_json_object(path: Path) -> dict | None:
    """Return a parsed JSON object, or None if missing/unreadable/not an object."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _has_status_line(path: Path) -> bool:
    """True when *path* is a settings JSON that already defines a ``statusLine``."""
    obj = _read_json_object(path)
    return bool(obj and obj.get("statusLine"))


def ensure_map_statusline(
    project_path: Path,
    *,
    home: Path | None = None,
) -> StatuslineResult:
    """Non-destructively wire the MAP context status line.

    Claude Code's ``statusLine`` setting fully owns the status row, so MAP must
    never overwrite a status line the user already configured. This detects an
    existing ``statusLine`` in every scope MAP must respect — highest precedence
    first —

      * ``<project>/.claude/settings.local.json`` (project-local overrides)
      * ``<project>/.claude/settings.json``       (project, MAP-managed)
      * ``~/.claude/settings.json``               (user global)

    and, only when NONE is present, merges a ``statusLine`` entry pointing at the
    installed ``map-statusline.py`` hook into ``.claude/settings.local.json``.

    ``settings.local.json`` is deliberately chosen over the MAP-managed
    ``settings.json``: it is user-owned and never re-rendered by the managed
    copier, so the injection introduces no template drift and creates no ``.bak``
    churn on upgrade. The merge preserves any pre-existing keys in that file, and
    the operation is idempotent — a second ``mapify init`` detects MAP's own
    entry and skips.

    Args:
        project_path: Root of the target project.
        home: Override for the user home directory (test seam). Defaults to
            ``Path.home()``.

    Returns:
        StatuslineResult describing whether a status line was wired or skipped.
    """
    home_dir = home if home is not None else Path.home()
    claude_dir = project_path / ".claude"
    scope_paths = {
        "local": claude_dir / "settings.local.json",
        "project": claude_dir / "settings.json",
        "user": home_dir / ".claude" / "settings.json",
    }

    # Highest-precedence scope first so the reported scope is the one that would
    # actually win at runtime.
    for scope in ("local", "project", "user"):
        if _has_status_line(scope_paths[scope]):
            return StatuslineResult(wired=False, reason=f"existing:{scope}")

    local_settings = scope_paths["local"]
    hook_path = claude_dir / "hooks" / "map-statusline.py"
    # Absolute, quoted path: settings.local.json is machine-local, and quoting
    # keeps the shell-invoked command correct when the project path has spaces.
    command = f'"{hook_path}"'

    settings = _read_json_object(local_settings) or {}
    settings["statusLine"] = {"type": "command", "command": command}

    claude_dir.mkdir(parents=True, exist_ok=True)
    local_settings.write_text(
        json.dumps(settings, indent=2) + "\n", encoding="utf-8"
    )
    return StatuslineResult(
        wired=True, reason="wired", settings_path=local_settings
    )


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
