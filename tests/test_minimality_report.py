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
    assert summary["sample_gaps"] == {
        "off_baseline_runs": 0,
        "opt_in_runs": 0,
        "historical_minimality_runs": 0,
    }
    assert summary["cohort_branches"] == {
        "off_baseline": ["off-run"],
        "opt_in": ["lite-run"],
        "missing_historical_minimality": [],
    }
    assert summary["next_actions"] == [
        ("Sample the candidate opt-in runs for clarity/underscope regressions "
        "before flipping the global default.")
    ]
    assert summary["manual_review_gate"] == {
        "required": True,
        "candidate_branches": ["lite-run"],
        "checklist": [
            ("Compare each opt-in run against the original user request for dropped "
            "explicit or implied requirements."),
            ("Inspect simplifications for terse or cryptic code that hurts "
            "maintainability."),
            ("Confirm Actor retries addressed only BLOCKER feedback, not NON-BLOCKING "
            "scope expansion."),
            "Verify map:simplification markers name a real ceiling and safe upgrade path.",
        ],
    }


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
    assert summary["sample_gaps"] == {
        "off_baseline_runs": 1,
        "opt_in_runs": 1,
        "historical_minimality_runs": 1,
    }
    assert summary["cohort_branches"] == {
        "off_baseline": [],
        "opt_in": [],
        "missing_historical_minimality": ["old-run"],
    }
    assert (
        "Regenerate complete run_health_report.json files with this mapify "
        "version so each sample records historical minimality."
        in summary["next_actions"]
    )
    assert (
        "Collect 1 more complete run(s) with minimality lite, full, or ultra."
        in summary["next_actions"]
    )
    assert (
        "Collect 1 more complete baseline run(s) with minimality off."
        in summary["next_actions"]
    )
    assert summary["manual_review_gate"] == {
        "required": False,
        "candidate_branches": [],
        "checklist": [],
    }


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
    assert (
        "Review restored deferred-YAGNI items and narrow pruning rules before "
        "considering the default flip." in report["summary"]["next_actions"]
    )


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
    assert payload["summary"]["sample_gaps"]["opt_in_runs"] == 0
    assert payload["summary"]["next_actions"]
    assert payload["summary"]["manual_review_gate"]["required"] is True


def test_minimality_report_cli_human_output_prints_manual_review_gate(tmp_path):
    _write_json(
        tmp_path / ".map" / "off-run" / "run_health_report.json", _run_health("off")
    )
    _write_json(
        tmp_path / ".map" / "lite-run" / "run_health_report.json", _run_health("lite")
    )

    result = CliRunner().invoke(
        app,
        ["minimality-report", "--path", str(tmp_path), "--min-runs", "1"],
    )

    assert result.exit_code == 0, result.output
    assert "Manual review gate" in result.output
    assert "Candidate opt-in branches: lite-run" in result.output
    assert "Checklist:" in result.output
    assert "map:simplification" in result.output


def test_minimality_report_cli_human_output_prints_cohort_branches(tmp_path):
    _write_json(
        tmp_path / ".map" / "old-run" / "run_health_report.json",
        {**_run_health("lite"), "minimality": None},
    )
    _write_json(
        tmp_path / ".map" / "off-run" / "run_health_report.json", _run_health("off")
    )
    _write_json(
        tmp_path / ".map" / "lite-run" / "run_health_report.json", _run_health("lite")
    )

    result = CliRunner().invoke(
        app,
        ["minimality-report", "--path", str(tmp_path), "--min-runs", "1"],
    )

    assert result.exit_code == 0, result.output
    assert "Cohort branches" in result.output
    assert "Off baseline: off-run" in result.output
    assert "Opt-in: lite-run" in result.output
    assert "Missing historical minimality: old-run" in result.output
