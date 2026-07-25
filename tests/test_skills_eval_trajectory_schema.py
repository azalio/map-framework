"""Tests for the trajectory outcome-eval data layer (issue #351).

Covers:
- EvidenceLine / ComponentScore / TrajectoryBundle / TrajectoryEvalRecord
  to_dict / from_dict round-trips.
- TRAJECTORY_BUNDLE_SCHEMA / TRAJECTORY_EVAL_SCHEMA validation of real records.
- compute_composite / is_hard_pass / make_run_id helpers.
- Validation rejections (bad severity, bad component name, out-of-range score).
"""

from __future__ import annotations

import pytest

from mapify_cli.schemas import (
    TRAJECTORY_BUNDLE_SCHEMA,
    TRAJECTORY_EVAL_SCHEMA,
    validate_artifact,
)
from mapify_cli.skills_eval.trajectory.eval_schema import (
    COMPONENT_NAMES,
    HARD_PASS_COMPOSITE_THRESHOLD,
    ComponentScore,
    EvidenceLine,
    JudgeMeta,
    TrajectoryBundle,
    TrajectoryEvalRecord,
    compute_composite,
    is_hard_pass,
    make_run_id,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _ev(severity: str = "info", ref: str = "git:x", detail: str = "d") -> EvidenceLine:
    return EvidenceLine(severity=severity, ref=ref, detail=detail)


def _comp(
    name: str = "formal",
    kind: str = "deterministic",
    score: float = 1.0,
) -> ComponentScore:
    return ComponentScore(name=name, kind=kind, score=score, evidence=[_ev()])


def _bundle() -> TrajectoryBundle:
    return TrajectoryBundle(
        fixture="fx",
        scenario="/map-task ST-001",
        branch="main",
        collected_at="2026-07-14T00:00:00Z",
        final_response="done",
        git={
            "modified_all": ["src/a.py"],
            "source_changes": ["src/a.py"],
            "out_of_scope": [],
            "trap_touched": [],
        },
        verification={"task_pass": True, "test_returncode": 0, "test_tail": ""},
    )


def _record(
    components: list[ComponentScore] | None = None,
    composite: float | None = None,
) -> TrajectoryEvalRecord:
    comps = components if components is not None else [_comp("formal"), _comp("end_result")]
    comp_val = composite if composite is not None else compute_composite(comps)
    return TrajectoryEvalRecord(
        run_id="ffx-r0",
        fixture="fx",
        run=0,
        ts="2026-07-14T00:00:00Z",
        components=comps,
        composite=comp_val,
        hard_pass=is_hard_pass(comps, comp_val),
        expected_outcome="complete",
        judge_meta=JudgeMeta(
            prompt_version="trajectory-batch-v1",
            ordering="instruction_compliance,pitfalls,reporting_trust",
            skipped=True,
        ),
    )


# ---------------------------------------------------------------------------
# EvidenceLine
# ---------------------------------------------------------------------------


def test_evidence_line_round_trip():
    ev = _ev("warning", "step_state.json:retry_count", "3 retries")
    assert EvidenceLine.from_dict(ev.to_dict()) == ev


def test_evidence_line_rejects_bad_severity():
    with pytest.raises(ValueError):
        EvidenceLine(severity="loud", ref="x", detail="d")


def test_evidence_line_rejects_empty_ref():
    with pytest.raises(ValueError):
        EvidenceLine(severity="info", ref="", detail="d")


# ---------------------------------------------------------------------------
# ComponentScore
# ---------------------------------------------------------------------------


def test_component_score_rejects_unknown_name():
    with pytest.raises(ValueError):
        ComponentScore(name="bogus", kind="deterministic", score=1.0, evidence=[_ev()])


def test_component_score_rejects_out_of_range():
    with pytest.raises(ValueError):
        ComponentScore(name="formal", kind="deterministic", score=1.5, evidence=[_ev()])


def test_component_score_round_trip():
    c = _comp("reporting_trust", "judge", 0.8)
    assert ComponentScore.from_dict(c.to_dict()) == c


# ---------------------------------------------------------------------------
# TrajectoryBundle
# ---------------------------------------------------------------------------


def test_bundle_round_trip_and_schema_valid():
    b = _bundle()
    d = b.to_dict()
    ok, errors = validate_artifact(d, TRAJECTORY_BUNDLE_SCHEMA)
    assert ok, errors
    assert TrajectoryBundle.from_dict(d) == b


def test_bundle_schema_rejects_missing_required():
    b = _bundle()
    d = b.to_dict()
    del d["git"]
    ok, errors = validate_artifact(d, TRAJECTORY_BUNDLE_SCHEMA)
    assert not ok
    assert any("git" in e for e in errors)


# ---------------------------------------------------------------------------
# TrajectoryEvalRecord
# ---------------------------------------------------------------------------


def test_record_round_trip_and_schema_valid():
    r = _record()
    d = r.to_dict()
    ok, errors = validate_artifact(d, TRAJECTORY_EVAL_SCHEMA)
    assert ok, errors
    assert TrajectoryEvalRecord.from_dict(d) == r


def test_record_component_by_name():
    r = _record([_comp("formal"), _comp("end_result")])
    assert r.component_by_name("formal") is not None
    assert r.component_by_name("reporting_trust") is None


# ---------------------------------------------------------------------------
# compute_composite / is_hard_pass
# ---------------------------------------------------------------------------


def test_composite_blends_deterministic_and_judge():
    det = [_comp("formal", "deterministic", 1.0), _comp("end_result", "deterministic", 1.0)]
    jud = [_comp("pitfalls", "judge", 0.5)]
    # 0.5 * 1.0 + 0.5 * 0.5 = 0.75
    assert compute_composite(det + jud) == 0.75


def test_composite_collapses_to_present_class_when_one_missing():
    det = [_comp("formal", "deterministic", 1.0)]
    assert compute_composite(det) == 1.0


def test_hard_pass_requires_formal_and_end_result_pass_and_composite():
    good = [_comp("formal", "deterministic", 1.0), _comp("end_result", "deterministic", 1.0)]
    assert is_hard_pass(good, HARD_PASS_COMPOSITE_THRESHOLD)
    # formal failure => not hard pass even with high composite
    assert not is_hard_pass(
        [_comp("formal", "deterministic", 0.0), _comp("end_result", "deterministic", 1.0)],
        0.9,
    )


def test_hard_pass_false_below_threshold():
    good = [_comp("formal", "deterministic", 1.0), _comp("end_result", "deterministic", 1.0)]
    # composite BELOW threshold => not hard pass, regardless of formal/end pass.
    assert not is_hard_pass(good, HARD_PASS_COMPOSITE_THRESHOLD - 0.1)


# ---------------------------------------------------------------------------
# make_run_id
# ---------------------------------------------------------------------------


def test_make_run_id_deterministic():
    assert make_run_id("map_task_x", 2) == "fmap-task-x-r2"
    assert make_run_id("map_task_x", 2) == make_run_id("map_task_x", 2)


def test_component_names_canonical_order():
    assert COMPONENT_NAMES == (
        "formal",
        "end_result",
        "tool_use",
        "instruction_compliance",
        "pitfalls",
        "reporting_trust",
    )
