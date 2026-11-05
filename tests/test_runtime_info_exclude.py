"""Runtime ignore block lives in .git/info/exclude for git repos (#634)."""

import subprocess
from pathlib import Path

import pytest

from mapify_cli.delivery.file_copier import (
    _UPDATE_RUNTIME_GITIGNORE_PATHS,
    merge_update_runtime_gitignore,
)

MARKER = "# map:update-runtime"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True)


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")


def test_git_repo_writes_runtime_block_to_exclude_not_gitignore(
    tmp_path: Path,
) -> None:
    _init_repo(tmp_path)
    (tmp_path / ".gitignore").write_text("custom/\n")
    tracked_before = (tmp_path / ".gitignore").read_bytes()

    assert merge_update_runtime_gitignore(tmp_path, settings_local=True) == 1

    assert "map:update-runtime" not in (tmp_path / ".gitignore").read_text()
    gitignore_lines = (tmp_path / ".gitignore").read_text().splitlines()
    assert not set(_UPDATE_RUNTIME_GITIGNORE_PATHS) & set(gitignore_lines)
    exclude = (tmp_path / ".git" / "info" / "exclude").read_text().splitlines()
    assert any(MARKER in line for line in exclude)
    for path in _UPDATE_RUNTIME_GITIGNORE_PATHS:
        assert exclude.count(path) == 1
    # Privacy blocks stay in the tracked .gitignore (repo policy).
    assert ".claude/settings.local.json" in gitignore_lines
    assert (tmp_path / ".gitignore").read_bytes() != tracked_before


def test_runtime_only_leaves_gitignore_untouched(tmp_path: Path) -> None:
    _init_repo(tmp_path)

    assert merge_update_runtime_gitignore(tmp_path) == 1

    assert not (tmp_path / ".gitignore").exists()
    assert _git(tmp_path, "status", "--porcelain") == ""


def test_exclude_is_effective_for_git(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    merge_update_runtime_gitignore(tmp_path)
    for rel in (".map/update.lock", ".claude/worktrees/map/x/f.py"):
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x")
        assert _git(tmp_path, "check-ignore", "-q", rel) == ""


def test_idempotent(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    merge_update_runtime_gitignore(tmp_path)
    exclude = tmp_path / ".git" / "info" / "exclude"
    first = exclude.read_bytes()

    assert merge_update_runtime_gitignore(tmp_path) == 0
    assert exclude.read_bytes() == first


def test_preserves_existing_exclude_content_and_adds_only_missing(
    tmp_path: Path,
) -> None:
    _init_repo(tmp_path)
    exclude = tmp_path / ".git" / "info" / "exclude"
    exclude.parent.mkdir(exist_ok=True)
    exclude.write_text("# mine\nscratch/\n.map/update.lock\n")

    merge_update_runtime_gitignore(tmp_path)

    lines = exclude.read_text().splitlines()
    assert lines[:2] == ["# mine", "scratch/"]
    assert lines.count(".map/update.lock") == 1
    assert ".map/update-state.json" in lines


def test_non_git_directory_falls_back_to_gitignore(tmp_path: Path) -> None:
    assert merge_update_runtime_gitignore(tmp_path) == 1

    lines = (tmp_path / ".gitignore").read_text().splitlines()
    for path in _UPDATE_RUNTIME_GITIGNORE_PATHS:
        assert path in lines


def test_subdirectory_of_repo_falls_back_to_gitignore(tmp_path: Path) -> None:
    # info/exclude patterns anchor at the repo root, so a nested project root
    # cannot use them.
    _init_repo(tmp_path)
    nested = tmp_path / "pkg"
    nested.mkdir()

    merge_update_runtime_gitignore(nested)

    assert (nested / ".gitignore").is_file()
    exclude = tmp_path / ".git" / "info" / "exclude"
    assert not exclude.exists() or MARKER not in exclude.read_text()


def test_linked_worktree_uses_common_dir(tmp_path: Path) -> None:
    main = tmp_path / "main"
    _init_repo(main)
    _git(main, "-c", "user.name=t", "-c", "user.email=t@t", "commit",
         "--allow-empty", "-q", "-m", "init")
    linked = tmp_path / "linked"
    _git(main, "worktree", "add", "-q", str(linked), "-b", "side")

    merge_update_runtime_gitignore(linked)

    assert not (linked / ".gitignore").exists()
    exclude = main / ".git" / "info" / "exclude"
    assert ".map/update.lock" in exclude.read_text().splitlines()
    assert _git(linked, "status", "--porcelain") == ""


def test_existing_gitignore_block_means_nothing_written(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    block = f"{MARKER} — local MAP runtime state; never commit.\n" + "".join(
        f"{p}\n" for p in _UPDATE_RUNTIME_GITIGNORE_PATHS
    )
    (tmp_path / ".gitignore").write_text(block)

    assert merge_update_runtime_gitignore(tmp_path) == 0

    assert (tmp_path / ".gitignore").read_text() == block
    exclude = tmp_path / ".git" / "info" / "exclude"
    assert not exclude.exists() or MARKER not in exclude.read_text()


def test_partial_gitignore_block_only_missing_paths_go_to_exclude(
    tmp_path: Path,
) -> None:
    _init_repo(tmp_path)
    (tmp_path / ".gitignore").write_text(".map/update.lock\n")

    merge_update_runtime_gitignore(tmp_path)

    assert (tmp_path / ".gitignore").read_text() == ".map/update.lock\n"
    exclude = (tmp_path / ".git" / "info" / "exclude").read_text().splitlines()
    assert ".map/update.lock" not in exclude
    assert ".map/update-state.json" in exclude


def test_gitignore_negation_defeats_exclude_so_gitignore_is_repaired(
    tmp_path: Path,
) -> None:
    # .gitignore outranks info/exclude, so a negation there needs a
    # .gitignore-level repair for the path to stay ignored.
    _init_repo(tmp_path)
    (tmp_path / ".gitignore").write_text("!.map/**\n")
    rel = ".map/update.lock"
    (tmp_path / ".map").mkdir()
    (tmp_path / rel).write_text("x")

    merge_update_runtime_gitignore(tmp_path)

    assert _git(tmp_path, "check-ignore", "-q", rel) == ""


def test_symlinked_exclude_is_rejected(tmp_path: Path) -> None:
    from mapify_cli.delivery.file_copier import UpdateRuntimeGitignoreSecurityError

    _init_repo(tmp_path)
    info = tmp_path / ".git" / "info"
    info.mkdir(exist_ok=True)
    victim = tmp_path / "victim.txt"
    victim.write_text("keep\n")
    exclude = info / "exclude"
    if exclude.exists() or exclude.is_symlink():
        exclude.unlink()
    exclude.symlink_to(victim)

    with pytest.raises(UpdateRuntimeGitignoreSecurityError):
        merge_update_runtime_gitignore(tmp_path)
    assert victim.read_text() == "keep\n"
