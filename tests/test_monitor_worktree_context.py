"""Monitor reads authoritative parent metadata and the isolated Actor diff."""

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_worktree_isolation import SCRIPTS_PATH, _enable, _git, _make_repo, m


@pytest.fixture
def context(tmp_path, monkeypatch):
    for name in list(os.environ):
        if name.startswith("GIT_") or name == "CLAUDE_PROJECT_DIR":
            monkeypatch.delenv(name)
    spaced = tmp_path / "parent checkout"
    spaced.mkdir()
    root = _make_repo(spaced, branch="actor-plan")
    _enable(root)
    (root / ".gitignore").write_text(".map/\n")
    assert _git(["add", ".gitignore"], root).returncode == 0
    assert _git(["commit", "-qm", "ignore runtime"], root).returncode == 0
    monkeypatch.chdir(root)
    branch_dir = root / ".map/actor-plan"
    branch_dir.mkdir()
    (branch_dir / "blueprint.json").write_text(json.dumps({
        "subtasks": [{"id": "ST-001", "title": "change source", "affected_files": ["a.txt"]}],
    }))
    (branch_dir / "step_state.json").write_text(json.dumps({
        "subtask_results": {"ST-000": {"files_changed": ["a.txt"]}},
    }))
    scripts = root / ".map/scripts"
    scripts.mkdir()
    for name in ("map_step_runner.py", "map_utils.py"):
        shutil.copyfile(SCRIPTS_PATH / name, scripts / name)
    created = m.create_subtask_worktree("ST-001")
    assert created["ok"], created
    actor = Path(created["worktree_path"])
    return root, actor, created


def gate(root, actor, name, *extra, cwd=None, env=None):
    return subprocess.run(
        [sys.executable, str(root / ".map/scripts/map_step_runner.py"), name,
         "actor-plan", "ST-001", "--metadata-root", str(root),
         "--worktree", str(actor), *extra],
        cwd=cwd or actor, env=env, capture_output=True, text=True, check=False,
    )


@pytest.mark.parametrize("committed", [False, True])
def test_real_monitor_commands_without_candidate_runtime(context, monkeypatch, committed):
    root, actor, created = context
    (actor / "a.txt").write_text("Actor edit\n")
    (actor / "leak.txt").write_text("unplanned\n")
    if committed:
        assert _git(["add", "a.txt", "leak.txt"], actor).returncode == 0
        assert _git(["commit", "-qm", "Actor result"], actor).returncode == 0
    # Parent-only work must never enter the candidate's mutation surface.
    (root / "parent.txt").write_text("unrelated\n")
    assert _git(["add", "parent.txt"], root).returncode == 0
    assert _git(["commit", "-qm", "parent advanced"], root).returncode == 0
    (root / "dirty-parent.txt").write_text("dirty\n")
    state_path = root / ".map/actor-plan/step_state.json"
    state = json.loads(state_path.read_text())
    state["last_subtask_commit_sha"] = _git(["rev-parse", "HEAD"], root).stdout.strip()
    state_path.write_text(json.dumps(state))
    before = state_path.read_bytes()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    monkeypatch.setenv("GIT_DIR", str(root / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(root))
    monkeypatch.setenv("GIT_COMMON_DIR", str(root / ".git"))
    monkeypatch.setenv("GIT_INDEX_FILE", str(root / ".git/index"))
    nested = actor / "nested"
    nested.mkdir()
    commands = [line for line in created["monitor_instruction"].splitlines()
                if line.startswith("python3 ")]
    assert len(commands) == 2
    reports = []
    for command in commands:
        argv = shlex.split(command)
        argv[0] = sys.executable
        result = subprocess.run(argv, cwd=nested, capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stderr + result.stdout
        reports.append(json.loads(result.stdout))
    boundary, risk = reports
    assert boundary["actual"] == ["a.txt", "leak.txt"]
    assert boundary["unexpected"] == ["leak.txt"]
    assert boundary["base_ref"] == created["base_sha"]
    assert risk["current_changed_files"] == ["a.txt", "leak.txt"]
    assert risk["shared_source_files"] == ["a.txt"]
    assert risk["recommended_gate"] == "full_suite"
    assert state_path.read_bytes() == before
    assert (root / ".map/actor-plan/scope-violations.log").is_file()
    assert not (actor / ".map").exists()


def test_clean_managed_gate_and_context_dispatch(context):
    root, actor, created = context
    assert created["metadata_root"] == str(root)
    block = m.build_context_block("actor-plan", "ST-001")
    assert created["monitor_instruction"] in block
    boundary = gate(root, actor, "validate_mutation_boundary")
    assert boundary.returncode == 0, boundary.stdout
    assert json.loads(boundary.stdout)["actual"] == []
    risk = gate(root, actor, "detect_cross_subtask_regression_risk")
    assert risk.returncode == 0
    assert json.loads(risk.stdout)["recommended_gate"] == "scoped"


def test_parent_baseline_cannot_hide_candidate_edit(context):
    root, actor, _ = context
    (root / "leak.txt").write_text("same contents\n")
    assert m.record_scope_baseline("actor-plan")["status"] == "success"
    (actor / "leak.txt").write_text("same contents\n")
    result = gate(root, actor, "validate_mutation_boundary")
    assert result.returncode == 0
    assert json.loads(result.stdout)["unexpected"] == ["leak.txt"]


def test_sibling_worktree_cannot_replace_assigned_candidate(context):
    root, actor, _ = context
    sibling = m.create_subtask_worktree("ST-002")
    assert sibling["ok"]
    result = gate(root, Path(sibling["worktree_path"]), "validate_mutation_boundary")
    assert result.returncode == 1
    assert "does not match" in json.loads(result.stdout)["message"]
    assert gate(root, actor, "validate_mutation_boundary").returncode == 0


def test_missing_parent_blueprint_does_not_use_candidate_copy(context):
    root, actor, _ = context
    source = root / ".map/actor-plan/blueprint.json"
    candidate = actor / ".map/actor-plan/blueprint.json"
    candidate.parent.mkdir(parents=True)
    shutil.copyfile(source, candidate)
    source.unlink()
    result = gate(root, actor, "validate_mutation_boundary")
    assert result.returncode == 1
    assert json.loads(result.stdout)["message"] == "blueprint.json not found"


@pytest.mark.parametrize("location", ["nested", "external"])
@pytest.mark.parametrize("declaration_root", ["actor", "parent"])
def test_absolute_declarations_use_actor_relative_paths(context, tmp_path, location, declaration_root):
    root, actor, _ = context
    if location == "external":
        moved = tmp_path / "external actor"
        assert _git(["worktree", "move", str(actor), str(moved)], root).returncode == 0
        registry = root / ".map/actor-plan/worktrees.json"
        data = json.loads(registry.read_text())
        next(iter(data["worktrees"].values()))["path"] = str(moved)
        registry.write_text(json.dumps(data))
        actor = moved
    blueprint = root / ".map/actor-plan/blueprint.json"
    data = json.loads(blueprint.read_text())
    data["subtasks"][0]["affected_files"] = [str((actor if declaration_root == "actor" else root) / "a.txt")]
    blueprint.write_text(json.dumps(data))
    (actor / "a.txt").write_text("Actor change\n")
    result = gate(root, actor, "validate_mutation_boundary")
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "clean"
    assert report["expected"] == report["actual"] == ["a.txt"]


def test_actor_absolute_escape_does_not_fall_back_to_parent(context):
    root, actor, _ = context
    (root / "outside").mkdir()
    (actor / "link").symlink_to(root / "outside", target_is_directory=True)
    blueprint = root / ".map/actor-plan/blueprint.json"
    data = json.loads(blueprint.read_text())
    data["subtasks"][0]["affected_files"] = [str(actor / "link/file.txt")]
    blueprint.write_text(json.dumps(data))
    result = gate(root, actor, "validate_mutation_boundary")
    assert result.returncode == 1
    assert "escapes checkout" in json.loads(result.stdout)["message"]


@pytest.mark.parametrize("gate_name", ["validate_mutation_boundary", "detect_cross_subtask_regression_risk"])
@pytest.mark.parametrize("damage", ["missing_registry", "bad_json", "wrong_path", "wrong_branch", "duplicate", "bad_base", "missing_base", "unrelated"])
def test_invalid_managed_context_blocks_without_parent_fallback(context, tmp_path, gate_name, damage):
    root, actor, _ = context
    registry = root / ".map/actor-plan/worktrees.json"
    data = json.loads(registry.read_text())
    record = next(iter(data["worktrees"].values()))
    if damage == "missing_registry":
        registry.unlink()
    elif damage == "bad_json":
        registry.write_text("{")
    elif damage == "unrelated":
        other = tmp_path / "other"
        other.mkdir()
        actor = _make_repo(other)
    else:
        if damage == "wrong_path":
            record["path"] = str(root)
        elif damage == "wrong_branch":
            record["branch"] = "another-branch"
        elif damage == "duplicate":
            data["worktrees"]["duplicate"] = record.copy()
        elif damage == "bad_base":
            record["base_sha"] = "--help"
        elif damage == "missing_base":
            record["base_sha"] = "0" * 40
        registry.write_text(json.dumps(data))
    result = gate(root, actor, gate_name)
    assert result.returncode == 1, result.stdout + result.stderr
    assert json.loads(result.stdout)["status"] == "error"


@pytest.mark.parametrize("gate_name", ["validate_mutation_boundary", "detect_cross_subtask_regression_risk"])
@pytest.mark.parametrize("flag", ["--metadata-root", "--worktree"])
def test_single_root_flag_cannot_silently_validate_parent(context, gate_name, flag):
    root, actor, _ = context
    result = subprocess.run(
        [sys.executable, str(root / ".map/scripts/map_step_runner.py"), gate_name,
         "actor-plan", "ST-001", flag, str(root if flag == "--metadata-root" else actor)],
        cwd=root, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1
    assert "supplied together" in json.loads(result.stdout)["message"]


def test_strict_scope_and_base_override(context):
    root, actor, _ = context
    (actor / "leak.txt").write_text("outside scope")
    result = gate(root, actor, "validate_mutation_boundary", env={**os.environ, "MAP_STRICT_SCOPE": "1"})
    assert result.returncode == 1
    assert json.loads(result.stdout)["status"] == "violation"
    override = gate(root, actor, "validate_mutation_boundary", "HEAD")
    assert override.returncode != 0


@pytest.mark.parametrize("provider", ["claude", "codex"])
def test_managed_monitor_instructions_shipped_for_both_providers(provider):
    templates = SCRIPTS_PATH.parent.parent
    monitor = templates / ("agents/monitor.md" if provider == "claude" else "codex/agents/monitor.toml")
    skill = templates / ("skills/map-efficient/SKILL.md" if provider == "claude" else "codex/skills/map-efficient/SKILL.md")
    assert "--metadata-root <parent>" in monitor.read_text()
    assert "--worktree <candidate>" in monitor.read_text()
    assert "monitor_instruction" in skill.read_text()
    assert "For non-isolated execution only" in skill.read_text()
    assert "regression result from `monitor_instruction`" in skill.read_text()
