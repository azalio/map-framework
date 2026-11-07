"""Completeness blocks only on denied access that intersects the reviewer's required scope (#655)."""

import json
from typing import Any, cast

import pytest

from tests import test_review_verdict_ledger as ledger_tests

runner = ledger_tests.map_step_runner
branch_workspace = ledger_tests.branch_workspace
review_git_workspace = ledger_tests.review_git_workspace


def run_with_denied(workspace, denied) -> tuple[dict[str, Any], list[str]]:
    """Admit one Monitor round, capture a fully covered receipt carrying ``denied`` and seal the ledger."""
    admission = ledger_tests._admit_receipt_review(runner)
    assert admission["status"] == "success", admission
    value: list[str] = cast("list[str]", denied(admission) if callable(denied) else denied)
    envelope = {**ledger_tests._monitor_no_issues(), "receipt": {
        "covered_files": admission["required_files"], "skipped_files": [],
        "denied_access": value, "check_evidence": []}}
    assert runner.capture_review_output("monitor", json.dumps(envelope), "receipt")["status"] == "success"
    assert runner.write_review_verdict_ledger(current_run=True)["status"] == "success"
    return json.loads((workspace / "review-verdict-ledger.json").read_text())["completeness"], value


@pytest.mark.parametrize("denied", [
    [".claude/agents/monitor.md"],
    ["role rubric (optional)"],
    ["repo:docs/unrelated.md"],
])
def test_vc1_denied_outside_required_scope_is_informational(review_git_workspace, denied):
    completeness, value = run_with_denied(review_git_workspace, denied)
    assert completeness["status"] == "COMPLETE", completeness
    assert not completeness["reasons"]
    assert completeness["informational_denied_access"] == [f"default:monitor: {item}" for item in value]


@pytest.mark.parametrize("shape", ["{file}", "./{file}", "repo:{file}", "current:{file}", "{file} (permission denied)"])
def test_vc2_denied_required_file_still_blocks(review_git_workspace, shape):
    completeness, _ = run_with_denied(review_git_workspace,
                                      lambda admission: [shape.format(file=admission["required_files"][0])])
    assert completeness["status"] == "BLOCKED", completeness
    assert any("required access denied" in reason for reason in completeness["reasons"])


@pytest.mark.parametrize("resource", ["manifest", "prompt", "diff", "inventory", "source_000000", "source_pack"])
def test_vc3_denied_required_resource_still_blocks(review_git_workspace, resource):
    completeness, _ = run_with_denied(review_git_workspace, [resource])
    assert completeness["status"] == "BLOCKED", completeness


def test_vc4_mixed_denials_block_and_name_only_the_required_one(review_git_workspace):
    completeness, _ = run_with_denied(
        review_git_workspace, lambda admission: ["optional-rubric.md", admission["required_files"][0]])
    assert completeness["status"] == "BLOCKED"
    assert completeness["informational_denied_access"] == ["default:monitor: optional-rubric.md"]
