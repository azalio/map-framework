"""Tests for trajectory repeated-run aggregation (issue #351).

Covers per-fixture median/mean/stddev, hard-pass rate, and flaky detection
(single run => stddev 0 + single_run; high variance / inconsistent hard_pass
=> flaky flag).
"""

from __future__ import annotations

import pytest

from mapify_cli.skills_eval.trajectory.eval_schema import (
    ComponentScore,
    EvidenceLine,
    JudgeMeta,
    TrajectoryEvalRecord,
)
from mapify_cli.skills_eval.trajectory.repeated import (
    aggregate_repeated,
)


def _ev() -> EvidenceLine:
    return EvidenceLine(severity="info", ref="x", detail="d")


def _comp(name: str, score: float) -> ComponentScore:
    return ComponentScore(name=name, kind="deterministic", score=score, evidence=[_ev()])


def _record(fixture: str, run: int, composite: float, hard_pass: bool) -> TrajectoryEvalRecord:
    return TrajectoryEvalRecord(
        run_id=f"f{fixture}-r{run}",
        fixture=fixture,
        run=run,
        ts="ts",
        components=[_comp("formal", 1.0 if hard_pass else 0.0)],
        composite=composite,
        hard_pass=hard_pass,
        expected_outcome="complete",
        judge_meta=JudgeMeta(prompt_version="v", ordering="o", skipped=True),
    )


def test_aggregate_empty_returns_empty():
    agg = aggregate_repeated([])
    assert agg.fixtures == []
    assert agg.total_runs == 0


def test_aggregate_single_run_zero_stddev_not_flaky():
    agg = aggregate_repeated([_record("fx", 0, 0.9, True)])
    fa = agg.fixture("fx")
    assert fa is not None
    assert fa.n == 1
    assert fa.composite_stddev == 0.0
    assert fa.flaky is False
    assert fa.hard_pass_count == 1


def test_aggregate_high_variance_marks_flaky():
    records = [
        _record("fx", 0, 1.0, True),
        _record("fx", 1, 0.2, False),
        _record("fx", 2, 0.9, True),
    ]
    agg = aggregate_repeated(records)
    fa = agg.fixture("fx")
    assert fa is not None
    assert fa.flaky is True
    assert any("stddev" in r for r in fa.flaky_reasons)
    assert fa.hard_pass_count == 2


def test_aggregate_inconsistent_hard_pass_is_flaky_even_low_variance():
    # Same composite => low stddev, but hard_pass flips because formal flips.
    records = [
        _record("fx", 0, 0.5, True),
        _record("fx", 1, 0.5, False),
    ]
    agg = aggregate_repeated(records)
    fa = agg.fixture("fx")
    assert fa is not None
    assert fa.flaky is True
    assert fa.composite_stddev == 0.0
    assert any("hard_pass inconsistent" in r for r in fa.flaky_reasons)


def test_aggregate_multiple_fixtures_preserves_order():
    records = [
        _record("a", 0, 1.0, True),
        _record("b", 0, 0.5, False),
    ]
    agg = aggregate_repeated(records)
    assert [f.fixture for f in agg.fixtures] == ["a", "b"]
    # Both fixtures are single-run (n=1) => stddev 0 and no hard_pass mix => not flaky.
    assert agg.n_flaky == 0


def test_aggregate_overall_hard_pass_rate():
    records = [
        _record("fx", 0, 1.0, True),
        _record("fx", 1, 1.0, True),
        _record("fx", 2, 0.0, False),
    ]
    agg = aggregate_repeated(records)
    assert agg.overall_hard_pass_rate == 2 / 3


def test_aggregate_component_medians_collect_present():
    records = [
        TrajectoryEvalRecord(
            run_id="ffx-r0",
            fixture="fx",
            run=0,
            ts="ts",
            components=[
                _comp("formal", 1.0),
                ComponentScore(
                    name="pitfalls",
                    kind="judge",
                    score=0.4,
                    evidence=[_ev()],
                ),
            ],
            composite=0.7,
            hard_pass=True,
            expected_outcome="complete",
            judge_meta=JudgeMeta(prompt_version="v", ordering="o", skipped=False),
        ),
        TrajectoryEvalRecord(
            run_id="ffx-r1",
            fixture="fx",
            run=1,
            ts="ts",
            components=[
                _comp("formal", 0.0),
                ComponentScore(
                    name="pitfalls",
                    kind="judge",
                    score=0.8,
                    evidence=[_ev()],
                ),
            ],
            composite=0.4,
            hard_pass=False,
            expected_outcome="complete",
            judge_meta=JudgeMeta(prompt_version="v", ordering="o", skipped=False),
        ),
    ]
    agg = aggregate_repeated(records)
    fa = agg.fixture("fx")
    assert fa is not None
    assert fa.component_medians["formal"] == pytest.approx(0.5)
    assert fa.component_medians["pitfalls"] == pytest.approx(0.6)
