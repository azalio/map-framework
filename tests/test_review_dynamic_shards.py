"""Admission sizes the shard count to the measured plan; only an explicit cap or a ceiling stops it."""

from tests.test_review_changed_scope import repo as _base_repo
from tests.test_review_changed_scope import runner
from tests.test_review_windowed_sources import many_files

repo = _base_repo
__all__ = ["repo"]


def admit(monkeypatch, files=12):
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", str(runner.REVIEW_CONTEXT_RESERVE_BYTES + 60_000))
    monkeypatch.delenv("MAP_REVIEW_MAX_SHARDS", raising=False)
    many_files(count=files)
    return runner.begin_review_run(branch="feature", provider="claude", round_id="dyn", base_ref="main")


def test_twelve_shard_plan_is_admitted_without_operator_settings(repo, monkeypatch):
    del repo
    admitted = admit(monkeypatch)
    assert admitted["status"] == "success", {k: v for k, v in admitted.items() if k != "hints"}
    assert admitted["shard_count"] == len(admitted["shard_ids"]) >= 12


def test_explicit_cap_still_reports_too_many_shards(repo, monkeypatch):
    del repo
    monkeypatch.setenv("MAP_REVIEW_MAX_SHARDS", "4")
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", str(runner.REVIEW_CONTEXT_RESERVE_BYTES + 60_000))
    many_files(count=12)
    result = runner.begin_review_run(branch="feature", provider="claude", round_id="dyn", base_ref="main")
    assert result["reason"] == "too_many_shards" and result["max_shards"] == 4, result
    assert result["max_shards_source"] == "explicit"
    hint = " ".join(result["hints"])
    assert "MAP_REVIEW_MAX_SHARDS" in hint and str(result["shards_needed"]) in hint


def test_safety_ceiling_is_enforced_without_an_explicit_cap(repo, monkeypatch):
    del repo
    monkeypatch.setattr(runner, "REVIEW_MAX_SHARDS", 5)
    result = admit(monkeypatch)
    assert result["reason"] == "too_many_shards" and result["max_shards"] == 5, result
    assert result["max_shards_source"] == "ceiling"
    hint = " ".join(result["hints"])
    assert "MAP_REVIEW_MAX_SHARDS" in hint and str(result["shards_needed"]) in hint


def test_default_ceiling_is_high_and_explicit_caps_win(monkeypatch):
    monkeypatch.delenv("MAP_REVIEW_MAX_SHARDS", raising=False)
    assert runner._review_max_shards({}) == runner.REVIEW_MAX_SHARDS >= 64
    assert runner._review_max_shards({"max_shards": 3}) == 3
    monkeypatch.setenv("MAP_REVIEW_MAX_SHARDS", "100")
    assert runner._review_max_shards({"max_shards": 3}) == 100
