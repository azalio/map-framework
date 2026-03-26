"""File copy/generation functions for MAP Framework delivery."""

from __future__ import annotations

import shutil
import sys
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
            result = copy_managed_file(ref_file, dest_file, version)
            if drift_report is not None:
                drift_report.results.append(result)
            count += 1

    return count


def create_command_files(
    project_path: Path,
    drift_report: DriftReport | None = None,
) -> int:
    """Create MAP slash commands in .claude/commands/."""
    commands_dir = project_path / ".claude" / "commands"
    commands_dir.mkdir(parents=True, exist_ok=True)

    # Get templates directory
    templates_dir = get_templates_dir()
    commands_template_dir = templates_dir / "commands"

    if not commands_template_dir.exists():
        # Fallback to inline generation if templates not found
        commands = {
            "map-efficient": """---
description: Implement features with optimized workflow (recommended)
---

Implement the following with efficient MAP workflow:

$ARGUMENTS

Start with task decomposition (task-decomposer), then iterate through actor-monitor for each subtask.
Predictor is called conditionally for high-risk subtasks only.
Run /map-learn after workflow if you want to preserve lessons learned.
""",
            "map-debug": """---
description: Debug issue using MAP analysis
---

Debug the following issue using MAP workflow:

$ARGUMENTS

Decompose the debugging process (task-decomposer), implement fixes (actor), validate with monitor, and assess impact (predictor).
""",
            "map-fast": """---
description: Quick implementation with minimal validation
---

Use minimal workflow to implement:

$ARGUMENTS

Implement quickly with basic monitor validation only. No learning, no predictor.
    Use for small, low-risk changes where speed matters.
""",
            "map-learn": """---
description: Extract lessons from completed workflows
---

Extract and preserve lessons from recent workflow:

$ARGUMENTS

Call Reflector to extract patterns from recent workflow.
""",
        }

        for name, content in commands.items():
            command_file = commands_dir / f"{name}.md"
            command_file.write_text(content)
        return len(commands)
    else:
        # Copy templates from bundled directory
        version = _get_version()
        count = 0
        for command_template in commands_template_dir.glob("*.md"):
            dest_file = commands_dir / command_template.name
            result = copy_managed_file(command_template, dest_file, version)
            if drift_report is not None:
                drift_report.results.append(result)
            count += 1
        return count


def create_skill_files(project_path: Path) -> int:
    """Create MAP skills in .claude/skills/

    Returns:
        Number of skills installed
    """
    skills_dir = project_path / ".claude" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)

    # Get templates directory
    templates_dir = get_templates_dir()
    skills_template_dir = templates_dir / "skills"

    count = 0

    if skills_template_dir.exists():
        # Copy README.md and skill-rules.json to .claude/skills/
        if (skills_template_dir / "README.md").exists():
            shutil.copy2(skills_template_dir / "README.md", skills_dir / "README.md")

        if (skills_template_dir / "skill-rules.json").exists():
            shutil.copy2(
                skills_template_dir / "skill-rules.json",
                skills_dir / "skill-rules.json",
            )

        # Copy each skill directory
        for skill_template in skills_template_dir.iterdir():
            if skill_template.is_dir() and skill_template.name != "__pycache__":
                target = skills_dir / skill_template.name
                shutil.copytree(skill_template, target, dirs_exist_ok=True)
                count += 1

    return count


def _copy_map_path(src: Path, dest: Path) -> int:
    """Copy a path from map templates to .map/ and mark scripts executable."""
    if dest.exists():
        try:
            if dest.is_dir():
                shutil.rmtree(dest)
            else:
                dest.unlink()
        except (OSError, PermissionError) as e:
            print(
                f"Warning: Could not remove existing {dest}: {e}",
                file=sys.stderr,
            )
    if src.is_dir():
        shutil.copytree(src, dest, dirs_exist_ok=True)
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)

    count = 0
    script_targets = [dest] if dest.is_file() else list(dest.rglob("*"))
    for script in script_targets:
        if script.is_file() and script.suffix in (".sh", ".py"):
            script.chmod(script.stat().st_mode | 0o755)
            count += 1
    return count


def create_map_tools(project_path: Path) -> int:
    """Create .map/ directory with shipped MAP runtime and planning assets."""
    map_dir = project_path / ".map"
    map_dir.mkdir(parents=True, exist_ok=True)

    templates_dir = get_templates_dir()
    map_template_dir = templates_dir / "map"

    count = 0
    if map_template_dir.exists():
        for item in map_template_dir.iterdir():
            count += _copy_map_path(item, map_dir / item.name)

    return count


def create_commands_dir(project_path: Path) -> None:
    """Create commands directory with README."""
    commands_dir = project_path / ".claude" / "commands"
    commands_dir.mkdir(parents=True, exist_ok=True)

    readme = commands_dir / "README.md"
    readme.write_text(
        """# Claude Code Commands

This directory contains custom slash commands for Claude Code.

## Available Commands

- `/map-efficient` - Implement features with optimized workflow (recommended)
- `/map-plan` - Decompose work without implementing it yet
- `/map-task` - Execute a single subtask from an existing plan
- `/map-tdd` - Run a test-first workflow for one task or plan
- `/map-debug` - Debug issues using MAP analysis
- `/map-debate` - Generate variants and synthesize the best result
- `/map-review` - Run a structured review workflow
- `/map-check` - Run workflow quality gates and verification
- `/map-fast` - Quick implementation with minimal validation
- `/map-learn` - Extract lessons from completed workflows
- `/map-release` - Execute MAP Framework package release workflow
- `/map-resume` - Resume an interrupted workflow from `.map/`

## Creating Custom Commands

Create a new `.md` file in this directory with the following format:

```markdown
---
description: Brief description of your command
---

Your command prompt here
```

The filename becomes the command name (without the `.md` extension).
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
