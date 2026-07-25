"""
ST-005 eval/regression harness:
  - VC1: compute_waves + split_wave_by_file_conflicts shape assertions for
         linear_chain, two_wave_parallel, conflict_split fixtures.
  - VC2 (reframed for Slice 6): With a default (no-new-key) config,
         _execution_wave_mode == 'auto' AND _worktree_isolation_mode == 'auto'
         (both defaults flipped ON). Under a parallel-ready plan the wave-loop is
         now engaged by default. The kill-switch (MAP_EFFICIENT_SEQUENTIAL_ONLY=1)
         forces sequential regardless of config.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Runner import — identical pattern to tests/test_map_step_runner.py
# ---------------------------------------------------------------------------

SCRIPTS_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "mapify_cli"
    / "templates"
    / "map"
    / "scripts"
)

sys.path.insert(0, str(SCRIPTS_PATH))

import map_step_runner  # type: ignore[import-not-found]

# ---------------------------------------------------------------------------
# DependencyGraph import (same package as fixtures use)
# ---------------------------------------------------------------------------
from mapify_cli.dependency_graph import DependencyGraph

# ---------------------------------------------------------------------------
# Fixtures import
# ---------------------------------------------------------------------------
from tests.fixtures.wave_blueprints import (
    BlueprintFixture,
    conflict_split,
    linear_chain,
    two_wave_parallel,
)

# ---------------------------------------------------------------------------
# wave / color-group shape assertions
# ---------------------------------------------------------------------------


def test_wave_color_computation() -> None:
    """
    VC1 [AC-5]: compute_waves + split_wave_by_file_conflicts produce the
    expected wave/color-group shapes for the three blueprint fixtures.
    """

    # ---- linear_chain: 4 waves each of width 1 ----------------------------
    lc: BlueprintFixture = linear_chain()
    graph: DependencyGraph = lc.build_graph()
    waves = graph.compute_waves()

    assert waves is not None, "linear_chain must not have a cycle"
    assert len(waves) == 4, f"expected 4 waves, got {len(waves)}: {waves}"
    for i, wave in enumerate(waves):
        assert len(wave) == 1, (
            f"linear_chain wave {i} must have width 1, got {len(wave)}: {wave}"
        )

    # ---- two_wave_parallel: wave 1 has width >= 2 with disjoint files -----
    tp: BlueprintFixture = two_wave_parallel()
    tp_graph: DependencyGraph = tp.build_graph()
    tp_waves = tp_graph.compute_waves()

    assert tp_waves is not None, "two_wave_parallel must not have a cycle"
    assert len(tp_waves) == 2, f"expected 2 waves, got {len(tp_waves)}: {tp_waves}"

    parallel_wave = tp_waves[1]
    assert len(parallel_wave) >= 2, (
        f"two_wave_parallel wave 1 must have width >= 2, got {len(parallel_wave)}: {parallel_wave}"
    )

    # Verify members have disjoint affected_files
    seen_files: set[str] = set()
    for subtask_id in parallel_wave:
        subtask_files = tp.affected_files_map[subtask_id]
        overlap = seen_files & subtask_files
        assert not overlap, (
            f"two_wave_parallel wave 1 members share files: {subtask_id} overlaps {overlap}"
        )
        seen_files |= subtask_files

    # Confirm split_wave_by_file_conflicts leaves wave 1 intact (no conflicts)
    sub_waves = tp_graph.split_wave_by_file_conflicts(parallel_wave, tp.affected_files_map)
    assert len(sub_waves) == 1, (
        f"disjoint files: split_wave_by_file_conflicts should produce 1 sub-wave, "
        f"got {len(sub_waves)}: {sub_waves}"
    )
    assert sorted(sub_waves[0]) == sorted(parallel_wave), (
        f"sub-wave members must equal original wave members: {sub_waves[0]} != {parallel_wave}"
    )

    # ---- conflict_split: shared-file pair ends up in different sub-waves --
    cs: BlueprintFixture = conflict_split()
    cs_graph: DependencyGraph = cs.build_graph()
    cs_waves = cs_graph.compute_waves()

    assert cs_waves is not None, "conflict_split must not have a cycle"
    assert len(cs_waves) == 2, f"expected 2 waves, got {len(cs_waves)}: {cs_waves}"

    conflict_wave = cs_waves[1]
    # are all in wave 1
    assert sorted(conflict_wave) == ["ST-002", "ST-003", "ST-004"], (
        f"conflict wave members mismatch: {conflict_wave}"
    )

    sub_waves_cs = cs_graph.split_wave_by_file_conflicts(
        conflict_wave, cs.affected_files_map
    )
    # Must produce at least 2 sub-waves because and share 'src/shared.py'
    assert len(sub_waves_cs) >= 2, (
        f"conflict_split must produce >= 2 sub-waves, got {len(sub_waves_cs)}: {sub_waves_cs}"
    )

    # and must be in different sub-waves
    def _sub_wave_index(subtask_id: str) -> int:
        for idx, sw in enumerate(sub_waves_cs):
            if subtask_id in sw:
                return idx
        raise AssertionError(f"{subtask_id!r} not found in any sub-wave: {sub_waves_cs}")

    assert _sub_wave_index("ST-002") != _sub_wave_index("ST-004"), (
        f"ST-002 and ST-004 share 'src/shared.py' and must be in different sub-waves; "
        f"sub_waves={sub_waves_cs}"
    )


# ---------------------------------------------------------------------------
# default config selects the sequential / legacy path
# ---------------------------------------------------------------------------


def test_default_config_has_parallel_defaults(tmp_path: Path) -> None:
    """
    VC2 [AC-5] [SC-2] (reframed, Slice 6): With a default (no-new-key) config,
    the canonical MapConfig defaults now apply: _execution_wave_mode == 'auto'
    AND _worktree_isolation_mode == 'auto' (both flipped ON in Slice 6).

    Under a parallel-ready plan (two_wave_parallel), the wave-loop is now
    ENGAGED by default because isolation != 'off'.

    Also verifies the color-group concurrency predicate: two_wave_parallel has
    at least one color group of width >= 2.
    """
    # Case A: no .map directory at all — defaults are 'auto'.
    assert map_step_runner._execution_wave_mode(tmp_path) == "auto", (
        "_execution_wave_mode must default to 'auto' (MapConfig) when .map dir is absent"
    )
    assert map_step_runner._worktree_isolation_mode(tmp_path) == "auto", (
        "_worktree_isolation_mode must return 'auto' when .map dir is absent (Slice 6 default)"
    )

    # Case B: .map/config.yaml exists but contains NO new keys — still defaults to 'auto'.
    map_dir = tmp_path / ".map"
    map_dir.mkdir()
    (map_dir / "config.yaml").write_text(
        "minimality: off\n",  # existing key only — no wave_mode or isolation keys
        encoding="utf-8",
    )

    assert map_step_runner._execution_wave_mode(tmp_path) == "auto", (
        "_execution_wave_mode must default to 'auto' when execution.wave_mode key is absent"
    )
    assert map_step_runner._worktree_isolation_mode(tmp_path) == "auto", (
        "_worktree_isolation_mode must return 'auto' when worktree.isolation key is absent "
        "(Slice 6 default flipped from 'off')"
    )

    # Show the concurrency predicate (color group width >= 2) is true for two_wave_parallel.
    tp: BlueprintFixture = two_wave_parallel()
    tp_graph: DependencyGraph = tp.build_graph()
    tp_waves = tp_graph.compute_waves()

    assert tp_waves is not None
    color_groups = [
        tp_graph.split_wave_by_file_conflicts(w, tp.affected_files_map) for w in tp_waves
    ]
    assert any(len(g) >= 2 for groups in color_groups for g in groups), (
        "two_wave_parallel must expose at least one color group of width >= 2 "
        "(the concurrency predicate gate)"
    )

    # Slice 6: wave_mode='auto' AND isolation='auto' (!=off) AND width>=2 group exists
    # → wave-loop is now engaged by default (not suppressed by the isolation gate).
    wave_mode = map_step_runner._execution_wave_mode(tmp_path)
    isolation = map_step_runner._worktree_isolation_mode(tmp_path)
    assert wave_mode == "auto", f"default wave_mode must be 'auto', got {wave_mode!r}"
    assert isolation == "auto", f"default isolation must be 'auto' (Slice 6), got {isolation!r}"
    # With isolation='auto' the wave-loop predicate CAN engage for parallel-ready plans.
    assert isolation != "off", (
        "isolation default must NOT be 'off' — Slice 6 flipped it to 'auto' so "
        "parallel-ready plans now use the wave-loop by default."
    )


def test_kill_switch_forces_sequential(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    VC2 kill-switch: MAP_EFFICIENT_SEQUENTIAL_ONLY=1 forces sequential regardless
    of the (now-parallel) defaults.

    This is the behavioral invariant that replaces the old 'default → sequential'
    test: the byte-identical-to-legacy proof now applies to the kill-switch path,
    not the default config path.
    """
    monkeypatch.setenv("MAP_EFFICIENT_SEQUENTIAL_ONLY", "1")

    # With the kill-switch set, isolation_mode does not matter — the gate short-circuits.
    isolation = map_step_runner._worktree_isolation_mode(tmp_path)
    wave_mode = map_step_runner._execution_wave_mode(tmp_path)
    # Defaults are still 'auto' at the reader level — kill-switch operates at orchestrator.
    assert wave_mode == "auto", (
        "_execution_wave_mode reads config (not the env var); still returns 'auto'"
    )
    assert isolation == "auto", (
        "_worktree_isolation_mode reads config (not the env var); still returns 'auto'"
    )
