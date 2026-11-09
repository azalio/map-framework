"""Completeness blocks only on denied access that intersects the reviewer's required scope (#655)."""

import hashlib
import json
from typing import Any, cast

import pytest

from tests import test_review_verdict_ledger as ledger_tests
from tests.review_paraphrase_helpers import with_paraphrase

runner = ledger_tests.map_step_runner
branch_workspace = ledger_tests.branch_workspace
review_git_workspace = ledger_tests.review_git_workspace


def run_with_denied(workspace, denied) -> tuple[dict[str, Any], list[str]]:
    """Admit one Monitor round, capture a fully covered receipt carrying ``denied`` and seal the ledger."""
    admission = ledger_tests._admit_receipt_review(runner)
    assert admission["status"] == "success", admission
    value: list[str] = cast("list[str]", denied(admission) if callable(denied) else denied)
    envelope = {**with_paraphrase(ledger_tests._monitor_no_issues()), "receipt": {
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


@pytest.mark.parametrize("adversarial", [False, True])
@pytest.mark.parametrize("denied,blocks", [
    ("b/main.py", False), ("repo:b/main.py", False), ("b/", False), ("b/**", False),
    ("b/main.py (permission denied)", False), ("a/main.py", True), ("a/**", True),
    ("source_000001", True), ("diff", True), ("check:suite", True),
])
def test_shard_capture_denial_classification_preserves_provenance(tmp_path, adversarial, denied, blocks):
    reviewer = "adversarial" if adversarial else "monitor"
    row = {"required_files": ["a/main.py", "b/main.py"], "binding": {"required_checks": ["suite"]},
           "shards": [{"id": "s01", "files": ["a/main.py"]}, {"id": "s02", "files": ["b/main.py"]}],
           "shard_receipts": {f"default:{reviewer}": {}}}
    for index, shard in enumerate(row["shards"]):
        output = {"receipt": {"covered_files": shard["files"], "skipped_files": [],
                              "denied_access": [denied] if index == 0 else [], "check_evidence": []}}
        envelope = {"reviewer_status": {"monitor": {"raw": output}}} if adversarial else output
        content = json.dumps(envelope).encode()
        path = tmp_path / f"{shard['id']}.json"
        path.write_bytes(content)
        row["shard_receipts"][f"default:{reviewer}"][shard["id"]] = {
            "artifact": path.name, "sha256": hashlib.sha256(content).hexdigest()}
    required, informational = runner._review_capture_denied_split(row, tmp_path, "default", reviewer, "monitor", [denied])
    assert bool(required) is blocks
    assert bool(informational) is not blocks
    assert (required or informational) == [f"s01: {denied}"]
    # Tampering may not turn a required denial into informational evidence.
    (tmp_path / "s01.json").write_text("{}")
    required, _ = runner._review_capture_denied_split(row, tmp_path, "default", reviewer, "monitor", [denied])
    assert required == [denied]


ROW = {"required_files": ["src/app/main.py", "src/app/auth.py", "go.sum"], "binding": {"required_checks": ["suite"]}}


@pytest.mark.parametrize("denied", [
    "src/app/", "src/app", "./src/app/", "src/**", "src/app/*.py", "SRC/APP/MAIN.PY", "src\\app\\main.py",
    "source_000001 (permission denied)", "resource diff", "*required", "check:suite", "GO.SUM",
    "./src//app/auth.py", "src/./app/auth.py", "diff", "diff (permission denied)", "resource_id: manifest",
    "repo:src//app/auth.py", "./",
])
def test_vc5_required_scope_forms_block(denied):
    required, informational = runner._review_denied_split(ROW, [denied])
    assert required == [denied] and informational == []


@pytest.mark.parametrize("denied", ["docs/other.md", ".claude/agents/monitor.md", "role rubric (optional)",
                                    "src/other/", "tests/**",
                                    "repo:docs/manifest.md", "repo:docs/diff-guide.md",
                                    "repo:.claude/agents/prompt-rules.md", "repo:docs/artifacts.md",
                                    "artifact:inventory-notes", "the diff was too large", "check:other-suite"])
def test_vc6_outside_required_scope_stays_informational(denied):
    required, informational = runner._review_denied_split(ROW, [denied])
    assert required == [] and informational == [denied]
