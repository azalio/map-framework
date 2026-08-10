"""Tests for normalize_review_verdict and write_review_verdict_ledger (issue #406)."""

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

import map_step_runner  # type: ignore[import-not-found]

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def branch_workspace(tmp_path, monkeypatch):
    branch = "test-branch"
    workspace = tmp_path / ".map" / branch
    workspace.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(map_step_runner, "get_branch_name", lambda: branch)
    return workspace


def _monitor_with_critical() -> dict:
    return {
        "verdict": "rejected",
        "issues": [
            {
                "severity": "CRITICAL",
                "category": "correctness",
                "description": "Data loss on rollback under concurrent writes",
                "was_present_before_pr": False,
                "reach_evidence": "Confirmed by reproducer in tests/",
            }
        ],
    }


def _monitor_with_high_important() -> dict:
    return {
        "verdict": "needs_revision",
        "issues": [
            {
                "severity": "HIGH",
                "category": "security",
                "description": "SQL injection in query builder",
                "was_present_before_pr": False,
                "reach_evidence": "Any user-supplied input reaches raw SQL concatenation",
            }
        ],
    }


def _monitor_with_pre_existing() -> dict:
    return {
        "verdict": "needs_revision",
        "issues": [
            {
                "severity": "HIGH",
                "category": "correctness",
                "description": "Known regression in legacy path (pre-existing)",
                "was_present_before_pr": True,
                "reach_evidence": "Old regression, not caused by this PR",
            }
        ],
    }


def _monitor_no_issues() -> dict:
    return {"verdict": "approved", "issues": []}


def _evaluator_high_score() -> dict:
    return {
        "overall_score": 9,
        "recommendation": "proceed",
        "scores": {"correctness": 9, "clarity": 8},
    }


def _evaluator_low_score() -> dict:
    return {
        "overall_score": 3,
        "recommendation": "revise",
        "scores": {"correctness": 3, "clarity": 4},
    }


def _predictor_low_risk() -> dict:
    return {
        "risk_assessment": "low",
        "evidence": [{"source": "test_coverage", "quote": "100% coverage"}],
        "predicted_state": {"breaking_changes": []},
    }


# ---------------------------------------------------------------------------
# normalize_review_verdict — pure function tests (no filesystem)
# ---------------------------------------------------------------------------


def test_critical_monitor_issue_yields_block():
    ledger = map_step_runner.normalize_review_verdict(
        monitor_result=_monitor_with_critical(),
        predictor_result=_predictor_low_risk(),
        evaluator_result=_evaluator_high_score(),
    )

    assert ledger["computed_verdict"] == "BLOCK"
    assert "BLOCK" in ledger["verdict_basis"]
    assert ledger["active_count"] >= 1


def test_high_security_important_issue_yields_block():
    ledger = map_step_runner.normalize_review_verdict(
        monitor_result=_monitor_with_high_important(),
    )

    assert ledger["computed_verdict"] == "BLOCK"
    assert "BLOCK" in ledger["verdict_basis"]


def test_important_finding_any_category_yields_revise():
    monitor = {
        "verdict": "needs_revision",
        "issues": [
            {
                "severity": "HIGH",
                "category": "performance",
                "description": "N+1 query on hot path",
                "was_present_before_pr": False,
                "reach_evidence": "Hits DB on every page load",
            }
        ],
    }
    ledger = map_step_runner.normalize_review_verdict(monitor_result=monitor)

    assert ledger["computed_verdict"] == "REVISE"


def test_pre_existing_finding_is_tombstoned_not_active():
    ledger = map_step_runner.normalize_review_verdict(
        monitor_result=_monitor_with_pre_existing(),
    )

    registry = ledger["findings_registry"]
    assert isinstance(registry, list)
    assert any(f["status"] == "tombstoned" for f in registry)
    # Pre-existing tombstoned findings must not block the verdict
    active = [f for f in registry if f["status"] == "active"]
    if not active:
        assert ledger["computed_verdict"] == "PROCEED"


def test_pre_existing_tombstoned_verdict_recomputed_without_it():
    monitor = {
        "verdict": "needs_revision",
        "issues": [
            {
                "severity": "CRITICAL",
                "category": "correctness",
                "description": "Old known issue",
                "was_present_before_pr": True,
                "reach_evidence": "Pre-existing",
            }
        ],
    }
    ledger = map_step_runner.normalize_review_verdict(monitor_result=monitor)

    # Should be PROCEED since the only finding is tombstoned
    assert ledger["computed_verdict"] == "PROCEED"
    assert ledger["tombstoned_count"] >= 1


def test_medium_issue_without_reach_evidence_downgraded_to_needs_investigation():
    monitor = {
        "verdict": "needs_revision",
        "issues": [
            {
                "severity": "MEDIUM",
                "category": "correctness",
                "description": "Potential off-by-one in loop boundary",
                "was_present_before_pr": False,
                # No reach_evidence provided
            }
        ],
    }
    ledger = map_step_runner.normalize_review_verdict(monitor_result=monitor)

    registry = ledger["findings_registry"]
    downgraded = [f for f in registry if f["status"] == "downgraded"]
    assert downgraded, "MEDIUM without reach_evidence must be downgraded"
    assert downgraded[0]["severity"] == "needs_investigation"


def test_needs_investigation_finding_is_downgraded_not_active():
    monitor = {
        "verdict": "needs_revision",
        "issues": [
            {
                "severity": "MEDIUM",
                "category": "unknown",
                "description": "Unclear side effect in module init",
                "was_present_before_pr": False,
                # No reach_evidence → downgraded; downgraded findings are NOT active
            }
        ],
    }
    ledger = map_step_runner.normalize_review_verdict(monitor_result=monitor)

    # Downgraded findings are recorded but not active, so verdict is PROCEED
    registry = ledger["findings_registry"]
    assert any(f["status"] == "downgraded" for f in registry)
    assert ledger["computed_verdict"] == "PROCEED"
    assert ledger["active_count"] == 0


def test_no_issues_yields_proceed():
    ledger = map_step_runner.normalize_review_verdict(
        monitor_result=_monitor_no_issues(),
        evaluator_result=_evaluator_high_score(),
    )

    assert ledger["computed_verdict"] == "PROCEED"
    assert ledger["active_count"] == 0


def test_only_minor_findings_yield_proceed():
    monitor = {
        "verdict": "approved",
        "issues": [
            {
                "severity": "LOW",
                "category": "style",
                "description": "Minor naming convention inconsistency",
                "was_present_before_pr": False,
                "reach_evidence": "Cosmetic only",
            }
        ],
    }
    ledger = map_step_runner.normalize_review_verdict(monitor_result=monitor)

    assert ledger["computed_verdict"] == "PROCEED"


def test_evaluator_proceed_vs_monitor_rejected_logs_not_verified():
    ledger = map_step_runner.normalize_review_verdict(
        monitor_result={
            "verdict": "rejected",
            "issues": [
                {
                    "severity": "CRITICAL",
                    "category": "correctness",
                    "description": "Critical bug",
                    "was_present_before_pr": False,
                    "reach_evidence": "Reproducible",
                }
            ],
        },
        evaluator_result=_evaluator_high_score(),
    )

    not_verified = ledger["not_verified"]
    assert isinstance(not_verified, list)
    assert any("Evaluator" in item and "proceed" in item.lower() for item in not_verified)


def test_adversarial_findings_are_ingested_into_registry():
    adversarial = [
        {
            "source_agent": "adversarial",
            "category": "security",
            "severity": "critical",
            "claim": "Token not rotated after privilege escalation",
        }
    ]
    ledger = map_step_runner.normalize_review_verdict(
        monitor_result=_monitor_no_issues(),
        adversarial_findings=adversarial,
        review_mode="adversarial",
    )

    registry = ledger["findings_registry"]
    adversarial_entries = [f for f in registry if f["source_agent"] == "adversarial"]
    assert adversarial_entries, "Adversarial findings must appear in registry"
    assert ledger["computed_verdict"] == "BLOCK"


def test_compare_orderings_mode_feeds_same_ledger_path():
    adversarial = [
        {
            "source_agent": "compare_orderings",
            "category": "performance",
            "severity": "important",
            "claim": "Ordering A is 3x slower under load",
        }
    ]
    ledger = map_step_runner.normalize_review_verdict(
        monitor_result=_monitor_no_issues(),
        adversarial_findings=adversarial,
        review_mode="compare_orderings",
    )

    assert ledger["input_classification"]["review_mode"] == "compare_orderings"
    registry = ledger["findings_registry"]
    compare_entries = [f for f in registry if f["source_agent"] == "compare_orderings"]
    assert compare_entries
    assert ledger["computed_verdict"] == "REVISE"


def test_previous_verdict_logged_in_journal():
    ledger = map_step_runner.normalize_review_verdict(
        monitor_result=_monitor_no_issues(),
        previous_verdict="REVISE",
    )

    journal = ledger["journal"]
    assert journal["previous_verdict"] == "REVISE"
    assert journal["current_verdict"] == "PROCEED"
    assert journal["matches_previous"] is False


def test_previous_verdict_matches_when_same():
    ledger = map_step_runner.normalize_review_verdict(
        monitor_result=_monitor_with_critical(),
        previous_verdict="BLOCK",
    )

    journal = ledger["journal"]
    assert journal["previous_verdict"] == "BLOCK"
    assert journal["current_verdict"] == "BLOCK"
    assert journal["matches_previous"] is True


def test_ledger_contains_required_schema_fields():
    ledger = map_step_runner.normalize_review_verdict(
        monitor_result=_monitor_no_issues(),
    )

    for field in (
        "schema_version",
        "generated_at",
        "branch",
        "criteria_version",
        "input_classification",
        "findings_registry",
        "not_verified",
        "computed_verdict",
        "verdict_table",
        "journal",
        "active_count",
        "tombstoned_count",
    ):
        assert field in ledger, f"Required field '{field}' missing from ledger"


def test_schema_version_is_correct():
    ledger = map_step_runner.normalize_review_verdict()

    assert ledger["schema_version"] == "review_verdict_ledger.v1"


def test_verdict_table_id_is_correct():
    ledger = map_step_runner.normalize_review_verdict()

    assert ledger["verdict_table"] == "review_verdict_table.v1"
    assert ledger["criteria_version"] == "review_verdict_table.v1"


def test_predictor_high_risk_adds_finding():
    predictor = {
        "risk_assessment": "critical",
        "evidence": [{"source": "analysis", "quote": "Cascading failure risk"}],
        "predicted_state": {"breaking_changes": ["API v1 removed"]},
    }
    ledger = map_step_runner.normalize_review_verdict(
        monitor_result=_monitor_no_issues(),
        predictor_result=predictor,
    )

    predictor_entries = [
        f for f in ledger["findings_registry"] if f["source_agent"] == "predictor"
    ]
    assert predictor_entries
    assert predictor_entries[0]["severity"] == "critical"
    assert ledger["computed_verdict"] == "BLOCK"


def test_predictor_low_risk_does_not_block():
    ledger = map_step_runner.normalize_review_verdict(
        monitor_result=_monitor_no_issues(),
        predictor_result=_predictor_low_risk(),
    )

    assert ledger["computed_verdict"] == "PROCEED"


def test_no_inputs_yields_proceed():
    ledger = map_step_runner.normalize_review_verdict()

    assert ledger["computed_verdict"] == "PROCEED"
    assert ledger["active_count"] == 0


# ---------------------------------------------------------------------------
# write_review_verdict_ledger — filesystem + manifest tests
# ---------------------------------------------------------------------------


def test_write_review_verdict_ledger_writes_json_and_md(branch_workspace):
    del branch_workspace

    result = map_step_runner.write_review_verdict_ledger(
        monitor_json=json.dumps(_monitor_no_issues()),
        predictor_json=json.dumps(_predictor_low_risk()),
        evaluator_json=json.dumps(_evaluator_high_score()),
    )

    assert result["status"] == "success"
    assert result["computed_verdict"] == "PROCEED"

    workspace = Path(".map/test-branch")
    json_path = workspace / "review-verdict-ledger.json"
    md_path = workspace / "review-verdict-ledger.md"
    assert json_path.exists(), "JSON ledger file must be written"
    assert md_path.exists(), "Markdown summary file must be written"


def test_write_review_verdict_ledger_json_is_valid(branch_workspace):
    del branch_workspace

    map_step_runner.write_review_verdict_ledger(
        monitor_json=json.dumps(_monitor_with_critical()),
    )

    workspace = Path(".map/test-branch")
    payload = json.loads((workspace / "review-verdict-ledger.json").read_text(encoding="utf-8"))
    assert payload["computed_verdict"] == "BLOCK"
    assert isinstance(payload["findings_registry"], list)
    assert payload["schema_version"] == "review_verdict_ledger.v1"


def test_write_review_verdict_ledger_md_contains_verdict(branch_workspace):
    del branch_workspace

    map_step_runner.write_review_verdict_ledger(
        monitor_json=json.dumps(_monitor_no_issues()),
    )

    workspace = Path(".map/test-branch")
    content = (workspace / "review-verdict-ledger.md").read_text(encoding="utf-8")
    assert "PROCEED" in content
    assert "## Findings Registry" in content


def test_write_review_verdict_ledger_updates_manifest_stage(branch_workspace):
    del branch_workspace

    map_step_runner.write_review_verdict_ledger(
        monitor_json=json.dumps(_monitor_no_issues()),
    )

    workspace = Path(".map/test-branch")
    manifest = json.loads((workspace / "artifact_manifest.json").read_text(encoding="utf-8"))
    assert "review_verdict_ledger" in manifest["stages"]
    stage = manifest["stages"]["review_verdict_ledger"]
    assert stage["status"] == "ready"
    assert stage["metadata"]["computed_verdict"] == "PROCEED"


def test_write_review_verdict_ledger_block_updates_manifest_with_block(branch_workspace):
    del branch_workspace

    map_step_runner.write_review_verdict_ledger(
        monitor_json=json.dumps(_monitor_with_critical()),
    )

    workspace = Path(".map/test-branch")
    manifest = json.loads((workspace / "artifact_manifest.json").read_text(encoding="utf-8"))
    stage = manifest["stages"]["review_verdict_ledger"]
    assert stage["metadata"]["computed_verdict"] == "BLOCK"


def test_write_review_verdict_ledger_empty_inputs_yields_proceed(branch_workspace):
    del branch_workspace

    result = map_step_runner.write_review_verdict_ledger()

    assert result["status"] == "success"
    assert result["computed_verdict"] == "PROCEED"


def test_write_review_verdict_ledger_passes_previous_verdict_to_journal(branch_workspace):
    del branch_workspace

    map_step_runner.write_review_verdict_ledger(
        monitor_json=json.dumps(_monitor_no_issues()),
        previous_verdict="REVISE",
    )

    workspace = Path(".map/test-branch")
    payload = json.loads((workspace / "review-verdict-ledger.json").read_text(encoding="utf-8"))
    assert payload["journal"]["previous_verdict"] == "REVISE"
    assert payload["journal"]["current_verdict"] == "PROCEED"


def test_write_review_verdict_ledger_malformed_json_does_not_crash(branch_workspace):
    del branch_workspace

    result = map_step_runner.write_review_verdict_ledger(
        monitor_json="NOT VALID JSON {{{",
        predictor_json="",
        evaluator_json="",
    )

    assert result["status"] == "success"
    assert result["computed_verdict"] == "PROCEED"


def test_write_review_verdict_ledger_adversarial_mode(branch_workspace):
    del branch_workspace

    # Use a non-blocking category (performance) with important severity → REVISE, not BLOCK
    adversarial_json = json.dumps([
        {
            "source_agent": "adversarial",
            "category": "performance",
            "severity": "important",
            "claim": "Hot path is 3x slower than baseline",
        }
    ])

    result = map_step_runner.write_review_verdict_ledger(
        monitor_json=json.dumps(_monitor_no_issues()),
        adversarial_json=adversarial_json,
        review_mode="adversarial",
    )

    assert result["computed_verdict"] == "REVISE"
    workspace = Path(".map/test-branch")
    payload = json.loads((workspace / "review-verdict-ledger.json").read_text(encoding="utf-8"))
    assert payload["input_classification"]["review_mode"] == "adversarial"


def test_write_review_verdict_ledger_result_contains_verdict_fields(branch_workspace):
    del branch_workspace

    result = map_step_runner.write_review_verdict_ledger(
        monitor_json=json.dumps(_monitor_no_issues()),
    )

    for key in ("status", "computed_verdict", "active_count", "tombstoned_count"):
        assert key in result, f"Expected key '{key}' in result"
