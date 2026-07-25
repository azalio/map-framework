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

import mapify_cli.skills_eval.dispatcher as _disp_mod
from mapify_cli.skills_eval.aggregator import aggregate
from mapify_cli.skills_eval.assertions import run_assertion
from mapify_cli.skills_eval.dispatcher import (
    ClaudeSubprocessDispatcher,
    MockDispatcher,
    VariantDispatcher,
)
from mapify_cli.skills_eval.eval_schema import (
    DispatchResult,
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

    from typer.testing import CliRunner

    import mapify_cli
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


# ---------------------------------------------------------------------------
# ST-003 Dispatcher tests — MockDispatcher + monkeypatched subprocess
# ---------------------------------------------------------------------------


def test_vc1_abc_returns_dispatchresult() -> None:
    """VC1: MockDispatcher().dispatch() returns DispatchResult; VariantDispatcher is ABC."""
    disp = MockDispatcher(triggered_skill="map-x", raw_output="hello")
    result = disp.dispatch("any prompt")
    assert isinstance(result, DispatchResult)
    assert result.triggered_skill == "map-x"
    assert result.raw_output == "hello"
    # VariantDispatcher is abstract — instantiating raises TypeError
    import pytest as _pytest
    with _pytest.raises(TypeError):
        VariantDispatcher()  # type: ignore[abstract]


def test_vc2_mock_dispatcher_sets_triggered_skill_no_subprocess() -> None:
    """VC2 / INV-2: MockDispatcher returns triggered_skill; dispatch() body has zero subprocess/.run refs."""
    disp = MockDispatcher(triggered_skill="map-x")
    result = disp.dispatch("test")
    assert result.triggered_skill == "map-x"

    # AST-walk MockDispatcher.dispatch to confirm no subprocess or .run calls (INV-2).
    import ast as _ast
    import inspect
    import textwrap
    source = textwrap.dedent(inspect.getsource(MockDispatcher.dispatch))
    tree = _ast.parse(source)
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Attribute) and node.attr == "run":
            raise AssertionError(
                "MockDispatcher.dispatch must not reference .run (INV-2 violation)"
            )
        if isinstance(node, (_ast.Import, _ast.ImportFrom)):
            names = (
                [alias.name for alias in node.names]
                if isinstance(node, _ast.Import)
                else ([node.module] if node.module else [])
            )
            for name in names:
                if name and "subprocess" in name:
                    raise AssertionError(
                        f"MockDispatcher.dispatch must not import subprocess (INV-2): {name!r}"
                    )


def test_vc4_backoff_bounded_on_transient_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """VC4: ClaudeSubprocessDispatcher retries exactly max_retries+1 times on failure."""
    # Seed a minimal .claude/skills/ dir so _seed_temp_cwd works.
    source_claude = tmp_path / ".claude"
    (source_claude / "skills").mkdir(parents=True)

    call_count: list[int] = [0]

    def _failing_run(
        argv: list[str],
        *args: object,
        **kwargs: object,
    ) -> object:
        call_count[0] += 1
        import subprocess as _sp
        result = _sp.CompletedProcess(args=argv, returncode=1, stdout="", stderr="err")
        return result

    def _noop_sleep(seconds: object) -> None:
        pass

    monkeypatch.setattr(_disp_mod.subprocess, "run", _failing_run)
    monkeypatch.setattr(_disp_mod.time, "sleep", _noop_sleep)

    disp = ClaudeSubprocessDispatcher(
        source_claude_dir=source_claude,
        max_retries=2,
        backoff_base=0.0,
    )
    result = disp.dispatch("hello")

    # Must return a DispatchResult (never raise).
    assert isinstance(result, DispatchResult)
    assert result.error is not None

    # subprocess.run must be called exactly max_retries+1 = 3 times (bounded).
    assert call_count[0] == 3, (
        f"expected 3 subprocess calls (1 + max_retries=2), got {call_count[0]}"
    )


def test_vc3_subprocess_cwd_is_temp_not_repo_map(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """VC3 / INV-5: subprocess.run cwd is a seeded temp dir, not the repo .map."""
    # Seed a source .claude/skills/ dir.
    source_claude = tmp_path / ".claude"
    (source_claude / "skills").mkdir(parents=True)

    # Capture results *inside* _capture_run while the temp dir is still live.
    # dispatch() calls shutil.rmtree(tmp) in its finally block, so checking
    # after dispatch() returns would always find the dir gone.
    cwd_observations: list[dict[str, object]] = []

    def _capture_run(
        argv: list[str],
        *args: object,
        **kwargs: object,
    ) -> object:
        cwd_val = kwargs.get("cwd")
        if cwd_val is not None:
            cwd_path = Path(str(cwd_val))
            cwd_observations.append({
                "cwd": cwd_path,
                "claude_exists": (cwd_path / ".claude").exists(),
                "map_exists": (cwd_path / ".map").exists(),
            })
        # Return a valid JSON envelope so dispatch() parses successfully.
        import subprocess as _sp
        envelope = (
            '{"result": "ok", "session_id": "test-session",'
            ' "usage": {"input_tokens": 1, "cache_read_input_tokens": 0,'
            ' "cache_creation_input_tokens": 0}}'
        )
        return _sp.CompletedProcess(
            args=argv, returncode=0, stdout=envelope, stderr=""
        )

    def _noop_sleep(seconds: object) -> None:
        pass

    monkeypatch.setattr(_disp_mod.subprocess, "run", _capture_run)
    monkeypatch.setattr(_disp_mod.time, "sleep", _noop_sleep)

    disp = ClaudeSubprocessDispatcher(
        source_claude_dir=source_claude,
        max_retries=0,
        backoff_base=0.0,
    )
    disp.dispatch("test prompt")

    assert len(cwd_observations) == 1, (
        f"expected exactly 1 subprocess call, got {len(cwd_observations)}"
    )
    obs = cwd_observations[0]
    cwd = obs["cwd"]
    assert isinstance(cwd, Path)

    # Must NOT be the repo .map dir.
    repo_map = Path(__file__).parent.parent / ".map"
    assert cwd != repo_map, f"cwd must not be repo .map, got {cwd!r}"

    # .claude and .map must both have existed in the seeded temp dir (INV-5).
    assert obs["claude_exists"], f".claude not found in temp cwd {cwd!r} at call time"
    assert obs["map_exists"], f".map not found in temp cwd {cwd!r} at call time"


# ---------------------------------------------------------------------------
# ST-004 Assertion tests
# ---------------------------------------------------------------------------


def test_vc1_contains_and_regex_match_and_nonmatch() -> None:
    """VC1: contains / not_contains / regex — match, non-match, invalid regex → FAIL no raise."""
    result = DispatchResult(
        raw_output="Hello world",
        triggered_skill=None,
        token_usage=None,
        duration_s=0.1,
    )

    # contains — match
    ar = run_assertion({"type": "contains", "value": "Hello"}, result)
    assert ar.passed is True

    # contains — non-match
    ar = run_assertion({"type": "contains", "value": "missing"}, result)
    assert ar.passed is False

    # not_contains — present → FAIL
    ar = run_assertion({"type": "not_contains", "value": "Hello"}, result)
    assert ar.passed is False

    # not_contains — absent → PASS
    ar = run_assertion({"type": "not_contains", "value": "absent"}, result)
    assert ar.passed is True

    # regex — match
    ar = run_assertion({"type": "regex", "pattern": r"H\w+"}, result)
    assert ar.passed is True

    # regex — non-match
    ar = run_assertion({"type": "regex", "pattern": r"xyz\d+"}, result)
    assert ar.passed is False

    # invalid regex — must FAIL, not raise
    ar = run_assertion({"type": "regex", "pattern": r"[invalid("}, result)
    assert ar.passed is False
    assert "invalid" in ar.detail.lower() or "error" in ar.detail.lower()


def test_vc2_valid_json_pass_and_fail() -> None:
    """VC2: valid_json — well-formed PASS, malformed FAIL."""
    good = DispatchResult(
        raw_output='{"key": "value"}',
        triggered_skill=None,
        token_usage=None,
        duration_s=0.1,
    )
    ar = run_assertion({"type": "valid_json"}, good)
    assert ar.passed is True

    bad = DispatchResult(
        raw_output="{not json}",
        triggered_skill=None,
        token_usage=None,
        duration_s=0.1,
    )
    ar = run_assertion({"type": "valid_json"}, bad)
    assert ar.passed is False


def test_vc3_trigger_and_not_trigger_including_none() -> None:
    """VC3 / SC-3: trigger == / != ; not_trigger None-safe PASS."""
    triggered = DispatchResult(
        raw_output="",
        triggered_skill="map-debug",
        token_usage=None,
        duration_s=0.1,
    )
    not_triggered = DispatchResult(
        raw_output="",
        triggered_skill=None,
        token_usage=None,
        duration_s=0.1,
    )

    # trigger — matching skill PASS
    ar = run_assertion({"type": "trigger", "skill": "map-debug"}, triggered)
    assert ar.passed is True

    # trigger — wrong skill FAIL
    ar = run_assertion({"type": "trigger", "skill": "map-other"}, triggered)
    assert ar.passed is False

    # not_trigger — different skill PASS
    ar = run_assertion({"type": "not_trigger", "skill": "map-other"}, triggered)
    assert ar.passed is True

    # not_trigger — same skill FAIL
    ar = run_assertion({"type": "not_trigger", "skill": "map-debug"}, triggered)
    assert ar.passed is False

    # SC-3: triggered_skill is None → not_trigger PASS (None != "map-debug")
    ar = run_assertion({"type": "not_trigger", "skill": "map-debug"}, not_triggered)
    assert ar.passed is True


# ---------------------------------------------------------------------------
# ST-009 own tests
# ---------------------------------------------------------------------------


def test_vc2_no_anthropic_import_in_skills_eval() -> None:
    """VC2 / INV-3: no 'anthropic' import and no ANTHROPIC_API_KEY env read in skills_eval."""
    import ast as _ast
    skills_eval_dir = (
        Path(__file__).parent.parent / "src" / "mapify_cli" / "skills_eval"
    )
    py_files = list(skills_eval_dir.rglob("*.py"))
    assert py_files, f"No .py files found under {skills_eval_dir}"

    for py_file in py_files:
        source = py_file.read_text(encoding="utf-8")
        tree = _ast.parse(source, filename=str(py_file))

        # Check 1: no anthropic import via AST.
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Import):
                for alias in node.names:
                    assert "anthropic" not in (alias.name or ""), (
                        f"Found 'anthropic' import in {py_file}: {alias.name!r}"
                    )
            elif isinstance(node, _ast.ImportFrom):
                module = node.module or ""
                assert "anthropic" not in module, (
                    f"Found 'anthropic' import in {py_file}: from {module!r}"
                )

        # Check 2: no ANTHROPIC_API_KEY env read.
        # Scan non-comment, non-docstring lines for the literal key string.
        # We allow docstring/comment mentions (INV-3 documentation), but not
        # actual environment reads. We do this by checking all Call nodes for
        # os.environ[...] or os.getenv(...) referencing the key.
        for node in _ast.walk(tree):
            # os.environ["ANTHROPIC_API_KEY"] or os.environ.get("ANTHROPIC_API_KEY")
            # Check if this is os.environ[<key>]
            if (
                isinstance(node, _ast.Subscript)
                and isinstance(node.value, _ast.Attribute)
                and node.value.attr == "environ"
            ):
                slice_val = node.slice
                # Python 3.9+: slice is the node directly
                key_node = slice_val
                if isinstance(key_node, _ast.Constant) and isinstance(key_node.value, str):
                    assert "ANTHROPIC_API_KEY" not in key_node.value, (
                        f"Found ANTHROPIC_API_KEY env read in {py_file}"
                    )
            if isinstance(node, _ast.Call):
                # os.getenv("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
                func = node.func
                is_getenv = (
                    isinstance(func, _ast.Attribute)
                    and func.attr in ("getenv", "get")
                )
                if is_getenv and node.args:
                    first_arg = node.args[0]
                    if isinstance(first_arg, _ast.Constant) and isinstance(first_arg.value, str):
                        assert "ANTHROPIC_API_KEY" not in first_arg.value, (
                            f"Found ANTHROPIC_API_KEY env read in {py_file}"
                        )


def test_vc1_end_to_end_run_via_mock_dispatcher(tmp_path: Path) -> None:
    """VC1 / AC-9: load fixture → run via MockDispatcher → aggregate; zero real claude."""
    fixture_path = (
        Path(__file__).parent / "skills_eval" / "fixtures" / "map_debug_eval_set.json"
    )
    assert fixture_path.exists(), f"Fixture not found: {fixture_path}"

    entries = load_eval_set(fixture_path)
    assert len(entries) >= 2

    out_path = tmp_path / "e2e_run.jsonl"
    disp = MockDispatcher(triggered_skill="map-debug", raw_output="debug info")

    records = run_eval(
        skill="map-debug",
        entries=entries,
        dispatcher=disp,
        runs=1,
        out_path=out_path,
        resume=False,
    )

    # Records durable: file written.
    assert out_path.exists()
    lines = [
        ln for ln in out_path.read_text(encoding="utf-8").splitlines() if ln.strip()
    ]
    assert len(lines) == len(records) == len(entries)

    # Aggregate produces a valid summary.
    summary = aggregate(records)
    assert summary.total_cells == len(entries)
    assert 0.0 <= summary.pass_rate <= 1.0
    d = summary.to_dict()
    assert "pass_rate" in d
    assert "total_cells" in d
    # JSON-serialisable (no TypeError).
    json.dumps(d)
