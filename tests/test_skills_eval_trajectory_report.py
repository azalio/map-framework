"""Tests for the trajectory side-by-side regression report (issue #351).

Covers decision buckets (improvement/regression/tie/small/no_anchor),
component-level regression flags, and HTML rendering (autoescaped, renders
without jinja2 errors, contains the regression banner when present).
"""

from __future__ import annotations

from pathlib import Path

from mapify_cli.skills_eval.trajectory.eval_schema import (
    ComponentScore,
    EvidenceLine,
    JudgeMeta,
    TrajectoryEvalRecord,
)
from mapify_cli.skills_eval.trajectory.report import (
    build_report,
    render_comparison_to_path,
)


def _ev() -> EvidenceLine:
    return EvidenceLine(severity="info", ref="x", detail="d")


def _comp(name: str, score: float, kind: str = "deterministic") -> ComponentScore:
    return ComponentScore(name=name, kind=kind, score=score, evidence=[_ev()])


def _full_components(formal: float, ic: float) -> list[ComponentScore]:
    return [
        _comp("formal", formal),
        _comp("end_result", formal),
        _comp("tool_use", 1.0),
        _comp("instruction_compliance", ic, "judge"),
        _comp("pitfalls", 0.8, "judge"),
        _comp("reporting_trust", 0.9, "judge"),
    ]


def _record(fixture: str, run: int, formal: float, ic: float, composite: float) -> TrajectoryEvalRecord:
    return TrajectoryEvalRecord(
        run_id=f"f{fixture}-r{run}",
        fixture=fixture,
        run=run,
        ts="ts",
        components=_full_components(formal, ic),
        composite=composite,
        hard_pass=formal >= 1.0 and composite >= 0.8,
        expected_outcome="complete",
        judge_meta=JudgeMeta(prompt_version="v", ordering="o", skipped=False),
    )


def _by_fixture(report, name):
    for c in report.comparisons:
        if c.fixture == name:
            return c
    raise AssertionError(f"fixture {name} not in report")


def test_report_improvement_bucket():
    candidate = [_record("fx", 0, 1.0, 0.9, 0.95)]
    anchor = [_record("fx", 0, 1.0, 0.5, 0.80)]
    report = build_report(candidate, anchor, candidate_path="c", anchor_path="a")
    cmp_ = _by_fixture(report, "fx")
    assert cmp_.decision == "improvement"
    assert report.n_regressions == 0


def test_report_regression_bucket():
    candidate = [_record("fx", 0, 1.0, 0.3, 0.50)]
    anchor = [_record("fx", 0, 1.0, 0.9, 0.90)]
    report = build_report(candidate, anchor, candidate_path="c", anchor_path="a")
    cmp_ = _by_fixture(report, "fx")
    assert cmp_.decision == "regression"
    assert cmp_.is_regression is True
    assert report.n_regressions == 1


def test_report_tie_bucket_within_epsilon():
    candidate = [_record("fx", 0, 1.0, 0.8, 0.82)]
    anchor = [_record("fx", 0, 1.0, 0.8, 0.82)]
    report = build_report(candidate, anchor, candidate_path="c", anchor_path="a")
    cmp_ = _by_fixture(report, "fx")
    assert cmp_.decision == "tie"


def test_report_small_bucket_between_bands():
    candidate = [_record("fx", 0, 1.0, 0.8, 0.80)]
    anchor = [_record("fx", 0, 1.0, 0.7, 0.74)]
    report = build_report(candidate, anchor, candidate_path="c", anchor_path="a")
    cmp_ = _by_fixture(report, "fx")
    # delta 0.06: above tie(0.05), below regression(0.10) => small
    assert cmp_.decision == "small"


def test_report_no_anchor_for_fixture_only_in_candidate():
    candidate = [_record("new_fx", 0, 1.0, 0.9, 0.9)]
    anchor = [_record("other", 0, 1.0, 0.9, 0.9)]
    report = build_report(candidate, anchor, candidate_path="c", anchor_path="a")
    cmp_ = _by_fixture(report, "new_fx")
    assert cmp_.decision == "no_anchor"
    assert cmp_.anchor is None


def test_report_component_level_regression_flagged():
    # Composite tie, but one judge component regressed beyond delta.
    candidate = [
        TrajectoryEvalRecord(
            run_id="ffx-r0",
            fixture="fx",
            run=0,
            ts="ts",
            components=[
                _comp("formal", 1.0),
                _comp("end_result", 1.0),
                _comp("tool_use", 1.0),
                _comp("instruction_compliance", 0.2, "judge"),  # regressed
                _comp("pitfalls", 1.0, "judge"),
                _comp("reporting_trust", 1.0, "judge"),
            ],
            composite=0.85,
            hard_pass=True,
            expected_outcome="complete",
            judge_meta=JudgeMeta(prompt_version="v", ordering="o", skipped=False),
        )
    ]
    anchor = [
        TrajectoryEvalRecord(
            run_id="ffx-r0",
            fixture="fx",
            run=0,
            ts="ts",
            components=[
                _comp("formal", 1.0),
                _comp("end_result", 1.0),
                _comp("tool_use", 1.0),
                _comp("instruction_compliance", 0.9, "judge"),
                _comp("pitfalls", 0.8, "judge"),
                _comp("reporting_trust", 0.8, "judge"),
            ],
            composite=0.85,
            hard_pass=True,
            expected_outcome="complete",
            judge_meta=JudgeMeta(prompt_version="v", ordering="o", skipped=False),
        )
    ]
    report = build_report(candidate, anchor, candidate_path="c", anchor_path="a")
    cmp_ = _by_fixture(report, "fx")
    # composite medians equal => tie at composite level
    assert cmp_.decision == "tie"
    # but instruction_compliance regressed
    assert "instruction_compliance" in cmp_.regression_components
    assert cmp_.is_regression is True
    assert report.n_regressions == 1


def test_render_html_writes_file(tmp_path: Path):
    candidate = [_record("fx", 0, 1.0, 0.3, 0.50)]
    anchor = [_record("fx", 0, 1.0, 0.9, 0.90)]
    report = build_report(candidate, anchor, candidate_path="c.jsonl", anchor_path="a.jsonl")
    html_path = tmp_path / "report.html"
    render_comparison_to_path(report, html_path)
    text = html_path.read_text(encoding="utf-8")
    assert "regression" in text
    assert "fx" in text
    assert "c.jsonl" in text


def test_render_html_no_regressions_banner(tmp_path: Path):
    candidate = [_record("fx", 0, 1.0, 0.9, 0.95)]
    anchor = [_record("fx", 0, 1.0, 0.5, 0.80)]
    report = build_report(candidate, anchor, candidate_path="c", anchor_path="a")
    html_path = tmp_path / "ok.html"
    render_comparison_to_path(report, html_path)
    text = html_path.read_text(encoding="utf-8")
    assert "No regressions" in text
