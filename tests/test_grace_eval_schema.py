"""Tests for grace_eval.schema data contracts (#339).

Covers:
  GE1 — variant enumeration is complete and ordered
  GE2 — GraceFixture round-trip and validation
  GE3 — VariantRunRecord round-trip and validation
  GE4 — VariantAggregate round-trip and validation
  GE5 — SweepFinding round-trip and validation
  GE6 — GraceReport round-trip and helpers
  GE7 — make_run_id is deterministic and unique
  GE8 — aggregate_runs computes correct stats
  GE9 — aggregate_runs baseline delta computation
"""

from __future__ import annotations

import json

import pytest

from mapify_cli.grace_eval.schema import (
    CODE_LOCAL_VARIANTS,
    NO_ANCHOR_VARIANTS,
    PROMPT_INJECTED_VARIANTS,
    VARIANT_NAMES,
    GraceFixture,
    GraceReport,
    SweepFinding,
    VariantAggregate,
    VariantRunRecord,
    aggregate_runs,
    make_run_id,
)

# ---------------------------------------------------------------------------
# GE1 — variant enumeration
# ---------------------------------------------------------------------------


class TestGe1VariantEnumeration:
    def test_all_six_variants_present(self) -> None:
        assert set(VARIANT_NAMES) == {"baseline", "inline", "lex", "min", "inj", "lie"}

    def test_variant_names_ordered(self) -> None:
        assert VARIANT_NAMES == ("baseline", "inline", "lex", "min", "inj", "lie")

    def test_variant_sets_partition(self) -> None:
        # baseline, inline, lex, min, inj, lie — all covered
        assert "baseline" in NO_ANCHOR_VARIANTS
        assert "inline" in CODE_LOCAL_VARIANTS
        assert "lex" in CODE_LOCAL_VARIANTS
        assert "min" in CODE_LOCAL_VARIANTS
        assert "inj" in PROMPT_INJECTED_VARIANTS
        assert "lie" in CODE_LOCAL_VARIANTS
        # no variant is in two sets at once
        assert not (CODE_LOCAL_VARIANTS & PROMPT_INJECTED_VARIANTS)
        assert not (CODE_LOCAL_VARIANTS & NO_ANCHOR_VARIANTS)
        assert not (PROMPT_INJECTED_VARIANTS & NO_ANCHOR_VARIANTS)

    def test_lie_in_code_local(self) -> None:
        assert "lie" in CODE_LOCAL_VARIANTS

    def test_inj_in_prompt_injected(self) -> None:
        assert "inj" in PROMPT_INJECTED_VARIANTS


# ---------------------------------------------------------------------------
# GE2 — GraceFixture
# ---------------------------------------------------------------------------


class TestGe2GraceFixture:
    def _make(self) -> GraceFixture:
        return GraceFixture(
            fixture_id="off-by-one",
            title="Off-by-one in range check",
            description="The range bound is exclusive but code treats it as inclusive.",
            bug_summary="fence-post error in validate_range()",
            expected_changed_files=["src/utils.py"],
            tags=["off-by-one", "boundary"],
        )

    def test_round_trip(self) -> None:
        f = self._make()
        rt = GraceFixture.from_dict(f.to_dict())
        assert rt.fixture_id == f.fixture_id
        assert rt.title == f.title
        assert rt.description == f.description
        assert rt.bug_summary == f.bug_summary
        assert rt.expected_changed_files == f.expected_changed_files
        assert rt.tags == f.tags

    def test_json_serialisable(self) -> None:
        f = self._make()
        raw = json.dumps(f.to_dict())
        data = json.loads(raw)
        rt = GraceFixture.from_dict(data)
        assert rt.fixture_id == "off-by-one"

    def test_schema_version_present(self) -> None:
        f = self._make()
        assert "schema_version" in f.to_dict()

    def test_invalid_empty_fixture_id(self) -> None:
        with pytest.raises(ValueError, match="fixture_id"):
            GraceFixture(fixture_id="", title="T", description="", bug_summary="")

    def test_invalid_empty_title(self) -> None:
        with pytest.raises(ValueError, match="title"):
            GraceFixture(fixture_id="x", title="", description="", bug_summary="")

    def test_optional_fields_default(self) -> None:
        f = GraceFixture(fixture_id="x", title="T", description="", bug_summary="")
        assert f.expected_changed_files == []
        assert f.tags == []

    def test_from_dict_tolerates_missing_optional(self) -> None:
        f = GraceFixture.from_dict({"fixture_id": "x", "title": "T"})
        assert f.description == ""
        assert f.expected_changed_files == []


# ---------------------------------------------------------------------------
# GE3 — VariantRunRecord
# ---------------------------------------------------------------------------


class TestGe3VariantRunRecord:
    def _make(self, variant: str = "baseline") -> VariantRunRecord:
        return VariantRunRecord(
            run_id="off-by-one-baseline-r0",
            fixture_id="off-by-one",
            variant=variant,
            success=True,
            retry_count=1,
            total_tokens=4500,
            output_tokens=800,
            repeated_reads=2,
            stale_detection=False,
        )

    def test_round_trip(self) -> None:
        r = self._make()
        rt = VariantRunRecord.from_dict(r.to_dict())
        assert rt.run_id == r.run_id
        assert rt.fixture_id == r.fixture_id
        assert rt.variant == r.variant
        assert rt.success == r.success
        assert rt.retry_count == r.retry_count
        assert rt.total_tokens == r.total_tokens
        assert rt.output_tokens == r.output_tokens
        assert rt.repeated_reads == r.repeated_reads
        assert rt.stale_detection == r.stale_detection
        assert rt.error is None

    def test_json_serialisable(self) -> None:
        r = self._make()
        data = json.loads(json.dumps(r.to_dict()))
        rt = VariantRunRecord.from_dict(data)
        assert rt.total_tokens == 4500

    def test_stale_detection_lie_variant(self) -> None:
        r2 = VariantRunRecord(
            run_id="x-lie-r0", fixture_id="x", variant="lie",
            success=False, stale_detection=True,
        )
        assert r2.stale_detection is True
        d = r2.to_dict()
        rt = VariantRunRecord.from_dict(d)
        assert rt.stale_detection is True

    def test_invalid_variant(self) -> None:
        with pytest.raises(ValueError, match="variant"):
            VariantRunRecord(run_id="x", fixture_id="f", variant="unknown", success=True)

    def test_invalid_negative_retry(self) -> None:
        with pytest.raises(ValueError, match="retry_count"):
            VariantRunRecord(
                run_id="x", fixture_id="f", variant="baseline",
                success=True, retry_count=-1,
            )

    def test_error_field_round_trip(self) -> None:
        r = VariantRunRecord(
            run_id="x", fixture_id="f", variant="lex",
            success=False, error="timeout after 30s",
        )
        rt = VariantRunRecord.from_dict(r.to_dict())
        assert rt.error == "timeout after 30s"

    @pytest.mark.parametrize("variant", VARIANT_NAMES)
    def test_all_variants_accepted(self, variant: str) -> None:
        r = VariantRunRecord(run_id=f"x-{variant}-r0", fixture_id="x", variant=variant, success=True)
        assert r.variant == variant


# ---------------------------------------------------------------------------
# GE4 — VariantAggregate
# ---------------------------------------------------------------------------


class TestGe4VariantAggregate:
    def _make(self, variant: str = "baseline") -> VariantAggregate:
        return VariantAggregate(
            variant=variant,
            n=5,
            success_rate=0.8,
            mean_retries=0.4,
            mean_total_tokens=5000.0,
            mean_repeated_reads=1.2,
            stale_detections=0,
        )

    def test_round_trip(self) -> None:
        a = self._make()
        rt = VariantAggregate.from_dict(a.to_dict())
        assert rt.variant == a.variant
        assert rt.n == a.n
        assert abs(rt.success_rate - a.success_rate) < 1e-6
        assert rt.trajectory_delta_note == "no_baseline"

    def test_json_serialisable(self) -> None:
        a = self._make("lex")
        data = json.loads(json.dumps(a.to_dict()))
        rt = VariantAggregate.from_dict(data)
        assert rt.variant == "lex"

    def test_invalid_trajectory_note(self) -> None:
        with pytest.raises(ValueError, match="trajectory_delta_note"):
            VariantAggregate(
                variant="lex", n=1, success_rate=1.0, mean_retries=0.0,
                mean_total_tokens=0.0, mean_repeated_reads=0.0, stale_detections=0,
                trajectory_delta_note="unknown",
            )

    def test_delta_fields_nullable(self) -> None:
        a = self._make()
        d = a.to_dict()
        assert d["vs_baseline_correctness_delta"] is None
        assert d["vs_baseline_tokens_delta"] is None

    def test_delta_fields_non_null_for_non_baseline(self) -> None:
        a = VariantAggregate(
            variant="lex", n=3, success_rate=0.9, mean_retries=0.2,
            mean_total_tokens=4000.0, mean_repeated_reads=0.8, stale_detections=0,
            vs_baseline_correctness_delta=0.1, vs_baseline_tokens_delta=-500.0,
            trajectory_delta_note="tie",
        )
        d = a.to_dict()
        rt = VariantAggregate.from_dict(d)
        assert rt.vs_baseline_correctness_delta is not None
        assert abs(rt.vs_baseline_correctness_delta - 0.1) < 1e-6


# ---------------------------------------------------------------------------
# GE5 — SweepFinding
# ---------------------------------------------------------------------------


class TestGe5SweepFinding:
    def test_round_trip(self) -> None:
        f = SweepFinding(
            severity="critical",
            location="src/utils.py:L42",
            detail="Contract 'never returns None' — return None found",
            variant="lie",
        )
        rt = SweepFinding.from_dict(f.to_dict())
        assert rt.severity == "critical"
        assert rt.location == "src/utils.py:L42"
        assert rt.variant == "lie"

    def test_warning_severity_accepted(self) -> None:
        f = SweepFinding(severity="warning", location="L1", detail="d", variant="inline")
        assert f.severity == "warning"

    def test_invalid_severity(self) -> None:
        with pytest.raises(ValueError, match="severity"):
            SweepFinding(severity="error", location="L1", detail="d", variant="lex")

    def test_invalid_variant(self) -> None:
        with pytest.raises(ValueError, match="variant"):
            SweepFinding(severity="warning", location="L1", detail="d", variant="unknown")

    def test_frozen(self) -> None:
        f = SweepFinding(severity="warning", location="L1", detail="d", variant="min")
        with pytest.raises((AttributeError, TypeError)):
            f.severity = "critical"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# GE6 — GraceReport
# ---------------------------------------------------------------------------


class TestGe6GraceReport:
    def _make(self) -> GraceReport:
        agg = VariantAggregate(
            variant="baseline", n=3, success_rate=0.67, mean_retries=0.5,
            mean_total_tokens=5000.0, mean_repeated_reads=1.0, stale_detections=0,
        )
        finding = SweepFinding(
            severity="critical", location="src/x.py:L10",
            detail="stale anchor", variant="lie",
        )
        return GraceReport(
            fixture_id="off-by-one",
            generated_at="2026-07-18T12:00:00Z",
            aggregates=[agg],
            sweep_findings=[finding],
        )

    def test_round_trip(self) -> None:
        r = self._make()
        rt = GraceReport.from_dict(r.to_dict())
        assert rt.fixture_id == "off-by-one"
        assert rt.generated_at == "2026-07-18T12:00:00Z"
        assert len(rt.aggregates) == 1
        assert len(rt.sweep_findings) == 1

    def test_json_serialisable(self) -> None:
        r = self._make()
        data = json.loads(json.dumps(r.to_dict()))
        rt = GraceReport.from_dict(data)
        assert rt.fixture_id == "off-by-one"

    def test_aggregate_for_helper(self) -> None:
        r = self._make()
        a = r.aggregate_for("baseline")
        assert a is not None
        assert a.variant == "baseline"
        assert r.aggregate_for("lex") is None

    def test_n_sweep_findings(self) -> None:
        r = self._make()
        assert r.n_sweep_findings == 1

    def test_n_stale_detections(self) -> None:
        r = self._make()
        assert r.n_stale_detections == 0

    def test_schema_version_preserved(self) -> None:
        r = self._make()
        d = r.to_dict()
        assert d["schema_version"] == "1.0"
        rt = GraceReport.from_dict(d)
        assert rt.schema_version == "1.0"

    def test_empty_aggregates_and_findings(self) -> None:
        r = GraceReport(
            fixture_id="x", generated_at="2026-01-01T00:00:00Z", aggregates=[]
        )
        assert r.n_sweep_findings == 0
        assert r.n_stale_detections == 0
        rt = GraceReport.from_dict(r.to_dict())
        assert rt.aggregates == []


# ---------------------------------------------------------------------------
# GE7 — make_run_id
# ---------------------------------------------------------------------------


class TestGe7MakeRunId:
    def test_format(self) -> None:
        rid = make_run_id("off-by-one", "lex", 2)
        assert rid == "off-by-one-lex-r2"

    def test_deterministic(self) -> None:
        assert make_run_id("f", "baseline", 0) == make_run_id("f", "baseline", 0)

    def test_unique_across_variants(self) -> None:
        ids = {make_run_id("fix", v, 0) for v in VARIANT_NAMES}
        assert len(ids) == len(VARIANT_NAMES)

    def test_unique_across_runs(self) -> None:
        ids = {make_run_id("fix", "lex", r) for r in range(5)}
        assert len(ids) == 5

    def test_special_chars_slugified(self) -> None:
        rid = make_run_id("my fixture/test", "min", 1)
        assert "/" not in rid
        assert "min" in rid
        assert "r1" in rid


# ---------------------------------------------------------------------------
# GE8 — aggregate_runs basic stats
# ---------------------------------------------------------------------------


class TestGe8AggregateRuns:
    def _records(self, successes: list[bool], variant: str = "baseline") -> list[VariantRunRecord]:
        return [
            VariantRunRecord(
                run_id=make_run_id("f", variant, i),
                fixture_id="f",
                variant=variant,
                success=s,
                retry_count=1 if not s else 0,
                total_tokens=4000 + i * 100,
                output_tokens=500,
                repeated_reads=1,
            )
            for i, s in enumerate(successes)
        ]

    def test_success_rate(self) -> None:
        recs = self._records([True, True, False, True, False])
        agg = aggregate_runs(recs)
        assert abs(agg.success_rate - 0.6) < 1e-6

    def test_mean_retries(self) -> None:
        recs = self._records([True, False])
        agg = aggregate_runs(recs)
        assert abs(agg.mean_retries - 0.5) < 1e-6

    def test_n(self) -> None:
        recs = self._records([True, True, True])
        agg = aggregate_runs(recs)
        assert agg.n == 3

    def test_mean_total_tokens(self) -> None:
        recs = self._records([True, True])
        # tokens: 4000, 4100
        agg = aggregate_runs(recs)
        assert abs(agg.mean_total_tokens - 4050.0) < 1e-6

    def test_all_success(self) -> None:
        recs = self._records([True, True, True])
        agg = aggregate_runs(recs)
        assert agg.success_rate == 1.0

    def test_all_failure(self) -> None:
        recs = self._records([False, False])
        agg = aggregate_runs(recs)
        assert agg.success_rate == 0.0

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one"):
            aggregate_runs([])

    def test_mixed_variants_raises(self) -> None:
        r1 = VariantRunRecord(run_id="a", fixture_id="f", variant="baseline", success=True)
        r2 = VariantRunRecord(run_id="b", fixture_id="f", variant="lex", success=True)
        with pytest.raises(ValueError, match="mixed variants"):
            aggregate_runs([r1, r2])

    def test_stale_detections_counted(self) -> None:
        recs = [
            VariantRunRecord(run_id=f"x-lie-r{i}", fixture_id="x", variant="lie",
                             success=False, stale_detection=(i % 2 == 0))
            for i in range(4)
        ]
        agg = aggregate_runs(recs)
        assert agg.stale_detections == 2

    def test_baseline_note_is_no_baseline(self) -> None:
        recs = self._records([True, True])
        agg = aggregate_runs(recs)
        assert agg.trajectory_delta_note == "no_baseline"
        assert agg.vs_baseline_correctness_delta is None


# ---------------------------------------------------------------------------
# GE9 — aggregate_runs baseline delta
# ---------------------------------------------------------------------------


class TestGe9BaselineDelta:
    def _baseline(self, success_rate: float, tokens: float) -> VariantAggregate:
        return VariantAggregate(
            variant="baseline", n=4,
            success_rate=success_rate, mean_retries=0.0,
            mean_total_tokens=tokens, mean_repeated_reads=0.0,
            stale_detections=0,
        )

    def _records(self, variant: str, successes: list[bool], token_base: int = 4000) -> list[VariantRunRecord]:
        return [
            VariantRunRecord(
                run_id=make_run_id("f", variant, i),
                fixture_id="f",
                variant=variant,
                success=s,
                total_tokens=token_base,
            )
            for i, s in enumerate(successes)
        ]

    def test_correctness_delta_positive(self) -> None:
        base = self._baseline(0.5, 4000.0)
        recs = self._records("lex", [True, True, True, True])
        agg = aggregate_runs(recs, baseline_agg=base)
        assert agg.vs_baseline_correctness_delta is not None
        assert abs(agg.vs_baseline_correctness_delta - 0.5) < 1e-4

    def test_correctness_delta_negative(self) -> None:
        base = self._baseline(1.0, 4000.0)
        recs = self._records("lie", [True, False, False, False])
        agg = aggregate_runs(recs, baseline_agg=base)
        assert agg.vs_baseline_correctness_delta is not None
        assert agg.vs_baseline_correctness_delta < 0

    def test_token_tie_note(self) -> None:
        base = self._baseline(0.8, 4000.0)
        recs = self._records("inline", [True, True, True, True], token_base=4200)
        agg = aggregate_runs(recs, baseline_agg=base)
        # delta is 200 tokens -> tie band (< 500)
        assert agg.trajectory_delta_note == "tie"

    def test_token_improvement_note(self) -> None:
        base = self._baseline(0.8, 6500.0)
        recs = self._records("min", [True, True, True, True], token_base=4000)
        agg = aggregate_runs(recs, baseline_agg=base)
        # delta is -2500 tokens -> improvement (saved tokens)
        assert agg.trajectory_delta_note == "improvement"

    def test_token_regression_note(self) -> None:
        base = self._baseline(0.8, 4000.0)
        recs = self._records("inj", [True, True, True, True], token_base=7000)
        agg = aggregate_runs(recs, baseline_agg=base)
        # delta is +3000 tokens -> regression
        assert agg.trajectory_delta_note == "regression"

    def test_no_baseline_passed_baseline_variant(self) -> None:
        recs = self._records("baseline", [True, True])
        agg = aggregate_runs(recs, baseline_agg=None)
        assert agg.trajectory_delta_note == "no_baseline"
        assert agg.vs_baseline_correctness_delta is None
