"""Shared utilities for MAP workflow scripts."""

import contextlib
import errno
import importlib
import os
import re
import subprocess
import tempfile
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

_BRANCH_TRANSACTION_THREAD_LOCK = threading.RLock()
_BRANCH_TRANSACTION_DEPTH = 0
_BRANCH_TRANSACTION_DESCRIPTOR: int | None = None
_BRANCH_TRANSACTION_PATH: Path | None = None


def _lock_branch_descriptor(descriptor: int) -> None:
    """Acquire a blocking cross-process lock for an open lock file."""
    if os.name == "nt":
        msvcrt: Any = importlib.import_module("msvcrt")
        if os.fstat(descriptor).st_size == 0:
            os.write(descriptor, b"\0")
            os.fsync(descriptor)
        os.lseek(descriptor, 0, os.SEEK_SET)
        while True:
            try:
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                return
            except OSError as exc:
                if exc.errno not in {
                    errno.EACCES,
                    errno.EAGAIN,
                    errno.EDEADLK,
                } and getattr(exc, "winerror", None) not in {33, 36}:
                    raise
                time.sleep(0.05)

    fcntl: Any = importlib.import_module("fcntl")
    fcntl.flock(descriptor, fcntl.LOCK_EX)


def _unlock_branch_descriptor(descriptor: int) -> None:
    """Release a lock acquired by :func:`_lock_branch_descriptor`."""
    if os.name == "nt":
        msvcrt: Any = importlib.import_module("msvcrt")
        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        return

    fcntl: Any = importlib.import_module("fcntl")
    fcntl.flock(descriptor, fcntl.LOCK_UN)


def acquire_branch_transaction(branch_dir: Path) -> None:
    """Serialize a complete branch read-modify-write transaction.

    The process-local ``RLock`` covers threads and makes nested calls reentrant;
    the persistent advisory lock file coordinates independent CLI processes.
    """
    global _BRANCH_TRANSACTION_DEPTH
    global _BRANCH_TRANSACTION_DESCRIPTOR
    global _BRANCH_TRANSACTION_PATH

    resolved_branch_dir = branch_dir.resolve()
    lock_path = (
        resolved_branch_dir.parent
        / ".locks"
        / f"{resolved_branch_dir.name}.transaction.lock"
    )
    _BRANCH_TRANSACTION_THREAD_LOCK.acquire()
    descriptor: int | None = None
    try:
        if _BRANCH_TRANSACTION_DEPTH:
            if _BRANCH_TRANSACTION_PATH != lock_path:
                raise RuntimeError(
                    "cannot nest MAP branch transactions for different directories"
                )
            _BRANCH_TRANSACTION_DEPTH += 1
            return

        lock_path.parent.mkdir(parents=True, exist_ok=True)
        flags = (
            os.O_RDWR
            | os.O_CREAT
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        descriptor = os.open(lock_path, flags, 0o600)
        _lock_branch_descriptor(descriptor)
        _BRANCH_TRANSACTION_DESCRIPTOR = descriptor
        _BRANCH_TRANSACTION_PATH = lock_path
        _BRANCH_TRANSACTION_DEPTH = 1
    except BaseException:
        if descriptor is not None:
            os.close(descriptor)
        _BRANCH_TRANSACTION_THREAD_LOCK.release()
        raise


def release_branch_transaction() -> None:
    """Release one nesting level of the current branch transaction."""
    global _BRANCH_TRANSACTION_DEPTH
    global _BRANCH_TRANSACTION_DESCRIPTOR
    global _BRANCH_TRANSACTION_PATH

    if _BRANCH_TRANSACTION_DEPTH <= 0:
        raise RuntimeError("no MAP branch transaction is currently held")

    descriptor: int | None = None
    try:
        _BRANCH_TRANSACTION_DEPTH -= 1
        if _BRANCH_TRANSACTION_DEPTH == 0:
            descriptor = _BRANCH_TRANSACTION_DESCRIPTOR
            _BRANCH_TRANSACTION_DESCRIPTOR = None
            _BRANCH_TRANSACTION_PATH = None
            if descriptor is None:
                raise RuntimeError("MAP branch transaction lost its lock descriptor")
            try:
                _unlock_branch_descriptor(descriptor)
            finally:
                os.close(descriptor)
    finally:
        _BRANCH_TRANSACTION_THREAD_LOCK.release()


@contextlib.contextmanager
def branch_transaction(branch_dir: Path) -> Iterator[None]:
    """Hold the shared branch lock for one complete state transaction."""
    acquire_branch_transaction(branch_dir)
    try:
        yield
    finally:
        release_branch_transaction()


def atomic_write_text(path: Path, content: str) -> None:
    """Atomically publish text through an invocation-unique sibling file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        stream = os.fdopen(descriptor, "w", encoding="utf-8", newline="\n")
        descriptor = -1
        with stream:
            stream.write(content)
        temporary_path.replace(path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary_path.unlink()
        except OSError:
            pass


def sanitize_branch_name(branch: str) -> str:
    """Normalize a branch name for safe use as a filesystem path component.

    Replaces ``/`` and any non-``[a-zA-Z0-9_.-]`` character with ``-``,
    collapses runs of hyphens, and strips leading/trailing hyphens. Refuses
    path-traversal patterns (``..`` anywhere, or a leading ``.``) by
    returning ``"default"``. Empty or all-stripped input also yields
    ``"default"`` so callers always get a non-empty, traversal-safe segment.
    """
    if not isinstance(branch, str):
        return "default"
    sanitized = branch.replace("/", "-")
    sanitized = re.sub(r"[^a-zA-Z0-9_.-]", "-", sanitized)
    sanitized = re.sub(r"-+", "-", sanitized).strip("-")
    if ".." in sanitized or sanitized.startswith("."):
        return "default"
    return sanitized or "default"


def get_branch_name() -> str:
    """Get sanitized git branch name.

    Returns the current git branch with unsafe characters replaced by hyphens.
    Falls back to 'default' on any error (not in a git repo, git not installed, etc.).
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=1,
            check=False,
        )
        if result.returncode == 0:
            return sanitize_branch_name(result.stdout.strip())
        return "default"
    except Exception:  # noqa: BLE001 -- deliberate fallback/resilience boundary, must not propagate
        return "default"
