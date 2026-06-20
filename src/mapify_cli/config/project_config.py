"""Project configuration for MAP Framework."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from mapify_cli.token_budget import VALID_POLICIES

try:
    import yaml
except ImportError:
    yaml = None

logger = logging.getLogger(__name__)

VALID_MINIMALITY = frozenset({"off", "lite", "full", "ultra"})
VALID_PROMPT_LAYERING = frozenset({"docs_first", "stable_first"})


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

    # Minimality doctrine intensity. Phase 3 (#183) flipped the global default
    # off -> lite after the promotion gate (`mapify minimality-report`) reached
    # `candidate` and the manual review gate passed: projects with no config key
    # now default to `lite` (advisory complexity-lens; no behavior/verdict gating).
    minimality: str = "lite"

    # Agent-prompt layering for repeated same-workflow dispatches (#231).
    # "docs_first"   (default) = variable <documents> first, stable contract
    #                last — best for attention, hostile to prefix caching.
    # "stable_first" = stable contract first, variable <documents> last — the
    #                stable prefix is byte-identical across same-role dispatches,
    #                enabling automatic prefix-cache hits. The attention-vs-cache
    #                tradeoff must be decided with measured data before the
    #                default flips; see docs/ARCHITECTURE.md.
    prompt_layering: str = "docs_first"

    # Context compression policy (see docs/context-compression-plan.md)
    # "never"      = never inject /compact nudge (default — user opts in by
    #                setting policy to auto/aggressive in .map/config.yaml or
    #                via `mapify init --compression auto`)
    # "auto"       = nudge when used >= compression_threshold_tokens
    # "aggressive" = nudge at 0.4 * threshold (cost-leaning)
    #
    # Default flipped from "auto" to "never" by user request: the unsolicited
    # "run /compact" injection mid-workflow interrupted long Actor runs on
    # 50+ subtask plans without operator consent. Users who want the nudge
    # now explicitly opt in.
    compression_policy: str = "never"
    # Token threshold above which the meter injects a /compact instruction.
    # Default = 120_000 (~60% of Sonnet-200k window, below the Chroma
    # context-rot zone). Override to ~250_000 for Opus/Sonnet 1M projects.
    compression_threshold_tokens: int = 120_000
    # Free-form focus text appended to the auto-generated /compact command.
    # Empty string = use the built-in MAP-aware default.
    compression_focus: str = ""

    # Stack Overflow for Agents (SOFA) integration (opt-in, off by default).
    # Enable via `mapify init --sofa` or by setting `sofa.enabled: true` in
    # .map/config.yaml. When enabled, the map-so-search skill is available.
    sofa_enabled: bool = False


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

        # Translate dotted YAML key to snake_case dataclass field before the
        # mapping loop. "sofa.enabled" is the cross-component contract written
        # by apply_sofa_overrides (consumed by ST-004's stdlib-only reader);
        # the dataclass field is "sofa_enabled". Without this alias the toggle
        # is a silent dead field — load_map_config would log "unknown key" and
        # return sofa_enabled=False even when the config says sofa.enabled=true.
        if isinstance(data, dict) and "sofa.enabled" in data and "sofa_enabled" not in data:
            data["sofa_enabled"] = data.pop("sofa.enabled")

        # YAML 1.1 parses bare ``off``/``on`` as booleans, so ``minimality: off``
        # — the documented opt-out from the lite default (#183) — arrives as bool
        # ``False``. Coerce it back to the string level before the type-check loop;
        # otherwise the str field rejects the bool and silently falls back to the
        # lite default, breaking opt-out. ``False`` -> ``"off"`` (valid opt-out);
        # ``True`` -> ``"on"`` (not a real level -> rejected -> lite fallback).
        if isinstance(data, dict) and isinstance(data.get("minimality"), bool):
            data["minimality"] = "off" if data["minimality"] is False else "on"

        # Map YAML keys to MapConfig fields, filtering out unrecognized keys
        # and validating types against dataclass field annotations
        defaults = MapConfig()
        recognized_fields = {f.name: f for f in MapConfig.__dataclass_fields__.values()}
        for key, value in data.items():
            if key not in recognized_fields:
                logger.debug("Unknown config key in %s: %s (ignored)", config_file, key)
                continue
            # Validate type: check that YAML value matches expected type
            expected_type = type(getattr(defaults, key))
            if not isinstance(value, expected_type):
                logger.warning(
                    "Config key '%s' expects %s, got %s (%r). Using default.",
                    key,
                    expected_type.__name__,
                    type(value).__name__,
                    value,
                )
                continue
            config_dict[key] = value

        # Create config with overrides; missing fields use dataclass defaults
        cfg = MapConfig(**config_dict)

        # Post-load validation for enum-like fields. We do not raise — a bad
        # value falls back to the default so a typo does not break the user's
        # workflow. The canonical policy set lives in ``token_budget`` so
        # config validation, CLI validation, and budget logic cannot drift.
        if cfg.compression_policy not in VALID_POLICIES:
            logger.warning(
                "Invalid compression_policy %r in %s (expected one of %s). "
                "Using default 'never'.",
                cfg.compression_policy,
                config_file,
                ", ".join(VALID_POLICIES),
            )
            cfg.compression_policy = "never"
        if cfg.compression_threshold_tokens <= 0:
            logger.warning(
                "compression_threshold_tokens must be > 0 in %s "
                "(got %d). Using default 120000.",
                config_file,
                cfg.compression_threshold_tokens,
            )
            cfg.compression_threshold_tokens = 120_000

        if cfg.minimality not in VALID_MINIMALITY:
            logger.warning(
                "Invalid minimality %r in %s (expected one of %s). "
                "Using default 'lite'.",
                cfg.minimality,
                config_file,
                ", ".join(sorted(VALID_MINIMALITY)),
            )
            cfg.minimality = "lite"

        if cfg.prompt_layering not in VALID_PROMPT_LAYERING:
            logger.warning(
                "Invalid prompt_layering %r in %s (expected one of %s). "
                "Using default 'docs_first'.",
                cfg.prompt_layering,
                config_file,
                ", ".join(sorted(VALID_PROMPT_LAYERING)),
            )
            cfg.prompt_layering = "docs_first"

        return cfg

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
        return "# MAP Framework Project Configuration\nprofile: full\nminimality: lite\n"

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

# Minimality doctrine for new workflows. Existing repos with no key keep the
# historical default (`off`); freshly generated configs opt into conservative
# `lite`: build what was asked, prefer the fewest moving parts, and surface
# lazier alternatives without silently dropping required work.
# Allowed: off, lite, full, ultra
minimality: lite

# Agent-prompt layering for repeated same-workflow dispatches (#231).
# "docs_first" (default) orders the variable <documents> first and the stable
# task/instructions/expected_output contract last — best for model attention.
# "stable_first" puts the stable contract first so its byte-identical prefix can
# trigger automatic prefix-cache hits across same-role dispatches. The
# attention-vs-cache tradeoff is unproven; measure before flipping the default
# (see docs/ARCHITECTURE.md). Allowed: docs_first, stable_first
# prompt_layering: docs_first

# Context compression policy. Default is "never" — the /compact nudge is
# opt-in. Uncomment and switch to "auto" or "aggressive" if you want the
# meter to interrupt long workflows and ask Claude to compact.
#   never      = never inject a /compact nudge (default — opt-in everywhere)
#   auto       = nudge when last assistant turn input >= threshold
#   aggressive = nudge at 0.4 x threshold (best for cost)
# compression_policy: never

# Token threshold for the auto/aggressive policies.
# 120_000 ~= 60% of a 200k Sonnet window; raise to ~250_000 for Opus 1M.
# Tip for 50+ subtask plans: a single subtask cycle commonly burns 10-15k
# tokens, so 120_000 forces ~10 mid-flight compacts across a 51-subtask
# plan. If you want the nudge active for long plans, raise threshold to
# 250_000+ so it fires once or twice, not after every few subtasks.
# compression_threshold_tokens: 120000

# Free-form focus text appended to the generated /compact command.
# Leave empty to use the built-in MAP-aware default
# ("MAP step state, last 2 monitor verdicts, pending subtasks ...").
# compression_focus: ""

# Stack Overflow for Agents (SOFA) integration — opt-in, off by default.
# Enable via `mapify init --sofa` or uncomment the line below.
# sofa.enabled: false
"""


def apply_compression_overrides(
    config_path: Path,
    policy: str | None,
    threshold: int | None,
) -> None:
    """Write user-supplied compression flags into an existing .map/config.yaml.

    Called by ``mapify init`` when the user passes ``--compression`` /
    ``--compression-threshold``. Replaces the commented placeholder lines so
    the values become active without duplicating keys.

    Idempotent: if the file already has uncommented entries for these keys,
    they are replaced rather than appended.

    Each parameter is independently optional. ``None`` means "leave that key
    untouched" — so re-running ``mapify init`` without flags does not rewrite
    a key the user has already customised. Callers should skip this function
    entirely when both arguments are ``None``.

    Args:
        config_path: path to the .map/config.yaml that ``write_default_config``
            just produced.
        policy: validated policy string, or ``None`` to leave it unchanged.
        threshold: validated positive integer, or ``None`` to leave it
            unchanged.
    """
    if not config_path.is_file():
        return
    if policy is None and threshold is None:
        return

    text = config_path.read_text(encoding="utf-8")

    def _set(key: str, value: str, body: str) -> str:
        # Match either an active entry ('key: ...') at the start of a line, or a
        # commented placeholder ('# key: ...'). DOTALL not needed — anchored
        # to line start via the leading newline.
        import re

        active_re = re.compile(rf"(?m)^{re.escape(key)}\s*:.*$")
        commented_re = re.compile(rf"(?m)^#\s*{re.escape(key)}\s*:.*$")
        new_line = f"{key}: {value}"
        if active_re.search(body):
            return active_re.sub(new_line, body, count=1)
        if commented_re.search(body):
            return commented_re.sub(new_line, body, count=1)
        # No placeholder found — append at end with a leading newline if the
        # file does not already end with one.
        sep = "" if body.endswith("\n") else "\n"
        return f"{body}{sep}{new_line}\n"

    if policy is not None:
        text = _set("compression_policy", policy, text)
    if threshold is not None:
        text = _set("compression_threshold_tokens", str(int(threshold)), text)
    config_path.write_text(text, encoding="utf-8")


def apply_sofa_overrides(config_path: Path) -> None:
    """Write sofa.enabled=true into an existing .map/config.yaml.

    Called by ``mapify init`` when the user passes ``--sofa``. Replaces the
    commented placeholder line so the value becomes active without duplicating
    keys.

    Idempotent: if the file already has an active ``sofa.enabled`` entry, it is
    replaced rather than appended. Callers should skip this function when
    ``sofa`` is ``False``.

    Args:
        config_path: path to the .map/config.yaml that ``write_default_config``
            just produced.
    """
    if not config_path.is_file():
        return

    text = config_path.read_text(encoding="utf-8")

    def _set(key: str, value: str, body: str) -> str:
        import re

        active_re = re.compile(rf"(?m)^{re.escape(key)}\s*:.*$")
        commented_re = re.compile(rf"(?m)^#\s*{re.escape(key)}\s*:.*$")
        new_line = f"{key}: {value}"
        if active_re.search(body):
            return active_re.sub(new_line, body, count=1)
        if commented_re.search(body):
            return commented_re.sub(new_line, body, count=1)
        sep = "" if body.endswith("\n") else "\n"
        return f"{body}{sep}{new_line}\n"

    text = _set("sofa.enabled", "true", text)
    config_path.write_text(text, encoding="utf-8")


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
