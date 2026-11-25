"""The coordinator closes a feature only on current repository and joint evidence."""

import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_feature_checks import feature as feature  # noqa: PLC0414 -- expose pytest fixture
from tests.test_map_orchestrator import map_orchestrator as workflow


@pytest.fixture
def pending_feature(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    branch = "feature"
    directory = Path(".map") / branch
    directory.mkdir(parents=True)
    subtask = {
        "id": "ST-001", "affected_files": ["api.py", "../client/client.py"],
        "repository_checks": {".": {"base": "a" * 40, "command": ["test-api"]},
                              "../client": {"base": "b" * 40, "command": ["test-client"]}},
        "joint_check": ["test-feature"],
    }
    (directory / "blueprint.json").write_text(json.dumps({"blueprint": {"subtasks": [subtask]}}))
    (directory / f"task_plan_{branch}.md").write_text("### ST-001: Update API and client\n")
    result = workflow.resume_from_plan(branch)
    assert result["status"] == "success", result
    evidence = {"status": "pending", "repositories": {".": {"status": "passed"},
                                                      "../client": {"status": "pending"}},
                "joint": {"status": "pending"}}
    monkeypatch.setitem(sys.modules, "map_feature_checks",
                        SimpleNamespace(feature_check=lambda branch, sid, *, project_dir: evidence.copy()))
    state = workflow.StepState.load(directory / "step_state.json")
    state.current_step_id = "2.4"
    state.current_step_phase = "MONITOR"
    state.pending_steps = ["2.4"]
    state.save(directory / "step_state.json")
    return branch, directory, evidence


def test_monitor_waits_for_both_repositories_and_joint_evidence(pending_feature):
    branch, directory, evidence = pending_feature
    state_path = directory / "step_state.json"
    assert workflow.get_next_step(branch)["feature_checks"]["ST-001"]["repositories"]["../client"]["status"] == "pending"
    for command in (
        lambda: workflow.validate_step("2.4", branch, recommendation="proceed"),
        lambda: workflow.validate_wave_step("ST-001", "2.4", branch),
        lambda: workflow.record_subtask_result("ST-001", branch, [], "valid"),
        lambda: workflow.mark_subtask_complete("ST-001", branch),
        lambda: workflow.advance_wave(branch),
    ):
        before = state_path.read_bytes()
        result = command()
        assert result["feature_checks"]["ST-001"]["status"] == "pending", result
        assert state_path.read_bytes() == before

    evidence["repositories"]["../client"]["status"] = "passed"
    evidence["joint"]["status"] = "failed"
    assert not workflow.validate_step("2.4", branch, recommendation="proceed")["valid"]
    evidence.update(status="complete", joint={"status": "passed"})
    assert workflow.mark_subtask_complete("ST-001", branch)["workflow_complete"]
    assert workflow.get_next_step(branch)["is_complete"]
    evidence.update(status="pending", joint={"status": "pending"})
    assert not workflow.peek_current_step(branch)["is_complete"]
    assert workflow.mark_workflow_complete(branch)["status"] == "error"
    assert workflow.archive_completed_workflow(branch)["status"] == "error"


@pytest.mark.parametrize("replacement", [None, {}, {"subtasks": [
    {"id": "ST-001", "repository_checks": {}, "joint_check": ["other-check"]},
]}])
def test_original_feature_contract_remains_required_on_resume(pending_feature, replacement):
    branch, directory, evidence = pending_feature
    evidence.update(status="complete", joint={"status": "passed"})
    assert workflow.mark_subtask_complete("ST-001", branch)["workflow_complete"]
    blueprint = directory / "blueprint.json"
    if replacement is None:
        blueprint.unlink()
    else:
        blueprint.write_text(json.dumps(replacement))
    state_file = directory / "step_state.json"
    before = state_file.read_bytes()
    assert workflow.set_plan_approved("true", branch)["status"] == "error"
    assert workflow.resume_from_plan(branch)["status"] == "error"
    assert state_file.read_bytes() == before
    result = workflow.get_next_step(branch)
    assert not result["is_complete"], result
    assert result["feature_checks"]["ST-001"]["status"] == "error"
    assert workflow.initialize_workflow("replacement", branch)["status"] == "error"
    assert workflow.StepState.load(directory / "step_state.json").approved_feature_contracts


def test_reapproval_replaces_feature_definition_after_review(pending_feature):
    branch, directory, _ = pending_feature
    blueprint = directory / "blueprint.json"
    plan = json.loads(blueprint.read_text())
    task = plan["blueprint"]["subtasks"][0]
    task["joint_check"] = ["check-new-contract"]
    blueprint.write_text(json.dumps(plan))
    assert workflow.set_plan_approved("false", branch)["status"] == "success"
    assert workflow.get_next_step(branch)["feature_checks"]["ST-001"]["status"] == "error"
    assert workflow.set_plan_approved("true", branch)["status"] == "success"
    assert workflow.get_next_step(branch)["feature_checks"]["ST-001"]["status"] == "pending"
    assert workflow.StepState.load(directory / "step_state.json").approved_feature_contracts == {
        "ST-001": workflow.feature_contract_digest(task, Path.cwd()),
    }


def test_feature_plan_uses_its_declared_checkouts_for_execution(pending_feature):
    branch, directory, _ = pending_feature
    state_file = directory / "step_state.json"
    state = workflow.StepState.load(state_file)
    state.execution_waves = [["ST-001", "ST-002"]]
    state.save(state_file)
    strategy = workflow.select_execution_strategy(branch)
    assert strategy["strategy"] == "sequential" and not strategy["concurrency_allowed"], strategy
    wave = workflow.get_wave_step(branch)
    assert wave["dispatch_mode"] == "sequential" and not wave["isolation_active"], wave


@pytest.mark.parametrize("verdict", ["invalid", "failed"])
def test_negative_monitor_result_keeps_the_feature_active(pending_feature, verdict):
    branch, directory, _ = pending_feature
    blueprint = directory / "blueprint.json"
    plan = json.loads(blueprint.read_text())
    plan["blueprint"]["subtasks"].append({"id": "ST-002", "dependencies": ["ST-001"]})
    blueprint.write_text(json.dumps(plan))
    state_path = directory / "step_state.json"
    state = workflow.StepState.load(state_path)
    state.subtask_sequence.append("ST-002")
    state.save(state_path)
    result = workflow.record_subtask_result("ST-001", branch, [], verdict)
    assert result["recorded"]["status"] == verdict
    assert workflow.get_next_step(branch)["current_subtask"] == "ST-001"
    assert "ST-001" not in workflow._completed_subtask_ids_for_deps(workflow.StepState.load(state_path))


def test_legacy_plan_with_two_checkouts_requires_checks_and_can_resume_after_review(feature, monkeypatch):
    server, _, task, _ = feature
    monkeypatch.chdir(server)
    branch = "feature"
    directory = server / ".map/feature"
    blueprint = directory / "blueprint.json"
    original_plan = blueprint.read_bytes()
    old_task = {"id": "ST-001", "affected_files": task["affected_files"]}
    blueprint.write_text(json.dumps({"subtasks": [old_task]}))
    (directory / "task_plan_feature.md").write_text("### ST-001: Update both checkouts\n")
    state = directory / "step_state.json"
    legacy_state = json.dumps({"plan_approved": True, "subtask_sequence": ["ST-001"]})
    state.write_text(legacy_state)
    for result in (workflow.resume_from_plan(branch), workflow.set_plan_approved("true", branch),
                   workflow.mark_subtask_complete("ST-001", branch)):
        assert result["status"] == "error", result
        assert "repository_checks" in str(result) and "joint_check" in str(result)
    assert state.read_text() == legacy_state
    blueprint.write_bytes(original_plan)
    assert workflow.set_plan_approved("true", branch)["status"] == "success"
    assert workflow.resume_from_plan(branch)["status"] == "success"
    status = workflow.get_next_step(branch)["feature_checks"]["ST-001"]
    assert set(status["repositories"]) == {".", "../client"} and status["status"] == "pending"


def test_coordinator_reads_its_own_receipts_when_the_environment_points_elsewhere(feature, tmp_path, monkeypatch):
    server, client, _, check = feature
    monkeypatch.chdir(server)
    branch = "feature"
    (server / ".map/feature/task_plan_feature.md").write_text("### ST-001: Update both checkouts\n")
    assert workflow.resume_from_plan(branch)["status"] == "success"
    for repo in (server, client):
        (repo / "payload.txt").write_text("matching")
    assert check(repository=".")["status"] == "pending"
    initial_step = workflow.get_next_step(branch)
    assert initial_step["feature_checks"]["ST-001"]["repositories"]["../client"]["status"] == "pending"
    assert check(repository="../client")["status"] == "pending"
    assert check(joint=True)["status"] == "complete"
    result = workflow.record_subtask_result("ST-001", branch, ["payload.txt", "../client/payload.txt"], "valid")
    assert result["cross_repo_files"] == ["../client/payload.txt"] and "files_not_in_diff" not in result
    assert workflow.mark_subtask_complete("ST-001", branch)["workflow_complete"]

    other_server = shutil.copytree(server, tmp_path / "other/server")
    other_client = shutil.copytree(client, tmp_path / "other/client")
    (other_client / "payload.txt").write_text("different")
    monkeypatch.chdir(other_server)
    assert workflow.set_plan_approved("false", branch)["status"] == "success"
    assert workflow.set_plan_approved("true", branch)["status"] == "success"
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(server))
    result = workflow.get_next_step(branch)
    assert not result["is_complete"], result
    assert result["feature_checks"]["ST-001"]["repositories"]["../client"]["status"] == "pending"
    assert check()["status"] == "complete"
