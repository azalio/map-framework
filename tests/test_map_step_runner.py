"""Tests for map_step_runner human-readable artifact helpers."""

import json
import subprocess
import sys
import types
from pathlib import Path
from unittest.mock import patch

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


def test_record_workflow_fit_creates_decision_and_manifest(branch_workspace):
    result = map_step_runner.record_workflow_fit(
        "map-plan",
        "large",
        "true",
        "true",
        "false",
        "true",
        "New invariants and review justify planning",
    )

    assert result["status"] == "success"
    decision = json.loads((branch_workspace / "workflow-fit.json").read_text())
    assert decision["recommended_workflow"] == "map-plan"
    assert decision["needs_map"] is True
    assert decision["signals"]["test_first_required"] is True

    manifest = json.loads((branch_workspace / "artifact_manifest.json").read_text())
    stage = manifest["stages"]["workflow_fit"]
    assert stage["status"] == "recorded"
    assert stage["metadata"]["recommended_workflow"] == "map-plan"
    assert decision["updated_at"].endswith("Z")
    assert manifest["updated_at"].endswith("Z")
    assert stage["updated_at"].endswith("Z")


def test_record_plan_artifacts_updates_manifest(branch_workspace):
    branch = branch_workspace.name
    (branch_workspace / f"spec_{branch}.md").write_text("# Spec\n", encoding="utf-8")
    (branch_workspace / f"task_plan_{branch}.md").write_text(
        "# Task Plan\n", encoding="utf-8"
    )
    (branch_workspace / "blueprint.json").write_text(
        '{"subtasks": [{"id": "ST-001", "dependencies": [], "affected_files": []}]}\n',
        encoding="utf-8",
    )

    result = map_step_runner.record_plan_artifacts()

    assert result["status"] == "success"
    manifest = json.loads((branch_workspace / "artifact_manifest.json").read_text())
    assert manifest["stages"]["spec"]["status"] == "ready"
    assert manifest["stages"]["plan"]["status"] == "ready"
    recorded_paths = {
        artifact["path"] for artifact in manifest["stages"]["plan"]["artifacts"]
    }
    assert f".map/{branch}/task_plan_{branch}.md" in recorded_paths
    assert f".map/{branch}/blueprint.json" in recorded_paths


def test_record_plan_artifacts_is_partial_when_only_step_state_exists(branch_workspace):
    (branch_workspace / "step_state.json").write_text(
        '{"current_step_phase": "INITIALIZED"}\n', encoding="utf-8"
    )

    result = map_step_runner.record_plan_artifacts()

    assert result["status"] == "success"
    assert result["plan_status"] == "partial"


def test_record_test_contract_handoff_creates_json_and_manifest(branch_workspace):
    (branch_workspace / "test_contract_ST-001.md").write_text(
        "# Test Contract\n", encoding="utf-8"
    )

    result = map_step_runner.record_test_contract_handoff(
        "ST-001",
        "pytest tests/test_auth.py -q",
        "tests/test_auth.py,tests/test_api.py",
        "Lock auth behavior before code generation",
        "Resume with /map-task",
    )

    assert result["status"] == "success"
    handoff = json.loads((branch_workspace / "test_handoff_ST-001.json").read_text())
    assert handoff["status"] == "contract_ready"
    assert handoff["subtask_id"] == "ST-001"
    assert handoff["test_files"] == ["tests/test_auth.py", "tests/test_api.py"]
    assert handoff["updated_at"].endswith("Z")

    manifest = json.loads((branch_workspace / "artifact_manifest.json").read_text())
    stage = manifest["stages"]["test_contract"]
    assert stage["status"] == "contract_ready"
    assert stage["metadata"]["subtask_id"] == "ST-001"
    assert manifest["updated_at"].endswith("Z")
    assert stage["updated_at"].endswith("Z")


def test_load_artifact_manifest_normalizes_branch_name(branch_workspace):
    (branch_workspace / "artifact_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "branch": "wrong-branch",
                "updated_at": "2026-04-12T00:00:00Z",
                "stages": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    manifest = map_step_runner.load_artifact_manifest()

    assert manifest["branch"] == branch_workspace.name


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


def test_build_handoff_bundle_ignores_placeholder_human_artifacts(branch_workspace):
    result = map_step_runner.build_handoff_bundle()

    assert result["status"] == "success"
    assert result["summary"] == "- [not recorded]"
    assert result["validation"] == "- [not recorded]"
    assert result["risks_follow_up"] == "- [not recorded]"


def test_write_learning_handoff_creates_artifacts_and_manifest(branch_workspace):
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
    (branch_workspace / "workflow-fit.json").write_text(
        json.dumps({"recommended_workflow": "map-efficient"}) + "\n",
        encoding="utf-8",
    )

    result = map_step_runner.write_learning_handoff(
        "map-check",
        "Implement auth",
        "READY FOR REVIEW",
        "Run /map-review next",
        "Capture auth lessons after review.",
    )

    assert result["status"] == "success"
    markdown = (branch_workspace / "learning-handoff.md").read_text(encoding="utf-8")
    assert "Run `/map-learn` with no arguments" in markdown
    assert "Implement auth" in markdown
    assert "READY FOR REVIEW" in markdown
    assert "artifact_manifest.json" in markdown

    payload = json.loads((branch_workspace / "learning-handoff.json").read_text())
    assert payload["workflow"] == "map-check"
    assert payload["task_title"] == "Implement auth"
    assert payload["outcome"] == "READY FOR REVIEW"
    assert (
        payload["artifacts"]["artifact_manifest"]["stages"]["learn_handoff"]["status"]
        == "ready"
    )
    assert (
        payload["artifacts"]["learning_metrics"]["counters"]["handoff_generated_count"]
        == 1
    )

    metrics = json.loads((branch_workspace / "learning-metrics.json").read_text())
    assert metrics["counters"]["handoff_generated_count"] == 1
    assert metrics["counters"]["pending_handoff_count"] == 1
    assert metrics["current_handoff"]["workflow"] == "map-check"

    manifest = json.loads((branch_workspace / "artifact_manifest.json").read_text())
    stage = manifest["stages"]["learn_handoff"]
    assert stage["status"] == "ready"
    recorded_paths = {artifact["path"] for artifact in stage["artifacts"]}
    assert f".map/{branch_workspace.name}/learning-handoff.md" in recorded_paths
    assert f".map/{branch_workspace.name}/learning-handoff.json" in recorded_paths
    assert f".map/{branch_workspace.name}/learning-metrics.json" in recorded_paths
    assert (
        stage["metadata"]["learning_metrics_counters"]["handoff_generated_count"] == 1
    )

    event_log = (
        Path(".claude/metrics/agent_metrics.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert any("learning_handoff_generated" in line for line in event_log)


def test_write_learning_handoff_marks_replaced_pending_handoff_as_never_used(
    branch_workspace,
):
    first = map_step_runner.write_learning_handoff(
        "map-check",
        "First task",
        "READY FOR REVIEW",
        "Run /map-review next",
    )
    second = map_step_runner.write_learning_handoff(
        "map-review",
        "Second task",
        "READY FOR LEARN",
        "Run /map-learn next",
    )

    assert first["status"] == "success"
    assert second["status"] == "success"

    metrics = json.loads((branch_workspace / "learning-metrics.json").read_text())
    assert metrics["counters"]["handoff_generated_count"] == 2
    assert metrics["counters"]["never_used_handoff_count"] == 1
    assert metrics["counters"]["pending_handoff_count"] == 1
    assert metrics["current_handoff"]["workflow"] == "map-review"
    event_names = [event["event"] for event in metrics["events"]]
    assert "learning_handoff_abandoned" in event_names
    assert event_names.count("learning_handoff_generated") == 2


def test_record_learning_consumption_records_immediate_usage_and_reuse(
    branch_workspace,
):
    map_step_runner.write_learning_handoff(
        "map-efficient",
        "Auth workflow",
        "READY FOR REVIEW",
        "Run /map-review next",
    )

    result = map_step_runner.record_learning_consumption("auto-handoff")

    assert result["status"] == "success"
    assert result["usage_status"] == "recorded"
    assert result["workflow"] == "map-efficient"
    assert result["consumption_mode"] == "immediate"

    metrics = json.loads((branch_workspace / "learning-metrics.json").read_text())
    assert metrics["counters"]["handoff_generated_count"] == 1
    assert metrics["counters"]["handoff_consumed_count"] == 1
    assert metrics["counters"]["immediate_learn_count"] == 1
    assert metrics["counters"]["pending_handoff_count"] == 0
    assert metrics["current_handoff"]["consumption_source"] == "auto-handoff"
    assert metrics["current_handoff"]["consumption_mode"] == "immediate"
    assert metrics["current_handoff"]["consumed_at"]

    second = map_step_runner.record_learning_consumption("auto-handoff")

    assert second["status"] == "success"
    assert second["usage_status"] == "already_recorded"

    metrics_after_reuse = json.loads(
        (branch_workspace / "learning-metrics.json").read_text()
    )
    assert metrics_after_reuse["counters"]["handoff_consumed_count"] == 1
    assert metrics_after_reuse["counters"]["immediate_learn_count"] == 1
    assert metrics_after_reuse["counters"]["pending_handoff_count"] == 0


def test_record_learning_consumption_tracks_inline_summaries(branch_workspace):
    result = map_step_runner.record_learning_consumption("inline-summary", "map-fast")

    assert result["status"] == "success"
    assert result["usage_status"] == "manual_summary"
    assert result["workflow"] == "map-fast"

    metrics = json.loads((branch_workspace / "learning-metrics.json").read_text())
    assert metrics["counters"]["manual_summary_count"] == 1
    assert metrics["counters"]["pending_handoff_count"] == 0
    assert metrics["events"][-1]["event"] == "learning_manual_summary_recorded"


def test_write_learning_handoff_records_repeated_rule_violations(branch_workspace):
    learned_rules_dir = Path(".claude/rules/learned")
    learned_rules_dir.mkdir(parents=True)
    (learned_rules_dir / "implementation-patterns.md").write_text(
        "---\n"
        "paths:\n"
        '  - "**/*.py"\n'
        "---\n\n"
        "# Implementation Patterns (Learned)\n\n"
        "- **Validation Functions Must Return None on Invalid** (2026-04-12): "
        "When validation functions receive invalid input, return None because "
        "callers rely on None as the failure signal. [workflow: map-learn]\n",
        encoding="utf-8",
    )
    (branch_workspace / "active-issues.json").write_text(
        json.dumps(
            {
                "updated_at": "2026-04-13T08:00:00Z",
                "issues": [
                    {
                        "id": "VER-001",
                        "stage": "verification",
                        "source_artifact": "verification-summary.md",
                        "status": "open",
                        "summary": "src/service.py:12 validation function returned data on invalid input",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = map_step_runner.write_learning_handoff(
        "map-check",
        "Auth validation",
        "NEEDS WORK",
        "Fix the validation contract",
    )

    assert result["status"] == "success"
    payload = json.loads((branch_workspace / "learning-handoff.json").read_text())
    repeated = payload["artifacts"]["repeated_violation_summary"]
    assert repeated["finding_count"] == 1
    assert repeated["matched_count"] == 1
    assert (
        repeated["matches"][0]["rule_title"]
        == "Validation Functions Must Return None on Invalid"
    )
    assert repeated["matches"][0]["path_match"] is True

    metrics = json.loads((branch_workspace / "learning-metrics.json").read_text())
    assert metrics["counters"]["repeated_violation_scan_count"] == 1
    assert metrics["counters"]["repeated_violation_match_count"] == 1
    assert metrics["events"][-1]["event"] == "learning_repeated_violation_detected"

    markdown = (branch_workspace / "learning-handoff.md").read_text(encoding="utf-8")
    assert "Learning Effectiveness Signals" in markdown
    assert "Validation Functions Must Return None on Invalid" in markdown


def test_write_learning_handoff_leaves_repeated_violation_summary_empty_on_non_match(
    branch_workspace,
):
    learned_rules_dir = Path(".claude/rules/learned")
    learned_rules_dir.mkdir(parents=True)
    (learned_rules_dir / "error-patterns.md").write_text(
        "# Error Patterns (Learned)\n\n"
        "- **Idempotent File Backups Need Timestamps** (2026-04-12): "
        "When creating backups, use timestamps so repeated upgrades do not overwrite "
        "customizations. [workflow: map-learn]\n",
        encoding="utf-8",
    )
    (branch_workspace / "active-issues.json").write_text(
        json.dumps(
            {
                "updated_at": "2026-04-13T08:00:00Z",
                "issues": [
                    {
                        "id": "VER-001",
                        "stage": "verification",
                        "source_artifact": "verification-summary.md",
                        "status": "open",
                        "summary": "OAuth callback misses CSRF state verification",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = map_step_runner.write_learning_handoff(
        "map-review",
        "OAuth review",
        "NEEDS WORK",
        "Add CSRF protection",
    )

    assert result["status"] == "success"
    payload = json.loads((branch_workspace / "learning-handoff.json").read_text())
    repeated = payload["artifacts"]["repeated_violation_summary"]
    assert repeated["finding_count"] == 1
    assert repeated["matched_count"] == 0
    assert repeated["matches"] == []

    metrics = json.loads((branch_workspace / "learning-metrics.json").read_text())
    assert metrics["counters"]["repeated_violation_scan_count"] == 1
    assert metrics["counters"]["repeated_violation_match_count"] == 0

    event_log = Path(".claude/metrics/agent_metrics.jsonl").read_text(encoding="utf-8")
    assert "learning_repeated_violation_detected" not in event_log


def test_map_step_runner_cli_write_learning_handoff_records_repeated_violation_smoke(
    tmp_path,
):
    (tmp_path / ".map" / "default").mkdir(parents=True)
    learned_rules_dir = tmp_path / ".claude" / "rules" / "learned"
    learned_rules_dir.mkdir(parents=True)
    (learned_rules_dir / "implementation-patterns.md").write_text(
        "# Implementation Patterns (Learned)\n\n"
        "- **Validation Functions Must Return None on Invalid** (2026-04-12): "
        "When validation functions receive invalid input, return None because "
        "callers rely on None as the failure signal. [workflow: map-learn]\n",
        encoding="utf-8",
    )
    (tmp_path / ".map" / "default" / "active-issues.json").write_text(
        json.dumps(
            {
                "updated_at": "2026-04-13T08:00:00Z",
                "issues": [
                    {
                        "id": "VER-001",
                        "stage": "verification",
                        "source_artifact": "verification-summary.md",
                        "status": "open",
                        "summary": "validation function returned data on invalid input",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_PATH / "map_step_runner.py"),
            "write_learning_handoff",
            "map-check",
            "CLI smoke task",
            "NEEDS WORK",
            "Fix validation handling",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(result.stdout)
    assert payload["status"] == "success"
    handoff = json.loads((tmp_path / payload["json_path"]).read_text())
    assert handoff["artifacts"]["repeated_violation_summary"]["matched_count"] == 1


def test_classify_learning_consumption_mode_distinguishes_immediate_vs_deferred():
    assert (
        map_step_runner._classify_learning_consumption_mode(
            "2026-04-12T10:00:00Z", "2026-04-12T10:10:00Z"
        )
        == "immediate"
    )
    assert (
        map_step_runner._classify_learning_consumption_mode(
            "2026-04-12T10:00:00Z", "2026-04-12T10:45:00Z"
        )
        == "deferred"
    )
    assert (
        map_step_runner._classify_learning_consumption_mode(
            "bad", "2026-04-12T10:45:00Z"
        )
        == "deferred"
    )


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


# ---------------------------------------------------------------------------
# append_session_log — deprecation stub test
# ---------------------------------------------------------------------------


class TestAppendSessionLog:
    """Focused tests for append_session_log deprecation stub."""

    def test_returns_deprecated_status(self, branch_workspace):
        """Deprecated function returns correct status and flag."""
        result = map_step_runner.append_session_log("ACTOR", "success")

        assert result["status"] == "deprecated"
        assert result["deprecated"] is True
        assert result["path"] == ""

    def test_accepts_all_arguments_without_error(self, branch_workspace):
        """All original arguments are accepted (backward compat) even though ignored."""
        result = map_step_runner.append_session_log(
            "MONITOR", "passed", "ST-001", "details", ["ref1", "ref2"]
        )

        assert result["status"] == "deprecated"


# ---------------------------------------------------------------------------
# write_stage_gate — focused unit tests
# ---------------------------------------------------------------------------


class TestWriteStageGate:
    """Focused tests for write_stage_gate."""

    def test_happy_path_creates_gate_file(self, branch_workspace):
        """Valid verdict creates {stage}-gate.json with correct JSON fields."""
        result = map_step_runner.write_stage_gate(
            "plan", "ready", "plan-review-001.md", "All good"
        )

        assert result["status"] == "success"
        gate_file = branch_workspace / "plan-gate.json"
        assert gate_file.exists()
        data = json.loads(gate_file.read_text(encoding="utf-8"))
        assert data["stage"] == "plan"
        assert data["verdict"] == "ready"
        assert data["source_artifact"] == "plan-review-001.md"
        assert data["notes"] == "All good"
        assert "updated_at" in data

    def test_invalid_verdict_returns_error(self, branch_workspace):
        """An unrecognised verdict returns an error dict without creating a file."""
        result = map_step_runner.write_stage_gate(
            "plan", "approved", "plan-review-001.md"
        )

        assert result["status"] == "error"
        assert "Invalid verdict" in result["message"]
        assert not (branch_workspace / "plan-gate.json").exists()

    def test_stage_name_normalised(self, branch_workspace):
        """Underscores in stage name are replaced with hyphens in file name."""
        result = map_step_runner.write_stage_gate("code_review", "ready")

        assert result["status"] == "success"
        assert (branch_workspace / "code-review-gate.json").exists()

    def test_all_valid_verdicts_accepted(self, branch_workspace):
        """All three GATE_VERDICTS are accepted without error."""
        for verdict in ("ready", "needs-revision", "blocked"):
            res = map_step_runner.write_stage_gate(f"stage-{verdict}", verdict)
            assert (
                res["status"] == "success"
            ), f"Expected success for verdict={verdict!r}"

    def test_source_artifact_optional(self, branch_workspace):
        """Omitting source_artifact stores None in the JSON payload."""
        map_step_runner.write_stage_gate("plan", "ready")
        data = json.loads(
            (branch_workspace / "plan-gate.json").read_text(encoding="utf-8")
        )
        assert data["source_artifact"] is None

    def test_branch_parameter_respected(self, tmp_path, monkeypatch):
        """Passing an explicit branch writes to that branch's directory."""
        other_branch = "other-branch"
        other_dir = tmp_path / ".map" / other_branch
        other_dir.mkdir(parents=True)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(map_step_runner, "get_branch_name", lambda: "wrong-branch")

        result = map_step_runner.write_stage_gate("plan", "ready", branch=other_branch)

        assert result["status"] == "success"
        assert (other_dir / "plan-gate.json").exists()


# ---------------------------------------------------------------------------
# ensure_active_issues_file — focused unit tests
# ---------------------------------------------------------------------------


class TestEnsureActiveIssuesFile:
    """Focused tests for ensure_active_issues_file."""

    def test_happy_path_creates_file_when_missing(self, branch_workspace):
        """Creates active-issues.json and returns created=True when file absent."""
        result = map_step_runner.ensure_active_issues_file()

        assert result["status"] == "success"
        assert result["created"] is True
        issues_file = branch_workspace / "active-issues.json"
        assert issues_file.exists()
        data = json.loads(issues_file.read_text(encoding="utf-8"))
        assert "issues" in data
        assert isinstance(data["issues"], list)

    def test_returns_created_false_when_file_exists(self, branch_workspace):
        """Returns created=False when active-issues.json already present."""
        # Create the file first
        map_step_runner.ensure_active_issues_file()

        result = map_step_runner.ensure_active_issues_file()

        assert result["status"] == "success"
        assert result["created"] is False

    def test_existing_file_content_not_overwritten(self, branch_workspace):
        """Pre-existing file content is preserved on second call."""
        issues_file = branch_workspace / "active-issues.json"
        custom_content = '{"updated_at": "2026-01-01", "issues": [{"id": "VER-001"}]}\n'
        issues_file.write_text(custom_content, encoding="utf-8")

        map_step_runner.ensure_active_issues_file()

        assert issues_file.read_text(encoding="utf-8") == custom_content


# ---------------------------------------------------------------------------
# replace_active_issues — focused unit tests
# ---------------------------------------------------------------------------


class TestReplaceActiveIssues:
    """Focused tests for replace_active_issues."""

    def test_happy_path_parses_bullet_lines(self, branch_workspace):
        """Bullet-prefixed lines become structured issue entries."""
        result = map_step_runner.replace_active_issues(
            "verification",
            "verification-summary.md",
            "- fix flaky auth test\n- update migration script",
        )

        assert result["status"] == "success"
        assert result["count"] == 2
        data = json.loads(
            (branch_workspace / "active-issues.json").read_text(encoding="utf-8")
        )
        ids = [issue["id"] for issue in data["issues"]]
        assert "VER-001" in ids
        assert "VER-002" in ids
        summaries = [issue["summary"] for issue in data["issues"]]
        assert "fix flaky auth test" in summaries

    def test_none_sentinel_produces_empty_issues(self, branch_workspace):
        """A single '(None)' line results in an empty issues list."""
        result = map_step_runner.replace_active_issues(
            "verification", "verification-summary.md", "(None)"
        )

        assert result["status"] == "success"
        assert result["count"] == 0
        data = json.loads(
            (branch_workspace / "active-issues.json").read_text(encoding="utf-8")
        )
        assert data["issues"] == []

    def test_issue_id_format_uses_stage_prefix(self, branch_workspace):
        """IDs use the first 3 uppercase chars of the stage name."""
        map_step_runner.replace_active_issues(
            "plan", "plan-review-001.md", "- missing acceptance criteria"
        )

        data = json.loads(
            (branch_workspace / "active-issues.json").read_text(encoding="utf-8")
        )
        assert data["issues"][0]["id"] == "PLA-001"

    def test_empty_issues_text_produces_empty_list(self, branch_workspace):
        """Completely empty issues_text results in zero issues."""
        result = map_step_runner.replace_active_issues("code", "code-review-001.md", "")

        assert result["count"] == 0

    def test_replaces_previous_issues(self, branch_workspace):
        """Calling replace twice overwrites the old issues entirely."""
        map_step_runner.replace_active_issues(
            "plan", "plan-review-001.md", "- first issue"
        )
        map_step_runner.replace_active_issues(
            "plan", "plan-review-002.md", "- second issue"
        )

        data = json.loads(
            (branch_workspace / "active-issues.json").read_text(encoding="utf-8")
        )
        assert len(data["issues"]) == 1
        assert data["issues"][0]["summary"] == "second issue"


# ---------------------------------------------------------------------------
# build_review_handoff — focused unit tests
# ---------------------------------------------------------------------------


class TestBuildReviewHandoff:
    """Focused tests for build_review_handoff."""

    def test_happy_path_returns_all_paths(self, branch_workspace):
        """Returns paths for all artifacts when they exist."""
        (branch_workspace / "plan-review-001.md").write_text(
            "# Plan Review 001\n", encoding="utf-8"
        )
        (branch_workspace / "code-review-001.md").write_text(
            "# Code Review 001\n", encoding="utf-8"
        )
        (branch_workspace / "verification-summary.md").write_text(
            "# VS\n", encoding="utf-8"
        )
        (branch_workspace / "active-issues.json").write_text(
            '{"issues": []}\n', encoding="utf-8"
        )

        result = map_step_runner.build_review_handoff()

        assert result["status"] == "success"
        assert result["plan_review_path"] == "plan-review-001.md"
        assert result["code_review_path"] == "code-review-001.md"
        assert result["verification_summary_path"] == "verification-summary.md"
        assert result["active_issues_path"] == "active-issues.json"

    def test_returns_none_paths_when_no_artifacts(self, branch_workspace):
        """Returns None for paths when no numbered artifacts exist."""
        result = map_step_runner.build_review_handoff()

        assert result["status"] == "success"
        assert result["plan_review_path"] is None
        assert result["code_review_path"] is None

    def test_returns_highest_numbered_review(self, branch_workspace):
        """With multiple code-review files, returns the highest-numbered one."""
        (branch_workspace / "code-review-001.md").write_text(
            "Review 1\n", encoding="utf-8"
        )
        (branch_workspace / "code-review-002.md").write_text(
            "Review 2\n", encoding="utf-8"
        )
        (branch_workspace / "code-review-003.md").write_text(
            "Review 3\n", encoding="utf-8"
        )

        result = map_step_runner.build_review_handoff()

        assert result["code_review_path"] == "code-review-003.md"

    def test_verification_summary_none_when_absent(self, branch_workspace):
        """verification_summary_path is None when file does not exist."""
        result = map_step_runner.build_review_handoff()

        assert result["verification_summary_path"] is None


# ---------------------------------------------------------------------------
# build_handoff_bundle — focused unit tests
# ---------------------------------------------------------------------------


class TestBuildHandoffBundle:
    """Focused tests for build_handoff_bundle."""

    def test_happy_path_returns_summary_validation_risks(self, branch_workspace):
        """Returns non-empty summary, validation, and risks when artifacts exist."""
        (branch_workspace / "verification-summary.md").write_text(
            "# Verification Summary\n\n- Verdict: READY FOR REVIEW\n", encoding="utf-8"
        )
        (branch_workspace / "code-review-001.md").write_text(
            "# Code Review 001\n\n- follow up on edge case\n", encoding="utf-8"
        )

        result = map_step_runner.build_handoff_bundle()

        assert result["status"] == "success"
        assert "Verification summary available" in result["summary"]
        assert "READY FOR REVIEW" in result["validation"]
        assert "follow up on edge case" in result["risks_follow_up"]

    def test_empty_artifacts_returns_minimal_output(self, branch_workspace):
        """With no review/verification artifacts, summary and risks default to '[not recorded]'.

        Note: build_handoff_bundle calls ensure_human_artifacts which creates qa-001.md,
        so validation will contain at least the QA stub rather than '[not recorded]'.
        """
        result = map_step_runner.build_handoff_bundle()

        assert result["status"] == "success"
        # No verification summary or code review → summary has no bullets
        assert "[not recorded]" in result["summary"]
        # risks_follow_up has no code review content
        assert "[not recorded]" in result["risks_follow_up"]
        # validation contains the auto-created qa-001.md stub at minimum
        assert "QA" in result["validation"] or "[not recorded]" in result["validation"]

    def test_branch_field_in_response(self, branch_workspace):
        """Response includes the branch name."""
        result = map_step_runner.build_handoff_bundle()

        assert result["branch"] == "test-branch"


# ---------------------------------------------------------------------------
# write_pr_draft — focused unit tests
# ---------------------------------------------------------------------------


class TestWritePrDraft:
    """Focused tests for write_pr_draft."""

    def test_happy_path_creates_file_with_content(self, branch_workspace):
        """Creates pr-draft.md with all provided sections."""
        result = map_step_runner.write_pr_draft(
            "- Added login flow",
            "- All tests pass",
            "- Monitor auth latency",
        )

        assert result["status"] == "success"
        content = (branch_workspace / "pr-draft.md").read_text(encoding="utf-8")
        assert "Added login flow" in content
        assert "All tests pass" in content
        assert "Monitor auth latency" in content

    def test_defaults_to_not_recorded(self, branch_workspace):
        """Empty arguments produce '[not recorded]' placeholders in each section."""
        map_step_runner.write_pr_draft()

        content = (branch_workspace / "pr-draft.md").read_text(encoding="utf-8")
        # All three sections should show the default placeholder
        assert content.count("[not recorded]") == 3

    def test_overwrites_existing_pr_draft(self, branch_workspace):
        """Second call replaces content written by the first call."""
        map_step_runner.write_pr_draft("- First summary")
        map_step_runner.write_pr_draft("- Second summary")

        content = (branch_workspace / "pr-draft.md").read_text(encoding="utf-8")
        assert "First summary" not in content
        assert "Second summary" in content


# ---------------------------------------------------------------------------
# write_plan_review — focused unit tests
# ---------------------------------------------------------------------------


class TestWritePlanReview:
    """Focused tests for write_plan_review."""

    def test_happy_path_creates_numbered_file(self, branch_workspace):
        """Creates plan-review-001.md on first call with correct content."""
        result = map_step_runner.write_plan_review(
            summary="Looks good",
            recommendation="ready",
        )

        assert result["status"] == "success"
        assert result["file_name"] == "plan-review-001.md"
        content = (branch_workspace / "plan-review-001.md").read_text(encoding="utf-8")
        assert "Looks good" in content
        assert "ready" in content

    def test_sequential_numbering(self, branch_workspace):
        """Second call creates plan-review-002.md."""
        map_step_runner.write_plan_review(recommendation="ready")
        result = map_step_runner.write_plan_review(recommendation="needs-revision")

        assert result["status"] == "success"
        assert result["file_name"] == "plan-review-002.md"

    def test_invalid_recommendation_returns_error(self, branch_workspace):
        """An unrecognised recommendation value returns an error dict."""
        result = map_step_runner.write_plan_review(recommendation="approve")

        assert result["status"] == "error"
        assert "Invalid recommendation" in result["message"]
        assert not (branch_workspace / "plan-review-001.md").exists()

    def test_all_valid_recommendations_accepted(self, branch_workspace):
        """All three GATE_VERDICTS are accepted as recommendation values."""
        for verdict in ("ready", "needs-revision", "blocked"):
            res = map_step_runner.write_plan_review(
                summary=f"Review for {verdict}", recommendation=verdict
            )
            assert (
                res["status"] == "success"
            ), f"Expected success for recommendation={verdict!r}"


# ---------------------------------------------------------------------------
# ensure_known_issues_file — focused unit tests
# ---------------------------------------------------------------------------


class TestEnsureKnownIssuesFile:
    """Focused tests for ensure_known_issues_file."""

    def test_happy_path_creates_with_default_structure(self, branch_workspace):
        """Creates known-issues.json with the default empty issues list."""
        result = map_step_runner.ensure_known_issues_file()

        assert result["status"] == "success"
        assert result["created"] is True
        issues_file = branch_workspace / "known-issues.json"
        assert issues_file.exists()
        data = json.loads(issues_file.read_text(encoding="utf-8"))
        assert "issues" in data
        assert data["issues"] == []

    def test_returns_created_false_when_exists(self, branch_workspace):
        """Returns created=False when known-issues.json already present."""
        map_step_runner.ensure_known_issues_file()
        result = map_step_runner.ensure_known_issues_file()

        assert result["status"] == "success"
        assert result["created"] is False

    def test_existing_content_preserved(self, branch_workspace):
        """Pre-existing known-issues.json content is not overwritten."""
        issues_file = branch_workspace / "known-issues.json"
        original = '{"issues": [{"title": "Already tracked"}]}\n'
        issues_file.write_text(original, encoding="utf-8")

        map_step_runner.ensure_known_issues_file()

        assert issues_file.read_text(encoding="utf-8") == original


# ---------------------------------------------------------------------------
# add_known_issue — focused unit tests
# ---------------------------------------------------------------------------


class TestAddKnownIssue:
    """Focused tests for add_known_issue."""

    def test_happy_path_appends_entry(self, branch_workspace):
        """Appends a new entry to the existing known-issues.json."""
        map_step_runner.ensure_known_issues_file()
        result = map_step_runner.add_known_issue(
            "Flaky integration test", "accepted", "Tracked in follow-up"
        )

        assert result["status"] == "success"
        assert result["count"] == 1
        data = json.loads(
            (branch_workspace / "known-issues.json").read_text(encoding="utf-8")
        )
        assert data["issues"][0]["title"] == "Flaky integration test"
        assert data["issues"][0]["status"] == "accepted"
        assert data["issues"][0]["notes"] == "Tracked in follow-up"
        assert "recorded_at" in data["issues"][0]

    def test_auto_creates_file_when_missing(self, branch_workspace):
        """Auto-creates known-issues.json if it does not yet exist."""
        assert not (branch_workspace / "known-issues.json").exists()

        result = map_step_runner.add_known_issue("Missing file test", "accepted")

        assert result["status"] == "success"
        assert (branch_workspace / "known-issues.json").exists()

    def test_multiple_issues_accumulate(self, branch_workspace):
        """Multiple add_known_issue calls accumulate entries (no overwrite)."""
        map_step_runner.ensure_known_issues_file()
        map_step_runner.add_known_issue("Issue A", "accepted")
        result = map_step_runner.add_known_issue("Issue B", "deferred")

        assert result["count"] == 2
        data = json.loads(
            (branch_workspace / "known-issues.json").read_text(encoding="utf-8")
        )
        titles = [issue["title"] for issue in data["issues"]]
        assert "Issue A" in titles
        assert "Issue B" in titles

    def test_default_status_is_accepted(self, branch_workspace):
        """Default status is 'accepted' when not supplied."""
        map_step_runner.ensure_known_issues_file()
        map_step_runner.add_known_issue("Default status issue")

        data = json.loads(
            (branch_workspace / "known-issues.json").read_text(encoding="utf-8")
        )
        assert data["issues"][0]["status"] == "accepted"


# ---------------------------------------------------------------------------
# run_test_gate — focused unit tests
# ---------------------------------------------------------------------------


class TestRunTestGate:
    """Focused tests for run_test_gate."""

    def test_no_test_runner_returns_skipped(self, tmp_path, monkeypatch):
        """Returns skipped when no test runner markers exist."""
        monkeypatch.chdir(tmp_path)

        result = map_step_runner.run_test_gate()

        assert result["status"] == "skipped"
        assert result["passed"] is True
        assert "No test runner detected" in result["reason"]

    def test_pytest_detected_and_executed(self, tmp_path, monkeypatch):
        """Detects pytest.ini and runs pytest."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")

        import subprocess as real_subprocess

        def mock_run(cmd, **kwargs):
            result = real_subprocess.CompletedProcess(cmd, 0, "1 passed\n", "")
            return result

        monkeypatch.setattr("subprocess.run", mock_run)

        result = map_step_runner.run_test_gate()

        assert result["status"] == "success"
        assert result["passed"] is True
        assert "pytest" in result["test_cmd"]

    def test_failed_tests_return_passed_false(self, tmp_path, monkeypatch):
        """Failed tests return passed=False with output."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")

        import subprocess as real_subprocess

        def mock_run(cmd, **kwargs):
            return real_subprocess.CompletedProcess(cmd, 1, "FAILED test_foo\n", "")

        monkeypatch.setattr("subprocess.run", mock_run)

        result = map_step_runner.run_test_gate()

        assert result["status"] == "success"
        assert result["passed"] is False
        assert result["exit_code"] == 1

    def test_timeout_returns_passed_false(self, tmp_path, monkeypatch):
        """Timeout returns passed=False with timeout status."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")

        import subprocess

        def mock_run(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd, 300)

        monkeypatch.setattr("subprocess.run", mock_run)

        result = map_step_runner.run_test_gate()

        assert result["status"] == "timeout"
        assert result["passed"] is False


# ---------------------------------------------------------------------------
# snapshot_code_state — focused unit tests
# ---------------------------------------------------------------------------


class TestSnapshotCodeState:
    """Focused tests for snapshot_code_state."""

    def test_returns_expected_structure(self, branch_workspace):
        """Returns dict with git_ref, files_changed, diff_stat, branch."""
        result = map_step_runner.snapshot_code_state()

        assert result["status"] == "success"
        assert "git_ref" in result
        assert isinstance(result["files_changed"], list)
        assert "diff_stat" in result
        assert result["branch"] == "test-branch"

    def test_git_ref_is_truncated(self, branch_workspace):
        """git_ref is at most 12 characters."""
        result = map_step_runner.snapshot_code_state()

        assert len(result["git_ref"]) <= 12


class TestLoadBlueprint:
    """Tests for load_blueprint function."""

    def test_returns_dict_for_valid_file(self, branch_workspace):
        blueprint = {"summary": "test", "subtasks": [{"id": "ST-001", "title": "T1"}]}
        (branch_workspace / "blueprint.json").write_text(json.dumps(blueprint))
        result = map_step_runner.load_blueprint("test-branch")
        assert result == blueprint

    def test_returns_none_for_missing_file(self, branch_workspace):
        result = map_step_runner.load_blueprint("test-branch")
        assert result is None

    def test_returns_none_for_invalid_json(self, branch_workspace):
        (branch_workspace / "blueprint.json").write_text("not json")
        result = map_step_runner.load_blueprint("test-branch")
        assert result is None


class TestGetSubtaskFromBlueprint:
    """Tests for get_subtask_from_blueprint function."""

    def test_finds_subtask_by_id(self):
        bp = {
            "subtasks": [{"id": "ST-001", "title": "A"}, {"id": "ST-002", "title": "B"}]
        }
        result = map_step_runner.get_subtask_from_blueprint(bp, "ST-002")
        assert result is not None
        assert result["title"] == "B"

    def test_returns_none_for_missing_id(self):
        bp = {"subtasks": [{"id": "ST-001", "title": "A"}]}
        result = map_step_runner.get_subtask_from_blueprint(bp, "ST-999")
        assert result is None

    def test_returns_none_for_empty_subtasks(self):
        result = map_step_runner.get_subtask_from_blueprint({}, "ST-001")
        assert result is None


class TestGetUpstreamIds:
    """Tests for get_upstream_ids function."""

    def test_returns_dependencies(self):
        bp = {"subtasks": [{"id": "ST-002", "dependencies": ["ST-001"]}]}
        result = map_step_runner.get_upstream_ids(bp, "ST-002")
        assert result == ["ST-001"]

    def test_returns_empty_for_no_deps(self):
        bp = {"subtasks": [{"id": "ST-001", "dependencies": []}]}
        result = map_step_runner.get_upstream_ids(bp, "ST-001")
        assert result == []

    def test_returns_empty_for_missing_subtask(self):
        bp = {"subtasks": []}
        result = map_step_runner.get_upstream_ids(bp, "ST-999")
        assert result == []


class TestBuildContextBlock:
    """Tests for build_context_block function."""

    def test_returns_empty_when_no_blueprint(self, branch_workspace):
        result = map_step_runner.build_context_block("test-branch", "ST-001")
        assert result == ""

    def test_returns_empty_when_subtask_not_found(self, branch_workspace):
        bp = {"summary": "test", "subtasks": [{"id": "ST-001", "title": "A"}]}
        (branch_workspace / "blueprint.json").write_text(json.dumps(bp))
        result = map_step_runner.build_context_block("test-branch", "ST-999")
        assert result == ""

    def test_builds_full_context_block(self, branch_workspace):
        bp = {
            "summary": "test goal",
            "subtasks": [
                {
                    "id": "ST-001",
                    "title": "First task",
                    "aag_contract": "Actor -> do() -> done",
                    "affected_files": ["a.py"],
                    "validation_criteria": ["VC1: check"],
                    "dependencies": [],
                },
                {
                    "id": "ST-002",
                    "title": "Second task",
                    "aag_contract": "Actor -> do2() -> done2",
                    "affected_files": ["b.py"],
                    "validation_criteria": ["VC2: check"],
                    "dependencies": ["ST-001"],
                },
            ],
        }
        (branch_workspace / "blueprint.json").write_text(json.dumps(bp))

        plan = "## Goal\nImplement the feature.\n\n## Subtasks\n..."
        (branch_workspace / "task_plan_test-branch.md").write_text(plan)

        state = {
            "subtask_phases": {"ST-001": "COMPLETE"},
            "subtask_results": {
                "ST-001": {
                    "files_changed": ["a.py"],
                    "status": "valid",
                    "summary": "done",
                }
            },
        }
        (branch_workspace / "step_state.json").write_text(json.dumps(state))

        result = map_step_runner.build_context_block("test-branch", "ST-002")

        assert "<map_context>" in result
        assert "</map_context>" in result
        assert "# Goal:" in result
        assert "Implement the feature." in result
        assert "ST-002" in result
        assert "Second task" in result
        assert "Actor -> do2() -> done2" in result
        assert "[>>] ST-002" in result
        assert "[x] ST-001" in result
        assert "# Upstream Results" in result
        assert "ST-001: files=" in result

    def test_upstream_results_omitted_when_no_deps(self, branch_workspace):
        bp = {
            "summary": "test",
            "subtasks": [
                {
                    "id": "ST-001",
                    "title": "Only task",
                    "aag_contract": "A -> B -> C",
                    "affected_files": [],
                    "validation_criteria": [],
                    "dependencies": [],
                },
            ],
        }
        (branch_workspace / "blueprint.json").write_text(json.dumps(bp))
        plan = "## Goal\nDo thing.\n\n## Done"
        (branch_workspace / "task_plan_test-branch.md").write_text(plan)

        result = map_step_runner.build_context_block("test-branch", "ST-001")

        assert "<map_context>" in result
        assert "# Upstream Results" not in result


class TestBuildContextBlockRepoDelta:
    """Tests for Repo Delta path in build_context_block (requires mocked compute_differential_insight)."""

    def _setup_blueprint_and_state(self, branch_workspace, last_sha=None):
        """Helper to set up blueprint + state with optional last_subtask_commit_sha."""
        bp = {
            "summary": "test",
            "subtasks": [
                {
                    "id": "ST-001",
                    "title": "First task",
                    "aag_contract": "A -> B -> C",
                    "affected_files": ["a.py"],
                    "validation_criteria": ["VC1"],
                    "dependencies": [],
                },
            ],
        }
        (branch_workspace / "blueprint.json").write_text(json.dumps(bp))
        plan = "## Goal\nDo thing.\n\n## Done"
        (branch_workspace / "task_plan_test-branch.md").write_text(plan)

        state = {"subtask_phases": {}, "subtask_results": {}}
        if last_sha is not None:
            state["last_subtask_commit_sha"] = last_sha
        (branch_workspace / "step_state.json").write_text(json.dumps(state))

    def test_includes_repo_delta_when_sha_available(self, branch_workspace):
        self._setup_blueprint_and_state(branch_workspace, last_sha="abc123")
        mock_insight = {
            "changed_files": ["src/foo.py", "src/bar.py"],
            "deleted_files": [],
            "since_sha": "abc123",
            "current_sha": "def456",
        }
        repo_insight = types.SimpleNamespace(
            compute_differential_insight=lambda *_args, **_kwargs: mock_insight
        )
        with patch.dict("sys.modules", {"mapify_cli.repo_insight": repo_insight}):
            result = map_step_runner.build_context_block("test-branch", "ST-001")

        assert "# Repo Delta" in result
        assert "src/foo.py" in result
        assert "src/bar.py" in result

    def test_repo_delta_capped_at_20_files(self, branch_workspace):
        self._setup_blueprint_and_state(branch_workspace, last_sha="abc123")
        many_files = [f"file_{i}.py" for i in range(25)]
        mock_insight = {
            "changed_files": many_files,
            "deleted_files": [],
            "since_sha": "abc123",
            "current_sha": "def456",
        }
        repo_insight = types.SimpleNamespace(
            compute_differential_insight=lambda *_args, **_kwargs: mock_insight
        )
        with patch.dict("sys.modules", {"mapify_cli.repo_insight": repo_insight}):
            result = map_step_runner.build_context_block("test-branch", "ST-001")

        assert "# Repo Delta" in result
        assert "file_19.py" in result
        assert "file_20.py" not in result
        assert "... +5 more" in result

    def test_repo_delta_omitted_on_error(self, branch_workspace):
        self._setup_blueprint_and_state(branch_workspace, last_sha="abc123")
        mock_insight = {
            "changed_files": [],
            "deleted_files": [],
            "error": "git diff failed",
        }
        repo_insight = types.SimpleNamespace(
            compute_differential_insight=lambda *_args, **_kwargs: mock_insight
        )
        with patch.dict("sys.modules", {"mapify_cli.repo_insight": repo_insight}):
            result = map_step_runner.build_context_block("test-branch", "ST-001")

        assert "<map_context>" in result
        assert "# Repo Delta" not in result

    def test_repo_delta_omitted_when_no_sha(self, branch_workspace):
        self._setup_blueprint_and_state(branch_workspace, last_sha=None)
        result = map_step_runner.build_context_block("test-branch", "ST-001")
        assert "<map_context>" in result
        assert "# Repo Delta" not in result

    def test_repo_delta_fallback_on_import_error(self, branch_workspace):
        """When mapify_cli.repo_insight is not importable, Repo Delta is silently skipped."""
        self._setup_blueprint_and_state(branch_workspace, last_sha="abc123")
        with patch.dict(
            "sys.modules", {"mapify_cli": None, "mapify_cli.repo_insight": None}
        ):
            result = map_step_runner.build_context_block("test-branch", "ST-001")

        assert "<map_context>" in result
        assert "# Repo Delta" not in result

    def test_repo_delta_includes_deleted_files(self, branch_workspace):
        """Deleted files from compute_differential_insight are shown in context block."""
        self._setup_blueprint_and_state(branch_workspace, last_sha="abc123")
        mock_insight = {
            "changed_files": ["src/new.py"],
            "deleted_files": ["src/old.py", "src/removed.py"],
            "since_sha": "abc123",
            "current_sha": "def456",
        }
        repo_insight = types.SimpleNamespace(
            compute_differential_insight=lambda *_args, **_kwargs: mock_insight
        )
        with patch.dict("sys.modules", {"mapify_cli.repo_insight": repo_insight}):
            result = map_step_runner.build_context_block("test-branch", "ST-001")

        assert "# Repo Delta" in result
        assert "src/new.py" in result
        assert "# Deleted since last subtask:" in result
        assert "(deleted) src/old.py" in result
        assert "(deleted) src/removed.py" in result

    def test_repo_delta_only_deleted_no_changed(self, branch_workspace):
        """When only deletions occurred, Repo Delta still appears."""
        self._setup_blueprint_and_state(branch_workspace, last_sha="abc123")
        mock_insight = {
            "changed_files": [],
            "deleted_files": ["src/gone.py"],
            "since_sha": "abc123",
            "current_sha": "def456",
        }
        repo_insight = types.SimpleNamespace(
            compute_differential_insight=lambda *_args, **_kwargs: mock_insight
        )
        with patch.dict("sys.modules", {"mapify_cli.repo_insight": repo_insight}):
            result = map_step_runner.build_context_block("test-branch", "ST-001")

        assert "# Repo Delta" in result
        assert "# Deleted since last subtask:" in result
        assert "(deleted) src/gone.py" in result


class TestBuildContextBlockIntegration:
    """Integration test: record_subtask_result → build_context_block → upstream results."""

    def test_upstream_results_flow(self, branch_workspace):
        """Subtask results recorded in step_state appear as upstream results in context block."""
        branch = "test-branch"

        # Set up blueprint with two subtasks, ST-002 depends on ST-001
        bp = {
            "subtasks": [
                {
                    "id": "ST-001",
                    "title": "First task",
                    "aag_contract": "A -> B -> C",
                    "affected_files": ["a.py"],
                    "validation_criteria": ["VC1"],
                    "dependencies": [],
                },
                {
                    "id": "ST-002",
                    "title": "Second task",
                    "aag_contract": "D -> E -> F",
                    "affected_files": ["b.py"],
                    "validation_criteria": ["VC2"],
                    "dependencies": ["ST-001"],
                },
            ],
        }
        (branch_workspace / "blueprint.json").write_text(json.dumps(bp))

        plan = "## Goal\nBuild the feature.\n\n## Done"
        (branch_workspace / f"task_plan_{branch}.md").write_text(plan)

        # Simulate ST-001 completed with results via StepState
        sys.path.insert(0, str(SCRIPTS_PATH))
        import map_orchestrator  # noqa: E402

        state = map_orchestrator.StepState()
        state.current_subtask_id = "ST-002"
        state.record_subtask_result(
            "ST-001", ["a.py"], "valid", "All tests pass", commit_sha="abc123"
        )
        state_file = branch_workspace / "step_state.json"
        state.save(state_file)

        # Now build context for ST-002 — should see ST-001 upstream results
        result = map_step_runner.build_context_block(branch, "ST-002")

        assert "<map_context>" in result
        assert "# Current Subtask: ST-002" in result
        assert "# Upstream Results (dependencies of ST-002):" in result
        assert "ST-001: files=['a.py'], status=valid" in result
        assert "All tests pass" in result
        assert "[x] ST-001: First task (valid)" in result
        assert "[>>] ST-002: Second task (IN PROGRESS)" in result
