"""Scope classification for scale-adaptive intelligence (#287).

Classifies a requested change into one of four scale brackets and returns
the recommended MAP workflow depth. The classification is deterministic
given the estimated metrics — no LLM calls, no side effects.

Bracket → recommended workflow mapping:
  TRIVIAL → map-fast            (skip Predictor, Reflector)
  SMALL   → map-plan-light      (spec only, no research phase)
  MEDIUM  → map-efficient       (full MAP loop)
  LARGE   → map-efficient+map-tdd  (full loop + TDD + adversarial review)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ScopeBracket(str, Enum):
    """Scale classification brackets for MAP workflow routing."""

    TRIVIAL = "trivial"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


_BRACKET_WORKFLOW: dict[str, str] = {
    ScopeBracket.TRIVIAL: "map-fast",
    ScopeBracket.SMALL: "map-plan-light",
    ScopeBracket.MEDIUM: "map-efficient",
    ScopeBracket.LARGE: "map-efficient+map-tdd",
}


@dataclass(frozen=True)
class ScopeClassification:
    """Result of classifying the estimated scope of a change."""

    bracket: ScopeBracket
    recommended_workflow: str
    estimated_files: int
    estimated_lines: int
    auto_enabled: bool


def classify_scope(
    estimated_files: int,
    estimated_lines: int,
    *,
    config: object | None = None,
) -> ScopeClassification:
    """Classify an estimated change into a scale bracket.

    Uses the thresholds from ``config`` (a ``MapConfig`` instance) when
    provided; falls back to the ``MapConfig`` defaults otherwise.  Importing
    ``MapConfig`` lazily keeps this module importable without the full
    ``mapify_cli`` package installed.

    Classification rules (both file AND line estimates must be within the
    bracket ceiling — if either exceeds the ceiling the next bracket is used):

      estimated_files <= trivial_max_files AND estimated_lines <= trivial_max_lines
          → TRIVIAL
      estimated_files <= small_max_files  AND estimated_lines <= small_max_lines
          → SMALL
      estimated_files <= medium_max_files AND estimated_lines <= medium_max_lines
          → MEDIUM
      otherwise
          → LARGE

    Args:
        estimated_files: Estimated number of files to change (>= 0).
        estimated_lines: Estimated number of lines to add/modify (>= 0).
        config: A ``MapConfig`` instance with scale thresholds, or ``None``
                to use defaults.

    Returns:
        ``ScopeClassification`` with the bracket, recommended workflow, input
        metrics, and whether auto-detection is enabled in the supplied config.
    """
    if config is None:
        from mapify_cli.config.project_config import MapConfig

        config = MapConfig()

    auto: bool = getattr(config, "scale_auto", True)
    trivial_files: int = getattr(config, "scale_trivial_max_files", 3)
    trivial_lines: int = getattr(config, "scale_trivial_max_lines", 50)
    small_files: int = getattr(config, "scale_small_max_files", 10)
    small_lines: int = getattr(config, "scale_small_max_lines", 200)
    medium_files: int = getattr(config, "scale_medium_max_files", 30)
    medium_lines: int = getattr(config, "scale_medium_max_lines", 1000)

    if estimated_files <= trivial_files and estimated_lines <= trivial_lines:
        bracket = ScopeBracket.TRIVIAL
    elif estimated_files <= small_files and estimated_lines <= small_lines:
        bracket = ScopeBracket.SMALL
    elif estimated_files <= medium_files and estimated_lines <= medium_lines:
        bracket = ScopeBracket.MEDIUM
    else:
        bracket = ScopeBracket.LARGE

    return ScopeClassification(
        bracket=bracket,
        recommended_workflow=_BRACKET_WORKFLOW[bracket],
        estimated_files=estimated_files,
        estimated_lines=estimated_lines,
        auto_enabled=auto,
    )
