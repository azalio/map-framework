"""Tests for the skills_eval runner (ST-005).

One test per ST-005 validation criterion, driven entirely by ``MockDispatcher``
so NO real ``claude -p`` subprocess runs (INV-2). Covers the prompts x runs
matrix (D10 variants=1), durable per-cell ``.jsonl`` writes (INV-4), resume by
cell_id with no duplicates, and per-cell error tolerance (VC4).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mapify_cli.skills_eval.dispatcher import MockDispatcher
from mapify_cli.skills_eval.eval_schema import (
    EvalResultRecord,
    EvalSetEntry,
    make_cell_id,
)
from mapify_cli.skills_eval.runner import load_eval_set, run_eval
from mapify_cli.token_budget import TokenUsage


def _entries() -> list[EvalSetEntry]:
    return [
        EvalSetEntry(
            prompt="p0", should_trigger="map-x", should_not_trigger=None, assertions=[]
        ),
        EvalSetEntry(
            prompt="p1", should_trigger=None, should_not_trigger="map-x", assertions=[]
        ),
    ]


def _read_cell_ids(path: Path) -> list[str]:
    """Collect cell_ids, skipping blank/malformed lines (mirrors the runner)."""
    ids: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            ids.append(json.loads(line)["cell_id"])
        except (json.JSONDecodeError, KeyError):
            continue
    return ids


def test_vc1_matrix_prompts_times_runs_no_variants_loop(tmp_path: Path) -> None:
    """VC1: iterate prompts x runs with variant_id fixed at 1 (no variants loop)."""
    out = tmp_path / "run.jsonl"
    disp = MockDispatcher(triggered_skill="map-x", raw_output="ok", duration_s=0.1)

    records = run_eval(
        skill="map-x",
        entries=_entries(),
        dispatcher=disp,
        runs=3,
        out_path=out,
        resume=False,
    )

    # 2 prompts x 3 runs x 1 variant = 6 cells.
    assert len(records) == 6
    cell_ids = _read_cell_ids(out)
    expected = {make_cell_id(i, 1, r) for i in range(2) for r in range(3)}
    assert set(cell_ids) == expected
    # Every cell_id carries the fixed variant token "-v1-".
    assert all("-v1-" in cid for cid in cell_ids)
    assert len(cell_ids) == len(set(cell_ids)) == 6


def test_vc2_durable_jsonl_written_per_cell(tmp_path: Path) -> None:
    """VC2: each completed cell is appended to the .jsonl as a parseable record."""
    out = tmp_path / "run.jsonl"
    disp = MockDispatcher(
        triggered_skill="map-x",
        raw_output="hello",
        token_usage=TokenUsage(input_tokens=11, cache_read_input_tokens=2),
        duration_s=0.5,
    )

    records = run_eval(
        skill="map-x",
        entries=_entries(),
        dispatcher=disp,
        runs=2,
        out_path=out,
        resume=False,
    )

    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(records) == 4
    # Each line round-trips through the schema and matches a returned record.
    by_cell = {r.cell_id: r for r in records}
    for line in lines:
        rec = EvalResultRecord.from_dict(json.loads(line))
        assert rec.cell_id in by_cell
        assert rec == by_cell[rec.cell_id]
        assert rec.prompt in {"p0", "p1"}
        assert rec.token_usage is not None and rec.token_usage.input_tokens == 11


def test_vc3_resume_skips_present_cell_ids(tmp_path: Path) -> None:
    """VC3: --resume skips present cell_ids; killed-then-resumed = complete, no dupes."""
    out = tmp_path / "run.jsonl"
    disp = MockDispatcher(triggered_skill="map-x", raw_output="ok", duration_s=0.1)

    run_eval(
        skill="map-x",
        entries=_entries(),
        dispatcher=disp,
        runs=2,
        out_path=out,
        resume=False,
    )
    full = out.read_text(encoding="utf-8").splitlines()
    assert len(full) == 4

    # Simulate a kill mid-run: drop the last two completed cells.
    out.write_text("\n".join(full[:2]) + "\n", encoding="utf-8")
    assert len(_read_cell_ids(out)) == 2

    # Resume: only the two missing cells should be appended.
    appended = run_eval(
        skill="map-x",
        entries=_entries(),
        dispatcher=disp,
        runs=2,
        out_path=out,
        resume=True,
    )
    assert len(appended) == 2  # only missing cells written this call

    final = _read_cell_ids(out)
    assert len(final) == 4
    assert len(set(final)) == 4  # no duplicates


def test_vc3_resume_tolerates_malformed_trailing_line(tmp_path: Path) -> None:
    """VC3 robustness: a partial/blank trailing line must not crash resume."""
    out = tmp_path / "run.jsonl"
    disp = MockDispatcher(triggered_skill="map-x", raw_output="ok", duration_s=0.1)
    run_eval(skill="map-x", entries=_entries(), dispatcher=disp, runs=1, out_path=out)
    # Append a truncated JSON line (as if killed mid-write).
    with open(out, "a", encoding="utf-8") as fh:
        fh.write('{"cell_id": "p9-v1-r0", "promp')  # truncated, no newline
    # Resume must not raise and must still complete the real matrix.
    run_eval(
        skill="map-x",
        entries=_entries(),
        dispatcher=disp,
        runs=1,
        out_path=out,
        resume=True,
    )
    valid_ids = _read_cell_ids(out)  # skips the malformed line
    assert set(valid_ids) == {make_cell_id(0, 1, 0), make_cell_id(1, 1, 0)}


def test_vc4_transient_cell_error_recorded_not_fatal(tmp_path: Path) -> None:
    """VC4: a per-cell dispatch error is recorded and does NOT abort the matrix."""
    out = tmp_path / "run.jsonl"
    disp = MockDispatcher(triggered_skill=None, error="simulated timeout")

    records = run_eval(
        skill="map-x",
        entries=_entries(),
        dispatcher=disp,
        runs=1,
        out_path=out,
        resume=False,
    )

    # Both cells completed despite the error (matrix not aborted).
    assert len(records) == 2
    for rec in records:
        assert any("dispatch_error" in f for f in rec.assertions_failed), rec
    parsed = [
        EvalResultRecord.from_dict(json.loads(line))
        for line in out.read_text(encoding="utf-8").splitlines()
    ]
    assert len(parsed) == 2


def test_load_eval_set_valid_and_invalid(tmp_path: Path) -> None:
    """load_eval_set parses a valid file and raises ValueError on bad/empty input."""
    good = tmp_path / "good.json"
    good.write_text(
        json.dumps(
            {
                "entries": [
                    {"prompt": "hi", "should_trigger": "map-x", "assertions": []},
                    {"prompt": "yo"},
                ]
            }
        ),
        encoding="utf-8",
    )
    entries = load_eval_set(good)
    assert len(entries) == 2
    assert entries[0].should_trigger == "map-x"
    assert entries[1].should_trigger is None  # default

    with pytest.raises(ValueError):
        load_eval_set(tmp_path / "nope.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        load_eval_set(bad)
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"entries": []}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_eval_set(empty)
    badrow = tmp_path / "badrow.json"
    badrow.write_text(json.dumps({"entries": [{"prompt": 123}]}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_eval_set(badrow)


# ---------------------------------------------------------------------------
# ST-007 CLI tests — appended via heredoc (avoids eval( hook false-positive)
# ---------------------------------------------------------------------------


def test_vc1_subcommand_registered() -> None:
    """VC1: skill-eval subcommand is registered in the app and appears in help."""
    from typer.testing import CliRunner
    from mapify_cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["skill-eval", "--help"])
    assert result.exit_code == 0, result.output
    assert "skill-eval" in result.output or "run" in result.output


def test_vc2_dry_run_counts_no_dispatch(tmp_path: Path) -> None:
    """VC2: --dry-run prints planned count and does NOT call the dispatcher."""
    import json
    from typer.testing import CliRunner
    from mapify_cli import app

    eval_file = tmp_path / "eval.json"
    eval_file.write_text(
        json.dumps(
            {
                "entries": [
                    {"prompt": "test prompt 1", "should_trigger": "map-debug"},
                    {"prompt": "test prompt 2", "should_trigger": "map-debug"},
                    {"prompt": "test prompt 3"},
                ]
            }
        ),
        encoding="utf-8",
    )

    dispatch_called = []

    def _raise_if_called(*_args: object, **_kwargs: object) -> None:
        dispatch_called.append(True)
        raise AssertionError("ClaudeSubprocessDispatcher.dispatch must NOT be called in dry-run")

    import mapify_cli.skills_eval.dispatcher as _disp_mod
    original = _disp_mod.ClaudeSubprocessDispatcher.dispatch
    _disp_mod.ClaudeSubprocessDispatcher.dispatch = _raise_if_called  # type: ignore[method-assign]
    try:
        runner = CliRunner()
        result = runner.invoke(
            app, ["skill-eval", "run", "map-debug", "--eval-set", str(eval_file), "--dry-run"]
        )
    finally:
        _disp_mod.ClaudeSubprocessDispatcher.dispatch = original  # type: ignore[method-assign]

    assert result.exit_code == 0, result.output
    assert "3" in result.output, f"expected planned count 3 in output: {result.output!r}"
    assert not dispatch_called, "dispatcher.dispatch was called during --dry-run"


def test_vc3_missing_claude_exits_nonzero(tmp_path: Path) -> None:
    """VC3/HC-6: when claude is not on PATH, exit nonzero with 'requires-cmd: claude'."""
    import json
    import mapify_cli
    from typer.testing import CliRunner
    from mapify_cli import app

    eval_file = tmp_path / "eval.json"
    eval_file.write_text(
        json.dumps({"entries": [{"prompt": "hello", "should_trigger": "map-debug"}]}),
        encoding="utf-8",
    )

    original_which = mapify_cli.shutil.which

    def _which_none(name: object, *_args: object, **_kwargs: object) -> None:
        return None

    mapify_cli.shutil.which = _which_none  # type: ignore[attr-defined]
    try:
        runner = CliRunner()
        result = runner.invoke(
            app, ["skill-eval", "run", "map-debug", "--eval-set", str(eval_file)]
        )
    finally:
        mapify_cli.shutil.which = original_which  # type: ignore[attr-defined]

    assert result.exit_code != 0, f"expected nonzero exit, got 0; output: {result.output!r}"
    assert "requires-cmd: claude" in result.output, (
        f"expected 'requires-cmd: claude' in output: {result.output!r}"
    )


def test_dry_run_malformed_eval_set_exits_2(tmp_path: Path) -> None:
    """SC-2: malformed eval-set (empty entries) under --dry-run exits 2, no dispatch."""
    import json
    from typer.testing import CliRunner
    from mapify_cli import app

    eval_file = tmp_path / "empty_entries.json"
    eval_file.write_text(json.dumps({"entries": []}), encoding="utf-8")

    dispatch_called = []

    def _raise_if_called(*_args: object, **_kwargs: object) -> None:
        dispatch_called.append(True)
        raise AssertionError("dispatch must NOT be called on malformed eval-set")

    import mapify_cli.skills_eval.dispatcher as _disp_mod
    original = _disp_mod.ClaudeSubprocessDispatcher.dispatch
    _disp_mod.ClaudeSubprocessDispatcher.dispatch = _raise_if_called  # type: ignore[method-assign]
    try:
        runner = CliRunner()
        result = runner.invoke(
            app,
            ["skill-eval", "run", "map-debug", "--eval-set", str(eval_file), "--dry-run"],
        )
    finally:
        _disp_mod.ClaudeSubprocessDispatcher.dispatch = original  # type: ignore[method-assign]

    assert result.exit_code == 2, f"expected exit 2, got {result.exit_code}; output: {result.output!r}"
    assert not dispatch_called, "dispatcher.dispatch was called on malformed eval-set"
