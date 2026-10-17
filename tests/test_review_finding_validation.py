"""Evidence validation through captured review rounds, not private helpers."""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src/mapify_cli/templates/map/scripts"))
import map_step_runner  # type: ignore[import-not-found]


@pytest.fixture()
def evidence_review(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(map_step_runner, "get_branch_name", lambda: "change")
    subprocess.run(["git", "init", "-b", "main"], check=True, capture_output=True)
    for key, value in (("user.email", "test@example.com"), ("user.name", "Test")):
        subprocess.run(["git", "config", key, value], check=True)
    Path(".gitignore").write_text(".map/\n")
    Path("divide.py").write_text("def divide(value):\n    if value == 0:\n        return 0\n    return 10 / value\n")
    subprocess.run(["git", "add", "."], check=True)
    subprocess.run(["git", "commit", "-m", "guarded baseline"], check=True, capture_output=True)
    subprocess.run(["git", "checkout", "-b", "change"], check=True, capture_output=True)
    Path("divide.py").write_text("def divide(value):\n    return 10 / value\n")
    profile = Path(".claude/agents/review-reader.md")
    profile.parent.mkdir(parents=True)
    profile.write_text("---\nname: review-reader\ntools: Read, Glob, Grep\n---\nRead only.\n")
    return tmp_path / ".map/change/review-verdict-ledger.json"


def _issue():
    current = {"file_path": "divide.py", "revision": "current", "quote": "return 10 / value"}
    baseline = {"file_path": "divide.py", "revision": "baseline", "quote": "if value == 0:\n        return 0"}
    return {"severity": "HIGH", "category": "correctness", "description": "divide(0) raises ZeroDivisionError",
            "reach_evidence": "public divide accepts zero", "was_present_before_pr": False,
            "bug_class": "zero_division", "cause": "removed zero guard", "failure_scenario": "call divide(0)",
            "evidence_refs": [current], "reachability": {"status": "reachable",
                "reason": "divide accepts value=0 without a guard before division", "evidence_refs": [current]},
            "baseline_attribution": {"status": "introduced", "reason": "baseline returns 0 before division",
                                     "evidence_refs": [current, baseline]}}


def _round(runner, round_id, issues, resolutions=None):
    admission = runner.begin_review_run(scheduled_reviewers=["monitor"], round_id=round_id)
    assert admission["status"] == "success", admission
    assert runner.create_review_bundle()["status"] == "success"
    payload = {"issues": issues, "resolved_findings": resolutions or [], "receipt": {
        "covered_files": admission["required_files"], "skipped_files": [], "denied_access": [], "check_evidence": []}}
    runner.capture_review_output("monitor", json.dumps(payload), round_id)
    return runner.write_review_verdict_ledger(current_run=True)


@pytest.mark.parametrize("defect", ["empty_scope", "unresolved_occurrence", "wrong_file_reference", "uncertainty"])
def test_sibling_search_does_not_close_without_bounded_checked_disposition(evidence_review, defect):
    runner = cast(Any, map_step_runner)
    _round(runner, "found", [_issue()])
    original = json.loads(evidence_review.read_text())["findings_registry"][0]
    assert original["validation"]["verdict"] == "confirmed"
    search = {"searched_scope": ["divide.py"], "method": "inspect each division and its guards",
              "uncertainty": "", "scope_expansion": [], "occurrences": [{"file_path": "divide.py",
                  "disposition": "fixed", "evidence_refs": _issue()["evidence_refs"]}]}
    if defect == "empty_scope":
        search["searched_scope"] = []
    elif defect == "unresolved_occurrence":
        search["occurrences"][0]["disposition"] = "unresolved"
    elif defect == "wrong_file_reference":
        search["occurrences"][0]["file_path"] = ".gitignore"
    else:
        search["uncertainty"] = "dynamic callers remain unknown"
    issue = _issue()
    resolution = {**issue, "finding_id": original["id"], "evidence": "guard reviewed",
        "reachability": {**issue["reachability"], "status": "unreachable"}, "sibling_search": search}
    _round(runner, "resolve", [], [resolution])
    ledger = json.loads(evidence_review.read_text())
    assert ledger["findings_registry"][0]["validation"]["verdict"] == "insufficient_evidence"
    assert ledger["findings_verdict"] != "PROCEED"


@pytest.mark.parametrize("builder", ["build_review_prompts", "build_role_review_prompts", "build_adversarial_review_prompts"])
def test_reviewer_dispatch_includes_evidence_contract_before_capture(builder):
    runner = cast(Any, map_step_runner)
    result = getattr(runner, builder)(git_diff_text="diff")
    prompts = result["prompts"]
    for reviewer, entry in prompts.items():
        if reviewer == "complexity_lens":
            continue
        assert "baseline_attribution" in entry["prompt"], reviewer
        assert "failure_scenario" in entry["prompt"], reviewer
        assert "evidence_refs" in entry["prompt"], reviewer
        assert "cause" in entry["prompt"], reviewer


def test_new_file_attribution_uses_runner_checked_baseline_absence(evidence_review):
    runner = cast(Any, map_step_runner)
    Path("new_divide.py").write_text("def divide(value):\n    return 10 / value\n")
    issue = _issue()
    current = {"file_path": "new_divide.py", "revision": "current", "quote": "return 10 / value"}
    issue["evidence_refs"] = [current]
    issue["reachability"]["evidence_refs"] = [current]
    issue["baseline_attribution"]["evidence_refs"] = [current, {
        "file_path": "new_divide.py", "revision": "baseline", "absent": True}]
    _round(runner, "new-file", [issue])
    assert json.loads(evidence_review.read_text())["findings_registry"][0]["validation"]["verdict"] == "confirmed"


@pytest.mark.parametrize("concrete_defect", [False, True])
def test_low_risk_predictor_only_creates_a_finding_for_a_concrete_defect(concrete_defect):
    predictor = {"risk_assessment": "low", "predicted_state": {"breaking_changes": []}}
    if concrete_defect:
        predictor.update(_issue())
    ledger = map_step_runner.normalize_review_verdict(predictor_result=predictor)
    findings = [row for row in ledger["findings_registry"] if row["source_agent"] == "predictor"]
    if concrete_defect:
        assert len(findings) == 1
        assert findings[0]["bug_class"] == "zero_division"
        assert findings[0]["cause"] == "removed zero guard"
        assert findings[0]["failure_scenario"] == "call divide(0)"
    else:
        assert findings == []


def test_same_description_different_causes_keep_their_metadata():
    first = _issue()
    second = {**first, "cause": "different underlying cause"}
    ledger = map_step_runner.normalize_review_verdict(monitor_result={"issues": [first, second]})
    assert [row["cause"] for row in ledger["findings_registry"]] == [
        "removed zero guard", "different underlying cause"]


def test_resolution_cannot_replace_the_finding_cause(evidence_review):
    runner = cast(Any, map_step_runner)
    _round(runner, "found", [_issue()])
    finding = json.loads(evidence_review.read_text())["findings_registry"][0]
    resolution = {**_issue(), "finding_id": finding["id"], "evidence": "another cause is fixed",
                  "cause": "different underlying cause"}
    result = _round(runner, "substitute", [], [resolution])
    assert result["status"] == "error"
    preserved = json.loads(evidence_review.read_text())["findings_registry"][0]
    assert preserved["cause"] == "removed zero guard"
    assert preserved["status"] != "tombstoned"


def test_omitted_finding_cannot_borrow_an_unrelated_fresh_capture(evidence_review):
    runner = cast(Any, map_step_runner)
    _round(runner, "found", [_issue()])
    assert json.loads(evidence_review.read_text())["findings_registry"][0]["validation"]["verdict"] == "confirmed"
    _round(runner, "omitted", [])
    ledger = json.loads(evidence_review.read_text())
    finding = ledger["findings_registry"][0]
    assert finding["validation"]["verdict"] == "insufficient_evidence"
    assert finding["validation"]["capture_receipts"] == {}
    assert ledger["findings_verdict"] != "PROCEED"
