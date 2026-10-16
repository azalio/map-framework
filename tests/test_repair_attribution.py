"""Real-Git regression checks for resumed subtask mutation attribution."""

import importlib.util
import json
import os
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
def repaired_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runner) -> tuple[Path, str]:
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
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    baseline = runner.record_subtask_baseline(BRANCH, SUBTASK)
    assert baseline["status"] == "success", baseline
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
    if record == "record_scope_baseline":
        # Exercise scope fallback rather than the fixture's authoritative subtask boundary.
        (repo / ".map" / BRANCH / "subtask-baselines" / f"{SUBTASK}.json").unlink()
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


@pytest.mark.parametrize("record", ["record_subtask_baseline", "record_scope_baseline"])
def test_failed_baseline_publication_preserves_previous_evidence(
    runner, repaired_repo, monkeypatch, record,
):
    repo, _ = repaired_repo
    recorder = getattr(runner, record)
    args = (BRANCH, SUBTASK) if record == "record_subtask_baseline" else (BRANCH,)
    report = recorder(*args)
    assert report["status"] == "success", report
    path = Path(report["path"])
    original = path.read_bytes()
    (repo / "existing.txt").write_text("Actor changed after baseline\n")
    original_replace = Path.replace

    def fail_publish(source, target):
        if Path(target) == path:
            raise OSError("injected baseline publication failure")
        return original_replace(source, target)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "replace", fail_publish)
        with pytest.raises(OSError, match="injected baseline publication failure"):
            recorder(*args)
    assert path.read_bytes() == original
    assert not list(path.parent.glob(f".{path.name}.*.tmp"))
    report = runner.detect_actor_files_changed_mismatch(BRANCH, SUBTASK, ["existing.txt"])
    assert report["declared_not_written"] == [], report


@pytest.fixture(params=[False, True], ids=["ordinary", "repair-adjusted"])
def dirty_baseline_repo(runner, repaired_repo, request):
    repo, _ = repaired_repo
    if not request.param:
        (repo / ".map" / BRANCH / "step_state.json").write_text(json.dumps({
            "last_subtask_commit_sha": git(repo, "rev-parse", "HEAD"),
            "subtask_results": {},
        }))
    (repo / "outside.txt").write_text("unchanged baseline control\n")
    report = runner.record_subtask_baseline(BRANCH, SUBTASK)
    assert report["status"] == "success", report
    baseline = json.loads(Path(report["path"]).read_text())
    assert {"existing.txt", "outside.txt"} <= set(baseline["files"])
    return repo


def test_rewritten_dirty_baseline_declared_file_is_written(runner, dirty_baseline_repo):
    (dirty_baseline_repo / "existing.txt").write_text("Actor retry rewrite\n")
    report = runner.detect_actor_files_changed_mismatch(BRANCH, SUBTASK, ["existing.txt"])
    assert report["declared_not_written"] == [], report
    assert report["status_mismatch"] is False, report
    assert "existing.txt" in report["actual"], report


def test_rewritten_dirty_baseline_is_mutation_boundary_violation(runner, dirty_baseline_repo):
    (dirty_baseline_repo / "existing.txt").write_text("Actor retry rewrite\n")
    report = runner.validate_mutation_boundary(BRANCH, SUBTASK)
    assert "existing.txt" in report["actual"], report
    assert "existing.txt" in report["unexpected"], report
    assert report["status"] == "violation", report


def test_rewritten_dirty_baseline_unchanged_control_is_excluded(runner, dirty_baseline_repo):
    current = runner._current_subtask_changed_files(BRANCH, SUBTASK, dirty_baseline_repo)
    assert current is not None
    assert "existing.txt" not in current
    assert "outside.txt" not in current
    report = runner.validate_mutation_boundary(BRANCH, SUBTASK)
    assert "existing.txt" not in report["actual"], report
    assert "outside.txt" not in report["actual"], report


def test_baseline_attribution_survives_fresh_process(runner, repaired_repo):
    repo, _ = repaired_repo
    script = Path(runner.__file__)
    env = {**os.environ, "PYTHONPATH": str(SCRIPTS), "PYTHONDONTWRITEBYTECODE": "1"}
    capture = subprocess.run(
        [sys.executable, str(script), "record_subtask_baseline", BRANCH, SUBTASK],
        cwd=repo, env=env, capture_output=True, text=True, timeout=20, check=True,
    )
    assert json.loads(capture.stdout)["status"] == "success"
    (repo / "existing.txt").write_text("rewrite between independent processes\n")
    verify = subprocess.run(
        [sys.executable, str(script), "detect_actor_files_changed_mismatch", BRANCH,
         SUBTASK, "--declared", "existing.txt"],
        cwd=repo, env=env, capture_output=True, text=True, timeout=20, check=True,
    )
    report = json.loads(verify.stdout)
    assert report["declared_not_written"] == [], report


@pytest.mark.parametrize("payload", ["{", "null", "[]", '"not-an-object"',
                                      '{"files":null}', '{"files":[12]}',
                                      '{"files":["existing.txt"],"evidence_version":1,"path_evidence":[]}'])
def test_malformed_baseline_cannot_crash_or_hide_dirty_path(runner, repaired_repo, payload):
    repo, _ = repaired_repo
    (repo / ".map" / BRANCH / "subtask-baselines" / f"{SUBTASK}.json").write_text(payload)
    report = runner.detect_actor_files_changed_mismatch(BRANCH, SUBTASK, ["existing.txt"])
    assert report["declared_not_written"] == [], report
    assert report["status_mismatch"] is False, report


@pytest.mark.parametrize("bad_type", [[], {}])
@pytest.mark.parametrize("consumer", ["detector", "boundary", "refresh"])
def test_nested_malformed_evidence_cannot_crash_or_hide_dirty_path(
    runner, repaired_repo, bad_type, consumer
):
    repo, _ = repaired_repo
    path = repo / ".map" / BRANCH / "subtask-baselines" / f"{SUBTASK}.json"
    baseline = json.loads(path.read_text())
    baseline["path_evidence"]["existing.txt"]["worktree"]["type"] = bad_type
    path.write_text(json.dumps(baseline))
    if consumer == "detector":
        report = runner.detect_actor_files_changed_mismatch(BRANCH, SUBTASK, ["existing.txt"])
        assert report["declared_not_written"] == [], report
    elif consumer == "boundary":
        report = runner.validate_mutation_boundary(BRANCH, SUBTASK)
        assert "existing.txt" in report["unexpected"], report
    else:
        report = runner.refresh_blueprint_affected_files(BRANCH, SUBTASK, replace=True)
        assert "existing.txt" in report["current"], report


def test_work_dir_evidence_not_main_checkout_controls_attribution(runner, repaired_repo, tmp_path):
    repo, _ = repaired_repo
    worktree = tmp_path / "actor-worktree"
    git(repo, "worktree", "add", "--detach", str(worktree), "HEAD")
    # Main's dirty baseline is unchanged; only Actor's selected checkout rewrites it.
    (worktree / "existing.txt").write_text("Actor worktree rewrite\n")
    current = runner._current_subtask_changed_files(BRANCH, SUBTASK, repo, work_dir=worktree)
    assert current is not None
    assert "existing.txt" in current


@pytest.mark.parametrize("rewritten", [False, True], ids=["unwritten", "written"])
def test_active_worktree_does_not_inherit_main_baseline_evidence(
    runner, repaired_repo, tmp_path, baseline_producer, rewritten
):
    repo, _ = repaired_repo
    record_baseline(runner, repo, baseline_producer)
    worktree = tmp_path / "actor-worktree"
    git(repo, "worktree", "add", "--detach", str(worktree), "HEAD")
    (repo / ".map" / BRANCH / "worktrees.json").write_text(json.dumps({
        "worktrees": {SUBTASK: {"subtask_id": SUBTASK, "path": str(worktree)}},
    }))
    if rewritten:
        (worktree / "existing.txt").write_text("Actor worktree rewrite\n")
    # Internal files remain excluded even on the separate-checkout path.
    (worktree / ".map").mkdir()
    (worktree / ".map" / "internal.txt").write_text("internal artifact\n")
    expected = {"existing.txt"} if rewritten else set()
    report = runner.detect_actor_files_changed_mismatch(BRANCH, SUBTASK, ["existing.txt"])
    assert report["checked_in"] == "worktree", report
    assert report["declared_not_written"] == ([] if rewritten else ["existing.txt"]), report
    assert report["status_mismatch"] is (not rewritten), report
    assert report["actual"] == sorted(expected), report
    assert runner._current_subtask_changed_files(
        BRANCH, SUBTASK, repo, work_dir=worktree,
    ) == expected


def test_same_checkout_work_dir_alias_still_reconciles_baseline(
    runner, repaired_repo, tmp_path, baseline_producer
):
    repo, _ = repaired_repo
    record_baseline(runner, repo, baseline_producer)
    alias = tmp_path / "repository-link"
    alias.symlink_to(repo, target_is_directory=True)
    assert runner._current_subtask_changed_files(BRANCH, SUBTASK, repo, work_dir=alias) == set()
    (repo / "existing.txt").write_text("Actor later rewrite\n")
    assert runner._current_subtask_changed_files(
        BRANCH, SUBTASK, repo, work_dir=alias,
    ) == {"existing.txt"}


@pytest.fixture(params=["subtask", "scope"])
def baseline_producer(request):
    return request.param


def record_baseline(runner, repo: Path, producer: str):
    if producer == "scope":
        # Scope-only tests must not inherit the fixture's legacy subtask filter.
        (repo / ".map" / BRANCH / "subtask-baselines" / f"{SUBTASK}.json").unlink(
            missing_ok=True
        )
        report = runner.record_scope_baseline(BRANCH)
    else:
        report = runner.record_subtask_baseline(BRANCH, SUBTASK)
    assert report["status"] == "success", report


@pytest.mark.parametrize("consumer", ["detector", "boundary", "refresh"])
@pytest.mark.parametrize("transition", [
    "unstaged", "staged_only", "reverted_to_head", "deleted", "recreated",
    "file_to_symlink", "symlink_target", "executable_mode", "committed",
    "untracked_to_staged",
])
def test_dirty_baseline_transitions_remain_visible(
    runner, repaired_repo, baseline_producer, consumer, transition
):
    repo, _ = repaired_repo
    path = repo / "existing.txt"
    if transition == "untracked_to_staged":
        path = repo / "previously-untracked.txt"
        path.write_text("same bytes before and after staging\n")
    elif transition == "recreated":
        path.unlink()
    elif transition == "symlink_target":
        path.unlink()
        path.symlink_to("baseline-target")
    record_baseline(runner, repo, baseline_producer)

    if transition == "untracked_to_staged":
        git(repo, "add", path.name)
    elif transition == "staged_only":
        baseline_bytes = path.read_bytes()
        path.write_text("Actor index-only rewrite\n")
        git(repo, "add", "existing.txt")
        path.write_bytes(baseline_bytes)
    elif transition == "reverted_to_head":
        path.write_text("original\n")
        assert "existing.txt" not in git(repo, "status", "--porcelain")
    elif transition == "deleted":
        path.unlink()
    elif transition in {"file_to_symlink", "symlink_target"}:
        path.unlink()
        path.symlink_to("Actor-target")
    elif transition == "executable_mode":
        git(repo, "config", "core.filemode", "true")
        path.chmod(path.stat().st_mode | 0o111)
    else:
        path.write_text("Actor rewritten or recreated\n")
        if transition == "committed":
            git(repo, "add", "existing.txt")
            git(repo, "commit", "-m", "Actor rewrite", "--", "existing.txt")

    if consumer == "detector":
        report = runner.detect_actor_files_changed_mismatch(BRANCH, SUBTASK, [path.name])
        assert report["declared_not_written"] == [], report
        assert report["status_mismatch"] is False, report
        assert path.name in report["actual"], report
    elif consumer == "boundary":
        report = runner.validate_mutation_boundary(BRANCH, SUBTASK)
        assert path.name in report["actual"], report
        assert path.name in report["unexpected"], report
        assert report["status"] == "violation", report
    else:
        report = runner.refresh_blueprint_affected_files(BRANCH, SUBTASK, replace=True)
        assert report["status"] == "success", report
        assert path.name in report["current"], report
        blueprint = json.loads((repo / ".map" / BRANCH / "blueprint.json").read_text())
        assert path.name in blueprint["subtasks"][0]["affected_files"]


@pytest.mark.parametrize("consumer", ["surface", "boundary", "refresh"])
def test_public_baseline_unchanged_path_is_excluded(
    runner, repaired_repo, baseline_producer, consumer
):
    repo, _ = repaired_repo
    record_baseline(runner, repo, baseline_producer)
    if consumer == "surface":
        current = runner._current_subtask_changed_files(BRANCH, SUBTASK, repo)
        assert current is not None
        assert "existing.txt" not in current
    elif consumer == "boundary":
        report = runner.validate_mutation_boundary(BRANCH, SUBTASK)
        assert "existing.txt" not in report["actual"], report
    else:
        report = runner.refresh_blueprint_affected_files(BRANCH, SUBTASK, replace=True)
        assert "existing.txt" not in report["current"], report


@pytest.mark.parametrize("consumer", ["surface", "boundary", "refresh"])
def test_symlinked_project_root_certifies_unchanged_dirty_baseline(
    runner, repaired_repo, baseline_producer, consumer, monkeypatch, tmp_path
):
    repo, _ = repaired_repo
    alias = tmp_path / "repository-link"
    alias.symlink_to(repo, target_is_directory=True)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(alias))
    record_baseline(runner, repo, baseline_producer)

    def actual_paths():
        if consumer == "surface":
            current = runner._current_subtask_changed_files(BRANCH, SUBTASK, alias)
            assert current is not None
            return current
        if consumer == "boundary":
            report = runner.validate_mutation_boundary(BRANCH, SUBTASK)
            assert report["status"] == "clean", report
            return report["actual"]
        report = runner.refresh_blueprint_affected_files(BRANCH, SUBTASK, replace=True)
        assert report["status"] == "success", report
        return report["current"]

    assert "existing.txt" not in actual_paths()
    # Resolving the trusted root must not suppress real later rewrites.
    (repo / "existing.txt").write_text("Actor rewrite through aliased project root\n")
    current = runner._current_subtask_changed_files(BRANCH, SUBTASK, alias)
    assert current is not None
    assert "existing.txt" in current


def test_symlinked_project_root_still_rejects_symlink_ancestor(runner, tmp_path):
    repo = tmp_path / "repository"
    repo.mkdir()
    alias = tmp_path / "repository-link"
    alias.symlink_to(repo, target_is_directory=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "file.txt").write_text("must not follow this ancestor\n")
    (repo / "linked-directory").symlink_to(outside, target_is_directory=True)
    assert runner._baseline_worktree_evidence(alias, "linked-directory/file.txt") is None


def test_symlinked_project_root_hashes_leaf_link_not_target(runner, tmp_path):
    repo = tmp_path / "repository"
    repo.mkdir()
    alias = tmp_path / "repository-link"
    alias.symlink_to(repo, target_is_directory=True)
    target = tmp_path / "outside.txt"
    target.write_text("initial target content\n")
    (repo / "link.txt").symlink_to(target)
    before = runner._baseline_worktree_evidence(alias, "link.txt")
    assert before is not None
    assert before["type"] == "symlink"
    target.write_text("changed target content must not affect evidence\n")
    assert runner._baseline_worktree_evidence(alias, "link.txt") == before


@pytest.mark.parametrize("path", ["../outside.txt", ".git/config", ".env", "credentials.json"])
def test_symlinked_project_root_preserves_path_exclusions(runner, tmp_path, path):
    repo = tmp_path / "repository"
    repo.mkdir()
    alias = tmp_path / "repository-link"
    alias.symlink_to(repo, target_is_directory=True)
    assert runner._baseline_worktree_evidence(alias, path) is None


def test_symlinked_project_root_rejects_special_file(runner, tmp_path):
    repo = tmp_path / "repository"
    repo.mkdir()
    alias = tmp_path / "repository-link"
    alias.symlink_to(repo, target_is_directory=True)
    os.mkfifo(repo / "pipe")
    assert runner._baseline_worktree_evidence(alias, "pipe") is None


@pytest.mark.parametrize("committed", [False, True], ids=["dirty-prior-work", "committed-prior-work"])
@pytest.mark.parametrize("consumer", ["surface", "boundary", "refresh"])
def test_current_subtask_baseline_excludes_untouched_prior_subtask_work(
    runner, repaired_repo, committed, consumer
):
    repo, _ = repaired_repo
    git(repo, "add", "actor.txt", "new.txt", "existing.txt")
    git(repo, "commit", "-m", "Complete fixture work")
    path = repo / "existing.txt"
    path.write_text("dirty before ST-001\n")
    scope = runner.record_scope_baseline(BRANCH)
    assert scope["status"] == "success", scope
    scope_path = Path(scope["path"])
    frozen_scope = scope_path.read_bytes()
    path.write_text("ST-001 work\n")
    if committed:
        git(repo, "add", "existing.txt")
        git(repo, "commit", "-m", "ST-001")
    (repo / ".map" / BRANCH / "step_state.json").write_text(json.dumps({
        "last_subtask_commit_sha": git(repo, "rev-parse", "HEAD"),
        "subtask_results": {},
    }))
    baseline = runner.record_subtask_baseline(BRANCH, SUBTASK)
    assert baseline["status"] == "success", baseline
    # Selection is by artifact existence, not an untrusted JSON identity field.
    baseline_path = Path(baseline["path"])
    payload = json.loads(baseline_path.read_text())
    payload.pop("subtask_id")
    baseline_path.write_text(json.dumps(payload))
    if consumer == "surface":
        assert runner._current_subtask_changed_files(BRANCH, SUBTASK, repo) == set()
    elif consumer == "boundary":
        report = runner.validate_mutation_boundary(BRANCH, SUBTASK)
        assert report["actual"] == [], report
        assert report["status"] == "clean", report
    else:
        report = runner.refresh_blueprint_affected_files(BRANCH, SUBTASK, replace=True)
        assert report["current"] == [], report
    assert scope_path.read_bytes() == frozen_scope


@pytest.mark.parametrize("subtask_payload", ["{", "null", "[]", '{"files":["existing.txt"]}'])
def test_existing_invalid_subtask_baseline_never_falls_back_to_scope(
    runner, repaired_repo, subtask_payload
):
    repo, _ = repaired_repo
    report = runner.record_scope_baseline(BRANCH)
    assert report["status"] == "success", report
    (repo / ".map" / BRANCH / "subtask-baselines" / f"{SUBTASK}.json").write_text(
        subtask_payload
    )
    current = runner._current_subtask_changed_files(BRANCH, SUBTASK, repo)
    assert current is not None
    assert "existing.txt" in current


@pytest.mark.parametrize("consumer", ["surface", "detector", "boundary", "refresh"])
def test_inherited_alternate_index_cannot_hide_actor_staged_only_mutation(
    runner, repaired_repo, baseline_producer, consumer, monkeypatch, tmp_path
):
    repo, _ = repaired_repo
    alternate_index = tmp_path / "alternate-index"
    alternate_index.write_bytes((repo / ".git" / "index").read_bytes())
    with monkeypatch.context() as patch:
        patch.setenv("GIT_INDEX_FILE", str(alternate_index))
        record_baseline(runner, repo, baseline_producer)
    path = repo / "existing.txt"
    original = path.read_bytes()
    path.write_text("Actor stage-only mutation\n")
    git(repo, "add", "existing.txt")
    path.write_bytes(original)
    monkeypatch.setenv("GIT_INDEX_FILE", str(alternate_index))
    if consumer == "surface":
        current = runner._current_subtask_changed_files(BRANCH, SUBTASK, repo)
        assert current is not None
        assert "existing.txt" in current
    elif consumer == "detector":
        report = runner.detect_actor_files_changed_mismatch(BRANCH, SUBTASK, ["existing.txt"])
        assert report["declared_not_written"] == [], report
        assert "existing.txt" in report["actual"], report
    elif consumer == "boundary":
        report = runner.validate_mutation_boundary(BRANCH, SUBTASK)
        assert "existing.txt" in report["unexpected"], report
    else:
        report = runner.refresh_blueprint_affected_files(BRANCH, SUBTASK, replace=True)
        assert "existing.txt" in report["current"], report


@pytest.mark.parametrize("consumer", ["surface", "detector", "boundary", "refresh"])
def test_inherited_repository_routing_cannot_redirect_attribution(
    runner, repaired_repo, baseline_producer, consumer, monkeypatch, tmp_path
):
    repo, _ = repaired_repo
    other = tmp_path / "other-repository"
    git(repo, "clone", "--quiet", str(repo), str(other))
    git(other, "config", "user.name", "Foreign fixture")
    git(other, "config", "user.email", "foreign@example.invalid")
    (other / "foreign-only.txt").write_text("different foreign HEAD\n")
    git(other, "add", "foreign-only.txt")
    git(other, "commit", "-m", "Foreign HEAD")
    intended_head = git(repo, "rev-parse", "HEAD")
    write_state(repo, {})
    with monkeypatch.context() as patch:
        patch.setenv("GIT_DIR", str(other / ".git"))
        patch.setenv("GIT_WORK_TREE", str(other))
        record_baseline(runner, repo, baseline_producer)
    baseline_path = (repo / ".map" / BRANCH / "scope-baseline.json" if baseline_producer == "scope"
                     else repo / ".map" / BRANCH / "subtask-baselines" / f"{SUBTASK}.json")
    baseline = json.loads(baseline_path.read_text())
    assert "existing.txt" in baseline["files"]
    if baseline_producer == "subtask":
        assert baseline["head_sha"] == intended_head
    (repo / "existing.txt").write_text("Actor local rewrite\n")
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))
    if consumer == "surface":
        current = runner._current_subtask_changed_files(BRANCH, SUBTASK, repo)
        assert current is not None
        assert "existing.txt" in current
    elif consumer == "detector":
        report = runner.detect_actor_files_changed_mismatch(BRANCH, SUBTASK, ["existing.txt"])
        assert report["status"] == "ok", report
        assert report["declared_not_written"] == [], report
    elif consumer == "boundary":
        report = runner.validate_mutation_boundary(BRANCH, SUBTASK)
        assert "existing.txt" in report["unexpected"], report
    else:
        report = runner.refresh_blueprint_affected_files(BRANCH, SUBTASK, replace=True)
        assert "existing.txt" in report["current"], report


def test_foreign_head_cannot_supply_unborn_checkout_diff_base(
    runner, repaired_repo, tmp_path, monkeypatch
):
    foreign, _ = repaired_repo
    unborn = tmp_path / "unborn-repository"
    unborn.mkdir()
    git(unborn, "init", "-b", "unborn")
    monkeypatch.setenv("GIT_DIR", str(foreign / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(foreign))
    assert runner._resolve_subtask_diff_base(BRANCH, SUBTASK, unborn) is None
    assert runner._current_subtask_changed_files(BRANCH, SUBTASK, unborn) == set()


def test_attribution_git_env_preserves_user_settings(runner, monkeypatch):
    blocked = {
        "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE",
        "GIT_PREFIX", "GIT_CEILING_DIRECTORIES", "GIT_DISCOVERY_ACROSS_FILESYSTEM",
        "GIT_IMPLICIT_WORK_TREE", "GIT_SHALLOW_FILE", "GIT_GRAFT_FILE",
    }
    for name in blocked:
        monkeypatch.setenv(name, "foreign-routing")
    preserved = {"GIT_CONFIG_GLOBAL": "/fixture/user-gitconfig", "GIT_TRACE": "0",
                 "MAP_ENV_FIXTURE": "unrelated-setting"}
    for name, value in preserved.items():
        monkeypatch.setenv(name, value)
    environment = runner._attribution_git_env()
    assert blocked.isdisjoint(environment)
    assert all(environment[name] == value for name, value in preserved.items())
    assert all(os.environ[name] == "foreign-routing" for name in blocked)


def test_missing_subtask_baseline_uses_scope_without_refresh(runner, repaired_repo):
    repo, _ = repaired_repo
    record_baseline(runner, repo, "scope")
    scope_path = repo / ".map" / BRANCH / "scope-baseline.json"
    frozen_scope = scope_path.read_bytes()
    assert runner._current_subtask_changed_files(BRANCH, SUBTASK, repo) == set()
    (repo / "existing.txt").write_text("Actor rewrite after scope-only capture\n")
    assert runner._current_subtask_changed_files(BRANCH, SUBTASK, repo) == {"existing.txt"}
    assert scope_path.read_bytes() == frozen_scope


@pytest.mark.parametrize("consumer", ["surface", "boundary", "refresh"])
def test_older_scope_baseline_cannot_hide_rewrite_since_subtask(runner, repaired_repo, consumer):
    repo, _ = repaired_repo
    path = repo / "existing.txt"
    older_bytes = path.read_bytes()
    report = runner.record_scope_baseline(BRANCH)
    assert report["status"] == "success", report
    path.write_text("newer subtask starting bytes\n")
    report = runner.record_subtask_baseline(BRANCH, SUBTASK)
    assert report["status"] == "success", report
    path.write_bytes(older_bytes)
    if consumer == "surface":
        current = runner._current_subtask_changed_files(BRANCH, SUBTASK, repo)
        assert current is not None
        assert "existing.txt" in current
    elif consumer == "boundary":
        report = runner.validate_mutation_boundary(BRANCH, SUBTASK)
        assert "existing.txt" in report["unexpected"], report
    else:
        report = runner.refresh_blueprint_affected_files(BRANCH, SUBTASK, replace=True)
        assert "existing.txt" in report["current"], report


@pytest.mark.parametrize("consumer", ["surface", "boundary", "refresh"])
@pytest.mark.parametrize("producer", ["subtask", "scope"])
def test_legacy_path_only_baseline_cannot_suppress_dirty_evidence(
    runner, repaired_repo, producer, consumer
):
    repo, _ = repaired_repo
    workspace = repo / ".map" / BRANCH
    subtask_path = workspace / "subtask-baselines" / f"{SUBTASK}.json"
    if producer == "scope":
        subtask_path.unlink()
        legacy_path = workspace / "scope-baseline.json"
    else:
        legacy_path = subtask_path
    legacy_path.write_text(json.dumps({"files": ["existing.txt"]}))
    if consumer == "surface":
        current = runner._current_subtask_changed_files(BRANCH, SUBTASK, repo)
        assert current is not None
        assert "existing.txt" in current
    elif consumer == "boundary":
        report = runner.validate_mutation_boundary(BRANCH, SUBTASK)
        assert "existing.txt" in report["unexpected"], report
    else:
        report = runner.refresh_blueprint_affected_files(BRANCH, SUBTASK, replace=True)
        assert "existing.txt" in report["current"], report
