"""Repository-local proofs and joint acceptance of a single approved feature."""

import importlib
import json
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def feature(tmp_path, monkeypatch):
    scripts = Path(__file__).resolve().parents[1] / "src/mapify_cli/templates/map/scripts"
    monkeypatch.syspath_prepend(str(scripts))
    checks = importlib.import_module("map_feature_checks")
    orchestrator = importlib.import_module("map_orchestrator")

    server, client = tmp_path / "server", tmp_path / "client"
    repo_checks = {}
    for name, root in ((".", server), ("../client", client)):
        root.mkdir()
        git(root, "init", "-q")
        git(root, "config", "user.name", "Example")
        git(root, "config", "user.email", "test@example.invalid")
        (root / ".gitignore").write_text(".map/\n")
        (root / "payload.txt").write_text("old")
        git(root, "add", ".")
        git(root, "commit", "-qm", "baseline")
        repo_checks[name] = {"base": git(root, "rev-parse", "HEAD"), "command": [
            sys.executable, "-c", "from pathlib import Path; assert Path('payload.txt').read_text() != 'old'"]}
    task = {"id": "ST-001", "affected_files": ["payload.txt", "../client/payload.txt"],
            "repository_checks": repo_checks, "joint_check": [sys.executable, "-c",
            "from pathlib import Path; assert Path('payload.txt').read_bytes() == Path('../client/payload.txt').read_bytes()"]}
    branch_dir = server / ".map/feature"
    branch_dir.mkdir(parents=True)
    (branch_dir / "blueprint.json").write_text(json.dumps({"subtasks": [task]}))
    (branch_dir / "step_state.json").write_text(json.dumps({
        "plan_approved": True, "approved_feature_contracts": {"ST-001": orchestrator.feature_contract_digest(task, server)}}))

    def check(**kwargs):
        return checks.feature_check("feature", "ST-001", project_dir=server, **kwargs)

    return server, client, task, check


def test_local_and_joint_receipts_follow_each_checkout(feature):
    server, client, _, check = feature
    (server / "payload.txt").write_text("new")
    assert check()["status"] == "pending"
    first = check(repository=".")
    assert first["repositories"]["."]["status"] == "passed", first
    assert first["repositories"]["../client"]["status"] == "pending"
    assert first["repositories"]["."]["files"] == first["repositories"]["../client"]["files"] == ["payload.txt"]
    assert first["repositories"]["."]["root"] == str(server)
    assert first["repositories"]["../client"]["root"] == str(client)
    receipt = json.loads(Path(first["repositories"]["."]["receipt"]).read_text())
    assert receipt["scope"]["status"] == "clean" and receipt["exit_code"] == 0
    assert first["status"] == "pending"
    assert check(joint=True)["status"] != "complete"
    assert check(repository="../client")["status"] == "error"
    assert check()["repositories"]["."]["status"] == "passed"
    (client / "payload.txt").write_text("different")
    assert check(repository="../client")["status"] == "pending"
    assert check(joint=True)["status"] == "error"
    (client / "payload.txt").write_text("new")
    assert check()["repositories"]["../client"]["status"] == "pending"
    assert check(repository="../client")["repositories"]["../client"]["status"] == "passed"
    assert check(joint=True)["status"] == "complete"
    assert check()["status"] == "complete"
    (client / "local-only.txt").write_text("outside scope")
    assert check()["status"] == "pending"
    assert check(repository="../client")["status"] == "error"
    assert check()["repositories"]["."]["status"] == "passed"


def test_unapproved_check_is_never_executed(feature):
    server, _, task, check = feature
    marker = server / "unauthorized-marker"
    task["repository_checks"]["."]["command"] = [sys.executable, "-c",
        f"from pathlib import Path; Path({str(marker)!r}).touch()"]
    (server / ".map/feature/blueprint.json").write_text(json.dumps({"subtasks": [task]}))
    assert check(repository=".")["status"] == "error"
    assert not marker.exists()


def test_writing_a_checked_input_during_the_command_cannot_publish_a_pass(feature):
    server, _, task, check = feature
    task["repository_checks"]["."]["command"] = [sys.executable, "-c",
        "from pathlib import Path; Path('payload.txt').write_text('changed while running')"]
    branch_dir = server / ".map/feature"
    (branch_dir / "blueprint.json").write_text(json.dumps({"subtasks": [task]}))
    orchestrator = importlib.import_module("map_orchestrator")
    state = json.loads((branch_dir / "step_state.json").read_text())
    state["approved_feature_contracts"]["ST-001"] = orchestrator.feature_contract_digest(task, server)
    (branch_dir / "step_state.json").write_text(json.dumps(state))
    result = check(repository=".")
    assert result["status"] == "error" and "changed" in result["message"], result
    assert (server / "payload.txt").read_text() == "changed while running"
    assert check()["repositories"]["."]["status"] == "pending"


def test_late_failure_cannot_replace_a_newer_local_result(feature, monkeypatch):
    server, _, _, check = feature
    (server / "payload.txt").write_text("new")
    checks = importlib.import_module("map_feature_checks")
    started = threading.Event()
    finish = threading.Event()
    original = checks._run

    def run(*args):
        if not started.is_set():
            started.set()
            assert finish.wait(timeout=20)
            return {"status": "failed", "message": "late failure"}
        return original(*args)

    monkeypatch.setattr(checks, "_run", run)
    with ThreadPoolExecutor(max_workers=1) as pool:
        earlier = pool.submit(check, repository=".")
        try:
            assert started.wait(timeout=20)
            assert check(repository=".")["repositories"]["."]["status"] == "passed"
        finally:
            finish.set()
        assert "superseded" in earlier.result(timeout=20)["message"]
    assert check()["repositories"]["."]["status"] == "passed"


def test_joint_receipt_tracks_the_separate_coordinator_checkout(feature):
    server, client, task, _ = feature
    coordinator = server.parent / "coordinator"
    coordinator.mkdir()
    git(coordinator, "init", "-q")
    git(coordinator, "config", "user.name", "Example")
    git(coordinator, "config", "user.email", "test@example.invalid")
    script = coordinator / "compat.py"
    script.write_text("from pathlib import Path\nassert Path('../server/payload.txt').read_bytes()"
                      " == Path('../client/payload.txt').read_bytes()\n")
    (coordinator / ".gitignore").write_text(".map/\n")
    git(coordinator, "add", ".")
    git(coordinator, "commit", "-qm", "joint test")
    git(coordinator, "update-index", "--assume-unchanged", "compat.py")
    state = coordinator / ".map/feature"
    state.mkdir(parents=True)
    task["affected_files"][0] = "../server/payload.txt"
    task["repository_checks"]["../server"] = task["repository_checks"].pop(".")
    task["joint_check"] = [sys.executable, "compat.py"]
    (state / "blueprint.json").write_text(json.dumps({"subtasks": [task]}))
    orchestrator = importlib.import_module("map_orchestrator")
    (state / "step_state.json").write_text(json.dumps({
        "plan_approved": True, "approved_feature_contracts": {"ST-001": orchestrator.feature_contract_digest(task, coordinator)}}))
    checks = importlib.import_module("map_feature_checks")

    def check(**kwargs):
        return checks.feature_check("feature", "ST-001", project_dir=coordinator, **kwargs)

    for project in (server, client):
        (project / "payload.txt").write_text("new")
        assert check(repository="../" + project.name)["status"] == "pending"
    assert check(joint=True)["status"] == "complete"
    script.write_text("raise SystemExit(1)\n")
    stale = check()
    assert stale["status"] == "pending" and stale["joint"]["status"] == "pending"
    assert all(row["status"] == "passed" for row in stale["repositories"].values())
    assert check(joint=True)["status"] == "error"


def test_joint_receipt_requires_prior_subtask_evidence_used_by_local_monitor(feature):
    server, client, task, check = feature
    (server / "README").write_text("other work\n")
    git(server, "add", "README")
    git(server, "commit", "-qm", "finish docs subtask")
    docs_sha = git(server, "rev-parse", "HEAD")
    directory = server / ".map/feature"
    (directory / "blueprint.json").write_text(json.dumps({
        "subtasks": [task, {"id": "ST-002", "affected_files": ["README"]}]}))
    state_file = directory / "step_state.json"
    state = json.loads(state_file.read_text())
    state["subtask_results"] = {"ST-002": {"subtask_id": "ST-002", "status": "valid", "files_changed": ["README"],
                                         "commit_sha": docs_sha}}
    state_file.write_text(json.dumps(state))
    for name, project in ((".", server), ("../client", client)):
        (project / "payload.txt").write_text("new")
        result = check(repository=name)
        assert result["repositories"][name]["status"] == "passed", result
    assert check(joint=True)["status"] == "complete"
    state["subtask_results"].clear()
    state_file.write_text(json.dumps(state))
    stale = check()
    assert stale["status"] == "pending" and stale["repositories"]["."]["status"] == "pending"
    assert stale["repositories"]["../client"]["status"] == "passed"
    assert check(joint=True)["status"] != "complete"


def test_retargeted_checkout_cannot_run_the_approved_command(feature):
    server, client, task, check = feature
    alias = server.parent / "client-alias"
    alias.symlink_to(client, target_is_directory=True)
    clone = server.parent / "other-client"
    git(server.parent, "clone", "-q", str(client), str(clone))
    marker = server.parent / "ran"
    task["affected_files"][1] = "../client-alias/payload.txt"
    config = task["repository_checks"].pop("../client")
    config["command"] = [sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).touch()"]
    task["repository_checks"]["../client-alias"] = config
    directory = server / ".map/feature"
    (directory / "blueprint.json").write_text(json.dumps({"subtasks": [task]}))
    state_file = directory / "step_state.json"
    state = json.loads(state_file.read_text())
    orchestrator = importlib.import_module("map_orchestrator")
    state["approved_feature_contracts"]["ST-001"] = orchestrator.feature_contract_digest(task, server)
    state_file.write_text(json.dumps(state))
    alias.unlink()
    alias.symlink_to(clone, target_is_directory=True)
    result = check(repository="../client-alias")
    assert result["status"] == "error" and "approve" in result["message"].lower(), result
    assert not marker.exists()
