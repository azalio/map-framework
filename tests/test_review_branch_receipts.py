"""Explicit slash branches share one review ledger, bundle, lock, and receipt tree."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_PATH = Path(__file__).resolve().parents[1] / "src/mapify_cli/templates/map/scripts"
sys.path.insert(0, str(SCRIPTS_PATH))

import map_step_runner  # type: ignore[import-not-found]


@pytest.mark.parametrize("bundle_positional", [False, True])
def test_explicit_slash_branch_receipt_lifecycle(tmp_path, monkeypatch, bundle_positional):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-b", "main"], check=True, capture_output=True)
    for key, value in (("user.email", "test@example.com"), ("user.name", "Test")):
        subprocess.run(["git", "config", key, value], check=True)
    Path(".gitignore").write_text(".map/\n")
    Path("writer.py").write_text("VALUE = 1\n")
    profile = Path(".claude/agents/review-reader.md")
    profile.parent.mkdir(parents=True)
    profile.write_text("---\nname: review-reader\ntools: Read, Glob, Grep\n---\nRead only.\n")
    subprocess.run(["git", "add", "."], check=True)
    subprocess.run(["git", "commit", "-m", "base"], check=True, capture_output=True)
    # The explicit review branch must not silently fall back to the checkout name.
    subprocess.run(["git", "checkout", "-b", "checkout-branch"], check=True, capture_output=True)
    Path("writer.py").write_text("VALUE = 2\n")
    subprocess.run(["git", "add", "writer.py"], check=True)
    subprocess.run(["git", "commit", "-m", "change"], check=True, capture_output=True)
    branch = "feat/x"
    directory = tmp_path / ".map/feat-x"
    command = [sys.executable, "-c", "print('checked')"]
    admission = map_step_runner.begin_review_run(
        scheduled_reviewers=["monitor"], provider="claude", round_id="receipt",
        branch=branch, required_checks=["smoke"], check_specs={"smoke": command},
    )
    assert admission["status"] == "success", admission
    assert (directory / "review-verdict-ledger.json").exists()
    bundle = (map_step_runner.create_review_bundle(branch) if bundle_positional
              else map_step_runner.create_review_bundle(branch=branch))
    assert bundle["status"] == "success", bundle
    check = map_step_runner.run_test_gate(check_id="smoke", branch=branch)
    assert check["passed"] is True, check
    capture = map_step_runner.capture_review_output("monitor", json.dumps({
        "verdict": "approved", "issues": [],
        "receipt": {"covered_files": admission["required_files"], "skipped_files": [],
                    "denied_access": [], "check_evidence": ["smoke"]},
    }), "receipt", branch=branch)
    assert capture["status"] == "success", capture
    result = map_step_runner.write_review_verdict_ledger(current_run=True, branch=branch)
    assert result["code_approval"]["approved"] is True, result
    gate = map_step_runner.write_stage_gate("review", "ready", branch=branch)
    assert gate["status"] == "success", gate
    scope = map_step_runner.review_round_scope(branch=branch)
    assert scope == map_step_runner.review_round_scope(branch="feat-x"), scope
    assert map_step_runner.review_publication("test", branch=branch)["status"] == "success"
    assert (directory / ".review-ledger.lock").exists()
    assert (directory / ".review-execution.lock").exists()
    assert (directory / "review-agent-monitor.json").exists()
    assert (directory / "review-gate.json").exists()
    assert not (tmp_path / ".map/feat").exists()
    assert not (tmp_path / ".map/checkout-branch").exists()
