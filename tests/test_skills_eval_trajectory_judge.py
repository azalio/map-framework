"""Tests for the batched trajectory judge (issue #351).

Covers:
- ``MockJudgeRunner`` happy parse (3 dimensions).
- Malformed judge output => 3 zero-score components, never raises.
- Missing dimension => zero score for that dimension.
- ``runner=None`` (``--no-judge`` / dry-run) => three skipped components at 1.0.
- JudgeMeta provenance (prompt_version, ordering, caveats).
"""

from __future__ import annotations

import json

from mapify_cli.skills_eval.trajectory.eval_schema import TrajectoryBundle
from mapify_cli.skills_eval.trajectory.judge import (
    JUDGE_ORDERING,
    JUDGE_PROMPT_VERSION,
    MockJudgeRunner,
    score_judge,
)


def _bundle(*, response: str = "done") -> TrajectoryBundle:
    return TrajectoryBundle(
        fixture="fx",
        scenario="/map-task ST-001",
        branch="main",
        collected_at="ts",
        final_response=response,
        git={
            "modified_all": ["src/a.py"],
            "source_changes": ["src/a.py"],
            "out_of_scope": [],
            "trap_touched": [],
        },
        verification={"task_pass": True, "test_returncode": 0, "test_tail": ""},
    )


def _by_name(comps):
    return {c.name: c for c in comps}


def test_score_judge_happy_parse():
    payload = {
        "instruction_compliance": {"score": 5, "evidence": "stayed in scope"},
        "pitfalls": {"score": 4, "evidence": "one retry"},
        "reporting_trust": {"score": 5, "evidence": "claims match"},
    }
    comps, meta = score_judge(
        _bundle(), runner=MockJudgeRunner(payload=payload), timeout=10.0
    )
    by = _by_name(comps)
    assert by["instruction_compliance"].score == 1.0
    assert by["pitfalls"].score == 0.8
    assert by["reporting_trust"].score == 1.0
    assert meta.skipped is False
    assert meta.prompt_version == JUDGE_PROMPT_VERSION
    assert meta.ordering == JUDGE_ORDERING
    assert meta.caveats  # known caveats recorded


def test_score_judge_normalizes_1_5_scale():
    payload = {
        "instruction_compliance": {"score": 1, "evidence": "ignored scope"},
        "pitfalls": {"score": 3, "evidence": "mid"},
        "reporting_trust": {"score": 5, "evidence": "ok"},
    }
    comps, _ = score_judge(_bundle(), runner=MockJudgeRunner(payload=payload), timeout=10.0)
    by = _by_name(comps)
    assert by["instruction_compliance"].score == 0.2
    assert by["pitfalls"].score == 0.6


def test_score_judge_malformed_json_yields_zeros():
    runner = MockJudgeRunner(payload="not json at all")
    comps, meta = score_judge(_bundle(), runner=runner, timeout=10.0)
    assert meta.skipped is False
    for c in comps:
        assert c.score == 0.0
        assert c.evidence[0].severity == "critical"


def test_score_judge_missing_dimension_yields_zero_for_it():
    payload = {
        "instruction_compliance": {"score": 5, "evidence": "ok"},
        # pitfalls + reporting_trust missing
    }
    comps, _ = score_judge(_bundle(), runner=MockJudgeRunner(payload=payload), timeout=10.0)
    by = _by_name(comps)
    assert by["instruction_compliance"].score == 1.0
    assert by["pitfalls"].score == 0.0
    assert by["reporting_trust"].score == 0.0


def test_score_judge_runner_error_yields_zeros():
    runner = MockJudgeRunner(error="timeout after 1s")
    comps, meta = score_judge(_bundle(), runner=runner, timeout=10.0)
    assert meta.skipped is False
    for c in comps:
        assert c.score == 0.0


def test_score_judge_skipped_when_runner_none():
    comps, meta = score_judge(_bundle(), runner=None, timeout=10.0)
    assert meta.skipped is True
    for c in comps:
        assert c.score == 1.0
        assert c.kind == "judge"


def test_score_judge_clamps_out_of_range():
    payload = {
        "instruction_compliance": {"score": 99, "evidence": "x"},
        "pitfalls": {"score": -3, "evidence": "x"},
        "reporting_trust": {"score": "bad", "evidence": "x"},
    }
    comps, _ = score_judge(
        _bundle(), runner=MockJudgeRunner(payload=json.dumps(payload)), timeout=10.0
    )
    by = _by_name(comps)
    assert by["instruction_compliance"].score == 1.0  # clamped down
    assert by["pitfalls"].score == 0.0  # clamped up
    assert by["reporting_trust"].score == 0.0  # non-numeric => 0
