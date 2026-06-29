"""ST-005: MapConfig fields max_actors + retry_degraded_once, and clamp helper.
ST-000: MapConfig fields concurrent_dispatch + max_wave_retries (5b config).

Covers:
  VC1 — dotted-key aliasing and field parsing from YAML
  VC2 — clamp_max_actors truth table
  VC3 — max_actors is ACTIVE in runner/orchestrator (Slice 5b); retry_degraded_once remains dormant
  VC4 (ST-000) — concurrent_dispatch and max_wave_retries parsed/clamped correctly
  VC5 (ST-000) — clamp_max_wave_retries truth table
  VC6 (ST-000) — concurrent_dispatch + max_wave_retries are ACTIVE in runner/orchestrator (Slice 5b)
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from mapify_cli.config.project_config import (
    MapConfig,
    clamp_max_actors,
    clamp_max_wave_retries,
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
    """VC3 (updated for Slice 5b): max_actors is now ACTIVE in runner/orchestrator.
    retry_degraded_once remains DORMANT (Slice 6+).
    """

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

    def test_vc3_max_actors_consumed_in_runner_orchestrator(self):
        """Slice 5b activated max_actors: runner/orchestrator .jinja must reference it."""
        hits = self._grep_templates_src("max_actors")
        assert hits != [], (
            "max_actors should be ACTIVE in Slice 5b — runner/orchestrator .jinja "
            "must reference it (run_concurrent_wave / _max_actors helper)."
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

    def test_vc3_grep_subprocess_confirms_runner_orchestrator_consumer(self):
        """Subprocess grep: runner/orchestrator Python sources now consume max_actors (Slice 5b active)."""
        src_root = Path(__file__).parent.parent / "src" / "mapify_cli"
        result = subprocess.run(
            ["grep", "-rl", "max_actors", str(src_root)],
            capture_output=True,
            text=True,
        )
        files_with_max_actors = [
            line for line in result.stdout.splitlines() if line.strip()
        ]
        # Slice 5b: max_actors must be consumed by at least one runner/orchestrator source.
        _ACTIVE_STEMS = ("runner", "orchestrator", "step_runner", "wave_coordinator")
        active = [
            f for f in files_with_max_actors
            if any(stem in Path(f).stem for stem in _ACTIVE_STEMS)
            and f.endswith(".py")
        ]
        assert active != [], (
            "max_actors not found in any runner/orchestrator Python source after Slice 5b — "
            "expected _max_actors() or run_concurrent_wave() to consume it."
        )


# ---------------------------------------------------------------------------
# ST-000: concurrent_dispatch + max_wave_retries (5b.0 config half)
# ---------------------------------------------------------------------------


class TestVc4ConcurrentDispatchAndMaxWaveRetries:
    """VC4: dotted-key aliases parsed; type/clamp/default behaviour correct."""

    def test_vc4_concurrent_dispatch_true_from_yaml(self, tmp_path: Path):
        _write_config(tmp_path, "execution.concurrent_dispatch: true\n")
        cfg = load_map_config(tmp_path)
        assert cfg.concurrent_dispatch is True

    def test_vc4_concurrent_dispatch_default_true(self, tmp_path: Path):
        # Slice 6: default flipped from False to True.
        cfg = load_map_config(tmp_path)
        assert cfg.concurrent_dispatch is True

    def test_vc4_concurrent_dispatch_false_from_yaml(self, tmp_path: Path):
        _write_config(tmp_path, "execution.concurrent_dispatch: false\n")
        cfg = load_map_config(tmp_path)
        assert cfg.concurrent_dispatch is False

    def test_vc4_max_wave_retries_from_yaml(self, tmp_path: Path):
        _write_config(tmp_path, "execution.max_wave_retries: 7\n")
        cfg = load_map_config(tmp_path)
        assert cfg.max_wave_retries == 7

    def test_vc4_max_wave_retries_default_three(self, tmp_path: Path):
        cfg = load_map_config(tmp_path)
        assert cfg.max_wave_retries == 3

    def test_vc4_max_wave_retries_zero_clamped_to_1(self, tmp_path: Path):
        _write_config(tmp_path, "execution.max_wave_retries: 0\n")
        cfg = load_map_config(tmp_path)
        assert cfg.max_wave_retries == 1

    def test_vc4_max_wave_retries_above_ceiling_clamped(self, tmp_path: Path):
        _write_config(tmp_path, "execution.max_wave_retries: 99\n")
        cfg = load_map_config(tmp_path)
        assert cfg.max_wave_retries == 10

    def test_vc4_max_wave_retries_string_falls_back_to_default(self, tmp_path: Path):
        _write_config(tmp_path, 'execution.max_wave_retries: "abc"\n')
        cfg = load_map_config(tmp_path)
        # Generic type-check loop rejects non-int; clamp_max_wave_retries on the
        # default value returns 3.
        assert cfg.max_wave_retries == 3

    def test_vc4_max_wave_retries_bool_falls_back_to_default(self, tmp_path: Path):
        # YAML `true` parses as bool True; the generic type-check loop rejects it
        # (bool != int at the expected_type check), so the field keeps its default.
        _write_config(tmp_path, "execution.max_wave_retries: true\n")
        cfg = load_map_config(tmp_path)
        assert cfg.max_wave_retries == 3

    def test_vc4_dotted_alias_not_a_dead_toggle_concurrent_dispatch(
        self, tmp_path: Path
    ):
        """Alias fires BEFORE the generic mapping loop — not a silent dead toggle."""
        _write_config(tmp_path, "execution.concurrent_dispatch: true\n")
        cfg = load_map_config(tmp_path)
        assert cfg.concurrent_dispatch is True, (
            "execution.concurrent_dispatch alias is a dead toggle — "
            "add it to the dotted-key alias list BEFORE the mapping loop"
        )

    def test_vc4_dotted_alias_not_a_dead_toggle_max_wave_retries(
        self, tmp_path: Path
    ):
        """Alias fires BEFORE the generic mapping loop — not a silent dead toggle."""
        _write_config(tmp_path, "execution.max_wave_retries: 5\n")
        cfg = load_map_config(tmp_path)
        assert cfg.max_wave_retries == 5, (
            "execution.max_wave_retries alias is a dead toggle — "
            "add it to the dotted-key alias list BEFORE the mapping loop"
        )

    def test_vc4_fields_exist_on_mapconfig(self):
        """Positive proof: both new fields exist on MapConfig."""
        cfg = MapConfig()
        assert hasattr(cfg, "concurrent_dispatch")
        assert hasattr(cfg, "max_wave_retries")


class TestVc5ClampMaxWaveRetries:
    """VC5: clamp_max_wave_retries truth table."""

    def test_vc5_valid_range_preserved(self):
        for n in range(1, 11):
            assert clamp_max_wave_retries(n) == n, f"expected {n} for input {n}"

    def test_vc5_below_floor_clamped_to_1(self):
        assert clamp_max_wave_retries(0) == 1
        assert clamp_max_wave_retries(-5) == 1

    def test_vc5_above_ceiling_clamped_to_10(self):
        assert clamp_max_wave_retries(11) == 10
        assert clamp_max_wave_retries(100) == 10

    def test_vc5_none_returns_default(self):
        assert clamp_max_wave_retries(None) == 3

    def test_vc5_string_returns_default(self):
        assert clamp_max_wave_retries("3") == 3
        assert clamp_max_wave_retries("bad") == 3

    def test_vc5_bool_returns_default(self):
        # bool is a subclass of int in Python; clamp_max_wave_retries explicitly
        # excludes it so a YAML boolean is treated as misconfiguration → default.
        assert clamp_max_wave_retries(True) == 3
        assert clamp_max_wave_retries(False) == 3

    def test_vc5_float_returns_default(self):
        assert clamp_max_wave_retries(3.0) == 3

    def test_vc5_boundary_values(self):
        assert clamp_max_wave_retries(1) == 1
        assert clamp_max_wave_retries(10) == 10


class TestVc6DormantFieldsUnused5b0:
    """VC6 (updated for Slice 5b): concurrent_dispatch and max_wave_retries are now ACTIVE.

    Slice 5b activated concurrent dispatch; these fields must now be consumed by
    runner/orchestrator .jinja and compiled Python sources.
    """

    def _grep_templates_src(self, field_name: str) -> list[str]:
        """Return lines from runner/orchestrator .jinja files that reference field_name."""
        if not _TEMPLATES_SRC.exists():
            return []
        matches = []
        for jinja_file in _TEMPLATES_SRC.rglob("*.jinja"):
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

    def test_vc6_concurrent_dispatch_consumed_in_runner_orchestrator(self):
        """Slice 5b: concurrent_dispatch must be referenced in runner/orchestrator .jinja."""
        hits = self._grep_templates_src("concurrent_dispatch")
        assert hits != [], (
            "concurrent_dispatch should be ACTIVE in Slice 5b — runner/orchestrator "
            ".jinja must reference it (compute_dispatch_gate / _concurrent_dispatch_enabled)."
        )

    def test_vc6_max_wave_retries_consumed_in_runner_orchestrator(self):
        """Slice 5b: max_wave_retries must be referenced in runner/orchestrator .jinja."""
        hits = self._grep_templates_src("max_wave_retries")
        assert hits != [], (
            "max_wave_retries should be ACTIVE in Slice 5b — runner/orchestrator "
            ".jinja must reference it (_max_wave_retries helper / abort_wave_group)."
        )

    def test_vc6_grep_subprocess_runner_consumer_concurrent_dispatch(self):
        """Subprocess grep: runner/orchestrator Python sources now consume concurrent_dispatch."""
        src_root = Path(__file__).parent.parent / "src" / "mapify_cli"
        result = subprocess.run(
            ["grep", "-rl", "concurrent_dispatch", str(src_root)],
            capture_output=True,
            text=True,
        )
        files_with_field = [line for line in result.stdout.splitlines() if line.strip()]
        _ACTIVE_STEMS = ("runner", "orchestrator", "step_runner", "wave_coordinator")
        active = [
            f for f in files_with_field
            if any(stem in Path(f).stem for stem in _ACTIVE_STEMS)
            and f.endswith(".py")
        ]
        assert active != [], (
            "concurrent_dispatch not found in any runner/orchestrator Python source after "
            "Slice 5b — expected compute_dispatch_gate or _concurrent_dispatch_enabled."
        )

    def test_vc6_grep_subprocess_runner_consumer_max_wave_retries(self):
        """Subprocess grep: runner/orchestrator Python sources now consume max_wave_retries."""
        src_root = Path(__file__).parent.parent / "src" / "mapify_cli"
        result = subprocess.run(
            ["grep", "-rl", "max_wave_retries", str(src_root)],
            capture_output=True,
            text=True,
        )
        files_with_field = [line for line in result.stdout.splitlines() if line.strip()]
        _ACTIVE_STEMS = ("runner", "orchestrator", "step_runner", "wave_coordinator")
        active = [
            f for f in files_with_field
            if any(stem in Path(f).stem for stem in _ACTIVE_STEMS)
            and f.endswith(".py")
        ]
        assert active != [], (
            "max_wave_retries not found in any runner/orchestrator Python source after "
            "Slice 5b — expected _max_wave_retries() or abort_wave_group() to consume it."
        )


class TestSlice6Defaults:
    """Slice 6: worktree_isolation and concurrent_dispatch defaults flipped ON."""

    def test_mapconfig_worktree_isolation_default_auto(self) -> None:
        """Slice 6: MapConfig().worktree_isolation == 'auto' (flipped from 'off')."""
        cfg = MapConfig()
        assert cfg.worktree_isolation == "auto", (
            f"MapConfig.worktree_isolation default must be 'auto' (Slice 6 flip), "
            f"got {cfg.worktree_isolation!r}"
        )

    def test_mapconfig_concurrent_dispatch_default_true(self) -> None:
        """Slice 6: MapConfig().concurrent_dispatch is True (flipped from False)."""
        cfg = MapConfig()
        assert cfg.concurrent_dispatch is True, (
            "MapConfig.concurrent_dispatch default must be True (Slice 6 flip)"
        )

    def test_absent_config_worktree_isolation_default_auto(self, tmp_path: Path) -> None:
        """Slice 6: no .map/config.yaml → worktree_isolation defaults to 'auto'."""
        cfg = load_map_config(tmp_path)
        assert cfg.worktree_isolation == "auto", (
            f"load_map_config with absent config must give worktree_isolation='auto' "
            f"(Slice 6 flip from 'off'), got {cfg.worktree_isolation!r}"
        )

    def test_absent_config_concurrent_dispatch_default_true(self, tmp_path: Path) -> None:
        """Slice 6: no .map/config.yaml → concurrent_dispatch defaults to True."""
        cfg = load_map_config(tmp_path)
        assert cfg.concurrent_dispatch is True, (
            "load_map_config with absent config must give concurrent_dispatch=True "
            "(Slice 6 flip from False)"
        )

    def test_per_repo_opt_out_worktree_isolation_off(self, tmp_path: Path) -> None:
        """Per-repo opt-out: worktree.isolation: off overrides the Slice 6 default."""
        (tmp_path / ".map").mkdir(parents=True, exist_ok=True)
        (tmp_path / ".map" / "config.yaml").write_text(
            "worktree.isolation: off\n", encoding="utf-8"
        )
        cfg = load_map_config(tmp_path)
        assert cfg.worktree_isolation == "off", (
            "worktree.isolation: off in config.yaml must override the Slice 6 default"
        )

    def test_per_repo_opt_out_concurrent_dispatch_false(self, tmp_path: Path) -> None:
        """Per-repo opt-out: execution.concurrent_dispatch: false overrides the default."""
        (tmp_path / ".map").mkdir(parents=True, exist_ok=True)
        (tmp_path / ".map" / "config.yaml").write_text(
            "execution.concurrent_dispatch: false\n", encoding="utf-8"
        )
        cfg = load_map_config(tmp_path)
        assert cfg.concurrent_dispatch is False, (
            "execution.concurrent_dispatch: false in config.yaml must override the Slice 6 default"
        )
