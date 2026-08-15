"""Project configuration for MAP Framework."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from mapify_cli.token_budget import VALID_POLICIES

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]  # optional dependency

logger = logging.getLogger(__name__)

VALID_MINIMALITY = frozenset({"off", "lite", "full", "ultra"})
VALID_PROMPT_LAYERING = frozenset({"docs_first", "stable_first"})
VALID_WORKTREE_ISOLATION = frozenset({"off", "auto", "required"})
VALID_WAVE_MODE = frozenset({"off", "auto", "on"})
VALID_AGENT_MEMORY_LEVELS = frozenset({"off", "local", "project"})

# Cross-AI peer review (#288): external AI CLI runtimes map-review can dispatch
# to. Keep in sync with CROSS_AI_RUNTIMES in the rendered step runner
# (map_step_runner.py) — the runner owns the per-runtime invocation adapters;
# this set only gates the config value so a typo falls back to the default.
VALID_CROSS_AI_RUNTIMES = frozenset({"claude", "codex", "gemini", "opencode"})


@dataclass
class MapConfig:
    """MAP Framework project configuration."""

    # Workflow profile: "core", "full", or "custom"
    profile: str = "full"

    # Automatically apply stable MAP Framework updates to this project.
    updates_auto: bool = True

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
    #                last — optimized for recency / "lost-in-the-middle".
    # "stable_first" = stable contract first, variable <documents> last — a
    #                byte-identical prefix across same-role dispatches. Resolved
    #                cache-neutral at the Claude Code Task layer (the harness owns
    #                cache_control and the seam is mid-block), but NOT a behavior
    #                no-op: it changes token order / attention. Kept opt-in; never
    #                remapped to docs_first. See docs/ARCHITECTURE.md (#231).
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

    # Role-local persistent memory for learning agents (#379). Enables the
    # Claude Code `memory:` frontmatter on the reflector agent so it can retain
    # lessons across sessions. Enum values:
    #   "off"     — no memory field added (default; behaviour unchanged)
    #   "local"   — user-local memory: .claude/agent-memory-local/ (not committed)
    #   "project" — project-scoped memory: .claude/agent-memory/ (committed)
    # Enable via `mapify init --agent-memory local|project` or set
    # `claude_agents.persistent_memory: local|project` in .map/config.yaml.
    # Dotted YAML key: `claude_agents.persistent_memory` (aliased in load_map_config).
    claude_agents_persistent_memory: str = "off"

    # Strip MAP-internal workflow IDs (ST-/AC-/VC-/INV-/HC-) from run-changed
    # code at workflow completion (Stop hook `scrub-internal-ids.py`). On by
    # default; set `scrub_internal_ids: false` in .map/config.yaml to opt out
    # and keep the IDs the framework wrote into comments/strings/test names.
    scrub_internal_ids: bool = True

    # Cross-AI peer review (#288) — opt-in, OFF by default. When enabled AND the
    # operator passes `map-review --cross-ai <runtime>`, the review is dispatched
    # to an INDEPENDENT external AI CLI (codex/gemini/claude/opencode) for a
    # second opinion. This is a DOUBLE-CONSENT gate: the per-run flag is the
    # explicit egress consent (your diff/code is sent to an external vendor), and
    # `review.cross_ai.enabled` is the org-level kill-switch — both must be true.
    # Dotted YAML keys `review.cross_ai.{enabled,runtime,timeout_seconds}` alias
    # to these snake_case fields (see load_map_config).
    review_cross_ai_enabled: bool = False
    # Default external runtime used when `--cross-ai` is passed without an
    # explicit runtime name. Validated against VALID_CROSS_AI_RUNTIMES.
    review_cross_ai_runtime: str = "codex"
    # Per-dispatch timeout (seconds) for the external CLI subprocess. A real
    # review can take minutes; default 180 balances latency against hangs.
    review_cross_ai_timeout_seconds: int = 180

    # Per-subtask git worktree isolation (#284) — opt-in, OFF by default. When
    # enabled, `/map-efficient` runs each subtask's Actor inside a dedicated git
    # worktree (stored OUT of the working tree, under the repo's common git dir),
    # then atomically squash-merges the result into the working branch ONLY after
    # the configured `verification_checks` pass IN the worktree (pre-merge gate).
    # A rejected attempt (Monitor/Evaluator fail) discards the worktree, so the
    # working branch is never touched by a bad attempt. This is a TOP-LEVEL
    # filesystem concern, deliberately NOT nested under review/sofa. Dotted YAML
    # key `worktree.isolation` aliases to this snake_case field (see
    # load_map_config). The step runner owns the lifecycle + safety guards.
    # Enum values:
    #   "off"      — never create worktrees; sequential execution always.
    #   "auto"     — create per-subtask worktrees when a parallel color-group
    #                dispatches; degrade to sequential with a loud warning when git
    #                worktrees are unavailable (non-git repo, shallow clone, etc.).
    #                default ON (Slice 6); disable via MAP_EFFICIENT_SEQUENTIAL_ONLY=1
    #                or set `worktree.isolation: off` in .map/config.yaml.
    #   "required" — hard-fail before parallel dispatch if worktrees are unavailable.
    # Backward compat: YAML boolean `false` migrates to `"off"`, `true` to
    # `"required"` in load_map_config.
    worktree_isolation: str = "auto"
    # Bulk-deletion guard threshold: the per-subtask merge refuses when the
    # worktree branch deletes MORE than this many files vs the base commit
    # (catches `rm -rf` / hallucinated mass deletion before it reaches the
    # working branch). 0 disables the guard. Dotted YAML key
    # `worktree.max_deletions`.
    worktree_max_deletions: int = 50

    # Parallel wave execution mode (#303, Slice 0 scaffolding — no behavior change
    # until Slice 3/5 promote the wave-loop to default). Controls whether
    # `/map-efficient` routes multi-subtask waves through the parallel wave
    # coordinator or the sequential single-subtask walker.
    # Enum values:
    #   "auto" — (default) engage the wave-loop when the color-group has >=2
    #             independent subtasks AND worktree.isolation != "off"; degrade to
    #             sequential otherwise. Slice 0: behaves as sequential everywhere
    #             (the wave-loop promotion and concurrent dispatch land in Slice 3/5).
    #   "off"  — always sequential; the legacy walker; instant rollback escape hatch.
    #   "on"   — always attempt parallel dispatch (reserved for Slice 5/6; same as
    #             "auto" until the concurrent-dispatch step lands).
    # Dotted YAML key `execution.wave_mode` aliases to this field. YAML 1.1 parses
    # bare `off`/`on` as booleans — load_map_config migrates them to strings.
    execution_wave_mode: str = "auto"

    # Maximum number of concurrent Actor workers in a parallel wave dispatch (#303
    # Slice 5b). Range 1–8; out-of-range values are clamped by clamp_max_actors().
    # Non-int / bool values fall back to the default 4 (see clamp_max_actors).
    # Dotted YAML key: `execution.max_actors`.
    # DORMANT in Slice 5a — parsed and validated but no execution path reads it yet.
    max_actors: int = 4

    # When True, a single worker that crashes with a transient error in a parallel
    # wave will be retried once before the wave is aborted. Pairs with max_actors
    # in Slice 5b concurrent dispatch. Dotted YAML key: `execution.retry_degraded_once`.
    # DORMANT in Slice 5a — parsed and validated but no execution path reads it yet.
    retry_degraded_once: bool = False

    # Enable same-turn concurrent Actor dispatch in a parallel wave (#303 Slice 5b).
    # default ON (Slice 6); disable via MAP_EFFICIENT_SEQUENTIAL_ONLY=1 (global
    # kill-switch) or set `execution.concurrent_dispatch: false` in .map/config.yaml.
    # Dotted YAML alias: `execution.concurrent_dispatch`.
    # YAML 1.1 bare off/on arrive as Python bool, which matches this field type —
    # no coercion needed (unlike the string enum fields).
    concurrent_dispatch: bool = True

    # Bounded retry cap for whole-wave rollback/restart in Slice 5b (#303).
    # Range 1–10; values outside the range are clamped by clamp_max_wave_retries().
    # Non-int / bool values fall back to the default 3.
    # Dotted YAML alias: `execution.max_wave_retries`.
    # DORMANT in 5b.0 — consumed by ST-006's rollback path; no execution path reads
    # it yet.
    max_wave_retries: int = 3

    # Enforce TDD discipline project-wide (#285).  When true, /map-efficient routes
    # Actor-phase dispatches through the TEST_WRITER → TEST_FAIL_GATE → ACTOR
    # sequence automatically, equivalent to always running /map-tdd.  Code written
    # before a failing test is treated as a violation: Monitor emits a TDD_VIOLATION
    # finding.  spec-compliance and code-quality reviewer subagents run after each
    # subtask.  Default OFF so existing workflows are unaffected.
    # Dotted YAML key: `tdd.enforce`  (aliased in load_map_config).
    tdd_enforce: bool = False

    # Scale-adaptive intelligence (#287) — automatic scope→workflow-depth mapping.
    # When scale_auto is True (default), the MAP workflow entry point may classify
    # the requested change into one of four brackets and recommend the appropriate
    # workflow depth. When False, auto-detection is skipped and the user must
    # choose the workflow explicitly.
    #
    # Classification brackets:
    #   TRIVIAL  — < trivial thresholds → map-fast (skip Predictor, Reflector)
    #   SMALL    — < small thresholds   → map-plan-light (spec only, no research)
    #   MEDIUM   — < medium thresholds  → map-efficient (full MAP loop)
    #   LARGE    — >= medium thresholds → map-efficient + map-tdd + adversarial review
    #
    # Dotted YAML aliases (see load_map_config):
    #   scale.auto
    #   scale.thresholds.trivial.max_files / scale.thresholds.trivial.max_lines
    #   scale.thresholds.small.max_files  / scale.thresholds.small.max_lines
    #   scale.thresholds.medium.max_files / scale.thresholds.medium.max_lines
    scale_auto: bool = True
    scale_trivial_max_files: int = 3
    scale_trivial_max_lines: int = 50
    scale_small_max_files: int = 10
    scale_small_max_lines: int = 200
    scale_medium_max_files: int = 30
    scale_medium_max_lines: int = 1000


def clamp_max_actors(n: object) -> int:
    """Clamp max_actors to the valid range [1, 8], or return the default 4.

    Non-int values (including bool, str, None) return the default 4.
    int values are clamped: below 1 → 1, above 8 → 8.

    Note: bool is explicitly excluded (isinstance(True, int) is True in Python)
    because a YAML boolean arriving here is a misconfiguration, not an int.
    The floor is 1, NOT the default 4 — a valid-but-low int (e.g. 0) is clamped
    to 1 (minimum legal value), while a non-int/bool/None falls back to 4.
    """
    if isinstance(n, bool) or not isinstance(n, int):
        return 4
    return max(1, min(8, n))


def clamp_max_wave_retries(n: object) -> int:
    """Clamp max_wave_retries to the valid range [1, 10], or return the default 3.

    Non-int values (including bool, str, None) return the default 3.
    int values are clamped: below 1 → 1, above 10 → 10.

    Note: bool is explicitly excluded (isinstance(True, int) is True in Python)
    because a YAML boolean arriving here is a misconfiguration, not an int.
    The floor is 1 — a valid-but-low int (e.g. 0) is clamped to 1 (minimum
    legal value), while a non-int/bool/None falls back to the default 3.
    """
    if isinstance(n, bool) or not isinstance(n, int):
        return 3
    return max(1, min(10, n))


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

        # Cross-AI peer review (#288): dotted hierarchical YAML keys
        # `review.cross_ai.*` alias to flat snake_case dataclass fields. Without
        # this the toggles are silent dead fields (load logs "unknown key" and
        # the defaults stand even when the YAML sets them).
        for dotted, field_name in (
            ("updates.auto", "updates_auto"),
            ("review.cross_ai.enabled", "review_cross_ai_enabled"),
            ("review.cross_ai.runtime", "review_cross_ai_runtime"),
            ("review.cross_ai.timeout_seconds", "review_cross_ai_timeout_seconds"),
            ("worktree.isolation", "worktree_isolation"),
            ("worktree.max_deletions", "worktree_max_deletions"),
            ("execution.wave_mode", "execution_wave_mode"),
            ("execution.max_actors", "max_actors"),
            ("execution.retry_degraded_once", "retry_degraded_once"),
            ("execution.concurrent_dispatch", "concurrent_dispatch"),
            ("execution.max_wave_retries", "max_wave_retries"),
            ("tdd.enforce", "tdd_enforce"),
            ("scale.auto", "scale_auto"),
            ("scale.thresholds.trivial.max_files", "scale_trivial_max_files"),
            ("scale.thresholds.trivial.max_lines", "scale_trivial_max_lines"),
            ("scale.thresholds.small.max_files", "scale_small_max_files"),
            ("scale.thresholds.small.max_lines", "scale_small_max_lines"),
            ("scale.thresholds.medium.max_files", "scale_medium_max_files"),
            ("scale.thresholds.medium.max_lines", "scale_medium_max_lines"),
            ("claude_agents.persistent_memory", "claude_agents_persistent_memory"),
        ):
            if dotted in data and field_name not in data:
                data[field_name] = data.pop(dotted)

        # Backward compat: worktree_isolation was a bool field; YAML `false`/`true`
        # (and YAML 1.1 `off`/`on`) arrive as Python booleans. Migrate to the new
        # enum string before the type-check loop (which expects str).
        if isinstance(data.get("worktree_isolation"), bool):
            data["worktree_isolation"] = (
                "required" if data["worktree_isolation"] else "off"
            )

        # YAML 1.1 parses bare `off`/`on` as booleans for execution.wave_mode too.
        # Coerce back to strings: False->"off", True->"on".
        if isinstance(data.get("execution_wave_mode"), bool):
            data["execution_wave_mode"] = "on" if data["execution_wave_mode"] else "off"

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

        if cfg.review_cross_ai_runtime not in VALID_CROSS_AI_RUNTIMES:
            logger.warning(
                "Invalid review_cross_ai_runtime %r in %s (expected one of %s). "
                "Using default 'codex'.",
                cfg.review_cross_ai_runtime,
                config_file,
                ", ".join(sorted(VALID_CROSS_AI_RUNTIMES)),
            )
            cfg.review_cross_ai_runtime = "codex"

        if cfg.review_cross_ai_timeout_seconds <= 0:
            logger.warning(
                "review_cross_ai_timeout_seconds must be > 0 in %s "
                "(got %d). Using default 180.",
                config_file,
                cfg.review_cross_ai_timeout_seconds,
            )
            cfg.review_cross_ai_timeout_seconds = 180

        if cfg.worktree_max_deletions < 0:
            logger.warning(
                "worktree_max_deletions must be >= 0 in %s "
                "(got %d). Using default 50.",
                config_file,
                cfg.worktree_max_deletions,
            )
            cfg.worktree_max_deletions = 50

        if cfg.worktree_isolation not in VALID_WORKTREE_ISOLATION:
            logger.warning(
                "Invalid worktree_isolation %r in %s (expected one of %s). "
                "Using default 'off'.",
                cfg.worktree_isolation,
                config_file,
                ", ".join(sorted(VALID_WORKTREE_ISOLATION)),
            )
            cfg.worktree_isolation = "off"

        if cfg.execution_wave_mode not in VALID_WAVE_MODE:
            logger.warning(
                "Invalid execution_wave_mode %r in %s (expected one of %s). "
                "Using default 'auto'.",
                cfg.execution_wave_mode,
                config_file,
                ", ".join(sorted(VALID_WAVE_MODE)),
            )
            cfg.execution_wave_mode = "auto"

        if cfg.claude_agents_persistent_memory not in VALID_AGENT_MEMORY_LEVELS:
            logger.warning(
                "Invalid claude_agents_persistent_memory %r in %s (expected one of %s). "
                "Using default 'off'.",
                cfg.claude_agents_persistent_memory,
                config_file,
                ", ".join(sorted(VALID_AGENT_MEMORY_LEVELS)),
            )
            cfg.claude_agents_persistent_memory = "off"

        # Clamp max_actors to [1, 8]; non-int/bool → default 4.
        # retry_degraded_once and concurrent_dispatch are plain bools handled by
        # the generic type-check loop.
        cfg.max_actors = clamp_max_actors(cfg.max_actors)
        # Clamp max_wave_retries to [1, 10]; non-int/bool → default 3.
        cfg.max_wave_retries = clamp_max_wave_retries(cfg.max_wave_retries)

        # Scale threshold fields must be >= 1; a value <= 0 makes one or more
        # scope brackets unreachable (e.g. estimated_files <= -1 is always False).
        _scale_defaults: dict[str, int] = {
            "scale_trivial_max_files": 3,
            "scale_trivial_max_lines": 50,
            "scale_small_max_files": 10,
            "scale_small_max_lines": 200,
            "scale_medium_max_files": 30,
            "scale_medium_max_lines": 1000,
        }
        for _sf, _default in _scale_defaults.items():
            _val = getattr(cfg, _sf)
            if _val < 1:
                logger.warning(
                    "%s must be >= 1 in %s (got %d). Using default %d.",
                    _sf,
                    config_file,
                    _val,
                    _default,
                )
                setattr(cfg, _sf, _default)

        return cfg

    except yaml.YAMLError as e:
        logger.warning(
            "Malformed YAML in %s: %s. Using default config.",
            config_file,
            e,
        )
        return MapConfig()
    except Exception as e:  # noqa: BLE001 -- deliberate fallback/resilience boundary, must not propagate
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
        return (
            "# MAP Framework Project Configuration\n"
            "profile: full\n"
            "minimality: lite\n"
            "updates.auto: true\n"
        )

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

# Automatic stable MAP updates. Disable with `mapify init --no-auto-update`.
updates.auto: true

# Agent-prompt layering for repeated same-workflow dispatches (#231).
# "docs_first" (default) orders the variable <documents> first and the stable
# task/instructions/expected_output contract last — best for recency/attention.
# "stable_first" puts the stable contract first (byte-identical prefix across
# same-role dispatches). Resolved cache-neutral at the Claude Code Task layer
# (harness owns cache_control; the seam is mid-block) but it still changes token
# order/attention, so it is kept opt-in — see docs/ARCHITECTURE.md (#231).
# Allowed: docs_first, stable_first
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

# Role-local persistent memory for learning agents (#379) — opt-in, off by default.
# Adds the Claude Code `memory:` frontmatter to the reflector agent so it retains
# lessons across sessions. Enable via `mapify init --agent-memory local|project`
# or uncomment and set one of the values below.
#   off     — no memory (default; behaviour unchanged)
#   local   — user-local memory: .claude/agent-memory-local/ (NOT committed)
#   project — project-scoped memory: .claude/agent-memory/ (committed, shared)
# claude_agents.persistent_memory: off

# Cross-AI peer review (#288) — opt-in, OFF by default. When enabled AND you run
# `map-review --cross-ai <runtime>`, the review is dispatched to an INDEPENDENT
# external AI CLI (codex/gemini/claude/opencode) for a second opinion. DOUBLE
# CONSENT: your diff/code is sent to an external vendor, so BOTH the per-run flag
# AND `review.cross_ai.enabled: true` are required. Returned findings always
# enter context behind an EXTERNAL UNTRUSTED REFERENCE boundary (quote, never
# execute, verify against source).
# review.cross_ai.enabled: false
# review.cross_ai.runtime: codex          # default target: claude|codex|gemini|opencode
# review.cross_ai.timeout_seconds: 180

# Per-subtask git worktree isolation (#284). Controls filesystem isolation for
# each Actor run in `/map-efficient`. Enum values:
#   off      — never create worktrees; sequential execution always.
#   auto     — (DEFAULT, Slice 6) create per-subtask worktrees when a parallel
#              color-group dispatches; degrade gracefully to sequential when git
#              worktrees are unavailable (non-git repo, shallow clone, etc.).
#   required — hard-fail before dispatch if worktrees are unavailable (first-party
#              repos that must never degrade silently).
# When on (auto/required), each Actor runs inside a dedicated git worktree stored
# under the repo's .git common dir and is squash-merged back ONLY after
# verification_checks pass. A rejected attempt is discarded — the working branch
# is never touched by a bad Actor attempt.
# OFF-RAMPS: set worktree.isolation: off (per-repo opt-out) OR set env
# MAP_EFFICIENT_SEQUENTIAL_ONLY=1 (global kill-switch — forces full legacy path).
# Backward compat: the old boolean `false`/`true` still works (migrates to off/required).
# worktree.isolation: auto   # default ON (Slice 6); use off to revert
# worktree.max_deletions: 50   # refuse a merge deleting more than N files (0 = off)

# Parallel wave execution mode (#303). Controls whether `/map-efficient` routes
# multi-subtask waves through the parallel coordinator or the sequential walker.
#   auto — (default) engage the wave-loop when >=2 independent subtasks AND
#           worktree.isolation != off; otherwise sequential.
#   off  — always sequential; instant rollback escape hatch.
#   on   — always attempt parallel (same as auto in Slice 6).
# execution.wave_mode: auto

# Concurrent Actor limit for parallel wave dispatch (#303 Slice 5b).
# Valid range 1–8; values outside the range are clamped (0→1, 9→8).
# Non-int / bool values fall back to the default 4.
# execution.max_actors: 4

# Retry a crashed worker once before aborting the wave (Slice 5b).
# execution.retry_degraded_once: false

# Enable same-turn concurrent Actor dispatch (#303 Slice 6). DEFAULT True.
# YAML 1.1 bare off/on arrive as bool.
# OFF-RAMPS: set false here (per-repo opt-out) OR MAP_EFFICIENT_SEQUENTIAL_ONLY=1 (global).
# execution.concurrent_dispatch: true   # default ON (Slice 6); use false to revert

# Bounded retry cap for whole-wave rollback/restart (#303 Slice 5b).
# Valid range 1–10; values outside the range are clamped (0→1, 99→10).
# Non-int / bool values fall back to the default 3.
# execution.max_wave_retries: 3

# Global kill-switch (Slice 6 off-ramp). Forces the FULL legacy sequential path
# regardless of any config — no wave-loop, no worktrees, no concurrent dispatch.
# Byte-identical to pre-5a legacy behavior. Set as an environment variable:
#   export MAP_EFFICIENT_SEQUENTIAL_ONLY=1   # or true/yes/y/on
# Unset (or empty / "0" / "false") to restore default parallel behavior.

# Strip MAP-internal workflow IDs (ST-/AC-/VC-/INV-/HC-) from the code a run
# changed, at workflow completion (Stop hook). On by default; uncomment and set
# to false to keep the IDs the framework wrote into comments/strings/test names.
# scrub_internal_ids: true

# TDD enforcement (#285). When true, /map-efficient automatically routes each
# subtask's Actor phase through the TEST_WRITER → TEST_FAIL_GATE → ACTOR sequence
# (equivalent to always running /map-tdd). Code written before a failing test is
# treated as a TDD_VIOLATION by Monitor; spec-compliance and code-quality reviewer
# subagents run after each subtask. Default OFF — existing workflows are unaffected.
# tdd.enforce: false

# Scale-adaptive intelligence (#287). When scale.auto is true (default), MAP may
# classify an incoming change request and recommend the appropriate workflow depth:
#   TRIVIAL  (< trivial thresholds) → map-fast
#   SMALL    (< small thresholds)   → map-plan-light (spec only, no research)
#   MEDIUM   (< medium thresholds)  → map-efficient (full MAP loop)
#   LARGE    (>= medium thresholds) → map-efficient + map-tdd + adversarial review
# Set scale.auto: false to disable auto-detection and always choose manually.
# scale.auto: true
# scale.thresholds.trivial.max_files: 3
# scale.thresholds.trivial.max_lines: 50
# scale.thresholds.small.max_files: 10
# scale.thresholds.small.max_lines: 200
# scale.thresholds.medium.max_files: 30
# scale.thresholds.medium.max_lines: 1000
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


def apply_auto_update_override(config_path: Path, enabled: bool) -> None:
    """Write the automatic-update setting into an existing config file."""
    if not config_path.is_file():
        return
    import re

    text = config_path.read_text(encoding="utf-8")
    active = re.compile(r"(?m)^updates\.auto\s*:.*$")
    commented = re.compile(r"(?m)^#\s*updates\.auto\s*:.*$")
    line = f"updates.auto: {'true' if enabled else 'false'}"
    if active.search(text):
        text = active.sub(line, text, count=1)
    elif commented.search(text):
        text = commented.sub(line, text, count=1)
    else:
        separator = "" if text.endswith("\n") else "\n"
        text = f"{text}{separator}{line}\n"
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


def apply_agent_memory_overrides(config_path: Path, level: str) -> None:
    """Write claude_agents.persistent_memory=<level> into an existing .map/config.yaml.

    Called by ``mapify init`` when the user passes ``--agent-memory``. Replaces
    the commented placeholder line so the value becomes active without duplicating
    keys. Callers should skip this function when ``level`` is ``"off"``.

    Args:
        config_path: path to the .map/config.yaml produced by ``write_default_config``.
        level: one of "off", "local", "project" (caller is responsible for validation).
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

    text = _set("claude_agents.persistent_memory", level, text)
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
