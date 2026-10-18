"""Sensitive review cannot trade security or human consent for fast execution."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_review_trusted_policy import git, runner
from tests.test_review_trusted_policy import policy_repo as _policy_repo

policy_repo = _policy_repo


@pytest.fixture
def strict_repo(policy_repo):
    del policy_repo
    git("checkout", "main")
    Path(".map").mkdir(exist_ok=True)
    Path(".map/config.yaml").write_text("review:\n  security_gates: strict\n")
    git("add", "-f", ".map/config.yaml")
    git("commit", "-m", "operator enables strict gates")
    git("checkout", "feature")


@pytest.fixture
def sensitive_repo(strict_repo):
    del strict_repo
    Path("old/code.py").write_text("import subprocess\nsubprocess.run(command, shell=True)\n")
    git("commit", "-am", "sensitive change")


@pytest.mark.parametrize("arguments,mode,roster", [
    ("--auto --quick", "lightweight", None),
    ("--auto", "full", ["monitor"]),
    ("--adversarial --quick", "lightweight", None),
])
def test_sensitive_forces_full_security_roster(sensitive_repo, arguments, mode, roster):
    del sensitive_repo
    result = runner.begin_review_run(branch="feature", arguments=arguments, mode=mode,
                                     scheduled_reviewers=roster)
    assert result["status"] == "success", result
    assert "security" in result["scheduled_reviewers"]
    expected = runner.ADVERSARIAL_REVIEWERS if "--adversarial" in arguments else runner.NORMAL_REVIEWERS
    assert set(result["scheduled_reviewers"]) == set(expected) | {"security"}


def test_unknown_forces_full_security_roster(strict_repo):
    del strict_repo
    Path("opaque.bin").write_bytes(b"\x00\xff")
    result = runner.begin_review_run(branch="feature", mode="lightweight")
    assert result["target"]["shadow_risk"]["tier"] == "unknown"
    assert set(result["scheduled_reviewers"]) == set(runner.NORMAL_REVIEWERS) | {"security"}
    assert "security" in result["scheduled_reviewers"]


def test_consent_is_durable_bound_and_never_agent_decidable(sensitive_repo):
    del sensitive_repo
    admitted = runner.begin_review_run(branch="feature")
    store_path = Path(".map/feature/approval_holds.json")
    store = json.loads(store_path.read_text())
    hold = next(iter(store["holds"].values()))
    assert hold["kind"] == "review_consent"
    assert hold["review_binding"] == {"target": admitted["target"], "policy_hash": admitted["policy_hash"],
                                      "action": "review-ready"}
    before = store_path.read_bytes()
    for decision in ("approved", "cancelled", "expired", "denied"):
        assert runner.decide_approval_hold(hold["id"], decision, branch="feature")["status"] == "error"
    runner.auto_decide_holds(branch="feature")
    assert store_path.read_bytes() == before
    assert runner.begin_review_run(branch="feature")["resumed"]
    assert store_path.read_bytes() == before


def test_sensitive_ready_gate_cannot_disable_consent(sensitive_repo, monkeypatch):
    del sensitive_repo
    monkeypatch.setenv("MAP_REVIEW_LEDGER_ENFORCE", "0")
    result = runner.write_stage_gate("review", "ready", branch="feature")
    assert result["status"] == "error"
    assert not Path(".map/feature/review-gate.json").exists()


def test_corrupt_holds_cannot_be_replaced_by_admission(sensitive_repo):
    del sensitive_repo
    path = Path(".map/feature/approval_holds.json")
    path.parent.mkdir(parents=True)
    path.write_text("{broken")
    assert runner.begin_review_run(branch="feature")["status"] == "error"
    assert path.read_text() == "{broken"


def test_security_evidence_cannot_be_normal_execution_checks(sensitive_repo):
    del sensitive_repo
    runner.begin_review_run(branch="feature")
    ledger = json.loads(Path(".map/feature/review-verdict-ledger.json").read_text())
    row = ledger["convergence"]["rounds"][-1]
    row["security_gate"] = {"status": "COMPLETE"}
    row["execution_checks"] = {"security": {"passed": True}}
    gate = runner._review_security_gate(row, Path(".map/feature"))
    assert gate["status"] == "INCOMPLETE"
    assert gate["reasons"]


def test_security_capture_passes_independently_but_consent_stays_pending(sensitive_repo):
    del sensitive_repo
    profile = Path(".claude/agents/review-reader.md")
    profile.parent.mkdir(parents=True)
    profile.write_text("---\nname: review-reader\ntools: Read, Glob, Grep\n---\nRead only.\n")
    admitted = runner.begin_review_run(branch="feature", provider="claude")
    payload = {"reviewer": "security", "all_clear": True, "findings": [],
               "receipt": {"covered_files": admitted["required_files"], "skipped_files": [],
                           "denied_access": [], "check_evidence": []}}
    capture = runner.capture_review_output("security", json.dumps(payload), admitted["round_id"], branch="feature")
    assert capture["status"] == "success", capture
    directory = Path(".map/feature")
    row = json.loads((directory / "review-verdict-ledger.json").read_text())["convergence"]["rounds"][-1]
    assert runner._review_security_gate(row, directory)["status"] == "COMPLETE"
    holds = runner.list_approval_holds(branch="feature")["holds"]
    assert holds[0]["state"] == "pending"
    assert runner.write_stage_gate("review", "ready", branch="feature")["status"] == "error"
    Path("old/code.py").write_text("changed snapshot\n")
    assert runner._review_security_gate(row, directory)["status"] == "INCOMPLETE"
    assert runner.capture_review_output("security", json.dumps(payload), admitted["round_id"],
                                        branch="feature")["status"] == "error"


def test_hold_restart_and_changed_snapshot_preserve_pending_history(sensitive_repo):
    del sensitive_repo
    admitted = runner.begin_review_run(branch="feature")
    path = Path(".map/feature/approval_holds.json")
    before = path.read_bytes()
    script = ("import sys,json; sys.path.insert(0,sys.argv[1]); import map_step_runner as r; "
              "print(json.dumps(r.begin_review_run(branch='feature')))")
    scripts = str(Path(runner.__file__).parent)
    child = subprocess.run([sys.executable, "-I", "-c", script, scripts],
                           check=True, capture_output=True, text=True)
    assert json.loads(child.stdout)["resumed"]
    assert path.read_bytes() == before
    Path("old/code.py").write_text("import subprocess\nsubprocess.run(other, shell=True)\n")
    assert runner.begin_review_run(branch="feature")["status"] == "error"
    holds = json.loads(path.read_text())["holds"]
    assert len(holds) == 2
    assert holds["hold-001"]["review_binding"]["target"] == admitted["target"]
    assert holds["hold-001"]["review_binding"] != holds["hold-002"]["review_binding"]
    assert all(hold["state"] == "pending" for hold in holds.values())


def test_complete_review_waits_without_spending_rounds(sensitive_repo):
    del sensitive_repo
    profile = Path(".claude/agents/review-reader.md")
    profile.parent.mkdir(parents=True)
    profile.write_text("---\nname: review-reader\ntools: Read, Glob, Grep\n---\nRead only.\n")
    admitted = runner.begin_review_run(branch="feature", provider="claude")
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    receipt = {"covered_files": admitted["required_files"], "skipped_files": [],
               "denied_access": [], "check_evidence": []}
    outputs = {"monitor": {"verdict": "approved", "issues": []},
               "predictor": {"risk_assessment": "low", "predicted_state": {"breaking_changes": []}},
               "evaluator": {"overall_score": 10, "recommendation": "proceed"}}
    for role in admitted["scheduled_reviewers"]:
        output = {**outputs.get(role, {"all_clear": True, "findings": []}), "receipt": receipt}
        assert runner.capture_review_output(role, json.dumps(output), admitted["round_id"],
                                            branch="feature")["status"] == "success"
    final = runner.write_review_verdict_ledger(current_run=True, branch="feature")
    assert final["code_approval"]["approved"], final
    assert final["convergence"]["outcome"] == "awaiting_human"
    ledger_path = Path(".map/feature/review-verdict-ledger.json")
    before = ledger_path.read_bytes()
    for _ in range(4):
        resumed = runner.begin_review_run(branch="feature", provider="claude")
        assert resumed["stop_reason"] == "human_consent_pending"
        assert resumed["round_id"] == admitted["round_id"]
    assert ledger_path.read_bytes() == before


def test_untracked_profile_never_lowers_strict_review(strict_repo):
    del strict_repo
    profile = Path(".claude/agents/review-reader.md")
    profile.parent.mkdir(parents=True)
    profile.write_text("---\nname: review-reader\ntools: Read, Glob, Grep\n---\n")
    result = runner.begin_review_run(branch="feature", scheduled_reviewers=["monitor"])
    assert result["target"]["shadow_risk"]["tier"] == "sensitive"
    assert set(result["scheduled_reviewers"]) == set(runner.NORMAL_REVIEWERS) | {"security"}


@pytest.mark.parametrize("head_mode", ["shadow", "strict"])
def test_default_shadow_cannot_be_changed_by_pr_config(policy_repo, head_mode):
    del policy_repo
    Path(".map").mkdir(exist_ok=True)
    Path(".map/config.yaml").write_text(f"review:\n  security_gates: {head_mode}\n")
    Path("old/code.py").write_text("import subprocess\nsubprocess.run(command, shell=True)\n")
    result = runner.begin_review_run(branch="feature", mode="lightweight", arguments="--auto --quick")
    assert result["status"] == "success", result
    assert result["scheduled_reviewers"] == ["monitor"]
    assert result["target"]["security_gate_policy"]["mode"] == "shadow"
    holds = runner.list_approval_holds(branch="feature")["holds"]
    assert len(holds) == 1 and holds[0]["state"] == "pending"
    assert holds[0]["enforcement"] == "shadow"
    assert not runner.get_pending_holds(branch="feature")["resume_blocked"]
    runner.auto_decide_holds(branch="feature")
    assert runner.list_approval_holds(branch="feature")["holds"] == holds


@pytest.mark.parametrize("defect", ["corrupt", "write_failure", "terminal"])
def test_shadow_consent_errors_are_nonblocking_diagnostics(policy_repo, monkeypatch, defect):
    del policy_repo
    Path("old/code.py").write_text("import subprocess\nsubprocess.run(command, shell=True)\n")
    path = Path(".map/feature/approval_holds.json")
    path.parent.mkdir(parents=True)
    if defect == "corrupt":
        path.write_text("{broken")
    elif defect == "terminal":
        assert runner.begin_review_run(branch="feature")["status"] == "success"
        store = json.loads(path.read_text())
        next(iter(store["holds"].values()))["state"] = "approved"
        path.write_text(json.dumps(store))
    else:
        original = runner._write_json_file

        def fail_hold_write(destination, data):
            if destination.name == "approval_holds.json":
                raise OSError("hold store unavailable")
            return original(destination, data)

        monkeypatch.setattr(runner, "_write_json_file", fail_hold_write)
    before = path.read_bytes() if path.exists() else None
    result = runner.begin_review_run(branch="feature")
    assert result["status"] == "success", result
    assert result["human_consent"]["status"] == "error"
    ledger = json.loads(Path(".map/feature/review-verdict-ledger.json").read_text())
    assert ledger["human_consent"] == result["human_consent"]
    assert (path.read_bytes() if path.exists() else None) == before
    monkeypatch.setenv("MAP_REVIEW_LEDGER_ENFORCE", "0")
    assert runner.write_stage_gate("review", "ready", branch="feature")["status"] == "success"
    if defect == "corrupt":
        assert runner.get_pending_holds(branch="feature")["resume_blocked"] is True


def test_shadow_resume_reports_unwritable_diagnostic_ledger(policy_repo, monkeypatch):
    del policy_repo
    Path("old/code.py").write_text("import subprocess\nsubprocess.run(command, shell=True)\n")
    assert runner.begin_review_run(branch="feature")["status"] == "success"
    Path(".map/feature/approval_holds.json").write_text("{broken")
    original = runner._write_json_file

    def fail_ledger_write(destination, data):
        if destination.name == "review-verdict-ledger.json":
            raise OSError("diagnostic ledger unavailable")
        return original(destination, data)

    monkeypatch.setattr(runner, "_write_json_file", fail_ledger_write)
    result = runner.begin_review_run(branch="feature")
    assert result["status"] == "success", result
    assert result["human_consent"]["status"] == "error"
    assert result["human_consent"]["persistence_error"] == "diagnostic ledger unavailable"


@pytest.mark.parametrize("policy_path", ["REVIEW.md", "old/REVIEW.md"])
@pytest.mark.parametrize("defect", ["symlink", "nontext"])
@pytest.mark.parametrize("mode", ["strict", "shadow"])
def test_invalid_policy_content_cannot_downgrade_trusted_gate_config(
    policy_repo, monkeypatch, policy_path, defect, mode,
):
    del policy_repo
    git("checkout", "main")
    Path(".map").mkdir(exist_ok=True)
    Path(".map/config.yaml").write_text(f"review:\n  security_gates: {mode}\n")
    path = Path(policy_path)
    path.unlink()
    if defect == "symlink":
        path.symlink_to("missing-policy")
    else:
        path.write_bytes(b"\xff\xfe")
    git("add", "-f", ".map/config.yaml", policy_path)
    git("commit", "-m", "invalid policy content with explicit gate config")
    git("checkout", "feature")
    Path("old/code.py").write_text("value = 2\n")
    # First ready attempt: there is no earlier round to preserve strict mode.
    monkeypatch.setenv("MAP_REVIEW_LEDGER_ENFORCE", "0")
    gate = runner.write_stage_gate("review", "ready", branch="feature")
    assert gate["status"] == ("error" if mode == "strict" else "success"), gate
    admitted = runner.begin_review_run(branch="feature", mode="lightweight")
    assert admitted["status"] == "success", admitted
    assert admitted["target"]["trusted_policy"]["status"] == "unverified"
    assert admitted["target"]["security_gate_policy"]["mode"] == mode
    # Existing policy protection remains active without the legacy override.
    monkeypatch.delenv("MAP_REVIEW_LEDGER_ENFORCE")
    assert runner.write_stage_gate("review", "ready", branch="feature")["status"] == "error"


@pytest.mark.parametrize("config", ["review: [", "review: {security_gates: other}"])
def test_invalid_trusted_gate_config_fails_closed_before_first_round(policy_repo, monkeypatch, config):
    del policy_repo
    git("checkout", "main")
    Path(".map").mkdir(exist_ok=True)
    Path(".map/config.yaml").write_text(config)
    git("add", "-f", ".map/config.yaml")
    git("commit", "-m", "invalid trusted gate configuration")
    git("checkout", "feature")
    Path("old/code.py").write_text("value = 2\n")
    monkeypatch.setenv("MAP_REVIEW_LEDGER_ENFORCE", "0")
    assert runner.write_stage_gate("review", "ready", branch="feature")["status"] == "error"


@pytest.mark.parametrize("mode", ["strict", "shadow"])
def test_snapshot_failure_preserves_trusted_gate_mode_before_first_round(
    policy_repo, monkeypatch, mode,
):
    del policy_repo
    git("checkout", "main")
    Path(".map").mkdir(exist_ok=True)
    Path(".map/config.yaml").write_text(f"review:\n  security_gates: {mode}\n")
    git("add", "-f", ".map/config.yaml")
    git("commit", "-m", "trusted gate mode")
    git("checkout", "feature")
    Path("old/code.py").write_text("value = 2\n")
    assert not Path(".map/feature/review-verdict-ledger.json").exists()
    file_entry = runner._review_file_entry
    failed_paths = []

    def fail_tracked_snapshot(name):
        if name == "old/code.py":
            failed_paths.append(name)
            raise OSError("snapshot unavailable")
        return file_entry(name)

    monkeypatch.setattr(runner, "_review_file_entry", fail_tracked_snapshot)
    monkeypatch.setenv("MAP_REVIEW_LEDGER_ENFORCE", "0")
    gate = runner.write_stage_gate("review", "ready", branch="feature")

    assert failed_paths, "the tracked-file snapshot failure must be exercised"
    assert gate["status"] == ("error" if mode == "strict" else "success"), gate
    assert Path(".map/feature/review-gate.json").exists() is (mode == "shadow")
    if mode == "strict":
        target = runner._review_target()
        assert target["security_gate_policy"]["mode"] == "strict"


@pytest.mark.parametrize("mode", ["strict", "shadow"])
def test_corrupt_prior_ledger_respects_trusted_mode_with_legacy_override(
    policy_repo, monkeypatch, mode,
):
    del policy_repo
    git("checkout", "main")
    Path(".map").mkdir(exist_ok=True)
    Path(".map/config.yaml").write_text(f"review:\n  security_gates: {mode}\n")
    git("add", "-f", ".map/config.yaml")
    git("commit", "-m", "trusted gate mode")
    git("checkout", "feature")
    Path("old/code.py").write_text("value = 2\n")
    ledger = Path(".map/feature/review-verdict-ledger.json")
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text("{broken", encoding="utf-8")
    monkeypatch.setenv("MAP_REVIEW_LEDGER_ENFORCE", "0")

    gate = runner.write_stage_gate("review", "ready", branch="feature")

    assert gate["status"] == ("error" if mode == "strict" else "success"), gate
    assert Path(".map/feature/review-gate.json").exists() is (mode == "shadow")
    assert ledger.read_text(encoding="utf-8") == "{broken"


def test_shadow_legacy_override_still_blocks_retained_strict_round(strict_repo, monkeypatch):
    del strict_repo
    Path("old/code.py").write_text("import subprocess\nsubprocess.run(command, shell=True)\n")
    admission = runner.begin_review_run(branch="feature")
    assert admission["status"] == "success", admission
    assert admission["target"]["security_gate_policy"]["mode"] == "strict"
    git("checkout", "main")
    Path(".map/config.yaml").write_text("review:\n  security_gates: shadow\n")
    git("add", "-f", ".map/config.yaml")
    git("commit", "-m", "operator switches current policy to shadow")
    git("checkout", "feature")
    assert runner._review_target()["security_gate_policy"]["mode"] == "shadow"
    monkeypatch.setenv("MAP_REVIEW_LEDGER_ENFORCE", "0")

    gate = runner.write_stage_gate("review", "ready", branch="feature")

    assert gate["status"] == "error", gate
    assert not Path(".map/feature/review-gate.json").exists()


@pytest.mark.parametrize("failure", ["head", "merge_base"])
def test_early_snapshot_failure_retains_resolved_strict_authority(strict_repo, monkeypatch, failure):
    del strict_repo
    original_git = runner._review_git

    def fail_snapshot_git(*args):
        if ((failure == "head" and args == ("rev-parse", "HEAD"))
                or (failure == "merge_base" and args[0] == "merge-base")):
            raise OSError("snapshot ancestry unavailable")
        return original_git(*args)

    monkeypatch.setattr(runner, "_review_git", fail_snapshot_git)
    monkeypatch.setenv("MAP_REVIEW_LEDGER_ENFORCE", "0")
    target = runner._review_target()
    assert target["security_gate_policy"]["mode"] == "strict"
    gate = runner.write_stage_gate("review", "ready", branch="feature")
    assert gate["status"] == "error", gate
    assert not Path(".map/feature/review-gate.json").exists()


def test_corrupt_sequence_cannot_overwrite_consent_via_generic_hold(sensitive_repo):
    del sensitive_repo
    runner.begin_review_run(branch="feature")
    path = Path(".map/feature/approval_holds.json")
    store = json.loads(path.read_text())
    store["next_id"] = 1
    path.write_text(json.dumps(store))
    before = path.read_bytes()
    result = runner.create_approval_hold("dangerous_action", "reason", "another action", branch="feature")
    assert result["status"] == "error"
    assert path.read_bytes() == before


@pytest.mark.parametrize("state", ["approved", "cancelled", "expired", "denied"])
def test_forged_terminal_consent_is_rejected(sensitive_repo, state):
    del sensitive_repo
    runner.begin_review_run(branch="feature")
    path = Path(".map/feature/approval_holds.json")
    store = json.loads(path.read_text())
    hold = next(iter(store["holds"].values()))
    hold.update(state=state, approved_by="human", tool_name="AskUserQuestion")
    path.write_text(json.dumps(store))
    before = path.read_bytes()
    assert runner.begin_review_run(branch="feature")["status"] == "error"
    assert runner.write_stage_gate("review", "ready", branch="feature")["status"] == "error"
    assert path.read_bytes() == before
