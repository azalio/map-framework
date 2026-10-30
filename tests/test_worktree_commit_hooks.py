"""Git hooks must participate in candidate and parent acceptance commits."""

import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_worktree_isolation import _enable, _git, _make_repo, m


@pytest.fixture
def hook_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = _make_repo(tmp_path)
    _enable(root)
    assert _git(["add", ".map/config.yaml"], root).returncode == 0
    assert _git(["commit", "-qm", "configuration"], root).returncode == 0
    hooks = root / ".git/hooks"
    assert _git(["config", "core.hooksPath", str(hooks)], root).returncode == 0
    monkeypatch.chdir(root)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    return root


def candidates(
    mode: str, *, changed: bool = True, identical: bool = False
) -> dict[str, Path]:
    paths = {}
    for sid in ["task-a"] if mode == "single" else ["task-a", "task-b"]:
        created = m.create_subtask_worktree(sid)
        assert created["ok"], created
        path = Path(created["worktree_path"])
        if changed:
            (path / ("shared.txt" if identical else f"{sid}.txt")).write_text(
                "shared" if identical else sid
            )
        paths[sid] = path
    return paths


def accept(mode: str, paths: dict[str, Path], **kwargs) -> dict:
    if mode == "single":
        return m.merge_subtask_worktree(next(iter(paths)), **kwargs)
    return m.merge_wave_worktrees(list(paths), **kwargs)


def install_hook(
    root: Path,
    name: str,
    log: Path,
    *,
    reject: Path | None = None,
    reject_after: int = 1,
    message: str = "hook rejected",
) -> None:
    counter = log.with_suffix(".count")
    body = "#!/bin/sh\n" + f'printf "%s\\n" "$PWD" >> {shlex.quote(str(log))}\n'
    if reject is not None:
        body += (
            f'if [ "$PWD" = {shlex.quote(str(reject))} ]; then\n'
            "  count=0\n"
            f"  if [ -f {shlex.quote(str(counter))} ]; then read -r count < {shlex.quote(str(counter))}; fi\n"
            "  count=$((count + 1))\n"
            f'  printf "%s\\n" "$count" > {shlex.quote(str(counter))}\n'
            f'  if [ "$count" -ge {reject_after} ]; then\n'
            f"    printf '%s\\n' {shlex.quote(message)} >&2\n"
            "    exit 9\n"
            "  fi\n"
            "fi\n"
        )
    body += "exit 0\n"
    hook = root / ".git/hooks" / name
    hook.write_text(body)
    hook.chmod(0o755)


@pytest.mark.parametrize("mode", ["single", "wave"])
@pytest.mark.parametrize("hook", ["pre-commit", "commit-msg"])
@pytest.mark.parametrize("target", ["candidate", "parent"])
@pytest.mark.parametrize(
    "message", ["hook rejected", "nothing to commit: hook rejected"]
)
def test_hook_failure_blocks_acceptance(
    hook_repo: Path, tmp_path: Path, mode: str, hook: str, target: str, message: str
) -> None:
    paths = candidates(mode)
    log = tmp_path / "hook.log"
    reject = hook_repo if target == "parent" else paths[next(reversed(paths))]
    install_hook(
        hook_repo,
        hook,
        log,
        reject=reject,
        reject_after=len(paths) if target == "parent" else 1,
        message=message,
    )
    base = _git(["rev-parse", "HEAD"], hook_repo).stdout
    result = accept(mode, paths)
    expected = (
        "WORKTREE_COMMIT_FAILED"
        if target == "candidate"
        else ("MERGE_COMMIT_FAILED" if mode == "single" else "WAVE_COMMIT_FAILED")
    )
    assert result.get("kind") == expected, result
    assert message in result["message"]
    assert str(reject) in log.read_text().splitlines()
    assert _git(["rev-parse", "HEAD"], hook_repo).stdout == base
    assert not _git(["diff", "--cached", "--name-only"], hook_repo).stdout
    for sid, path in paths.items():
        assert (path / f"{sid}.txt").read_text() == sid
        assert not (hook_repo / f"{sid}.txt").exists()
    assert len(m._read_worktree_state(m.get_branch_name())["worktrees"]) == len(paths)


@pytest.mark.parametrize("mode", ["single", "wave"])
@pytest.mark.parametrize("hook", ["pre-commit", "commit-msg"])
def test_successful_hooks_and_verification_both_run(
    hook_repo: Path, tmp_path: Path, mode: str, hook: str
) -> None:
    paths = candidates(mode)
    hook_log = tmp_path / "hook.log"
    install_hook(hook_repo, hook, hook_log)
    verify_log = tmp_path / "verify.log"
    code = (
        "from pathlib import Path; "
        f"p = Path({str(verify_log)!r}); "
        "p.open('a').write(str(Path.cwd()) + '\\n')"
    )
    command = shlex.join([sys.executable, "-c", code])
    base = _git(["rev-parse", "HEAD"], hook_repo).stdout.strip()
    result = accept(
        mode,
        paths,
        verify_cmds=[command],
        **({"post_wave_cmds": [command]} if mode == "wave" else {}),
    )
    assert result["ok"], result
    assert _git(
        ["rev-list", "--count", f"{base}..HEAD"], hook_repo
    ).stdout.strip() == str(len(paths))
    hook_calls = hook_log.read_text().splitlines()
    assert hook_calls.count(str(hook_repo)) == len(paths)
    for sid, path in paths.items():
        assert hook_calls.count(str(path)) == 1
        assert (hook_repo / f"{sid}.txt").read_text() == sid
        assert _git(["show", f"HEAD:{sid}.txt"], hook_repo).stdout == sid
        assert not path.exists()
    assert verify_log.read_text().splitlines() == [str(p) for p in paths.values()] + (
        [str(hook_repo)] if mode == "wave" else []
    )


@pytest.mark.parametrize("mode", ["single", "wave"])
def test_unchanged_candidates_do_not_invoke_commit_hooks(
    hook_repo: Path, tmp_path: Path, mode: str
) -> None:
    paths = candidates(mode, changed=False)
    log = tmp_path / "hook.log"
    install_hook(hook_repo, "pre-commit", log)
    head = _git(["rev-parse", "HEAD"], hook_repo).stdout
    result = accept(mode, paths)
    assert result["ok"], result
    assert not log.exists()
    assert _git(["rev-parse", "HEAD"], hook_repo).stdout == head


def test_identical_squashes_skip_only_the_empty_parent_commit(
    hook_repo: Path, tmp_path: Path
) -> None:
    paths = candidates("wave", identical=True)
    log = tmp_path / "hook.log"
    install_hook(hook_repo, "commit-msg", log)
    head = _git(["rev-parse", "HEAD"], hook_repo).stdout.strip()
    result = accept("wave", paths)
    assert result["ok"], result
    assert (hook_repo / "shared.txt").read_text() == "shared"
    assert (
        _git(["rev-list", "--count", f"{head}..HEAD"], hook_repo).stdout.strip() == "1"
    )
    assert log.read_text().splitlines() == [str(p) for p in paths.values()] + [
        str(hook_repo)
    ]


@pytest.mark.parametrize("mode", ["single", "wave"])
@pytest.mark.parametrize("target", ["candidate", "parent"])
def test_index_inspection_failure_is_not_an_empty_commit(
    hook_repo: Path, monkeypatch: pytest.MonkeyPatch, mode: str, target: str
) -> None:
    paths = candidates(mode)
    git = m._wt_git

    def fail_probe(args, cwd=None, **kwargs):
        is_parent = cwd is None or Path(cwd) == hook_repo
        if args == ["diff", "--cached", "--quiet"] and is_parent == (
            target == "parent"
        ):
            return subprocess.CompletedProcess(
                args, 2, stdout="", stderr="index inspection failed"
            )
        return git(args, cwd=cwd, **kwargs)

    monkeypatch.setattr(m, "_wt_git", fail_probe)
    base = _git(["rev-parse", "HEAD"], hook_repo).stdout
    result = accept(mode, paths)
    assert result["status"] == "error", result
    assert "index inspection failed" in result["message"]
    assert _git(["rev-parse", "HEAD"], hook_repo).stdout == base
    assert all(path.exists() for path in paths.values())
