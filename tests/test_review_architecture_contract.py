"""Architectural findings survive both review paths without an invented patch."""

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src/mapify_cli/templates/map/scripts"))
import map_step_runner as runner  # type: ignore[import-not-found]

from tests.review_paraphrase_helpers import with_paraphrase


def architecture_finding():
    return {
        "reviewer": "maintainer",
        "id": "F-M-ownership",
        "severity": "IMPORTANT",
        "category": "architecture",
        "file_path": "install.py",
        "symbol": "admit",
        "problem": "install.py:1 and finish.py:1 independently decide whether a snapshot job is obsolete",
        "current_code": "if live.revision != snapshot.revision: retire(job)",
        "why_better": "One owner decides admission and completion from the same durable decision",
        "cost": "Migrate in-flight jobs and change completion's input",
        "design_change": {
            "invariant": "A run has one authority for its target revision and terminal outcome",
            "current_owners": ["install.py:admit", "finish.py:complete"],
            "proposed_owner": "run.py:RunState owns the durable admission and terminal outcome",
            "affected_sites": ["install.py:admit consumes RunState", "finish.py:complete consumes RunState"],
            "migration": "Finish existing snapshot runs before enabling the new state representation",
            "validation": "Change live revision mid-run and restart; all consumers observe the same outcome",
        },
        "evidence": "install.py retires a run; finish.py independently excludes it from completion",
    }


def through_ledger(finding, mode):
    if mode == "normal":
        return runner.normalize_review_verdict(role_findings=[finding])
    aggregate = runner.aggregate_adversarial_findings(role_json={
        "maintainer": json.dumps(with_paraphrase({"reviewer": "maintainer", "all_clear": False,
            "checks_performed": ["trace ownership"], "receipt": {
                "covered_files": [], "skipped_files": [], "denied_access": [], "check_evidence": []},
            "findings": [finding]}))
    })
    assert not aggregate["parse_errors"]
    return runner.normalize_review_verdict(adversarial_findings=aggregate["ledger_findings"])


@pytest.mark.parametrize("mode", ["normal", "adversarial"])
def test_concrete_design_change_survives_without_proposed_code(mode):
    finding = architecture_finding()
    ledger = through_ledger(finding, mode)
    row, = ledger["findings_registry"]
    assert row["status"] == "active"
    assert row["transition_reason"] is None
    assert row["category"] == "maintainability"
    assert row["design_change"] == finding["design_change"]
    assert ledger["computed_verdict"] == "REVISE"
    assert not ledger["not_verified"]


@pytest.mark.parametrize("mode", ["normal", "adversarial"])
@pytest.mark.parametrize("field", ["invariant", "current_owners", "proposed_owner", "affected_sites", "migration", "validation"])
def test_incomplete_design_change_remains_visible_and_unverified(mode, field):
    finding = architecture_finding()
    del finding["design_change"][field]
    ledger = through_ledger(finding, mode)
    row, = ledger["findings_registry"]
    assert row["transition_reason"] == "contract_incomplete"
    assert "design_change." + field in row["transition_evidence"]
    assert ledger["computed_verdict"] != "PROCEED"
    assert ledger["not_verified"]


@pytest.mark.parametrize("bad", ["extract a helper", {}, {"invariant": "too complicated"}])
def test_vague_design_advice_is_not_a_complete_finding(bad):
    finding = architecture_finding()
    finding["design_change"] = bad
    assert runner.role_finding_contract_gaps(finding)


@pytest.mark.parametrize("field,bad", [("current_owners", "install.py"), ("affected_sites", []),
                                      ("invariant", []), ("validation", " ")])
def test_design_contract_rejects_wrong_types_and_empty_fields(field, bad):
    finding = architecture_finding()
    finding["design_change"][field] = bad
    assert "design_change." + field in runner.role_finding_contract_gaps(finding)


def test_existing_patch_contract_still_works_without_design_change():
    finding = architecture_finding()
    del finding["design_change"]
    finding["proposed_code"] = "def admit(job): return job.state.admitted"
    assert runner.role_finding_contract_gaps(finding) == []


def test_adversarial_capture_owner_comes_from_envelope_not_finding():
    finding = architecture_finding()
    finding["reviewer"] = "monitor"
    ledger = through_ledger(finding, "adversarial")
    row, = ledger["findings_registry"]
    assert row["originating_reviewer"] == "maintainer"
    assert row["reported_by"] == ["maintainer"]


@pytest.mark.parametrize("builder", ["build_role_review_prompts", "build_review_prompts", "build_adversarial_review_prompts"])
def test_maintainer_gets_ownership_trace_and_alternative_remediation_contract(builder):
    result = getattr(runner, builder)(git_diff_text="diff")
    prompt = result["prompts"]["maintainer"]["prompt"]
    assert "design_change" in prompt
    assert "source of truth" in prompt
    assert "restart" in prompt
    assert "Moving unchanged code" in prompt


@pytest.mark.parametrize("mode,second_reach,expected", [
    ("normal", None, "confirmed"),
    ("compare_orderings", None, "confirmed"),
    ("adversarial", None, "insufficient_evidence"),
    ("adversarial", "reachable", "confirmed"),
    ("adversarial", "unreachable", "insufficient_evidence"),
])
@pytest.mark.parametrize("remedy", ["design", "patch"])
def test_captured_design_finding_reaches_persisted_verdict(tmp_path, monkeypatch, mode, second_reach, expected, remedy):
    fixture = json.loads((Path(__file__).parent / "skills_eval/fixtures/review_ownership.json").read_text())
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(runner, "get_branch_name", lambda: "change")

    def git(*args):
        subprocess.run(["git", *args], check=True, capture_output=True)

    git("init", "-b", "main")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Test")
    Path(".gitignore").write_text(".map/\n.claude/\n")
    for name, content in fixture["baseline"].items():
        Path(name).write_text(content)
    git("add", ".")
    git("commit", "-m", "snapshot baseline")
    git("checkout", "-b", "change")
    for name, content in fixture["candidate"].items():
        Path(name).write_text(content)
    profile = Path(".claude/agents/review-reader.md")
    profile.parent.mkdir(parents=True)
    profile.write_text("---\nname: review-reader\ntools: Read, Glob, Grep\n---\nRead only.\n")
    roster = runner.ADVERSARIAL_REVIEWERS if mode == "adversarial" else runner.NORMAL_REVIEWERS
    admitted = runner.begin_review_run(review_mode=mode, scheduled_reviewers=list(roster),
                                      round_id="ownership", provider="claude",
                                      arguments={"adversarial": "--adversarial", "compare_orderings": "--compare-orderings"}.get(mode, ""))
    assert admitted["status"] == "success", admitted
    assert runner.create_review_bundle()["status"] == "success"
    current = [
        {"file_path": "worker.py", "revision": "current",
         "quote": "if live['revision'] != task['revision']:"},
        {"file_path": "publisher.py", "revision": "current",
         "quote": "if state.get('retired') or live['revision'] != task['revision']:"},
        {"file_path": "completion.py", "revision": "current",
         "quote": "pending = [t for t in tasks if not (states[t['id']].get('retired') and not states[t['id']].get('started'))]"},
    ]
    baseline = {"file_path": "worker.py", "revision": "baseline", "quote": "source.apply(task['payload'])"}
    finding = architecture_finding()
    finding.update(file_path="worker.py", symbol="reconcile", current_code=current[0]["quote"],
        problem="worker.py, publisher.py and completion.py independently decide whether a run is obsolete",
        bug_class="split_lifecycle_authority", cause="Live revision gates are mixed with snapshot completion",
        failure_scenario="Change revision before work: worker retires the task, publication skips its result and completion reports success",
        evidence="worker.py retires a task; publisher.py skips its result; completion.py excludes it from pending work",
        evidence_refs=current,
        reachability={"status": "reachable", "reason": "A live revision change enters these guards", "evidence_refs": current},
        baseline_attribution={"status": "introduced", "reason": "Previously the worker applied the captured task without a live gate",
                              "evidence_refs": [*current, baseline]})
    finding["design_change"]["current_owners"] = ["worker.py:reconcile", "publisher.py:publish", "completion.py:complete"]
    finding["design_change"]["affected_sites"] = [
        "worker.py:reconcile records one durable run decision",
        "publisher.py:publish publishes that decision",
        "completion.py:complete consumes that decision",
    ]
    if remedy == "patch":
        del finding["design_change"]
        finding["proposed_code"] = "def reconcile(task, run): return run.apply(task)"
    # A payload cannot select a different author's capture for validation.
    finding["reviewer"] = "monitor"
    payload = {"discarded_candidates": [], "paraphrase": {
        "change": "The worker and publisher now consult live revisions; completion excludes retired tasks.",
        "existing_system": "Each run applies the captured task and finishes after all tasks report done."},
        "reviewer": "maintainer", "all_clear": False, "findings": [finding],
        "checks_performed": ["traced worker, publisher and completion against baseline"], "receipt": {
            "covered_files": admitted["required_files"], "skipped_files": [], "denied_access": [], "check_evidence": []}}
    envelopes = {}
    for reviewer in roster:
        envelope = payload if reviewer == "maintainer" else {
            "discarded_candidates": [], "paraphrase": payload["paraphrase"], "reviewer": reviewer, "all_clear": True,
            "all_clear_rationale": "No additional findings in this capture-path fixture",
            "findings": [], "issues": [], "risk_assessment": "low", "overall_score": 8,
            "checks_performed": [], "receipt": payload["receipt"],
        }
        if reviewer == "blind" and second_reach:
            envelope = copy.deepcopy(payload)
            envelope["reviewer"] = reviewer
            other = envelope["findings"][0]
            other["reachability"]["status"] = second_reach
            other["reachability"]["reason"] = "Independent entrypoint audit of the live revision guard"
            if remedy == "design":
                del other["design_change"]
                other["failure_mode"] = other["problem"]
        envelopes[reviewer] = json.dumps(envelope)
        for ordering in (("default", "reverse") if mode == "compare_orderings" else ("",)):
            captured_envelope = copy.deepcopy(envelope)
            if mode == "compare_orderings" and ordering == "reverse" and reviewer == "maintainer" and remedy == "design":
                del captured_envelope["findings"][0]["design_change"]
                captured_envelope["findings"][0]["proposed_code"] = "def reconcile(task, run): return run.apply(task)"
            captured = runner.capture_review_output(reviewer, json.dumps(captured_envelope), "ownership", ordering=ordering)
            assert captured["status"] == "success", captured
    if mode == "adversarial":
        aggregate = runner.aggregate_adversarial_findings(
            blind_json=envelopes["blind"], edge_case_json=envelopes["edge_case"],
            acceptance_json=envelopes["acceptance"],
            role_json={name: envelopes[name] for name in runner.BASE_ROLE_REVIEWERS})
        assert not aggregate["parse_errors"]
        Path(".map/change/review-agent-adversarial.json").write_text(json.dumps(aggregate))
    result = runner.write_review_verdict_ledger(current_run=True, review_mode=mode)
    assert result["status"] == "success", result
    ledger = json.loads(Path(".map/change/review-verdict-ledger.json").read_text())
    row, = [f for f in ledger["findings_registry"] if f.get("bug_class") == "split_lifecycle_authority"]
    assert row["status"] == ("active" if expected == "confirmed" else "downgraded")
    assert row["validation"]["verdict"] == expected
    assert row["originating_reviewer"] == ("blind" if second_reach else "maintainer")
    if mode != "adversarial":
        assert set(row["validation"]["capture_receipts"]) == (
            {"default:maintainer", "reverse:maintainer"} if mode == "compare_orderings" else {"default:maintainer"})
    else:
        assert {v["reviewer"] for v in row["validation"]["validations"]} == (
            {"blind", "maintainer"} if second_reach else {"maintainer"})
    if remedy == "design":
        if second_reach:
            assert "design_change" not in row
            assert row["remedies"] == [{"reviewer": "maintainer", "ordering": "default",
                                       "design_change": finding["design_change"]}]
        else:
            assert row["design_change"] == finding["design_change"]
        if mode == "compare_orderings":
            assert row["remedies"] == [
                {"reviewer": "maintainer", "ordering": "default", "design_change": finding["design_change"]},
                {"reviewer": "maintainer", "ordering": "reverse",
                 "proposed_code": "def reconcile(task, run): return run.apply(task)"},
            ]
    assert ledger["computed_verdict"] != "PROCEED"
    assert not any(f.get("transition_reason") == "input_integrity" for f in ledger["findings_registry"])


@pytest.mark.parametrize("mode", ["normal", "adversarial"])
@pytest.mark.parametrize("bad", [None, "", " ", [], ["patch"], {}, {"code": "patch"}, 42, True])
def test_invalid_patch_remedy_is_not_coerced_into_code(mode, bad):
    finding = architecture_finding()
    del finding["design_change"]
    finding["proposed_code"] = bad
    ledger = through_ledger(finding, mode)
    row, = ledger["findings_registry"]
    assert row["transition_reason"] == "contract_incomplete"
    assert "proposed_code" in row["transition_evidence"]
    assert ledger["not_verified"]


def test_valid_patch_does_not_require_optional_malformed_design():
    finding = architecture_finding()
    finding.update(proposed_code="def admit(job): return job.state.admitted", design_change=[])
    assert runner.role_finding_contract_gaps(finding) == []


def test_hunter_primary_preserves_secondary_design_with_separate_author():
    finding = architecture_finding()
    finding.update(bug_class="split_owner", cause="duplicated authority", failure_scenario="live revision changes")
    hunter = {**finding, "reviewer": "monitor", "failure_mode": finding["problem"]}
    del hunter["design_change"]
    aggregate = runner.aggregate_adversarial_findings(
        blind_json=json.dumps(with_paraphrase({"all_clear": False, "findings": [hunter]})),
        role_json={"maintainer": json.dumps(with_paraphrase({"all_clear": False, "findings": [finding],
            "receipt": {"covered_files": [], "skipped_files": [], "denied_access": [], "check_evidence": []}}))})
    assert not aggregate["parse_errors"]
    row, = runner.normalize_review_verdict(adversarial_findings=aggregate["ledger_findings"])["findings_registry"]
    assert row["originating_reviewer"] == "blind"
    assert "design_change" not in row
    assert row["remedies"] == [{"reviewer": "maintainer", "design_change": finding["design_change"]}]


def test_envelope_key_index_ignores_spoofed_finding_reviewer():
    finding = architecture_finding()
    expected = runner._review_envelope_finding_keys("maintainer", {"findings": [finding]})
    finding["reviewer"] = "monitor"
    assert runner._review_envelope_finding_keys("maintainer", {"findings": [finding]}) == expected


@pytest.mark.parametrize("problem", ["missing_source", "bad_source", "missing_capture", "bad_capture_hash"])
def test_design_remedy_never_substitutes_for_checked_validation(tmp_path, monkeypatch, problem):
    # Reuse the existing ledger suite's real git workspace and bound evidence fixture.
    from tests.test_review_verdict_ledger import _bound_resolution

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(runner, "get_branch_name", lambda: "change")
    Path(".map/change").mkdir(parents=True)
    finding = architecture_finding()
    finding.update(_bound_resolution())
    finding.pop("finding_id")
    finding["reachability"]["status"] = "reachable"
    ledger = runner.normalize_review_verdict(role_findings=[finding])
    row, = ledger["findings_registry"]
    subprocess.run(["git", "init", "-b", "main"], check=True, capture_output=True)
    Path("writer.py").write_text("VALUE = 1\n")
    subprocess.run(["git", "add", "writer.py"], check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.com",
                    "commit", "-m", "baseline"], check=True, capture_output=True)
    target = {"required_files": ["writer.py"], "base": "HEAD"}
    artifact = Path(".map/change/capture.json")
    artifact.write_text(json.dumps({"findings": [finding]}))
    receipt = {"artifact": artifact.name, "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest()}
    admitted = {"target": target, "policy_hash": "policy", "binding": {"arguments": ""},
                "receipts": {"default:maintainer": receipt}}
    # Positive control proves the same admitted snapshot and capture really validate.
    runner._validate_review_findings(ledger, admitted)
    assert row["validation"]["verdict"] == "confirmed"
    if problem == "missing_source":
        row.pop("evidence_refs")
    elif problem == "bad_source":
        row["evidence_refs"] = [{"file_path": "writer.py", "revision": "current", "quote": "not in snapshot"}]
    elif problem == "missing_capture":
        admitted["receipts"] = {}
    else:
        receipt["sha256"] = "wrong"
    runner._validate_review_findings(ledger, admitted)
    assert row["validation"]["verdict"] == "insufficient_evidence"
    assert ledger["not_verified"]
    reason = "Source references" if problem in {"missing_source", "bad_source"} else "capture provenance"
    assert any(reason in message for message in row["validation"]["reasons"])
