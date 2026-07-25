"""Tests for `skill-eval optimize` and `skill-eval view` CLI commands (ST-005).

Validation criteria covered:
- VC1: `optimize --dry-run` prints budget + model line, exits 0, no dispatcher constructed.
- VC2: eval-set with < 5 entries exits 2 with ">= 5" message, BEFORE any dispatcher.
- VC3: claude absent -> exit 1 with "requires-cmd: claude" before any work.
- VC4: full run writes *-optimize.json + *-optimize.html; `view` renders from stored result.
- VC5: --open with a raising webbrowser does NOT error the run (exit stays 0).
- VC6: full run (no --apply) modifies NOTHING outside .map/; apply_patcher never invoked.

All tests use MockDispatcher + mock proposer — no real claude invocation (INV-2).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from mapify_cli import app
from mapify_cli.skills_eval.dispatcher import MockDispatcher
from mapify_cli.token_budget import TokenUsage

runner = CliRunner()

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_SKILL = "test-skill"


def _which_present(_cmd: object) -> str:
    """shutil.which stub: pretend the requested command is on PATH."""
    del _cmd
    return "/usr/bin/claude"


def _which_absent(_cmd: object) -> None:
    """shutil.which stub: pretend the requested command is NOT on PATH."""
    del _cmd


def _raise_no_browser(_url: object) -> None:
    """webbrowser.open stub that raises — proves --open swallows the error (SC-2)."""
    del _url
    raise OSError("no browser")


_VALID_FRONTMATTER = """\
---
name: test-skill
description: "A test skill for optimize CLI tests"
triggers:
  - test trigger phrase
---
Skill body.
"""


def _make_eval_set(tmp_path: Path, n: int, skill: str = _SKILL) -> Path:
    """Write a minimal eval-set JSON with *n* entries to tmp_path."""
    entries = [
        {"prompt": f"prompt {i}", "should_trigger": skill}
        for i in range(n)
    ]
    p = tmp_path / "eval_set.json"
    p.write_text(json.dumps({"entries": entries}), encoding="utf-8")
    return p


def _make_claude_dir(tmp_path: Path, skill: str = _SKILL) -> Path:
    """Create a minimal .claude/skills/<skill>/SKILL.md tree under tmp_path."""
    skill_dir = tmp_path / ".claude" / "skills" / skill
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(_VALID_FRONTMATTER, encoding="utf-8")
    return tmp_path / ".claude"


def _mock_dispatcher_factory(skill: str = _SKILL) -> Any:
    """Return a MockDispatcher factory callable that ignores source_claude_dir."""

    class _FactoryMock(MockDispatcher):
        def __init__(self, source_claude_dir: Path | None = None, **_kw: Any) -> None:
            del source_claude_dir, _kw  # intentionally unused in mock
            super().__init__(
                triggered_skill=skill,
                token_usage=TokenUsage(
                    input_tokens=10,
                    cache_read_input_tokens=0,
                    cache_creation_input_tokens=0,
                ),
                duration_s=0.01,
            )

    return _FactoryMock


def _mock_proposer(current_description: str, failing_records: object) -> str:
    del current_description, failing_records  # intentionally unused in mock
    return "improved candidate description"


# ---------------------------------------------------------------------------
# VC1: dry-run prints budget + model line, exits 0, NO dispatcher constructed
# ---------------------------------------------------------------------------


def test_vc1_dry_run_prints_budget_and_exits_0(tmp_path: Path) -> None:
    """VC1: --dry-run prints dispatch count + proposer count + model line; exit 0."""
    eval_set = _make_eval_set(tmp_path, n=5)

    result = runner.invoke(
        app,
        [
            "skill-eval", "optimize", _SKILL,
            "--eval-set", str(eval_set),
            "--dry-run",
        ],
    )

    assert result.exit_code == 0, f"Expected exit 0, got {result.exit_code}.\nOutput:\n{result.stdout}"
    # Budget line: "5 x (N+M) = K dispatch calls + 5 proposer calls"
    assert "dispatch calls" in result.stdout, f"Missing budget line.\nOutput:\n{result.stdout}"
    assert "proposer calls" in result.stdout, f"Missing proposer call count.\nOutput:\n{result.stdout}"
    assert "model: default" in result.stdout, f"Missing model line.\nOutput:\n{result.stdout}"


def test_vc1_dry_run_with_5_entries_budget_numbers(tmp_path: Path) -> None:
    """VC1: with 5 entries and iterations=3, budget numbers must be consistent."""
    from mapify_cli.skills_eval.description_optimizer import (
        _DEFAULT_SEED,
        split_train_test,
    )
    from mapify_cli.skills_eval.runner import load_eval_set

    eval_set = _make_eval_set(tmp_path, n=5)
    entries = load_eval_set(eval_set)
    train, test = split_train_test(entries, _DEFAULT_SEED)
    n_train = len(train)
    n_test = len(test)
    expected_dispatches = 3 * (n_train + n_test)

    result = runner.invoke(
        app,
        [
            "skill-eval", "optimize", _SKILL,
            "--eval-set", str(eval_set),
            "--dry-run",
            "--iterations", "3",
        ],
    )

    assert result.exit_code == 0
    assert str(expected_dispatches) in result.stdout, (
        f"Expected {expected_dispatches} in output.\nOutput:\n{result.stdout}"
    )
    assert "3" in result.stdout  # iterations count visible


def test_vc1_dry_run_constructs_no_dispatcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """VC1: dry-run must NOT construct a ClaudeSubprocessDispatcher."""
    eval_set = _make_eval_set(tmp_path, n=5)

    constructed: list[str] = []

    class _SentinelDispatcher(MockDispatcher):
        def __init__(self, **_kw: Any) -> None:
            del _kw  # intentionally unused in sentinel
            constructed.append("constructed")
            super().__init__()

    monkeypatch.setattr(
        "mapify_cli.skills_eval.description_optimizer.ClaudeSubprocessDispatcher",
        _SentinelDispatcher,
    )

    result = runner.invoke(
        app,
        [
            "skill-eval", "optimize", _SKILL,
            "--eval-set", str(eval_set),
            "--dry-run",
        ],
    )

    assert result.exit_code == 0
    assert constructed == [], (
        f"Dispatcher was constructed during dry-run! Calls: {constructed}"
    )


# ---------------------------------------------------------------------------
# VC2: < 5 entries -> exit 2 with ">= 5" message, BEFORE any dispatcher
# ---------------------------------------------------------------------------


def test_vc2_fewer_than_5_entries_exits_2(tmp_path: Path) -> None:
    """VC2: eval-set with 4 entries exits 2 with '>= 5' message."""
    eval_set = _make_eval_set(tmp_path, n=4)

    result = runner.invoke(
        app,
        [
            "skill-eval", "optimize", _SKILL,
            "--eval-set", str(eval_set),
        ],
    )

    assert result.exit_code == 2, (
        f"Expected exit 2 for < 5 entries, got {result.exit_code}.\nOutput:\n{result.stdout}"
    )
    assert "5" in result.stdout, (
        f"Expected '>= 5' minimum in error message.\nOutput:\n{result.stdout}"
    )


def test_vc2_min_size_before_dispatcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """VC2: dispatcher must NOT be constructed when entries < 5 (even non-dry-run)."""
    eval_set = _make_eval_set(tmp_path, n=3)
    constructed: list[str] = []

    class _SentinelDispatcher(MockDispatcher):
        def __init__(self, **_kw: Any) -> None:
            del _kw  # intentionally unused in sentinel
            constructed.append("constructed")
            super().__init__()

    monkeypatch.setattr(
        "mapify_cli.skills_eval.description_optimizer.ClaudeSubprocessDispatcher",
        _SentinelDispatcher,
    )
    # Even if claude were on PATH, dispatcher must not be constructed before min-size check
    monkeypatch.setattr("shutil.which", _which_present)

    result = runner.invoke(
        app,
        [
            "skill-eval", "optimize", _SKILL,
            "--eval-set", str(eval_set),
        ],
    )

    assert result.exit_code == 2
    assert constructed == [], (
        f"Dispatcher was constructed before min-size check! Calls: {constructed}"
    )


def test_vc2_exactly_5_entries_does_not_exit_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """VC2: boundary — exactly 5 entries must NOT be rejected by the min-size guard."""
    _make_claude_dir(tmp_path)
    eval_set = _make_eval_set(tmp_path, n=5)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("shutil.which", _which_present)
    monkeypatch.setattr(
        "mapify_cli.skills_eval.description_optimizer.ClaudeSubprocessDispatcher",
        _mock_dispatcher_factory(_SKILL),
    )
    monkeypatch.setattr(
        "mapify_cli.skills_eval.proposer.propose_description",
        _mock_proposer,
    )

    result = runner.invoke(
        app,
        [
            "skill-eval", "optimize", _SKILL,
            "--eval-set", str(eval_set),
            "--iterations", "1",
        ],
    )

    # Must not exit 2 due to the min-size guard (5 >= 5)
    assert result.exit_code != 2, (
        f"5 entries should not trigger the min-size guard.\nOutput:\n{result.stdout}"
    )


# ---------------------------------------------------------------------------
# VC3: claude absent -> exit 1 with "requires-cmd: claude"
# ---------------------------------------------------------------------------


def test_vc3_claude_absent_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """VC3: when claude is not on PATH, exit 1 with 'requires-cmd: claude'."""
    eval_set = _make_eval_set(tmp_path, n=5)
    monkeypatch.setattr("shutil.which", _which_absent)

    result = runner.invoke(
        app,
        [
            "skill-eval", "optimize", _SKILL,
            "--eval-set", str(eval_set),
        ],
    )

    assert result.exit_code == 1, (
        f"Expected exit 1 when claude absent, got {result.exit_code}.\nOutput:\n{result.stdout}"
    )
    assert "requires-cmd: claude" in result.stdout, (
        f"Expected 'requires-cmd: claude' in output.\nOutput:\n{result.stdout}"
    )


def test_vc3_claude_absent_dry_run_still_exits_0(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """VC3: dry-run does NOT check for claude; exit 0 even when claude absent."""
    eval_set = _make_eval_set(tmp_path, n=5)
    monkeypatch.setattr("shutil.which", _which_absent)

    result = runner.invoke(
        app,
        [
            "skill-eval", "optimize", _SKILL,
            "--eval-set", str(eval_set),
            "--dry-run",
        ],
    )

    # dry-run exits BEFORE the claude check
    assert result.exit_code == 0, (
        f"Dry-run should exit 0 even when claude absent.\nOutput:\n{result.stdout}"
    )


# ---------------------------------------------------------------------------
# VC4 + VC6: full run writes JSON + HTML; view renders; nothing outside .map/ changed
# ---------------------------------------------------------------------------


def test_vc4_vc6_full_run_writes_artifacts_and_nothing_outside_map(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """VC4+VC6: full run writes *-optimize.json + *.html under .map/; SKILL.md unchanged."""
    _make_claude_dir(tmp_path)
    eval_set = _make_eval_set(tmp_path, n=5)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("shutil.which", _which_present)
    monkeypatch.setattr(
        "mapify_cli.skills_eval.description_optimizer.ClaudeSubprocessDispatcher",
        _mock_dispatcher_factory(_SKILL),
    )
    monkeypatch.setattr(
        "mapify_cli.skills_eval.proposer.propose_description",
        _mock_proposer,
    )

    # Snapshot files BEFORE the run (relative to tmp_path, under .claude only)
    skill_md_path = tmp_path / ".claude" / "skills" / _SKILL / "SKILL.md"
    skill_md_before = skill_md_path.read_text(encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "skill-eval", "optimize", _SKILL,
            "--eval-set", str(eval_set),
            "--iterations", "2",
        ],
    )

    assert result.exit_code == 0, (
        f"Expected exit 0 for full run.\nOutput:\n{result.stdout}"
    )

    # VC4: *-optimize.json and *-optimize.html must exist under .map/eval-runs/<skill>/
    out_dir = tmp_path / ".map" / "eval-runs" / _SKILL
    json_files = list(out_dir.glob("*-optimize.json"))
    html_files = list(out_dir.glob("*-optimize.html"))
    assert len(json_files) == 1, (
        f"Expected 1 *-optimize.json under {out_dir}, found: {json_files}"
    )
    assert len(html_files) == 1, (
        f"Expected 1 *-optimize.html under {out_dir}, found: {html_files}"
    )

    # VC4: JSON must be a valid OptimizeResult
    from mapify_cli.skills_eval.eval_schema import OptimizeResult

    stored = OptimizeResult.from_dict(json.loads(json_files[0].read_text(encoding="utf-8")))
    assert stored.skill == _SKILL

    # VC6: all NEW paths must be under .map/; SKILL.md must be byte-unchanged
    all_new_paths = [
        p for p in tmp_path.rglob("*")
        if p.is_file() and ".map" not in str(p.relative_to(tmp_path)).split("/")
    ]
    map_new = [
        p for p in tmp_path.rglob("*")
        if p.is_file() and str(p.relative_to(tmp_path)).startswith(".map")
    ]
    # The only files outside .map/ were there before; verify SKILL.md unchanged
    assert skill_md_path.read_text(encoding="utf-8") == skill_md_before, (
        "SKILL.md was modified by optimize (no --apply)!"
    )
    assert len(map_new) >= 2, (
        f"Expected at least JSON+HTML under .map/, found: {map_new}"
    )
    # Confirm no unexpected files outside .map/ (only .claude and eval_set.json expected)
    unexpected = [
        p for p in all_new_paths
        if not str(p.relative_to(tmp_path)).startswith(".claude")
        and p != eval_set
    ]
    assert unexpected == [], (
        f"Files created outside .map/ and .claude/: {unexpected}"
    )


def test_vc4_view_renders_from_stored_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """VC4: `view` loads the stored JSON and renders an HTML report."""
    _make_claude_dir(tmp_path)
    eval_set = _make_eval_set(tmp_path, n=5)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("shutil.which", _which_present)
    monkeypatch.setattr(
        "mapify_cli.skills_eval.description_optimizer.ClaudeSubprocessDispatcher",
        _mock_dispatcher_factory(_SKILL),
    )
    monkeypatch.setattr(
        "mapify_cli.skills_eval.proposer.propose_description",
        _mock_proposer,
    )

    # Run optimize first to produce the stored result
    optimize_result = runner.invoke(
        app,
        [
            "skill-eval", "optimize", _SKILL,
            "--eval-set", str(eval_set),
            "--iterations", "1",
        ],
    )
    assert optimize_result.exit_code == 0, (
        f"Optimize failed before view test.\nOutput:\n{optimize_result.stdout}"
    )

    # Now run view
    view_result = runner.invoke(
        app,
        ["skill-eval", "view", _SKILL],
    )

    assert view_result.exit_code == 0, (
        f"Expected exit 0 for view.\nOutput:\n{view_result.stdout}"
    )
    # HTML must exist
    out_dir = tmp_path / ".map" / "eval-runs" / _SKILL
    html_files = list(out_dir.glob("*-optimize.html"))
    assert len(html_files) >= 1, (
        f"Expected HTML report to exist after view.\nFiles: {list(out_dir.iterdir())}"
    )


def test_vc6_apply_patcher_not_called_without_apply_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """VC6: without --apply, apply_optimized_description must never be called."""
    _make_claude_dir(tmp_path)
    eval_set = _make_eval_set(tmp_path, n=5)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("shutil.which", _which_present)
    monkeypatch.setattr(
        "mapify_cli.skills_eval.description_optimizer.ClaudeSubprocessDispatcher",
        _mock_dispatcher_factory(_SKILL),
    )
    monkeypatch.setattr(
        "mapify_cli.skills_eval.proposer.propose_description",
        _mock_proposer,
    )

    # Monkeypatch apply_optimized_description to raise if called
    def _should_not_be_called(**_kw: Any) -> str:
        del _kw
        raise AssertionError("apply_optimized_description was called without --apply!")

    monkeypatch.setattr(
        "mapify_cli.skills_eval.apply_patcher.apply_optimized_description",
        _should_not_be_called,
    )

    result = runner.invoke(
        app,
        [
            "skill-eval", "optimize", _SKILL,
            "--eval-set", str(eval_set),
            "--iterations", "1",
        ],
    )

    assert result.exit_code == 0, (
        f"Expected exit 0.\nOutput:\n{result.stdout}"
    )


# ---------------------------------------------------------------------------
# VC5: --open with raising webbrowser does NOT error the run
# ---------------------------------------------------------------------------


def test_vc5_open_swallows_browser_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """VC5: --open with a raising webbrowser.open does NOT error the run (exit 0)."""
    _make_claude_dir(tmp_path)
    eval_set = _make_eval_set(tmp_path, n=5)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("shutil.which", _which_present)
    monkeypatch.setattr(
        "mapify_cli.skills_eval.description_optimizer.ClaudeSubprocessDispatcher",
        _mock_dispatcher_factory(_SKILL),
    )
    monkeypatch.setattr(
        "mapify_cli.skills_eval.proposer.propose_description",
        _mock_proposer,
    )
    monkeypatch.setattr("webbrowser.open", _raise_no_browser)

    result = runner.invoke(
        app,
        [
            "skill-eval", "optimize", _SKILL,
            "--eval-set", str(eval_set),
            "--iterations", "1",
            "--open",
        ],
    )

    assert result.exit_code == 0, (
        f"Expected exit 0 even when webbrowser.open raises.\nOutput:\n{result.stdout}"
    )


def test_vc5_view_open_swallows_browser_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """VC5: `view --open` with raising webbrowser does NOT error the run."""
    _make_claude_dir(tmp_path)
    eval_set = _make_eval_set(tmp_path, n=5)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("shutil.which", _which_present)
    monkeypatch.setattr(
        "mapify_cli.skills_eval.description_optimizer.ClaudeSubprocessDispatcher",
        _mock_dispatcher_factory(_SKILL),
    )
    monkeypatch.setattr(
        "mapify_cli.skills_eval.proposer.propose_description",
        _mock_proposer,
    )

    # Run optimize first
    optimize_result = runner.invoke(
        app,
        [
            "skill-eval", "optimize", _SKILL,
            "--eval-set", str(eval_set),
            "--iterations", "1",
        ],
    )
    assert optimize_result.exit_code == 0

    monkeypatch.setattr("webbrowser.open", _raise_no_browser)

    view_result = runner.invoke(
        app,
        ["skill-eval", "view", _SKILL, "--open"],
    )

    assert view_result.exit_code == 0, (
        f"Expected exit 0 for view --open even with raising webbrowser.\nOutput:\n{view_result.stdout}"
    )


# ---------------------------------------------------------------------------
# Edge: view with no optimize result -> exit 2
# ---------------------------------------------------------------------------


def test_view_no_result_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """view exits 2 when no *-optimize.json found under the skill's eval-runs dir."""
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app,
        ["skill-eval", "view", _SKILL],
    )

    assert result.exit_code == 2, (
        f"Expected exit 2 when no optimize result found.\nOutput:\n{result.stdout}"
    )


# ---------------------------------------------------------------------------
# Edge: optimize --eval-set missing / malformed -> exit 2
# ---------------------------------------------------------------------------


def test_optimize_missing_eval_set_exits_2() -> None:
    """optimize without --eval-set exits 2."""
    result = runner.invoke(
        app,
        ["skill-eval", "optimize", _SKILL],
    )
    assert result.exit_code == 2


def test_optimize_malformed_eval_set_exits_2(tmp_path: Path) -> None:
    """optimize with malformed eval-set JSON exits 2."""
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "skill-eval", "optimize", _SKILL,
            "--eval-set", str(bad),
        ],
    )
    assert result.exit_code == 2
