"""ST-005: MapConfig dormant fields max_actors + retry_degraded_once, and clamp helper.

Covers:
  VC1 — dotted-key aliasing and field parsing from YAML
  VC2 — clamp_max_actors truth table
  VC3 — no runner/orchestrator .jinja in templates_src reads these fields
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from mapify_cli.config.project_config import (
    MapConfig,
    clamp_max_actors,
    load_map_config,
)

_TEMPLATES_SRC = Path(__file__).parent.parent / "src" / "mapify_cli" / "templates_src"


def _write_config(tmp_path: Path, body: str) -> None:
    (tmp_path / ".map").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".map" / "config.yaml").write_text(body, encoding="utf-8")


class TestVc1MaxActorsAndRetryDegraded:
    """VC1: dotted-key aliases are parsed; clamp and type fallback apply."""

    def test_vc1_defaults(self):
        cfg = MapConfig()
        assert cfg.max_actors == 4
        assert cfg.retry_degraded_once is False

    def test_vc1_absent_config_uses_defaults(self, tmp_path: Path):
        cfg = load_map_config(tmp_path)
        assert cfg.max_actors == 4
        assert cfg.retry_degraded_once is False

    def test_vc1_max_actors_above_range_clamped_to_8(self, tmp_path: Path):
        _write_config(tmp_path, "execution.max_actors: 12\n")
        cfg = load_map_config(tmp_path)
        assert cfg.max_actors == 8

    def test_vc1_max_actors_zero_clamped_to_1(self, tmp_path: Path):
        # 0 is a valid int (below floor 1) → clamped to 1, NOT the default 4.
        # Only non-int/bool/None values fall back to the default 4.
        _write_config(tmp_path, "execution.max_actors: 0\n")
        cfg = load_map_config(tmp_path)
        assert cfg.max_actors == 1

    def test_vc1_max_actors_in_range_preserved(self, tmp_path: Path):
        _write_config(tmp_path, "execution.max_actors: 3\n")
        cfg = load_map_config(tmp_path)
        assert cfg.max_actors == 3

    def test_vc1_retry_degraded_once_true(self, tmp_path: Path):
        _write_config(tmp_path, "execution.retry_degraded_once: true\n")
        cfg = load_map_config(tmp_path)
        assert cfg.retry_degraded_once is True

    def test_vc1_retry_degraded_once_default_false(self, tmp_path: Path):
        _write_config(tmp_path, "profile: full\n")
        cfg = load_map_config(tmp_path)
        assert cfg.retry_degraded_once is False

    def test_vc1_max_actors_non_int_falls_back_to_default(self, tmp_path: Path):
        _write_config(tmp_path, "execution.max_actors: \"notanint\"\n")
        cfg = load_map_config(tmp_path)
        # Generic type-check loop rejects non-int; clamp_max_actors on the
        # default 4 returns 4.
        assert cfg.max_actors == 4


class TestVc2ClampMaxActors:
    """VC2: clamp_max_actors truth table."""

    def test_vc2_in_range_values_preserved(self):
        for n in range(1, 9):
            assert clamp_max_actors(n) == n, f"expected {n} for input {n}"

    def test_vc2_below_floor_clamped_to_1(self):
        # int values below the floor (1) are clamped to 1, not the default 4.
        assert clamp_max_actors(0) == 1
        assert clamp_max_actors(-5) == 1

    def test_vc2_above_ceiling_clamped_to_8(self):
        assert clamp_max_actors(9) == 8
        assert clamp_max_actors(100) == 8

    def test_vc2_none_returns_default_4(self):
        assert clamp_max_actors(None) == 4

    def test_vc2_string_returns_default_4(self):
        assert clamp_max_actors("4") == 4
        assert clamp_max_actors("bad") == 4

    def test_vc2_bool_returns_default_4(self):
        # bool is a subclass of int in Python; clamp_max_actors explicitly
        # excludes bools so True/False return 4, not 1/0 clamped.
        assert clamp_max_actors(True) == 4
        assert clamp_max_actors(False) == 4

    def test_vc2_float_returns_default_4(self):
        assert clamp_max_actors(4.0) == 4

    def test_vc2_boundary_values(self):
        assert clamp_max_actors(1) == 1
        assert clamp_max_actors(8) == 8


class TestVc3DormantKeysUnused:
    """VC3: no execution path in templates_src runner/orchestrator reads the fields."""

    def _grep_templates_src(self, field_name: str) -> list[str]:
        """Return lines from runner/orchestrator .jinja files that reference field_name."""
        if not _TEMPLATES_SRC.exists():
            return []
        matches = []
        for jinja_file in _TEMPLATES_SRC.rglob("*.jinja"):
            # Only check runner and orchestrator files — those are the execution paths.
            if not any(
                tag in jinja_file.name
                for tag in ("runner", "orchestrator", "step_runner", "wave")
            ):
                continue
            content = jinja_file.read_text(encoding="utf-8")
            for lineno, line in enumerate(content.splitlines(), 1):
                if field_name in line:
                    matches.append(f"{jinja_file}:{lineno}: {line.rstrip()}")
        return matches

    def test_vc3_max_actors_not_consumed_in_runner_orchestrator(self):
        hits = self._grep_templates_src("max_actors")
        assert hits == [], (
            "max_actors is DORMANT in Slice 5a — no runner/orchestrator .jinja "
            "should reference it yet.\nFound:\n" + "\n".join(hits)
        )

    def test_vc3_retry_degraded_once_not_consumed_in_runner_orchestrator(self):
        hits = self._grep_templates_src("retry_degraded_once")
        assert hits == [], (
            "retry_degraded_once is DORMANT in Slice 5a — no runner/orchestrator "
            ".jinja should reference it yet.\nFound:\n" + "\n".join(hits)
        )

    def test_vc3_field_defined_in_project_config(self):
        """Positive proof: the fields exist on MapConfig."""
        cfg = MapConfig()
        assert hasattr(cfg, "max_actors")
        assert hasattr(cfg, "retry_degraded_once")

    def test_vc3_grep_subprocess_confirms_no_runner_orchestrator_consumer(self):
        """Subprocess grep across runner/orchestrator/step_runner Python sources.

        VC3 dormant means: no execution dispatch path reads the fields.
        Documentation files (.md, .md.jinja) and observability modules are
        permitted to mention max_actors by name; only the runner/orchestrator
        execution paths are forbidden in Slice 5a.
        """
        src_root = Path(__file__).parent.parent / "src" / "mapify_cli"
        result = subprocess.run(
            ["grep", "-rl", "max_actors", str(src_root)],
            capture_output=True,
            text=True,
        )
        files_with_max_actors = [
            line for line in result.stdout.splitlines() if line.strip()
        ]
        # Runner/orchestrator Python source files are forbidden in Slice 5a.
        # Documentation (.md, .jinja) and observability modules are allowed.
        _FORBIDDEN_STEMS = ("runner", "orchestrator", "step_runner", "wave_coordinator")
        forbidden = [
            f for f in files_with_max_actors
            if any(stem in Path(f).stem for stem in _FORBIDDEN_STEMS)
            and f.endswith(".py")
        ]
        assert forbidden == [], (
            "max_actors found in runner/orchestrator Python sources in Slice 5a "
            "(DORMANT violation — field must not be consumed until Slice 5b):\n"
            + "\n".join(forbidden)
        )
