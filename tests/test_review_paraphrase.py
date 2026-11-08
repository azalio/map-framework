"""Paraphrase-first reviewer output (#670).

Every /map-review reviewer restates the change and the existing system before
its findings. A capture without a valid paraphrase is rejected so the relay can
retry the live reviewer; the ledger shows each paraphrase next to the findings
it qualifies; a misread is recorded as a ``paraphrase_mismatch`` objection that
keeps the findings for re-check.
"""

import copy
import json
import re
from pathlib import Path
from typing import Any, cast

import pytest

from tests import test_review_verdict_ledger as ledger_tests
from tests.review_paraphrase_helpers import PARAPHRASE, with_paraphrase
from tests.test_role_coverage_receipts import admitted_role_review, envelope

runner = ledger_tests.map_step_runner
branch_workspace = ledger_tests.branch_workspace
review_git_workspace = ledger_tests.review_git_workspace
__all__ = ["admitted_role_review", "branch_workspace", "review_git_workspace"]

ROLES = tuple(runner.ROLE_REVIEWER_IDS)
HUNTERS = ("blind", "edge_case", "acceptance")
CAP = 1200
DEFECTS = ["missing", "null", "string", "empty_change", "blank_existing", "missing_existing", "overlong"]

CORE = {
    "monitor": {"verdict": "approved", "issues": []},
    "predictor": {"risk_assessment": "low", "predicted_state": {"breaking_changes": []}},
    "evaluator": {"overall_score": 10, "recommendation": "proceed"},
}


def _break(payload: dict, defect: str) -> dict:
    broken = copy.deepcopy(payload)
    if defect == "missing":
        broken.pop("paraphrase", None)
    elif defect == "null":
        broken["paraphrase"] = None
    elif defect == "string":
        broken["paraphrase"] = "I read the diff"
    elif defect == "empty_change":
        broken["paraphrase"]["change"] = ""
    elif defect == "blank_existing":
        broken["paraphrase"]["existing_system"] = "   "
    elif defect == "missing_existing":
        del broken["paraphrase"]["existing_system"]
    else:
        broken["paraphrase"]["change"] = "x" * (CAP + 1)
    return broken


def _role_payload(role: str, covered) -> dict:
    return with_paraphrase(envelope(role, covered=covered))


def _core_payload(role: str, covered) -> dict:
    receipt = envelope("maintainer", covered=covered)["receipt"]
    return with_paraphrase({**CORE[role], "receipt": receipt})


def _hunter(**extra) -> dict:
    return with_paraphrase({"reviewer": "blind", "all_clear": True, "all_clear_rationale": "Checked the diff",
                            "findings": [], "checks_performed": ["read diff"], **extra})


def test_paraphrase_cap_is_explicit_and_shared():
    assert runner.REVIEWER_PARAPHRASE_MAX_CHARS == CAP
    assert set(runner.REVIEWER_PARAPHRASE_SCHEMA) == {"change", "existing_system"}
    expected = {"monitor", "predictor", "evaluator", *ROLES, *HUNTERS}
    assert set(runner.REVIEWER_PARAPHRASE_AGENTS) == expected
    for agent in expected:
        schema = runner.AGENT_OUTPUT_SCHEMAS[agent]
        assert "paraphrase" in schema["required_keys"]
        assert schema["skeleton"]["paraphrase"] is runner.REVIEWER_PARAPHRASE_SCHEMA
        assert next(iter(schema["skeleton"])) == "paraphrase"  # paraphrase comes before findings
    assert "paraphrase" not in runner.AGENT_OUTPUT_SCHEMAS["actor"]["required_keys"]


@pytest.mark.parametrize("role", [*CORE, *ROLES])
@pytest.mark.parametrize("defect", DEFECTS)
def test_capture_rejects_role_reviewer_without_valid_paraphrase(admitted_role_review, role, defect):
    workspace, admission = admitted_role_review
    build = _core_payload if role in CORE else _role_payload
    valid = build(role, admission["required_files"])
    result = runner.capture_review_output(role, json.dumps(_break(valid, defect)), "receipt")
    assert result["status"] == "error", result
    assert "paraphrase" in result["message"]
    assert not (workspace / f"review-agent-{role}.json").exists()
    accepted = runner.capture_review_output(role, json.dumps(valid), "receipt")
    assert accepted["status"] == "success", accepted
    stored = json.loads((workspace / f"review-agent-{role}.json").read_text())
    assert stored["paraphrase"] == PARAPHRASE


@pytest.mark.parametrize("role", [*ROLES, *HUNTERS, "review-monitor", "predictor", "evaluator"])
def test_truncation_gate_and_retry_prompt_demand_paraphrase(role):
    if role in ROLES:
        payload = envelope(role)
        del payload["paraphrase"]
    elif role in HUNTERS:
        payload = {"all_clear": True, "findings": []}
    else:
        payload = {key: [] for key in runner.AGENT_OUTPUT_SCHEMAS[role.removeprefix("review-")]["required_keys"]
                   if key != "paraphrase"}
    result = cast(dict[str, Any], runner.detect_truncated_agent_output(json.dumps(payload), agent_kind=role))
    reasons: list[str] = result["reasons"]
    assert result["truncated"] is True
    assert "missing required key: paraphrase" in reasons
    overlong = cast(dict[str, Any], runner.detect_truncated_agent_output(
        json.dumps(_break(with_paraphrase(payload), "overlong")), agent_kind=role))
    assert overlong["truncated"] is True
    assert any("exceeds 1200 characters" in reason for reason in overlong["reasons"])
    assert runner.detect_truncated_agent_output(json.dumps(with_paraphrase(payload)),
                                                agent_kind=role)["truncated"] is False
    retry = cast(dict[str, Any], runner.build_json_retry_prompt(role.removeprefix("review-"), reasons))
    prompt: str = retry["prompt"]
    assert retry["status"] == "ok"
    assert '"paraphrase"' in prompt and '"existing_system"' in prompt
    assert "Fill paraphrase FIRST" in prompt


def test_map_efficient_monitor_gate_does_not_require_paraphrase():
    payload = {"valid": True, "summary": "ok", "issues": []}
    assert runner.detect_truncated_agent_output(json.dumps(payload), agent_kind="monitor")["truncated"] is False


@pytest.mark.parametrize("builder", ["build_review_prompts", "build_adversarial_review_prompts"])
def test_dispatch_prompts_carry_paraphrase_schema_and_cap(review_git_workspace, builder):
    del review_git_workspace
    result = getattr(runner, builder)()
    assert result["status"] == "success", result
    for role, entry in result["prompts"].items():
        if role == "complexity_lens":
            continue
        prompt = entry["prompt"]
        match = re.search(r"<output_schema>\s*(.*?)\s*</output_schema>", prompt, re.DOTALL)
        assert match, role
        schema = json.loads(match[1])
        assert schema["paraphrase"] == runner.REVIEWER_PARAPHRASE_SCHEMA, role
        assert "Fill paraphrase FIRST" in prompt, role
        assert "at most 1200 characters" in prompt, role


@pytest.mark.parametrize("name", [*HUNTERS, *ROLES])
@pytest.mark.parametrize("defect", ["missing", "overlong"])
def test_aggregate_marks_reviewer_without_paraphrase_as_parse_error(name, defect):
    good = {"blind": _hunter(), **{role: _role_payload(role, []) for role in ROLES}}
    good["edge_case"] = _hunter(reviewer="edge_case")
    good["acceptance"] = _hunter(reviewer="acceptance")
    inputs = {key: json.dumps(value) for key, value in good.items()}
    inputs[name] = json.dumps(_break(good[name], defect))
    report = runner.aggregate_adversarial_findings(
        inputs["blind"], inputs["edge_case"], inputs["acceptance"], {role: inputs[role] for role in ROLES})
    assert report["reviewer_status"][name]["status"] == "parse_error"
    assert "raw" not in report["reviewer_status"][name]
    assert any(error.startswith(f"{name}: paraphrase") for error in report["parse_errors"])
    for other in good:
        if other != name:
            assert report["reviewer_status"][other]["status"] == "ok", other


@pytest.mark.parametrize("name", [*HUNTERS, *ROLES])
@pytest.mark.parametrize("defect", ["missing", "empty_change", "overlong"])
def test_adversarial_capture_rejects_raw_output_without_paraphrase(review_git_workspace, name, defect):
    """A hunter without a receipt claims no coverage, but no reviewer with raw output skips the paraphrase."""
    workspace = review_git_workspace
    admission = runner.begin_review_run(arguments="--adversarial", round_id="paraphrase", review_mode="adversarial",
                                        scheduled_reviewers=[*runner.ADVERSARIAL_REVIEWERS, "security"])
    assert admission["status"] == "success", admission
    report = runner.aggregate_adversarial_findings(
        json.dumps(_hunter()), json.dumps(_hunter(reviewer="edge_case")), json.dumps(_hunter(reviewer="acceptance")),
        {role: json.dumps(_role_payload(role, [])) for role in ROLES})
    assert all(entry["status"] == "ok" for entry in report["reviewer_status"].values()), report["parse_errors"]
    invalid = copy.deepcopy(report)
    invalid["reviewer_status"][name]["raw"] = _break(report["reviewer_status"][name]["raw"], defect)
    result = runner.capture_review_output("adversarial", json.dumps(invalid), "paraphrase")
    assert result["status"] == "error", result
    assert f"Invalid {name} paraphrase" in result["message"]
    assert not (workspace / "review-agent-adversarial.json").exists()
    assert runner.capture_review_output("adversarial", json.dumps(report), "paraphrase")["status"] == "success"


def test_ledger_and_report_show_paraphrase_next_to_findings(admitted_role_review):
    workspace, admission = admitted_role_review
    covered = admission["required_files"]
    monitor = _core_payload("monitor", covered)
    monitor["paraphrase"] = {"change": "Monitor says VALUE moves to 2.",
                             "existing_system": "Monitor says writer.py is a constant holder."}
    monitor["verdict"] = "needs_revision"
    monitor["issues"] = [{"severity": "MEDIUM", "category": "correctness", "description": "VALUE change is untested",
                          "file_path": "writer.py", "line_range": "1", "was_present_before_pr": False,
                          "reach_evidence": "grep:VALUE:1"}]
    for role in CORE:
        payload = monitor if role == "monitor" else _core_payload(role, covered)
        assert runner.capture_review_output(role, json.dumps(payload), "receipt")["status"] == "success"
    for role in ROLES:
        assert runner.capture_review_output(role, json.dumps(_role_payload(role, covered)), "receipt")["status"] == "success"
    assert runner.write_review_verdict_ledger(current_run=True)["status"] == "success"
    ledger = json.loads((workspace / "review-verdict-ledger.json").read_text())
    entry = ledger["reviewer_paraphrases"]["monitor"]
    assert entry["paraphrase"] == monitor["paraphrase"]
    monitor_ids = [row["id"] for row in ledger["findings_registry"] if row["source_agent"] == "monitor"]
    assert monitor_ids and entry["finding_ids"] == monitor_ids
    assert ledger["reviewer_paraphrases"]["maintainer"]["paraphrase"] == PARAPHRASE
    assert ledger["reviewer_paraphrases"]["maintainer"]["finding_ids"] == []
    report = (workspace / "review-verdict-ledger.md").read_text()
    section = report.split("## Reviewer Paraphrases", 1)[1].split("## Findings Registry", 1)[0]
    monitor_block = section.split("### monitor", 1)[1].split("###", 1)[0]
    assert "- Change: Monitor says VALUE moves to 2." in monitor_block
    assert "- Existing system: Monitor says writer.py is a constant holder." in monitor_block
    assert f"- Findings: {', '.join(monitor_ids)}" in monitor_block
    assert "paraphrase_mismatch" in section


def test_paraphrase_mismatch_marks_findings_for_recheck_without_dismissal(branch_workspace):
    monitor = with_paraphrase({"verdict": "needs_revision", "issues": [
        {"severity": "MEDIUM", "category": "correctness", "description": "Retry loses the value",
         "was_present_before_pr": False, "reach_evidence": "grep:retry:3"}]})
    first = runner.write_review_verdict_ledger(monitor_json=json.dumps(monitor))
    assert first["status"] == "success"
    ledger = json.loads((branch_workspace / "review-verdict-ledger.json").read_text())
    finding = ledger["findings_registry"][0]
    assert runner.record_review_objection(finding["id"], "paraphrase_mismatch", "")["status"] == "error"
    recorded = runner.record_review_objection(
        finding["id"], "paraphrase_mismatch", "Paraphrase says the change adds a cache; it removes one")
    assert recorded["status"] == "success", recorded
    assert recorded.get("effect", "rechecks") == "rechecks"
    second = runner.write_review_verdict_ledger(monitor_json=json.dumps(monitor))
    assert second["computed_verdict"] != "PROCEED"
    ledger = json.loads((branch_workspace / "review-verdict-ledger.json").read_text())
    row = ledger["findings_registry"][0]
    assert row["status"] == "active" and row["severity"] == finding["severity"]
    assert row["paraphrase_recheck"] is True
    assert row["transition_reason"] == "paraphrase_mismatch"
    assert ledger["escalation_required"] is True
    assert ledger["reviewer_paraphrases"]["monitor"]["recheck_ids"] == [row["id"]]
    report = (branch_workspace / "review-verdict-ledger.md").read_text()
    assert "re-check: reviewer misread the change" in report
    assert f"Marked for re-check (paraphrase_mismatch): {row['id']}" in report


def test_ledger_schema_accepts_paraphrase_fields(branch_workspace):
    import jsonschema

    from mapify_cli.schemas import REVIEW_VERDICT_LEDGER_SCHEMA

    monitor = with_paraphrase({"verdict": "needs_revision", "issues": [
        {"severity": "LOW", "category": "correctness", "description": "Minor naming drift",
         "was_present_before_pr": False}]})
    runner.write_review_verdict_ledger(monitor_json=json.dumps(monitor))
    ledger = json.loads((branch_workspace / "review-verdict-ledger.json").read_text())
    runner.record_review_objection(ledger["findings_registry"][0]["id"], "paraphrase_mismatch", "misread scope")
    runner.write_review_verdict_ledger(monitor_json=json.dumps(monitor))
    payload = json.loads((branch_workspace / "review-verdict-ledger.json").read_text())
    jsonschema.validate(payload, REVIEW_VERDICT_LEDGER_SCHEMA)


def test_sharded_merge_keeps_every_shard_paraphrase():
    shard_a = with_paraphrase({"all_clear": True, "findings": [], "receipt": envelope("maintainer")["receipt"]})
    shard_b = {**shard_a, "paraphrase": {"change": "Shard b sees the reader.", "existing_system": "Reader polls."}}
    merged = runner._review_merge_envelopes([("s1", shard_a), ("s2", shard_b)], {"s1": set(), "s2": set()})
    assert runner._review_paraphrase_errors(merged["paraphrase"]) == []
    assert merged["paraphrases"] == {"s1": PARAPHRASE, "s2": shard_b["paraphrase"]}


@pytest.mark.parametrize("provider", ["claude", "codex"])
def test_map_plan_step_2b_paraphrases_spec_first(provider):
    root = Path(__file__).resolve().parents[1]
    tree = root / (".claude" if provider == "claude" else ".agents")
    skill = (tree / "skills" / "map-plan" / "SKILL.md").read_text(encoding="utf-8")
    reference = (tree / "skills" / "map-plan" / "plan-reference.md").read_text(encoding="utf-8")
    step = skill.split("Step 2b: Devil's Advocate Review", 1)[1].split("Step 3: Create Branch Directory", 1)[0]
    assert "paraphrase" in step.lower()
    assert "cannot paraphrase" in step and "CRITICAL" in step
    assert "## Spec Paraphrase First (Step 2b)" in reference
    assert "What this proposes" in reference and "How the existing system works" in reference
