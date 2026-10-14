"""Real-Git regression checks for resumed subtask mutation attribution."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from mapify_cli.delivery.template_renderer import get_environment

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "src/mapify_cli/templates_src"
SCRIPTS = ROOT / "src/mapify_cli/templates/map/scripts"
BRANCH = "repair-attribution"
SUBTASK = "ST-002"


@pytest.fixture
def runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    output = tmp_path / "rendered_runner.py"
    environment = get_environment(SOURCES)
    output.write_text(
        environment.get_template("map/scripts/map_step_runner.py.jinja").render(
            PROVIDER="claude"
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("repair_attribution_runner", output)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True,
        timeout=10,
    )
    return result.stdout.strip()


def write_state(repo: Path, value: Any) -> None:
    state = {
        "last_subtask_commit_sha": git(repo, "rev-parse", "HEAD"),
        "subtask_results": {SUBTASK: {"commit_sha": git(repo, "rev-parse", "HEAD")}},
        "subtask_diff_bases": value,
    }
    (repo / ".map" / BRANCH / "step_state.json").write_text(json.dumps(state))


@pytest.fixture
def repaired_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str]:
    repo = tmp_path / "repository"
    repo.mkdir()
    git(repo, "init", "-b", BRANCH)
    git(repo, "config", "user.name", "Fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    for path in ("actor.txt", "repair.txt", "existing.txt", "outside.txt"):
        (repo / path).write_text("original\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "H")
    head = git(repo, "rev-parse", "HEAD")
    (repo / "existing.txt").write_text("preexisting dirty\n")
    workspace = repo / ".map" / BRANCH
    (workspace / "subtask-baselines").mkdir(parents=True)
    (workspace / "subtask-baselines" / f"{SUBTASK}.json").write_text(
        json.dumps({"head_sha": head, "files": ["existing.txt"]})
    )
    (workspace / "blueprint.json").write_text(json.dumps({"subtasks": [
        {"id": SUBTASK, "affected_files": ["actor.txt", "new.txt"]},
        {"id": "ST-003", "affected_files": []},
    ]}))
    # Intent: preserve staged and unstaged Actor bytes while committing only repair.
    (repo / "actor.txt").write_text("Actor staged\n")
    git(repo, "add", "actor.txt")
    (repo / "actor.txt").write_text("Actor staged and unstaged\n")
    (repo / "new.txt").write_text("Actor untracked\n")
    (repo / "repair.txt").write_text("repair fixed\n")
    git(repo, "add", "repair.txt")
    # Commit-tree builds R from H without taking the paused Actor index entries.
    repair_blob = git(repo, "hash-object", "repair.txt")
    tree_input = "\n".join(
        line.replace(line.split()[2], repair_blob)
        if line.endswith("\trepair.txt") else line
        for line in git(repo, "ls-tree", head).splitlines()
    ) + "\n"
    tree = subprocess.run(
        ["git", "mktree"], cwd=repo, input=tree_input, capture_output=True,
        text=True, check=True, timeout=10,
    ).stdout.strip()
    repair_commit = git(repo, "commit-tree", tree, "-p", head, "-m", "R")
    git(repo, "update-ref", f"refs/heads/{BRANCH}", repair_commit, head)
    write_state(repo, {SUBTASK: tree})
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    monkeypatch.setenv("MAP_STRICT_SCOPE", "1")
    return repo, tree


def test_adjusted_tree_precedes_own_commit_parent(runner, repaired_repo):
    repo, tree = repaired_repo
    assert runner._resolve_subtask_diff_base(BRANCH, SUBTASK, repo) == tree
    assert runner._resolve_subtask_diff_base(BRANCH, "ST-003", repo) == git(
        repo, "rev-parse", "HEAD"
    )


def test_resumed_surface_retains_actor_omits_repair(runner, repaired_repo):
    repo, _ = repaired_repo
    assert runner._current_subtask_changed_files(BRANCH, SUBTASK, repo) == {
        "actor.txt", "new.txt"
    }
    report = runner.validate_mutation_boundary(BRANCH, SUBTASK)
    assert report["status"] == "clean"
    assert report["actual"] == ["actor.txt", "new.txt"]


def test_later_repair_path_mutation_is_not_hidden(runner, repaired_repo):
    repo, _ = repaired_repo
    (repo / "repair.txt").write_text("later Actor edit\n")
    git(repo, "add", "repair.txt")
    (repo / "outside.txt").write_text("out of scope\n")
    expected = {"actor.txt", "new.txt", "repair.txt", "outside.txt"}
    assert runner._current_subtask_changed_files(BRANCH, SUBTASK, repo) == expected
    report = runner.validate_mutation_boundary(BRANCH, SUBTASK)
    assert report["status"] == "violation"
    assert report["unexpected"] == ["outside.txt", "repair.txt"]


def test_refresh_uses_adjusted_surface_and_persists_only_actor(runner, repaired_repo):
    repo, _ = repaired_repo
    report = runner.refresh_blueprint_affected_files(BRANCH, SUBTASK, replace=True)
    assert report["status"] == "success"
    assert report["current"] == ["actor.txt", "new.txt"]
    blueprint = json.loads((repo / ".map" / BRANCH / "blueprint.json").read_text())
    assert blueprint["subtasks"][0]["affected_files"] == ["actor.txt", "new.txt"]
    (repo / "repair.txt").write_text("later edit\n")
    report = runner.refresh_blueprint_affected_files(BRANCH, SUBTASK, replace=True)
    assert "repair.txt" in report["current"]


@pytest.mark.parametrize("metadata", [None, [], {SUBTASK: ""}, {SUBTASK: 12},
                                      {SUBTASK: "missing-tree"},
                                      {SUBTASK: "f" * 40}])
def test_invalid_adjusted_base_fails_closed(runner, repaired_repo, metadata):
    repo, _ = repaired_repo
    write_state(repo, metadata)
    before = (repo / ".map" / BRANCH / "blueprint.json").read_bytes()
    assert runner._current_subtask_changed_files(BRANCH, SUBTASK, repo) is None
    assert runner.validate_mutation_boundary(BRANCH, SUBTASK)["status"] == "error"
    assert runner.refresh_blueprint_affected_files(BRANCH, SUBTASK)["status"] == "error"
    assert (repo / ".map" / BRANCH / "blueprint.json").read_bytes() == before


def test_missing_legacy_ref_is_unknown_not_clean(runner, repaired_repo):
    repo, _ = repaired_repo
    state_path = repo / ".map" / BRANCH / "step_state.json"
    state_path.write_text(json.dumps({"last_subtask_commit_sha": "missing-ref"}))
    assert runner._current_subtask_changed_files(BRANCH, SUBTASK, repo) is None
    assert runner.validate_mutation_boundary(BRANCH, SUBTASK)["status"] == "error"


@pytest.mark.parametrize("filename", [
    "file with spaces.txt", 'file"quote.txt', "файл.txt", " literal -> name.txt ",
    "file\ttab.txt", "file\nnewline.txt", "file\rcarriage.txt",
])
@pytest.mark.parametrize("adjusted", [True, False])
def test_current_surface_preserves_literal_git_paths(runner, repaired_repo, filename, adjusted):
    repo, _ = repaired_repo
    if not adjusted:
        write_state(repo, {})
    (repo / filename).write_text("Actor untracked\n")
    expected = {"actor.txt", "new.txt", filename}
    if not adjusted:
        expected.add("repair.txt")
    assert runner._current_subtask_changed_files(BRANCH, SUBTASK, repo) == expected
    report = runner.validate_mutation_boundary(BRANCH, SUBTASK)
    assert report["status"] == "violation"
    assert report["unexpected"] == sorted({filename} | ({"repair.txt"} if not adjusted else set()))
    report = runner.refresh_blueprint_affected_files(BRANCH, SUBTASK, replace=True)
    assert report["current"] == sorted(expected)
    blueprint = json.loads((repo / ".map" / BRANCH / "blueprint.json").read_text())
    assert blueprint["subtasks"][0]["affected_files"] == sorted(expected)
    # Also exercise the diff path after this file leaves porcelain entirely.
    git(repo, "add", "--", filename)
    git(repo, "commit", "-m", "Actor file", "--", filename)
    assert runner._current_subtask_changed_files(BRANCH, SUBTASK, repo) == expected


def test_current_surface_preserves_both_rename_endpoints(runner, repaired_repo):
    repo, _ = repaired_repo
    destination = 'renamed "файл -> target.txt'
    git(repo, "mv", "outside.txt", destination)
    expected = {"actor.txt", "new.txt", "outside.txt", destination}
    assert runner._current_subtask_changed_files(BRANCH, SUBTASK, repo) == expected
    report = runner.validate_mutation_boundary(BRANCH, SUBTASK)
    assert report["unexpected"] == sorted({"outside.txt", destination})
    report = runner.refresh_blueprint_affected_files(BRANCH, SUBTASK, replace=True)
    assert report["current"] == sorted(expected)


@pytest.mark.parametrize("record", ["record_subtask_baseline", "record_scope_baseline"])
def test_baselines_preserve_literal_paths(runner, repaired_repo, record):
    repo, _ = repaired_repo
    filename = 'preexisting "файл\n -> file.txt '
    (repo / filename).write_text("preexisting\n")
    recorder = getattr(runner, record)
    report = recorder(BRANCH, SUBTASK) if record == "record_subtask_baseline" else recorder(BRANCH)
    baseline = json.loads(Path(report["path"]).read_text())
    assert filename in baseline["files"]
    assert filename not in runner.validate_mutation_boundary(BRANCH, SUBTASK)["actual"]


def test_absent_adjustment_preserves_legacy_parent_fallback(runner, repaired_repo):
    repo, _ = repaired_repo
    write_state(repo, {})
    # Without adjustment the existing own-commit-parent behavior includes repair.
    assert "repair.txt" in runner._current_subtask_changed_files(BRANCH, SUBTASK, repo)
    assert runner._resolve_subtask_diff_base(BRANCH, SUBTASK, repo).endswith("^")
