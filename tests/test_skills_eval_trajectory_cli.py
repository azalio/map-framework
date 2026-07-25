"""Tests for `mapify skill-eval trajectory` CLI command (issue #351).

Validation criteria covered:
- VC1: missing --fixture => exit 2.
- VC2: malformed fixture manifest => exit 2 before any dispatcher.
- VC3: claude absent => exit 1 with "requires-cmd: claude".
- VC4: --dry-run prints planned runs, exits 0, no dispatcher constructed.
- VC5: --no-judge full run with a monkeypatched dispatcher + seeding writes a
  .jsonl + renders no report; --anchor renders a side-by-side HTML.

All real-run tests monkeypatch the dispatcher + seeding + claude presence so
no quota is spent (INV-2).
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from mapify_cli import app

runner = CliRunner()

_SKILL = "map-task"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _which_present(_cmd: object) -> str:
    del _cmd
    return "/usr/bin/claude"


def _which_absent(_cmd: object) -> None:
    del _cmd


def _write_fixture(root: Path, *, name: str = "fx") -> Path:
    fx = root / name
    fx.mkdir(parents=True)
    (fx / "manifest.json").write_text(
        json.dumps(
            {
                "fixture": name,
                "skill": _SKILL,
                "invocation": "/map-task ST-001",
                "test_cmd": "true",
                "allowed_files": ["src/a.py"],
                "trap_files": [],
                "expected_outcome": "complete",
                "branch": "main",
            }
        ),
        encoding="utf-8",
    )
    return fx


# ---------------------------------------------------------------------------
# VC1 / VC2: validation before any dispatcher
# ---------------------------------------------------------------------------


def test_missing_fixture_exits_2(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["skill-eval", "trajectory", _SKILL])
    assert result.exit_code == 2
    assert "--fixture" in result.output


def test_nonexistent_fixture_dir_exits_2(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app,
        ["skill-eval", "trajectory", _SKILL, "--fixture", str(tmp_path / "nope")],
    )
    assert result.exit_code == 2


def test_malformed_manifest_exits_2(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fx = tmp_path / "fx"
    fx.mkdir()
    (fx / "manifest.json").write_text(
        json.dumps({"fixture": "fx"}),  # missing required keys
        encoding="utf-8",
    )
    result = runner.invoke(
        app, ["skill-eval", "trajectory", _SKILL, "--fixture", str(fx)]
    )
    assert result.exit_code == 2


# ---------------------------------------------------------------------------
# VC3: claude absent
# ---------------------------------------------------------------------------


def test_claude_absent_exits_1(tmp_path, monkeypatch):
    fx = _write_fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("shutil.which", _which_absent)
    result = runner.invoke(
        app,
        [
            "skill-eval",
            "trajectory",
            _SKILL,
            "--fixture",
            str(fx),
            "--runs",
            "1",
        ],
    )
    assert result.exit_code == 1
    assert "requires-cmd: claude" in result.output


# ---------------------------------------------------------------------------
# VC4: dry-run
# ---------------------------------------------------------------------------


def test_dry_run_exits_0_no_dispatcher(tmp_path, monkeypatch):
    fx = _write_fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    # Dry-run must NOT require claude.
    monkeypatch.setattr("shutil.which", _which_absent)
    result = runner.invoke(
        app,
        [
            "skill-eval",
            "trajectory",
            _SKILL,
            "--fixture",
            str(fx),
            "--runs",
            "2",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert "spends 0 quota" in result.output
    assert "runs=2" in result.output


# ---------------------------------------------------------------------------
# VC5: full run with monkeypatched dispatcher + seeding (--no-judge)
# ---------------------------------------------------------------------------


def test_full_run_no_judge_writes_jsonl(tmp_path, monkeypatch):
    fx = _write_fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("shutil.which", _which_present)

    from mapify_cli.skills_eval.trajectory.dispatcher import (
        MockTrajectoryDispatcher,
        RunOutcome,
    )

    seed_dir = tmp_path / "seeded"
    seed_dir.mkdir()
    (seed_dir / ".map" / "main").mkdir(parents=True)

    monkeypatch.setattr(
        "mapify_cli.skills_eval.trajectory.seeding.seed_temp",
        lambda fixture_dir, **kw: seed_dir,
    )
    monkeypatch.setattr(
        "mapify_cli.skills_eval.trajectory.dispatcher.ClaudeTrajectoryDispatcher",
        lambda **kw: MockTrajectoryDispatcher(
            outcome=RunOutcome(ok=True, returncode=0, raw_output="done")
        ),
    )

    result = runner.invoke(
        app,
        [
            "skill-eval",
            "trajectory",
            _SKILL,
            "--fixture",
            str(fx),
            "--runs",
            "1",
            "--no-judge",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Trajectory eval complete" in result.output
    # A .jsonl landed under .map/eval-runs/trajectory/<skill>/
    out_dir = tmp_path / ".map" / "eval-runs" / "trajectory" / _SKILL
    jsonls = sorted(out_dir.glob("*.jsonl"))
    assert jsonls, "expected a trajectory jsonl output"
    lines = [ln for ln in jsonls[-1].read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["fixture"] == "fx"
    assert row["judge_meta"]["skipped"] is True


def test_full_run_with_anchor_renders_html(tmp_path, monkeypatch):
    fx = _write_fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("shutil.which", _which_present)

    from mapify_cli.skills_eval.trajectory.dispatcher import (
        MockTrajectoryDispatcher,
        RunOutcome,
    )

    seed_dir = tmp_path / "seeded"
    seed_dir.mkdir()
    (seed_dir / ".map" / "main").mkdir(parents=True)

    # Anchor: a pre-existing prior run with one record.
    anchor_dir = tmp_path / ".map" / "eval-runs" / "trajectory" / _SKILL
    anchor_dir.mkdir(parents=True)
    anchor_path = anchor_dir / "20260101T000000Z.jsonl"
    anchor_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "run_id": "ffx-r0",
                "fixture": "fx",
                "run": 0,
                "ts": "old",
                "components": [
                    {
                        "name": "formal",
                        "kind": "deterministic",
                        "score": 1.0,
                        "evidence": [
                            {"severity": "info", "ref": "x", "detail": "d"}
                        ],
                    }
                ],
                "composite": 0.5,
                "hard_pass": False,
                "expected_outcome": "complete",
                "judge_meta": {
                    "prompt_version": "v",
                    "ordering": "o",
                    "skipped": True,
                },
                "error": None,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "mapify_cli.skills_eval.trajectory.seeding.seed_temp",
        lambda fixture_dir, **kw: seed_dir,
    )
    monkeypatch.setattr(
        "mapify_cli.skills_eval.trajectory.dispatcher.ClaudeTrajectoryDispatcher",
        lambda **kw: MockTrajectoryDispatcher(
            outcome=RunOutcome(ok=True, returncode=0, raw_output="done")
        ),
    )

    result = runner.invoke(
        app,
        [
            "skill-eval",
            "trajectory",
            _SKILL,
            "--fixture",
            str(fx),
            "--runs",
            "1",
            "--no-judge",
            "--anchor",
            str(anchor_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "side-by-side" in result.output
    htmls = sorted(anchor_dir.glob("*.html"))
    assert htmls, "expected a side-by-side HTML report"
