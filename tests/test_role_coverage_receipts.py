"""Role schemas, early response gates and admitted captures share receipt shape."""

import copy
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests import test_review_verdict_ledger as ledger_tests

SCRIPTS_PATH = ledger_tests.SCRIPTS_PATH
runner = ledger_tests.map_step_runner
branch_workspace = ledger_tests.branch_workspace
review_git_workspace = ledger_tests.review_git_workspace

KEYS = ("covered_files", "skipped_files", "denied_access", "check_evidence")
ROLES = tuple(runner.ROLE_REVIEWER_IDS)


def envelope(role, *, covered=()):
    return {"reviewer": role, "all_clear": True, "all_clear_rationale": "Checked supplied source",
            "findings": [], "checks_performed": ["read source"],
            "receipt": {"covered_files": list(covered), "skipped_files": [],
                        "denied_access": [], "check_evidence": []}}


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("defect", ["missing", "null", "array", *KEYS])
def test_role_gate_rejects_bad_receipt_even_for_all_clear(role, defect):
    payload = envelope(role)
    if defect == "missing":
        payload.pop("receipt")
    elif defect == "null":
        payload["receipt"] = None
    elif defect == "array":
        payload["receipt"] = []
    else:
        payload["receipt"][defect] = [42]
    result = runner.detect_truncated_agent_output(json.dumps(payload), agent_kind=role)
    assert result["truncated"] is True
    assert any("receipt" in reason for reason in result["reasons"])
    retry = runner.build_json_retry_prompt(role, result["reasons"])
    assert retry["status"] == "ok"
    assert '"receipt"' in retry["prompt"]
    for key in KEYS:
        assert f'"{key}"' in retry["prompt"]


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("key", KEYS)
@pytest.mark.parametrize("value", [None, "path", {}, [False], [{}]])
def test_every_receipt_field_must_be_a_string_array(role, key, value):
    payload = envelope(role)
    payload["receipt"][key] = value
    result = runner.detect_truncated_agent_output(json.dumps(payload), agent_kind=role)
    assert result["truncated"] is True
    assert f"receipt.{key} must be an array of strings" in result["reasons"]


@pytest.mark.parametrize("role", ROLES)
def test_receipt_requires_all_four_fields_and_allows_empty_lists(role):
    payload = envelope(role)
    assert runner.detect_truncated_agent_output(json.dumps(payload), agent_kind=role)["truncated"] is False
    for key in KEYS:
        missing = copy.deepcopy(payload)
        del missing["receipt"][key]
        assert runner.detect_truncated_agent_output(json.dumps(missing), agent_kind=role)["truncated"] is True


@pytest.mark.parametrize("builder", ["build_review_prompts", "build_adversarial_review_prompts", "build_role_review_prompts"])
def test_dispatch_and_retry_share_receipt_schema(review_git_workspace, builder):
    del review_git_workspace
    result = getattr(runner, builder)()
    assert result["status"] == "success", result
    for role in ("user_experience", "maintainer"):
        prompt = result["prompts"][role]["prompt"]
        schema = json.loads(re.search(r"<output_schema>\s*(.*?)\s*</output_schema>", prompt, re.DOTALL)[1])
        assert schema["receipt"] == runner.REVIEW_COVERAGE_RECEIPT_SCHEMA
        assert "even when all_clear=true" in prompt
        assert "current runner-issued check IDs" in prompt
        retry = runner.build_json_retry_prompt(role)["prompt"]
        retry_schema = json.loads(re.search(r"<output_schema>\s*(.*?)\s*</output_schema>", retry, re.DOTALL)[1])
        assert retry_schema == schema


@pytest.fixture
def admitted_role_review(review_git_workspace):
    workspace = review_git_workspace
    Path("writer.py").write_text("VALUE = 2\n")
    subprocess.run(["git", "commit", "-am", "change"], check=True, capture_output=True)
    profile = Path(".claude/agents/review-reader.md")
    profile.parent.mkdir(parents=True)
    profile.write_text("---\nname: review-reader\ntools: Read, Glob, Grep\n---\nRead only.\n")
    admission = runner.begin_review_run(
        scheduled_reviewers=[*runner.NORMAL_REVIEWERS, "security"],
        round_id="receipt", provider="claude",
    )
    assert admission["status"] == "success", admission
    assert runner.create_review_bundle()["status"] == "success"
    assert "writer.py" in admission["required_files"]
    return workspace, admission


@pytest.mark.parametrize("role", ROLES)
def test_invalid_capture_cannot_replace_valid_role_evidence(admitted_role_review, role):
    workspace, admission = admitted_role_review
    payload = envelope(role, covered=admission["required_files"])
    assert runner.capture_review_output(role, json.dumps(payload), "receipt")["status"] == "success"
    artifact = workspace / f"review-agent-{role}.json"
    ledger = workspace / "review-verdict-ledger.json"
    before = artifact.read_bytes(), ledger.read_bytes()
    del payload["receipt"]
    result = runner.capture_review_output(role, json.dumps(payload), "receipt")
    assert result["status"] == "error", result
    assert "coverage receipt" in result["message"]
    assert (artifact.read_bytes(), ledger.read_bytes()) == before


@pytest.mark.parametrize("gap", [None, "skipped_files", "denied_access"])
def test_role_receipts_reach_ledger_without_fabricating_coverage(admitted_role_review, gap):
    workspace, admission = admitted_role_review
    receipt = envelope("maintainer", covered=admission["required_files"])["receipt"]
    core = {"monitor": {"verdict": "approved", "issues": []},
            "predictor": {"risk_assessment": "low", "predicted_state": {"breaking_changes": []}},
            "evaluator": {"overall_score": 10, "recommendation": "proceed"}}
    for role, output in core.items():
        assert runner.capture_review_output(role, json.dumps({**output, "receipt": receipt}), "receipt")["status"] == "success"
    for role in ROLES:
        payload = envelope(role, covered=admission["required_files"])
        if role == "maintainer" and gap:
            payload["receipt"][gap] = ["writer.py"]
        assert runner.detect_truncated_agent_output(json.dumps(payload), agent_kind=role)["truncated"] is False
        assert runner.capture_review_output(role, json.dumps(payload), "receipt")["status"] == "success"
    result = runner.write_review_verdict_ledger(current_run=True)
    ledger = json.loads((workspace / "review-verdict-ledger.json").read_text())
    assert not any("missing or invalid reviewer coverage receipt" in x for x in ledger["completeness"]["reasons"])
    if gap:
        assert ledger["code_approval"]["approved"] is False
        assert ledger["completeness"]["status"] == ("BLOCKED" if gap == "denied_access" else "INCOMPLETE")
    else:
        assert ledger["completeness"]["status"] == "COMPLETE", result
        assert ledger["code_approval"]["approved"] is True


def test_real_cli_receipt_failure_and_one_retry(tmp_path):
    payload = envelope("maintainer")
    del payload["receipt"]
    command = [sys.executable, str(SCRIPTS_PATH / "map_step_runner.py"),
               "detect_truncated_agent_output", "--agent", "maintainer"]
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path)}
    invalid = subprocess.run(command, input=json.dumps(payload), cwd=tmp_path, env=env,
                             text=True, capture_output=True, check=False)
    assert json.loads(invalid.stdout)["truncated"] is True
    corrected = subprocess.run(command, input=json.dumps(envelope("maintainer")), cwd=tmp_path, env=env,
                               text=True, capture_output=True, check=False)
    assert corrected.returncode == 0
    assert json.loads(corrected.stdout)["truncated"] is False


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("defect", ["missing", "null", *KEYS])
def test_aggregation_rejects_malformed_role_receipts_and_accepts_retry(role, defect):
    payload = envelope(role)
    if defect == "missing":
        del payload["receipt"]
    elif defect == "null":
        payload["receipt"] = None
    else:
        payload["receipt"][defect] = [False]
    hunter = json.dumps({"all_clear": True, "findings": []})
    invalid = runner.aggregate_adversarial_findings(blind_json=hunter, role_json={role: json.dumps(payload)})
    assert invalid["reviewer_status"][role]["status"] == "parse_error"
    assert any(f"{role}: receipt" in error for error in invalid["parse_errors"])
    assert invalid["reviewer_status"]["blind"]["status"] == "ok"
    retry = runner.build_json_retry_prompt(role)["prompt"]
    assert '"receipt"' in retry
    corrected = runner.aggregate_adversarial_findings(role_json={role: json.dumps(envelope(role))})
    assert corrected["reviewer_status"][role]["status"] == "ok"


@pytest.mark.parametrize("ordering", ["", "default", "reverse"])
@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("defect", ["missing", "malformed", "parse_error", "invalid_entry"])
def test_adversarial_capture_preserves_evidence_on_bad_nested_receipt(review_git_workspace, ordering, role, defect):
    workspace = review_git_workspace
    flags = "--adversarial" + (" --compare-orderings" if ordering else "")
    admitted = runner.begin_review_run(arguments=flags, round_id="receipt")
    assert admitted["status"] == "success", admitted
    report = runner.aggregate_adversarial_findings(role_json={name: json.dumps(envelope(name)) for name in ROLES})
    assert runner.capture_review_output("adversarial", json.dumps(report), "receipt", ordering=ordering)["status"] == "success"
    directory = workspace / "review-collections" / ordering if ordering else workspace
    artifact = directory / "review-agent-adversarial.json"
    ledger = workspace / "review-verdict-ledger.json"
    before = artifact.read_bytes(), ledger.read_bytes()
    invalid = copy.deepcopy(report)
    entry = invalid["reviewer_status"][role]
    if defect == "missing":
        del entry["raw"]["receipt"]
    elif defect == "malformed":
        entry["raw"]["receipt"]["covered_files"] = [42]
    elif defect == "parse_error":
        invalid["reviewer_status"][role] = {"status": "parse_error", "error": "receipt is invalid"}
    else:
        invalid["reviewer_status"][role] = []
    result = runner.capture_review_output("adversarial", json.dumps(invalid), "receipt", ordering=ordering)
    assert result["status"] == "error", result
    assert f"{role} coverage receipt" in result["message"]
    assert (artifact.read_bytes(), ledger.read_bytes()) == before
    assert runner.capture_review_output("adversarial", json.dumps(report), "receipt", ordering=ordering)["status"] == "success"


def test_adversarial_capture_retains_missing_response_evidence(review_git_workspace):
    del review_git_workspace
    assert runner.begin_review_run(arguments="--adversarial", round_id="receipt")["status"] == "success"
    report = runner.aggregate_adversarial_findings(blind_json=json.dumps({"all_clear": True, "findings": []}))
    assert report["reviewer_status"]["maintainer"]["status"] == "not_run"
    assert runner.capture_review_output("adversarial", json.dumps(report), "receipt")["status"] == "success"
