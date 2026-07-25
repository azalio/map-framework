"""Tests for src/mapify_cli/_locking.py.

Covers AC-5 test matrix:
  (a) happy path — acquire/release, created marker
  (b) explicit set(UPDATED) mid-block
  (c) timeout when sibling process holds the lock
  (d) exception inside with → error marker + re-raise
  (e) symlink on lock-file path → LockSecurityError
  (e2) symlink on sidecar path → LockSecurityError
  (f) two-process contention via subprocess
  (g) tmp state file is co-located in ~/.map/locks/, not /tmp

AC-6: mode assertions on Unix
INV-4: module docstring contains verbatim thread-safety sentence
INV-6: _state_tmp_path returns path under ~/.map/locks/
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

import mapify_cli._locking as _locking_mod
from mapify_cli._locking import (
    LockSecurityError,
    LockState,
    LockTimeoutError,
    StateWriter,
    _state_tmp_path,
    flock_with_state,
)

# ---------------------------------------------------------------------------
# PYTHONPATH for subprocess helper scripts
#
# The editable install may point at a different worktree. We prepend the
# hogback-gap src/ directory so helper scripts find mapify_cli._locking from
# THIS worktree regardless of which site-package is active.
# ---------------------------------------------------------------------------
_SRC_DIR = str(Path(__file__).parent.parent / "src")


def _subprocess_env(home: str) -> dict[str, str]:
    """Return an env dict with HOME overridden and PYTHONPATH prepended."""
    existing_pp = os.environ.get("PYTHONPATH", "")
    new_pp = _SRC_DIR + (os.pathsep + existing_pp if existing_pp else "")
    return {**os.environ, "HOME": home, "PYTHONPATH": new_pp}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_HELPER_SCRIPT = """\
import sys
import os
import time
from pathlib import Path

# Redirect HOME before importing _locking so lazy Path.home() returns tmp dir.
os.environ["HOME"] = sys.argv[1]
name = sys.argv[2]
hold_s = float(sys.argv[3])

from mapify_cli._locking import flock_with_state, LockState

with flock_with_state(name, timeout_s=30.0, initial_state=LockState.IN_PROGRESS):
    # Signal readiness by touching a sentinel file.
    sentinel = Path(sys.argv[1]) / ".lock_held"
    sentinel.touch()
    time.sleep(hold_s)
"""

_HELPER_CONTENTION_SCRIPT = """\
import sys
import os
from pathlib import Path

os.environ["HOME"] = sys.argv[1]
name = sys.argv[2]
timeout_s = float(sys.argv[3])

from mapify_cli._locking import flock_with_state, LockState, LockTimeoutError

try:
    with flock_with_state(name, timeout_s=timeout_s):
        pass
    sys.exit(0)   # acquired successfully
except LockTimeoutError:
    sys.exit(42)  # expected contention exit code
"""


def _write_helper(tmp_path: Path, script_body: str, filename: str) -> Path:
    p = tmp_path / filename
    p.write_text(script_body)
    return p


def _wait_for_sentinel(sentinel: Path, timeout: float = 5.0) -> None:
    """Block until the sentinel file exists (subprocess signals readiness)."""
    deadline = time.monotonic() + timeout
    while not sentinel.exists():
        if time.monotonic() > deadline:
            raise TimeoutError(f"Sentinel {sentinel} never appeared")
        time.sleep(0.02)


# ---------------------------------------------------------------------------
# (a) Happy path: acquire/release with created marker
# ---------------------------------------------------------------------------


def test_happy_path_created_marker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    with flock_with_state("mylock") as writer:
        assert isinstance(writer, StateWriter)
        writer.set(LockState.CREATED)

    lock_root = tmp_path / ".map" / "locks"
    sidecar = lock_root / "mylock.state.json"
    assert sidecar.exists(), "Sidecar must exist after block"
    data = json.loads(sidecar.read_text())
    assert data["state"] == "created"
    assert data["pid"] == os.getpid()
    assert "updated_at" in data


# ---------------------------------------------------------------------------
# (b) Explicit set(UPDATED)
# ---------------------------------------------------------------------------


def test_set_updated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    with flock_with_state("uplock", initial_state=LockState.CREATED) as writer:
        writer.set(LockState.UPDATED)

    sidecar = tmp_path / ".map" / "locks" / "uplock.state.json"
    data = json.loads(sidecar.read_text())
    assert data["state"] == "updated"


# ---------------------------------------------------------------------------
# (c) Timeout: sibling process holds the lock, current times out
# ---------------------------------------------------------------------------


def test_timeout_raises_and_writes_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    helper = _write_helper(tmp_path, _HELPER_SCRIPT, "holder.py")
    sentinel = tmp_path / ".lock_held"

    proc = None
    try:
        proc = __import__("subprocess").Popen(
            [sys.executable, str(helper), str(tmp_path), "timeout_lock", "5.0"],
            env=_subprocess_env(str(tmp_path)),
        )
        _wait_for_sentinel(sentinel)

        with pytest.raises(LockTimeoutError), flock_with_state("timeout_lock", timeout_s=0.3):
            pass  # should not reach here

    finally:
        if proc is not None:
            proc.terminate()
            proc.wait()

    sidecar = tmp_path / ".map" / "locks" / "timeout_lock.state.json"
    assert sidecar.exists(), "Sidecar must be written even on timeout"
    data = json.loads(sidecar.read_text())
    assert data["state"] == "timeout"


# ---------------------------------------------------------------------------
# (d) Exception inside with → error marker + re-raise
# ---------------------------------------------------------------------------


def test_exception_writes_error_marker_and_reraises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    with pytest.raises(RuntimeError, match="boom"), flock_with_state("errlock") as writer:
        writer.set(LockState.CREATED)
        raise RuntimeError("boom")

    sidecar = tmp_path / ".map" / "locks" / "errlock.state.json"
    data = json.loads(sidecar.read_text())
    assert data["state"] == "error", "Sidecar must record error state after exception"


# ---------------------------------------------------------------------------
# (e) Symlink on lock-file path → LockSecurityError
# ---------------------------------------------------------------------------


def test_symlink_on_lock_path_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    lock_root = tmp_path / ".map" / "locks"
    lock_root.mkdir(mode=0o700, parents=True)
    lock_path = lock_root / "symlinklock.lock"
    os.symlink("/tmp/innocuous", str(lock_path))

    with pytest.raises(LockSecurityError), flock_with_state("symlinklock"):
        pass


# ---------------------------------------------------------------------------
# (e2) Symlink on sidecar path → LockSecurityError
# ---------------------------------------------------------------------------


def test_symlink_on_sidecar_path_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    lock_root = tmp_path / ".map" / "locks"
    lock_root.mkdir(mode=0o700, parents=True)
    sidecar = lock_root / "sidecarsym.state.json"
    os.symlink("/tmp/nowhere", str(sidecar))

    with pytest.raises(LockSecurityError), flock_with_state("sidecarsym"):
        pass


# ---------------------------------------------------------------------------
# (f) Two-process contention via subprocess
# ---------------------------------------------------------------------------


def test_two_process_contention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Process 2 gets LockTimeoutError while process 1 holds; succeeds after."""
    monkeypatch.setenv("HOME", str(tmp_path))

    holder_script = _write_helper(tmp_path, _HELPER_SCRIPT, "holder2.py")
    contender_script = _write_helper(
        tmp_path, _HELPER_CONTENTION_SCRIPT, "contender.py"
    )
    sentinel = tmp_path / ".lock_held"

    import subprocess

    proc = None
    try:
        proc = subprocess.Popen(
            [sys.executable, str(holder_script), str(tmp_path), "contlock", "4.0"],
            env=_subprocess_env(str(tmp_path)),
        )
        _wait_for_sentinel(sentinel)

        # Contender should time out while holder owns the lock.
        result = subprocess.run(
            [
                sys.executable,
                str(contender_script),
                str(tmp_path),
                "contlock",
                "0.3",
            ],
            env=_subprocess_env(str(tmp_path)),
            check=False,
        )
        assert result.returncode == 42, (
            f"Expected contender to exit 42 (LockTimeoutError), got {result.returncode}"
        )
    finally:
        if proc is not None:
            proc.terminate()
            proc.wait()

    # After holder terminates, lock is released — contender should now succeed.
    result2 = subprocess.run(
        [sys.executable, str(contender_script), str(tmp_path), "contlock", "5.0"],
        env=_subprocess_env(str(tmp_path)),
        check=False,
    )
    assert result2.returncode == 0, "Contender should succeed after holder releases"


# ---------------------------------------------------------------------------
# (g) Tmp state file is co-located under ~/.map/locks/, not /tmp
# ---------------------------------------------------------------------------


def test_tmp_state_file_colocated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_state_tmp_path must return a path co-located with the target sidecar.

    INV-6 is about ``os.replace`` atomicity, which requires src+dst on the same
    filesystem. The correct check is ``tmp.parent == sidecar.parent``, NOT a
    string-prefix scan for ``/tmp`` — on Linux CI ``pytest`` roots ``tmp_path``
    under ``/tmp/pytest-of-runner/...``, so a naive prefix check falsely flags
    the legitimate ``$HOME/.map/locks/`` layout.
    """
    monkeypatch.setenv("HOME", str(tmp_path))

    lock_root = tmp_path / ".map" / "locks"
    tmp_file = _state_tmp_path("myname", lock_root)
    sidecar = lock_root / "myname.state.json"

    # The INV-6 invariant: tmp file shares the target sidecar's directory.
    assert tmp_file.parent == sidecar.parent == lock_root, (
        f"INV-6 violated: tmp {tmp_file} and sidecar {sidecar} must share "
        f"a parent for os.replace to be atomic; got {tmp_file.parent} != "
        f"{sidecar.parent}"
    )


# ---------------------------------------------------------------------------
# AC-6: mode assertions (Unix only)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="Permissions not applicable on Windows")
def test_lock_dir_and_file_modes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    with flock_with_state("modelock") as writer:
        writer.set(LockState.CREATED)

    lock_root = tmp_path / ".map" / "locks"

    # Directory must be 0o700.
    dir_mode = oct(os.stat(str(lock_root)).st_mode & 0o777)
    assert dir_mode == oct(0o700), f"Lock dir mode {dir_mode} != 0o700"

    # Lock file must be 0o600.
    lock_file = lock_root / "modelock.lock"
    lock_mode = oct(os.stat(str(lock_file)).st_mode & 0o777)
    assert lock_mode == oct(0o600), f"Lock file mode {lock_mode} != 0o600"

    # State sidecar must be 0o600.
    sidecar = lock_root / "modelock.state.json"
    sidecar_mode = oct(os.stat(str(sidecar)).st_mode & 0o777)
    assert sidecar_mode == oct(0o600), f"Sidecar mode {sidecar_mode} != 0o600"


# ---------------------------------------------------------------------------
# INV-4: module docstring contains verbatim thread-safety sentence
# ---------------------------------------------------------------------------


def test_module_docstring_contains_thread_safety_sentence() -> None:
    doc = _locking_mod.__doc__ or ""
    required = (
        "Thread safety is NOT provided. "
        "If two threads in the same process call flock_with_state with the same name, "
        "behavior is undefined. "
        "Use a threading.Lock at the call site if needed."
    )
    assert required in doc, (
        f"Module docstring missing required thread-safety sentence.\n"
        f"Expected to find:\n  {required!r}\n"
        f"Actual docstring:\n  {doc!r}"
    )


# ---------------------------------------------------------------------------
# INV-6: regression — tmp path never under /tmp
# ---------------------------------------------------------------------------


def test_tmp_path_never_under_system_tmp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression for INV-6: tmp path must share the sidecar's directory.

    Implementation detail: any path returned by ``_state_tmp_path`` must live
    inside the supplied ``lock_root`` argument — otherwise ``os.replace`` would
    cross filesystems and raise ``OSError(EXDEV)``.
    """
    monkeypatch.setenv("HOME", str(tmp_path))

    lock_root = tmp_path / ".map" / "locks"
    tmp = _state_tmp_path("regression", lock_root)
    assert tmp.parent == lock_root, (
        f"INV-6 violated: tmp path {tmp!r} is not inside lock_root {lock_root!r}"
    )


# ---------------------------------------------------------------------------
# Name validation
# ---------------------------------------------------------------------------


def test_invalid_name_raises_value_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    bad_names = [
        "../evil",
        "/etc/passwd",
        ".hidden",
        "a" * 65,
        "has space",
        "has/slash",
    ]
    for name in bad_names:
        with pytest.raises(ValueError, match="Invalid lock name"):
            # The context manager raises before yielding.
            ctx = flock_with_state(name)
            ctx.__enter__()


# ---------------------------------------------------------------------------
# StateWriter is frozen — caller cannot mutate `.name` to bypass the regex
# ---------------------------------------------------------------------------


def test_state_writer_is_frozen(tmp_path: Path) -> None:
    """Attempts to mutate StateWriter.name must raise FrozenInstanceError."""
    import dataclasses

    writer = StateWriter(lock_root=tmp_path, name="legit", pid=12345)
    with pytest.raises(dataclasses.FrozenInstanceError):
        writer.name = "../escape"  # type: ignore[misc]


def test_direct_state_writer_with_bad_name_revalidated(tmp_path: Path) -> None:
    """Hand-crafted StateWriter with a traversal name must still be rejected.

    Defence-in-depth: ``flock_with_state`` validates the name at entry, but a
    caller can construct ``StateWriter`` directly. ``_write_state_atomic``
    therefore re-validates ``name`` on every write so a bypass is impossible
    even without the context manager.
    """
    lock_root = tmp_path / ".map" / "locks"
    lock_root.mkdir(mode=0o700, parents=True)
    writer = StateWriter(lock_root=lock_root, name="../../etc/passwd", pid=42)
    with pytest.raises(ValueError, match="Invalid lock name"):
        writer.set(LockState.UPDATED)


# ---------------------------------------------------------------------------
# AC-6 hardening: pre-existing dir/file with wrong permissions get corrected
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions only")
def test_existing_lock_dir_mode_enforced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pre-existing ~/.map/locks/ with broader perms gets corrected to 0o700."""
    monkeypatch.setenv("HOME", str(tmp_path))

    lock_root = tmp_path / ".map" / "locks"
    lock_root.mkdir(mode=0o755, parents=True)  # too permissive
    # Verify the broad mode is actually in place before we call.
    pre_mode = os.stat(str(lock_root)).st_mode & 0o777
    assert pre_mode == 0o755, f"Setup precondition failed: {oct(pre_mode)}"

    with flock_with_state("modefix") as writer:
        writer.set(LockState.CREATED)

    post_mode = os.stat(str(lock_root)).st_mode & 0o777
    assert post_mode == 0o700, (
        f"Pre-existing lock dir should be chmod'd to 0o700, got {oct(post_mode)}"
    )


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions only")
def test_existing_lock_file_mode_enforced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pre-existing lock file with broader perms gets corrected to 0o600."""
    monkeypatch.setenv("HOME", str(tmp_path))

    lock_root = tmp_path / ".map" / "locks"
    lock_root.mkdir(mode=0o700, parents=True)
    lock_file = lock_root / "filemodefix.lock"
    lock_file.touch()
    os.chmod(str(lock_file), 0o644)  # too permissive
    pre_mode = os.stat(str(lock_file)).st_mode & 0o777
    assert pre_mode == 0o644, f"Setup precondition failed: {oct(pre_mode)}"

    with flock_with_state("filemodefix") as writer:
        writer.set(LockState.CREATED)

    post_mode = os.stat(str(lock_file)).st_mode & 0o777
    assert post_mode == 0o600, (
        f"Pre-existing lock file should be chmod'd to 0o600, got {oct(post_mode)}"
    )
