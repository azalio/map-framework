"""Domain skill bootstrap for project-local reference skills.

Generates a minimal, fact-backed .claude/skills/<name>/SKILL.md without
fabricating content: discovered facts come from local files; missing data
becomes explicit placeholders for the user to fill.

This is a project-local skill, not a MAP-managed shipped template. It is
intentionally excluded from skill-rules.json's global catalog so it never
conflicts with MAP's own shipped skill set.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# File globs that may contain secrets — never read their content.
_SECRET_FILENAMES = re.compile(
    r"(\.env|credentials|secrets|\.pem|\.key|id_rsa|\.pfx|\.p12)",
    re.IGNORECASE,
)

# Makefile targets that are clearly safe/read-only.
_SAFE_MAKE_TARGETS = frozenset(
    ["check", "test", "lint", "build", "run", "dev", "start", "format", "fmt", "help"]
)

# npm scripts that are clearly safe.
_SAFE_NPM_SCRIPTS = frozenset(
    ["test", "lint", "build", "dev", "start", "format", "typecheck", "check"]
)

# Top-level directory names worth surfacing in the layout section.
_CANDIDATE_DIRS = (
    "src", "lib", "pkg", "cmd", "app", "api",
    "tests", "test", "docs", "scripts", "configs",
)


def _extract_project_name(project_path: Path) -> str:
    """Extract the project name from common config files or directory name."""
    pyproject = project_path / "pyproject.toml"
    if pyproject.exists():
        text = pyproject.read_text(encoding="utf-8", errors="replace")
        m = re.search(r'^\s*name\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
        if m:
            return m.group(1)

    pkg = project_path / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
            if isinstance(data.get("name"), str) and data["name"]:
                return data["name"]
        except (json.JSONDecodeError, OSError):
            pass

    go_mod = project_path / "go.mod"
    if go_mod.exists():
        text = go_mod.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"^module\s+(\S+)", text, re.MULTILINE)
        if m:
            return m.group(1).rstrip("/").rsplit("/", 1)[-1]

    return project_path.resolve().name


def _extract_readme_summary(project_path: Path) -> str | None:
    """Return the first meaningful non-heading line from README.md, if any."""
    for readme_name in ("README.md", "readme.md", "Readme.md"):
        readme = project_path / readme_name
        if readme.exists():
            text = readme.read_text(encoding="utf-8", errors="replace")
            for line in text.splitlines():
                stripped = line.strip()
                if (
                    stripped
                    and not stripped.startswith("#")
                    and not stripped.startswith("!")
                    and not stripped.startswith("[!")
                    and not stripped.startswith("[![")
                ):
                    return stripped[:200]
            break
    return None


def _extract_key_dirs(project_path: Path) -> list[str]:
    """Identify top-level source directories worth surfacing."""
    found = []
    for candidate in _CANDIDATE_DIRS:
        if (project_path / candidate).is_dir():
            found.append(candidate)
        if len(found) >= 5:
            break
    return found


def _extract_safe_commands(project_path: Path) -> list[str]:
    """Extract read-only / safe commands from Makefile or package.json scripts."""
    commands: list[str] = []

    makefile = project_path / "Makefile"
    if makefile.exists():
        text = makefile.read_text(encoding="utf-8", errors="replace")
        targets = re.findall(r"^([a-zA-Z][a-zA-Z0-9_-]*)\s*:", text, re.MULTILINE)
        for t in targets:
            if t.lower() in _SAFE_MAKE_TARGETS and f"make {t}" not in commands:
                commands.append(f"make {t}")
            if len(commands) >= 4:
                break

    pkg = project_path / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
            scripts = data.get("scripts", {}) if isinstance(data, dict) else {}
            for name in _SAFE_NPM_SCRIPTS:
                if name in scripts:
                    commands.append(f"npm run {name}")
                if len(commands) >= 6:
                    break
        except (json.JSONDecodeError, OSError):
            pass

    pyproject = project_path / "pyproject.toml"
    if pyproject.exists() and not any("pytest" in c for c in commands):
        commands.append("pytest tests/")

    return commands[:6]


def _make_skill_name(raw_name: str) -> str:
    """Normalize a project name to a valid kebab-case skill name."""
    name = raw_name.lower()
    name = re.sub(r"[^a-z0-9]+", "-", name)
    name = name.strip("-")
    return name or "project-domain"


def _resolve_skill_name(user_name: str | None, project_path: Path) -> str:
    """Determine the final skill name from user override or project detection."""
    if user_name:
        return _make_skill_name(user_name)
    project_name = _extract_project_name(project_path)
    return _make_skill_name(project_name) + "-domain"


def _build_skill_md(
    skill_name: str,
    project_name: str,
    summary: str | None,
    key_dirs: list[str],
    safe_commands: list[str],
) -> str:
    """Assemble the SKILL.md content from discovered facts and explicit placeholders."""
    description = (
        f"Project-specific domain context for {project_name}. "
        f"Use when working on {project_name} code, asking about project-specific "
        f"commands, repo layout, or domain terms. "
        f"Do NOT use for general MAP workflow commands (use map-efficient, map-plan, etc.) "
        f"or for cross-project questions."
    )

    purpose_line = (
        summary
        if summary
        else f"<!-- TODO: one-line description of {project_name} -->"
    )

    layout_block = ""
    if key_dirs:
        layout_block = "## Repo Layout\n\n"
        for d in key_dirs:
            layout_block += f"- `{d}/` — <!-- TODO: brief description -->\n"
        layout_block += "\n"

    commands_block = ""
    if safe_commands:
        commands_block = "## Key Commands\n\n"
        for cmd in safe_commands:
            commands_block += f"- `{cmd}`\n"
        commands_block += "\n"

    return (
        f"---\n"
        f"name: {skill_name}\n"
        f"description: >-\n"
        f"  {description}\n"
        f"---\n"
        f"# {skill_name} — Project Domain Reference\n"
        f"\n"
        f"> Generated by `mapify domain-skill init`. Edit freely; this file is yours.\n"
        f"> Replace placeholders with real project facts discovered from local files.\n"
        f"> **Never commit secrets, tokens, passwords, or API keys into this file.**\n"
        f"\n"
        f"## Purpose\n"
        f"\n"
        f"{purpose_line}\n"
        f"\n"
        f"{layout_block}"
        f"{commands_block}"
        f"## Domain Glossary\n"
        f"\n"
        f"<!-- TODO: list key domain terms and their definitions -->\n"
        f"<!-- Example:\n"
        f"- **WidgetId**: UUID identifying a Widget resource.\n"
        f"-->\n"
        f"\n"
        f"## Safety Boundaries\n"
        f"\n"
        f"<!-- TODO: list files or systems this project must never modify -->\n"
        f"\n"
        f"## How This Differs From /map-learn\n"
        f"\n"
        f"- `/map-learn` captures post-workflow lessons after a run completes.\n"
        f"- This skill provides day-one project context before any workflow runs.\n"
        f"- Edit here when you discover stable project-specific knowledge worth persisting.\n"
    )


def create_domain_skill(
    project_path: Path,
    *,
    skill_name: str | None = None,
    overwrite: bool = False,
) -> tuple[Path, bool]:
    """
    Scaffold a project-local reference skill under .claude/skills/<name>/SKILL.md.

    Scans common project files (README.md, pyproject.toml, package.json, go.mod,
    Makefile) to extract factual content. Missing facts become explicit placeholders.
    Secrets are never read or emitted.

    Args:
        project_path: Root of the target project.
        skill_name: Optional explicit skill name (kebab-case). Defaults to
            ``<project-name>-domain`` derived from config files.
        overwrite: If True, overwrite an existing SKILL.md. Defaults to False.

    Returns:
        (skill_file, created) where created=False when the file already existed
        and overwrite=False (no write performed).
    """
    resolved_name = _resolve_skill_name(skill_name, project_path)
    project_name = _extract_project_name(project_path)

    summary = _extract_readme_summary(project_path)
    key_dirs = _extract_key_dirs(project_path)
    safe_commands = _extract_safe_commands(project_path)

    skill_dir = project_path / ".claude" / "skills" / resolved_name
    skill_file = skill_dir / "SKILL.md"

    if skill_file.exists() and not overwrite:
        return skill_file, False

    skill_dir.mkdir(parents=True, exist_ok=True)
    content = _build_skill_md(resolved_name, project_name, summary, key_dirs, safe_commands)
    skill_file.write_text(content, encoding="utf-8")
    return skill_file, True
