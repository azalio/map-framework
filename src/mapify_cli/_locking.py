"""Process-safe locking with state-marker sidecars for MAP Framework.

This module provides ``flock_with_state``, a context manager that acquires an
exclusive advisory lock via :func:`fcntl.flock` and writes a JSON sidecar
(``~/.map/locks/<name>.state.json``) so observers can inspect lock ownership
and lifecycle state without peeking inside the lock protocol itself.

Thread safety is NOT provided. If two threads in the same process call flock_with_state with the same name, behavior is undefined. Use a threading.Lock at the call site if needed.

Timeout mechanism: polling loop with ``fcntl.LOCK_NB``; sleep interval is
50 ms per iteration (configurable via ``timeout_s``).

Lock directory: ``~/.map/locks/`` (mode 0o700, created on demand).
Lock file:      ``~/.map/locks/<name>.lock``      (mode 0o600)
State sidecar:  ``~/.map/locks/<name>.state.json`` (mode 0o600)
Tmp sidecar:    ``~/.map/locks/<name>.state.tmp.<pid>`` (same directory —
                required for atomic ``os.replace`` across same filesystem).

Name validation: ``^[a-zA-Z0-9_-]{1,64}$`` is enforced before any filesystem
touch to prevent path-traversal attacks.

Security: lock fd is opened with ``O_NOFOLLOW`` to refuse symlinks on the
lock-file path.  The sidecar write path uses ``os.lstat`` before every
``os.replace`` call to guard against symlinks independently (``O_NOFOLLOW``
does not protect ``os.replace`` by name).
"""

from __future__ import annotations

import contextlib
import errno
import fcntl
import json
import os
import re
import time
from collections.abc import Generator
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path

# ---------------------------------------------------------------------------
# Public API — constants
# ---------------------------------------------------------------------------

_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
_POLL_INTERVAL = 0.05  # seconds between flock retry attempts


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class LockState(StrEnum):
    """Closed set of lifecycle states for a named lock."""

    IN_PROGRESS = "in_progress"
    CREATED = "created"
    UPDATED = "updated"
    SKIPPED = "skipped"
    TIMEOUT = "timeout"
    ERROR = "error"


class LockTimeoutError(Exception):
    """Raised when ``flock_with_state`` cannot acquire the lock within ``timeout_s``."""


class LockSecurityError(Exception):
    """Raised when a symlink is detected on a lock or sidecar path."""


# ---------------------------------------------------------------------------
# StateWriter
# ---------------------------------------------------------------------------


@dataclass
class StateWriter:
    """Yields from ``flock_with_state``; call ``.set()`` to update the marker."""

    lock_root: Path
    name: str
    pid: int

    def set(self, state: LockState) -> None:
        """Write *state* to the sidecar atomically."""
        _write_state_atomic(self.lock_root, self.name, state, self.pid)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _lock_root() -> Path:
    """Return the lock directory, resolved lazily so test monkeypatches work."""
    return Path.home() / ".map" / "locks"


def _ensure_lock_dir(lock_root: Path) -> None:
    """Create the lock directory with mode 0o700 if absent."""
    lock_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Do NOT chmod an already-existing dir — respect what the user set.


def _state_tmp_path(name: str, lock_root: Path) -> Path:
    """Return the path used for the atomic-write temp file (same dir as target)."""
    return lock_root / f"{name}.state.tmp.{os.getpid()}"


def _write_state_atomic(
    lock_root: Path, name: str, state: LockState, pid: int
) -> None:
    """Write the JSON sidecar atomically via a co-located tmp file.

    Uses ``os.lstat`` before ``os.replace`` to detect symlinks on the target
    path (``O_NOFOLLOW`` only protects file-open, not rename-by-name).
    """
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload: dict[str, object] = {
        "state": str(state),
        "pid": pid,
        "updated_at": now_iso,
    }
    data = json.dumps(payload).encode()

    target = lock_root / f"{name}.state.json"
    tmp = _state_tmp_path(name, lock_root)

    # Write to tmp file — refuse symlinks via O_NOFOLLOW.
    o_nofollow = getattr(os, "O_NOFOLLOW", 0)
    tmp_fd = os.open(
        str(tmp),
        os.O_CREAT | os.O_WRONLY | os.O_TRUNC | o_nofollow,
        0o600,
    )
    try:
        os.write(tmp_fd, data)
        os.fsync(tmp_fd)
    finally:
        os.close(tmp_fd)

    # Guard target against symlinks before atomic rename.
    try:
        st = os.lstat(str(target))
        if os.path.islink(str(target)):  # lstat reveals symlinks
            # Clean up tmp before raising.
            try:
                os.unlink(str(tmp))
            except OSError:
                pass
            raise LockSecurityError(
                f"Sidecar path {target} is a symlink; refusing to write."
            )
        del st  # result not needed beyond the check
    except FileNotFoundError:
        pass  # target does not exist yet — safe to create

    os.replace(str(tmp), str(target))


# ---------------------------------------------------------------------------
# Public context manager
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def flock_with_state(
    name: str,
    *,
    timeout_s: float = 10.0,
    initial_state: LockState = LockState.IN_PROGRESS,
) -> Generator[StateWriter, None, None]:
    """Acquire an exclusive named flock and track lifecycle state.

    Parameters
    ----------
    name:
        Identifier for the lock; must match ``^[a-zA-Z0-9_-]{1,64}$``.
    timeout_s:
        Maximum seconds to wait for the lock before raising
        :exc:`LockTimeoutError`.
    initial_state:
        State written to the sidecar immediately after the lock is acquired.

    Yields
    ------
    StateWriter
        Use ``.set(LockState.<X>)`` to update the sidecar mid-flight.

    Raises
    ------
    ValueError
        If *name* fails the name-validation regex.
    LockSecurityError
        If the lock-file or sidecar path is a symlink.
    LockTimeoutError
        If the lock cannot be acquired within *timeout_s*.
    """
    # ---- 1. Name validation (before any filesystem touch) -----------------
    if not _NAME_RE.fullmatch(name):
        raise ValueError(
            f"Invalid lock name {name!r}. Must match ^[a-zA-Z0-9_-]{{1,64}}$"
        )

    # ---- 2. Resolve lock directory lazily ---------------------------------
    lock_root = _lock_root()
    _ensure_lock_dir(lock_root)

    lock_path = lock_root / f"{name}.lock"

    # ---- 3. Open lock file (O_NOFOLLOW refuses symlinks) ------------------
    o_nofollow = getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT | o_nofollow, 0o600)
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.EMLINK):
            raise LockSecurityError(
                f"Lock path {lock_path} is a symlink; refusing to open."
            ) from exc
        raise

    pid = os.getpid()
    writer = StateWriter(lock_root=lock_root, name=name, pid=pid)

    try:
        # ---- 4. Polling acquire loop --------------------------------------
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break  # acquired
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    # Write timeout marker before raising.
                    try:
                        _write_state_atomic(lock_root, name, LockState.TIMEOUT, pid)
                    except Exception:  # noqa: BLE001 — best-effort
                        pass
                    raise LockTimeoutError(
                        f"Could not acquire lock {name!r} within {timeout_s}s"
                    )
                time.sleep(_POLL_INTERVAL)

        # ---- 5. Write initial state marker --------------------------------
        _write_state_atomic(lock_root, name, initial_state, pid)

        # ---- 6. Yield control to caller -----------------------------------
        try:
            yield writer
        except Exception:
            # HC-4: write error marker then re-raise original unchanged.
            try:
                _write_state_atomic(lock_root, name, LockState.ERROR, pid)
            except Exception:  # noqa: BLE001 — best-effort, don't mask original
                pass
            raise  # bare raise preserves original exc info

    finally:
        # Always release the flock and close the fd.
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(fd)
