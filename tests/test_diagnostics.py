"""Tests for diagnostics run summaries."""

import json
import sys
from pathlib import Path

import pytest

SCRIPTS_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "mapify_cli"
    / "templates"
    / "map"
    / "scripts"
)

sys.path.insert(0, str(SCRIPTS_PATH))

import diagnostics  # pyright: ignore[reportMissingImports]


@pytest.fixture
def branch_workspace(tmp_path, monkeypatch):
    branch = "test-branch"
    workspace = tmp_path / ".map" / branch
    workspace.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(diagnostics, "get_branch_name", lambda: branch)
    return workspace


def test_cmd_summarize_writes_run_summary(branch_workspace):
    diagnostics_file = branch_workspace / "diagnostics.json"
    diagnostics_file.write_text(
        json.dumps({"issues": [{"path": "app.py", "line": 10, "message": "boom"}]})
        + "\n",
        encoding="utf-8",
    )
    known_issues_file = branch_workspace / "known-issues.json"
    known_issues_file.write_text(
        json.dumps(
            {
                "issues": [
                    {"title": "Flaky test", "status": "accepted"},
                    {"title": "Manual repro pending", "status": "deferred"},
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )

    args = type(
        "Args",
        (),
        {
            "branch": "",
            "out": "",
            "diagnostics": str(diagnostics_file),
            "known_issues": str(known_issues_file),
            "tool": "tests",
            "command": "pytest",
            "exit_code": 1,
            "summary": "Pytest failed",
            "notes": "Observed flaky timing in integration setup",
        },
    )()

    result = diagnostics.cmd_summarize(args)
    assert result == 0

    payload = json.loads(
        (branch_workspace / "run-summary.json").read_text(encoding="utf-8")
    )
    assert payload["tool"] == "tests"
    assert payload["status"] == "failed"
    assert payload["issue_count"] == 1
    assert payload["accepted_issue_count"] == 1
    assert payload["run_dir"].endswith(
        ".map/test-branch/runs/" + Path(payload["run_dir"]).name
    )
    results_path = Path(payload["results_path"])
    assert results_path.exists()
    assert results_path.name == "RESULTS.md"
    results = results_path.read_text(encoding="utf-8")
    assert "Run Results" in results
    assert "Deferred issue count: 1" in results
    assert "Pytest failed" in results
    notes_path = Path(payload["notes_path"])
    assert notes_path.exists()
    assert "Observed flaky timing" in notes_path.read_text(encoding="utf-8")


def test_cmd_summarize_handles_invalid_json_gracefully(branch_workspace):
    diagnostics_file = branch_workspace / "diagnostics.json"
    diagnostics_file.write_text("{invalid json\n", encoding="utf-8")
    known_issues_file = branch_workspace / "known-issues.json"
    known_issues_file.write_text("{invalid json\n", encoding="utf-8")

    args = type(
        "Args",
        (),
        {
            "branch": "",
            "out": "",
            "diagnostics": str(diagnostics_file),
            "known_issues": str(known_issues_file),
            "tool": "lint",
            "command": "ruff check .",
            "exit_code": 0,
            "summary": "Lint passed",
            "notes": "",
        },
    )()

    result = diagnostics.cmd_summarize(args)
    assert result == 0

    payload = json.loads(
        (branch_workspace / "run-summary.json").read_text(encoding="utf-8")
    )
    assert payload["status"] == "passed"
    assert payload["issue_count"] == 0
