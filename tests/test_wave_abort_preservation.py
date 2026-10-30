"""Real-Git regressions for lossless wave refusal and abort."""

import os
import subprocess
from pathlib import Path

import pytest

from tests.test_worktree_isolation import _enable, _git, _make_repo, m


@pytest.fixture
def wave_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = _make_repo(tmp_path)
    _enable(root)
    config = root / ".map/config.yaml"
    config.write_text(config.read_text() + "execution.max_actors: 2\n")
    runtime = root / ".map/feat-x/handoff.json"
    runtime.parent.mkdir()
    runtime.write_text("original runtime\n")
    assert _git(["add", ".map"], root).returncode == 0
    assert _git(["commit", "-qm", "runtime baseline"], root).returncode == 0
    monkeypatch.chdir(root)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.delenv("MAP_EFFICIENT_SEQUENTIAL_ONLY", raising=False)
    return root


def group(ids: list[str]) -> tuple[str, dict[str, Path]]:
    paths = {}
    for sid in ids:
        result = m.create_subtask_worktree(sid)
        assert result["ok"], result
        paths[sid] = Path(result["worktree_path"])
    result = m.begin_wave_group(ids)
    assert result["ok"], result
    return result["group_key"], paths


def test_over_cap_refuses_before_merge_or_cleanup(wave_repo: Path) -> None:
    ids = ["task-a", "task-b", "task-c"]
    key, paths = group(ids)
    for sid, path in paths.items():
        (path / f"{sid}.txt").write_text(sid)
    before = _git(["rev-parse", "HEAD"], wave_repo).stdout
    result = m.run_concurrent_wave(ids)
    assert result["kind"] == "WAVE_EXCEEDS_MAX_ACTORS", result
    assert result["needs_redispatch"] is False
    assert _git(["rev-parse", "HEAD"], wave_repo).stdout == before
    assert key in m._read_worktree_state(m.get_branch_name())["wave_groups"]
    for sid, path in paths.items():
        assert (path / f"{sid}.txt").read_text() == sid
        assert not (wave_repo / f"{sid}.txt").exists()


def test_within_cap_accepts_all_members(wave_repo: Path) -> None:
    ids = ["task-a", "task-b"]
    _, paths = group(ids)
    for sid, path in paths.items():
        (path / f"{sid}.txt").write_text(sid)
    result = m.run_concurrent_wave(ids)
    assert result["ok"], result
    for sid, path in paths.items():
        assert (wave_repo / f"{sid}.txt").read_text() == sid
        assert not path.exists()


def test_abort_preserves_recoverable_binary_patches(
    wave_repo: Path, tmp_path: Path
) -> None:
    key, paths = group(["task-a", "task-b"])
    base = _git(["rev-parse", "HEAD"], wave_repo).stdout.strip()
    payload = b"\x00\xffuncommitted binary\x00"
    for path in paths.values():
        (path / "payload.bin").write_bytes(payload)
        (path / "a.txt").unlink()
        (path / "link").symlink_to("payload.bin")
    result = m.abort_wave_group(key)
    assert result["ok"], result
    assert len(result["patches"]) == 2
    for sid, patch in result["patches"].items():
        recovered = tmp_path / f"recover-{sid}"
        assert (
            _git(
                ["worktree", "add", "--detach", str(recovered), base], wave_repo
            ).returncode
            == 0
        )
        applied = _git(["apply", "--binary", str(patch)], recovered)
        assert applied.returncode == 0, applied.stderr
        assert (recovered / "payload.bin").read_bytes() == payload
        assert not (recovered / "a.txt").exists()
        assert os.readlink(recovered / "link") == "payload.bin"
    assert all(not path.exists() for path in paths.values())


def test_patch_failure_preserves_every_worktree(
    wave_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key, paths = group(["task-a", "task-b"])
    for path in paths.values():
        (path / "keep.txt").write_text("keep")
    real_git = m._wt_git

    def fail_add(args, cwd=None, **kwargs):
        if args == ["add", "-A"] and cwd == paths["task-b"]:
            return subprocess.CompletedProcess(args, 1, "", "injected index failure")
        return real_git(args, cwd=cwd, **kwargs)

    monkeypatch.setattr(m, "_wt_git", fail_add)
    result = m.abort_wave_group(key)
    assert not result["ok"], result
    assert key in m._read_worktree_state(m.get_branch_name())["wave_groups"]
    assert all((path / "keep.txt").read_text() == "keep" for path in paths.values())


@pytest.mark.parametrize("runtime_kind", ["binary", "deleted", "symlink", "mode"])
def test_conflict_abort_preserves_tracked_runtime_and_user_stash(
    wave_repo: Path, runtime_kind: str
) -> None:
    (wave_repo / "a.txt").write_text("unrelated user stash\n")
    assert _git(["stash", "push", "-m", "user-owned"], wave_repo).returncode == 0
    stash_before = _git(["stash", "list", "--format=%H"], wave_repo).stdout
    assert _git(["config", "merge.autoStash", "true"], wave_repo).returncode == 0
    ids = ["task-a", "task-b"]
    _, paths = group(ids)
    for sid, path in paths.items():
        (path / "a.txt").write_text(sid + "\n")
    runtime = wave_repo / ".map/feat-x/handoff.json"
    if runtime_kind == "binary":
        runtime.write_bytes(b"changed\x00runtime")
    elif runtime_kind == "deleted":
        runtime.unlink()
    elif runtime_kind == "symlink":
        runtime.unlink()
        runtime.symlink_to("local-target")
    else:
        runtime.chmod(0o755)

    def snapshot():
        if runtime.is_symlink():
            return ("symlink", os.readlink(runtime))
        if not runtime.exists():
            return ("missing",)
        return (runtime.stat().st_mode, runtime.read_bytes())

    before = snapshot()
    base = _git(["rev-parse", "HEAD"], wave_repo).stdout
    result = m.run_concurrent_wave(ids)
    assert result["kind"] == "WAVE_ABORTED", result
    assert _git(["rev-parse", "HEAD"], wave_repo).stdout == base
    assert snapshot() == before
    assert _git(["stash", "list", "--format=%H"], wave_repo).stdout == stash_before
    assert len(result["abort_result"]["patches"]) == 2


def test_staged_runtime_refuses_without_changing_index(wave_repo: Path) -> None:
    _, paths = group(["task-a"])
    (paths["task-a"] / "new.txt").write_text("candidate")
    runtime = wave_repo / ".map/feat-x/handoff.json"
    runtime.write_text("staged runtime")
    assert _git(["add", str(runtime)], wave_repo).returncode == 0
    before = _git(["diff", "--cached", "--binary"], wave_repo).stdout
    result = m.run_concurrent_wave(["task-a"])
    assert not result["ok"], result
    assert result["needs_redispatch"] is False
    assert _git(["diff", "--cached", "--binary"], wave_repo).stdout == before
    assert (paths["task-a"] / "new.txt").exists()


def test_failed_rollback_keeps_candidates(
    wave_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key, paths = group(["task-a"])
    (paths["task-a"] / "keep.txt").write_text("keep")
    monkeypatch.setattr(m, "_wt_rollback", lambda base: False)
    result = m.abort_wave_group(key)
    assert not result["ok"], result
    assert (paths["task-a"] / "keep.txt").read_text() == "keep"
    assert key in m._read_worktree_state(m.get_branch_name())["wave_groups"]


def test_external_head_movement_never_resets_user_commit(wave_repo: Path) -> None:
    _, paths = group(["task-a"])
    (paths["task-a"] / "candidate.txt").write_text("keep candidate")
    (wave_repo / "user.txt").write_text("keep user commit")
    assert _git(["add", "user.txt"], wave_repo).returncode == 0
    assert _git(["commit", "-qm", "user change"], wave_repo).returncode == 0
    head = _git(["rev-parse", "HEAD"], wave_repo).stdout
    result = m.run_concurrent_wave(["task-a"])
    assert result["kind"] == "EXTERNAL_HEAD_MOVED", result
    assert result["needs_redispatch"] is False
    assert _git(["rev-parse", "HEAD"], wave_repo).stdout == head
    assert (paths["task-a"] / "candidate.txt").read_text() == "keep candidate"


def test_discard_patch_write_failure_retains_candidate(
    wave_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, paths = group(["task-a"])
    (paths["task-a"] / "keep.txt").write_text("keep")

    def no_space(*args, **kwargs):
        raise OSError("injected disk full")

    monkeypatch.setattr(m.tempfile, "mkstemp", no_space)
    result = m.discard_subtask_worktree("task-a", save_patch=True)
    assert result["kind"] == "PATCH_SAVE_FAILED", result
    assert (paths["task-a"] / "keep.txt").read_text() == "keep"
