"""Real-Git contract tests for serial, lossless blocker repair."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src/mapify_cli/templates_src/map/scripts/map_interruption.py.jinja"


def test_public_engine_contract_exists():
    assert SOURCE.is_file(), "The standalone interruption engine must exist"
    text = SOURCE.read_text()
    for name in (
        "request_repair", "begin_repair", "verify_repair", "finish_repair",
        "interruption_guard", "get_interruption_status",
    ):
        assert f"def {name}(" in text


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True,
                            text=True, check=True)
    return result.stdout.strip()


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


@pytest.fixture
def engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    script = tmp_path / "engine.py"
    script.write_text(SOURCE.read_text())
    spec = importlib.util.spec_from_file_location("repair_test_engine", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    scripts = ROOT / "src/mapify_cli/templates/map/scripts"
    monkeypatch.syspath_prepend(str(scripts))
    # Real canonical utils and orchestrator; runner approval boundary is modeled
    # with the exact durable hold shape, avoiding unrelated package startup.
    runner = ModuleType("map_step_runner")

    def create_hold(**kwargs: Any):
        branch = kwargs["branch"]
        path = Path.cwd() / ".map" / branch / "approval_holds.json"
        hold = {**kwargs, "id": "hold-001", "state": "pending"}
        dump(path, {"holds": {"hold-001": hold}})
        return {"status": "ok", "hold_id": "hold-001", "hold": hold}

    runner.create_approval_hold = create_hold  # type: ignore[attr-defined]
    def baseline(*args: Any) -> str:
        del args
        return "HEAD"

    runner._resolve_subtask_diff_base = baseline  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "map_step_runner", runner)
    return module


@pytest.fixture(params=["standalone", "linked"])
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine: Any, request: pytest.FixtureRequest):
    root = tmp_path / "main"
    root.mkdir()
    git(root, "init", "-b", "feature")
    git(root, "config", "user.name", "Test")
    git(root, "config", "user.email", "test@localhost")
    files = {"feature.txt": "base", "fix.txt": "broken", "remove.txt": "delete",
             "rename.txt": "rename", "unstaged-delete.txt": "delete", "binary": "base"}
    for name, value in files.items():
        (root / name).write_text(value)
    (root / "link").symlink_to("feature.txt")
    git(root, "add", ".")
    git(root, "commit", "-m", "base")
    if request.param == "linked":
        linked = tmp_path / "linked"
        git(root, "worktree", "add", "-b", "linked", str(linked))
        root = linked
    gitdir = Path(git(root, "rev-parse", "--absolute-git-dir"))
    head = git(root, "rev-parse", "HEAD")
    (root / "feature.txt").write_text("staged")
    git(root, "add", "feature.txt")
    (root / "feature.txt").write_text("working")
    git(root, "mv", "rename.txt", "renamed.txt")
    (root / "renamed.txt").write_text("unstaged rename")
    (root / "unstaged-delete.txt").unlink()
    (root / "binary").write_bytes(b"\0binary\xff")
    (root / "untracked").write_text("private feature")
    (root / "untracked").chmod(0o600)
    (root / "link").unlink()
    (root / "link").symlink_to("renamed.txt")
    branch = "feature"
    directory = root / ".map" / branch
    state = {"current_subtask_id": "FEATURE", "current_step_phase": "ACTOR",
             "current_step_id": "2.3", "retry_count": 3, "subtask_sequence": ["DONE", "FEATURE"],
             "subtask_results": {"DONE": {"status": "completed"}}, "tdd_mode": False}
    dump(directory / "step_state.json", state)
    gate = [sys.executable, "-c", "from pathlib import Path; assert Path('fix.txt').read_text()=='fixed'; assert Path('feature.txt').read_text()=='working'"]
    contract = {"id": "REPAIR", "affected_files": ["fix.txt", "remove.txt", "new.txt", "new-exec", "new-link"],
                "dependencies": ["DONE"], "repair_checks": [gate]}
    dump(directory / "blueprint.json", {"subtasks": [contract]})
    monkeypatch.chdir(root)
    return SimpleNamespace(root=root, directory=directory, state=state, contract=contract,
                           engine=engine, head=head, branch=branch, gitdir=gitdir)


def test_fresh_linked_workflow_guard(workspace: Any, monkeypatch: pytest.MonkeyPatch):
    w = workspace
    fresh = w.root.parent / "fresh"
    git(w.root, "worktree", "add", "-b", "fresh", str(fresh))
    monkeypatch.chdir(fresh)
    assert w.engine.interruption_guard("fresh") is None
    assert w.engine.get_interruption_status("fresh") == {"status": "idle"}
    assert not (fresh / ".map").exists()


def test_linked_worktrees_do_not_share_repair_journals(workspace: Any, monkeypatch: pytest.MonkeyPatch):
    w = workspace
    other = w.root.parent / "other"
    git(w.root, "worktree", "add", "-b", "other", str(other))
    other_gitdir = Path(git(other, "rev-parse", "--absolute-git-dir"))
    operation = start(w)
    assert (w.gitdir / "map-repairs" / operation["operation_id"] / "journal.json").is_file()
    assert not (other_gitdir / "map-repairs").exists()
    monkeypatch.chdir(other)
    # Matching runtime identifiers prove isolation does not rely on branch names.
    assert w.engine.interruption_guard(w.branch) is None
    dump(other / ".map" / w.branch / "step_state.json", w.state)
    assert w.engine.interruption_guard(w.branch) is None
    dump(other / ".map" / w.branch / "step_state.json",
         json.loads((w.directory / "step_state.json").read_text()))
    assert w.engine.interruption_guard(w.branch)["status"] == "error"
    monkeypatch.chdir(w.root)
    assert w.engine.interruption_guard(w.branch)["status"] == "interrupted"


@pytest.mark.parametrize("fault", ["map_symlink", "branch_symlink", "unsafe_branch", "missing_state",
                                   "dangling_storage", "missing_objects", "bad_gitfile",
                                   "bad_backlink", "bad_commondir"])
def test_linked_guard_fail_closed(workspace: Any, monkeypatch: pytest.MonkeyPatch, fault: str):
    w = workspace
    linked = w.root.parent / "guard-linked"
    git(w.root, "worktree", "add", "-b", "guard-linked", str(linked))
    gitdir = Path(git(linked, "rev-parse", "--absolute-git-dir"))
    common = Path(git(linked, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    branch = w.branch
    if fault == "map_symlink":
        (linked / ".map").symlink_to(w.root / ".map", target_is_directory=True)
    elif fault == "branch_symlink":
        (linked / ".map").mkdir()
        (linked / ".map" / branch).symlink_to(w.directory, target_is_directory=True)
    elif fault == "unsafe_branch":
        branch = "../escape"
    elif fault == "missing_state":
        (gitdir / "map-repairs").mkdir()
    elif fault == "dangling_storage":
        (gitdir / "map-repairs").symlink_to(linked / "absent")
    elif fault == "missing_objects":
        (common / "objects").rename(common / "saved-objects")
    elif fault == "bad_backlink":
        (gitdir / "gitdir").write_text(str(w.root / ".git"))
    elif fault == "bad_commondir":
        (gitdir / "commondir").write_text("../missing\n")
    else:
        (linked / ".git").write_text("gitdir: nonexistent\n")
    monkeypatch.chdir(linked)
    assert w.engine.interruption_guard(branch)["status"] == "error"


@pytest.mark.parametrize("nested", [False, True])
def test_guard_refuses_dangling_git_metadata(engine: Any, tmp_path: Path,
                                           monkeypatch: pytest.MonkeyPatch, nested: bool):
    root = tmp_path / "dangling"
    root.mkdir()
    (root / ".git").symlink_to(tmp_path / "missing-git")
    cwd = root / "child" if nested else root
    cwd.mkdir(exist_ok=True)
    monkeypatch.chdir(cwd)
    assert engine.interruption_guard("feature")["status"] == "error"


def test_guard_allows_genuine_pre_git_workspace(engine: Any, tmp_path: Path,
                                              monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "pre-git"
    root.mkdir()
    monkeypatch.chdir(root)
    assert engine.interruption_guard("feature") is None
    assert not (root / ".map").exists()


def start(w: Any) -> dict[str, Any]:
    request = w.engine.request_repair("REPAIR", w.branch)
    assert request["status"] == "ok", request
    path = w.directory / "approval_holds.json"
    holds = json.loads(path.read_text())
    holds["holds"][request["hold_id"]]["state"] = "approved"
    dump(path, holds)
    result = w.engine.begin_repair("REPAIR", w.branch, request["hold_id"])
    assert result["status"] == "ok", result
    return result


def certify(w: Any, operation: dict[str, Any], *, real_workflow: bool = False) -> dict[str, Any]:
    private = Path(operation["private_checkout"])
    (private / "fix.txt").write_text("fixed")
    (private / "remove.txt").unlink()
    (private / "new.txt").write_text("new")
    (private / "new-exec").write_text("#!/bin/sh\nexit 0\n")
    (private / "new-exec").chmod(0o755)
    (private / "new-link").symlink_to("fix.txt")
    git(private, "add", "-A")
    git(private, "-c", "user.name=Test", "-c", "user.email=test@localhost", "commit", "-m", "repair")
    state_path = private / ".map" / w.branch / "step_state.json"
    state = json.loads(state_path.read_text())
    if not real_workflow:
        state.update(workflow_status="WORKFLOW_COMPLETE", current_step_phase="COMPLETE",
                     completed_steps=["2.2", "2.3", "2.4"])
        dump(state_path, state)
    monitor = private / ".map" / w.branch / "monitor.json"
    dump(monitor, {"valid": True, "recommendation": "approve", "summary": "Verified", "issues": [],
                   "operation_id": operation["operation_id"],
                   "contract_digest": operation["contract_digest"],
                   "candidate_tree": git(private, "rev-parse", "HEAD^{tree}")})
    if real_workflow:
        driver = """
import json, sys
sys.path.insert(0,sys.argv[1])
import map_orchestrator as o
import map_step_runner as r
research={'status':'OK','confidence':1.0,'relevant_locations':[],
          'search_stats':{'files_scanned':1,'total_matches_found':1,'results_truncated':False}}
r.save_research('feature','REPAIR',json.dumps(research))
next_step=o.get_next_step('feature')
assert next_step['phase']=='RESEARCH',next_step
report=o.validate_step('2.2','feature');assert report['valid'],report
report=o.validate_step('2.3','feature');assert report['valid'],report
import subprocess
commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
o.record_subtask_result('REPAIR','feature',files_changed=['fix.txt','remove.txt','new.txt','new-exec','new-link'],status='completed',commit_sha=commit)
monitor=open(sys.argv[2]).read()
report=o.validate_step('2.4','feature',recommendation='approve',monitor_envelope=monitor)
assert report['valid'],report
print(json.dumps(o.get_next_step('feature')))
"""
        process = subprocess.run([sys.executable, "-I", "-c", driver,
                                  str(ROOT / "src/mapify_cli/templates/map/scripts"), str(monitor)],
                                 cwd=private, capture_output=True, text=True, check=False)
        assert process.returncode == 0, process.stdout + process.stderr
    result = w.engine.verify_repair(operation["operation_id"], w.branch, str(monitor))
    assert result["status"] == "ok", result
    return result


def test_private_normal_workflow_apis_complete(workspace: Any):
    operation = start(workspace)
    certify(workspace, operation, real_workflow=True)
    assert workspace.engine.finish_repair(operation["operation_id"], workspace.branch)["stage"] == "done"


@pytest.mark.parametrize("phase,tdd", [("ACTOR", False), ("MONITOR", False), ("TEST_WRITER", True)])
def test_lossless_lifecycle_preserves_exact_paused_frame(workspace: Any, phase: str, tdd: bool):
    w = workspace
    w.state.update(current_step_phase=phase, tdd_mode=tdd)
    dump(w.directory / "step_state.json", w.state)
    index = w.engine._entries(w.root)
    images = {p: w.engine._image(w.root, p) for p in w.engine._paths(w.root)}
    operation = start(w)
    assert git(w.root, "rev-parse", "HEAD") == w.head
    assert w.engine._entries(w.root) == index
    assert all(w.engine._image(w.root, p) == image for p, image in images.items())
    private = Path(operation["private_checkout"])
    assert git(private, "remote") == ""
    assert not (private / ".git/objects/info/alternates").exists()
    assert (private / "untracked").stat().st_mode & 0o777 == 0o600
    assert json.loads((private / ".map/feature/step_state.json").read_text())["current_step_phase"] == "RESEARCH"
    certify(w, operation)
    result = w.engine.finish_repair(operation["operation_id"], w.branch)
    assert result["stage"] == "done", result
    commit = git(w.root, "rev-parse", "HEAD")
    assert git(w.root, "rev-parse", "HEAD^") == w.head
    assert set(git(w.root, "diff", "--name-only", "HEAD^", "HEAD").splitlines()) == set(w.contract["affected_files"])
    for p, image in images.items():
        if p not in w.contract["affected_files"]:
            assert w.engine._image(w.root, p) == image
            assert w.engine._entries(w.root).get(p) == index.get(p)
    state = json.loads((w.directory / "step_state.json").read_text())
    assert w.engine._frame(state) == w.engine._frame(w.state)
    assert state["subtask_results"]["DONE"] == w.state["subtask_results"]["DONE"]
    assert state["active_interruption"] is None
    assert len(state["completed_repair_operations"]) == 1
    adjusted = state["subtask_diff_bases"]["FEATURE"]
    assert git(w.root, "show", adjusted + ":fix.txt") == "fixed"
    assert git(w.root, "show", adjusted + ":feature.txt") == "base"
    state["retry_count"] += 1
    dump(w.directory / "step_state.json", state)
    assert w.engine.finish_repair(operation["operation_id"], w.branch)["stage"] == "done"
    assert json.loads((w.directory / "step_state.json").read_text())["retry_count"] == state["retry_count"]
    assert git(w.root, "rev-parse", "HEAD") == commit
    journal = json.loads((w.gitdir / "map-repairs" / operation["operation_id"] / "journal.json").read_text())
    probe = subprocess.run(["git", "cat-file", "-e", journal["snapshot"]], cwd=w.root, check=False, capture_output=True)
    assert probe.returncode != 0


@pytest.mark.parametrize("fault", ["approval", "overlap", "dependencies", "waves", "secret", "checks"])
def test_begin_refusals_do_not_mutate_checkout(workspace: Any, fault: str):
    w = workspace
    if fault == "overlap":
        w.contract["affected_files"] = ["feature.txt"]
    elif fault == "dependencies":
        w.contract["dependencies"] = ["FEATURE"]
    elif fault == "waves":
        w.state["execution_waves"] = [["FEATURE", "OTHER"]]
    elif fault == "secret":
        (w.root / ".env.private").write_text("fixture, not a credential")
    elif fault == "checks":
        w.contract.pop("repair_checks")
    dump(w.directory / "blueprint.json", {"subtasks": [w.contract]})
    dump(w.directory / "step_state.json", w.state)
    before = (git(w.root, "rev-parse", "HEAD"), (w.gitdir / "index").read_bytes(),
              (w.directory / "step_state.json").read_bytes())
    request = w.engine.request_repair("REPAIR", w.branch)
    if request["status"] != "error":
        holds = json.loads((w.directory / "approval_holds.json").read_text())
        if fault != "approval":
            holds["holds"]["hold-001"]["state"] = "approved"
            dump(w.directory / "approval_holds.json", holds)
        result = w.engine.begin_repair("REPAIR", w.branch, "hold-001")
        assert result["status"] == "error", result
    assert before == (git(w.root, "rev-parse", "HEAD"), (w.gitdir / "index").read_bytes(),
                      (w.directory / "step_state.json").read_bytes())


@pytest.mark.parametrize("left,right,expected", [("a", "a", True), ("a", "a/b", True),
    ("a/b", "a", True), ("A", "a/b", True), ("a", "ab", False)])
def test_prefix_casefold_overlap(engine: Any, left: str, right: str, expected: bool):
    assert engine._overlap(left, right) is expected


def test_gate_failure_cannot_finish(workspace: Any):
    w = workspace
    w.contract["repair_checks"] = [[sys.executable, "-c", "raise SystemExit(7)"]]
    dump(w.directory / "blueprint.json", {"subtasks": [w.contract]})
    operation = start(w)
    with pytest.raises(AssertionError, match="gate failed"):
        certify(w, operation)
    assert w.engine.finish_repair(operation["operation_id"], w.branch)["status"] == "error"
    assert git(w.root, "rev-parse", "HEAD") == w.head


@pytest.mark.parametrize("fault", ["private", "paused", "index", "head", "contract", "ledger", "new_index", "monitor"])
def test_finish_rejects_external_drift(workspace: Any, fault: str):
    w = workspace
    operation = start(w)
    certify(w, operation)
    if fault == "private":
        (Path(operation["private_checkout"]) / "fix.txt").write_text("drift")
    elif fault == "paused":
        (w.root / "feature.txt").write_text("drift")
    elif fault == "index":
        git(w.root, "add", "feature.txt")
    elif fault == "head":
        git(w.root, "commit", "--allow-empty", "-m", "external")
    elif fault == "ledger":
        state = json.loads((w.directory / "step_state.json").read_text())
        state["subtask_results"]["EXTERNAL"] = {"status": "completed"}
        dump(w.directory / "step_state.json", state)
    elif fault == "new_index":
        (w.root / "external").write_text("drift")
        git(w.root, "add", "external")
    elif fault == "monitor":
        dump(Path(operation["private_checkout"]) / ".map/feature/monitor.json", {"valid": True})
    else:
        w.contract["repair_checks"] = [["false"]]
        dump(w.directory / "blueprint.json", {"subtasks": [w.contract]})
    before = (git(w.root, "rev-parse", "HEAD"), (w.gitdir / "index").read_bytes(),
              (w.root / "feature.txt").read_bytes())
    result = w.engine.finish_repair(operation["operation_id"], w.branch)
    assert result["status"] == "error", result
    assert before == (git(w.root, "rev-parse", "HEAD"), (w.gitdir / "index").read_bytes(),
                      (w.root / "feature.txt").read_bytes())


@pytest.mark.parametrize("attribute", ["filter=unsafe", "eol=crlf", "working-tree-encoding=UTF-16"])
def test_conversion_attributes_refused_before_marker(workspace: Any, attribute: str):
    w = workspace
    (w.root / ".gitattributes").write_text("fix.txt " + attribute + "\n")
    request = w.engine.request_repair("REPAIR", w.branch)
    holds_path = w.directory / "approval_holds.json"
    holds = json.loads(holds_path.read_text())
    holds["holds"]["hold-001"]["state"] = "approved"
    dump(holds_path, holds)
    before = (w.directory / "step_state.json").read_bytes()
    result = w.engine.begin_repair("REPAIR", w.branch, request["hold_id"])
    assert result["status"] == "error" and "filters" in result["reasons"][0]
    assert (w.directory / "step_state.json").read_bytes() == before


def test_git_routing_environment_cannot_redirect_checkout(workspace: Any, monkeypatch: pytest.MonkeyPatch):
    w = workspace
    monkeypatch.setenv("GIT_INDEX_FILE", str(w.root / "external-index"))
    monkeypatch.setenv("GIT_WORK_TREE", str(w.root / "not-a-checkout"))
    monkeypatch.setenv("GIT_DIR", str(w.root / "not-a-gitdir"))
    operation = start(w)
    assert operation["stage"] == "active"
    assert not (w.root / "external-index").exists()


def test_stale_monitor_tree_cannot_verify(workspace: Any):
    w = workspace
    operation = start(w)
    certify(w, operation)
    monitor_path = Path(operation["private_checkout"]) / ".map/feature/monitor.json"
    monitor = json.loads(monitor_path.read_text())
    monitor["candidate_tree"] = w.head
    dump(monitor_path, monitor)
    result = w.engine.verify_repair(operation["operation_id"], w.branch, str(monitor_path))
    assert result["status"] == "error" and "bound" in result["reasons"][0]
    assert w.engine.finish_repair(operation["operation_id"], w.branch)["status"] == "error"


@pytest.mark.parametrize("when", ["gate", "after_verify"])
def test_hidden_index_flag_mutation_cannot_certify(workspace: Any, when: str):
    w = workspace
    if when == "gate":
        w.contract["repair_checks"] = [[sys.executable, "-c",
            ("import subprocess; from pathlib import Path; "
             "subprocess.run(['git','update-index','--assume-unchanged','fix.txt'],check=True); "
             "Path('fix.txt').write_text('unchecked')")]]
        dump(w.directory / "blueprint.json", {"subtasks": [w.contract]})
    operation = start(w)
    if when == "gate":
        with pytest.raises(AssertionError, match="flags"):
            certify(w, operation)
    else:
        certify(w, operation)
        private = Path(operation["private_checkout"])
        git(private, "update-index", "--assume-unchanged", "fix.txt")
        (private / "fix.txt").write_text("unchecked")
    assert w.engine.finish_repair(operation["operation_id"], w.branch)["status"] == "error"
    assert git(w.root, "rev-parse", "HEAD") == w.head


def test_guard_detects_missing_corrupt_journal(workspace: Any):
    w = workspace
    operation = start(w)
    journal_path = w.gitdir / "map-repairs" / operation["operation_id"] / "journal.json"
    journal_path.write_text("{")
    assert w.engine.interruption_guard(w.branch)["status"] == "error"
    journal_path.unlink()
    assert w.engine.interruption_guard(w.branch)["status"] == "error"


@pytest.mark.parametrize("fault", ["init", "fetch", "prepared"])
def test_begin_initialization_failure_unblocks_parent(workspace: Any, fault: str, monkeypatch: pytest.MonkeyPatch):
    w = workspace
    request = w.engine.request_repair("REPAIR", w.branch)
    path = w.directory / "approval_holds.json"
    holds = json.loads(path.read_text())
    holds["holds"]["hold-001"]["state"] = "approved"
    dump(path, holds)
    before = ((w.gitdir / "index").read_bytes(), (w.directory / "step_state.json").read_bytes(),
              {p: w.engine._image(w.root, p) for p in w.engine._paths(w.root)})
    original_git = w.engine._git

    def failing_git(root: Path, *args: str, **kwargs: Any) -> bytes:
        if root != w.root and args[0] == fault:
            raise w.engine.RepairError("Injected private initialization failure")
        return original_git(root, *args, **kwargs)

    def checkpoint(name: str) -> None:
        if name == fault:
            raise OSError("Injected prepared initialization failure")

    with monkeypatch.context() as patch:
        patch.setattr(w.engine, "_git", failing_git)
        patch.setattr(w.engine, "_checkpoint", checkpoint)
        result = w.engine.begin_repair("REPAIR", w.branch, request["hold_id"])
    assert result["status"] == "error", result
    assert w.engine.interruption_guard(w.branch) is None
    assert not (w.gitdir / "map-repairs" / request["operation_id"]).exists()
    archives = list(w.gitdir.glob("map-failed-" + request["operation_id"] + "-*"))
    assert len(archives) == 1
    assert archives[0].stat().st_mode & 0o777 == 0o700
    assert not archives[0].is_symlink()
    assert archives[0].name in result["reasons"][0]
    assert (archives[0] / "checkout").is_dir()
    if fault == "prepared":
        assert json.loads((archives[0] / "journal.json").read_text())["stage"] == "prepared"
    assert before == ((w.gitdir / "index").read_bytes(), (w.directory / "step_state.json").read_bytes(),
                      {p: w.engine._image(w.root, p) for p in w.engine._paths(w.root)})
    assert git(w.root, "rev-parse", "HEAD") == w.head
    assert w.engine.begin_repair("REPAIR", w.branch, request["hold_id"])["stage"] == "active"


@pytest.mark.parametrize("drift", ["journal", "missing_journal", "state", "directory", "marker"])
def test_begin_failure_preserves_drifted_recovery_storage(workspace: Any, drift: str, monkeypatch: pytest.MonkeyPatch):
    w = workspace
    request = w.engine.request_repair("REPAIR", w.branch)
    path = w.directory / "approval_holds.json"
    holds = json.loads(path.read_text())
    holds["holds"]["hold-001"]["state"] = "approved"
    dump(path, holds)
    directory = w.gitdir / "map-repairs" / request["operation_id"]

    def checkpoint(name: str) -> None:
        if name != "prepared":
            return
        if drift == "journal":
            journal = json.loads((directory / "journal.json").read_text())
            journal["stage"] = "unfamiliar"
            dump(directory / "journal.json", journal)
        elif drift == "missing_journal":
            (directory / "journal.json").unlink()
        elif drift == "directory":
            directory.rename(directory.with_name("saved-private"))
            directory.mkdir()
            (directory / "unfamiliar").write_text("preserve")
        else:
            state = dict(w.state)
            if drift == "marker":
                state["active_interruption"] = {"operation_id": request["operation_id"],
                                                "contract_digest": request["contract_digest"]}
            else:
                state["retry_count"] += 1
            dump(w.directory / "step_state.json", state)
        raise OSError("Injected failure after metadata drift")

    monkeypatch.setattr(w.engine, "_checkpoint", checkpoint)
    result = w.engine.begin_repair("REPAIR", w.branch, request["hold_id"])
    assert result["status"] == "error" and "cleanup refused" in result["reasons"][0], result
    assert directory.is_dir()
    assert not list(w.gitdir.glob("map-failed-*"))
    if drift == "directory":
        assert (directory / "unfamiliar").read_text() == "preserve"
        assert (directory.with_name("saved-private") / "checkout").is_dir()
    else:
        assert (directory / "checkout").is_dir()
    assert git(w.root, "rev-parse", "HEAD") == w.head


def test_begin_does_not_archive_preexisting_unfamiliar_storage(workspace: Any):
    w = workspace
    request = w.engine.request_repair("REPAIR", w.branch)
    path = w.directory / "approval_holds.json"
    holds = json.loads(path.read_text())
    holds["holds"]["hold-001"]["state"] = "approved"
    dump(path, holds)
    directory = w.gitdir / "map-repairs" / request["operation_id"]
    directory.mkdir(parents=True)
    (directory / "unfamiliar").write_text("preserve")
    result = w.engine.begin_repair("REPAIR", w.branch, request["hold_id"])
    assert result["status"] == "error", result
    assert (directory / "unfamiliar").read_text() == "preserve"
    assert not list(w.gitdir.glob("map-failed-*"))


def test_begin_ordinary_failure_after_marker_retains_recovery(workspace: Any, monkeypatch: pytest.MonkeyPatch):
    w = workspace
    request = w.engine.request_repair("REPAIR", w.branch)
    path = w.directory / "approval_holds.json"
    holds = json.loads(path.read_text())
    holds["holds"]["hold-001"]["state"] = "approved"
    dump(path, holds)

    def checkpoint(name: str) -> None:
        if name == "marker_written":
            raise OSError("Injected failure after durable marker")

    with monkeypatch.context() as patch:
        patch.setattr(w.engine, "_checkpoint", checkpoint)
        result = w.engine.begin_repair("REPAIR", w.branch, request["hold_id"])
    assert result["status"] == "error", result
    assert w.engine.interruption_guard(w.branch)["operation_id"] == request["operation_id"]
    assert not list(w.gitdir.glob("map-failed-*"))
    assert w.engine.begin_repair("REPAIR", w.branch, request["hold_id"])["stage"] == "active"


@pytest.mark.parametrize("cut", ["prepared", "marker_written"])
def test_initialization_marker_cut_recovers(workspace: Any, cut: str, monkeypatch: pytest.MonkeyPatch):
    w = workspace
    request = w.engine.request_repair("REPAIR", w.branch)
    path = w.directory / "approval_holds.json"
    holds = json.loads(path.read_text())
    holds["holds"]["hold-001"]["state"] = "approved"
    dump(path, holds)

    def checkpoint(name: str) -> None:
        if name == cut:
            raise SystemExit(99)

    monkeypatch.setattr(w.engine, "_checkpoint", checkpoint)
    with pytest.raises(SystemExit):
        w.engine.begin_repair("REPAIR", w.branch, request["hold_id"])
    def resume_checkpoint(name: str) -> None:
        del name

    monkeypatch.setattr(w.engine, "_checkpoint", resume_checkpoint)
    recovered = w.engine.begin_repair("REPAIR", w.branch, request["hold_id"])
    assert recovered["stage"] == "active", recovered
    assert w.engine.interruption_guard(w.branch)["operation_id"] == request["operation_id"]


CUTS = ["index_lock_ready", "file_temporary_ready", "head_intent", "after_cas_before_journal", "head_done", "index_intent",
        "after_index_before_journal", "index_done", "files_intent", "file_0", "file_1",
        "file_2", "file_3", "file_4", "done"]


@pytest.mark.parametrize("cut", CUTS)
def test_thirteen_cuts_recover_in_fresh_process(workspace: Any, cut: str):
    w = workspace
    operation = start(w)
    certify(w, operation)
    script = Path(w.engine.__file__)
    driver = """
import importlib.util, json, sys
sys.path.insert(0, sys.argv[2])
spec=importlib.util.spec_from_file_location('repair',sys.argv[1])
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
if sys.argv[5] != 'recover':
    def cut(name):
        if name == sys.argv[5]: raise SystemExit(99)
    m._checkpoint=cut
print(json.dumps(m.finish_repair(sys.argv[3],sys.argv[4])))
"""
    args = [sys.executable, "-I", "-c", driver, str(script),
            str(ROOT / "src/mapify_cli/templates/map/scripts"), operation["operation_id"], w.branch]
    interrupted = subprocess.run([*args, cut], cwd=w.root, check=False, capture_output=True, text=True)
    assert interrupted.returncode == 99, interrupted.stdout + interrupted.stderr
    recovered = subprocess.run([*args, "recover"], cwd=w.root, check=False, capture_output=True, text=True)
    assert recovered.returncode == 0, recovered.stderr
    result = json.loads(recovered.stdout)
    assert result.get("stage") == "done", result
    assert (w.root / "feature.txt").read_text() == "working"
    assert git(w.root, "show", ":feature.txt") == "staged"
    assert (w.root / "fix.txt").read_text() == "fixed"
    assert git(w.root, "rev-parse", "HEAD^") == w.head
    state = json.loads((w.directory / "step_state.json").read_text())
    assert state["retry_count"] == 3 and state["active_interruption"] is None
    assert len(state["completed_repair_operations"]) == 1
