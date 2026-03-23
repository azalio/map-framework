"""Project configuration for MAP Framework."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None

logger = logging.getLogger(__name__)


@dataclass
class MapConfig:
    """MAP Framework project configuration."""

    # Workflow profile: "core", "full", or "custom"
    profile: str = "full"

    # Project context injected into all agent prompts
    context: str = ""

    # Per-phase rules (injected only into matching phase prompts)
    rules: dict[str, list[str]] = field(default_factory=dict)

    # Verification commands
    verification_checks: list[str] = field(default_factory=list)

    # Policy thresholds
    research_threshold_existing_files: int = 3
    final_verify_subtask_threshold: int = 5
    actor_monitor_max_retries: int = 5
    stuck_recovery_at: int = 3
    guard_rework_max: int = 2
    confidence_threshold: float = 0.7

    # Safety guardrails (overridable)
    safe_path_prefixes: list[str] = field(
        default_factory=lambda: [
            "src/",
            "lib/",
            "test/",
            "tests/",
            "docs/",
            "pkg/",
            "cmd/",
            "internal/",
            ".claude/agents/",
            ".claude/commands/",
            ".claude/hooks/",
            ".claude/references/",
            ".claude/skills/",
            "scripts/",
        ]
    )

    # Context pruner settings
    pruner_max_lines: int = 100
    pruner_max_age_hours: int = 24

    # Thrashing detection
    thrashing_window: int = 3
    same_file_repeat_threshold: int = 3
    effectiveness_threshold: float = 0.5

    # Delivery settings
    delivery_assistant: str = "claude"
    delivery_hooks: bool = True
    delivery_mcp: str = "essential"

    # Language preference for agent responses
    language: str = ""


def load_map_config(project_path: Path) -> MapConfig:
    """Load MAP config from .map/config.yaml with fallback to defaults.

    Resolution order:
    1. .map/config.yaml (if exists)
    2. Default values from MapConfig dataclass

    Returns MapConfig with all defaults filled in.

    Args:
        project_path: Root path of the project.

    Returns:
        MapConfig with all fields populated (defaults + overrides from file).
    """
    project_path = Path(project_path)
    config_file = project_path / ".map" / "config.yaml"

    # If config file doesn't exist, return defaults
    if not config_file.exists():
        return MapConfig()

    # If yaml is not available, warn and return defaults
    if yaml is None:
        logger.warning(
            "PyYAML not installed; cannot load %s. Using default config.",
            config_file,
        )
        return MapConfig()

    try:
        with open(config_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        # If file is empty or only comments, return defaults
        if data is None:
            return MapConfig()

        if not isinstance(data, dict):
            logger.warning(
                "Invalid config format in %s: expected dict, got %s. Using defaults.",
                config_file,
                type(data).__name__,
            )
            return MapConfig()

        # Create defaults dict from MapConfig defaults
        config_dict = {}

        # Map YAML keys to MapConfig fields, filtering out unrecognized keys
        recognized_fields = {f.name for f in MapConfig.__dataclass_fields__.values()}
        for key, value in data.items():
            if key in recognized_fields:
                config_dict[key] = value
            else:
                logger.debug("Unknown config key in %s: %s (ignored)", config_file, key)

        # Create config with overrides; missing fields use dataclass defaults
        return MapConfig(**config_dict)

    except yaml.YAMLError as e:
        logger.warning(
            "Malformed YAML in %s: %s. Using default config.",
            config_file,
            e,
        )
        return MapConfig()
    except Exception as e:
        logger.warning(
            "Error reading %s: %s. Using default config.",
            config_file,
            e,
        )
        return MapConfig()


def generate_default_config(include_comments: bool = True) -> str:
    """Generate a default config.yaml content string with comments.

    Args:
        include_comments: If True, include commented-out examples and descriptions.

    Returns:
        YAML string suitable for writing to .map/config.yaml.
    """
    if not include_comments:
        # Minimal config without comments
        return "# MAP Framework Project Configuration\nprofile: full\n"

    return """\
# MAP Framework Project Configuration
# See: https://github.com/azalio/map-framework/docs/USAGE.md

# Workflow profile: "core" (plan/efficient/check), "full" (all), or "custom"
profile: full

# Project context injected into all agent prompts
# context: |
#   Python CLI project.
#   Prefer deterministic shell commands.

# Per-phase rules (injected only into matching phase prompts)
# rules:
#   research:
#     - Check for existing patterns before proposing new abstractions
#   monitor:
#     - Verify template sync between .claude/ and src/mapify_cli/templates/

# Verification commands (run by /map-check and per-wave guards)
# verification_checks:
#   - make check
#   - pytest tests/ -v

# Policy thresholds
# research_threshold_existing_files: 3
# final_verify_subtask_threshold: 5
# actor_monitor_max_retries: 5
# stuck_recovery_at: 3
# guard_rework_max: 2
# confidence_threshold: 0.7

# Safety: additional safe path prefixes for edits
# safe_path_prefixes:
#   - src/
#   - lib/
#   - test/
#   - tests/

# Context pruner
# pruner_max_lines: 100
# pruner_max_age_hours: 24

# Thrashing detection
# thrashing_window: 3
# same_file_repeat_threshold: 3
# effectiveness_threshold: 0.5

# Delivery settings
# delivery_assistant: claude
# delivery_hooks: true
# delivery_mcp: essential

# Language for agent responses (e.g., "ru", "en", "de")
# language: ""
"""


def write_default_config(project_path: Path) -> Path:
    """Write default config.yaml to .map/config.yaml.

    Does NOT overwrite existing config.

    Args:
        project_path: Root path of the project.

    Returns:
        Path to created or existing config file.

    Raises:
        RuntimeError: If .map directory cannot be created.
    """
    project_path = Path(project_path)
    map_dir = project_path / ".map"
    config_file = map_dir / "config.yaml"

    # If config already exists, return its path
    if config_file.exists():
        return config_file

    # Create .map directory if needed
    try:
        map_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        raise RuntimeError(f"Failed to create .map directory: {e}") from e

    # Write default config
    content = generate_default_config(include_comments=True)
    try:
        with open(config_file, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        raise RuntimeError(f"Failed to write config file: {e}") from e

    return config_file
