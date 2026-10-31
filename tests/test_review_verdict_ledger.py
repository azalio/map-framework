"""Tests for normalize_review_verdict and write_review_verdict_ledger (issue #406)."""

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, cast

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


def test_adversarial_votes_without_checked_validation_never_establish_quorum():
    envelope = json.dumps({"all_clear": False, "findings": [{"severity": "MINOR",
        "category": "correctness", "file_path": "writer.py", "failure_mode": "retry loses data",
        "evidence": "trust reviewer", "validation": {"verdict": "confirmed"}}]})
    report = map_step_runner.aggregate_adversarial_findings(blind_json=envelope, edge_case_json=envelope)
    assert report["findings"][0]["corroborated"] is False
    assert report["findings"][0]["validation"]["verdict"] == "insufficient_evidence"
    ledger = map_step_runner.normalize_review_verdict(adversarial_findings=report["ledger_findings"],
                                                      review_mode="adversarial")
    assert ledger["computed_verdict"] != "PROCEED"


def test_adversarial_preserves_two_causes_in_same_file_and_scenario():
    findings = [{"file_path": "writer.py", "category": "correctness", "severity": "IMPORTANT",
                 "bug_class": "lost_write", "failure_scenario": "retry loses data", "cause": cause,
                 "failure_mode": "retry loses data", "evidence": "writer.py:1"}
                for cause in ("truncate before locking", "ignore failed flush")]
    report = map_step_runner.aggregate_adversarial_findings(
        blind_json=json.dumps({"findings": findings, "all_clear": False}))
    assert len(report["findings"]) == 2
    assert {finding["cause"] for finding in report["findings"]} == {
        "truncate before locking", "ignore failed flush"}
    assert not any(finding["corroborated"] for finding in report["findings"])


def test_legacy_findings_remain_visible_without_implied_confirmation():
    ledger = map_step_runner.normalize_review_verdict(monitor_result=_monitor_with_critical())
    finding = ledger["findings_registry"][0]
    assert finding["claim"] == "Data loss on rollback under concurrent writes"
    assert finding["validation"]["verdict"] == "insufficient_evidence"
    assert finding["author_reactions"] == []
    assert finding["baseline_attribution"]["status"] == "unknown"
    assert ledger["computed_verdict"] != "PROCEED"


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


def test_pre_existing_minor_finding_is_tombstoned():
    """A low-severity pre-existing finding is genuinely removed from the table."""
    monitor = {
        "verdict": "needs_revision",
        "issues": [
            {
                "severity": "LOW",
                "category": "maintainability",
                "description": "Old naming inconsistency",
                "was_present_before_pr": True,
                "reach_evidence": "grep:oldName:44",
            }
        ],
    }
    ledger = map_step_runner.normalize_review_verdict(monitor_result=monitor)

    assert [f["status"] for f in ledger["findings_registry"]] == ["tombstoned"]
    assert ledger["computed_verdict"] == "PROCEED"
    assert ledger["tombstoned_count"] == 1
    assert ledger["active_count"] == 0


def test_pre_existing_critical_is_retained_not_erased():
    """`was_present_before_pr` is self-attested and may not delete a CRITICAL.

    The reviewer that raised the finding is the same actor asserting it predates
    the PR, so the claim is not independent evidence. The finding is downgraded
    (still counted) and the ledger demands human escalation.
    """
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

    assert ledger["computed_verdict"] == "REVISE"
    assert ledger["tombstoned_count"] == 0
    assert ledger["downgraded_count"] == 1
    assert ledger["active_count"] == 1

    finding = ledger["findings_registry"][0]
    assert finding["status"] == "downgraded"
    assert finding["severity"] == "needs_investigation"
    assert finding["downgraded_from"] == "critical"
    assert finding["transition_reason"] == "pre_existing_backlog"

    assert ledger["escalation_required"] is True
    assert ledger["not_verified"], "the unverified pre-existing claim must be named"


def test_pre_existing_important_is_retained_not_erased():
    ledger = map_step_runner.normalize_review_verdict(
        monitor_result=_monitor_with_pre_existing(),
    )

    assert all(
        f["status"] != "tombstoned" for f in ledger["findings_registry"]
    ), "an important pre-existing finding must not be tombstoned"
    assert ledger["computed_verdict"] != "PROCEED"


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


def test_downgraded_finding_is_still_counted_by_the_table():
    """A downgrade lowers severity; it must not remove the finding from the gate.

    Dropping it would let a missing metadata field silently delete a blocking
    finding — the reason downgraded statuses feed the table.
    """
    monitor = {
        "verdict": "needs_revision",
        "issues": [
            {
                "severity": "MEDIUM",
                "category": "unknown",
                "description": "Unclear side effect in module init",
                "was_present_before_pr": False,
                # No reach_evidence → downgraded, but still counted.
            }
        ],
    }
    ledger = map_step_runner.normalize_review_verdict(monitor_result=monitor)

    assert any(f["status"] == "downgraded" for f in ledger["findings_registry"])
    assert ledger["computed_verdict"] == "REVISE"
    assert ledger["active_count"] == 1
    assert ledger["downgraded_count"] == 1


def test_critical_without_reach_evidence_does_not_vanish():
    """A CRITICAL whose reachability was never proven still holds the gate."""
    monitor = {
        "verdict": "rejected",
        "issues": [
            {
                "severity": "CRITICAL",
                "category": "security",
                "description": "Hardcoded API key in request signer",
                "was_present_before_pr": False,
            }
        ],
    }
    ledger = map_step_runner.normalize_review_verdict(monitor_result=monitor)

    assert ledger["computed_verdict"] == "REVISE"
    assert ledger["active_count"] == 1
    assert ledger["escalation_required"] is True
    assert ledger["findings_registry"][0]["transition_reason"] == "quote_absent"


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
    # The schema's own spelling for an ordering finding is `ordering`; the mode
    # name callers use is aliased onto it rather than widening the enum.
    compare_entries = [f for f in registry if f["source_agent"] == "ordering"]
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


def test_predictor_low_risk_breaking_summary_is_advisory():
    predictor = _predictor_low_risk()
    predictor["predicted_state"]["breaking_changes"] = ["Documented API adjustment"]
    ledger = map_step_runner.normalize_review_verdict(
        monitor_result=_monitor_no_issues(), predictor_result=predictor,
    )
    assert ledger["computed_verdict"] == "PROCEED"
    assert not any(row["source_agent"] == "predictor" for row in ledger["findings_registry"])


def test_no_inputs_is_an_unobserved_review_not_a_clean_one():
    """An empty registry means the review was not seen, not that it was clean."""
    ledger = map_step_runner.normalize_review_verdict()

    assert ledger["computed_verdict"] == "REVISE"
    assert ledger["active_count"] == 1
    assert ledger["escalation_required"] is True

    finding = ledger["findings_registry"][0]
    assert finding["source_agent"] == "operator"
    assert finding["transition_reason"] == "input_integrity"
    assert finding["status"] == "active"
    assert ledger["not_verified"], "the unobserved review must be named in not_verified"


def test_parse_failure_is_recorded_as_an_active_finding():
    ledger = map_step_runner.normalize_review_verdict(
        input_errors=["monitor: invalid JSON (Expecting value at line 1)"],
    )

    assert ledger["computed_verdict"] == "REVISE"
    assert ledger["active_count"] == 1
    finding = ledger["findings_registry"][0]
    assert finding["transition_reason"] == "input_integrity"
    assert "invalid JSON" in finding["claim"]


def test_parse_failure_does_not_also_report_a_missing_review():
    """One integrity problem yields one row, not two."""
    ledger = map_step_runner.normalize_review_verdict(
        input_errors=["monitor: invalid JSON (Expecting value at line 1)"],
    )

    integrity = [
        f for f in ledger["findings_registry"]
        if f["transition_reason"] == "input_integrity"
    ]
    assert len(integrity) == 1


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
    assert result.get("findings_verdict", result["computed_verdict"]) == "PROCEED"

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


def test_write_review_verdict_ledger_empty_inputs_is_not_a_pass(branch_workspace):
    del branch_workspace

    result = map_step_runner.write_review_verdict_ledger()

    assert result["status"] == "success"
    assert result["computed_verdict"] == "REVISE"
    assert result["escalation_required"] is True


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


def test_write_review_verdict_ledger_malformed_json_is_reported_not_swallowed(
    branch_workspace,
):
    """A truncated envelope must not read as an absence of findings."""
    del branch_workspace

    result = map_step_runner.write_review_verdict_ledger(
        monitor_json="NOT VALID JSON {{{",
        predictor_json="",
        evaluator_json="",
    )

    assert result["status"] == "success"
    assert result["computed_verdict"] == "REVISE"
    assert result["input_errors"], "the parse failure must be reported"
    assert "monitor" in result["input_errors"][0]


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


def test_evaluator_low_score_alone_does_not_move_the_verdict(branch_workspace):
    """The score is advisory in BOTH directions: it cannot create a verdict either."""
    del branch_workspace

    ledger = map_step_runner.normalize_review_verdict(
        monitor_result=_monitor_no_issues(),
        evaluator_result=_evaluator_low_score(),
    )

    assert ledger["computed_verdict"] == "PROCEED"
    assert ledger["evaluator_scores"]["overall_score"] == 3


# ---------------------------------------------------------------------------
# File-based reviewer input
# ---------------------------------------------------------------------------


def test_reviewer_envelopes_are_read_from_files(branch_workspace):
    (branch_workspace / "review-agent-monitor.json").write_text(
        json.dumps(_monitor_with_critical()), encoding="utf-8"
    )

    result = map_step_runner.write_review_verdict_ledger(
        monitor_file=str(branch_workspace / "review-agent-monitor.json"),
    )

    assert result["computed_verdict"] == "BLOCK"
    assert result["input_errors"] == []


def test_missing_reviewer_file_is_reported_not_ignored(branch_workspace):
    result = map_step_runner.write_review_verdict_ledger(
        monitor_file=str(branch_workspace / "does-not-exist.json"),
    )

    assert result["computed_verdict"] == "REVISE"
    assert any("does-not-exist.json" in err for err in result["input_errors"])


# ---------------------------------------------------------------------------
# Journal continuity
# ---------------------------------------------------------------------------


def test_previous_verdict_is_recovered_from_the_ledger_on_disk(branch_workspace):
    del branch_workspace

    first = map_step_runner.write_review_verdict_ledger(
        monitor_json=json.dumps(_monitor_with_critical()),
    )
    assert first["computed_verdict"] == "BLOCK"

    # Second run supplies no --previous-verdict; the journal must still know.
    map_step_runner.write_review_verdict_ledger(
        monitor_json=json.dumps(_monitor_no_issues()),
    )

    payload = json.loads(
        (Path(".map/test-branch") / "review-verdict-ledger.json").read_text(encoding="utf-8")
    )
    assert payload["journal"]["previous_verdict"] == "BLOCK"
    assert payload["journal"]["current_verdict"] == "PROCEED"
    assert payload["journal"]["matches_previous"] is False


# ---------------------------------------------------------------------------
# write_stage_gate binding
# ---------------------------------------------------------------------------


def test_review_gate_is_refused_when_it_contradicts_the_ledger(branch_workspace):
    map_step_runner.write_review_verdict_ledger(
        monitor_json=json.dumps(_monitor_with_critical()),
    )

    result = map_step_runner.write_stage_gate("review", "ready", "code-review-001.md", "ok")

    assert result["status"] == "error"
    assert result["computed_verdict"] == "blocked"
    assert result["requested_verdict"] == "ready"
    assert not (branch_workspace / "review-gate.json").exists(), (
        "a refused gate must not be written"
    )


def test_review_gate_is_written_when_it_matches_the_ledger(branch_workspace):
    map_step_runner.write_review_verdict_ledger(
        monitor_json=json.dumps(_monitor_with_critical()),
    )

    result = map_step_runner.write_stage_gate("review", "blocked", "code-review-001.md", "")

    assert result["status"] == "success"
    assert result["ledger_enforcement"] == "enforced"
    assert (branch_workspace / "review-gate.json").exists()


def test_review_gate_binding_can_be_disabled_explicitly(branch_workspace, monkeypatch):
    monkeypatch.setenv("MAP_REVIEW_LEDGER_ENFORCE", "0")
    map_step_runner.write_review_verdict_ledger(
        monitor_json=json.dumps(_monitor_with_critical()),
    )

    result = map_step_runner.write_stage_gate("review", "ready", "code-review-001.md", "")

    assert result["status"] == "success"
    assert result["ledger_enforcement"] == "disabled_by_env"
    assert (branch_workspace / "review-gate.json").exists()


def test_non_review_stages_are_unaffected_by_the_ledger(branch_workspace):
    map_step_runner.write_review_verdict_ledger(
        monitor_json=json.dumps(_monitor_with_critical()),
    )

    result = map_step_runner.write_stage_gate("verification", "ready", "verification-summary.md", "")

    assert result["status"] == "success"
    assert result["ledger_enforcement"] == "not_applicable"
    assert (branch_workspace / "verification-gate.json").exists()


def test_review_gate_without_a_ledger_is_refused(branch_workspace):
    """/map-review is the only writer of a review gate and always writes the
    ledger first, so a missing ledger means the closeout was skipped."""
    result = map_step_runner.write_stage_gate("review", "ready", "code-review-001.md", "")

    assert result["status"] == "error"
    assert "no review-verdict-ledger.json" in result["message"]
    assert not (branch_workspace / "review-gate.json").exists()


def test_review_gate_without_a_ledger_can_be_forced(branch_workspace, monkeypatch):
    monkeypatch.setenv("MAP_REVIEW_LEDGER_ENFORCE", "0")

    result = map_step_runner.write_stage_gate("review", "ready", "code-review-001.md", "")

    assert result["status"] == "success"
    assert (branch_workspace / "review-gate.json").exists()


# ---------------------------------------------------------------------------
# Operator objections — the only supported way to contest a finding
# ---------------------------------------------------------------------------


def _seed_ledger_with_security_finding() -> None:
    map_step_runner.write_review_verdict_ledger(
        monitor_json=json.dumps(_monitor_with_high_important()),
    )


def test_removing_channel_requires_evidence(branch_workspace):
    del branch_workspace
    _seed_ledger_with_security_finding()

    result = map_step_runner.record_review_objection("RVF-001", "quote_absent", "")

    assert result["status"] == "error"
    assert "requires evidence" in result["message"]


def test_unknown_channel_is_rejected(branch_workspace):
    del branch_workspace
    _seed_ledger_with_security_finding()

    result = map_step_runner.record_review_objection("RVF-001", "i_disagree", "because")

    assert result["status"] == "error"
    assert "unknown objection channel" in result["message"]


def test_objection_against_unknown_finding_is_rejected(branch_workspace):
    del branch_workspace
    _seed_ledger_with_security_finding()

    result = map_step_runner.record_review_objection(
        "RVF-999", "quote_absent", "not in the diff"
    )

    assert result["status"] == "error"
    assert "not in the current ledger" in result["message"]


def test_objection_requires_an_existing_ledger(branch_workspace):
    del branch_workspace

    result = map_step_runner.record_review_objection("RVF-001", "no_new_fact", "")

    assert result["status"] == "error"
    assert "run write_review_verdict_ledger" in result["message"]


def test_evidenced_objection_downgrades_an_important_finding(branch_workspace):
    """Objection evidence is free text, so above `minor` it buys a downgrade.

    The retention floor is the same at both removal sites: only a finding proven
    `minor` leaves the table, whether the removal is argued by the reviewer's own
    `was_present_before_pr` flag or by an operator objection.
    """
    del branch_workspace
    _seed_ledger_with_security_finding()

    map_step_runner.record_review_objection(
        "RVF-001", "quote_absent", "grep for the concatenation returns nothing in the diff"
    )
    result = map_step_runner.write_review_verdict_ledger(
        monitor_json=json.dumps(_monitor_with_high_important()),
    )

    assert result["computed_verdict"] == "REVISE"
    assert result["tombstoned_count"] == 0
    assert result["downgraded_count"] == 1
    assert result["escalation_required"] is True


def test_operator_objection_does_not_resolve_a_minor_finding(branch_workspace):
    del branch_workspace
    monitor = {
        "verdict": "approved",
        "issues": [
            {
                "severity": "LOW",
                "category": "maintainability",
                "description": "Naming nit in helper",
                "was_present_before_pr": False,
                "reach_evidence": "grep:helper:12",
            }
        ],
    }
    map_step_runner.write_review_verdict_ledger(monitor_json=json.dumps(monitor))
    map_step_runner.record_review_objection(
        "RVF-001", "wrong_category", "the helper is generated, so this is not maintainability"
    )
    result = map_step_runner.write_review_verdict_ledger(monitor_json=json.dumps(monitor))

    assert result.get("findings_verdict", result["computed_verdict"]) == "REVISE"
    assert result["tombstoned_count"] == 0
    assert result["downgraded_count"] == 1
    assert result["escalation_required"] is False


def test_unverifiable_context_retains_the_finding_and_escalates(branch_workspace):
    del branch_workspace
    _seed_ledger_with_security_finding()

    map_step_runner.record_review_objection(
        "RVF-001", "unverifiable_context", "we never call that path in production"
    )
    result = map_step_runner.write_review_verdict_ledger(
        monitor_json=json.dumps(_monitor_with_high_important()),
    )

    assert result["computed_verdict"] == "BLOCK", "context alone cannot clear a finding"
    assert result["tombstoned_count"] == 0
    assert result["escalation_required"] is True


def test_pressure_without_a_new_fact_repeats_the_verdict(branch_workspace):
    del branch_workspace
    _seed_ledger_with_security_finding()

    map_step_runner.record_review_objection(
        "RVF-001", "no_new_fact", "this is obviously a false positive, trust me"
    )
    map_step_runner.write_review_verdict_ledger(
        monitor_json=json.dumps(_monitor_with_high_important()),
    )

    payload = json.loads(
        (Path(".map/test-branch") / "review-verdict-ledger.json").read_text(encoding="utf-8")
    )
    assert payload["computed_verdict"] == "BLOCK"
    assert payload["journal"]["repeated_verbatim"] is True
    assert payload["findings_registry"][0]["transition_reason"] == "pressure_without_new_fact"
    assert payload["findings_registry"][0]["status"] != "tombstoned"


def test_escalation_ceiling_blocks_a_clean_pass(branch_workspace):
    """Only minor findings remain, but one was contested on unverifiable context."""
    del branch_workspace
    monitor = {
        "verdict": "approved",
        "issues": [
            {
                "severity": "LOW",
                "category": "maintainability",
                "description": "Naming nit in helper",
                "was_present_before_pr": False,
                "reach_evidence": "grep:helper:12",
            }
        ],
    }
    first = map_step_runner.write_review_verdict_ledger(monitor_json=json.dumps(monitor))
    assert first["computed_verdict"] == "PROCEED"

    map_step_runner.record_review_objection(
        "RVF-001", "unverifiable_context", "the author says it is intentional"
    )
    result = map_step_runner.write_review_verdict_ledger(monitor_json=json.dumps(monitor))

    assert result["computed_verdict"] == "REVISE"
    assert result["escalation_required"] is True


def test_stale_objection_does_not_land_on_a_different_finding(branch_workspace):
    del branch_workspace
    _seed_ledger_with_security_finding()
    map_step_runner.record_review_objection(
        "RVF-001", "quote_absent", "not present in the diff"
    )

    # The reviewer now reports a completely different issue under the same id.
    other = {
        "verdict": "rejected",
        "issues": [
            {
                "severity": "CRITICAL",
                "category": "correctness",
                "description": "Unrelated data-loss bug",
                "was_present_before_pr": False,
                "reach_evidence": "test_rollback fails",
            }
        ],
    }
    result = map_step_runner.write_review_verdict_ledger(monitor_json=json.dumps(other))

    assert result["computed_verdict"] == "BLOCK"
    assert result["tombstoned_count"] == 0


def test_second_objection_replaces_the_first(branch_workspace):
    del branch_workspace
    _seed_ledger_with_security_finding()

    map_step_runner.record_review_objection("RVF-001", "no_new_fact", "come on")
    map_step_runner.record_review_objection(
        "RVF-001", "unverifiable_context", "internal-only endpoint"
    )

    stored = json.loads(
        (Path(".map/test-branch") / "review-objections.json").read_text(encoding="utf-8")
    )
    assert len(stored) == 1
    assert stored[0]["channel"] == "unverifiable_context"


# ---------------------------------------------------------------------------
# Input classification carries real values
# ---------------------------------------------------------------------------


def test_destination_and_executor_class_are_recorded(branch_workspace):
    del branch_workspace

    map_step_runner.write_review_verdict_ledger(
        monitor_json=json.dumps(_monitor_no_issues()),
        destination="ci",
        executor_class="opus",
    )

    payload = json.loads(
        (Path(".map/test-branch") / "review-verdict-ledger.json").read_text(encoding="utf-8")
    )
    assert payload["input_classification"]["destination"] == "ci"
    assert payload["input_classification"]["executor_class"] == "opus"


def test_unknown_destination_falls_back_to_unknown(branch_workspace):
    del branch_workspace

    map_step_runner.write_review_verdict_ledger(
        monitor_json=json.dumps(_monitor_no_issues()),
        destination="somewhere-else",
    )

    payload = json.loads(
        (Path(".map/test-branch") / "review-verdict-ledger.json").read_text(encoding="utf-8")
    )
    assert payload["input_classification"]["destination"] == "unknown"


def test_evidence_mode_is_derived_not_asserted(branch_workspace):
    del branch_workspace

    map_step_runner.write_review_verdict_ledger(
        monitor_json=json.dumps(_monitor_no_issues()),
    )
    structural = json.loads(
        (Path(".map/test-branch") / "review-verdict-ledger.json").read_text(encoding="utf-8")
    )
    assert structural["input_classification"]["evidence_mode"] == "structural"

    map_step_runner.write_review_verdict_ledger(
        monitor_json=json.dumps(_monitor_no_issues()),
        adversarial_json=json.dumps(
            [{"severity": "minor", "category": "tests", "claim": "second opinion"}]
        ),
        review_mode="adversarial",
    )
    independent = json.loads(
        (Path(".map/test-branch") / "review-verdict-ledger.json").read_text(encoding="utf-8")
    )
    assert independent["input_classification"]["evidence_mode"] == "independent_run"


# ---------------------------------------------------------------------------
# The artifact must satisfy its own declared schema
# ---------------------------------------------------------------------------


def test_ledger_validates_against_its_declared_schema(branch_workspace):
    """REVIEW_VERDICT_LEDGER_SCHEMA is the contract; the writer must honour it.

    Without this the schema is prose: closed enums (transition_reason,
    source_agent, previous_verdict) drift the moment a new value is emitted.
    """
    jsonschema = pytest.importorskip("jsonschema")
    from mapify_cli.schemas import REVIEW_VERDICT_LEDGER_SCHEMA

    del branch_workspace

    # Exercise every branch that writes an unusual field in one artifact:
    # pre-existing downgrade, missing reach_evidence, an unknown source_agent on
    # an adversarial row, and a parse failure.
    monitor = {
        "verdict": "rejected",
        "issues": [
            {
                "severity": "CRITICAL",
                "category": "security",
                "description": "Key material in the signer",
                "was_present_before_pr": True,
                "reach_evidence": "grep:KEY:3",
            },
            {
                "severity": "HIGH",
                "category": "correctness",
                "description": "Off-by-one with no reachability proof",
                "was_present_before_pr": False,
            },
            {
                "severity": "LOW",
                "category": "maintainability",
                "description": "Naming nit",
                "was_present_before_pr": False,
                "reach_evidence": "grep:n:1",
            },
        ],
    }
    map_step_runner.write_review_verdict_ledger(
        monitor_json=json.dumps(monitor),
        predictor_json="{ not json",
        adversarial_json=json.dumps(
            [{"severity": "minor", "category": "tests", "claim": "x",
              "source_agent": "compare_orderings"}]
        ),
        review_mode="compare_orderings",
        previous_verdict="MAYBE",
        destination="ci",
    )
    map_step_runner.record_review_objection("RVF-003", "no_new_fact", "come on")
    map_step_runner.write_review_verdict_ledger(
        monitor_json=json.dumps(monitor),
        review_mode="compare_orderings",
    )

    payload = json.loads(
        (Path(".map/test-branch") / "review-verdict-ledger.json").read_text(encoding="utf-8")
    )
    jsonschema.validate(payload, REVIEW_VERDICT_LEDGER_SCHEMA)


def test_unknown_source_agent_is_mapped_into_the_enum(branch_workspace):
    del branch_workspace

    map_step_runner.write_review_verdict_ledger(
        adversarial_json=json.dumps(
            [{"severity": "minor", "category": "tests", "claim": "x",
              "source_agent": "compare_orderings"}]
        ),
        review_mode="compare_orderings",
    )

    payload = json.loads(
        (Path(".map/test-branch") / "review-verdict-ledger.json").read_text(encoding="utf-8")
    )
    assert payload["findings_registry"][0]["source_agent"] == "ordering"


def test_genuinely_unknown_source_agent_falls_back(branch_workspace):
    del branch_workspace

    map_step_runner.write_review_verdict_ledger(
        adversarial_json=json.dumps(
            [{"severity": "minor", "category": "tests", "claim": "x",
              "source_agent": "some-new-reviewer"}]
        ),
        review_mode="adversarial",
    )

    payload = json.loads(
        (Path(".map/test-branch") / "review-verdict-ledger.json").read_text(encoding="utf-8")
    )
    assert payload["findings_registry"][0]["source_agent"] == "adversarial"


def test_unrecognized_previous_verdict_is_not_copied_into_the_journal(branch_workspace):
    del branch_workspace

    map_step_runner.write_review_verdict_ledger(
        monitor_json=json.dumps(_monitor_no_issues()),
        previous_verdict="probably fine",
    )

    payload = json.loads(
        (Path(".map/test-branch") / "review-verdict-ledger.json").read_text(encoding="utf-8")
    )
    assert payload["journal"]["previous_verdict"] is None
    assert payload["journal"]["matches_previous"] is None


# ---------------------------------------------------------------------------
# Atomic write regression tests (issue #409)
# ---------------------------------------------------------------------------


def test_write_review_verdict_ledger_uses_atomic_write(branch_workspace):
    """write_review_verdict_ledger must use _write_json_file (atomic .tmp -> replace).

    A non-atomic write_text() call would leave the ledger in an inconsistent
    state if the process is killed mid-write.  We verify the ledger JSON is
    parseable immediately after a successful call (no truncation) and that
    no residual .tmp file was left behind.
    """
    del branch_workspace

    map_step_runner.write_review_verdict_ledger(
        monitor_json=json.dumps(_monitor_no_issues()),
    )

    ledger_path = Path(".map/test-branch/review-verdict-ledger.json")
    tmp_path = ledger_path.with_suffix(".tmp")
    assert ledger_path.exists(), "ledger JSON must be written"
    assert not tmp_path.exists(), "no residual .tmp file should remain after atomic write"
    # Confirm the file is valid JSON (not truncated)
    payload = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert "computed_verdict" in payload


def test_record_review_objection_uses_atomic_write(branch_workspace):
    """record_review_objection must use _write_json_file for the objections list.

    Validates that a second objection (replacing the first) leaves a valid JSON
    array with no residual .tmp file.
    """
    del branch_workspace
    _seed_ledger_with_security_finding()

    map_step_runner.record_review_objection(
        "RVF-001", "quote_absent", "searched the diff, the quoted line is absent"
    )

    objections_path = Path(".map/test-branch/review-objections.json")
    tmp_path = objections_path.with_suffix(".tmp")
    assert objections_path.exists(), "objections file must be written"
    assert not tmp_path.exists(), "no residual .tmp file should remain after atomic write"
    records = json.loads(objections_path.read_text(encoding="utf-8"))
    assert isinstance(records, list) and len(records) == 1
    assert records[0]["channel"] == "quote_absent"


def test_write_json_file_accepts_list_payload(branch_workspace):
    """_write_json_file must accept a list payload (widened from dict-only)."""
    workspace = branch_workspace
    test_path = workspace / "test-list.json"
    sample: list = [{"a": 1}, {"b": 2}]

    map_step_runner._write_json_file(test_path, sample)  # type: ignore[attr-defined]

    assert test_path.exists()
    assert json.loads(test_path.read_text(encoding="utf-8")) == sample


# ---------------------------------------------------------------------------
# Role reviewers (user_experience / maintainer)
# ---------------------------------------------------------------------------


def _complete_role_finding(**overrides) -> dict:
    finding = {
        "id": "F-M-01",
        "reviewer": "maintainer",
        "severity": "IMPORTANT",
        "category": "duplication",
        "file_path": "cmd/install.go",
        "line_range": "40-58",
        "problem": "identical retry loop in cmd/install.go:40 and cmd/upgrade.go:66",
        "current_code": "for i := 0; i < 3; i++ { ... }",
        "proposed_code": "func retry(n int, f func() error) error { ... }",
        "why_better": "2 edit sites -> 1",
        "cost": "none",
        "evidence": "grep -n 'for i := 0; i < 3' cmd/",
    }
    finding.update(overrides)
    return finding


def test_role_finding_contract_gaps_names_every_missing_part():
    gaps = map_step_runner.role_finding_contract_gaps(
        {"problem": "flag is confusable", "current_code": "  "}
    )
    assert gaps == ["current_code", "proposed_code", "why_better", "cost"], (
        "a blank part counts as missing, not as present"
    )
    assert map_step_runner.role_finding_contract_gaps(_complete_role_finding()) == []


def test_complete_role_finding_is_counted_by_the_table():
    ledger = map_step_runner.normalize_review_verdict(
        role_findings=[_complete_role_finding()], branch="test-branch"
    )
    rows = [f for f in ledger["findings_registry"] if f["source_agent"] == "role"]
    assert len(rows) == 1
    assert rows[0]["status"] == "active"
    assert rows[0]["severity"] == "important"
    assert rows[0]["category"] == "maintainability"
    assert rows[0]["claim"].startswith("[maintainer] ")
    # Every contract part travels as evidence, so the row is reviewable on its own.
    assert {e["source"] for e in rows[0]["evidence"]} >= {
        "current_code",
        "proposed_code",
        "why_better",
        "cost",
    }
    assert ledger["computed_verdict"] == "REVISE"


def test_incomplete_role_finding_is_tombstoned_not_counted():
    """An unfinished remark must neither gate the change nor vanish."""
    incomplete = _complete_role_finding(
        id="F-M-02", severity="MINOR", proposed_code="", why_better="", cost=""
    )
    ledger = map_step_runner.normalize_review_verdict(
        role_findings=[incomplete], branch="test-branch"
    )
    row = next(f for f in ledger["findings_registry"] if f["source_agent"] == "role")
    assert row["status"] == "tombstoned"
    assert row["transition_reason"] == "contract_incomplete"
    assert "proposed_code" in row["transition_evidence"]
    assert any("contract is incomplete" in nv for nv in ledger["not_verified"])
    # A minor claim that never met the contract must not gate on its own.
    assert ledger["computed_verdict"] == "PROCEED"
    assert ledger["escalation_required"] is False


@pytest.mark.parametrize("severity", ["CRITICAL", "IMPORTANT"])
def test_dropped_high_severity_role_finding_escalates_instead_of_proceeding(severity):
    """A missing `cost` must not let a reviewer erase its own CRITICAL from the gate.

    Tombstoning keeps the row out of the decision table — a reviewer that
    stopped halfway does not gate the change. But above `minor` the claim is
    too expensive to lose silently, so the ledger escalates and PROCEED
    becomes unavailable until a human rules on it.
    """
    incomplete = _complete_role_finding(id="F-M-03", severity=severity, cost="")
    ledger = map_step_runner.normalize_review_verdict(
        role_findings=[incomplete], branch="test-branch"
    )
    row = next(f for f in ledger["findings_registry"] if f["source_agent"] == "role")
    assert row["status"] == "tombstoned", "the row still leaves the table"
    assert row["transition_reason"] == "contract_incomplete"

    assert ledger["escalation_required"] is True
    assert any(
        "output contract is incomplete" in reason and "cost" in reason
        for reason in ledger["escalation_reasons"]
    ), ledger["escalation_reasons"]
    assert ledger["computed_verdict"] == "REVISE", (
        "PROCEED must be unavailable while a high-severity claim is unresolved"
    )


@pytest.mark.parametrize("severity", ["CRITICAL", "IMPORTANT"])
def test_adversarial_mode_reports_incomplete_role_finding_without_gating(severity):
    """The adversarial path removes the finding BEFORE the ledger.

    `aggregate_adversarial_findings` is the enforcement point there, so the
    row is listed under `contract_incomplete` in the report and never becomes
    a ledger row at all — the mirror image of the normal fan-out.
    """
    report = map_step_runner.aggregate_adversarial_findings(
        role_json={
            "maintainer": json.dumps(
                {
                    "reviewer": "maintainer",
                    "all_clear": False,
                    "checks_performed": ["B"],
                    "receipt": {"covered_files": [], "skipped_files": [], "denied_access": [], "check_evidence": []},
                    "findings": [
                        _complete_role_finding(id="F-M-04", severity=severity, cost="")
                    ],
                }
            )
        }
    )
    assert report["summary"]["contract_incomplete"] == 1
    dropped = report["contract_incomplete"][0]
    assert dropped["reviewer"] == "maintainer"
    assert dropped["id"] == "F-M-04"
    assert dropped["contract_gaps"] == ["cost"]
    assert report["findings"] == [], (
        "an incomplete finding must not reach the aggregated finding list"
    )
    # ...but it MUST reach the ledger, which is a different array.
    assert report["ledger_findings"] == report["contract_incomplete"]


@pytest.mark.parametrize("severity", ["CRITICAL", "IMPORTANT"])
def test_adversarial_ledger_findings_carry_incomplete_role_findings_to_the_ledger(
    severity,
):
    """The adversarial path must not lose the claim between aggregator and ledger.

    `findings` deliberately excludes incomplete role findings so the report
    counts stay honest. Handing the ledger that array alone drops the claim
    entirely — no tombstone, no `not_verified`, no escalation — and PROCEED
    stays available. `ledger_findings` is the array that closes the gap.
    """
    report = map_step_runner.aggregate_adversarial_findings(
        role_json={
            "maintainer": json.dumps(
                {
                    "reviewer": "maintainer",
                    "all_clear": False,
                    "checks_performed": ["B"],
                    "receipt": {"covered_files": [], "skipped_files": [], "denied_access": [], "check_evidence": []},
                    "findings": [
                        _complete_role_finding(id="F-M-05", severity=severity, cost="")
                    ],
                }
            )
        }
    )

    # What the OLD handoff passed: the report array. The claim is gone —
    # no role row, no tombstone, nothing named in not_verified.
    lost = map_step_runner.normalize_review_verdict(
        adversarial_findings=report["findings"],
        review_mode="adversarial",
        branch="test-branch",
    )
    assert not any(f["source_agent"] == "role" for f in lost["findings_registry"])
    assert not any(
        f["transition_reason"] == "contract_incomplete" for f in lost["findings_registry"]
    )
    assert not any("contract is incomplete" in nv for nv in lost["not_verified"])

    # What the fixed handoff passes: same three outcomes as the normal path.
    kept = map_step_runner.normalize_review_verdict(
        adversarial_findings=report["ledger_findings"],
        review_mode="adversarial",
        branch="test-branch",
    )
    row = next(f for f in kept["findings_registry"] if f["source_agent"] == "role")
    assert row["status"] == "tombstoned"
    assert row["transition_reason"] == "contract_incomplete"
    assert row["claim"].startswith("[maintainer] ")
    assert any("contract is incomplete" in nv for nv in kept["not_verified"])
    assert kept["escalation_required"] is True
    assert kept["computed_verdict"] == "REVISE", (
        "an incomplete high-severity role finding must cost the adversarial run "
        "its PROCEED, exactly as it does on the normal fan-out"
    )


def test_adversarial_complete_role_finding_is_not_double_counted():
    """`ledger_findings` must add the dropped rows, not duplicate the kept ones."""
    report = map_step_runner.aggregate_adversarial_findings(
        role_json={
            "maintainer": json.dumps(
                {
                    "reviewer": "maintainer",
                    "all_clear": False,
                    "checks_performed": ["B"],
                    "receipt": {"covered_files": [], "skipped_files": [], "denied_access": [], "check_evidence": []},
                    "findings": [_complete_role_finding(id="F-M-06")],
                }
            )
        }
    )
    assert report["contract_incomplete"] == []
    assert report["ledger_findings"] == report["findings"]

    ledger = map_step_runner.normalize_review_verdict(
        adversarial_findings=report["ledger_findings"],
        review_mode="adversarial",
        branch="test-branch",
    )
    assert len(ledger["findings_registry"]) == 1
    assert ledger["findings_registry"][0]["status"] == "active"


def test_role_envelopes_reach_the_ledger_from_disk(branch_workspace):
    workspace = branch_workspace
    (workspace / "review-agent-maintainer.json").write_text(
        json.dumps(
            {
                "reviewer": "maintainer",
                "all_clear": False,
                "findings": [_complete_role_finding()],
                "checks_performed": ["A1", "B"],
            }
        ),
        encoding="utf-8",
    )
    (workspace / "review-agent-user_experience.json").write_text(
        json.dumps(
            {
                "reviewer": "user_experience",
                "all_clear": True,
                "all_clear_rationale": "old path unchanged; no new mandatory flag",
                "findings": [],
                "checks_performed": ["old path", "flag names"],
            }
        ),
        encoding="utf-8",
    )

    result = map_step_runner.write_review_verdict_ledger(
        role_files={
            "maintainer": str(workspace / "review-agent-maintainer.json"),
            "user_experience": str(workspace / "review-agent-user_experience.json"),
        },
        review_mode="normal",
    )

    assert result["status"] == "success"
    assert result["computed_verdict"] == "REVISE"
    payload = json.loads((workspace / "review-verdict-ledger.json").read_text(encoding="utf-8"))
    role_rows = [f for f in payload["findings_registry"] if f["source_agent"] == "role"]
    assert len(role_rows) == 1, "an all_clear role reviewer contributes no findings"
    assert role_rows[0]["claim"].startswith("[maintainer] ")


def test_all_clear_role_envelope_counts_as_supplied_input(branch_workspace):
    """A review that ran and found nothing is not "no review reached the ledger".

    Every other source keys `supplied_by_source` off envelope truthiness. If
    `role` keyed off finding COUNT instead, a role reviewer reporting
    `all_clear` with `findings: []` would contribute nothing, and a role-only
    run would report the absence of a review, escalate, and compute REVISE for
    an observed clean pass.
    """
    workspace = branch_workspace
    role_files = {}
    for role_id in ("user_experience", "maintainer"):
        path = workspace / f"review-agent-{role_id}.json"
        path.write_text(
            json.dumps(
                {
                    "reviewer": role_id,
                    "all_clear": True,
                    "all_clear_rationale": "old path unchanged; no new mandatory flag",
                    "findings": [],
                    "checks_performed": ["old path", "flag names"],
                }
            ),
            encoding="utf-8",
        )
        role_files[role_id] = str(path)

    result = map_step_runner.write_review_verdict_ledger(
        role_files=role_files, review_mode="normal"
    )

    assert result["input_errors"] == []
    payload = json.loads((workspace / "review-verdict-ledger.json").read_text(encoding="utf-8"))
    assert payload["findings_registry"] == [], (
        "an observed, clean role review must not manufacture an integrity finding"
    )
    assert not any(
        "no output was supplied" in nv for nv in payload["not_verified"]
    ), payload["not_verified"]
    assert payload["escalation_required"] is False
    assert result.get("findings_verdict", result["computed_verdict"]) == "PROCEED"


def test_no_role_envelope_at_all_is_still_reported_as_no_input(branch_workspace):
    """The negative half: nothing supplied must still fail closed."""
    del branch_workspace
    ledger = map_step_runner.normalize_review_verdict(branch="test-branch")
    assert any(
        "No reviewer output reached the ledger" in str(f.get("claim") or "")
        for f in ledger["findings_registry"]
    )
    assert ledger["escalation_required"] is True
    assert ledger["computed_verdict"] == "REVISE"

    # ...and the flag alone is enough: an envelope that parsed but carried no
    # findings is supplied input, even with `role_findings` empty.
    supplied = map_step_runner.normalize_review_verdict(
        role_inputs_supplied=True, branch="test-branch"
    )
    assert supplied["findings_registry"] == []
    assert supplied["escalation_required"] is False
    assert supplied["computed_verdict"] == "PROCEED"


def test_partial_role_roster_is_an_integrity_finding(branch_workspace):
    """One role back, the other silent = a dropped reviewer, not a clean review.

    `all_clear` from `user_experience` alone must not read as "the role fan-out
    ran". The ledger cannot demand the full roster whenever
    `review_mode="normal"` — `lightweight` mode legitimately runs Monitor alone
    under that same label — but one-of-two has no such innocent explanation.
    """
    workspace = branch_workspace
    (workspace / "review-agent-user_experience.json").write_text(
        json.dumps(
            {
                "reviewer": "user_experience",
                "all_clear": True,
                "all_clear_rationale": "old path unchanged",
                "findings": [],
                "checks_performed": ["old path"],
            }
        ),
        encoding="utf-8",
    )

    result = map_step_runner.write_review_verdict_ledger(
        role_files={
            "user_experience": str(workspace / "review-agent-user_experience.json")
        },
        review_mode="normal",
    )

    assert any(
        "maintainer" in err and "fan-out is incomplete" in err
        for err in result["input_errors"]
    ), result["input_errors"]
    assert result["computed_verdict"] != "PROCEED"


def test_no_role_envelopes_at_all_is_not_flagged_as_a_partial_roster(branch_workspace):
    """The negative half: Monitor-only lightweight review must stay clean.

    Guards the fix above from over-firing. `lightweight` runs Monitor alone and
    still labels itself `review_mode="normal"`; demanding the role roster there
    would hard-fail every legitimate Monitor-only review.
    """
    workspace = branch_workspace
    (workspace / "review-agent-monitor.json").write_text(
        json.dumps({"valid": True, "verdict": "approved", "issues": []}),
        encoding="utf-8",
    )

    result = map_step_runner.write_review_verdict_ledger(
        monitor_file=str(workspace / "review-agent-monitor.json"),
        review_mode="normal",
    )

    assert result["input_errors"] == []
    assert not any(
        "fan-out is incomplete" in nv for nv in result.get("not_verified", [])
    )
    assert result.get("findings_verdict", result["computed_verdict"]) == "PROCEED"


def test_unreadable_role_envelope_is_a_finding_not_a_clean_pass(branch_workspace):
    """A missing role envelope must not read as 'that reviewer found nothing'."""
    workspace = branch_workspace
    result = map_step_runner.write_review_verdict_ledger(
        role_files={"maintainer": str(workspace / "does-not-exist.json")},
        review_mode="normal",
    )
    assert result["computed_verdict"] in {"REVISE", "BLOCK"}
    assert any("maintainer" in err for err in result["input_errors"])


# ---------------------------------------------------------------------------
# Observed adversarial reviews and review-run isolation
# ---------------------------------------------------------------------------


def _all_clear_adversarial_report(blind_payload: str | None = "clean") -> dict:
    clean = json.dumps({
        "all_clear": True,
        "all_clear_rationale": "Reviewed the diff and found no reachable defect",
        "findings": [],
        "checks_performed": ["changed paths", "boundary inputs"],
        "receipt": {"covered_files": [], "skipped_files": [], "denied_access": [], "check_evidence": []},
    })
    return map_step_runner.aggregate_adversarial_findings(
        blind_json=clean if blind_payload == "clean" else blind_payload,
        edge_case_json=clean,
        acceptance_json=clean,
        role_json={"user_experience": clean, "maintainer": clean},
    )


@pytest.mark.parametrize("mode", ["adversarial", "compare_orderings"])
def test_all_clear_adversarial_aggregate_is_an_observed_review(branch_workspace, mode):
    report = _all_clear_adversarial_report()
    assert report["ledger_findings"] == []
    assert report["parse_errors"] == []
    assert {entry["status"] for entry in report["reviewer_status"].values()} == {"ok"}
    aggregate_path = branch_workspace / "review-agent-adversarial.json"
    aggregate_path.write_text(json.dumps(report), encoding="utf-8")

    result = map_step_runner.write_review_verdict_ledger(
        adversarial_file=str(aggregate_path), review_mode=mode,
    )

    assert result.get("findings_verdict", result["computed_verdict"]) == "PROCEED"
    assert result["input_errors"] == []
    ledger = json.loads((branch_workspace / "review-verdict-ledger.json").read_text())
    assert ledger["findings_registry"] == []
    assert ledger["escalation_required"] is False
    assert ledger["input_classification"]["review_mode"] == mode
    assert ledger["input_classification"]["evidence_mode"] == "independent_run"


@pytest.mark.parametrize("observed", [False, True])
def test_adversarial_observation_is_independent_of_finding_count(observed):
    ledger = cast(Any, map_step_runner).normalize_review_verdict(
        adversarial_findings=[], adversarial_inputs_supplied=observed,
        review_mode="adversarial", branch="test-branch",
    )
    assert ledger["computed_verdict"] == ("PROCEED" if observed else "REVISE")
    assert ledger["escalation_required"] is not observed


@pytest.mark.parametrize(
    "blind_payload",
    [None, "", "{broken", "{}", '{"all_clear":"true","findings":[]}',
     '{"all_clear":true,"findings":{}}',
     '{"all_clear":true,"findings":[{"severity":"MINOR","category":"tests"}]}'],
    ids=["missing", "empty", "invalid-json", "missing-fields", "invalid-bool",
         "invalid-findings", "contradictory-all-clear"],
)
def test_adversarial_incomplete_current_reviewer_fails_closed_with_clean_peers(
    branch_workspace, blind_payload,
):
    del branch_workspace
    result = map_step_runner.write_review_verdict_ledger(
        adversarial_json=json.dumps(_all_clear_adversarial_report(blind_payload)),
        review_mode="adversarial",
    )
    assert result["computed_verdict"] == "REVISE"
    assert any("blind" in error for error in result["input_errors"]), result


@pytest.mark.parametrize("broken_field", ["schema_version", "ledger_findings", "parse_errors"])
def test_malformed_tagged_adversarial_aggregate_is_not_a_legacy_finding(
    branch_workspace, broken_field,
):
    del branch_workspace
    report = _all_clear_adversarial_report()
    report[broken_field] = "adversarial_aggregate.v999" if broken_field == "schema_version" else {}
    result = map_step_runner.write_review_verdict_ledger(
        adversarial_json=json.dumps(report), review_mode="adversarial",
    )
    assert result["computed_verdict"] == "REVISE"
    assert result["input_errors"], "a malformed aggregate must be reported as input integrity"


@pytest.mark.parametrize("container", ["empty-list", "empty-dict", "finding-list", "finding-dict"])
def test_legacy_adversarial_payload_compatibility(branch_workspace, container):
    del branch_workspace
    finding = {"severity": "critical", "category": "correctness", "claim": "Data loss"}
    payload = {"empty-list": [], "empty-dict": {}, "finding-list": [finding], "finding-dict": finding}[
        container
    ]
    result = map_step_runner.write_review_verdict_ledger(
        adversarial_json=json.dumps(payload), review_mode="adversarial",
    )
    assert result["computed_verdict"] == ("REVISE" if container.startswith("empty-") else "BLOCK")
    assert result["input_errors"] == []


@pytest.mark.parametrize("compare", [False, True])
def test_quick_adversarial_clean_round_completes_with_unscheduled_edge(branch_workspace, compare):
    runner = cast(Any, map_step_runner)
    runner.begin_review_run(arguments="--adversarial --quick" + (" --compare-orderings" if compare else ""))
    report = _all_clear_adversarial_report()
    report["reviewer_status"]["edge_case"] = {"status": "not_run"}
    directories = [branch_workspace] if not compare else [branch_workspace / "review-collections" / name for name in ("default", "reverse")]
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "review-agent-adversarial.json").write_text(json.dumps(report))
    result = runner.write_review_verdict_ledger(current_run=True)
    assert result["status"] == "success", result
    assert result.get("findings_verdict", result["computed_verdict"]) == "PROCEED"


def test_monitor_location_only_distinct_files_do_not_merge(branch_workspace):
    runner = cast(Any, map_step_runner)
    runner.begin_review_run(scheduled_reviewers=["monitor"], round_id="1")
    first = {"severity": "CRITICAL", "category": "correctness", "description": "Missing authorization check",
             "reach_evidence": "reachable", "location": "a.py:10"}
    envelope = {"issues": [first, {**first, "severity": "LOW", "location": "b.py:20"}]}
    (branch_workspace / "review-agent-monitor.json").write_text(json.dumps(envelope))
    result = runner.write_review_verdict_ledger(current_run=True)
    assert result["computed_verdict"] == "BLOCK"
    ledger = json.loads((branch_workspace / "review-verdict-ledger.json").read_text())
    assert len(ledger["findings_registry"]) == 2


@pytest.mark.parametrize("flags", ["--adversarial", "--adversarial --quick", "--adversarial --quick --compare-orderings"])
def test_adversarial_originating_reviewer_can_resolve_prior_finding(review_git_workspace, flags):
    """Accept bound resolution evidence from the originating adversarial reviewer."""
    branch_workspace = review_git_workspace
    runner = cast(Any, map_step_runner)
    runner.begin_review_run(arguments=flags, round_id="1")
    result = _capture_aggregate(_produced_adversarial_report(), "1", flags)
    assert result["status"] == "success", result
    assert result["computed_verdict"] != "PROCEED"
    assert runner.abandon_review_round("1", reason="Continue findings review in a new attempt")["status"] == "success"
    admission = runner.begin_review_run(arguments=flags, round_id="2")
    runner.create_review_bundle()
    report = _captured_adversarial_resolution(runner, admission, "2", "blind", flags)
    result = _capture_aggregate(report, "2", flags)
    assert result["status"] == "success", result
    assert result.get("findings_verdict", result["computed_verdict"]) == "PROCEED"
    ledger = json.loads((branch_workspace / "review-verdict-ledger.json").read_text())
    assert ledger["findings_registry"][0]["reported_by"] == ["blind"]


def test_adversarial_distinct_defects_survive_round_merge(branch_workspace):
    runner = cast(Any, map_step_runner)
    runner.begin_review_run(arguments="--adversarial", round_id="1")
    report = _all_clear_adversarial_report()
    report["ledger_findings"] = [
        {"severity": "critical", "category": "correctness", "file_path": "a.py", "failure_mode": "data loss", "evidence": []},
        {"severity": "minor", "category": "correctness", "file_path": "a.py", "failure_mode": "small defect", "evidence": []},
    ]
    (branch_workspace / "review-agent-adversarial.json").write_text(json.dumps(report))
    result = runner.write_review_verdict_ledger(current_run=True)
    assert result["computed_verdict"] == "REVISE"
    ledger = json.loads((branch_workspace / "review-verdict-ledger.json").read_text())
    assert len(ledger["findings_registry"]) == 2
    assert all(row["validation"]["verdict"] == "insufficient_evidence" for row in ledger["findings_registry"])


def test_moved_finding_retains_identity_and_resolves_without_phantom(review_git_workspace):
    """Preserve finding identity across moved anchors and checked resolution."""
    branch_workspace = review_git_workspace
    runner = cast(Any, map_step_runner)
    for number, line in ((1, 10), (2, 11)):
        runner.begin_review_run(scheduled_reviewers=["monitor"], round_id=str(number))
        envelope = _monitor_with_critical()
        envelope["issues"][0].update({"file": "rollback.py", "line": line})
        (branch_workspace / "review-agent-monitor.json").write_text(json.dumps(envelope))
        runner.write_review_verdict_ledger(current_run=True)
        assert runner.abandon_review_round(str(number), reason="Continue findings review in a new attempt")["status"] == "success"
    ledger = json.loads((branch_workspace / "review-verdict-ledger.json").read_text())
    assert len(ledger["findings_registry"]) == 1
    admission = _admit_receipt_review(runner, round_id="3")
    _capture_monitor_resolution(runner, admission, "3", evidence="new regression passes")
    assert runner.write_review_verdict_ledger(current_run=True)["findings_verdict"] == "PROCEED"
    ledger = json.loads((branch_workspace / "review-verdict-ledger.json").read_text())
    assert len(ledger["findings_registry"]) == 1
    assert ledger["findings_registry"][0]["id"] == "RVF-001"
    assert ledger["findings_registry"][0]["status"] == "tombstoned"


@pytest.mark.parametrize("owner,other", [("maintainer", "user_experience"), ("user_experience", "maintainer")])
def test_role_resolution_cannot_close_another_role_finding(branch_workspace, owner, other):
    """Reject resolution evidence from a different role reviewer."""
    runner = cast(Any, map_step_runner)
    runner.begin_review_run(round_id="first")
    envelopes = {"monitor": _monitor_no_issues(), "predictor": _predictor_low_risk(),
                 "evaluator": _evaluator_high_score(), "maintainer": {"all_clear": True, "findings": []},
                 "user_experience": {"all_clear": True, "findings": []}}
    finding = {"severity": "critical", "category": "correctness", "claim": "Broken workflow",
               "proof": "call trace", "cost": "user loses state", "counterfactual": "old path retained state",
               "failure_mode": "restart loses state", "anchor": "workflow.py:12"}
    envelopes[owner] = {"all_clear": False, "findings": [finding]}
    for role, envelope in envelopes.items():
        (branch_workspace / f"review-agent-{role}.json").write_text(json.dumps(envelope))
    runner.write_review_verdict_ledger(current_run=True)
    ledger = json.loads((branch_workspace / "review-verdict-ledger.json").read_text())
    target = next(row for row in ledger["findings_registry"] if "Broken workflow" in row["claim"])
    assert runner.abandon_review_round("first", reason="Continue findings review in a new attempt")["status"] == "success"
    runner.begin_review_run(round_id="second")
    envelopes[owner] = {"all_clear": True, "findings": []}
    envelopes[other]["resolved_findings"] = [{"finding_id": target["id"], "evidence": "fixed"}]
    for role, envelope in envelopes.items():
        (branch_workspace / f"review-agent-{role}.json").write_text(json.dumps(envelope))
    result = runner.write_review_verdict_ledger(current_run=True)
    assert result["status"] == "error"
    assert "originating reviewer" in result["message"]


def test_incomplete_round_recovers_without_counting_and_rejects_stale_finalizer(review_git_workspace):
    """Complete a pending collection once and reject its stale finalizer."""
    del review_git_workspace
    runner = cast(Any, map_step_runner)
    admission = _admit_receipt_review(runner, round_id="first")
    result = runner.write_review_verdict_ledger(current_run=True, round_id="first")
    assert result["convergence"]["outcome"] == "incomplete"
    assert not result["convergence"].get("completed_rounds")
    assert runner.begin_review_run(scheduled_reviewers=["monitor"], round_id="second")["status"] == "error"
    _capture_complete_monitor(runner, admission, "first")
    result = runner.write_review_verdict_ledger(current_run=True, round_id="first")
    assert result["convergence"]["completed_rounds"] == 1
    runner.begin_review_run(scheduled_reviewers=["monitor"], round_id="second")
    assert runner.write_review_verdict_ledger(current_run=True, round_id="first")["status"] == "error"


def test_completed_round_rejects_changed_submission_and_corrupt_history(review_git_workspace):
    """Keep completed submissions and damaged convergence history immutable."""
    branch_workspace = review_git_workspace
    runner = cast(Any, map_step_runner)
    admission = _admit_receipt_review(runner, round_id="first")
    capture = branch_workspace / "review-agent-monitor.json"
    _capture_complete_monitor(runner, admission, "first")
    runner.write_review_verdict_ledger(current_run=True)
    capture.write_text(json.dumps(_monitor_no_issues()))
    assert runner.write_review_verdict_ledger(current_run=True)["status"] == "error"
    (branch_workspace / "review-verdict-ledger.json").write_text("{")
    assert runner.begin_review_run(scheduled_reviewers=["monitor"], round_id="second")["status"] == "error"
    assert capture.exists()


@pytest.mark.parametrize("ordering", ["", "default", "reverse"])
def test_archive_interruption_resumes_same_admission(branch_workspace, monkeypatch, ordering):
    """Recover moved captures and their receipt paths after an interrupted admission."""
    runner = cast(Any, map_step_runner)
    mode = "compare_orderings" if ordering else "normal"
    admission = runner.begin_review_run(review_mode=mode, scheduled_reviewers=["monitor"], round_id="first")
    assert admission["status"] == "success", admission
    assert runner.capture_review_output("monitor", json.dumps(_monitor_no_issues()), "first",
                                        ordering=ordering)["status"] == "success"
    ledger_path = branch_workspace / "review-verdict-ledger.json"
    ledger = json.loads(ledger_path.read_text())
    witness = ledger["convergence"]["rounds"][0]["receipts"][f"{ordering or 'default'}:monitor"]
    old_capture = (branch_workspace / witness["artifact"]).read_bytes()
    assert runner.abandon_review_round("first", reason="Exercise archive recovery")["status"] == "success"
    rename = Path.rename

    def interrupt(self, target):
        rename(self, target)
        raise OSError("interrupted after move")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "rename", interrupt)
        assert runner.begin_review_run(review_mode=mode, scheduled_reviewers=["monitor"],
                                       round_id="second")["status"] == "error"
    assert runner.begin_review_run(review_mode=mode, scheduled_reviewers=["monitor"], round_id="second")["resumed"]
    archives = list(branch_workspace.rglob("review-agent-monitor.json"))
    assert len(archives) == 1 and archives[0].read_bytes() == old_capture
    ledger = json.loads(ledger_path.read_text())
    assert len(ledger["convergence"]["rounds"]) == 2
    relocated = ledger["convergence"]["rounds"][0]["receipts"][f"{ordering or 'default'}:monitor"]
    assert (branch_workspace / relocated["artifact"]) == archives[0]
    assert {key: value for key, value in relocated.items() if key != "artifact"} == {
        key: value for key, value in witness.items() if key != "artifact"}
    assert hashlib.sha256(archives[0].read_bytes()).hexdigest() == relocated["sha256"]


def test_incremental_scope_includes_dependent_modules_and_falls_back(branch_workspace, monkeypatch):
    """A delivered and captured baseline enables dependent scope with conservative fallback."""
    runner = cast(Any, map_step_runner)
    monkeypatch.chdir(branch_workspace.parents[1])
    import subprocess

    def git(*args):
        return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout.strip()

    git("init", "-b", "main")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Test")
    Path(".gitignore").write_text(".map/\n")
    Path("core.py").write_text("VALUE = 1\n")
    Path("consumer.py").write_text("from core import VALUE\n")
    git("add", ".")
    git("commit", "-m", "base")
    git("checkout", "-b", "feature")
    Path("core.py").write_text("VALUE = 2\n")
    git("commit", "-am", "first")
    Path(".gitignore").write_text(".map/\n.claude/\n")
    git("commit", "-am", "ignore installed profiles")
    admission = _admit_receipt_review(runner, round_id="baseline")
    prompts = runner.build_review_prompts(review_bundle_text="bundle")
    assert prompts["review_scope"]["kind"] == "full"
    envelope = _monitor_with_critical()
    envelope["receipt"] = {"covered_files": admission["required_files"], "skipped_files": [],
                           "denied_access": [], "check_evidence": []}
    context_id = prompts["prompts"]["monitor"]["context_transport"]["context_id"]
    delivery = runner.bind_review_context("monitor", context_id, "baseline-monitor", "baseline")
    while delivery["status"] == "context_pending":
        pending = delivery["remaining"][0]
        request = {"type": "context_request", "context_id": context_id,
                   "resource_id": pending["resource_id"], "offset": pending["offset"]}
        chunk = runner.serve_review_context("monitor", json.dumps(request), "baseline",
                                             session_id=delivery["session_id"], agent_id="baseline-monitor")
        assert chunk["status"] == "context_response", chunk
        delivery = runner.ack_review_context(delivery["session_id"], "baseline-monitor", json.dumps(chunk), "baseline")
    assert delivery["status"] == "context_ready", delivery
    envelope["context_receipt"] = {"session_id": delivery["session_id"],
                                   "finalization_token": delivery["finalization_token"]}
    assert runner.capture_review_output("monitor", json.dumps(envelope), "baseline")["status"] == "success"
    runner.write_review_verdict_ledger(current_run=True)
    Path("core.py").write_text("VALUE = 3\n")
    git("commit", "-am", "fix")
    runner.begin_review_run(scheduled_reviewers=["monitor"], round_id="2")
    prompts = runner.build_review_prompts(review_bundle_text="bundle")
    assert prompts["review_scope"]["kind"] == "incremental"
    assert prompts["review_scope"]["affected_files"] == ["consumer.py", "core.py"]
    assert "VALUE = 3" in prompts["prompts"]["monitor"]["prompt"]
    assert "Receipt coverage must still satisfy the admitted required_files scope" in prompts["prompts"]["monitor"]["prompt"]
    assert "unresolved findings only" not in prompts["prompts"]["monitor"]["prompt"]
    Path("unknown.txt").write_text("untracked impact")
    assert runner.build_review_prompts(review_bundle_text="bundle")["review_scope"]["kind"] == "full"


def test_publication_suppresses_only_acknowledged_unchanged_revision(branch_workspace):
    """Republish only new or changed finding revisions at each destination."""
    runner = cast(Any, map_step_runner)
    runner.begin_review_run(scheduled_reviewers=["monitor"], round_id="1")
    capture = branch_workspace / "review-agent-monitor.json"
    capture.write_text(json.dumps(_monitor_with_critical()))
    runner.write_review_verdict_ledger(current_run=True)
    first = runner.review_publication(destination="github:pr/1")
    assert len(first["publishable"]) == 1
    revision = first["publishable"][0]["revision_id"]
    runner.review_publication(destination="github:pr/1", acknowledge=[revision])
    assert runner.review_publication(destination="github:pr/1")["publishable"] == []
    assert runner.review_publication(destination="github:pr/2")["publishable"]
    assert runner.abandon_review_round("1", reason="Continue findings review in a new attempt")["status"] == "success"
    runner.begin_review_run(scheduled_reviewers=["monitor"], round_id="2")
    changed = _monitor_with_critical()
    changed["issues"][0]["reach_evidence"] = "New reproducer: rollback loses both writers"
    changed["issues"].append({**changed["issues"][0], "description": "Different rollback leak"})
    capture.write_text(json.dumps(changed))
    runner.write_review_verdict_ledger(current_run=True)
    assert len(runner.review_publication(destination="github:pr/1")["publishable"]) == 2


def test_explicit_rereview_resolution_allows_third_round_pass(review_git_workspace):
    """Count earlier abandoned attempts when a verified third round passes."""
    branch_workspace = review_git_workspace
    runner = cast(Any, map_step_runner)
    for number in (1, 2):
        runner.begin_review_run(scheduled_reviewers=["monitor"], round_id=str(number))
        (branch_workspace / "review-agent-monitor.json").write_text(json.dumps(_monitor_with_critical()))
        runner.write_review_verdict_ledger(current_run=True)
        assert runner.abandon_review_round(str(number), reason="Continue findings review in a new attempt")["status"] == "success"
    admission = _admit_receipt_review(runner, round_id="3")
    _capture_monitor_resolution(runner, admission, "3", evidence="Reproducer now passes on corrected rollback path")
    result = runner.write_review_verdict_ledger(current_run=True)
    assert result.get("findings_verdict", result["computed_verdict"]) == "PROCEED"
    assert result["convergence"]["outcome"] == "passed"
    assert result["convergence"]["rounds_to_pass"] == 3
    assert result["convergence"]["duration_seconds"] >= 0


def test_round_keeps_omitted_unresolved_findings(branch_workspace):
    """Keep omitted findings and route their resolution requests to the owner."""
    runner = cast(Any, map_step_runner)
    runner.begin_review_run(scheduled_reviewers=["monitor"], round_id="first")
    capture = branch_workspace / "review-agent-monitor.json"
    capture.write_text(json.dumps(_monitor_with_critical()))
    runner.write_review_verdict_ledger(current_run=True)
    assert runner.abandon_review_round("first", reason="Continue findings review in a new attempt")["status"] == "success"
    runner.begin_review_run(scheduled_reviewers=["monitor"], round_id="second")
    capture.write_text(json.dumps(_monitor_no_issues()))
    result = runner.write_review_verdict_ledger(current_run=True)
    assert result["computed_verdict"] == "BLOCK"
    ledger = json.loads((branch_workspace / "review-verdict-ledger.json").read_text())
    assert ledger["findings_registry"]
    assert len(ledger["convergence"]["rounds"]) == 2
    prompts = runner.build_review_prompts(review_bundle_text="bundle")
    assert prompts["review_scope"]["kind"] == "full"
    assert "RVF-001" in prompts["prompts"]["monitor"]["prompt"]
    assert "<carried_findings_for_this_reviewer>" in prompts["prompts"]["monitor"]["prompt"]
    assert "structured object in resolved_findings" in prompts["prompts"]["monitor"]["prompt"]
    assert "<carried_findings_for_this_reviewer>" not in prompts["prompts"]["predictor"]["prompt"]
    assert "RVF-001" in runner.build_adversarial_review_prompts()["prompts"]["blind"]["prompt"]


def test_carried_finding_requests_only_its_originator():
    runner = cast(Any, map_step_runner)
    scope = {"unresolved_findings": [
        {"id": "RVF-002", "source_agent": "role", "originating_reviewer": "maintainer",
         "claim": "Retry loses writes", "affected_files": ["writer.py"]},
        {"id": "RVF-003", "source_agent": "adversarial", "reported_by": ["blind"],
         "claim": "Rollback race", "affected_files": ["writer.py"]},
    ]}
    assert "RVF-002" in runner._review_resolution_request("base", scope, "maintainer")
    assert "RVF-003" not in runner._review_resolution_request("base", scope, "maintainer")
    assert "RVF-003" in runner._review_resolution_request("base", scope, "blind")
    assert runner._review_resolution_request("base", scope, "predictor") == "base"


def test_reviewer_schemas_expose_checked_finding_and_resolution_fields():
    runner = cast(Any, map_step_runner)
    for role in ("monitor", "predictor", "evaluator", "user_experience", "maintainer"):
        schema = runner.AGENT_OUTPUT_SCHEMAS[role]
        assert "resolved_findings" in schema["skeleton"]
        assert "resolved_findings" not in schema["required_keys"]
        assert "a nonempty evidence string" in schema["skeleton"]["resolved_findings"]
    for finding in (runner.AGENT_OUTPUT_SCHEMAS["monitor"]["skeleton"]["issues"][0],
                    runner.ROLE_FINDING_SCHEMA["findings"][0],
                    runner.ADVERSARIAL_FINDING_SCHEMA["findings"][0]):
        assert set(runner.REVIEW_FINDING_EVIDENCE_SCHEMA).issubset(finding)
    assert "resolved_findings" in runner.ADVERSARIAL_FINDING_SCHEMA
    predictor = runner.AGENT_OUTPUT_SCHEMAS["predictor"]["skeleton"]
    assert set(runner.REVIEW_FINDING_EVIDENCE_SCHEMA).issubset(predictor)


def test_review_round_retry_and_cap_are_durable(review_git_workspace):
    """Seal complete unsuccessful rounds once and enforce the three-attempt cap."""
    branch_workspace = review_git_workspace
    runner = cast(Any, map_step_runner)
    for number in range(1, 4):
        round_id = f"iteration-{number}"
        admitted = _admit_receipt_review(runner, round_id=round_id)
        assert admitted["status"] == "success"
        capture = branch_workspace / "review-agent-monitor.json"
        _capture_complete_monitor(runner, admitted, round_id)
        assert _admit_receipt_review(runner, round_id=round_id)["resumed"]
        assert capture.exists()
        result = runner.write_review_verdict_ledger(current_run=True)
        assert result["convergence"]["completed_rounds"] == number
        assert runner.write_review_verdict_ledger(current_run=True)["convergence"] == result["convergence"]
    before = {p.name: p.read_bytes() for p in branch_workspace.glob("review-*.json")}
    rejected = runner.begin_review_run(scheduled_reviewers=["monitor"], round_id="iteration-4")
    assert rejected["status"] == "error"
    assert rejected["stop_reason"] == "reconsider_approach"
    assert {p.name: p.read_bytes() for p in branch_workspace.glob("review-*.json")} == before
    ledger = json.loads((branch_workspace / "review-verdict-ledger.json").read_text())
    assert ledger["computed_verdict"] == "BLOCK"
    assert ledger["convergence"]["outcome"] == "capped"
    assert ledger["convergence"]["rounds_to_pass"] is None


def test_begin_review_run_archives_only_inputs_and_gate_preserving_journal(branch_workspace):
    """Archive each owned reviewer capture while retaining findings and audit history."""
    workspace = branch_workspace
    map_step_runner.write_review_verdict_ledger(monitor_json=json.dumps(_monitor_with_critical()))
    map_step_runner.record_review_objection("RVF-001", "no_new_fact", "retain this objection")
    preserved_names = (
        "review-verdict-ledger.json", "review-verdict-ledger.md", "review-objections.json",
    )
    preserved = {name: (workspace / name).read_bytes() for name in preserved_names}
    stale_names = (
        *(f"review-agent-{role}.json" for role in (
            "monitor", "predictor", "evaluator", "adversarial", "user_experience", "maintainer", "security",
        )),
        *(f"adversarial-{role}.json" for role in (
            "blind", "edge", "acceptance", "user-experience", "maintainer", "security",
        )),
        "review-mode.json", "review-gate.json",
    )
    stale = {name: json.dumps({"previous_input": name}).encode() for name in stale_names}
    untouched = {
        "review-agent-unrelated.json": b"not a runner-owned reviewer",
        "adversarial-unrelated.json": b"not a runner-owned raw envelope",
        "code-review-001.md": b"previous walkthrough",
    }
    for name, content in {**stale, **untouched}.items():
        (workspace / name).write_bytes(content)

    result = cast(Any, map_step_runner).begin_review_run(
        review_mode="adversarial",
        scheduled_reviewers=["blind", "edge_case", "acceptance", "user_experience", "maintainer"],
    )

    assert result["status"] == "success"
    for name, content in stale.items():
        archived = [path for path in workspace.rglob(name) if path != workspace / name]
        assert len(archived) == 1, name
        assert archived[0].read_bytes() == content
        if name != "review-mode.json":
            assert not (workspace / name).exists(), name
    for name, content in {**preserved, **untouched}.items():
        if name == "review-verdict-ledger.json":
            updated = json.loads((workspace / name).read_text())
            convergence = updated.pop("convergence")
            consent = updated.pop("human_consent")
            assert consent == result["human_consent"]
            assert consent["status"] == "pending"
            holds = json.loads((workspace / "approval_holds.json").read_text())
            hold = holds["holds"][consent["hold_id"]]
            assert hold["kind"] == "review_consent"
            assert hold["state"] == "pending"
            assert hold["enforcement"] == "shadow"
            assert hold["review_binding"] == {
                "target": result["target"], "policy_hash": result["policy_hash"],
                "action": "review-ready",
            }
            assert convergence["outcome"] == "incomplete"
            assert convergence["stop_reason"] == "review_pending"
            assert not map_step_runner.get_pending_holds()["resume_blocked"]
            assert updated == json.loads(content)
        else:
            assert (workspace / name).read_bytes() == content
        assert list(workspace.rglob(name)) == [workspace / name], name
    mode = json.loads((workspace / "review-mode.json").read_text())
    assert mode["review_mode"] == "adversarial"
    assert mode["scheduled_reviewers"] == [
        "blind", "edge_case", "acceptance", "user_experience", "maintainer",
    ]
    map_step_runner.write_review_verdict_ledger(monitor_json=json.dumps(_monitor_no_issues()))
    ledger = json.loads((workspace / "review-verdict-ledger.json").read_text())
    assert ledger["computed_verdict"] == "BLOCK"
    assert ledger["convergence"]["outcome"] == "incomplete"


def test_same_mode_review_reruns_do_not_overwrite_archived_inputs(branch_workspace):
    """Preserve earlier archives when an incomplete collection is abandoned."""
    workspace = branch_workspace
    begin = cast(Any, map_step_runner).begin_review_run
    (workspace / "review-agent-monitor.json").write_text("stale", encoding="utf-8")
    begin(review_mode="normal", scheduled_reviewers=["monitor"], round_id="first")
    payload = json.dumps(_monitor_with_critical())
    (workspace / "review-agent-monitor.json").write_text(payload, encoding="utf-8")
    map_step_runner.write_review_verdict_ledger(current_run=True)
    assert map_step_runner.abandon_review_round("first", reason="Continue with a fresh collection")["status"] == "success"
    begin(review_mode="normal", scheduled_reviewers=["monitor"], round_id="second")
    archives = list(workspace.rglob("review-agent-monitor.json"))
    assert len(archives) == 2
    assert {path.read_text() for path in archives} == {"stale", payload}
    assert not (workspace / "review-agent-monitor.json").exists()


@pytest.mark.parametrize(
    ("arguments", "mode", "reviewers"),
    [
        ("check user's config", "normal", ["monitor", "predictor", "evaluator", "user_experience", "maintainer"]),
        ('review the "new config', "normal", ["monitor", "predictor", "evaluator", "user_experience", "maintainer"]),
        ("check user's config --adversarial --quick", "adversarial", ["blind", "acceptance", "user_experience", "maintainer"]),
        ('review "new config --compare-orderings', "compare_orderings", ["monitor", "predictor", "evaluator", "user_experience", "maintainer"]),
    ],
    ids=["apostrophe", "unbalanced-quote", "prose-quick-flags", "prose-compare-flag"],
)
def test_review_start_accepts_free_prose_preserving_arguments(branch_workspace, arguments, mode, reviewers):
    result = map_step_runner.begin_review_run(arguments=arguments)
    assert result["status"] == "success"
    persisted = json.loads((branch_workspace / "review-mode.json").read_text())
    assert persisted["arguments"] == arguments
    assert persisted["review_mode"] == mode
    assert persisted["scheduled_reviewers"] == reviewers


def test_review_start_preserves_sibling_hint(branch_workspace):
    result = map_step_runner.begin_review_run(mode="sibling-aware", sibling_hint="port of sibling/install.py")
    assert result["status"] == "success"
    persisted = json.loads((branch_workspace / "review-mode.json").read_text())
    assert persisted["mode"] == "sibling-aware"
    assert persisted["sibling_hint"] == "port of sibling/install.py"


def test_current_run_requires_tagged_adversarial_evidence(branch_workspace):
    map_step_runner.begin_review_run(arguments="--adversarial")
    (branch_workspace / "review-agent-adversarial.json").write_text(json.dumps([
        {"severity": "minor", "category": "tests", "claim": "Finding without roster evidence"},
    ]), encoding="utf-8")
    result = map_step_runner.write_review_verdict_ledger(current_run=True)
    assert result["computed_verdict"] == "REVISE"
    assert any("tagged aggregate" in error for error in result["input_errors"])


def test_archive_failure_aborts_review_start_before_new_mode(branch_workspace, monkeypatch):
    marker = branch_workspace / "review-agent-monitor.json"
    marker.write_text("prior review", encoding="utf-8")

    def fail_rename(self, target):
        del self, target
        raise OSError("archive unavailable")

    monkeypatch.setattr(Path, "rename", fail_rename)
    result = map_step_runner.begin_review_run(scheduled_reviewers=["monitor"])
    assert result["status"] == "error"
    assert "archive unavailable" in result["message"]
    assert marker.read_text() == "prior review"
    assert not (branch_workspace / "review-mode.json").exists()


@pytest.mark.parametrize("missing_collection", [False, True], ids=["both-returned", "reverse-missing"])
@pytest.mark.parametrize("adversarial", [False, True], ids=["normal", "adversarial"])
def test_compare_orderings_preserves_both_collections(branch_workspace, missing_collection, adversarial):
    workspace = branch_workspace
    map_step_runner.begin_review_run(arguments="--compare-orderings" + (" --adversarial" if adversarial else ""))
    for label in ("default", "reverse"):
        directory = workspace / "review-collections" / label
        directory.mkdir(parents=True, exist_ok=True)
        if label == "reverse" and missing_collection:
            continue
        if adversarial:
            report = _all_clear_adversarial_report()
            if label == "default":
                report["ledger_findings"] = [{
                    "severity": "important", "category": "performance", "claim": "First collection hot-path regression",
                }]
            (directory / "review-agent-adversarial.json").write_text(json.dumps(report), encoding="utf-8")
        else:
            envelopes = {
                "monitor": _monitor_no_issues(), "predictor": _predictor_low_risk(), "evaluator": _evaluator_high_score(),
                "user_experience": {"all_clear": True, "findings": []},
                "maintainer": {"all_clear": True, "findings": []},
            }
            if label == "default":
                envelopes["monitor"] = {"issues": [{
                    "severity": "HIGH", "category": "performance", "description": "First collection hot-path regression",
                    "reach_evidence": "benchmark reproduces", "was_present_before_pr": False,
                }]}
            for reviewer, envelope in envelopes.items():
                (directory / f"review-agent-{reviewer}.json").write_text(json.dumps(envelope), encoding="utf-8")
    result = map_step_runner.write_review_verdict_ledger(current_run=True)
    assert result["computed_verdict"] == "REVISE"
    ledger = json.loads((workspace / "review-verdict-ledger.json").read_text())
    assert any("First collection" in row["claim"] for row in ledger["findings_registry"])
    assert bool(result["input_errors"]) is missing_collection
    if missing_collection:
        assert any("reverse" in error for error in result["input_errors"])


def test_ledger_with_role_findings_validates_against_its_declared_schema(branch_workspace):
    """Role rows must satisfy the declared schema, not just the writer.

    The registry's `source_agent` and `transition_reason` are CLOSED enums; a
    role reviewer emits `role` and `contract_incomplete`, so a ledger carrying
    either value is the exact drift this schema exists to catch.
    """
    jsonschema = pytest.importorskip("jsonschema")
    from mapify_cli.schemas import REVIEW_VERDICT_LEDGER_SCHEMA

    workspace = branch_workspace
    (workspace / "review-agent-maintainer.json").write_text(
        json.dumps(
            {
                "reviewer": "maintainer",
                "all_clear": False,
                "checks_performed": ["A1"],
                "findings": [
                    _complete_role_finding(),
                    _complete_role_finding(id="F-M-99", proposed_code="", cost=""),
                ],
            }
        ),
        encoding="utf-8",
    )

    map_step_runner.write_review_verdict_ledger(
        role_files={"maintainer": str(workspace / "review-agent-maintainer.json")},
        review_mode="normal",
    )

    payload = json.loads((workspace / "review-verdict-ledger.json").read_text(encoding="utf-8"))
    statuses = {f["status"] for f in payload["findings_registry"]}
    assert statuses == {"active", "tombstoned"}, "both role branches must be exercised"
    assert any(
        f["transition_reason"] == "contract_incomplete" for f in payload["findings_registry"]
    )
    jsonschema.validate(payload, REVIEW_VERDICT_LEDGER_SCHEMA)


# PR #525: exercise the aggregate producer, not fabricated ledger_findings.
def _produced_adversarial_report(reporters=("blind",), *, evidence="writer.py:10 drops the committed write", resolutions=None,
                                 captured_round=None, receipt=None, capture_flags="--adversarial"):
    finding = {"severity": "CRITICAL", "category": "correctness", "file_path": "writer.py",
               "line_range": "10-12", "symbol": "write", "failure_mode": "Committed write is lost",
               "evidence": evidence}
    envelopes = {}
    for reviewer in ("blind", "edge_case", "acceptance", "maintainer", "user_experience"):
        entries = [finding] if reviewer in reporters else []
        envelope = {"all_clear": not entries, "findings": entries, "checks_performed": ["write rollback"],
                    "receipt": {"covered_files": [], "skipped_files": [], "denied_access": [], "check_evidence": []}}
        if resolutions and reviewer in resolutions:
            envelope["resolved_findings"] = resolutions[reviewer]
        if receipt is not None:
            envelope["receipt"] = receipt
        envelopes[reviewer] = json.dumps(envelope)
        if captured_round is not None and resolutions and reviewer in resolutions:
            for ordering in (("default", "reverse") if "--compare-orderings" in capture_flags else ("",)):
                result = cast(Any, map_step_runner).capture_review_output(
                    reviewer, envelopes[reviewer], captured_round, ordering=ordering)
                assert result["status"] == "success", result
    return map_step_runner.aggregate_adversarial_findings(
        blind_json=envelopes["blind"], edge_case_json=envelopes["edge_case"],
        acceptance_json=envelopes["acceptance"],
        role_json={role: envelopes[role] for role in ("maintainer", "user_experience")},
    )


def _capture_aggregate(report, round_id, flags="--adversarial"):
    runner = cast(Any, map_step_runner)
    for ordering in (("default", "reverse") if "--compare-orderings" in flags else ("",)):
        result = runner.capture_review_output("adversarial", json.dumps(report), round_id, ordering=ordering)
        assert result["status"] == "success", result
    return runner.write_review_verdict_ledger(current_run=True, round_id=round_id)


def test_real_aggregate_string_evidence_reaches_durable_ledger(branch_workspace):
    runner = cast(Any, map_step_runner)
    assert runner.begin_review_run(arguments="--adversarial", round_id="1")["status"] == "success"
    result = _capture_aggregate(_produced_adversarial_report(), "1")
    assert result["status"] == "success", result
    assert result["computed_verdict"] == "REVISE"
    ledger = json.loads((branch_workspace / "review-verdict-ledger.json").read_text())
    assert ledger["findings_registry"][0]["validation"]["verdict"] == "insufficient_evidence"
    assert {"source": "evidence", "quote": "writer.py:10 drops the committed write"} in ledger["findings_registry"][0]["evidence"]


@pytest.mark.parametrize("resolver,expected", [("blind", "success"), ("edge_case", "success"), ("acceptance", "error")])
def test_real_aggregate_merges_reporters_without_changing_identity(review_git_workspace, resolver, expected):
    """Merge reporters without changing the defect identity or resolution ownership."""
    branch_workspace = review_git_workspace
    runner = cast(Any, map_step_runner)
    for round_id, reporters in (("1", ("blind",)), ("2", ("edge_case",))):
        runner.begin_review_run(arguments="--adversarial", round_id=round_id)
        assert _capture_aggregate(_produced_adversarial_report(reporters), round_id)["status"] == "success"
        assert runner.abandon_review_round(round_id, reason="Continue findings review in a new attempt")["status"] == "success"
    ledger = json.loads((branch_workspace / "review-verdict-ledger.json").read_text())
    assert len(ledger["findings_registry"]) == 1
    assert ledger["findings_registry"][0]["reported_by"] == ["blind", "edge_case"]
    admission = runner.begin_review_run(arguments="--adversarial", round_id="3")
    runner.create_review_bundle()
    result = _capture_aggregate(_captured_adversarial_resolution(runner, admission, "3", resolver), "3")
    assert result["status"] == expected, result
    if expected == "success":
        assert result.get("findings_verdict", result["computed_verdict"]) == "PROCEED"
    else:
        assert "originating reviewer" in result["message"]


@pytest.mark.parametrize("evidence", ["old text", ["x", None, 4, {"source": "finding_location", "quote": "{"}],
                                      [{"source": "finding_location", "quote": "[]"}],
                                      [{"source": "finding_location", "quote": None}], None, 7])
def test_legacy_malformed_evidence_does_not_discard_finding(branch_workspace, evidence):
    runner = cast(Any, map_step_runner)
    assert runner.write_review_verdict_ledger(monitor_json=json.dumps(_monitor_with_critical()))["status"] == "success"
    path = branch_workspace / "review-verdict-ledger.json"
    prior = json.loads(path.read_text())
    prior["findings_registry"][0]["evidence"] = evidence
    path.write_text(json.dumps(prior))
    runner.begin_review_run(scheduled_reviewers=["monitor"], round_id="1")
    runner.capture_review_output("monitor", json.dumps(_monitor_no_issues()), "1")
    result = runner.write_review_verdict_ledger(current_run=True)
    assert result["status"] == "success", result
    assert result["computed_verdict"] == "BLOCK"
    assert len(json.loads(path.read_text())["findings_registry"]) == 1


def test_monitor_schema_locations_keep_distinct_files_and_stable_moved_ids(branch_workspace):
    """Keep file-specific finding IDs stable when reported locations move."""
    runner = cast(Any, map_step_runner)
    for round_id, line in (("1", "10-12"), ("2", "20-22")):
        runner.begin_review_run(scheduled_reviewers=["monitor"], round_id=round_id)
        issue = _monitor_with_critical()["issues"][0]
        issues = [{**issue, "file_path": path, "line_range": line} for path in ("a.py", "b.py")]
        if round_id == "2":
            issues.reverse()
        runner.capture_review_output("monitor", json.dumps({"issues": issues}), round_id)
        result = runner.write_review_verdict_ledger(current_run=True)
        assert result["computed_verdict"] == "BLOCK"
        ledger = json.loads((branch_workspace / "review-verdict-ledger.json").read_text())
        assert len(ledger["findings_registry"]) == 2
        locations = {json.loads(ev["quote"])["file_path"]: row["id"]
                     for row in ledger["findings_registry"] for ev in row["evidence"]
                     if ev["source"] == "finding_location"}
        assert locations == {"a.py": "RVF-001", "b.py": "RVF-002"}
        assert len(runner.review_publication("github:pr/525")["publishable"]) == 2
        assert runner.abandon_review_round(round_id, reason="Continue findings review in a new attempt")["status"] == "success"



@pytest.mark.parametrize("omitted", [False, True])
@pytest.mark.parametrize("channel", ["wrong_category", "unverifiable_context", "no_new_fact"])
def test_current_objections_bind_after_durable_ids_and_include_omissions(branch_workspace, omitted, channel):
    """Bind objections to durable findings even when later reports omit them."""
    runner = cast(Any, map_step_runner)
    issue = _monitor_with_critical()["issues"][0]
    issues = [{**issue, "file_path": path} for path in ("a.py", "b.py")]
    runner.begin_review_run(scheduled_reviewers=["monitor"], round_id="1")
    runner.capture_review_output("monitor", json.dumps({"issues": issues}), "1")
    assert runner.write_review_verdict_ledger(current_run=True)["computed_verdict"] == "BLOCK"
    assert runner.record_review_objection("RVF-002", channel, "Checked b.py against the contract")["status"] == "success"
    assert runner.abandon_review_round("1", reason="Continue findings review in a new attempt")["status"] == "success"
    runner.begin_review_run(scheduled_reviewers=["monitor"], round_id="2")
    runner.capture_review_output("monitor", json.dumps({"issues": [issues[0]] if omitted else issues[::-1]}), "2")
    result = runner.write_review_verdict_ledger(current_run=True)
    assert result["status"] == "success", result
    ledger = json.loads((branch_workspace / "review-verdict-ledger.json").read_text())
    rows = {row["id"]: row for row in ledger["findings_registry"]}
    assert rows["RVF-001"]["transition_reason"] is None
    expected_reason = {"wrong_category": "wrong_category", "unverifiable_context": "human_escalation",
                       "no_new_fact": "pressure_without_new_fact"}[channel]
    assert rows["RVF-002"]["transition_reason"] == expected_reason
    assert result["computed_verdict"] == "BLOCK"
    assert ledger["active_count"] == 2
    assert ledger["journal"]["matches_previous"] is True
    assert ledger["journal"]["repeated_verbatim"] is (channel == "no_new_fact")
    assert ledger["escalation_required"] is (channel != "no_new_fact")
    if channel == "wrong_category":
        assert rows["RVF-002"]["status"] == "downgraded"
        assert ledger["downgraded_count"] == 1
    assert any(entry["finding"] == rows["RVF-002"] for entry in ledger["finding_history"])


@pytest.mark.parametrize("completed", [False, True])
def test_legacy_write_rejected_after_admission_without_artifact_mutation(review_git_workspace, completed):
    """Reject legacy writes for both pending and completed admitted reviews."""
    branch_workspace = review_git_workspace
    runner = cast(Any, map_step_runner)
    admission = _admit_receipt_review(runner, round_id="1")
    if completed:
        _capture_complete_monitor(runner, admission, "1", _monitor_no_issues())
        assert runner.write_review_verdict_ledger(current_run=True)["code_approval"]["approved"] is True
    before = {path: path.read_bytes() for path in branch_workspace.rglob("*") if path.is_file()}
    result = runner.write_review_verdict_ledger(monitor_json=json.dumps(_monitor_with_critical()))
    assert result["status"] == "error", result
    assert "--current-run" in result["message"]
    assert {path: path.read_bytes() for path in branch_workspace.rglob("*") if path.is_file()} == before


@pytest.fixture()
def review_git_workspace(branch_workspace):
    subprocess.run(["git", "init", "-b", "main"], check=True, capture_output=True)
    for key, value in (("user.email", "test@example.com"), ("user.name", "Test")):
        subprocess.run(["git", "config", key, value], check=True)
    Path(".gitignore").write_text(".map/\n")
    Path("writer.py").write_text("VALUE = 1\n")
    subprocess.run(["git", "add", "."], check=True)
    subprocess.run(["git", "commit", "-m", "base"], check=True, capture_output=True)
    subprocess.run(["git", "checkout", "-b", "test-branch"], check=True, capture_output=True)
    return branch_workspace


def _bound_resolution(finding_id="RVF-001", *, evidence="Regression now passes", quote="VALUE = 1"):
    current = {"file_path": "writer.py", "revision": "current", "quote": quote}
    baseline = {"file_path": "writer.py", "revision": "baseline", "quote": "VALUE = 1"}
    return {"finding_id": finding_id, "evidence": evidence,
            "bug_class": "lost_write", "cause": "unconditional replacement",
            "failure_scenario": "retry overwrites value", "evidence_refs": [current],
            "reachability": {"status": "unreachable", "reason": "entry path now guarded",
                             "evidence_refs": [current]},
            "baseline_attribution": {"status": "introduced", "reason": "base compared to current",
                                     "evidence_refs": [baseline, current]},
            "sibling_search": {"searched_scope": ["writer.py"],
                "method": "inspect all replacement and retry paths", "uncertainty": "",
                "scope_expansion": [], "occurrences": [{"file_path": "writer.py",
                    "disposition": "fixed", "evidence_refs": [current]}]}}


def test_legacy_free_text_resolution_cannot_close_a_finding(review_git_workspace):
    """Require structured checked evidence to close a retained finding."""
    workspace = review_git_workspace
    runner = cast(Any, map_step_runner)
    runner.begin_review_run(scheduled_reviewers=["monitor"], round_id="first")
    runner.capture_review_output("monitor", json.dumps(_monitor_with_critical()), "first")
    assert runner.write_review_verdict_ledger(current_run=True)["computed_verdict"] == "BLOCK"
    assert runner.abandon_review_round("first", reason="Continue findings review in a new attempt")["status"] == "success"
    admission = _admit_receipt_review(runner, round_id="second")
    clean = {"issues": [], "resolved_findings": [{"finding_id": "RVF-001", "evidence": "Regression passes"}],
             "receipt": {"covered_files": admission["required_files"], "skipped_files": [],
                         "denied_access": [], "check_evidence": []}}
    runner.capture_review_output("monitor", json.dumps(clean), "second")
    assert runner.write_review_verdict_ledger(current_run=True)["findings_verdict"] != "PROCEED"
    ledger = json.loads((workspace / "review-verdict-ledger.json").read_text())
    row = ledger["findings_registry"][0]
    assert row["id"] == "RVF-001"
    assert row["status"] != "tombstoned"
    assert row["validation"]["verdict"] == "insufficient_evidence"
    assert "resolved_by" not in row


def _capture_monitor_resolution(runner, admission, round_id, *, finding_id="RVF-001",
                                evidence="Regression now passes", quote="VALUE = 1", issues=None):
    envelope = {"issues": issues or [], "resolved_findings": [
        _bound_resolution(finding_id, evidence=evidence, quote=quote)],
        "receipt": {"covered_files": admission["required_files"], "skipped_files": [],
                    "denied_access": [], "check_evidence": []}}
    result = runner.capture_review_output("monitor", json.dumps(envelope), round_id)
    assert result["status"] == "success", result


def _captured_adversarial_resolution(runner, admission, round_id, resolver, flags="--adversarial"):
    resolution = _bound_resolution()
    receipt = {"covered_files": admission["required_files"], "skipped_files": [],
               "denied_access": [], "check_evidence": []}
    independent = "acceptance" if resolver != "acceptance" else "blind"
    independent_resolution = {**resolution, "reachability": {**resolution["reachability"],
        "reason": "independent caller audit confirms guarded retry entry"}}
    envelope = {"all_clear": True, "findings": [], "resolved_findings": [independent_resolution], "receipt": receipt}
    for ordering in (("default", "reverse") if "--compare-orderings" in flags else ("",)):
        result = runner.capture_review_output(independent, json.dumps(envelope), round_id, ordering=ordering)
        assert result["status"] == "success", result
    return _produced_adversarial_report((), resolutions={resolver: [resolution]},
                                        captured_round=round_id, receipt=receipt, capture_flags=flags)


@pytest.mark.parametrize("reach,attribution,expected", [
    ("reachable", "introduced", "confirmed"),
    ("reachable", "pre_existing", "confirmed"),
    ("unreachable", "introduced", "refuted"),
    ("unknown", "introduced", "insufficient_evidence"),
])
def test_captured_finding_validation_is_snapshot_bound(review_git_workspace, reach, attribution, expected):
    workspace = review_git_workspace
    runner = cast(Any, map_step_runner)
    admission = _admit_receipt_review(runner)
    current = {"file_path": "writer.py", "revision": "current", "quote": "VALUE = 1"}
    baseline = {**current, "revision": "baseline"}
    issue = {**_monitor_with_critical()["issues"][0], "bug_class": "lost_write",
             "cause": "unconditional replacement", "failure_scenario": "retry overwrites value",
             "evidence_refs": [current],
             "reachability": {"status": reach, "reason": "entrypoint permits retry", "evidence_refs": [current]},
             "baseline_attribution": {"status": attribution, "reason": "base compared to current",
                                      "evidence_refs": [baseline, current]}}
    envelope = {"issues": [issue], "receipt": {"covered_files": admission["required_files"],
                "skipped_files": [], "denied_access": [], "check_evidence": []}}
    runner.capture_review_output("monitor", json.dumps(envelope), "receipt")
    runner.write_review_verdict_ledger(current_run=True)
    ledger = json.loads((workspace / "review-verdict-ledger.json").read_text())
    finding = ledger["findings_registry"][0]
    assert finding["validation"]["verdict"] == expected
    assert finding["validation"]["snapshot"]
    assert finding["baseline_attribution"]["status"] == attribution
    if expected == "confirmed":
        assert finding["sibling_search"]["status"] == "required"
        runner.begin_review_run(scheduled_reviewers=["monitor"], round_id="remediation")
        runner.create_review_bundle()
        resolution = {**issue, "finding_id": finding["id"], "evidence": "Checked remediation",
                      "reachability": {"status": "unreachable", "reason": "entry path now guarded",
                                       "evidence_refs": [current]},
                      "sibling_search": {"searched_scope": ["writer.py"],
                         "method": "inspect all replacement and retry paths", "uncertainty": "",
                         "scope_expansion": [], "occurrences": [{"file_path": "writer.py",
                             "disposition": "fixed", "evidence_refs": [current]}]}}
        resolved = {"issues": [], "resolved_findings": [resolution], "receipt": envelope["receipt"]}
        runner.capture_review_output("monitor", json.dumps(resolved), "remediation")
        runner.write_review_verdict_ledger(current_run=True)
        ledger = json.loads((workspace / "review-verdict-ledger.json").read_text())
        assert ledger["findings_verdict"] == "PROCEED"
        assert ledger["findings_registry"][0]["sibling_search"]["status"] == "complete"


@pytest.mark.parametrize("second_reach,individual_captures,expected", [
    ("reachable", True, "confirmed"), ("unreachable", True, "insufficient_evidence"),
    ("reachable", False, "insufficient_evidence"),
])
def test_adversarial_quorum_uses_individual_bound_evidence(review_git_workspace, second_reach, individual_captures, expected):
    workspace = review_git_workspace
    runner = cast(Any, map_step_runner)
    admission = runner.begin_review_run(arguments="--adversarial --quick", round_id="quorum")
    runner.create_review_bundle()
    current = {"file_path": "writer.py", "revision": "current", "quote": "VALUE = 1"}
    finding = {"severity": "IMPORTANT", "category": "correctness", "file_path": "writer.py",
        "failure_mode": "retry loses value", "bug_class": "lost_write", "cause": "replacement",
        "failure_scenario": "retry overwrites", "evidence_refs": [current],
        "reachability": {"status": "reachable", "reason": "entrypoint retry", "evidence_refs": [current]},
        "baseline_attribution": {"status": "introduced", "reason": "base compared",
                                 "evidence_refs": [current, {**current, "revision": "baseline"}]}}
    receipt = {"covered_files": admission["required_files"], "skipped_files": [], "denied_access": [], "check_evidence": []}
    first = json.dumps({"all_clear": False, "findings": [finding], "receipt": receipt})
    other = {**finding, "reachability": {**finding["reachability"], "status": second_reach,
                                        "reason": "independent path audit confirms caller retry"}}
    second = json.dumps({"all_clear": False, "findings": [other], "receipt": receipt})
    if individual_captures:
        runner.capture_review_output("blind", first, "quorum")
        runner.capture_review_output("acceptance", second, "quorum")
    report = runner.aggregate_adversarial_findings(blind_json=first, acceptance_json=second)
    runner.capture_review_output("adversarial", json.dumps(report), "quorum")
    runner.write_review_verdict_ledger(current_run=True)
    ledger = json.loads((workspace / "review-verdict-ledger.json").read_text())
    assert ledger["findings_registry"][0]["validation"]["verdict"] == expected
    assert ledger.get("findings_verdict", ledger["computed_verdict"]) != "PROCEED"


def test_bound_sibling_search_and_reactions_survive_restart_without_closing_by_reaction(review_git_workspace):
    workspace = review_git_workspace
    runner = cast(Any, map_step_runner)
    admission = _admit_receipt_review(runner)
    envelope = {**_monitor_with_critical(), "receipt": {"covered_files": admission["required_files"],
                "skipped_files": [], "denied_access": [], "check_evidence": []}}
    runner.capture_review_output("monitor", json.dumps(envelope), "receipt")
    runner.write_review_verdict_ledger(current_run=True)
    result = runner.record_review_reaction("RVF-001", "fixed", "author says fixed")
    assert result["status"] == "success"
    proc, restarted = _review_cli("record_review_reaction", "--finding-id", "RVF-001",
                                  "--reaction", "fixed", "--evidence", "author says fixed")
    assert proc.returncode == 0, restarted
    ledger = json.loads((workspace / "review-verdict-ledger.json").read_text())
    finding = ledger["findings_registry"][0]
    assert len(finding["author_reactions"]) == 1
    assert finding["validation"]["verdict"] == "insufficient_evidence"
    assert ledger["findings_verdict"] != "PROCEED"


def test_completed_review_gate_rejects_changed_snapshot_after_restart(review_git_workspace):
    workspace = review_git_workspace
    runner = cast(Any, map_step_runner)
    admission = _admit_receipt_review(runner, round_id="clean")
    envelope = {**_monitor_no_issues(), "receipt": {"covered_files": admission["required_files"],
                "skipped_files": [], "denied_access": [], "check_evidence": []}}
    runner.capture_review_output("monitor", json.dumps(envelope), "clean")
    assert runner.write_review_verdict_ledger(current_run=True)["findings_verdict"] == "PROCEED"
    Path("writer.py").write_text("VALUE = 2\n")
    proc, result = _review_cli("write_stage_gate", "review", "ready", "review.md", "clean")
    assert proc.returncode != 0 or result["status"] == "error", result
    assert not (workspace / "review-gate.json").exists()


@pytest.mark.parametrize("mutation", ["binary", "index", "policy", "base", "head", "untracked", "symlink"])
def test_completed_binding_detects_byte_and_policy_changes(review_git_workspace, mutation):
    """Reject completed evidence after any reviewed input or policy changes."""
    del review_git_workspace
    runner = cast(Any, map_step_runner)
    Path("image.bin").write_bytes(b"\x00\xff\x01")
    Path("link").symlink_to("writer.py")
    subprocess.run(["git", "add", "."], check=True)
    subprocess.run(["git", "commit", "-m", "inputs"], check=True, capture_output=True)
    admission = _admit_receipt_review(runner, round_id="clean")
    _capture_complete_monitor(runner, admission, "clean", _monitor_no_issues())
    runner.write_review_verdict_ledger(current_run=True)
    if mutation == "binary":
        Path("image.bin").write_bytes(b"\x00\xff\x02")
    elif mutation == "index":
        Path("writer.py").write_text("VALUE = 2\n")
        subprocess.run(["git", "add", "writer.py"], check=True)
        Path("writer.py").write_text("VALUE = 1\n")
    elif mutation == "policy":
        Path(".map/config.yaml").write_text("review: changed\n")
    elif mutation == "base":
        subprocess.run(["git", "branch", "-f", "main", "HEAD"], check=True)
    elif mutation == "head":
        subprocess.run(["git", "commit", "--allow-empty", "-m", "new head"], check=True, capture_output=True)
    elif mutation == "symlink":
        Path("link").unlink()
        Path("link").symlink_to("image.bin")
    else:
        Path("extra\nfile.bin").write_bytes(b"\x00\xfe")
    result = runner.write_review_verdict_ledger(current_run=True)
    assert result["status"] == "error", result
    assert runner.begin_review_run(scheduled_reviewers=["monitor"], round_id="new")["status"] == "success"


def _admit_receipt_review(runner, *, provider="claude", required_checks=None, round_id="receipt", check_specs=None):
    profile = Path(".claude/agents/review-reader.md")
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text("---\nname: review-reader\ntools: Read, Glob, Grep\n---\nRead only.\n")
    admission = runner.begin_review_run(scheduled_reviewers=["monitor"], round_id=round_id,
                                       provider=provider, required_checks=required_checks, check_specs=check_specs)
    if admission["status"] == "success":
        assert runner.create_review_bundle()["status"] == "success"
    return admission


def _capture_complete_monitor(runner, admission, round_id, payload=None):
    """Capture a Monitor result with full admitted coverage and a durable witness."""
    assert admission["status"] == "success", admission
    envelope = {**(payload if payload is not None else _monitor_with_critical()), "receipt": {
        "covered_files": admission["required_files"], "skipped_files": [],
        "denied_access": [], "check_evidence": []}}
    assert runner.capture_review_output("monitor", json.dumps(envelope), round_id)["status"] == "success"


def test_complete_receipts_approve_after_restart(review_git_workspace):
    workspace = review_git_workspace
    runner = cast(Any, map_step_runner)
    admission = _admit_receipt_review(runner)
    assert admission["capability"]["status"] == "verified", admission
    envelope = {**_monitor_no_issues(), "receipt": {"covered_files": admission["required_files"],
                "skipped_files": [], "denied_access": [], "check_evidence": []}}
    runner.capture_review_output("monitor", json.dumps(envelope), "receipt")
    result = runner.write_review_verdict_ledger(current_run=True)
    ledger = json.loads((workspace / "review-verdict-ledger.json").read_text())
    assert ledger["completeness"]["status"] == "COMPLETE", result
    assert ledger["code_approval"]["approved"] is True
    assert ledger["human_consent"]["status"] == "pending"
    assert admission["target"]["security_gate_policy"]["mode"] == "shadow"
    assert runner.get_pending_holds()["resume_blocked"] is False
    proc, gate = _review_cli("write_stage_gate", "review", "ready", "review.md", "clean")
    assert proc.returncode == 0 and gate["status"] == "success", gate


@pytest.mark.parametrize("defect,expected", [("missing", "INCOMPLETE"), ("scope", "INCOMPLETE"),
    ("denied", "BLOCKED"), ("codex", "INCOMPLETE"), ("check", "INCOMPLETE"),
    ("capability", "INCOMPLETE")])
def test_receipt_gaps_never_approve_but_keep_findings(review_git_workspace, defect, expected):
    workspace = review_git_workspace
    runner = cast(Any, map_step_runner)
    admission = _admit_receipt_review(runner, provider="codex" if defect == "codex" else "claude")
    receipt = {"covered_files": admission["required_files"], "skipped_files": [],
               "denied_access": [], "check_evidence": []}
    if defect == "scope":
        receipt["covered_files"] = []
    elif defect == "denied":
        receipt["denied_access"] = ["writer.py"]
    elif defect == "check":
        receipt["check_evidence"] = ["fabricated-pass"]
    envelope = {**_monitor_with_critical(), "receipt": receipt}
    if defect == "missing":
        del envelope["receipt"]
    if defect == "capability":
        Path(".claude/agents/review-reader.md").write_text("---\ntools: Read, Bash\n---\n")
        assert runner.capture_review_output("monitor", json.dumps(envelope), "receipt")["status"] == "error"
        return
    runner.capture_review_output("monitor", json.dumps(envelope), "receipt")
    runner.write_review_verdict_ledger(current_run=True)
    ledger = json.loads((workspace / "review-verdict-ledger.json").read_text())
    assert ledger["completeness"]["status"] == expected
    assert ledger["code_approval"]["approved"] is False
    assert ledger["findings_registry"]
    assert runner.review_publication("github:pr/521")["publishable"]


@pytest.mark.parametrize("command_kind", ["pass", "fail", "mutate", "missing"])
def test_runner_checks_are_durable_snapshot_bound_evidence(review_git_workspace, command_kind):
    workspace = review_git_workspace
    runner = cast(Any, map_step_runner)
    programs = {"pass": "print('verified')", "fail": "raise SystemExit(2)",
                "mutate": "from pathlib import Path; Path('writer.py').write_text('VALUE = 9')"}
    command = [sys.executable, "-c", programs.get(command_kind, "")] if command_kind != "missing" else ["/no/such/check"]
    admission = _admit_receipt_review(runner, required_checks=["suite"], check_specs={"suite": command})
    result = runner.run_test_gate(command=command, check_id="suite")
    assert result["passed"] is (command_kind == "pass"), result
    ledger = json.loads((workspace / "review-verdict-ledger.json").read_text())
    check = ledger["execution_checks"]["suite"]
    assert check["state"] == "finished"
    assert (workspace / check["output_artifact"]).is_file()
    if command_kind == "mutate":
        return
    envelope = {**_monitor_no_issues(), "receipt": {"covered_files": admission["required_files"],
                "skipped_files": [], "denied_access": [], "check_evidence": ["suite"]}}
    runner.capture_review_output("monitor", json.dumps(envelope), "receipt")
    proc, final = _review_cli("write_review_verdict_ledger", "--current-run")
    assert proc.returncode == 0, final
    ledger = json.loads((workspace / "review-verdict-ledger.json").read_text())
    assert ledger["code_approval"]["approved"] is (command_kind == "pass")
    if command_kind == "pass":
        (workspace / check["output_artifact"]).unlink()
        _, gate = _review_cli("write_stage_gate", "review", "ready", "review.md", "clean")
        assert gate["status"] == "error", gate


def test_interrupted_check_retries_after_restart_without_losing_failed_attempt(review_git_workspace):
    workspace = review_git_workspace
    runner = cast(Any, map_step_runner)
    marker = workspace / "check-started"
    release = workspace / "check-release"
    command = [sys.executable, "-c", (
        "from pathlib import Path; import time; "
        f"Path({str(marker)!r}).write_text('started'); "
        f"release = Path({str(release)!r}); "
        "exec('while not release.exists(): time.sleep(0.02)'); "
        "raise SystemExit(2)"
    )]
    admission = _admit_receipt_review(runner, required_checks=["suite"], check_specs={"suite": command})
    process = subprocess.Popen(
        [sys.executable, str(SCRIPTS_PATH / "map_step_runner.py"), "run_test_gate", "--check-id", "suite"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert marker.exists(), process.communicate(timeout=5)
        ledger_path = workspace / "review-verdict-ledger.json"
        running_ledger = ledger_path.read_bytes()
        _, blocked = _review_cli("run_test_gate", "--check-id", "suite")
        assert blocked["status"] == "error" and blocked["passed"] is False, blocked
        assert ledger_path.read_bytes() == running_ledger
        process.kill()
        process.wait(timeout=5)
        # The direct check process is alive after its runner dies: no overlap.
        _, blocked = _review_cli("run_test_gate", "--check-id", "suite")
        assert blocked["status"] == "error" and blocked["passed"] is False, blocked
        assert ledger_path.read_bytes() == running_ledger
        release.touch()
        deadline = time.monotonic() + 10
        while True:
            _, result = _review_cli("run_test_gate", "--check-id", "suite")
            if result.get("state") == "finished" or time.monotonic() >= deadline:
                break
            time.sleep(0.02)
        assert result.get("state") == "finished", result
        ledger = json.loads((workspace / "review-verdict-ledger.json").read_text())
        history = ledger["execution_check_history"]
        assert len(history) == 1
        assert history[0]["check_id"] == "suite"
        assert history[0]["state"] == "interrupted"
        assert history[0]["passed"] is False
        receipt = {"covered_files": admission["required_files"], "skipped_files": [],
                   "denied_access": [], "check_evidence": ["suite"]}
        runner.capture_review_output("monitor", json.dumps({**_monitor_no_issues(), "receipt": receipt}), "receipt")
        _, final = _review_cli("write_review_verdict_ledger", "--current-run")
        assert final["code_approval"]["approved"] is False
        assert json.loads((workspace / "review-verdict-ledger.json").read_text())["execution_check_history"] == history
    finally:
        release.touch()
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)


def test_terminal_review_rejects_check_rerun_without_revoking_approval(review_git_workspace):
    workspace = review_git_workspace
    runner = cast(Any, map_step_runner)
    command = [sys.executable, "-c", "pass"]
    admission = _admit_receipt_review(runner, required_checks=["suite"], check_specs={"suite": command})
    assert runner.run_test_gate(command=command, check_id="suite")["passed"] is True
    receipt = {"covered_files": admission["required_files"], "skipped_files": [],
               "denied_access": [], "check_evidence": ["suite"]}
    runner.capture_review_output("monitor", json.dumps({**_monitor_no_issues(), "receipt": receipt}), "receipt")
    assert runner.write_review_verdict_ledger(current_run=True)["code_approval"]["approved"] is True
    ledger_path = workspace / "review-verdict-ledger.json"
    before = ledger_path.read_bytes()
    _, rejected = _review_cli("run_test_gate", "--check-id", "suite")
    assert rejected["status"] == "error" and rejected["passed"] is False, rejected
    assert ledger_path.read_bytes() == before
    _, gate = _review_cli("write_stage_gate", "review", "ready", "review.md", "clean")
    assert gate["status"] == "success", gate


def test_execution_completion_cannot_cross_abandoned_round(review_git_workspace):
    workspace = review_git_workspace
    runner = cast(Any, map_step_runner)
    marker, release = workspace / "started", workspace / "release"
    command = [sys.executable, "-c", (
        "from pathlib import Path; import time; "
        f"Path({str(marker)!r}).touch(); release = Path({str(release)!r}); "
        "exec('while not release.exists(): time.sleep(0.02)')"
    )]
    admission = _admit_receipt_review(runner, required_checks=["suite"], check_specs={"suite": command})
    assert admission["status"] == "success", admission
    process = subprocess.Popen(
        [sys.executable, str(SCRIPTS_PATH / "map_step_runner.py"), "run_test_gate", "--check-id", "suite"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert marker.exists(), process.communicate(timeout=5)
        assert runner.abandon_review_round("receipt", reason="Replace active review")["status"] == "success"
        replacement = _admit_receipt_review(runner, round_id="replacement", required_checks=["suite"],
                                            check_specs={"suite": command})
        assert replacement["status"] == "success", replacement
        release.touch()
        stdout, stderr = process.communicate(timeout=10)
        result = json.loads(stdout)
        assert result["status"] == "error", (result, stderr)
        ledger = json.loads((workspace / "review-verdict-ledger.json").read_text())
        assert ledger["execution_checks"]["suite"]["passed"] is False
        _, retried = _review_cli("run_test_gate", "--check-id", "suite")
        assert retried["passed"] is True and retried["round_id"] == "replacement", retried
        ledger = json.loads((workspace / "review-verdict-ledger.json").read_text())
        assert ledger["execution_check_history"][0]["round_id"] == "receipt"
        assert ledger["execution_check_history"][0]["state"] == "interrupted"
    finally:
        release.touch()
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)


def test_historical_legacy_ledger_does_not_approve_without_receipts(review_git_workspace):
    workspace = review_git_workspace
    runner = cast(Any, map_step_runner)
    runner.write_review_verdict_ledger(monitor_json=json.dumps(_monitor_no_issues()))
    _, gate = _review_cli("write_stage_gate", "review", "ready", "review.md", "legacy")
    assert gate["status"] == "error", gate
    assert not (workspace / "review-gate.json").exists()


def test_required_check_rejects_substituted_command(review_git_workspace):
    del review_git_workspace
    runner = cast(Any, map_step_runner)
    profile = Path(".claude/agents/review-reader.md")
    profile.parent.mkdir(parents=True)
    profile.write_text("---\ntools: Read, Glob, Grep\n---\n")
    command = [sys.executable, "-c", "raise SystemExit(1)"]
    admission = runner.begin_review_run(scheduled_reviewers=["monitor"], provider="claude", round_id="bound",
                                       required_checks=["suite"], check_specs={"suite": command})
    assert admission["status"] == "success", admission
    runner.create_review_bundle()
    rejected = runner.run_test_gate(command=[sys.executable, "-c", "pass"], check_id="suite")
    assert rejected["status"] == "error" and rejected["passed"] is False, rejected
    assert runner.run_test_gate(command=command, check_id="suite")["passed"] is False
    receipt = {"covered_files": admission["required_files"], "skipped_files": [],
               "denied_access": [], "check_evidence": ["suite"]}
    runner.capture_review_output("monitor", json.dumps({**_monitor_no_issues(), "receipt": receipt}), "bound")
    final = runner.write_review_verdict_ledger(current_run=True)
    assert final["computed_verdict"] != "PROCEED"
    assert runner.write_stage_gate("review", "ready", "review.md")["status"] == "error"


def test_malformed_capability_profile_is_unverified_not_a_crash(review_git_workspace):
    del review_git_workspace
    runner = cast(Any, map_step_runner)
    profile = Path(".claude/agents/review-reader.md")
    profile.parent.mkdir(parents=True)
    profile.write_text("---\ntools: [Read,\n---\n")
    admission = runner.begin_review_run(provider="claude", mode="lightweight", round_id="malformed")
    assert admission["status"] == "success", admission
    assert admission["capability"]["status"] == "unverified"
    assert "malformed" in admission["capability"]["reason"].lower()
    runner.create_review_bundle()
    receipt = {"covered_files": admission["required_files"], "skipped_files": [],
               "denied_access": [], "check_evidence": []}
    runner.capture_review_output("monitor", json.dumps({**_monitor_no_issues(), "receipt": receipt}), "malformed")
    final = runner.write_review_verdict_ledger(current_run=True)
    assert final["completeness"]["status"] == "INCOMPLETE"
    assert final["code_approval"]["approved"] is False


def _review_cli(*args, payload=""):
    result = subprocess.run([sys.executable, str(SCRIPTS_PATH / "map_step_runner.py"), *args],
                            input=payload, text=True, capture_output=True, check=False)
    return result, json.loads(result.stdout)


@pytest.mark.parametrize("changed_path", ["writer.py", "untracked.py"])
def test_explicit_abandonment_recovers_changed_target_without_reset(review_git_workspace, changed_path):
    """Recover a changed pending target without resetting history or attempt counts."""
    workspace = review_git_workspace
    runner = cast(Any, map_step_runner)
    admission = _admit_receipt_review(runner, round_id="first")
    _capture_complete_monitor(runner, admission, "first")
    assert runner.write_review_verdict_ledger(current_run=True)["computed_verdict"] == "BLOCK"
    publication = runner.review_publication("github:pr/525")
    runner.review_publication("github:pr/525", [publication["publishable"][0]["revision_id"]])
    runner.begin_review_run(scheduled_reviewers=["monitor"], round_id="stuck")
    runner.capture_review_output("monitor", json.dumps(_monitor_no_issues()), "stuck")
    Path(changed_path).write_text("VALUE = 2\n")
    assert runner.begin_review_run(scheduled_reviewers=["monitor"], round_id="stuck")["status"] == "error"
    assert runner.write_review_verdict_ledger(current_run=True)["status"] == "error"
    assert runner.begin_review_run(scheduled_reviewers=["monitor"], round_id="recovery")["status"] == "error"
    path = workspace / "review-verdict-ledger.json"
    before = json.loads(path.read_text())
    captured = (workspace / "review-agent-monitor.json").read_bytes()
    result = runner.abandon_review_round("stuck", reason="Target changed while reviewers were running")
    assert result["status"] == "success", result
    ledger = json.loads(path.read_text())
    row = ledger["convergence"]["rounds"][-1]
    assert row["verdict"] == "ABANDONED"
    assert row["aborted_at"] > 0 and "completed_at" not in row
    assert row["abandon_reason"] == "Target changed while reviewers were running"
    assert ledger["convergence"]["completed_rounds"] == 1
    assert ledger["convergence"]["attempted_rounds"] == 2
    assert ledger["computed_verdict"] == "BLOCK"
    for field in ("findings_registry", "finding_history", "publication_history"):
        assert ledger[field] == before[field]
    assert (workspace / "review-agent-monitor.json").read_bytes() == captured
    snapshot = path.read_bytes()
    assert runner.abandon_review_round("stuck", reason=row["abandon_reason"])["status"] == "success"
    assert path.read_bytes() == snapshot
    assert runner.abandon_review_round("stuck", reason="rewrite audit")["status"] == "error"
    assert runner.capture_review_output("monitor", "{}", "stuck")["status"] == "error"
    assert runner.write_review_verdict_ledger(current_run=True, round_id="stuck")["status"] == "error"
    assert runner.begin_review_run(scheduled_reviewers=["monitor"], round_id="stuck")["status"] == "error"
    admission = _admit_receipt_review(runner, round_id="recovery")
    assert admission["status"] == "success"
    assert runner.write_review_verdict_ledger(current_run=True, round_id="stuck")["status"] == "error"
    _capture_monitor_resolution(runner, admission, "recovery", evidence="Fixed writer regression passes",
                                quote="VALUE = 2" if changed_path == "writer.py" else "VALUE = 1")
    result = runner.write_review_verdict_ledger(current_run=True)
    assert result.get("findings_verdict", result["computed_verdict"]) == "PROCEED"
    assert result["convergence"]["rounds_to_pass"] == 3
    assert result["convergence"]["completed_rounds"] == 2
    assert runner.abandon_review_round("recovery", reason="cannot abandon completed")["status"] == "error"


def test_abandon_cli_preserves_three_attempt_cap_across_processes(review_git_workspace):
    """Combine completed and abandoned attempts in the durable CLI cap."""
    workspace = review_git_workspace
    runner = cast(Any, map_step_runner)
    for round_id in ("1", "2"):
        admission = _admit_receipt_review(runner, round_id=round_id)
        _capture_complete_monitor(runner, admission, round_id)
        runner.write_review_verdict_ledger(current_run=True)
    runner.begin_review_run(scheduled_reviewers=["monitor"], round_id="3")
    incomplete = runner.write_review_verdict_ledger(current_run=True)
    assert incomplete["convergence"]["completed_rounds"] == 2
    Path("untracked.py").write_text("VALUE = 3\n")
    proc, result = _review_cli("abandon_review_round", "3", "--reason", "Changed target; explicit operator cancellation")
    assert proc.returncode == 0, result
    assert result["convergence"]["outcome"] == "capped"
    path = workspace / "review-verdict-ledger.json"
    snapshot = path.read_bytes()
    proc, result = _review_cli("begin_review_run", "--mode", "lightweight", "--round-id", "4")
    assert proc.returncode == 1
    assert result["stop_reason"] == "reconsider_approach"
    assert path.read_bytes() == snapshot
    assert json.loads(snapshot)["convergence"]["rounds_to_pass"] is None


@pytest.mark.parametrize("adversarial", [False, True])
def test_acknowledged_identical_publication_is_suppressed_across_rounds(branch_workspace, adversarial):
    """Suppress previously acknowledged revisions after starting another attempt."""
    runner = cast(Any, map_step_runner)
    first_revision = None
    for round_id in ("1", "2"):
        if adversarial:
            runner.begin_review_run(arguments="--adversarial", round_id=round_id)
            result = _capture_aggregate(_produced_adversarial_report(), round_id)
        else:
            runner.begin_review_run(scheduled_reviewers=["monitor"], round_id=round_id)
            runner.capture_review_output("monitor", json.dumps(_monitor_with_critical()), round_id)
            result = runner.write_review_verdict_ledger(current_run=True)
        assert result["status"] == "success", result
        publication = runner.review_publication("github:pr/525")
        if round_id == "1":
            first_revision = publication["publishable"][0]["revision_id"]
            runner.review_publication("github:pr/525", [first_revision])
            assert runner.abandon_review_round(round_id, reason="Continue findings review in a new attempt")["status"] == "success"
        else:
            assert publication["publishable"] == []
            assert publication["suppressed"] == [first_revision]
    ledger = json.loads((branch_workspace / "review-verdict-ledger.json").read_text())
    assert len(ledger["publication_history"]) == 1
    assert len(ledger["finding_history"]) == 1


def test_abandoned_capture_never_establishes_review_coverage(review_git_workspace):
    workspace = review_git_workspace
    runner = cast(Any, map_step_runner)
    runner.begin_review_run(scheduled_reviewers=["monitor"], round_id="1")
    envelope = _monitor_with_critical()
    envelope["covered_files"] = ["writer.py"]
    runner.capture_review_output("monitor", json.dumps(envelope), "1")
    result = runner.abandon_review_round("1", reason="Incomplete verification; do not reuse coverage")
    assert result["status"] == "success", result
    assert runner.review_round_scope()["kind"] == "full"
    ledger = json.loads((workspace / "review-verdict-ledger.json").read_text())
    assert ledger["computed_verdict"] == "REVISE"
    assert ledger["convergence"]["completed_rounds"] == 0
    assert ledger["convergence"]["attempted_rounds"] == 1
    assert "covered_files" not in ledger["convergence"]["rounds"][0]
    assert runner.begin_review_run(scheduled_reviewers=["monitor"], round_id="2")["status"] == "success"
    assert runner.review_round_scope()["kind"] == "full"
    assert runner.abandon_review_round("2", reason=" ")["status"] == "error"
    assert runner.abandon_review_round("missing", reason="Unknown admission")["status"] == "error"


@pytest.mark.parametrize("channel", ["wrong_category", "unverifiable_context", "no_new_fact"])
def test_explicit_resolution_supersedes_persisted_objection(review_git_workspace, channel):
    """Let checked originating-reviewer evidence supersede a prior objection."""
    branch_workspace = review_git_workspace
    runner = cast(Any, map_step_runner)
    runner.begin_review_run(scheduled_reviewers=["monitor"], round_id="1")
    runner.capture_review_output("monitor", json.dumps(_monitor_with_critical()), "1")
    assert runner.write_review_verdict_ledger(current_run=True)["computed_verdict"] == "BLOCK"
    runner.record_review_objection("RVF-001", channel, "Operator contests original report")
    assert runner.abandon_review_round("1", reason="Continue findings review in a new attempt")["status"] == "success"
    runner.begin_review_run(scheduled_reviewers=["monitor"], round_id="2")
    runner.capture_review_output("monitor", json.dumps(_monitor_no_issues()), "2")
    assert runner.write_review_verdict_ledger(current_run=True)["computed_verdict"] != "PROCEED"
    assert runner.abandon_review_round("2", reason="Continue findings review in a new attempt")["status"] == "success"
    admission = _admit_receipt_review(runner, round_id="3")
    _capture_monitor_resolution(runner, admission, "3", evidence="Originating reviewer verified corrected rollback")
    result = runner.write_review_verdict_ledger(current_run=True)
    assert result.get("findings_verdict", result["computed_verdict"]) == "PROCEED", result
    ledger = json.loads((branch_workspace / "review-verdict-ledger.json").read_text())
    row = ledger["findings_registry"][0]
    assert row["status"] == "tombstoned"
    assert row["transition_reason"] == "new_evidence"
    assert row["transition_evidence"] == "Originating reviewer verified corrected rollback"
    assert ledger["escalation_required"] is False
    assert ledger["journal"]["repeated_verbatim"] is False


@pytest.mark.parametrize("reported_again", [False, True])
def test_resolved_objection_stays_superseded_on_omission_but_observation_reopens(review_git_workspace, reported_again):
    """Preserve resolved objections on omission and reopen freshly observed defects."""
    branch_workspace = review_git_workspace
    runner = cast(Any, map_step_runner)
    first = _monitor_with_critical()["issues"][0]
    other = {**first, "description": "Independent second defect"}
    runner.begin_review_run(scheduled_reviewers=["monitor"], round_id="1")
    runner.capture_review_output("monitor", json.dumps({"issues": [first, other]}), "1")
    runner.write_review_verdict_ledger(current_run=True)
    runner.record_review_objection("RVF-001", "wrong_category", "Operator contests initial rollback defect")
    assert runner.abandon_review_round("1", reason="Continue findings review in a new attempt")["status"] == "success"
    admission = _admit_receipt_review(runner, round_id="2")
    _capture_monitor_resolution(runner, admission, "2", evidence="Verified rollback correction")
    assert runner.write_review_verdict_ledger(current_run=True)["computed_verdict"] == "BLOCK"
    admission = _admit_receipt_review(runner, round_id="3")
    _capture_monitor_resolution(runner, admission, "3", finding_id="RVF-002",
                                evidence="Verified independent correction", issues=[first] if reported_again else [])
    result = runner.write_review_verdict_ledger(current_run=True)
    assert result["findings_verdict"] == ("REVISE" if reported_again else "PROCEED")
    ledger = json.loads((branch_workspace / "review-verdict-ledger.json").read_text())
    assert {row["id"] for row in ledger["findings_registry"]} == {"RVF-001", "RVF-002"}
    row = next(row for row in ledger["findings_registry"] if row["id"] == "RVF-001")
    assert row["status"] == ("downgraded" if reported_again else "tombstoned")
    assert ("resolved_by" in row) is not reported_again
