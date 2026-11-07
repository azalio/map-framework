"""Resolution identity, individual rejection and the verdict-gated attempt cap (#659)."""

import json
from pathlib import Path
from typing import Any, cast

import pytest

from tests import test_review_verdict_ledger as ledger_tests

runner = cast(Any, ledger_tests.map_step_runner)
review_git_workspace = ledger_tests.review_git_workspace
branch_workspace = ledger_tests.branch_workspace

CURRENT = {"file_path": "writer.py", "revision": "current", "quote": "VALUE = 1"}


def _issue() -> dict:
    return {**ledger_tests._monitor_with_critical()["issues"][0], "bug_class": "lost_write",
            "cause": "unconditional replacement", "failure_scenario": "retry overwrites value, JSX example included",
            "evidence_refs": [CURRENT],
            "reachability": {"status": "reachable", "reason": "entrypoint permits retry", "evidence_refs": [CURRENT]},
            "baseline_attribution": {"status": "introduced", "reason": "base compared to current",
                                     "evidence_refs": [{**CURRENT, "revision": "baseline"}, CURRENT]}}


def _receipt(admission: dict) -> dict:
    return {"covered_files": admission["required_files"], "skipped_files": [], "denied_access": [], "check_evidence": []}


def _carry_one_finding() -> dict:
    """Round 'first' records a confirmed finding, is abandoned after a verdict, round 'second' is admitted."""
    admission = ledger_tests._admit_receipt_review(runner, round_id="first")
    # Intent: an incomplete receipt keeps the round pending, so it can be abandoned after its verdict.
    envelope = {"issues": [_issue()], "receipt": {**_receipt(admission), "covered_files": []}}
    assert runner.capture_review_output("monitor", json.dumps(envelope), "first")["status"] == "success"
    assert runner.write_review_verdict_ledger(current_run=True)["status"] == "success"
    assert runner.abandon_review_round("first", reason="Continue findings review in a new attempt")["status"] == "success"
    return ledger_tests._admit_receipt_review(runner, round_id="second")


def _resolve(admission: dict, **overrides) -> dict:
    resolution = {**ledger_tests._bound_resolution(), **overrides}
    envelope = {"issues": [], "resolved_findings": [resolution], "receipt": _receipt(admission)}
    assert runner.capture_review_output("monitor", json.dumps(envelope), "second")["status"] == "success"
    return runner.write_review_verdict_ledger(current_run=True)


def test_vc1_paraphrased_scenario_resolves_and_keeps_note(review_git_workspace):
    admission = _carry_one_finding()
    result = _resolve(admission)  # _bound_resolution restates the scenario more briefly
    assert result["status"] == "success", result
    assert result["rejected_resolutions"] == []
    assert result["findings_verdict"] == "PROCEED"
    ledger = json.loads((review_git_workspace / "review-verdict-ledger.json").read_text())
    finding = ledger["findings_registry"][0]
    assert finding["resolved_by"] == "monitor"
    assert finding["failure_scenario"] == "retry overwrites value, JSX example included"
    assert finding["resolution_scenario_note"] == "retry overwrites value"


def test_vc2_cause_mismatch_rejects_only_that_resolution(review_git_workspace):
    admission = _carry_one_finding()
    result = _resolve(admission, cause="some other cause")
    assert result["status"] == "success", result
    assert result["findings_verdict"] != "PROCEED"
    assert result["rejected_resolutions"] == [{
        "finding_id": "RVF-001", "source_agent": "monitor",
        "reason": "Resolution cannot substitute another finding cause", "fields": ["cause"]}]
    ledger = json.loads((review_git_workspace / "review-verdict-ledger.json").read_text())
    finding = ledger["findings_registry"][0]
    assert "resolved_by" not in finding and finding["status"] != "tombstoned"
    assert ledger["rejected_resolutions"] == result["rejected_resolutions"]
    assert "cause" in (review_git_workspace / "review-verdict-ledger.md").read_text()


@pytest.mark.parametrize("overrides,field", [({"finding_id": "RVF-099"}, "finding_id"), ({"evidence": "  "}, "evidence")])
def test_vc2_unknown_finding_and_missing_evidence_are_named(review_git_workspace, overrides, field):
    result = _resolve(_carry_one_finding(), **overrides)
    assert result["status"] == "success", result
    assert result["rejected_resolutions"][0]["fields"] == [field]
    assert result["findings_verdict"] != "PROCEED"


def test_vc3_verdictless_abandon_does_not_consume_an_attempt(review_git_workspace):
    for number in ("1", "2", "3", "4"):
        assert runner.begin_review_run(scheduled_reviewers=["monitor"], round_id=number)["status"] == "success"
        result = runner.abandon_review_round(number, reason="Reviewers could not run")
        assert result["convergence"]["attempted_rounds"] == 0
        assert result["convergence"]["outcome"] == "incomplete"
    ledger = json.loads((review_git_workspace / "review-verdict-ledger.json").read_text())
    assert all(row["abandoned_without_verdict"] for row in ledger["convergence"]["rounds"])
    assert runner.begin_review_run(scheduled_reviewers=["monitor"], round_id="5")["status"] == "success"


def test_vc3_stuck_ledger_from_issue_admits_a_new_round(review_git_workspace):
    """r1 BLOCK, r2 BLOCK, r3 abandoned without verdict (written by 3.37.0, no marker) is no longer capped."""
    assert runner.begin_review_run(scheduled_reviewers=["monitor"], round_id="seed")["status"] == "success"
    assert runner.abandon_review_round("seed", reason="seed")["status"] == "success"
    path: Path = review_git_workspace / "review-verdict-ledger.json"
    ledger = json.loads(path.read_text())
    template = ledger["convergence"]["rounds"][0]
    base = {key: template[key] for key in ("binding", "started_at", "archive_inputs", "prepared", "target",
                                           "policy_hash", "capability", "receipts")}
    complete = {"completed_at": 1.0, "submission_digest": "d", "verdict": "BLOCK",
                "completeness": {"status": "COMPLETE", "reasons": []}}
    ledger["convergence"]["rounds"] = [
        {**base, "round_id": "round-1", **complete},
        {**base, "round_id": "round-2", **complete},
        {**base, "round_id": "round-3", "aborted_at": 2.0, "verdict": "ABANDONED", "abandon_reason": "stale"},
    ]
    path.write_text(json.dumps(ledger))
    admitted = runner.begin_review_run(scheduled_reviewers=["monitor"], round_id="round-4")
    assert admitted["status"] == "success", admitted
    after = json.loads(path.read_text())["convergence"]["rounds"]
    assert [row["round_id"] for row in after[:3]] == ["round-1", "round-2", "round-3"]
    assert after[2]["verdict"] == "ABANDONED"


def test_vc3_block_verdicts_still_cap_the_budget(review_git_workspace):
    for number in ("1", "2", "3"):
        admission = ledger_tests._admit_receipt_review(runner, round_id=number)
        envelope = {"issues": [_issue()], "receipt": _receipt(admission)}
        assert runner.capture_review_output("monitor", json.dumps(envelope), number)["status"] == "success"
        assert runner.write_review_verdict_ledger(current_run=True)["status"] == "success"
    capped = runner.begin_review_run(scheduled_reviewers=["monitor"], round_id="4")
    assert capped["stop_reason"] == "reconsider_approach"


def _resolve_many(admission: dict, resolutions: list[dict], round_id: str = "second") -> dict:
    envelope = {"issues": [], "resolved_findings": resolutions, "receipt": _receipt(admission)}
    assert runner.capture_review_output("monitor", json.dumps(envelope), round_id)["status"] == "success"
    return runner.write_review_verdict_ledger(current_run=True)


@pytest.mark.parametrize("bad_first", [True, False])
def test_vc5_duplicate_resolutions_do_not_claim_a_closed_finding_stays_open(review_git_workspace, bad_first):
    admission = _carry_one_finding()
    good = ledger_tests._bound_resolution()
    bad = {**good, "cause": "some other cause"}
    result = _resolve_many(admission, [bad, good] if bad_first else [good, bad])
    assert result["findings_verdict"] == "PROCEED"
    assert [(item["fields"], item.get("superseded")) for item in result["rejected_resolutions"]] == [(["cause"], True)]
    assert "another resolution for this finding was accepted" in result["rejected_resolutions"][0]["reason"]
    markdown = (review_git_workspace / "review-verdict-ledger.md").read_text()
    assert "stays open" not in markdown and "another resolution for this finding was accepted" in markdown


def test_vc1_input_error_rounds_still_consume_the_attempt_cap(review_git_workspace):
    """A verdict written on the input-error path is a recorded verdict, so abandoning it spends an attempt."""
    del review_git_workspace
    for number in ("1", "2", "3"):
        assert ledger_tests._admit_receipt_review(runner, round_id=number)["status"] == "success"
        assert runner.capture_review_output("monitor", json.dumps({"issues": "not-a-list"}), number)["status"] == "success"
        written = runner.write_review_verdict_ledger(current_run=True)
        assert written["input_errors"], written
        assert runner.abandon_review_round(number, reason="Continue findings review")["status"] == "success"
    capped = runner.begin_review_run(scheduled_reviewers=["monitor"], round_id="4")
    assert capped.get("stop_reason") == "reconsider_approach", capped


def _adversarial_finding(mode: str) -> dict:
    return {"severity": "CRITICAL", "category": "correctness", "file_path": "writer.py", "line_range": "10-12",
            "symbol": "write", "failure_mode": mode, "evidence": f"writer.py:10 {mode}"}


def _adversarial_envelope(findings: list[dict], resolutions: list[dict], receipt: dict) -> str:
    return json.dumps({"all_clear": not findings, "findings": findings, "checks_performed": ["write rollback"],
                       "receipt": receipt, **({"resolved_findings": resolutions} if resolutions else {})})


def _adversarial_report(blind: str, acceptance: str, other: str) -> dict:
    return runner.aggregate_adversarial_findings(
        blind_json=blind, edge_case_json=other, acceptance_json=acceptance,
        role_json={role: other for role in ("maintainer", "user_experience")})


def test_vc3_adversarial_resolutions_match_by_finding_id_not_shared_bug_class(review_git_workspace):
    two = [_adversarial_finding("Committed write is lost"), _adversarial_finding("Rollback leaks a lock")]
    empty = {"covered_files": [], "skipped_files": [], "denied_access": [], "check_evidence": []}
    runner.begin_review_run(arguments="--adversarial", round_id="1")
    first = _adversarial_report(_adversarial_envelope(two, [], empty), _adversarial_envelope([], [], empty),
                                _adversarial_envelope([], [], empty))
    assert ledger_tests._capture_aggregate(first, "1")["status"] == "success"
    assert runner.abandon_review_round("1", reason="Continue findings review")["status"] == "success"
    ledger = json.loads((review_git_workspace / "review-verdict-ledger.json").read_text())
    ids = [row["id"] for row in ledger["findings_registry"]]
    assert len(ids) == 2
    admission = runner.begin_review_run(arguments="--adversarial", round_id="2")
    runner.create_review_bundle()
    receipt = _receipt(admission)
    base = ledger_tests._bound_resolution()
    closes = {**base, "finding_id": ids[1], "evidence": "second lock leak fixed"}
    keeps = {**base, "finding_id": ids[0], "evidence": "first still reachable",
             "reachability": {**base["reachability"], "status": "reachable"}}
    resolutions = [keeps, closes]  # the non-closing resolution comes first and shares bug_class/cause
    independent = [{**item, "reachability": {**item["reachability"], "reason": "independent audit agrees"}}
                   for item in resolutions]
    for reviewer, items in (("acceptance", independent), ("blind", resolutions)):
        assert runner.capture_review_output(reviewer, _adversarial_envelope([], items, receipt), "2")["status"] == "success"
    report = _adversarial_report(_adversarial_envelope([], resolutions, receipt),
                                 _adversarial_envelope([], independent, receipt),
                                 _adversarial_envelope([], [], receipt))
    result = ledger_tests._capture_aggregate(report, "2")
    assert result["status"] == "success", result
    after = json.loads((review_git_workspace / "review-verdict-ledger.json").read_text())
    registry = {row["id"]: row for row in after["findings_registry"]}
    assert registry[ids[1]].get("resolved_by"), registry[ids[1]]
    assert not registry[ids[0]].get("resolved_by"), "finding picked up another finding's resolution evidence"
    assert result["findings_verdict"] != "PROCEED"
