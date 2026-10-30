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
    admitted = m.begin_wave_group(ids)
    assert admitted["ok"], admitted
    paths = {}
    for sid in ids:
        result = m.create_subtask_worktree(sid)
        assert result["ok"], result
        paths[sid] = Path(result["worktree_path"])
    return admitted["group_key"], paths


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


@pytest.mark.parametrize("direct_abort", [False, True])
def test_external_head_movement_never_resets_user_commit(
    wave_repo: Path, direct_abort: bool
) -> None:
    key, paths = group(["task-a"])
    (paths["task-a"] / "candidate.txt").write_text("keep candidate")
    (wave_repo / "user.txt").write_text("keep user commit")
    assert _git(["add", "user.txt"], wave_repo).returncode == 0
    assert _git(["commit", "-qm", "user change"], wave_repo).returncode == 0
    head = _git(["rev-parse", "HEAD"], wave_repo).stdout
    result = (
        m.abort_wave_group(key) if direct_abort else m.run_concurrent_wave(["task-a"])
    )
    assert result["kind"] == "EXTERNAL_HEAD_MOVED", result
    assert result["worktrees_preserved"] is True
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


@pytest.mark.parametrize("parent_change", ["untracked", "tracked", "staged_runtime"])
def test_direct_abort_refuses_unowned_parent_changes(
    wave_repo: Path, parent_change: str
) -> None:
    key, paths = group(["task-a"])
    path = (
        wave_repo
        / {
            "untracked": "user.txt",
            "tracked": "a.txt",
            "staged_runtime": ".map/feat-x/handoff.json",
        }[parent_change]
    )
    path.write_text("user work")
    if parent_change == "staged_runtime":
        assert _git(["add", str(path)], wave_repo).returncode == 0
    before = _git(["diff", "--cached", "--binary"], wave_repo).stdout
    result = m.abort_wave_group(key)
    assert not result["ok"], result
    assert result["worktrees_preserved"] is True
    assert path.read_text() == "user work"
    assert _git(["diff", "--cached", "--binary"], wave_repo).stdout == before
    assert paths["task-a"].is_dir()


@pytest.mark.parametrize("direct_discard", [False, True])
def test_cleanup_reentry_after_removal_before_sidecar_update(
    wave_repo: Path, monkeypatch: pytest.MonkeyPatch, direct_discard: bool
) -> None:
    key, paths = group(["task-a"])
    (paths["task-a"] / "candidate.txt").write_text("recover me")
    real_remove = m._wt_force_remove

    def crash_after_remove(*args):
        real_remove(*args)
        raise RuntimeError("simulated process stop")

    def cleanup():
        if direct_discard:
            return m.discard_subtask_worktree("task-a", save_patch=True)
        return m.abort_wave_group(key)

    monkeypatch.setattr(m, "_wt_force_remove", crash_after_remove)
    with pytest.raises(RuntimeError, match="simulated process stop"):
        cleanup()
    patches = list((wave_repo / ".map/feat-x/worktree_attempts").glob("*.patch"))
    assert len(patches) == 1
    assert b"recover me" in patches[0].read_bytes()
    monkeypatch.setattr(m, "_wt_force_remove", real_remove)
    result = cleanup()
    assert result["ok"], result
    assert patches[0].exists()
    assert not paths["task-a"].exists()


def test_unregistered_group_failure_cannot_authorize_redispatch(
    wave_repo: Path,
) -> None:
    ids = ["task-a", "task-b"]
    paths = []
    for sid in ids:
        result = m.create_subtask_worktree(sid)
        assert result["ok"], result
        path = Path(result["worktree_path"])
        (path / "a.txt").write_text(sid)
        paths.append(path)
    result = m.run_concurrent_wave(ids)
    assert result["kind"] == "WAVE_ABORT_FAILED", result
    assert result["needs_redispatch"] is False
    assert all(path.exists() for path in paths)


@pytest.mark.parametrize("capture_fails", [False, True])
def test_missing_directory_preserves_surviving_branch_commits(
    wave_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capture_fails: bool,
) -> None:
    key, paths = group(["task-a"])
    candidate = paths["task-a"]
    payload = b"\x00\xffcommitted candidate"
    (candidate / "payload.bin").write_bytes(payload)
    assert _git(["add", "payload.bin"], candidate).returncode == 0
    assert _git(["commit", "-qm", "candidate"], candidate).returncode == 0
    ref = _git(["branch", "--show-current"], candidate).stdout.strip()
    base = _git(["rev-parse", "HEAD"], wave_repo).stdout.strip()
    assert (
        _git(["worktree", "remove", "--force", str(candidate)], wave_repo).returncode
        == 0
    )
    if capture_fails:

        def no_space(*args, **kwargs):
            raise OSError("injected disk full")

        monkeypatch.setattr(m.tempfile, "mkstemp", no_space)
    result = m.abort_wave_group(key)
    if capture_fails:
        assert result["kind"] == "PATCH_SAVE_FAILED", result
        assert (
            _git(["show-ref", "--verify", f"refs/heads/{ref}"], wave_repo).returncode
            == 0
        )
        return
    assert result["ok"], result
    recovered = tmp_path / "recovered"
    assert (
        _git(
            ["worktree", "add", "--detach", str(recovered), base], wave_repo
        ).returncode
        == 0
    )
    assert (
        _git(["apply", "--binary", result["patches"]["task-a"]], recovered).returncode
        == 0
    )
    assert (recovered / "payload.bin").read_bytes() == payload


def test_accepted_batch_does_not_block_later_abort(wave_repo: Path) -> None:
    first, paths = group(["task-a"])
    (paths["task-a"] / "accepted.txt").write_text("accepted")
    assert m.run_concurrent_wave(["task-a"])["ok"]
    assert first not in m._read_worktree_state(m.get_branch_name())["wave_groups"]
    second, _ = group(["task-b"])
    result = m.abort_wave_group(second)
    assert result["ok"], result
    assert (wave_repo / "accepted.txt").read_text() == "accepted"


def test_retry_history_survives_abort_and_resets_on_accept(wave_repo: Path) -> None:
    ids = ["task-a", "task-b"]
    for remaining in (2, 1):
        key, paths = group(ids)
        for sid, path in paths.items():
            (path / "a.txt").write_text(sid)
        result = m.run_concurrent_wave(ids)
        assert result["kind"] == "WAVE_ABORTED", result
        assert result["attempts_remaining"] == remaining
        assert result["escalate_to_human"] is False
    _, paths = group(ids)
    for sid, path in paths.items():
        (path / f"{sid}.txt").write_text(sid)
    assert m.run_concurrent_wave(ids)["ok"]
    state = m._read_worktree_state(m.get_branch_name())
    assert key not in state["wave_abort_attempts"]
    for remaining in (2, 1, 0):
        _, paths = group(ids)
        for sid, path in paths.items():
            (path / "a.txt").write_text(sid)
        result = m.run_concurrent_wave(ids)
        assert result["kind"] == "WAVE_ABORTED", result
        assert result["attempts_remaining"] == remaining
        assert result["escalate_to_human"] is (remaining == 0)
        assert result["needs_redispatch"] is (remaining > 0)
    before = m._read_worktree_state(m.get_branch_name())
    refused = m.begin_wave_group(ids)
    assert refused["kind"] == "WAVE_RETRIES_EXHAUSTED", refused
    assert refused["needs_redispatch"] is False
    assert m._read_worktree_state(m.get_branch_name()) == before
    # Even a caller bypassing group admission cannot merge or lose fresh work.
    candidate = m.create_subtask_worktree(ids[0])
    assert candidate["ok"], candidate
    path = Path(candidate["worktree_path"])
    (path / "keep.txt").write_text("do not freeze or remove")
    head = _git(["rev-parse", "HEAD"], wave_repo).stdout
    refused = m.run_concurrent_wave(ids)
    assert refused["kind"] == "WAVE_RETRIES_EXHAUSTED", refused
    assert refused["needs_redispatch"] is False
    assert (path / "keep.txt").read_text() == "do not freeze or remove"
    assert _git(["rev-parse", "HEAD"], wave_repo).stdout == head
    assert _git(["rev-parse", "HEAD"], path).stdout == head


@pytest.mark.parametrize("invalid_count", [True, -1, "3", None])
def test_invalid_retry_state_fails_closed(wave_repo: Path, invalid_count) -> None:
    branch = m.get_branch_name()
    state = m._read_worktree_state(branch)
    state["wave_abort_attempts"] = {"task-a": invalid_count}
    m._write_worktree_state(branch, state)
    for operation in (m.begin_wave_group, m.run_concurrent_wave):
        result = operation(["task-a"])
        assert result["kind"] == "WAVE_RETRY_STATE_INVALID", result
        assert result["needs_redispatch"] is False
        assert m._read_worktree_state(branch) == state


@pytest.mark.parametrize("ids", [["task-a"], ["task-a", "task-b"]])
def test_direct_aborts_consume_budget_exactly_once(
    wave_repo: Path, ids: list[str]
) -> None:
    for used in (1, 2, 3):
        key, paths = group(ids)
        (paths["task-a"] / "attempt.txt").write_text(str(used))
        result = m.abort_wave_group(key)
        assert result["ok"], result
        assert result["attempts_used"] == used
        assert result["attempts_remaining"] == 3 - used
        assert result["needs_redispatch"] is (used < 3)
        repeated = m.abort_wave_group(ids[0])
        assert repeated["attempts_used"] == used
        assert repeated["needs_redispatch"] is (used < 3)
    refused = m.begin_wave_group(ids)
    assert refused["kind"] == "WAVE_RETRIES_EXHAUSTED", refused


@pytest.mark.parametrize("gate_fails", [False, True])
def test_concurrent_acceptance_runs_post_wave_gate(
    wave_repo: Path, gate_fails: bool
) -> None:
    # The same check passes in each candidate but detects a semantic failure
    # only after both independently valid files have landed in the parent.
    check = wave_repo / "verify.py"
    check.write_text(
        "from pathlib import Path\n"
        "a, b = Path('part-a.txt').exists(), Path('part-b.txt').exists()\n"
        "if a and b:\n"
        "    Path('.map/post-wave-ran').write_text('ran')\n"
        f"    raise SystemExit({7 if gate_fails else 0})\n"
    )
    config = wave_repo / ".map/config.yaml"
    config.write_text(
        config.read_text() + "verification_checks:\n  - python3 verify.py\n"
    )
    assert _git(["add", "verify.py", ".map/config.yaml"], wave_repo).returncode == 0
    assert _git(["commit", "-qm", "verification command"], wave_repo).returncode == 0
    _, paths = group(["task-a", "task-b"])
    (paths["task-a"] / "part-a.txt").write_text("a")
    (paths["task-b"] / "part-b.txt").write_text("b")
    base = _git(["rev-parse", "HEAD"], wave_repo).stdout
    result = m.run_concurrent_wave(["task-a", "task-b"])
    assert (wave_repo / ".map/post-wave-ran").read_text() == "ran"
    if gate_fails:
        assert result["kind"] == "WAVE_ABORTED", result
        assert result["merge_error"]["kind"] == "WAVE_VERIFY_FAILED"
        assert _git(["rev-parse", "HEAD"], wave_repo).stdout == base
        assert not (wave_repo / "part-a.txt").exists()
        assert not (wave_repo / "part-b.txt").exists()
        assert len(result["abort_result"]["patches"]) == 2
        assert result["attempts_remaining"] == 2
    else:
        assert result["ok"], result
        assert (wave_repo / "part-a.txt").read_text() == "a"
        assert (wave_repo / "part-b.txt").read_text() == "b"
