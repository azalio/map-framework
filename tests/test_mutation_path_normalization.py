"""Real-Git declaration normalization without rewriting literal Git entry paths."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from mapify_cli.delivery.template_renderer import get_environment

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "src/mapify_cli/templates_src"
SCRIPTS = ROOT / "src/mapify_cli/templates/map/scripts"
BRANCH = "mutation-paths"
SUBTASK = "ST-001"


@pytest.fixture
def runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    output = tmp_path / "rendered_runner.py"
    output.write_text(
        get_environment(SOURCES).get_template("map/scripts/map_step_runner.py.jinja").render(
            PROVIDER="claude"
        ), encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("mutation_paths_runner", output)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True, timeout=10,
    ).stdout.strip()


def blueprint_path(repo: Path) -> Path:
    return repo / ".map" / BRANCH / "blueprint.json"


def declare(repo: Path, paths: list[str]) -> dict:
    data = {"metadata": {"untouched": [1, 2]}, "blueprint": {"subtasks": [
        {"id": SUBTASK, "affected_files": paths, "description": "keep me"},
        {"id": "ST-002", "affected_files": ["other.txt"]},
    ]}}
    blueprint_path(repo).write_text(json.dumps(data, indent=4) + "\n", encoding="utf-8")
    return data


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "repository"
    root.mkdir()
    git(root, "init", "-b", BRANCH)
    git(root, "config", "user.name", "Fixture")
    git(root, "config", "user.email", "fixture@example.invalid")
    for name in ("production.py", "tests/test_production.py", "undeclared.py"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("original\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "initial")
    blueprint_path(root).parent.mkdir(parents=True)
    declare(root, [])
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    monkeypatch.setenv("MAP_STRICT_SCOPE", "1")
    return root


def test_absolute_approved_production_and_tests_are_strict_clean(runner, repo):
    names = ["production.py", "tests/test_production.py"]
    declare(repo, [str(repo / name) for name in names])
    for name in names:
        (repo / name).write_text("changed\n")
    report = runner.validate_mutation_boundary(BRANCH, SUBTASK, "HEAD")
    assert report["status"] == "clean"
    assert report["expected"] == sorted(names)
    assert report["actual"] == sorted(names)
    assert report["allowed_test_files"] == []


def test_unchanged_approval_does_not_hide_undeclared_change(runner, repo):
    declare(repo, [str(repo / "production.py")])
    (repo / "undeclared.py").write_text("changed\n")
    report = runner.validate_mutation_boundary(BRANCH, SUBTASK, "HEAD")
    assert report["status"] == "violation"
    assert report["unexpected"] == ["undeclared.py"]
    assert (blueprint_path(repo).parent / "scope-violations.log").exists()


@pytest.mark.parametrize("absolute", [False, True])
@pytest.mark.parametrize("name", [
    " spaced.py ", "line\nbreak.py", "tab\tname.py", "back\\slash.py", "name (literal).py",
])
def test_literal_git_names_survive_validation_and_refresh(runner, repo, name, absolute):
    (repo / name).write_text("new\n")
    declare(repo, [str(repo / name) if absolute else name])
    report = runner.validate_mutation_boundary(BRANCH, SUBTASK, "HEAD")
    assert report["status"] == "clean"
    assert report["expected"] == report["actual"] == [name]
    refreshed = runner.refresh_blueprint_affected_files(BRANCH, SUBTASK)
    assert refreshed["previous"] == refreshed["current"] == [name]


@pytest.mark.parametrize("kind", ["outside", "sibling", "traversal", "absolute_traversal"])
@pytest.mark.parametrize("replace", [False, True])
@pytest.mark.parametrize("dry_run", [False, True])
def test_invalid_declarations_error_and_preserve_blueprint(runner, repo, kind, replace, dry_run):
    invalid = {
        "outside": str(repo.parent / "outside.py"),
        "sibling": str(repo.parent / (repo.name + "-sibling") / "production.py"),
        "traversal": "inside/../production.py",
        "absolute_traversal": str(repo / "inside") + "/../production.py",
    }[kind]
    declare(repo, ["production.py", invalid])
    (repo / "production.py").write_text("changed\n")
    before = blueprint_path(repo).read_bytes()
    checked = runner.validate_mutation_boundary(BRANCH, SUBTASK, "HEAD")
    assert checked["status"] == "error"
    assert "affected_files" in checked["message"]
    assert "expected" not in checked
    refreshed = runner.refresh_blueprint_affected_files(
        BRANCH, SUBTASK, replace=replace, dry_run=dry_run,
    )
    assert refreshed["status"] == "error"
    assert "affected_files" in refreshed["message"]
    assert blueprint_path(repo).read_bytes() == before


def test_supplied_and_canonical_root_aliases(runner, repo, monkeypatch):
    alias = repo.parent / "checkout-alias"
    alias.symlink_to(repo, target_is_directory=True)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(alias))
    declare(repo, [str(alias / "production.py"), str(repo / "production.py")])
    (repo / "production.py").write_text("changed\n")
    report = runner.validate_mutation_boundary(BRANCH, SUBTASK, "HEAD")
    assert report["status"] == "clean"
    assert report["expected"] == ["production.py"]
    refreshed = runner.refresh_blueprint_affected_files(BRANCH, SUBTASK)
    assert refreshed["previous"] == refreshed["current"] == ["production.py"]


def test_unsupplied_absolute_root_alias_is_not_authorization(runner, repo):
    alias = repo.parent / "unsupplied-alias"
    alias.symlink_to(repo, target_is_directory=True)
    declare(repo, [str(alias / "production.py")])
    (repo / "production.py").write_text("changed\n")
    before = blueprint_path(repo).read_bytes()
    assert runner.validate_mutation_boundary(BRANCH, SUBTASK, "HEAD")["status"] == "error"
    assert runner.refresh_blueprint_affected_files(BRANCH, SUBTASK)["status"] == "error"
    assert blueprint_path(repo).read_bytes() == before


def test_leaf_symlink_approves_entry_not_target(runner, repo):
    outside = repo.parent / "outside.py"
    outside.write_text("outside\n")
    (repo / "entry.py").symlink_to(outside)
    declare(repo, [str(repo / "entry.py")])
    report = runner.validate_mutation_boundary(BRANCH, SUBTASK, "HEAD")
    assert report["status"] == "clean"
    assert report["expected"] == report["actual"] == ["entry.py"]
    refreshed = runner.refresh_blueprint_affected_files(BRANCH, SUBTASK)
    assert refreshed["current"] == ["entry.py"]
    assert outside.read_text() == "outside\n"


@pytest.mark.parametrize("external", [False, True])
def test_interior_symlink_never_authorizes_target_alias(runner, repo, external):
    target = repo.parent / "outside" if external else repo / "real"
    target.mkdir()
    (target / "changed.py").write_text("changed\n")
    (repo / "alias").symlink_to(target, target_is_directory=True)
    git(repo, "add", "alias")
    git(repo, "commit", "-m", "symlink entry")
    declare(repo, [str(repo / "alias" / "changed.py")])
    report = runner.validate_mutation_boundary(BRANCH, SUBTASK, "HEAD")
    if external:
        assert report["status"] == "error"
        assert runner.refresh_blueprint_affected_files(BRANCH, SUBTASK)["status"] == "error"
    else:
        assert report["status"] == "violation"
        assert report["expected"] == ["alias/changed.py"]
        assert report["unexpected"] == ["real/changed.py"]


@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize("replace", [False, True])
def test_refresh_keeps_created_paths_consistent(runner, repo, dry_run, replace):
    name = " new\\tfile.py "
    data = declare(repo, [str(repo / name)])
    data["blueprint"]["subtasks"][0]["creates_files"] = [str(repo / name)]
    blueprint_path(repo).write_text(json.dumps(data))
    (repo / name).write_text("created\n")
    before = blueprint_path(repo).read_bytes()
    report = runner.refresh_blueprint_affected_files(
        BRANCH, SUBTASK, dry_run=dry_run, replace=replace,
    )
    assert report["status"] == ("dry_run" if dry_run else "success")
    if dry_run:
        assert blueprint_path(repo).read_bytes() == before
    else:
        refreshed = json.loads(blueprint_path(repo).read_text())
        subtask = refreshed["blueprint"]["subtasks"][0]
        assert subtask["creates_files"] == subtask["affected_files"] == [name]
        contract = runner.validate_blueprint_contract(BRANCH)
        assert not any("creates_files" in str(error) for error in contract["errors"])
        assert runner.refresh_blueprint_affected_files(BRANCH, SUBTASK)["diff"] == {
            "added": [], "removed": [],
        }


@pytest.mark.parametrize("invalid", ["../outside.py", "outside", [17]])
@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize("replace", [False, True])
def test_refresh_rejects_invalid_creates_without_publishing(runner, repo, invalid, dry_run, replace):
    data = declare(repo, [str(repo / "production.py")])
    data["blueprint"]["subtasks"][0]["creates_files"] = (
        [invalid] if invalid == "../outside.py" else invalid
    )
    blueprint_path(repo).write_text(json.dumps(data))
    before = blueprint_path(repo).read_bytes()
    report = runner.refresh_blueprint_affected_files(
        BRANCH, SUBTASK, dry_run=dry_run, replace=replace,
    )
    assert report["status"] == "error"
    assert "creates_files" in report["message"]
    assert blueprint_path(repo).read_bytes() == before


@pytest.mark.parametrize("wrong_root", [False, True])
def test_checkout_root_symlink_before_parent_traversal(runner, repo, monkeypatch, wrong_root):
    (repo / "nested").mkdir()
    alias = repo.parent / "checkout-hop"
    alias.symlink_to(repo / "nested", target_is_directory=True)
    supplied = str(alias) + "/.."
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", supplied)
    declaration_root = repo.parent if wrong_root else repo
    declare(repo, [str(declaration_root / "production.py")])
    (repo / "production.py").write_text("changed\n")
    before = blueprint_path(repo).read_bytes()
    checked = runner.validate_mutation_boundary(BRANCH, SUBTASK, "HEAD")
    refreshed = runner.refresh_blueprint_affected_files(BRANCH, SUBTASK)
    if wrong_root:
        assert checked["status"] == refreshed["status"] == "error"
        assert blueprint_path(repo).read_bytes() == before
    else:
        assert checked["status"] == "clean"
        assert checked["expected"] == ["production.py"]
        assert refreshed["status"] == "success"
        assert refreshed["current"] == ["production.py"]


@pytest.mark.parametrize("dry_run", [False, True])
def test_refresh_normalizes_deduplicates_and_preserves_other_state(runner, repo, dry_run):
    before_data = declare(repo, [
        str(repo / "production.py"), "production.py", "missing/deleted.py",
        str(repo / "missing" / "deleted.py"),
    ])
    (repo / "undeclared.py").write_text("new actor edit\n")
    state = blueprint_path(repo).parent / "step_state.json"
    state.write_text('{"unrelated":true}\n')
    before_state = state.read_bytes()
    before = blueprint_path(repo).read_bytes()
    report = runner.refresh_blueprint_affected_files(BRANCH, SUBTASK, dry_run=dry_run)
    assert report["status"] == ("dry_run" if dry_run else "success")
    assert report["previous"] == ["missing/deleted.py", "production.py"]
    assert report["current"] == ["missing/deleted.py", "production.py", "undeclared.py"]
    assert report["diff"] == {"added": ["undeclared.py"], "removed": []}
    if dry_run:
        assert blueprint_path(repo).read_bytes() == before
    else:
        before_data["blueprint"]["subtasks"][0]["affected_files"] = report["current"]
        assert json.loads(blueprint_path(repo).read_text()) == before_data
    assert state.read_bytes() == before_state
