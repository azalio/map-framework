"""Tests for OptimizeIterationRecord, OptimizeResult, and ProposerFn in eval_schema.

VC1 [AC-7]: to_dict/from_dict round-trip for OptimizeResult (incl. nested iterations).
VC2 [AC-7]: ProposerFn importable and usable as a type alias.
VC3 [AC-7]: OptimizeIterationRecord carries all required fields.
"""

from __future__ import annotations

import json

from mapify_cli.skills_eval.eval_schema import (
    EvalResultRecord,
    OptimizeIterationRecord,
    OptimizeResult,
    ProposerFn,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_iter(
    iteration: int,
    *,
    candidate_description: str | None = "desc-v1",
    train_pass_rate: float = 0.8,
    test_pass_rate: float = 0.75,
    selected: bool = False,
    proposal_failed: bool = False,
    overfit: bool = False,
) -> OptimizeIterationRecord:
    return OptimizeIterationRecord(
        iteration=iteration,
        candidate_description=candidate_description,
        train_pass_rate=train_pass_rate,
        test_pass_rate=test_pass_rate,
        train_tokens_total=100 * iteration,
        test_tokens_total=50 * iteration,
        selected=selected,
        proposal_failed=proposal_failed,
        overfit=overfit,
        train_jsonl_path=f"/tmp/train-{iteration}.jsonl",
        test_jsonl_path=f"/tmp/test-{iteration}.jsonl",
    )


def _make_result() -> OptimizeResult:
    return OptimizeResult(
        skill="map-plan",
        eval_set_path="/evals/map-plan.json",
        seed=42,
        n_train=10,
        n_test=5,
        baseline_description="original description",
        winning_description="improved description",
        winning_iteration=2,
        no_improvement=False,
        iterations=[
            _make_iter(0, candidate_description=None, proposal_failed=True),
            _make_iter(1, train_pass_rate=0.7, test_pass_rate=0.65),
            _make_iter(2, train_pass_rate=0.9, test_pass_rate=0.85, selected=True),
        ],
    )


# ---------------------------------------------------------------------------
# VC1: full round-trip (OptimizeResult + each iteration)
# ---------------------------------------------------------------------------


def test_vc1_optimize_result_round_trip() -> None:
    """VC1: from_dict(json.loads(json.dumps(r.to_dict()))) == r for OptimizeResult."""
    original = _make_result()
    serialized = json.dumps(original.to_dict())
    restored = OptimizeResult.from_dict(json.loads(serialized))
    assert restored == original, f"round-trip mismatch:\n{restored!r}\n!=\n{original!r}"


def test_vc1_iteration_round_trip_each() -> None:
    """VC1: each OptimizeIterationRecord individually round-trips."""
    result = _make_result()
    for it in result.iterations:
        restored = OptimizeIterationRecord.from_dict(json.loads(json.dumps(it.to_dict())))
        assert restored == it, f"iteration {it.iteration} round-trip mismatch"


def test_vc1_iteration_none_candidate_round_trip() -> None:
    """VC1: candidate_description=None survives the JSON round-trip."""
    it = _make_iter(0, candidate_description=None, proposal_failed=True)
    restored = OptimizeIterationRecord.from_dict(json.loads(json.dumps(it.to_dict())))
    assert restored.candidate_description is None
    assert restored.proposal_failed is True
    assert restored == it


# ---------------------------------------------------------------------------
# Test 2: from_dict tolerates absent optional keys
# ---------------------------------------------------------------------------


def test_from_dict_tolerates_absent_optional_keys_iteration() -> None:
    """from_dict on OptimizeIterationRecord applies defaults for absent optional fields."""
    minimal: dict = {
        "iteration": 3,
        "candidate_description": "minimal",
        "train_pass_rate": 0.5,
        "test_pass_rate": 0.4,
        # omit: selected, proposal_failed, overfit, train/test_jsonl_path, token totals
    }
    rec = OptimizeIterationRecord.from_dict(minimal)
    assert rec.iteration == 3
    assert rec.candidate_description == "minimal"
    assert rec.train_pass_rate == 0.5
    assert rec.test_pass_rate == 0.4
    assert rec.train_tokens_total == 0
    assert rec.test_tokens_total == 0
    assert rec.selected is False
    assert rec.proposal_failed is False
    assert rec.overfit is False
    assert rec.train_jsonl_path == ""
    assert rec.test_jsonl_path == ""


def test_from_dict_tolerates_absent_iterations_in_optimize_result() -> None:
    """from_dict on OptimizeResult applies empty list when 'iterations' is absent."""
    minimal: dict = {
        "skill": "map-x",
        "eval_set_path": "/evals/x.json",
        "seed": 0,
        "n_train": 5,
        "n_test": 3,
        "baseline_description": "base",
        "winning_description": "base",
        "winning_iteration": 0,
        "no_improvement": True,
        # omit: iterations
    }
    result = OptimizeResult.from_dict(minimal)
    assert result.iterations == []
    assert result.no_improvement is True


# ---------------------------------------------------------------------------
# VC2: ProposerFn importable and callable
# ---------------------------------------------------------------------------


def test_vc2_proposer_fn_importable_and_callable() -> None:
    """VC2: ProposerFn is importable and a matching def is assignable and callable.

    The proposer signature is ``Callable[[str, list[EvalResultRecord]], str | None]``;
    both branches (None and str) satisfy the alias.
    """

    def none_proposer(current: str, failing: list[EvalResultRecord]) -> str | None:
        del current, failing  # unused: this proposer always declines
        return None

    p: ProposerFn = none_proposer
    assert p("some description", []) is None

    # A proposer that returns a string — exercises both params and EvalResultRecord.
    failing_record = EvalResultRecord(
        cell_id="p0-v1-r0",
        prompt="plan a feature",
        triggered_skill=None,
        token_usage=None,
        duration_s=1.0,
        assertions_failed=["expected map-plan to trigger"],
    )

    def echo_proposer(current: str, failing: list[EvalResultRecord]) -> str | None:
        return f"improved ({len(failing)} failing): {current}"

    p2: ProposerFn = echo_proposer
    assert p2("old", [failing_record]) == "improved (1 failing): old"


# ---------------------------------------------------------------------------
# VC3: OptimizeIterationRecord carries all required fields
# ---------------------------------------------------------------------------


def test_vc3_iteration_record_has_all_required_fields() -> None:
    """VC3: OptimizeIterationRecord carries train/test pass rates, token totals,
    selected, overfit flags, and per-iteration jsonl paths."""
    it = _make_iter(
        5,
        train_pass_rate=0.88,
        test_pass_rate=0.77,
        selected=True,
        overfit=True,
    )
    # pass rates
    assert it.train_pass_rate == 0.88
    assert it.test_pass_rate == 0.77
    # token totals (flat ints, no TokenUsage)
    assert isinstance(it.train_tokens_total, int)
    assert isinstance(it.test_tokens_total, int)
    assert it.train_tokens_total == 500
    assert it.test_tokens_total == 250
    # flags
    assert it.selected is True
    assert it.overfit is True
    # per-iteration jsonl paths (so viewer can render without re-parsing)
    assert it.train_jsonl_path == "/tmp/train-5.jsonl"
    assert it.test_jsonl_path == "/tmp/test-5.jsonl"
