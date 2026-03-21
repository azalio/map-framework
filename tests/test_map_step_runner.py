"""Tests for map_step_runner human-readable artifact helpers."""

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

import map_step_runner  # noqa: E402


@pytest.fixture
def branch_workspace(tmp_path, monkeypatch):
    branch = "test-branch"
    workspace = tmp_path / ".map" / branch
    workspace.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(map_step_runner, "get_branch_name", lambda: branch)
    return workspace


def test_ensure_human_artifacts_creates_defaults(branch_workspace):
    result = map_step_runner.ensure_human_artifacts()

    assert result["status"] == "success"
    assert (branch_workspace / "qa-001.md").exists()
    assert (branch_workspace / "pr-draft.md").exists()


def test_next_numbered_artifact_path_increments(branch_workspace):
    (branch_workspace / "code-review-001.md").write_text("one", encoding="utf-8")
    (branch_workspace / "code-review-002.md").write_text("two", encoding="utf-8")

    result = map_step_runner.next_numbered_artifact_path("code-review")

    assert result["status"] == "success"
    assert result["file_name"] == "code-review-003.md"



def test_write_verification_summary_creates_report(branch_workspace):
    result = map_step_runner.write_verification_summary(
        "READY FOR REVIEW",
        "Implement auth",
        "- pytest\n- ruff",
        "- no blocking issues",
        "- open PR",
    )

    assert result["status"] == "success"
    content = (branch_workspace / "verification-summary.md").read_text(encoding="utf-8")
    assert "READY FOR REVIEW" in content
    assert "Implement auth" in content
    assert "open PR" in content


def test_write_pr_draft_creates_report(branch_workspace):
    result = map_step_runner.write_pr_draft(
        "- Added auth flow",
        "- pytest\n- ruff",
        "- follow up on metrics",
    )

    assert result["status"] == "success"
    content = (branch_workspace / "pr-draft.md").read_text(encoding="utf-8")
    assert "Added auth flow" in content
    assert "pytest" in content
    assert "follow up on metrics" in content


def test_build_handoff_bundle_reads_artifacts(branch_workspace):
    """Build handoff bundle reads available artifacts."""
    (branch_workspace / "verification-summary.md").write_text(
        "# Verification Summary\n\n- Verdict: READY FOR REVIEW\n",
        encoding="utf-8",
    )
    (branch_workspace / "qa-001.md").write_text(
        "# QA 001\n\n- Commands Run: pytest\n",
        encoding="utf-8",
    )
    (branch_workspace / "code-review-001.md").write_text(
        "# Code Review 001\n\n- follow up on edge case\n",
        encoding="utf-8",
    )

    result = map_step_runner.build_handoff_bundle()

    assert result["status"] == "success"
    assert "Verification summary available" in result["summary"]
    assert "READY FOR REVIEW" in result["validation"]
    assert "follow up on edge case" in result["risks_follow_up"]


def test_write_plan_review_creates_numbered_artifact(branch_workspace):
    result = map_step_runner.write_plan_review(
        "Planning looks solid overall",
        "(None)",
        "- PR-001 Clarify retry policy",
        "(None)",
        "(None)",
        "- PR-001 Clarify retry policy",
        "needs-revision",
    )

    assert result["status"] == "success"
    content = (branch_workspace / "plan-review-001.md").read_text(encoding="utf-8")
    assert "Plan Review 001" in content
    assert "PR-001 Clarify retry policy" in content
    assert "needs-revision" in content


def test_write_stage_gate_creates_plan_gate(branch_workspace):
    result = map_step_runner.write_stage_gate(
        "plan", "ready", "plan-review-001.md", "Planning approved"
    )

    assert result["status"] == "success"
    content = (branch_workspace / "plan-gate.json").read_text(encoding="utf-8")
    assert '"verdict": "ready"' in content
    assert '"source_artifact": "plan-review-001.md"' in content


def test_active_issues_file_replace(branch_workspace):
    ensure = map_step_runner.ensure_active_issues_file()
    assert ensure["status"] == "success"

    result = map_step_runner.replace_active_issues(
        "verification",
        "verification-summary.md",
        "- fix flaky auth test\n- clarify migration rollback",
    )
    assert result["status"] == "success"

    content = (branch_workspace / "active-issues.json").read_text(encoding="utf-8")
    assert '"stage": "verification"' in content
    assert "fix flaky auth test" in content
    assert "clarify migration rollback" in content


def test_build_review_handoff_collects_branch_artifacts(branch_workspace):
    (branch_workspace / "plan-review-001.md").write_text(
        "# Plan Review 001\n\n- PR-001 tighten scope\n", encoding="utf-8"
    )
    (branch_workspace / "code-review-001.md").write_text(
        "# Code Review 001\n\n- CR-001 add null guard\n", encoding="utf-8"
    )
    (branch_workspace / "verification-summary.md").write_text(
        "# Verification Summary\n\n- Verdict: READY FOR REVIEW\n",
        encoding="utf-8",
    )
    (branch_workspace / "qa-001.md").write_text("# QA 001\n", encoding="utf-8")
    (branch_workspace / "pr-draft.md").write_text(
        "# PR Draft\n\n## Summary\n", encoding="utf-8"
    )
    (branch_workspace / "active-issues.json").write_text(
        '{"updated_at":"2026-03-19T00:00:00","issues":[{"id":"VER-001"}]}\n',
        encoding="utf-8",
    )

    result = map_step_runner.build_review_handoff()

    assert result["status"] == "success"
    assert result["plan_review_path"] == "plan-review-001.md"
    assert result["code_review_path"] == "code-review-001.md"
    assert result["verification_summary_path"] == "verification-summary.md"
    assert result["active_issues_path"] == "active-issues.json"


def test_known_issues_file_and_add_issue(branch_workspace):
    result = map_step_runner.ensure_known_issues_file()
    assert result["status"] == "success"

    add_result = map_step_runner.add_known_issue(
        "Flaky integration test", "accepted", "Track in follow-up"
    )
    assert add_result["status"] == "success"

    content = (branch_workspace / "known-issues.json").read_text(encoding="utf-8")
    assert "Flaky integration test" in content
    assert "accepted" in content
