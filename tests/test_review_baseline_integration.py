"""Real runner replay, durable attribution and fail-closed evidence checks."""

import json
import os
import subprocess
from pathlib import Path
from typing import Any, cast

import pytest

from tests.test_review_baseline_replay import native_ruff_command
from tests.test_review_verdict_ledger import (
    _admit_receipt_review,
    _monitor_no_issues,
    _review_cli,
    branch_workspace,
    map_step_runner,
    review_git_workspace,
)

IMPORTED_FIXTURES = (branch_workspace, review_git_workspace, native_ruff_command)


@pytest.fixture
def isolated_review(request, native_ruff_command):
    workspace = request.getfixturevalue("review_git_workspace")
    root = Path.cwd()
    (root / "src").mkdir()
    (root / "tests").mkdir()
    (root / "src/a.py").write_text("import os\n")
    (root / "tests/test_a.py").write_text("VALUE = 1\n")
    profile = root / ".claude/agents/review-reader.md"
    profile.parent.mkdir(parents=True)
    profile.write_text("---\nname: review-reader\ntools: Read, Glob, Grep\n---\nRead only.\n")
    subprocess.run(["git", "add", "."], check=True)
    subprocess.run(["git", "commit", "-qm", "frozen replay inputs"], check=True)
    subprocess.run(["git", "branch", "-f", "main", "HEAD"], check=True)
    # Leave the diagnostic source byte-identical; change a different Python file.
    (root / "writer.py").write_text("VALUE = 2\n")
    return workspace, native_ruff_command


@pytest.mark.parametrize("mutation", ["none", "head_output", "base_output", "source", "clean_policy", "ownership_error",
                                     "baseline_resource_tamper", "baseline_resource_rerun"])
def test_real_runner_baseline_only_is_durable_and_tamper_bound(isolated_review, mutation, monkeypatch):
    # Child Python launch normalizes terminal dimensions in this test harness.
    # Supply them before admission so a restart preserves the full environment.
    monkeypatch.setenv("COLUMNS", os.environ.get("COLUMNS", "80"))
    monkeypatch.setenv("LINES", os.environ.get("LINES", "24"))
    workspace, command = isolated_review
    runner = cast(Any, map_step_runner)
    admission = _admit_receipt_review(runner, required_checks=["lint"], check_specs={"lint": command})
    assert admission["status"] == "success", admission
    execute = runner._execute_owned_check
    if mutation == "ownership_error":
        def uncertain_baseline(argv, attempt_dir, lease_fd, timeout, cwd="."):
            if Path(attempt_dir).name == "baseline-execution":
                return {"status": "error", "passed": False, "exit_code": None}, b"supervisor lost"
            return execute(argv, attempt_dir, lease_fd, timeout, cwd=cwd)

        monkeypatch.setattr(runner, "_execute_owned_check", uncertain_baseline)
    result = runner.run_test_gate(command=command, check_id="lint")
    if mutation == "ownership_error":
        ledger = json.loads((workspace / "review-verdict-ledger.json").read_text())
        check = ledger["execution_checks"]["lint"]
        assert result["status"] == "cleanup_blocked", result
        assert result["observation_valid"] is False
        assert check["state"] == "running"
        interrupted_tree = workspace / check["baseline_intent"]["workspace"]
        assert interrupted_tree.is_dir()
        assert not ledger["code_approval"]["approved"]
        # A fresh lease owner recovers only the inode-bound interrupted tree.
        # The stub never launched any process; restoring the real executor makes
        # the second attempt an actual supervised replay, not a synthetic receipt.
        monkeypatch.setattr(runner, "_execute_owned_check", execute)
        recovered = runner.run_test_gate(command=command, check_id="lint")
        assert recovered["attempt_id"] != check["attempt_id"]
        assert recovered["baseline_attribution"]["status"] == "baseline_only", recovered
        assert not interrupted_tree.exists()
        after = json.loads((workspace / "review-verdict-ledger.json").read_text())
        history = after["execution_check_history"][-1]
        assert history["state"] == "interrupted"
        assert history["baseline_intent"]["state"] == "interrupted_cleaned"
        assert after["execution_checks"]["lint"]["state"] == "finished"
        return
    assert result["passed"] is False, result
    assert result["observation_valid"] is True, result
    assert result["baseline_attribution"]["status"] == "baseline_only", result
    ledger = json.loads((workspace / "review-verdict-ledger.json").read_text())
    check = ledger["execution_checks"]["lint"]
    row = ledger["convergence"]["rounds"][-1]
    if mutation.startswith("baseline_resource_"):
        resource = "check:lint:baseline"
        summary = runner._review_check_prompt_entry("lint", check, 1000)
        assert summary["baseline_resource"] == resource
        assert "check:lint" not in row.get("context_lazy", {})
        metadata, created = runner._review_lazy_check_resource(workspace, row, resource)
        assert created is True
        text = runner._review_context_read(workspace, metadata).decode()
        proof = json.loads((workspace / check["baseline_receipt"]["artifact"]).read_text())
        raw_baseline = (workspace / proof["output_artifact"]).read_text()
        assert "Baseline output:\n" + raw_baseline in text
        assert json.loads(text.split("\n\nBaseline output:", 1)[0]) == proof
        assert metadata["check_identity"]["attempt_id"] == check["attempt_id"]
        # Persist first-use baseline identity without ever fetching the head log.
        runner._write_json_file(workspace / "review-verdict-ledger.json", ledger)
        if mutation == "baseline_resource_tamper":
            (workspace / proof["output_artifact"]).write_bytes(b"tampered")
            with pytest.raises(ValueError, match="Baseline evidence"):
                runner._review_lazy_check_resource(workspace, row, resource)
        else:
            rerun = runner.run_test_gate(command=command, check_id="lint")
            assert rerun["attempt_id"] != check["attempt_id"]
            refreshed = json.loads((workspace / "review-verdict-ledger.json").read_text())
            fresh_row = refreshed["convergence"]["rounds"][-1]
            assert "check:lint" not in fresh_row.get("context_lazy", {})
            assert runner._review_check_observation_valid(workspace, "lint", fresh_row) is False
            with pytest.raises(ValueError):
                runner._review_lazy_check_resource(workspace, fresh_row, resource)
        return
    if mutation == "head_output":
        (workspace / check["output_artifact"]).write_bytes(b"tampered")
    elif mutation == "base_output":
        baseline = json.loads((workspace / check["baseline_receipt"]["artifact"]).read_text())
        (workspace / baseline["output_artifact"]).write_bytes(b"tampered")
    elif mutation == "source":
        Path("src/a.py").write_text("import sys\n")
    elif mutation == "clean_policy":
        # Isolate approval policy from replay eligibility: a trusted .map config
        # itself makes this initial narrow extractor ineligible for replay.
        def strict_policy(target):
            del target
            return {"require_clean_checks": True}
        monkeypatch.setattr(runner, "_review_trusted_config", strict_policy)
        assert runner._review_baseline_verified(workspace, "lint", row)
        assert not runner._review_check_approval(workspace, "lint", row)
        return
    envelope = {**_monitor_no_issues(), "receipt": {
        "covered_files": admission["required_files"], "skipped_files": [],
        "denied_access": [], "check_evidence": ["lint"],
    }}
    runner.capture_review_output("monitor", json.dumps(envelope), "receipt")
    # A fresh CLI process recomputes disposition from durable artifacts.
    assert runner._review_baseline_verified(workspace, "lint", row) is (mutation == "none")
    _review_cli("write_review_verdict_ledger", "--current-run")
    ledger = json.loads((workspace / "review-verdict-ledger.json").read_text())
    assert ledger["code_approval"]["approved"] is (mutation == "none"), ledger["completeness"]
    assert ledger["execution_checks"]["lint"]["passed"] is False
    if mutation == "none":
        # Cached completed approval must not survive immutable baseline proof loss.
        (workspace / check["baseline_receipt"]["artifact"]).write_bytes(b"tampered")
        _, gate = _review_cli("write_stage_gate", "review", "ready", "review.md", "clean")
        assert gate["status"] == "error", gate
