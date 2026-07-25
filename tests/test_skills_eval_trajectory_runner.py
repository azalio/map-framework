"""Tests for the trajectory runner orchestration (issue #351).

Covers:
- ``score_one``: pure scoring of a ready bundle into a record.
- ``run_matrix``: durable append, bundle persistence, resume by run_id, and
  synthetic failure rows on fatal errors (VC4). ``seeding.seed_temp`` is
  monkeypatched so no real ``.claude/`` copy happens.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mapify_cli.skills_eval.trajectory import runner
from mapify_cli.skills_eval.trajectory.dispatcher import (
    MockTrajectoryDispatcher,
    RunOutcome,
)
from mapify_cli.skills_eval.trajectory.eval_schema import TrajectoryBundle
from mapify_cli.skills_eval.trajectory.judge import MockJudgeRunner

# ---------------------------------------------------------------------------
# score_one
# ---------------------------------------------------------------------------


def _bundle(*, task_pass: bool = True, out_of_scope=None) -> TrajectoryBundle:
    return TrajectoryBundle(
        fixture="fx",
        scenario="/map-task ST-001",
        branch="main",
        collected_at="ts",
        final_response="done",
        git={
            "modified_all": ["src/a.py"],
            "source_changes": ["src/a.py"],
            "out_of_scope": list(out_of_scope or []),
            "trap_touched": [],
        },
        verification={"task_pass": task_pass, "test_returncode": 0, "test_tail": ""},
        resiliency_signals={"retry_count": 0},
    )


def test_score_one_clean_run_is_hard_pass():
    payload = {
        "instruction_compliance": {"score": 5, "evidence": "ok"},
        "pitfalls": {"score": 5, "evidence": "ok"},
        "reporting_trust": {"score": 5, "evidence": "ok"},
    }
    rec = runner.score_one(
        _bundle(),
        run_id="ffx-r0",
        run=0,
        ts="ts",
        expected_outcome="complete",
        judge_runner=MockJudgeRunner(payload=payload),
        judge_timeout=10.0,
    )
    assert rec.hard_pass is True
    assert rec.composite == 1.0
    assert rec.judge_meta.skipped is False
    assert {c.name for c in rec.components} == {
        "formal",
        "end_result",
        "tool_use",
        "instruction_compliance",
        "pitfalls",
        "reporting_trust",
    }


def test_score_one_no_judge_skips_and_neutral():
    rec = runner.score_one(
        _bundle(),
        run_id="ffx-r0",
        run=0,
        ts="ts",
        expected_outcome="complete",
        judge_runner=None,
        judge_timeout=10.0,
    )
    assert rec.judge_meta.skipped is True
    judge_comps = [c for c in rec.components if c.kind == "judge"]
    assert all(c.score == 1.0 for c in judge_comps)


def test_score_one_formal_failure_blocks_hard_pass():
    rec = runner.score_one(
        _bundle(out_of_scope=["src/extra.py"]),
        run_id="ffx-r0",
        run=0,
        ts="ts",
        expected_outcome="complete",
        judge_runner=None,
        judge_timeout=10.0,
    )
    assert rec.hard_pass is False
    assert rec.bundle_summary["out_of_scope"] == ["src/extra.py"]


# ---------------------------------------------------------------------------
# run_matrix (monkeypatched seeding)
# ---------------------------------------------------------------------------


def _manifest(fixture_dir: Path) -> dict:
    return json.loads((fixture_dir / "manifest.json").read_text(encoding="utf-8"))


@pytest.fixture
def fake_fixture(tmp_path: Path) -> Path:
    fx = tmp_path / "fx"
    fx.mkdir()
    (fx / "manifest.json").write_text(
        json.dumps(
            {
                "fixture": "fx",
                "skill": "map-task",
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


def test_run_matrix_writes_records_and_bundles(tmp_path, monkeypatch, fake_fixture):
    # Seed factory returns a FRESH dir per call (run_one rmtree's it in finally),
    # mirroring real seed_temp (tempfile.mkdtemp). Each dir has a fake edited
    # file + branch artifacts so classify_scope / collect_bundle work.
    call_count = {"n": 0}

    def _seed(fixture_dir, **kw):
        call_count["n"] += 1
        d = tmp_path / f"seeded-{call_count['n']}"
        d.mkdir()
        (d / "src").mkdir()
        (d / "src" / "a.py").write_text("X = 1\n", encoding="utf-8")
        branch = d / ".map" / "main"
        branch.mkdir(parents=True)
        (branch / "step_state.json").write_text(
            json.dumps({"retry_count": 0}), encoding="utf-8"
        )
        return d

    monkeypatch.setattr("mapify_cli.skills_eval.trajectory.seeding.seed_temp", _seed)
    out_path = tmp_path / "out.jsonl"
    dispatcher = MockTrajectoryDispatcher(
        outcome=RunOutcome(
            ok=True, returncode=0, raw_output="done", session_id="s", duration_s=0.1
        )
    )
    written = runner.run_matrix(
        fixture_dirs=[fake_fixture],
        repo_root=tmp_path,
        dispatcher=dispatcher,
        runs=2,
        out_path=out_path,
        ts="ts",
        judge_runner=None,
        judge_timeout=10.0,
        run_timeout=10.0,
    )
    assert len(written) == 2
    # JSONL has 2 lines.
    lines = [ln for ln in out_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 2
    # Bundle dir persisted.
    bdir = runner.bundle_dir_for(out_path)
    assert (bdir / "ffx-r0.json").is_file()
    assert (bdir / "ffx-r1.json").is_file()


def test_run_matrix_resume_skips_present(tmp_path, monkeypatch, fake_fixture):
    seed_dir = tmp_path / "seeded"
    seed_dir.mkdir()
    (seed_dir / ".map" / "main").mkdir(parents=True)
    monkeypatch.setattr(
        "mapify_cli.skills_eval.trajectory.seeding.seed_temp",
        lambda fixture_dir, **kw: seed_dir,
    )
    out_path = tmp_path / "out.jsonl"
    # Pre-seed one record so resume skips it.
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "run_id": "ffx-r0",
                "fixture": "fx",
                "run": 0,
                "ts": "old",
                "components": [
                    {"name": "formal", "kind": "deterministic", "score": 1.0, "evidence": []}
                ],
                "composite": 1.0,
                "hard_pass": True,
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
    dispatcher = MockTrajectoryDispatcher()
    written = runner.run_matrix(
        fixture_dirs=[fake_fixture],
        repo_root=tmp_path,
        dispatcher=dispatcher,
        runs=2,
        out_path=out_path,
        ts="ts",
        judge_runner=None,
        judge_timeout=10.0,
        run_timeout=10.0,
        resume=True,
    )
    # Only run 1 written (run 0 was present).
    assert {r.run for r in written} == {1}


def test_run_matrix_fatal_error_records_synthetic_row(tmp_path, monkeypatch, fake_fixture):
    def boom(fixture_dir, **kw):
        raise RuntimeError("seed blew up")

    monkeypatch.setattr(
        "mapify_cli.skills_eval.trajectory.seeding.seed_temp", boom
    )
    out_path = tmp_path / "out.jsonl"
    dispatcher = MockTrajectoryDispatcher()
    written = runner.run_matrix(
        fixture_dirs=[fake_fixture],
        repo_root=tmp_path,
        dispatcher=dispatcher,
        runs=1,
        out_path=out_path,
        ts="ts",
        judge_runner=None,
        judge_timeout=10.0,
        run_timeout=10.0,
    )
    assert len(written) == 1
    assert written[0].error is not None
    assert written[0].composite == 0.0
    assert written[0].hard_pass is False


def test_read_records_round_trip(tmp_path, monkeypatch, fake_fixture):
    seed_dir = tmp_path / "seeded"
    seed_dir.mkdir()
    (seed_dir / ".map" / "main").mkdir(parents=True)
    monkeypatch.setattr(
        "mapify_cli.skills_eval.trajectory.seeding.seed_temp",
        lambda fixture_dir, **kw: seed_dir,
    )
    out_path = tmp_path / "out.jsonl"
    runner.run_matrix(
        fixture_dirs=[fake_fixture],
        repo_root=tmp_path,
        dispatcher=MockTrajectoryDispatcher(),
        runs=1,
        out_path=out_path,
        ts="ts",
        judge_runner=None,
        judge_timeout=10.0,
        run_timeout=10.0,
    )
    records = runner.read_records(out_path)
    assert len(records) == 1
    assert records[0].fixture == "fx"


def test_load_bundle_reads_persisted(tmp_path, monkeypatch, fake_fixture):
    seed_dir = tmp_path / "seeded"
    seed_dir.mkdir()
    (seed_dir / ".map" / "main").mkdir(parents=True)
    monkeypatch.setattr(
        "mapify_cli.skills_eval.trajectory.seeding.seed_temp",
        lambda fixture_dir, **kw: seed_dir,
    )
    out_path = tmp_path / "out.jsonl"
    runner.run_matrix(
        fixture_dirs=[fake_fixture],
        repo_root=tmp_path,
        dispatcher=MockTrajectoryDispatcher(),
        runs=1,
        out_path=out_path,
        ts="ts",
        judge_runner=None,
        judge_timeout=10.0,
        run_timeout=10.0,
    )
    bundle = runner.load_bundle(out_path, "ffx-r0")
    assert bundle is not None
    assert bundle.fixture == "fx"


def test_load_fixture_manifest_rejects_missing_required(tmp_path):
    fx = tmp_path / "fx"
    fx.mkdir()
    (fx / "manifest.json").write_text(json.dumps({"fixture": "fx"}), encoding="utf-8")
    with pytest.raises(ValueError):
        runner.load_fixture_manifest(fx)
