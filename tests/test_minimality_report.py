import json

from typer.testing import CliRunner

from mapify_cli import app
from mapify_cli.minimality_report import build_minimality_rollout_report


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def _run_health(minimality, retry_count=0, guard_rework=None):
    return {
        "schema_version": "1.0",
        "generated_at": "2026-06-16T10:00:00Z",
        "workflow": "map-efficient",
        "branch": "sample",
        "minimality": minimality,
        "terminal_status": "complete",
        "completed_step_count": 4,
        "pending_step_count": 0,
        "artifacts": {},
        "resiliency_signals": {
            "retry_count": retry_count,
            "subtask_retry_counts": {},
            "max_subtask_retry_count": 0,
            "guard_rework_counts": guard_rework or {},
        },
    }


def test_minimality_report_marks_candidate_with_clean_baseline_and_opt_in(tmp_path):
    _write_json(
        tmp_path / ".map" / "off-run" / "run_health_report.json", _run_health("off")
    )
    _write_json(
        tmp_path / ".map" / "lite-run" / "run_health_report.json", _run_health("lite")
    )

    report = build_minimality_rollout_report(tmp_path, min_complete_runs=1)

    summary = report["summary"]
    assert summary["decision"] == "candidate"
    assert summary["ready_for_phase3"] is True
    assert summary["complete_off_runs"] == 1
    assert summary["complete_opt_in_runs"] == 1


def test_minimality_report_requires_historical_minimality_in_run_health(tmp_path):
    _write_json(
        tmp_path / ".map" / "old-run" / "run_health_report.json",
        {**_run_health("lite"), "minimality": None},
    )
    (tmp_path / ".map" / "config.yaml").write_text(
        "minimality: lite\n", encoding="utf-8"
    )

    report = build_minimality_rollout_report(tmp_path, min_complete_runs=1)

    summary = report["summary"]
    assert summary["decision"] == "insufficient_data"
    assert summary["complete_runs_missing_historical_minimality"] == 1


def test_minimality_report_counts_deferred_yagni_reversals(tmp_path):
    _write_json(
        tmp_path / ".map" / "off-run" / "run_health_report.json", _run_health("off")
    )
    _write_json(
        tmp_path / ".map" / "lite-run" / "run_health_report.json", _run_health("lite")
    )
    _write_json(
        tmp_path / ".map" / "lite-run" / "blueprint.json",
        {
            "blueprint": {
                "subtasks": [
                    {
                        "id": "ST-001",
                        "pruneable": False,
                        "restored_from_deferred_yagni": "YG-001",
                    }
                ],
                "deferred_yagni": [{"id": "YG-002"}],
            }
        },
    )

    report = build_minimality_rollout_report(tmp_path, min_complete_runs=1)

    lite_branch = next(
        branch for branch in report["branches"] if branch["branch"] == "lite-run"
    )
    assert lite_branch["restored_yagni_count"] == 1
    assert lite_branch["total_yagni_recommendations"] == 2
    assert lite_branch["user_reversal_rate"] == 0.5
    assert report["summary"]["decision"] == "hold"


def test_minimality_report_cli_json(tmp_path):
    _write_json(
        tmp_path / ".map" / "off-run" / "run_health_report.json", _run_health("off")
    )
    _write_json(
        tmp_path / ".map" / "lite-run" / "run_health_report.json", _run_health("lite")
    )

    result = CliRunner().invoke(
        app,
        ["minimality-report", "--path", str(tmp_path), "--min-runs", "1", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["summary"]["decision"] == "candidate"
