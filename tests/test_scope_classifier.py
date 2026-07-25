"""Tests for scale-adaptive intelligence: scope classification (#287).

Covers:
  VC1 — ScopeBracket values and _BRACKET_WORKFLOW mapping completeness
  VC2 — classify_scope with default config thresholds (all four brackets)
  VC3 — classify_scope with custom MapConfig thresholds
  VC4 — scale.* dotted-key aliases in load_map_config
  VC5 — generate_default_config() documents the scale section
  VC6 — scale_auto=False preserved through load_map_config
  VC7 — boundary conditions: at-threshold vs. one-over for each bracket
  VC8 — ScopeClassification fields populated correctly
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mapify_cli.config.project_config import (
    MapConfig,
    generate_default_config,
    load_map_config,
)
from mapify_cli.scope_classifier import (
    _BRACKET_WORKFLOW,
    ScopeBracket,
    classify_scope,
)


def _write_config(tmp_path: Path, body: str) -> None:
    (tmp_path / ".map").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".map" / "config.yaml").write_text(body, encoding="utf-8")


# ---------------------------------------------------------------------------
# VC1 — ScopeBracket enum and workflow mapping completeness
# ---------------------------------------------------------------------------


class TestVc1BracketEnum:
    def test_all_brackets_have_string_values(self):
        assert ScopeBracket.TRIVIAL == "trivial"
        assert ScopeBracket.SMALL == "small"
        assert ScopeBracket.MEDIUM == "medium"
        assert ScopeBracket.LARGE == "large"

    def test_all_brackets_have_recommended_workflow(self):
        for bracket in ScopeBracket:
            assert bracket in _BRACKET_WORKFLOW, f"Missing workflow for {bracket}"

    def test_workflow_values_are_nonempty_strings(self):
        for bracket, wf in _BRACKET_WORKFLOW.items():
            assert isinstance(wf, str) and wf, f"Empty workflow for {bracket}"

    def test_trivial_routes_to_map_fast(self):
        assert _BRACKET_WORKFLOW[ScopeBracket.TRIVIAL] == "map-fast"

    def test_large_routes_to_tdd_workflow(self):
        assert _BRACKET_WORKFLOW[ScopeBracket.LARGE] == "map-efficient+map-tdd"


# ---------------------------------------------------------------------------
# VC2 — classify_scope with default thresholds (all four brackets)
# ---------------------------------------------------------------------------


class TestVc2DefaultThresholds:
    """Default: trivial(3f/50l), small(10f/200l), medium(30f/1000l)."""

    def test_trivial_both_at_ceiling(self):
        result = classify_scope(3, 50)
        assert result.bracket == ScopeBracket.TRIVIAL

    def test_trivial_well_within(self):
        result = classify_scope(1, 10)
        assert result.bracket == ScopeBracket.TRIVIAL

    def test_small_files_exceed_trivial(self):
        result = classify_scope(4, 10)
        assert result.bracket == ScopeBracket.SMALL

    def test_small_lines_exceed_trivial(self):
        result = classify_scope(1, 51)
        assert result.bracket == ScopeBracket.SMALL

    def test_small_both_at_ceiling(self):
        result = classify_scope(10, 200)
        assert result.bracket == ScopeBracket.SMALL

    def test_medium_files_exceed_small(self):
        result = classify_scope(11, 10)
        assert result.bracket == ScopeBracket.MEDIUM

    def test_medium_lines_exceed_small(self):
        result = classify_scope(1, 201)
        assert result.bracket == ScopeBracket.MEDIUM

    def test_medium_both_at_ceiling(self):
        result = classify_scope(30, 1000)
        assert result.bracket == ScopeBracket.MEDIUM

    def test_large_files_exceed_medium(self):
        result = classify_scope(31, 10)
        assert result.bracket == ScopeBracket.LARGE

    def test_large_lines_exceed_medium(self):
        result = classify_scope(1, 1001)
        assert result.bracket == ScopeBracket.LARGE

    def test_large_both_far_exceed(self):
        result = classify_scope(100, 5000)
        assert result.bracket == ScopeBracket.LARGE

    def test_zero_zero_is_trivial(self):
        result = classify_scope(0, 0)
        assert result.bracket == ScopeBracket.TRIVIAL

    def test_recommended_workflow_matches_bracket(self):
        for files, lines, expected_bracket in [
            (1, 10, ScopeBracket.TRIVIAL),
            (5, 100, ScopeBracket.SMALL),
            (15, 500, ScopeBracket.MEDIUM),
            (50, 2000, ScopeBracket.LARGE),
        ]:
            result = classify_scope(files, lines)
            assert result.bracket == expected_bracket
            assert result.recommended_workflow == _BRACKET_WORKFLOW[expected_bracket]


# ---------------------------------------------------------------------------
# VC3 — classify_scope with custom MapConfig thresholds
# ---------------------------------------------------------------------------


class TestVc3CustomThresholds:
    def test_custom_trivial_ceiling_applied(self):
        cfg = MapConfig(scale_trivial_max_files=1, scale_trivial_max_lines=10)
        assert classify_scope(1, 10, config=cfg).bracket == ScopeBracket.TRIVIAL
        assert classify_scope(2, 10, config=cfg).bracket == ScopeBracket.SMALL

    def test_custom_small_ceiling_applied(self):
        cfg = MapConfig(scale_small_max_files=5, scale_small_max_lines=100)
        assert classify_scope(5, 100, config=cfg).bracket == ScopeBracket.SMALL
        assert classify_scope(6, 10, config=cfg).bracket == ScopeBracket.MEDIUM

    def test_custom_medium_ceiling_applied(self):
        cfg = MapConfig(scale_medium_max_files=20, scale_medium_max_lines=500)
        assert classify_scope(20, 500, config=cfg).bracket == ScopeBracket.MEDIUM
        assert classify_scope(21, 10, config=cfg).bracket == ScopeBracket.LARGE

    def test_none_config_uses_defaults(self):
        result_none = classify_scope(1, 10, config=None)
        result_default = classify_scope(1, 10, config=MapConfig())
        assert result_none.bracket == result_default.bracket

    def test_auto_false_in_custom_config(self):
        cfg = MapConfig(scale_auto=False)
        result = classify_scope(1, 10, config=cfg)
        assert result.auto_enabled is False
        assert result.bracket == ScopeBracket.TRIVIAL  # still classifies

    def test_auto_true_default(self):
        result = classify_scope(1, 10)
        assert result.auto_enabled is True


# ---------------------------------------------------------------------------
# VC4 — scale.* dotted-key aliases in load_map_config
# ---------------------------------------------------------------------------


class TestVc4DottedKeyAliases:
    def test_scale_auto_false(self, tmp_path: Path):
        _write_config(tmp_path, "scale.auto: false\n")
        cfg = load_map_config(tmp_path)
        assert cfg.scale_auto is False

    def test_scale_auto_true_explicit(self, tmp_path: Path):
        _write_config(tmp_path, "scale.auto: true\n")
        cfg = load_map_config(tmp_path)
        assert cfg.scale_auto is True

    def test_scale_trivial_max_files(self, tmp_path: Path):
        _write_config(tmp_path, "scale.thresholds.trivial.max_files: 5\n")
        cfg = load_map_config(tmp_path)
        assert cfg.scale_trivial_max_files == 5

    def test_scale_trivial_max_lines(self, tmp_path: Path):
        _write_config(tmp_path, "scale.thresholds.trivial.max_lines: 25\n")
        cfg = load_map_config(tmp_path)
        assert cfg.scale_trivial_max_lines == 25

    def test_scale_small_max_files(self, tmp_path: Path):
        _write_config(tmp_path, "scale.thresholds.small.max_files: 15\n")
        cfg = load_map_config(tmp_path)
        assert cfg.scale_small_max_files == 15

    def test_scale_small_max_lines(self, tmp_path: Path):
        _write_config(tmp_path, "scale.thresholds.small.max_lines: 300\n")
        cfg = load_map_config(tmp_path)
        assert cfg.scale_small_max_lines == 300

    def test_scale_medium_max_files(self, tmp_path: Path):
        _write_config(tmp_path, "scale.thresholds.medium.max_files: 50\n")
        cfg = load_map_config(tmp_path)
        assert cfg.scale_medium_max_files == 50

    def test_scale_medium_max_lines(self, tmp_path: Path):
        _write_config(tmp_path, "scale.thresholds.medium.max_lines: 2000\n")
        cfg = load_map_config(tmp_path)
        assert cfg.scale_medium_max_lines == 2000

    def test_absent_config_uses_all_defaults(self, tmp_path: Path):
        cfg = load_map_config(tmp_path)
        assert cfg.scale_auto is True
        assert cfg.scale_trivial_max_files == 3
        assert cfg.scale_trivial_max_lines == 50
        assert cfg.scale_small_max_files == 10
        assert cfg.scale_small_max_lines == 200
        assert cfg.scale_medium_max_files == 30
        assert cfg.scale_medium_max_lines == 1000

    def test_multiple_scale_keys_in_one_config(self, tmp_path: Path):
        _write_config(
            tmp_path,
            "scale.auto: true\n"
            "scale.thresholds.trivial.max_files: 2\n"
            "scale.thresholds.small.max_files: 8\n",
        )
        cfg = load_map_config(tmp_path)
        assert cfg.scale_auto is True
        assert cfg.scale_trivial_max_files == 2
        assert cfg.scale_small_max_files == 8
        # other fields stay at default
        assert cfg.scale_trivial_max_lines == 50


# ---------------------------------------------------------------------------
# VC5 — generate_default_config documents the scale section
# ---------------------------------------------------------------------------


class TestVc5DefaultConfigDocuments:
    def test_scale_auto_documented(self):
        config = generate_default_config()
        assert "scale.auto" in config

    def test_scale_trivial_thresholds_documented(self):
        config = generate_default_config()
        assert "scale.thresholds.trivial.max_files" in config
        assert "scale.thresholds.trivial.max_lines" in config

    def test_scale_small_thresholds_documented(self):
        config = generate_default_config()
        assert "scale.thresholds.small.max_files" in config
        assert "scale.thresholds.small.max_lines" in config

    def test_scale_medium_thresholds_documented(self):
        config = generate_default_config()
        assert "scale.thresholds.medium.max_files" in config
        assert "scale.thresholds.medium.max_lines" in config

    def test_scale_section_references_issue(self):
        config = generate_default_config()
        assert "#287" in config


# ---------------------------------------------------------------------------
# VC6 — scale_auto preserved through round-trip
# ---------------------------------------------------------------------------


class TestVc6ScaleAutoRoundTrip:
    def test_scale_auto_false_round_trip(self, tmp_path: Path):
        _write_config(tmp_path, "scale.auto: false\n")
        cfg = load_map_config(tmp_path)
        result = classify_scope(1, 10, config=cfg)
        assert result.auto_enabled is False

    def test_scale_auto_true_default_round_trip(self, tmp_path: Path):
        cfg = load_map_config(tmp_path)
        result = classify_scope(1, 10, config=cfg)
        assert result.auto_enabled is True


# ---------------------------------------------------------------------------
# VC7 — boundary conditions: at-threshold vs. one-over for each bracket
# ---------------------------------------------------------------------------


class TestVc7BoundaryConditions:
    """Thresholds are INCLUSIVE upper bounds: at == trivial, at+1 == next."""

    @pytest.mark.parametrize(
        "files, lines, expected",
        [
            # Trivial ceiling (3f / 50l) — both must fit
            (3, 50, ScopeBracket.TRIVIAL),
            (4, 50, ScopeBracket.SMALL),   # one file over
            (3, 51, ScopeBracket.SMALL),   # one line over
            # Small ceiling (10f / 200l)
            (10, 200, ScopeBracket.SMALL),
            (11, 200, ScopeBracket.MEDIUM),
            (10, 201, ScopeBracket.MEDIUM),
            # Medium ceiling (30f / 1000l)
            (30, 1000, ScopeBracket.MEDIUM),
            (31, 1000, ScopeBracket.LARGE),
            (30, 1001, ScopeBracket.LARGE),
        ],
    )
    def test_boundary(self, files: int, lines: int, expected: ScopeBracket):
        assert classify_scope(files, lines).bracket == expected


# ---------------------------------------------------------------------------
# VC8 — ScopeClassification fields populated correctly
# ---------------------------------------------------------------------------


class TestVc8ClassificationFields:
    def test_fields_match_inputs(self):
        result = classify_scope(7, 120)
        assert result.estimated_files == 7
        assert result.estimated_lines == 120

    def test_recommended_workflow_is_string(self):
        for files, lines in [(1, 10), (5, 100), (15, 400), (50, 2000)]:
            result = classify_scope(files, lines)
            assert isinstance(result.recommended_workflow, str)
            assert result.recommended_workflow  # non-empty

    def test_bracket_is_scope_bracket_instance(self):
        result = classify_scope(1, 10)
        assert isinstance(result.bracket, ScopeBracket)

    def test_classification_is_frozen(self):
        result = classify_scope(1, 10)
        with pytest.raises((AttributeError, TypeError)):
            result.bracket = ScopeBracket.LARGE  # type: ignore[misc]
