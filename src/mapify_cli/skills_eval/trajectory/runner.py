"""Trajectory outcome-eval runner.

Orchestrates one full run per (fixture, run) cell:

    seed -> dispatch -> classify_scope -> run_verification
        -> collect_bundle -> score_deterministic + score_judge
        -> compute_composite -> TrajectoryEvalRecord -> append JSONL

Mirrors the trigger-eval runner's durability invariants (INV-4 per-cell
flush, VC3 resume by ``run_id``, VC4 per-cell errors recorded not raised)
but executes the whole skill body so the trajectory can be scored.

Bundle persistence: each run's full ``TrajectoryBundle`` is written beside
the JSONL under ``<ts>-bundles/<run_id>.json`` so a side-by-side comparator
(``report``) can re-open the exact evidence without the throwaway cwd.
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from mapify_cli.skills_eval.trajectory import bundle as bundle_mod
from mapify_cli.skills_eval.trajectory import gates
from mapify_cli.skills_eval.trajectory.dispatcher import (
    RunOutcome,
    TrajectoryDispatcher,
)
from mapify_cli.skills_eval.trajectory.eval_schema import (
    TrajectoryBundle,
    TrajectoryEvalRecord,
    compute_composite,
    is_hard_pass,
    make_run_id,
)
from mapify_cli.skills_eval.trajectory.judge import (
    JudgeRunner,
    score_judge,
)

logger = logging.getLogger(__name__)

_TRAJECTORY_SUBDIR = "trajectory"


# ---------------------------------------------------------------------------
# Manifest loading
# ---------------------------------------------------------------------------


def load_fixture_manifest(fixture_dir: Path) -> dict[str, Any]:
    """Load and sanity-check a whole-skill fixture ``manifest.json``.

    Raises ``ValueError`` on missing file / invalid JSON / missing required
    keys so the CLI surfaces a clean validation error (exit 2) before any
    invocation.
    """
    manifest_path = fixture_dir / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"fixture manifest not found: {manifest_path}")
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read fixture manifest {manifest_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"fixture manifest must be a JSON object: {manifest_path}")
    required = ("fixture", "skill", "invocation", "test_cmd", "allowed_files")
    missing = [k for k in required if k not in data]
    if missing:
        raise ValueError(
            f"fixture manifest missing required keys {missing}: {manifest_path}"
        )
    return data


# ---------------------------------------------------------------------------
# score_one — pure scoring of a ready bundle (testable without I/O)
# ---------------------------------------------------------------------------


def score_one(
    bundle: TrajectoryBundle,
    *,
    run_id: str,
    run: int,
    ts: str,
    expected_outcome: str,
    judge_runner: JudgeRunner | None,
    judge_timeout: float,
) -> TrajectoryEvalRecord:
    """Score a finished bundle into a ``TrajectoryEvalRecord``.

    Pure wrt the filesystem: deterministic components read only the bundle,
    judge components go through *judge_runner* (Mock in tests / dry-run,
    Claude in production).  Composite + hard_pass are derived via
    ``eval_schema`` helpers.
    """
    deterministic = gates.score_deterministic(bundle, expected_outcome=expected_outcome)
    judge_components, judge_meta = score_judge(
        bundle, runner=judge_runner, timeout=judge_timeout
    )
    components = list(deterministic) + list(judge_components)
    composite = compute_composite(components)
    hard_pass = is_hard_pass(components, composite)
    return TrajectoryEvalRecord(
        run_id=run_id,
        fixture=bundle.fixture,
        run=run,
        ts=ts,
        components=components,
        composite=composite,
        hard_pass=hard_pass,
        expected_outcome=expected_outcome,
        judge_meta=judge_meta,
        error=None,
        bundle_summary={
            "scope_pass": (len(bundle.git.get("out_of_scope", [])) == 0)
            and (len(bundle.git.get("trap_touched", [])) == 0),
            "task_pass": bool(bundle.verification.get("task_pass", False)),
            "out_of_scope": list(bundle.git.get("out_of_scope", [])),
            "trap_touched": list(bundle.git.get("trap_touched", [])),
            "retry_count": (bundle.resiliency_signals or {}).get("retry_count"),
        },
    )


# ---------------------------------------------------------------------------
# run_one — orchestrate one (fixture, run) cell end to end
# ---------------------------------------------------------------------------


def _outcome_to_run_meta(outcome: RunOutcome) -> dict[str, Any]:
    return {
        "ok": outcome.ok,
        "returncode": outcome.returncode,
        "duration_s": outcome.duration_s,
        "error": outcome.error,
        "session_id": outcome.session_id,
        "usage": dict(outcome.usage) if outcome.usage else {},
    }


def run_one(
    fixture_dir: Path,
    *,
    repo_root: Path,
    dispatcher: TrajectoryDispatcher,
    manifest: dict[str, Any],
    run: int,
    ts: str,
    variant: str,
    degrade: str,
    agent_models: dict[str, str] | None,
    judge_runner: JudgeRunner | None,
    judge_timeout: float,
    run_timeout: float,
) -> tuple[TrajectoryEvalRecord | None, TrajectoryBundle | None, str | None]:
    """Run one cell; return ``(record_or_None, bundle_or_None, fatal_error)``.

    On a fatal seeding/run error, returns ``(None, None, error_str)`` so the
    matrix can record a synthetic failure row (VC4) and continue.
    """
    fixture_name = str(manifest["fixture"])
    invocation = str(manifest["invocation"])
    test_cmd = str(manifest["test_cmd"])
    allowed = list(manifest.get("allowed_files", []))
    trap = list(manifest.get("trap_files", []))
    expected_outcome = str(manifest.get("expected_outcome", "complete"))
    branch = str(manifest.get("branch", "main"))
    run_id = make_run_id(fixture_name, run)

    tmp: Path | None = None
    try:
        from mapify_cli.skills_eval.trajectory import seeding

        tmp = seeding.seed_temp(
            fixture_dir,
            repo_root=repo_root,
            variant=variant,
            degrade=degrade,
            agent_models=agent_models,
        )
        outcome = dispatcher.run(invocation, tmp, run_timeout)
        scope = bundle_mod.classify_scope(tmp, allowed, trap)
        verification = gates.run_verification(tmp, test_cmd)
        bundle = bundle_mod.collect_bundle(
            tmp,
            fixture=fixture_name,
            scenario=invocation,
            branch=branch,
            collected_at=ts,
            final_response=(outcome.raw_output or ""),
            scope=scope,
            verification=verification,
            run_meta=_outcome_to_run_meta(outcome),
        )
        record = score_one(
            bundle,
            run_id=run_id,
            run=run,
            ts=ts,
            expected_outcome=expected_outcome,
            judge_runner=judge_runner,
            judge_timeout=judge_timeout,
        )
        if outcome.error:
            record.error = outcome.error
        return (record, bundle, None)
    except Exception as exc:
        logger.exception("run_one: fatal error for %s run=%d", fixture_name, run)
        return (None, None, repr(exc))
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Durable persistence
# ---------------------------------------------------------------------------


def default_run_path(root: Path, skill: str, timestamp: str) -> Path:
    """``<root>/.map/eval-runs/trajectory/<skill>/<timestamp>.jsonl``."""
    return (
        root
        / ".map"
        / "eval-runs"
        / _TRAJECTORY_SUBDIR
        / skill
        / f"{timestamp}.jsonl"
    )


def bundle_dir_for(out_path: Path) -> Path:
    """Directory holding per-run bundle JSONs (sibling of the .jsonl)."""
    return out_path.parent / f"{out_path.stem}-bundles"


def _append_record(out_path: Path, record: TrajectoryEvalRecord) -> None:
    """Append *record* as one JSON line and flush (INV-4 durable per-cell)."""
    line = json.dumps(record.to_dict()) + "\n"
    with open(out_path, "a", encoding="utf-8") as fh:
        fh.write(line)
        fh.flush()


def _save_bundle(out_path: Path, record: TrajectoryEvalRecord, bundle: TrajectoryBundle) -> Path:
    """Persist the full bundle for side-by-side re-opening. Returns its path."""
    bdir = bundle_dir_for(out_path)
    bdir.mkdir(parents=True, exist_ok=True)
    bpath = bdir / f"{record.run_id}.json"
    bpath.write_text(
        json.dumps(bundle.to_dict(), indent=2), encoding="utf-8"
    )
    return bpath


def _read_present_run_ids(out_path: Path) -> set[str]:
    """Return ``run_id``s already in *out_path* (resume; tolerates partial lines)."""
    present: set[str] = set()
    if not out_path.is_file():
        return present
    try:
        with open(out_path, encoding="utf-8") as fh:
            for raw_line in fh:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    row = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict) and isinstance(row.get("run_id"), str):
                    present.add(row["run_id"])
    except OSError as exc:
        logger.warning("_read_present_run_ids: could not read %s: %s", out_path, exc)
    return present


def _fatal_row(
    *,
    run_id: str,
    fixture: str,
    run: int,
    ts: str,
    error: str,
) -> TrajectoryEvalRecord:
    """Synthetic failure row for a fatal cell error (VC4)."""
    from mapify_cli.skills_eval.trajectory.eval_schema import (
        ComponentScore,
        EvidenceLine,
        JudgeMeta,
    )

    components = [
        ComponentScore(
            name=name,
            kind=("deterministic" if name in ("formal", "end_result", "tool_use") else "judge"),
            score=0.0,
            evidence=[
                EvidenceLine(
                    severity="critical",
                    ref="run:fatal",
                    detail=f"fatal error: {error[:200]}",
                )
            ],
        )
        for name in (
            "formal",
            "end_result",
            "tool_use",
            "instruction_compliance",
            "pitfalls",
            "reporting_trust",
        )
    ]
    return TrajectoryEvalRecord(
        run_id=run_id,
        fixture=fixture,
        run=run,
        ts=ts,
        components=components,
        composite=0.0,
        hard_pass=False,
        expected_outcome="complete",
        judge_meta=JudgeMeta(
            prompt_version="fatal",
            ordering="n/a",
            skipped=True,
            caveats=["fatal cell error; judge not run"],
        ),
        error=error,
    )


# ---------------------------------------------------------------------------
# run_matrix
# ---------------------------------------------------------------------------


def run_matrix(
    *,
    fixture_dirs: list[Path],
    repo_root: Path,
    dispatcher: TrajectoryDispatcher,
    runs: int,
    out_path: Path,
    ts: str,
    judge_runner: JudgeRunner | None,
    judge_timeout: float,
    run_timeout: float,
    variant: str = "good",
    degrade: str = "body",
    agent_models: dict[str, str] | None = None,
    resume: bool = False,
) -> list[TrajectoryEvalRecord]:
    """Execute the fixtures x runs matrix and append records to *out_path*.

    Returns records written *during this call* (VC3 resume skips present
    ``run_id``s).  Per-cell fatal errors are recorded as synthetic failure
    rows (VC4); the matrix never aborts.
    """
    present = _read_present_run_ids(out_path) if resume else set()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    written: list[TrajectoryEvalRecord] = []

    for fixture_dir in fixture_dirs:
        manifest = load_fixture_manifest(fixture_dir)
        fixture_name = str(manifest["fixture"])
        for run in range(runs):
            run_id = make_run_id(fixture_name, run)
            if run_id in present:
                logger.debug("run_matrix: skipping %s (resume)", run_id)
                continue
            record, bundle_obj, fatal = run_one(
                fixture_dir,
                repo_root=repo_root,
                dispatcher=dispatcher,
                manifest=manifest,
                run=run,
                ts=ts,
                variant=variant,
                degrade=degrade,
                agent_models=agent_models,
                judge_runner=judge_runner,
                judge_timeout=judge_timeout,
                run_timeout=run_timeout,
            )
            if record is not None:
                _append_record(out_path, record)
                if bundle_obj is not None:
                    _save_bundle(out_path, record, bundle_obj)
                written.append(record)
            else:
                # VC4: fatal cell error -> synthetic failure row.
                row = _fatal_row(
                    run_id=run_id,
                    fixture=fixture_name,
                    run=run,
                    ts=ts,
                    error=fatal or "unknown fatal error",
                )
                _append_record(out_path, row)
                written.append(row)
            logger.info(
                "run_matrix: %s run=%d composite=%.3f hard_pass=%s",
                fixture_name,
                run,
                (record.composite if record else 0.0),
                (record.hard_pass if record else False),
            )
    return written


# ---------------------------------------------------------------------------
# Readers (for aggregation / side-by-side / CLI summary)
# ---------------------------------------------------------------------------


def read_records(out_path: Path) -> list[TrajectoryEvalRecord]:
    """Read all records from a trajectory JSONL (tolerant of partial lines)."""
    records: list[TrajectoryEvalRecord] = []
    if not out_path.is_file():
        return records
    for raw_line in out_path.read_text(encoding="utf-8").splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            row = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        try:
            records.append(TrajectoryEvalRecord.from_dict(row))
        except (KeyError, ValueError, TypeError):
            continue
    return records


def load_bundle(out_path: Path, run_id: str) -> TrajectoryBundle | None:
    """Load a persisted bundle by ``run_id`` (for side-by-side re-opening)."""
    bpath = bundle_dir_for(out_path) / f"{run_id}.json"
    if not bpath.is_file():
        return None
    try:
        return TrajectoryBundle.from_dict(json.loads(bpath.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, KeyError, ValueError):
        return None


def latest_run_path(root: Path, skill: str) -> Path | None:
    """Most-recent trajectory ``.jsonl`` for *skill*, or None."""
    run_dir = root / ".map" / "eval-runs" / _TRAJECTORY_SUBDIR / skill
    if not run_dir.is_dir():
        return None
    candidates = sorted(run_dir.glob("*.jsonl"))
    return candidates[-1] if candidates else None
