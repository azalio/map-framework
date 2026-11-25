"""Completion uses current runner evidence, never a cached terminal flag."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src/mapify_cli/templates/map/scripts"


def orchestrator(command, *args):
    result = subprocess.run(
        [sys.executable, "-B", str(SCRIPTS / "map_orchestrator.py"), command, *args,
         "--branch", "main"], capture_output=True, text=True, check=False,
    )
    assert result.stdout, result.stderr
    return json.loads(result.stdout)


@pytest.fixture()
def completion_workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-b", "main"], check=True, capture_output=True)
    for key, value in (("user.email", "test@example.com"), ("user.name", "Test")):
        subprocess.run(["git", "config", key, value], check=True)
    Path(".gitignore").write_text(".map/\n")
    Path("product.txt").write_text("ready")
    subprocess.run(["git", "add", "."], check=True)
    subprocess.run(["git", "commit", "-m", "base"], check=True, capture_output=True)
    directory = tmp_path / ".map/main"
    directory.mkdir(parents=True)
    (directory / "step_state.json").write_text(json.dumps({
        "workflow_status": "IN_PROGRESS", "pending_steps": [],
        "current_subtask_id": "ST-001", "subtask_sequence": ["ST-001"],
        "current_step_id": "2.4", "current_step_phase": "MONITOR",
    }))
    return directory


def runner(api, **payload):
    arguments = ["--json", json.dumps({"branch": "main", **payload})]
    if api == "record_test_contract_handoff":
        arguments = [payload["subtask_id"], "", payload["test_files_csv"], "Proof contract", "",
                     "--authoring-result", payload["authoring_result"],
                     "--authoring-justification", payload["authoring_justification"]]
    result = subprocess.run(
        [sys.executable, "-B", str(SCRIPTS / "map_step_runner.py"), api, *arguments],
        capture_output=True, text=True, check=False,
    )
    assert result.stdout, result.stderr
    return json.loads(result.stdout)


def freeze_proof(directory):
    (directory / "spec_main.md").write_text(
        "<!-- mapify:requirements-index:v1 -->\n```yaml\nrequirements:\n"
        "  - id: AC-1\n    kind: acceptance_criterion\n"
        "```\n<!-- /mapify:requirements-index:v1 -->\n"
    )
    Path("proof.py").write_text("from pathlib import Path\nassert Path('product.txt').read_text() == 'ready'\n")
    state_path = directory / "step_state.json"
    state = json.loads(state_path.read_text())
    state.update(current_step_id="2.25", current_step_phase="TEST_WRITER")
    state_path.write_text(json.dumps(state))
    assert orchestrator("begin_acceptance_authoring", "ST-001")["status"] == "success"
    result = runner("freeze_acceptance_contract", ac_id="AC-1",
                    command=[sys.executable, "proof.py"], proof_files=["proof.py"],
                    subtask_id="ST-001", author="test-writer")
    assert result["status"] == "success", result
    (directory / "test_contract_ST-001.md").write_text("Product must be ready; proof.py checks it.\n")
    handoff = runner("record_test_contract_handoff", subtask_id="ST-001",
                     test_files_csv="proof.py", authoring_result="already_green",
                     authoring_justification="Existing implementation satisfies the independent proof")
    assert handoff["status"] == "success", handoff
    state = json.loads(state_path.read_text())
    state.update(current_step_id="2.4", current_step_phase="MONITOR")
    state_path.write_text(json.dumps(state))


def test_malformed_inventory_cannot_complete(completion_workspace):
    (completion_workspace / "spec_main.md").write_text(
        "<!-- mapify:requirements-index:v1 -->\n```yaml\nrequirements: [\n"
        "```\n<!-- /mapify:requirements-index:v1 -->\n"
    )
    result = orchestrator("mark_workflow_complete")
    assert result["status"] == "error", result
    state = json.loads((completion_workspace / "step_state.json").read_text())
    assert state["workflow_status"] != "WORKFLOW_COMPLETE"


def test_legacy_completion_warns_without_fabricating_proof(completion_workspace):
    del completion_workspace
    result = orchestrator("mark_workflow_complete")
    assert result["status"] == "success", result
    assert "acceptance" in result
    assert orchestrator("get_next_step")["is_complete"] is True


def test_frozen_proof_executes_before_completion_and_revalidates_after_restart(completion_workspace):
    freeze_proof(completion_workspace)
    exhausted = orchestrator("get_next_step")
    assert exhausted["step_id"] == "FINAL_VERIFICATION", exhausted
    assert exhausted["implementation_complete"] is True
    assert exhausted["is_complete"] is False
    assert runner("run_acceptance_proofs")["status"] == "success"
    assert orchestrator("mark_workflow_complete")["status"] == "success"
    assert orchestrator("peek_current_step")["is_complete"] is True
    Path("product.txt").write_text("changed")
    assert orchestrator("get_next_step")["is_complete"] is False
    assert orchestrator("peek_current_step")["is_complete"] is False
    assert orchestrator("archive")["status"] == "error"


@pytest.mark.parametrize("command,args", [
    ("mark_subtask_complete", ("ST-001", "--reason", "done", "--kind", "noop")),
    ("validate_step", ("2.4", "--recommendation", "proceed")),
    ("advance_wave", ()),
])
def test_terminal_paths_preserve_final_proof_phase(completion_workspace, command, args):
    freeze_proof(completion_workspace)
    state_path = completion_workspace / "step_state.json"
    state = json.loads(state_path.read_text())
    if command == "validate_step":
        state["pending_steps"] = ["2.4"]
    elif command == "advance_wave":
        state["execution_waves"] = [["ST-001"]]
    state_path.write_text(json.dumps(state))
    result = orchestrator(command, *args)
    assert result.get("status", "success") == "success", result
    assert result.get("valid", True), result
    state = json.loads(state_path.read_text())
    assert state["workflow_status"] == "FINAL_VERIFICATION", result
    assert state["completed_at"] is None


def test_actor_cannot_claim_independent_authoring(completion_workspace):
    state_path = completion_workspace / "step_state.json"
    state = json.loads(state_path.read_text())
    state.update(current_step_id="2.3", current_step_phase="ACTOR")
    state_path.write_text(json.dumps(state))
    result = orchestrator("begin_acceptance_authoring", "ST-001",
                          "--authoring-stage", "independent_test_first")
    assert result["status"] == "error", result
    assert "acceptance_authoring" not in json.loads(state_path.read_text())


def _cursor_hints(provider, directory):
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(directory.parent.parent)}
    env.pop("MAP_EFFICIENT_SEQUENTIAL_ONLY", None)
    env.pop("MAP_INVOKED_BY", None)
    hooks = ROOT / provider / "hooks"
    for name in ("workflow-context-injector", "post-compact-context"):
        result = subprocess.run([sys.executable, "-B", str(hooks / f"{name}.py")],
                                env=env, input=json.dumps({"tool_name": "Edit", "tool_input": {"file_path": "x"}}),
                                text=True, capture_output=True, check=True)
        yield json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]


@pytest.fixture()
def cursor_plan(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    subprocess.run(["git", "init", "-b", "main"], check=True, capture_output=True)
    directory = tmp_path / ".map/main"
    directory.mkdir(parents=True)
    subtasks = [{"id": "ST-001"}, {"id": "ST-002", "dependencies": ["ST-001"]},
                {"id": "ST-003", "dependencies": ["ST-002"]}, {"id": "ST-004"}]
    for task in subtasks:
        task["affected_files"] = [task["id"] + ".py"]
    monkeypatch.delenv("MAP_EFFICIENT_SEQUENTIAL_ONLY", raising=False)
    (directory.parent / "config.yaml").write_text("execution.concurrent_dispatch: false\n")
    (directory / "blueprint.json").write_text(json.dumps({"subtasks": subtasks}))
    (directory / "task_plan_main.md").write_text("Feature with four subtasks.")
    result = orchestrator("resume_from_plan")
    assert result.get("waves_computed") == "success", result
    return directory


@pytest.mark.parametrize(("provider", "forced"), [(".claude", True), (".codex", False)])
def test_serial_revision_shows_advanced_cursor_in_both_hooks(cursor_plan, monkeypatch, provider, forced):
    from tests.test_map_orchestrator import _write_valid_research_artifact

    if forced:
        monkeypatch.setenv("MAP_EFFICIENT_SEQUENTIAL_ONLY", "1")
    else:
        (cursor_plan.parent / "config.yaml").write_text("execution.wave_mode: off\n")
    assert orchestrator("select_execution_strategy")["strategy"] == "sequential"
    assert orchestrator("get_next_step")["current_subtask"] == "ST-001"
    assert orchestrator("mark_subtask_complete", "ST-001", "--reason", "already done")["status"] == "success"
    assert orchestrator("request_acceptance_revision", "ST-002", "--reason", "Updated requirement")["status"] == "success"
    edit, restored = _cursor_hints(provider, cursor_plan)
    for hint in (edit, restored):
        assert "ST-002" in hint and "TEST_WRITER" in hint, hint
    assert "Write tests" in restored
    for step in ("2.25", "2.26"):
        result = orchestrator("validate_step", step)
        assert result["valid"], result
    Path("ST-002.py").write_text("value = 2\n")
    result = orchestrator("validate_step", "2.4", "--recommendation", "proceed")
    assert result["valid"], result
    assert orchestrator("get_next_step")["current_subtask"] == "ST-003"
    for hint in _cursor_hints(provider, cursor_plan):
        assert "ST-003" in hint and "Persist" in hint and "RESEARCH" in hint, hint
    _write_valid_research_artifact(cursor_plan.parent.parent, "main", "ST-003")
    assert orchestrator("validate_step", "2.2")["next_step"] == "2.25"
    state = json.loads((cursor_plan / "step_state.json").read_bytes())
    assert state["subtask_phases"]["ST-002"] == "2.25"
    edit, restored = _cursor_hints(provider, cursor_plan)
    for hint in (edit, restored):
        assert "ST-003" in hint and "TEST_WRITER" in hint and "ST-002" not in hint, hint
    assert "Write tests" in restored


def test_wave_hooks_show_members_on_dispatch_and_after_advance(cursor_plan):
    assert orchestrator("select_execution_strategy")["strategy"] == "wave_loop"
    first = orchestrator("get_wave_step")
    assert {s["subtask_id"] for s in first["subtasks"]} == {"ST-001", "ST-004"}
    for hint in _cursor_hints(".codex", cursor_plan):
        assert "ST-001:2.3" in hint and "ST-004:2.3" in hint, hint
        assert "ST: -" not in hint
    assert orchestrator("validate_wave_step", "ST-001", "2.3")["valid"]
    for hint in _cursor_hints(".claude", cursor_plan):
        assert "ST-001:2.4" in hint and "ST-004:2.3" in hint, hint
    assert orchestrator("advance_wave")["current_wave_index"] == 1
    for hint in _cursor_hints(".codex", cursor_plan):
        assert "ST-002:2.3" in hint and "ST-004" not in hint, hint


def test_old_cursor_with_phases_from_another_wave(completion_workspace):
    path = completion_workspace / "step_state.json"
    state = json.loads(path.read_bytes())
    state.update(current_subtask_id="ST-003", current_step_id="2.25", current_step_phase="TEST_WRITER",
                 execution_waves=[["ST-002"], ["ST-003"]], current_wave_index=0, subtask_phases={"ST-002": "2.25"})
    path.write_text(json.dumps(state))
    for hint in _cursor_hints(".claude", completion_workspace):
        assert "ST-003" in hint and "ST-002" not in hint, hint


def test_revision_reenters_writer_before_opening_independent_checkpoint(completion_workspace):
    freeze_proof(completion_workspace)
    state_path = completion_workspace / "step_state.json"
    before = json.loads(state_path.read_text())
    before.update(subtask_results={"ST-001": {"status": "completed"}},
                  contract_ready_subtasks={"ST-001": {"ready_at": "old"}},
                  subtask_phases={"ST-001": "COMPLETE"})
    state_path.write_text(json.dumps(before))
    result = orchestrator("request_acceptance_revision", "ST-001", "--reason", "Requirement clarified")
    assert result["status"] == "success", result
    state_path = completion_workspace / "step_state.json"
    state = json.loads(state_path.read_text())
    assert state["current_step_phase"] == "TEST_WRITER"
    assert "ST-001" not in state["subtask_results"]
    assert "ST-001" not in state["contract_ready_subtasks"]
    assert state["subtask_phases"]["ST-001"] == "2.25"
    assert state["acceptance_authoring"]["ST-001"]["status"] == "revision_requested"
    terminal = orchestrator("mark_subtask_complete", "ST-001", "--reason", "already done")
    assert terminal.get("workflow_complete") is not True, terminal
    # The shortcut cannot clear the unresolved revision; request is restart-safe.
    assert runner("evaluate_acceptance")["allowed"] is False
    assert orchestrator("request_acceptance_revision", "ST-001", "--reason", "Resume revision")["status"] == "success"
    opened = orchestrator("begin_acceptance_authoring", "ST-001",
                          "--authoring-stage", "independent_test_first")
    assert opened["status"] == "success", opened
    checkpoint_id = opened["checkpoint"]["checkpoint_id"]
    assert orchestrator("get_next_step")["phase"] == "TEST_WRITER"
    state = json.loads(state_path.read_text())
    assert state["acceptance_authoring"]["ST-001"]["checkpoint_id"] == checkpoint_id
    assert state["acceptance_authoring"]["ST-001"]["stage"] == "independent_test_first"
    assert state["acceptance_authoring_history"][0]["status"] == "superseded"
    assert state["completed_at"] is None
    revised = runner("revise_acceptance_contract", ac_id="AC-1",
                     command=[sys.executable, "proof.py"], proof_files=["proof.py"],
                     author="test-writer", authoring_stage="independent_test_first",
                     reason="Clarified requirement without changing assertions",
                     assessment="equivalent")
    assert revised["status"] == "success", revised
    # Old checkpoint's handoff must not admit the new revision.
    assert orchestrator("mark_contract_ready", "ST-001")["status"] == "error"
    handoff = runner("record_test_contract_handoff", subtask_id="ST-001",
                     test_files_csv="proof.py", authoring_result="already_green",
                     authoring_justification="Assertions unchanged and existing product satisfies them")
    assert handoff["status"] == "success", handoff
    assert orchestrator("mark_contract_ready", "ST-001")["status"] == "success"
    assert runner("run_acceptance_proofs")["status"] == "success"


def test_batch_red_gate_consumes_checkpoint_before_actor(completion_workspace):
    freeze_proof(completion_workspace)
    state_path = completion_workspace / "step_state.json"
    state = json.loads(state_path.read_text())
    state.update(current_step_id="2.26", current_step_phase="TEST_FAIL_GATE",
                 pending_steps=["2.26", "2.3", "2.4"], tdd_mode=True)
    state_path.write_text(json.dumps(state))
    result = orchestrator("validate_step", "2.26")
    assert result["valid"] is True, result
    state = json.loads(state_path.read_text())
    assert state["acceptance_authoring"]["ST-001"]["status"] == "consumed"
    assert orchestrator("get_next_step")["phase"] == "ACTOR"


def test_wave_reader_revalidates_historical_completion(completion_workspace):
    freeze_proof(completion_workspace)
    assert runner("run_acceptance_proofs")["status"] == "success"
    state_path = completion_workspace / "step_state.json"
    state = json.loads(state_path.read_text())
    state.update(execution_waves=[["ST-001"]], current_wave_index=1)
    state_path.write_text(json.dumps(state))
    assert orchestrator("get_wave_step")["is_complete"] is True
    Path("product.txt").write_text("changed")
    assert orchestrator("get_wave_step")["is_complete"] is False


def test_explicit_warn_first_completion_lists_unexecuted_proof(completion_workspace):
    freeze_proof(completion_workspace)
    result = orchestrator("mark_workflow_complete")
    assert result["status"] == "success", result
    assert result["acceptance"]["requirements"][0]["status"] == "unproven"
    assert orchestrator("get_next_step")["is_complete"] is True


def test_actor_admission_detects_proof_tampering(completion_workspace):
    freeze_proof(completion_workspace)
    Path("proof.py").write_text("pass\n")
    state_path = completion_workspace / "step_state.json"
    state = json.loads(state_path.read_text())
    state.update(current_step_id="2.3", current_step_phase="ACTOR", pending_steps=["2.3"])
    state_path.write_text(json.dumps(state))
    result = orchestrator("get_next_step")
    assert result["step_id"] == "ACCEPTANCE_BLOCKED", result
    assert result["is_complete"] is False
