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


@pytest.mark.parametrize("candidates", [{}, [None], [{"candidate_id": "C-1"}], [_candidate(), _candidate()]])
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
