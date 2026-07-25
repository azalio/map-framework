"""Tests for skills_eval aggregator (ST-006).

Covers aggregate() and bounded_run() using MockDispatcher only -- zero real
claude subprocess (INV-2/INV-3).  Tests map 1:1 to validation criteria:
  VC1  -- pass_rate fraction
  VC2  -- token mean/stddev, n<2 no raise
  VC3  -- bounded_run serialised writes: every .jsonl line parses, no corruption
  VC4  -- all-null token_usage -> token stats None, pass_rate + duration still valid
  SC-1 -- max_concurrency=3 matrix -> complete unique cell set; resume -> no dupes
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from mapify_cli.skills_eval.aggregator import aggregate, bounded_run
from mapify_cli.skills_eval.dispatcher import MockDispatcher
from mapify_cli.skills_eval.eval_schema import (
    EvalResultRecord,
    EvalSetEntry,
    make_cell_id,
)
from mapify_cli.token_budget import TokenUsage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _entries(n: int = 2) -> list[EvalSetEntry]:
    return [
        EvalSetEntry(
            prompt=f"p{i}",
            should_trigger=None,
            should_not_trigger=None,
            assertions=[],
        )
        for i in range(n)
    ]


def _read_all_records(path: Path) -> list[EvalResultRecord]:
    """Parse every non-blank line in the .jsonl; raise on malformed."""
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        records.append(EvalResultRecord.from_dict(json.loads(line)))
    return records


def _make_record(
    cell_id: str,
    *,
    assertions_failed: list[str] | None = None,
    token_usage: TokenUsage | None = None,
    duration_s: float = 1.0,
) -> EvalResultRecord:
    return EvalResultRecord(
        cell_id=cell_id,
        prompt="test",
        triggered_skill=None,
        token_usage=token_usage,
        duration_s=duration_s,
        assertions_passed=[],
        assertions_failed=assertions_failed or [],
    )


# ---------------------------------------------------------------------------
# aggregate() -- AggregateSummary correctness
# ---------------------------------------------------------------------------


def test_vc1_pass_rate_fraction() -> None:
    """VC1: pass_rate = passed_cells / total_cells."""
    records = [
        _make_record("p0-v1-r0"),  # passed (empty assertions_failed)
        _make_record("p1-v1-r0", assertions_failed=["x"]),  # failed
        _make_record("p2-v1-r0"),  # passed
        _make_record("p3-v1-r0", assertions_failed=["y", "z"]),  # failed
    ]
    summary = aggregate(records)
    assert summary.total_cells == 4
    assert summary.passed_cells == 2
    assert math.isclose(summary.pass_rate, 0.5)


def test_vc1_all_passed() -> None:
    records = [_make_record(f"p{i}-v1-r0") for i in range(3)]
    summary = aggregate(records)
    assert summary.passed_cells == 3
    assert math.isclose(summary.pass_rate, 1.0)


def test_vc1_all_failed() -> None:
    records = [_make_record(f"p{i}-v1-r0", assertions_failed=["f"]) for i in range(3)]
    summary = aggregate(records)
    assert summary.passed_cells == 0
    assert math.isclose(summary.pass_rate, 0.0)


def test_vc1_empty_list_no_raise() -> None:
    """VC4/VC1: empty list must not raise; pass_rate = 0.0."""
    summary = aggregate([])
    assert summary.total_cells == 0
    assert summary.passed_cells == 0
    assert math.isclose(summary.pass_rate, 0.0)
    assert summary.tokens_mean is None
    assert summary.tokens_stddev is None
    assert summary.duration_mean is None
    assert summary.duration_stddev is None


def test_vc2_token_mean_and_stddev() -> None:
    """VC2: tokens_mean and tokens_stddev correct over non-null token_usage."""
    tu_a = TokenUsage(input_tokens=100, cache_read_input_tokens=0)
    tu_b = TokenUsage(input_tokens=200, cache_read_input_tokens=0)
    tu_c = TokenUsage(input_tokens=300, cache_read_input_tokens=0)
    records = [
        _make_record("p0-v1-r0", token_usage=tu_a, duration_s=1.0),
        _make_record("p1-v1-r0", token_usage=tu_b, duration_s=2.0),
        _make_record("p2-v1-r0", token_usage=tu_c, duration_s=3.0),
    ]
    summary = aggregate(records)
    assert summary.token_sample_size == 3
    assert math.isclose(summary.tokens_mean or 0.0, 200.0)
    # sample stdev of [100, 200, 300]
    import statistics
    expected_stdev = statistics.stdev([100.0, 200.0, 300.0])
    assert math.isclose(summary.tokens_stddev or 0.0, expected_stdev)


def test_vc2_token_n_eq_1_no_raise() -> None:
    """VC2: n<2 must not raise; stddev is 0.0."""
    tu = TokenUsage(input_tokens=50, cache_read_input_tokens=10)
    records = [_make_record("p0-v1-r0", token_usage=tu, duration_s=1.0)]
    summary = aggregate(records)
    assert summary.token_sample_size == 1
    assert math.isclose(summary.tokens_mean or 0.0, 60.0)  # 50+10
    assert summary.tokens_stddev is not None and math.isclose(summary.tokens_stddev, 0.0)


def test_vc4_all_null_token_usage() -> None:
    """VC4: all-null token_usage -> token stats None; pass_rate + duration valid."""
    records = [
        _make_record("p0-v1-r0", token_usage=None, duration_s=1.0),
        _make_record("p1-v1-r0", token_usage=None, duration_s=3.0),
    ]
    summary = aggregate(records)
    # Token stats absent.
    assert summary.token_sample_size == 0
    assert summary.tokens_mean is None
    assert summary.tokens_stddev is None
    # Pass_rate still valid.
    assert math.isclose(summary.pass_rate, 1.0)  # no assertions_failed in either
    # Duration stats still valid.
    assert summary.duration_mean is not None
    assert math.isclose(summary.duration_mean, 2.0)


def test_duration_mean_and_stddev() -> None:
    """duration_mean / duration_stddev correct when total_cells >= 2."""
    records = [
        _make_record("p0-v1-r0", duration_s=1.0),
        _make_record("p1-v1-r0", duration_s=3.0),
    ]
    summary = aggregate(records)
    assert math.isclose(summary.duration_mean or 0.0, 2.0)
    import statistics
    assert math.isclose(summary.duration_stddev or 0.0, statistics.stdev([1.0, 3.0]))


def test_duration_stddev_zero_when_single_record() -> None:
    """duration_stddev is 0.0 for a single record (n<2 guard)."""
    records = [_make_record("p0-v1-r0", duration_s=5.0)]
    summary = aggregate(records)
    assert math.isclose(summary.duration_mean or 0.0, 5.0)
    assert summary.duration_stddev is not None and math.isclose(summary.duration_stddev, 0.0)


def test_aggregate_summary_to_dict() -> None:
    """AggregateSummary.to_dict() returns a JSON-serialisable dict."""
    summary = aggregate([])
    d = summary.to_dict()
    assert isinstance(d, dict)
    # Verify round-trip via json.dumps (raises TypeError on non-serialisable).
    json.dumps(d)
    assert "pass_rate" in d
    assert "total_cells" in d


# ---------------------------------------------------------------------------
# bounded_run() -- SC-1 / VC3 concurrent dispatch
# ---------------------------------------------------------------------------


def test_sc1_max_concurrency_3_complete_unique_cell_set(tmp_path: Path) -> None:
    """SC-1: max_concurrency=3 over a matrix -> complete + unique cell set."""
    out = tmp_path / "run.jsonl"
    disp = MockDispatcher(triggered_skill=None, raw_output="ok", duration_s=0.01)

    entries = _entries(3)
    records = bounded_run(
        skill="map-x",
        entries=entries,
        dispatcher=disp,
        runs=4,
        out_path=out,
        max_concurrency=3,
    )

    # 3 entries x 4 runs = 12 cells total.
    expected_ids = {make_cell_id(i, 1, r) for i in range(3) for r in range(4)}
    returned_ids = {r.cell_id for r in records}
    assert returned_ids == expected_ids

    # Verify .jsonl: every line must parse and cell_id set must match.
    file_records = _read_all_records(out)
    file_ids = {r.cell_id for r in file_records}
    assert file_ids == expected_ids
    assert len(file_records) == 12  # no duplicates


def test_vc3_jsonl_not_corrupted_concurrent(tmp_path: Path) -> None:
    """VC3: concurrent writes produce valid .jsonl -- every line parses."""
    out = tmp_path / "run.jsonl"
    disp = MockDispatcher(triggered_skill=None, raw_output="x" * 200, duration_s=0.01)

    bounded_run(
        skill="map-x",
        entries=_entries(4),
        dispatcher=disp,
        runs=5,
        out_path=out,
        max_concurrency=4,
    )

    raw_lines = [
        ln for ln in out.read_text(encoding="utf-8").splitlines() if ln.strip()
    ]
    assert len(raw_lines) == 20  # 4*5
    for line in raw_lines:
        # Must parse without exception.
        obj = json.loads(line)
        assert "cell_id" in obj


def test_sc1_resume_after_partial_no_dupes(tmp_path: Path) -> None:
    """SC-1: resume after partial run -> no duplicate cell_ids in output."""
    out = tmp_path / "run.jsonl"
    disp = MockDispatcher(triggered_skill=None, raw_output="ok", duration_s=0.01)
    entries = _entries(2)

    # First pass: complete the first entry only (2 cells out of 4).
    first_pass = bounded_run(
        skill="map-x",
        entries=entries,
        dispatcher=disp,
        runs=2,
        out_path=out,
        max_concurrency=1,
    )
    assert len(first_pass) == 4  # 2 entries * 2 runs

    # Simulate partial completion: keep only first 2 lines.
    lines = out.read_text(encoding="utf-8").splitlines()
    out.write_text("\n".join(lines[:2]) + "\n", encoding="utf-8")
    assert len([ln for ln in out.read_text().splitlines() if ln.strip()]) == 2

    # Resume: only missing 2 cells should be added.
    second_pass = bounded_run(
        skill="map-x",
        entries=entries,
        dispatcher=disp,
        runs=2,
        out_path=out,
        resume=True,
        max_concurrency=2,
    )
    assert len(second_pass) == 2  # only the 2 missing cells

    # Final file: 4 unique cell_ids, no duplicates.
    file_records = _read_all_records(out)
    all_ids = [r.cell_id for r in file_records]
    assert len(all_ids) == 4
    assert len(set(all_ids)) == 4  # no duplicates


def test_bounded_run_default_concurrency_1_sequential(tmp_path: Path) -> None:
    """Default max_concurrency=1 produces a correct sequential result."""
    out = tmp_path / "run.jsonl"
    disp = MockDispatcher(triggered_skill=None, raw_output="ok", duration_s=0.0)

    records = bounded_run(
        skill="map-x",
        entries=_entries(2),
        dispatcher=disp,
        runs=3,
        out_path=out,
    )
    assert len(records) == 6
    file_records = _read_all_records(out)
    assert len(file_records) == 6
    assert len({r.cell_id for r in file_records}) == 6


def test_bounded_run_empty_entries(tmp_path: Path) -> None:
    """bounded_run on empty entries list returns [] and creates no file."""
    out = tmp_path / "run.jsonl"
    disp = MockDispatcher(triggered_skill=None, raw_output="ok", duration_s=0.0)

    records = bounded_run(
        skill="map-x",
        entries=[],
        dispatcher=disp,
        runs=5,
        out_path=out,
    )
    assert records == []
    # No file should exist since parent was just mkdir'd and no records were written.
    # (out_path.parent exists but out_path itself was never opened for append.)
    assert not out.exists()
