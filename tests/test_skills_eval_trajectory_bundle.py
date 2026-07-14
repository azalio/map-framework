"""Tests for trajectory bundle collection (issue #351).

Covers ``collect_bundle`` over a tmp_path seeded with ``.map/<branch>/``
artifacts: best-effort load + resiliency-signal distillation + scope-bucket
projection.
"""

from __future__ import annotations

import json

from mapify_cli.skills_eval.trajectory import bundle as bundle_mod
from mapify_cli.skills_eval.trajectory.eval_schema import TrajectoryBundle


def _scope(**overrides) -> dict:
    base = {
        "modified_all": ["src/a.py"],
        "source_changes": ["src/a.py"],
        "out_of_scope": [],
        "trap_touched": [],
        "scope_pass": True,
    }
    base.update(overrides)
    return base


def _verification() -> dict:
    return {"task_pass": True, "test_returncode": 0, "test_tail": "ok"}


def test_collect_bundle_basic_projection(tmp_path):
    b = bundle_mod.collect_bundle(
        tmp_path,
        fixture="fx",
        scenario="/map-task ST-001",
        branch="main",
        collected_at="2026-07-14T00:00:00Z",
        final_response="done",
        scope=_scope(),
        verification=_verification(),
        run_meta={"ok": True},
    )
    assert b.fixture == "fx"
    assert b.final_response == "done"
    assert b.git["source_changes"] == ["src/a.py"]
    # scope_pass is dropped from the bundle (owned by gates, not the bundle).
    assert "scope_pass" not in b.git
    assert b.verification["task_pass"] is True
    assert b.run_meta == {"ok": True}


def test_collect_bundle_round_trip(tmp_path):
    b = bundle_mod.collect_bundle(
        tmp_path,
        fixture="fx",
        scenario="s",
        branch="main",
        collected_at="ts",
        final_response="r",
        scope=_scope(),
        verification=_verification(),
    )
    assert TrajectoryBundle.from_dict(b.to_dict()) == b


def test_collect_bundle_loads_map_artifacts(tmp_path):
    branch_dir = tmp_path / ".map" / "main"
    branch_dir.mkdir(parents=True)
    (branch_dir / "step_state.json").write_text(
        json.dumps({"workflow": "map-efficient", "retry_count": 2}), encoding="utf-8"
    )
    (branch_dir / "run_health_report.json").write_text(
        json.dumps(
            {
                "resiliency_signals": {
                    "retry_count": 3,
                    "guard_rework_counts": {"scope": 1},
                    "predictor_called": True,
                }
            }
        ),
        encoding="utf-8",
    )
    b = bundle_mod.collect_bundle(
        tmp_path,
        fixture="fx",
        scenario="s",
        branch="main",
        collected_at="ts",
        final_response="r",
        scope=_scope(),
        verification=_verification(),
    )
    assert "step_state" in b.map_artifacts
    assert "run_health_report" in b.map_artifacts
    # resiliency distilled from run_health_report (preferred over step_state)
    assert b.resiliency_signals["retry_count"] == 3
    assert b.resiliency_signals["guard_rework_counts"] == {"scope": 1}


def test_collect_bundle_falls_back_to_step_state_retry_counters(tmp_path):
    branch_dir = tmp_path / ".map" / "main"
    branch_dir.mkdir(parents=True)
    (branch_dir / "step_state.json").write_text(
        json.dumps({"retry_count": 5, "clean_retry_count": 4}), encoding="utf-8"
    )
    b = bundle_mod.collect_bundle(
        tmp_path,
        fixture="fx",
        scenario="s",
        branch="main",
        collected_at="ts",
        final_response="r",
        scope=_scope(),
        verification=_verification(),
    )
    # No run_health_report => fallback to step_state counters.
    assert b.resiliency_signals.get("retry_count") == 5


def test_collect_bundle_missing_artifacts_yields_empty(tmp_path):
    b = bundle_mod.collect_bundle(
        tmp_path,
        fixture="fx",
        scenario="s",
        branch="main",
        collected_at="ts",
        final_response="r",
        scope=_scope(),
        verification=_verification(),
    )
    assert b.map_artifacts == {}
    assert b.resiliency_signals == {}


def test_collect_bundle_ignores_invalid_json(tmp_path):
    branch_dir = tmp_path / ".map" / "main"
    branch_dir.mkdir(parents=True)
    (branch_dir / "step_state.json").write_text("not json{", encoding="utf-8")
    b = bundle_mod.collect_bundle(
        tmp_path,
        fixture="fx",
        scenario="s",
        branch="main",
        collected_at="ts",
        final_response="r",
        scope=_scope(),
        verification=_verification(),
    )
    # Invalid file is simply absent — never an error.
    assert "step_state" not in b.map_artifacts
