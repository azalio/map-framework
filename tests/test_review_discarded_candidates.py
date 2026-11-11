"""Discarded hypotheses remain reviewable through the real capture/ledger path."""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest

from tests.review_paraphrase_helpers import with_paraphrase
from tests.test_review_finding_validation import (
    _issue,
    map_step_runner,
)
from tests.test_review_finding_validation import (
    evidence_review as _evidence_review_fixture,
)

evidence_review = _evidence_review_fixture


def _candidate():
    issue = _issue()
    return {**{key: issue[key] for key in ("bug_class", "cause", "failure_scenario", "evidence_refs")},
            "candidate_id": "C-1", "dismissal_reason": "Assumed caller excludes zero",
            "dismissal_invariant": "All callers pass nonzero values"}


def _capture(runner, candidates, issues=None, round_id="audit"):
    admission = runner.begin_review_run(scheduled_reviewers=["monitor"], round_id=round_id, provider="claude")
    assert admission["status"] == "success", admission
    assert runner.create_review_bundle()["status"] == "success"
    payload = with_paraphrase({"issues": issues or [], "discarded_candidates": candidates, "receipt": {
        "covered_files": admission["required_files"], "skipped_files": [], "denied_access": [], "check_evidence": []}})
    captured = runner.capture_review_output("monitor", json.dumps(payload), round_id)
    assert captured["status"] == "success", captured
    result = runner.write_review_verdict_ledger(current_run=True)
    assert result["status"] == "success", result


def _audit_file(ledger_path, **changes):
    ledger = json.loads(ledger_path.read_text())
    candidate = ledger["discarded_candidates"][0]
    audit = {"candidate_id": candidate["id"], "binding": candidate["binding"],
             "verdict": "refuted", "reason": "Checked the precise precondition", "invariant": "Caller excludes zero",
             "evidence_refs": _issue()["baseline_attribution"]["evidence_refs"], **changes}
    path = ledger_path.parent / "candidate-audit.json"
    path.write_text(json.dumps({"schema_version": 1, "audits": [audit]}))
    return str(path)


def test_all_clear_stays_unsealed_until_parent_audits(evidence_review):
    runner = cast(Any, map_step_runner)
    _capture(runner, [_candidate()])
    ledger = json.loads(evidence_review.read_text())
    assert ledger["candidate_audit"]["pending"]
    assert ledger["code_approval"]["approved"] is False
    assert "completed_at" not in ledger["convergence"]["rounds"][-1]
    audit = _audit_file(evidence_review)
    runner.write_review_verdict_ledger(current_run=True, candidate_audit_file=audit)
    ledger = json.loads(evidence_review.read_text())
    assert ledger["candidate_audit"]["status"] == "complete"
    assert ledger["findings_verdict"] == "PROCEED"
    # Checked citations are not a semantic proof of this intentionally false invariant.
    assert ledger["discarded_candidates"][0]["audit"]["evidence_kind"] == "checked_citations_parent_reasoning"
    assert "completed_at" in ledger["convergence"]["rounds"][-1]


@pytest.mark.parametrize("change", [
    {"binding": "old"}, {"invariant": ""}, {"evidence_refs": []},
    {"evidence_refs": [{"file_path": "divide.py", "revision": "current", "quote": "invented guard"}]},
    {"verdict": "restored", "finding_id": "RVF-999"}, {"verdict": "unresolved"},
])
def test_unsupported_audit_cannot_approve(evidence_review, change):
    runner = cast(Any, map_step_runner)
    _capture(runner, [_candidate()])
    runner.write_review_verdict_ledger(current_run=True, candidate_audit_file=_audit_file(evidence_review, **change))
    ledger = json.loads(evidence_review.read_text())
    assert ledger["candidate_audit"]["status"] == "incomplete"
    assert not ledger["code_approval"]["approved"]
    assert ledger["findings_verdict"] != "PROCEED"


def test_restoration_requires_same_confirmed_finding(evidence_review):
    runner = cast(Any, map_step_runner)
    _capture(runner, [_candidate()], [_issue()])
    ledger = json.loads(evidence_review.read_text())
    finding = ledger["findings_registry"][0]
    assert finding["validation"]["verdict"] == "confirmed"
    audit = _audit_file(evidence_review, verdict="restored", finding_id=finding["id"])
    runner.write_review_verdict_ledger(current_run=True, candidate_audit_file=audit)
    ledger = json.loads(evidence_review.read_text())
    assert ledger["candidate_audit"]["status"] == "complete"
    assert ledger["findings_verdict"] != "PROCEED"
    assert ledger["discarded_candidates"][0]["audit"]["finding_id"] == finding["id"]


def test_omission_and_changed_snapshot_do_not_erase_candidate(evidence_review):
    runner = cast(Any, map_step_runner)
    _capture(runner, [_candidate()])
    audit = _audit_file(evidence_review)
    runner.write_review_verdict_ledger(current_run=True, candidate_audit_file=audit)
    Path("divide.py").write_text("def divide(value):\n    return 20 / value\n")
    _capture(runner, [], round_id="changed")
    ledger = json.loads(evidence_review.read_text())
    assert len(ledger["discarded_candidates"]) == 1
    assert ledger["candidate_audit"]["status"] == "incomplete"
    assert not ledger["code_approval"]["approved"]


@pytest.mark.parametrize("candidates", [[None], [{"candidate_id": "C-1"}], [_candidate(), _candidate()]])
def test_malformed_candidates_do_not_disappear(evidence_review, candidates):
    runner = cast(Any, map_step_runner)
    _capture(runner, candidates)
    ledger = json.loads(evidence_review.read_text())
    assert ledger["candidate_audit"]["errors"]
    assert not ledger["code_approval"]["approved"]


def test_adversarial_all_clear_preserves_rejected_candidate(evidence_review):
    runner = cast(Any, map_step_runner)
    reviewers = ["blind", "edge_case", "acceptance", "user_experience", "maintainer"]
    admission = runner.begin_review_run(review_mode="adversarial", arguments="--adversarial",
        scheduled_reviewers=reviewers, round_id="adversarial-audit", provider="claude")
    assert admission["status"] == "success", admission
    assert runner.create_review_bundle()["status"] == "success"
    envelopes = {}
    for reviewer in reviewers:
        payload = with_paraphrase({"all_clear": True, "findings": [], "checks_performed": ["division"],
            "discarded_candidates": [_candidate()] if reviewer == "blind" else [], "receipt": {
                "covered_files": admission["required_files"], "skipped_files": [], "denied_access": [], "check_evidence": []}})
        envelopes[reviewer] = json.dumps(payload)
        assert runner.capture_review_output(reviewer, envelopes[reviewer], "adversarial-audit")["status"] == "success"
    aggregate = runner.aggregate_adversarial_findings(blind_json=envelopes["blind"],
        edge_case_json=envelopes["edge_case"], acceptance_json=envelopes["acceptance"],
        role_json={role: envelopes[role] for role in ("user_experience", "maintainer")})
    assert runner.capture_review_output("adversarial", json.dumps(aggregate), "adversarial-audit")["status"] == "success"
    runner.write_review_verdict_ledger(current_run=True)
    ledger = json.loads(evidence_review.read_text())
    assert ledger["discarded_candidates"][0]["source_reviewer"] == "blind"
    assert ledger["candidate_audit"]["status"] == "incomplete"
    assert not ledger["code_approval"]["approved"]


def test_shard_merge_preserves_each_hypothesis_and_producer():
    runner = cast(Any, map_step_runner)
    candidates = [_candidate(), {**_candidate(), "cause": "another cause"}]
    outputs = [(f"s{i}", with_paraphrase({"issues": [], "discarded_candidates": [candidate], "receipt": {
        "covered_files": [f"f{i}.py"], "skipped_files": [], "denied_access": [], "check_evidence": []}}))
        for i, candidate in enumerate(candidates)]
    merged = runner._review_merge_shard_outputs("monitor", outputs,
        {"shards": [{"id": f"s{i}", "files": [f"f{i}.py"]} for i in range(2)]})
    assert [item["candidate_id"] for item in merged["discarded_candidates"]] == ["s0:C-1", "s1:C-1"]
    assert [item["source_candidate_id"] for item in merged["discarded_candidates"]] == ["C-1", "C-1"]
    assert [item["cause"] for item in merged["discarded_candidates"]] == [item["cause"] for item in candidates]


def test_restoration_cannot_point_to_different_defect(evidence_review):
    runner = cast(Any, map_step_runner)
    candidate = {**_candidate(), "cause": "unrelated old hypothesis"}
    _capture(runner, [candidate], [_issue()])
    ledger = json.loads(evidence_review.read_text())
    audit = _audit_file(evidence_review, verdict="restored", finding_id=ledger["findings_registry"][0]["id"])
    runner.write_review_verdict_ledger(current_run=True, candidate_audit_file=audit)
    ledger = json.loads(evidence_review.read_text())
    assert ledger["candidate_audit"]["status"] == "incomplete"
    assert ledger["candidate_audit"]["errors"]


def test_audit_cli_accepts_file_and_finishes_same_round(evidence_review):
    runner = cast(Any, map_step_runner)
    _capture(runner, [_candidate()])
    audit = _audit_file(evidence_review)
    result = subprocess.run([sys.executable, runner.__file__, "write_review_verdict_ledger", "--current-run",
                             "--branch", "change", "--candidate-audit-file", audit], check=False, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["status"] == "success"
    ledger = json.loads(evidence_review.read_text())
    assert ledger["candidate_audit"]["status"] == "complete"
    assert "completed_at" in ledger["convergence"]["rounds"][-1]


def test_restoration_cannot_substitute_identical_claim_at_another_file(evidence_review):
    runner = cast(Any, map_step_runner)
    candidate = {**_candidate(), "evidence_refs": [
        {"file_path": "other.py", "revision": "current", "quote": "return 10 / value"}]}
    _capture(runner, [candidate], [_issue()])
    ledger = json.loads(evidence_review.read_text())
    audit = _audit_file(evidence_review, verdict="restored", finding_id=ledger["findings_registry"][0]["id"])
    runner.write_review_verdict_ledger(current_run=True, candidate_audit_file=audit)
    ledger = json.loads(evidence_review.read_text())
    assert ledger["candidate_audit"]["status"] == "incomplete"
    assert ledger["candidate_audit"]["errors"]


@pytest.mark.parametrize("missing", [True, False])
def test_capture_requires_explicit_candidate_declaration(evidence_review, missing):
    runner = cast(Any, map_step_runner)
    admission = runner.begin_review_run(scheduled_reviewers=["monitor"], round_id="declaration", provider="claude")
    runner.create_review_bundle()
    payload = with_paraphrase({"issues": [], "receipt": {"covered_files": admission["required_files"],
        "skipped_files": [], "denied_access": [], "check_evidence": []}})
    if missing:
        payload.pop("discarded_candidates")
    else:
        payload["discarded_candidates"] = {}
    result = runner.capture_review_output("monitor", json.dumps(payload), "declaration")
    assert result["status"] == "error"
    assert "discarded_candidates" in result["message"]


def test_compare_orderings_preserves_both_predictor_candidate_lists(evidence_review):
    runner = cast(Any, map_step_runner)
    admission = runner.begin_review_run(scheduled_reviewers=list(runner.NORMAL_REVIEWERS),
        review_mode="compare_orderings", arguments="--compare-orderings", round_id="order", provider="claude")
    assert admission["status"] == "success", admission
    runner.create_review_bundle()
    receipt = {"covered_files": admission["required_files"], "skipped_files": [], "denied_access": [], "check_evidence": []}
    for ordering, risk in (("default", "low"), ("reverse", "high")):
        runner.capture_review_output("monitor", json.dumps(with_paraphrase({"issues": [], "receipt": receipt})), "order", ordering=ordering)
        payload = with_paraphrase({"risk_assessment": risk, "receipt": receipt,
            "discarded_candidates": [{**_candidate(), "failure_scenario": ordering}]})
        runner.capture_review_output("predictor", json.dumps(payload), "order", ordering=ordering)
        runner.capture_review_output("evaluator", json.dumps(with_paraphrase({"overall_score": 9, "receipt": receipt})), "order", ordering=ordering)
        for role in runner.BASE_ROLE_REVIEWERS:
            runner.capture_review_output(role, json.dumps(with_paraphrase({"all_clear": True, "findings": [],
                "checks_performed": ["source"], "receipt": receipt})), "order", ordering=ordering)
    runner.write_review_verdict_ledger(current_run=True)
    candidates = json.loads(evidence_review.read_text())["discarded_candidates"]
    assert {row["source_reviewer"]: row["candidate"]["failure_scenario"] for row in candidates} == {
        "predictor": "default", "reverse:predictor": "reverse"}


def test_restoration_retains_original_source_witnesses(evidence_review):
    runner = cast(Any, map_step_runner)
    candidate = {**_candidate(), "evidence_refs": [
        {"file_path": "divide.py", "revision": "current", "quote": "def divide(value):"}]}
    _capture(runner, [candidate], [_issue()])
    ledger = json.loads(evidence_review.read_text())
    audit = _audit_file(evidence_review, verdict="restored", finding_id=ledger["findings_registry"][0]["id"])
    runner.write_review_verdict_ledger(current_run=True, candidate_audit_file=audit)
    assert json.loads(evidence_review.read_text())["candidate_audit"]["status"] == "incomplete"


def test_role_contract_gap_cannot_be_restored_as_a_proved_finding(evidence_review):
    runner = cast(Any, map_step_runner)
    admission = runner.begin_review_run(scheduled_reviewers=list(runner.NORMAL_REVIEWERS), round_id="gap", provider="claude")
    assert admission["status"] == "success", admission
    runner.create_review_bundle()
    receipt = {"covered_files": admission["required_files"], "skipped_files": [], "denied_access": [], "check_evidence": []}
    incomplete = {**_issue(), "severity": "MINOR", "problem": "divide.py:2 public zero division",
        "current_code": "return 10 / value", "proposed_code": "return 0 if value == 0 else 10 / value",
        "why_better": "Restores zero handling"}  # cost deliberately absent
    envelopes = {"monitor": {"issues": [], "discarded_candidates": [_candidate()]},
                 "predictor": {"risk_assessment": "low"}, "evaluator": {"overall_score": 9},
                 "user_experience": {"all_clear": True, "findings": []},
                 "maintainer": {"all_clear": False, "findings": [incomplete]}}
    for reviewer, payload in envelopes.items():
        result = runner.capture_review_output(reviewer, json.dumps(with_paraphrase({**payload, "receipt": receipt})), "gap")
        assert result["status"] == "success", result
    runner.write_review_verdict_ledger(current_run=True)
    ledger = json.loads(evidence_review.read_text())
    finding = next(row for row in ledger["findings_registry"] if row.get("bug_class") == "zero_division")
    assert finding["contract_gaps"]
    audit = _audit_file(evidence_review, verdict="restored", finding_id=finding["id"])
    runner.write_review_verdict_ledger(current_run=True, candidate_audit_file=audit)
    ledger = json.loads(evidence_review.read_text())
    assert ledger["candidate_audit"]["status"] == "incomplete"
    assert not ledger["code_approval"]["approved"]


def test_restoration_accepts_original_witness_in_checked_reachability(evidence_review):
    runner = cast(Any, map_step_runner)
    Path("caller.py").write_text("result = divide(0)\n")
    witness = {"file_path": "caller.py", "revision": "current", "quote": "divide(0)"}
    issue = _issue()
    issue["reachability"]["evidence_refs"].append(witness)
    candidate = _candidate()
    candidate["evidence_refs"].append(witness)
    _capture(runner, [candidate], [issue])
    ledger = json.loads(evidence_review.read_text())
    audit = _audit_file(evidence_review, verdict="restored", finding_id=ledger["findings_registry"][0]["id"])
    runner.write_review_verdict_ledger(current_run=True, candidate_audit_file=audit)
    assert json.loads(evidence_review.read_text())["candidate_audit"]["status"] == "complete"


def test_parent_can_refute_source_free_candidate_with_checked_evidence(evidence_review):
    runner = cast(Any, map_step_runner)
    _capture(runner, [{**_candidate(), "evidence_refs": []}])
    runner.write_review_verdict_ledger(current_run=True, candidate_audit_file=_audit_file(evidence_review))
    assert json.loads(evidence_review.read_text())["candidate_audit"]["status"] == "complete"


@pytest.mark.parametrize("replacement", ["refuted", "omitted"])
def test_retained_restoration_is_rechecked_after_recapture(evidence_review, replacement):
    runner = cast(Any, map_step_runner)
    candidates = [_candidate(), {**_candidate(), "candidate_id": "C-2", "cause": "Another hypothesis still pending"}]
    _capture(runner, candidates, [_issue()])
    ledger = json.loads(evidence_review.read_text())
    identifier = ledger["discarded_candidates"][0]["id"]
    finding_id = ledger["findings_registry"][0]["id"]
    runner.write_review_verdict_ledger(current_run=True, candidate_audit_file=_audit_file(
        evidence_review, verdict="restored", finding_id=finding_id))
    runner.write_review_verdict_ledger(current_run=True)  # unchanged proof remains valid
    ledger = json.loads(evidence_review.read_text())
    entry = next(row for row in ledger["discarded_candidates"] if row["id"] == identifier)
    assert entry["audit"]["verdict"] == "restored"
    binding = entry["binding"]
    revised = _issue()
    revised["reachability"]["status"] = "unreachable"
    payload = with_paraphrase({"issues": [revised] if replacement == "refuted" else [],
        "discarded_candidates": [], "receipt": {"covered_files": ["divide.py"], "skipped_files": [],
                                                 "denied_access": [], "check_evidence": []}})
    assert runner.capture_review_output("monitor", json.dumps(payload), "audit")["status"] == "success"
    runner.write_review_verdict_ledger(current_run=True)
    ledger = json.loads(evidence_review.read_text())
    assert next(row for row in ledger["findings_registry"] if row["id"] == finding_id)["validation"]["verdict"] != "confirmed"
    entry = next(row for row in ledger["discarded_candidates"] if row["id"] == identifier)
    assert entry["binding"] == binding
    assert entry["audit"]["verdict"] == "pending"
    assert identifier in ledger["candidate_audit"]["pending"]
