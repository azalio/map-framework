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


def test_evidenced_objection_removes_a_minor_finding(branch_workspace):
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

    assert result["computed_verdict"] == "PROCEED"
    assert result["tombstoned_count"] == 1
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
