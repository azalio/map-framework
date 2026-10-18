"""Lossless pending-order changes through the public orchestrator API and CLI."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "src/mapify_cli/templates/map/scripts"
sys.path.insert(0, str(SCRIPTS))
import map_orchestrator  # pyright: ignore[reportMissingImports]


@pytest.fixture
def active_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    branch = "resequence-test"
    directory = tmp_path / ".map" / branch
    directory.mkdir(parents=True)
    state = map_orchestrator.StepState(
        current_subtask_id="ST-002",
        subtask_index=1,
        subtask_sequence=["ST-001", "ST-002", "ST-003", "ST-004"],
        current_step_id="2.2",
        current_step_phase="RESEARCH",
        pending_steps=["2.2", "2.3", "2.4"],
        completed_steps=["2.1"],
        retry_count=2,
        subtask_results={"ST-001": {"status": "done", "unknown": [1, None]}},
        subtask_diff_bases={"ST-002": "baseline-sha"},
    ).to_dict()
    state["future_extension"] = {"receipt": [None, True, 1.25, "opaque"]}
    path = directory / "step_state.json"
    path.write_text(json.dumps(state, indent=4) + "\n", encoding="utf-8")
    blueprint = {
        "subtasks": [
            {"id": sid, "dependencies": [], "affected_files": [f"{sid}.py"]}
            for sid in state["subtask_sequence"]
        ]
    }
    (directory / "blueprint.json").write_text(json.dumps(blueprint), encoding="utf-8")
    return branch, path, state


@pytest.mark.parametrize(
    "order",
    [
        ["ST-002", "ST-001", "ST-003", "ST-004"],
        ["ST-001", "ST-003", "ST-002", "ST-004"],
        ["ST-001", "ST-002", "ST-003"],
        ["ST-001", "ST-002", "ST-004", "ST-004"],
        ["ST-001", "ST-002", "ST-004", "ST-005"],
    ],
)
def test_invalid_order_leaves_state_byte_identical(active_run, order):
    branch, path, _ = active_run
    before = path.read_bytes()
    result = map_orchestrator.resequence_pending(order, branch, "invalid")
    assert result["status"] == "error"
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "bad_blueprint", ["missing", "malformed", "dependency", "unknown", "self"]
)
def test_blueprint_validation_is_fail_closed(active_run, bad_blueprint):
    branch, path, _ = active_run
    blueprint_path = path.with_name("blueprint.json")
    if bad_blueprint == "missing":
        blueprint_path.unlink()
    elif bad_blueprint == "malformed":
        blueprint_path.write_text("[]", encoding="utf-8")
    else:
        blueprint = json.loads(blueprint_path.read_text())
        blueprint["subtasks"][3]["dependencies"] = [
            {"dependency": "ST-003", "unknown": "ST-999", "self": "ST-004"}[
                bad_blueprint
            ]
        ]
        blueprint_path.write_text(json.dumps(blueprint))
    before = path.read_bytes()
    result = map_orchestrator.resequence_pending(
        ["ST-001", "ST-002", "ST-004", "ST-003"], branch, "DoD first"
    )
    assert result["status"] == "error"
    assert path.read_bytes() == before


def test_noop_is_byte_identical_and_audit_survives_typed_save(active_run):
    branch, path, state = active_run
    before = path.read_bytes()
    assert (
        map_orchestrator.resequence_pending(state["subtask_sequence"], branch, "same")[
            "status"
        ]
        == "success"
    )
    assert path.read_bytes() == before
    order = ["ST-001", "ST-002", "ST-004", "ST-003"]
    assert (
        map_orchestrator.resequence_pending(order, branch, "DoD first")["status"]
        == "success"
    )
    audit = json.loads(path.read_text())["resequence_history"]
    loaded = map_orchestrator.StepState.load(path)
    loaded.save(path)
    assert json.loads(path.read_text())["resequence_history"] == audit
    step = map_orchestrator.peek_current_step(branch)
    assert step["current_subtask"] == "ST-002"
    assert step["step_id"] == "2.2"
    assert step["phase"] == "RESEARCH"


def test_future_waves_recomputed_without_changing_current_wave(active_run):
    branch, path, state = active_run
    state["execution_waves"] = [["ST-001"], ["ST-002"], ["ST-003"], ["ST-004"]]
    state["current_wave_index"] = 1
    state["subtask_phases"] = {"ST-002": "2.3"}
    state["subtask_retry_counts"] = {"ST-002": 2}
    path.write_text(json.dumps(state))
    sidecar = path.with_name("worktrees.json")
    sidecar.write_text(
        json.dumps(
            {
                "wave_groups": {
                    "ST-002": {
                        "subtask_ids": ["ST-002"],
                        "base_sha": "base",
                        "lifecycle": {},
                    }
                }
            }
        )
    )
    before_sidecar = sidecar.read_bytes()
    order = ["ST-001", "ST-002", "ST-004", "ST-003"]
    assert (
        map_orchestrator.resequence_pending(order, branch, "DoD first")["status"]
        == "success"
    )
    after = json.loads(path.read_text())
    assert after["execution_waves"] == [["ST-001"], ["ST-002"], ["ST-004", "ST-003"]]
    assert after["current_wave_index"] == 1
    assert after["subtask_phases"] == {"ST-002": "2.3"}
    assert after["subtask_retry_counts"] == {"ST-002": 2}
    assert sidecar.read_bytes() == before_sidecar


def test_cli_resequence_and_restart_at_same_step(active_run):
    branch, path, _ = active_run
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(path.parents[2])}
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "map_orchestrator.py"),
            "resequence_pending",
            branch,
            "--sequence",
            "ST-001,ST-002,ST-004,ST-003",
            "--reason",
            "DoD first",
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "success"
    restarted = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "map_orchestrator.py"),
            "get_next_step",
            "--branch",
            branch,
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert restarted.returncode == 0, restarted.stderr
    step = json.loads(restarted.stdout)
    assert step["current_subtask"] == "ST-002"
    assert step["step_id"] == "2.2"
    assert step["phase"] == "RESEARCH"
    assert json.loads(path.read_text())["retry_count"] == 2


@pytest.mark.parametrize(
    "mode", ["completed", "sibling", "active_group", "phase", "cursor", "audit", "raw"]
)
def test_inconsistent_or_started_state_rejected(active_run, mode):
    branch, path, state = active_run
    if mode == "completed":
        state["subtask_results"]["ST-003"] = {"status": "done"}
    elif mode == "sibling":
        state["execution_waves"] = [["ST-001"], ["ST-002", "ST-003"], ["ST-004"]]
        state["current_wave_index"] = 1
    elif mode == "active_group":
        path.with_name("worktrees.json").write_text(
            json.dumps({"wave_groups": {"g": {"subtask_ids": ["ST-004"]}}})
        )
    elif mode == "phase":
        state["subtask_phases"] = {"ST-003": "2.3"}
    elif mode == "cursor":
        state["subtask_index"] = 0
    elif mode == "audit":
        state["resequence_history"] = {}
    path.write_text("[]" if mode == "raw" else json.dumps(state))
    before = path.read_bytes()
    result = map_orchestrator.resequence_pending(
        ["ST-001", "ST-002", "ST-004", "ST-003"], branch, "DoD first"
    )
    assert result["status"] == "error"
    assert path.read_bytes() == before


def test_atomic_replace_failure_keeps_state_and_audit(active_run, monkeypatch):
    branch, path, _ = active_run
    before = path.read_bytes()
    original_replace = Path.replace

    def fail_state_replace(source, target):
        if target == path or Path(target).resolve() == path:
            raise OSError("injected publication failure")
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", fail_state_replace)
    result = map_orchestrator.resequence_pending(
        ["ST-001", "ST-002", "ST-004", "ST-003"], branch, "DoD first"
    )
    assert result["status"] == "error"
    assert path.read_bytes() == before
    assert list(path.parent.glob(".step_state.json.*.tmp")) == []


def test_direct_api_waits_for_branch_transaction(active_run):
    branch, path, state = active_run
    code = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import map_orchestrator
result = map_orchestrator.resequence_pending(
    ['ST-001', 'ST-002', 'ST-004', 'ST-003'], sys.argv[2], 'DoD first')
assert result['status'] == 'success', result
"""
    with map_orchestrator.branch_transaction(path.parent):
        process = subprocess.Popen([sys.executable, "-c", code, str(SCRIPTS), branch])
        try:
            with pytest.raises(subprocess.TimeoutExpired):
                process.wait(timeout=1)
            state["future_extension"]["concurrent_receipt"] = "preserved"
            path.write_text(json.dumps(state))
        finally:
            map_orchestrator.release_branch_transaction()
            try:
                assert process.wait(timeout=20) == 0
            finally:
                map_orchestrator.acquire_branch_transaction(path.parent)
                if process.poll() is None:
                    process.kill()
                    process.wait()
    assert (
        json.loads(path.read_text())["future_extension"]["concurrent_receipt"]
        == "preserved"
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("current_step_id", "bogus"),
        ("current_step_phase", []),
        ("pending_steps", "bad"),
        ("current_wave_index", "bad"),
        ("retry_count", "bad"),
        ("subtask_retry_counts", {"ST-002": "bad"}),
        ("subtask_phases", {"ST-002": []}),
        ("subtask_results", {"ST-001": "bad"}),
    ],
)
def test_malformed_execution_frame_is_unchanged(active_run, field, value):
    branch, path, state = active_run
    state[field] = value
    path.write_text(json.dumps(state))
    before = path.read_bytes()
    assert (
        map_orchestrator.resequence_pending(
            ["ST-001", "ST-002", "ST-004", "ST-003"], branch, "DoD first"
        )["status"]
        == "error"
    )
    assert path.read_bytes() == before


def test_missing_scheduled_dependency_rejected(active_run):
    branch, path, _ = active_run
    blueprint_path = path.with_name("blueprint.json")
    blueprint = json.loads(blueprint_path.read_text())
    blueprint["subtasks"].append({"id": "ST-005", "dependencies": []})
    blueprint["subtasks"][3]["dependencies"] = ["ST-005"]
    blueprint_path.write_text(json.dumps(blueprint))
    before = path.read_bytes()
    assert (
        map_orchestrator.resequence_pending(
            ["ST-001", "ST-002", "ST-004", "ST-003"], branch, "DoD first"
        )["status"]
        == "error"
    )
    assert path.read_bytes() == before


@pytest.mark.parametrize("shared_wave", [False, True])
def test_serial_walker_resequences_with_stale_wave_cursor(active_run, shared_wave):
    branch, path, state = active_run
    (path.parents[1] / "config.yaml").write_text("worktree.isolation: off\n")
    state["execution_waves"] = [["ST-001"], ["ST-002"], ["ST-003"], ["ST-004"]]
    state["current_wave_index"] = 0
    if shared_wave:
        state["execution_waves"] = [state["subtask_sequence"]]
    path.write_text(json.dumps(state))
    assert (
        map_orchestrator.resequence_pending(
            ["ST-001", "ST-002", "ST-004", "ST-003"], branch, "DoD first"
        )["status"]
        == "success"
    )
    after = json.loads(path.read_text())
    assert after["current_wave_index"] == 0
    assert after["execution_waves"] == [["ST-001", "ST-002", "ST-004", "ST-003"]]
    assert (
        map_orchestrator.select_execution_strategy(branch)["strategy"] == "sequential"
    )
    assert after["current_subtask_id"] == "ST-002"
    assert after["current_step_id"] == "2.2"


def test_original_long_serial_run_preserves_execution_frame(active_run):
    branch, path, state = active_run
    (path.parents[1] / "config.yaml").write_text("worktree.isolation: off\n")
    ids = [f"ST-{index:03d}" for index in range(1, 29)]
    state["subtask_sequence"] = ids
    state["subtask_index"] = 14
    state["current_subtask_id"] = "ST-015"
    state["subtask_results"] = {sid: {"status": "done"} for sid in ids[:14]}
    state["execution_waves"] = [[sid] for sid in ids]
    state["current_wave_index"] = 0
    path.write_text(json.dumps(state))
    path.with_name("blueprint.json").write_text(
        json.dumps(
            {
                "subtasks": [
                    {"id": sid, "dependencies": [], "affected_files": [f"{sid}.py"]}
                    for sid in ids
                ]
            }
        )
    )
    order = ids[:21] + ["ST-023", "ST-025", "ST-022", "ST-024"] + ids[25:]
    assert (
        map_orchestrator.resequence_pending(order, branch, "DoD first")["status"]
        == "success"
    )
    after = json.loads(path.read_text())
    for field in (
        "current_subtask_id",
        "subtask_index",
        "current_step_id",
        "current_step_phase",
        "retry_count",
        "subtask_results",
        "subtask_diff_bases",
        "future_extension",
        "current_wave_index",
    ):
        assert after[field] == state[field]
    assert after["subtask_sequence"] == order


@pytest.mark.parametrize("provider", ["claude", "codex"])
def test_installed_cli_resequences_waves_without_checkout_imports(
    active_run, tmp_path, provider
):
    from typer.testing import CliRunner

    from mapify_cli import app

    branch, path, state = active_run
    project = tmp_path / f"installed-{provider}"
    installed = CliRunner().invoke(
        app, ["init", str(project), "--provider", provider, "--no-git", "--mcp", "none"]
    )
    assert installed.exit_code == 0, installed.output
    directory = project / ".map" / branch
    directory.mkdir()
    state["execution_waves"] = [["ST-001"], ["ST-002"], ["ST-003"], ["ST-004"]]
    state["current_wave_index"] = 1
    (directory / "step_state.json").write_text(json.dumps(state))
    (directory / "blueprint.json").write_bytes(
        path.with_name("blueprint.json").read_bytes()
    )
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project)}
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [
            sys.executable,
            str(project / ".map/scripts/map_orchestrator.py"),
            "resequence_pending",
            branch,
            "--sequence",
            "ST-001,ST-002,ST-004,ST-003",
            "--reason",
            "DoD first",
        ],
        cwd=project,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "success"
    assert json.loads((directory / "step_state.json").read_text())[
        "execution_waves"
    ] == [["ST-001"], ["ST-002"], ["ST-004", "ST-003"]]


def test_active_parallel_group_and_earlier_waves_preserved(active_run):
    branch, path, state = active_run
    ids = [f"ST-{index:03d}" for index in range(1, 7)]
    state["subtask_sequence"] = ids
    state["execution_waves"] = [[ids[0]], ids[1:3], [ids[3]], [ids[4]], [ids[5]]]
    state["current_wave_index"] = 1
    state["subtask_phases"] = {ids[1]: "2.3", ids[2]: "2.4"}
    path.write_text(json.dumps(state))
    blueprint = {
        "subtasks": [
            {"id": sid, "dependencies": [], "affected_files": ["shared.py"]}
            for sid in ids
        ]
    }
    path.with_name("blueprint.json").write_text(json.dumps(blueprint))
    sidecar = path.with_name("worktrees.json")
    sidecar.write_text(
        json.dumps(
            {
                "wave_groups": {
                    "ST-002|ST-003": {
                        "subtask_ids": ids[1:3],
                        "base_sha": "base",
                        "lifecycle": {ids[1]: [{"event": "dispatch", "seq": 1}]},
                    }
                }
            }
        )
    )
    sidecar_before = sidecar.read_bytes()
    order = ids[:3] + [ids[5], ids[3], ids[4]]
    assert (
        map_orchestrator.resequence_pending(order, branch, "DoD first")["status"]
        == "success"
    )
    after = json.loads(path.read_text())
    assert after["execution_waves"] == [
        [ids[0]],
        ids[1:3],
        [ids[5]],
        [ids[3]],
        [ids[4]],
    ]
    assert after["subtask_phases"] == state["subtask_phases"]
    assert sidecar.read_bytes() == sidecar_before


def test_active_wave_dependency_conflict_rejected(active_run):
    branch, path, state = active_run
    ids = [f"ST-{index:03d}" for index in range(1, 6)]
    state["subtask_sequence"] = ids
    state["execution_waves"] = [[ids[0]], ids[1:3], ids[3:]]
    state["current_wave_index"] = 1
    path.write_text(json.dumps(state))
    path.with_name("blueprint.json").write_text(
        json.dumps(
            {
                "subtasks": [
                    {
                        "id": sid,
                        "dependencies": ["ST-002"] if sid == "ST-003" else [],
                        "affected_files": [f"{sid}.py"],
                    }
                    for sid in ids
                ]
            }
        )
    )
    before = path.read_bytes()
    assert (
        map_orchestrator.resequence_pending(
            ids[:3] + list(reversed(ids[3:])), branch, "DoD first"
        )["status"]
        == "error"
    )
    assert path.read_bytes() == before


def test_serial_recompute_rejects_out_of_bounds_preserved_wave_cursor(active_run):
    branch, path, state = active_run
    (path.parents[1] / "config.yaml").write_text("worktree.isolation: off\n")
    state["execution_waves"] = [[sid] for sid in state["subtask_sequence"]]
    state["current_wave_index"] = 2
    path.write_text(json.dumps(state))
    before = path.read_bytes()
    result = map_orchestrator.resequence_pending(
        ["ST-001", "ST-002", "ST-004", "ST-003"], branch, "DoD first"
    )
    assert result["status"] == "error"
    assert "preserve the existing wave cursor" in result["message"]
    assert path.read_bytes() == before


def test_pending_reorder_preserves_all_protected_values(active_run):
    branch, path, before = active_run
    order = ["ST-001", "ST-002", "ST-004", "ST-003"]

    result = map_orchestrator.resequence_pending(order, branch, "DoD first")

    assert result["status"] == "success"
    after = json.loads(path.read_text(encoding="utf-8"))
    assert after.pop("subtask_sequence") == order
    assert after.pop("resequence_history") == [
        {
            "old_order": before["subtask_sequence"],
            "new_order": order,
            "reason": "DoD first",
        }
    ]
    assert after == {
        key: value
        for key, value in before.items()
        if key not in {"subtask_sequence", "resequence_history"}
    }
