from __future__ import annotations

import contextlib
import contextvars
import errno
import hashlib
import hmac
import importlib
import json
import os
import re
import secrets
import stat
import tempfile
import time
from collections.abc import Generator
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

if os.name == "nt":
    msvcrt: Any = importlib.import_module("msvcrt")
else:
    import fcntl


STATE_SCHEMA_VERSION = 2
STATE_RELATIVE_PATH = Path(".map/update-state.json")
MAP_UPDATE_PARENT_LEASE_ENV = "MAP_UPDATE_PARENT_LEASE"
UPDATE_INTERVAL = timedelta(hours=24)
_STABLE_VERSION_RE = re.compile(
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
)
_PROVIDERS = frozenset({"claude", "codex"})
_V1_KEYS = frozenset(
    {
        "schema_version",
        "last_attempt_at",
        "last_observed_version",
        "last_installed_version",
        "pending_refresh",
        "pending_providers",
    }
)
_V2_KEYS = _V1_KEYS | {"pending_install_version"}
_LEASE_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{43}")
_LOCK_RECORD_KEYS = frozenset(
    {"schema_version", "lease_digest", "owner_pid", "project"}
)


class UpdateLockBusy(RuntimeError):
    """Raised when another process holds a project's update lock."""


class UpdateLockSecurityError(RuntimeError):
    """Raised when the project lock path cannot be opened safely."""


class UpdateLeaseRejected(RuntimeError):
    """Raised when a provider child cannot prove direct updater authority."""


@dataclass(frozen=True)
class ProjectUpdateLease:
    """In-memory authority delegated only to direct provider-refresh children."""

    token: str
    owner_pid: int
    project: Path


_CURRENT_UPDATE_LEASE: contextvars.ContextVar[ProjectUpdateLease | None] = (
    contextvars.ContextVar("map_current_update_lease", default=None)
)


@dataclass(frozen=True)
class UpdateState:
    schema_version: int = STATE_SCHEMA_VERSION
    last_attempt_at: str | None = None
    last_observed_version: str | None = None
    last_installed_version: str | None = None
    pending_install_version: str | None = None
    pending_refresh: bool = False
    pending_providers: tuple[str, ...] = ()


def _state_from_payload(payload: Any) -> UpdateState | None:
    if not isinstance(payload, dict):
        return None
    if type(payload.get("schema_version")) is not int:
        return None
    schema_version = payload["schema_version"]
    expected_keys = _V1_KEYS if schema_version == 1 else _V2_KEYS
    if schema_version not in {1, STATE_SCHEMA_VERSION} or set(payload) != expected_keys:
        return None

    for field_name in (
        "last_attempt_at",
        "last_observed_version",
        "last_installed_version",
    ):
        value = payload.get(field_name)
        if value is not None and not isinstance(value, str):
            return None

    pending_refresh = payload.get("pending_refresh", False)
    if type(pending_refresh) is not bool:
        return None

    pending_providers = payload.get("pending_providers", [])
    if not isinstance(pending_providers, list) or not all(
        isinstance(provider, str) for provider in pending_providers
    ):
        return None
    pending_install_version = (
        None if schema_version == 1 else payload.get("pending_install_version")
    )
    if pending_install_version is not None and not isinstance(
        pending_install_version, str
    ):
        return None

    state = UpdateState(
        schema_version=STATE_SCHEMA_VERSION,
        last_attempt_at=payload.get("last_attempt_at"),
        last_observed_version=payload.get("last_observed_version"),
        last_installed_version=payload.get("last_installed_version"),
        pending_install_version=pending_install_version,
        pending_refresh=pending_refresh,
        pending_providers=tuple(pending_providers),
    )
    if _valid_state(state):
        return state
    if (
        schema_version == 1
        and state.pending_refresh
        and state.last_installed_version is not None
        and not state.pending_providers
        and _valid_state(replace(state, pending_providers=("claude",)))
    ):
        # Intent: v1 allowed provider-less refresh recovery. Keep it only as an
        # in-memory migration phase so the updater can discover and persist v2
        # provider authority before launching a child; v2 writes stay strict.
        return state
    return None


def _stable_version_or_none(value: str | None) -> bool:
    return value is None or _STABLE_VERSION_RE.fullmatch(value) is not None


def _valid_state(state: UpdateState) -> bool:
    if state.schema_version != STATE_SCHEMA_VERSION:
        return False
    if not all(
        _stable_version_or_none(value)
        for value in (
            state.last_observed_version,
            state.last_installed_version,
            state.pending_install_version,
        )
    ):
        return False
    providers = state.pending_providers
    if any(provider not in _PROVIDERS for provider in providers) or len(
        set(providers)
    ) != len(providers):
        return False

    has_install_intent = state.pending_install_version is not None
    if has_install_intent:
        return not state.pending_refresh and bool(providers)
    if state.pending_refresh:
        return state.last_installed_version is not None and bool(providers)
    return not providers


def read_update_state(project_path: Path) -> UpdateState:
    state_path = project_path / STATE_RELATIVE_PATH
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return UpdateState()
    return _state_from_payload(payload) or UpdateState()


def write_update_state(project_path: Path, state: UpdateState) -> None:
    if not _valid_state(state):
        raise ValueError("invalid MAP update state")
    state_path = project_path / STATE_RELATIVE_PATH
    state_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        dir=state_path.parent,
        prefix=f".{state_path.name}.",
        suffix=".tmp",
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as temp_file:
            json.dump(
                {
                    "schema_version": state.schema_version,
                    "last_attempt_at": state.last_attempt_at,
                    "last_observed_version": state.last_observed_version,
                    "last_installed_version": state.last_installed_version,
                    "pending_install_version": state.pending_install_version,
                    "pending_refresh": state.pending_refresh,
                    "pending_providers": list(state.pending_providers),
                },
                temp_file,
                sort_keys=True,
            )
            temp_file.write("\n")
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_path, state_path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def pending_refresh_state(
    project_path: Path,
    provider: str,
) -> UpdateState | None:
    """Return state only when it authorizes recovery for ``provider``."""
    state = read_update_state(project_path)
    if (
        state.pending_refresh
        and bool(state.last_installed_version)
        and provider in state.pending_providers
    ):
        return state
    return None


def complete_pending_provider_refresh(
    project_path: Path,
    provider: str,
) -> UpdateState:
    """Atomically remove one successfully refreshed provider from pending state.

    This transition deliberately does not acquire the project update lock: updater
    child processes run while their parent owns that lock.
    """
    state = pending_refresh_state(project_path, provider)
    if state is None:
        raise RuntimeError(
            f"Pending MAP refresh state no longer includes provider '{provider}'."
        )
    remaining = tuple(
        pending_provider
        for pending_provider in state.pending_providers
        if pending_provider != provider
    )
    completed = replace(
        state,
        pending_refresh=bool(remaining),
        pending_providers=remaining,
    )
    write_update_state(project_path, completed)
    return completed


def automatic_check_due(state: UpdateState, now: datetime) -> bool:
    previous_raw = state.last_attempt_at
    if previous_raw is None or not previous_raw.endswith("Z"):
        return True
    try:
        previous = datetime.fromisoformat(f"{previous_raw[:-1]}+00:00")
        elapsed = now - previous
    except (TypeError, ValueError):
        return True
    return elapsed >= UPDATE_INTERVAL


if os.name == "nt":

    def _try_lock(fd: int) -> None:
        # Intent: Windows byte-range locks need a persistent byte to lock.
        if os.fstat(fd).st_size == 0:
            os.lseek(fd, 0, os.SEEK_SET)
            os.write(fd, b"\0")
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise BlockingIOError(exc.errno, str(exc)) from exc
            raise

    def _unlock(fd: int) -> None:
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            return

else:

    def _try_lock(fd: int) -> None:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN):
                raise BlockingIOError(exc.errno, str(exc)) from exc
            raise

    def _unlock(fd: int) -> None:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            return


def _lock_security_error(lock_path: Path) -> UpdateLockSecurityError:
    return UpdateLockSecurityError(str(lock_path))


def _prepare_lock_directory(lock_path: Path, *, create: bool) -> os.stat_result:
    map_dir = lock_path.parent
    if create:
        try:
            map_dir.mkdir(mode=0o700)
        except FileExistsError:
            pass
    try:
        map_stat = os.lstat(map_dir)
        resolved_map_dir = map_dir.resolve(strict=True)
    except OSError as exc:
        raise _lock_security_error(lock_path) from exc
    if (
        stat.S_ISLNK(map_stat.st_mode)
        or not stat.S_ISDIR(map_stat.st_mode)
        or resolved_map_dir != map_dir
    ):
        raise _lock_security_error(lock_path)
    return map_stat


def _validate_lock_file_identity(
    fd: int,
    lock_path: Path,
    map_identity: tuple[int, int],
) -> None:
    try:
        fd_stat = os.fstat(fd)
        path_stat = os.lstat(lock_path)
        map_stat = os.lstat(lock_path.parent)
        resolved_map_dir = lock_path.parent.resolve(strict=True)
    except OSError as exc:
        raise _lock_security_error(lock_path) from exc
    if (
        not stat.S_ISREG(fd_stat.st_mode)
        or fd_stat.st_nlink != 1
        or stat.S_ISLNK(path_stat.st_mode)
        or not stat.S_ISREG(path_stat.st_mode)
        or path_stat.st_nlink != 1
        or (path_stat.st_dev, path_stat.st_ino) != (fd_stat.st_dev, fd_stat.st_ino)
        or stat.S_ISLNK(map_stat.st_mode)
        or not stat.S_ISDIR(map_stat.st_mode)
        or (map_stat.st_dev, map_stat.st_ino) != map_identity
        or resolved_map_dir != lock_path.parent
    ):
        raise _lock_security_error(lock_path)


def _open_lock_file(lock_path: Path, *, create: bool) -> int:
    map_stat = _prepare_lock_directory(lock_path, create=create)
    map_identity = (map_stat.st_dev, map_stat.st_ino)
    try:
        existing_stat = os.lstat(lock_path)
    except FileNotFoundError:
        existing_stat = None
    except OSError as exc:
        raise _lock_security_error(lock_path) from exc
    if existing_stat is not None and (
        stat.S_ISLNK(existing_stat.st_mode)
        or not stat.S_ISREG(existing_stat.st_mode)
        or existing_stat.st_nlink != 1
    ):
        raise _lock_security_error(lock_path)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    flags = os.O_RDWR | (os.O_CREAT if create else 0) | nofollow
    try:
        fd = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.EMLINK):
            raise _lock_security_error(lock_path) from exc
        raise

    try:
        # Intent: Match path, descriptor, and parent identities after opening;
        # reject non-regular or multiply-linked files before chmod or writes.
        _validate_lock_file_identity(fd, lock_path, map_identity)
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        return fd
    except BaseException:
        os.close(fd)
        raise


def _acquire_fd(fd: int, lock_path: Path, timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            _try_lock(fd)
            return
        except BlockingIOError as exc:
            if time.monotonic() >= deadline:
                raise UpdateLockBusy(str(lock_path)) from exc
            time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))


def _write_fd(fd: int, lock_path: Path, data: bytes) -> None:
    map_stat = _prepare_lock_directory(lock_path, create=False)
    _validate_lock_file_identity(
        fd,
        lock_path,
        (map_stat.st_dev, map_stat.st_ino),
    )
    os.lseek(fd, 0, os.SEEK_SET)
    os.ftruncate(fd, 0)
    remaining = memoryview(data)
    while remaining:
        written = os.write(fd, remaining)
        if written <= 0:
            raise OSError("failed to write MAP update lock record")
        remaining = remaining[written:]
    os.fsync(fd)


def _write_lock_record(
    fd: int,
    lock_path: Path,
    lease: ProjectUpdateLease,
) -> None:
    payload = {
        "schema_version": 1,
        "lease_digest": hashlib.sha256(lease.token.encode()).hexdigest(),
        "owner_pid": lease.owner_pid,
        "project": str(lease.project),
    }
    _write_fd(
        fd,
        lock_path,
        (json.dumps(payload, sort_keys=True) + "\n").encode(),
    )


def _read_lock_record(fd: int) -> dict[str, Any] | None:
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        raw = os.read(fd, 2_049)
        if len(raw) > 2_048:
            return None
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or set(payload) != _LOCK_RECORD_KEYS:
        return None
    if payload.get("schema_version") != 1:
        return None
    if not isinstance(payload.get("lease_digest"), str):
        return None
    if type(payload.get("owner_pid")) is not int or payload["owner_pid"] <= 0:
        return None
    if not isinstance(payload.get("project"), str):
        return None
    return payload


def current_project_update_lease(project_path: Path) -> ProjectUpdateLease | None:
    """Return this context's lease only for its exact resolved project."""
    lease = _CURRENT_UPDATE_LEASE.get()
    if lease is None or lease.project != project_path.resolve():
        return None
    return lease


def _state_authorizes_provider_child(
    state: UpdateState,
    provider: str,
    running_version: str,
) -> bool:
    if provider not in state.pending_providers:
        return False
    if state.pending_install_version is not None:
        return (
            not state.pending_refresh
            and state.pending_install_version == running_version
        )
    return state.pending_refresh and state.last_installed_version == running_version


def validate_parent_update_lease(
    project_path: Path,
    provider: str,
    running_version: str,
    raw_lease: str | None,
) -> bool:
    """Validate a direct updater parent's active, project-bound refresh lease."""
    if raw_lease is None or _LEASE_TOKEN_RE.fullmatch(raw_lease) is None:
        return False
    project = project_path.resolve()
    if not _state_authorizes_provider_child(
        read_update_state(project), provider, running_version
    ):
        return False

    lock_path = project / ".map" / "update.lock"
    try:
        fd = _open_lock_file(lock_path, create=False)
    except (OSError, UpdateLockSecurityError):
        return False
    try:
        try:
            _try_lock(fd)
        except BlockingIOError:
            record = _read_lock_record(fd)
        else:
            # Intent: A persisted digest without active lock contention is stale.
            _unlock(fd)
            return False
    finally:
        os.close(fd)

    if record is None:
        return False
    expected_digest = hashlib.sha256(raw_lease.encode()).hexdigest()
    return (
        hmac.compare_digest(record["lease_digest"], expected_digest)
        and record["owner_pid"] == os.getppid()
        and record["project"] == str(project)
    )


@contextlib.contextmanager
def provider_refresh_lock(
    project_path: Path,
    *,
    timeout_s: float,
) -> Generator[None, None, None]:
    """Serialize provider mutation independently from an updater parent lifetime."""
    lock_path = project_path.resolve() / ".map" / "provider-refresh.lock"
    fd = _open_lock_file(lock_path, create=True)
    acquired = False
    try:
        _acquire_fd(fd, lock_path, timeout_s)
        acquired = True
        yield
    finally:
        try:
            if acquired:
                _unlock(fd)
        finally:
            os.close(fd)


@contextlib.contextmanager
def installer_process_lock(
    project_path: Path,
    *,
    timeout_s: float,
) -> Generator[None, None, None]:
    """Serialize package mutation across updater-parent process death."""
    lock_path = project_path.resolve() / ".map" / "installer.lock"
    fd = _open_lock_file(lock_path, create=True)
    acquired = False
    try:
        _acquire_fd(fd, lock_path, timeout_s)
        acquired = True
        yield
    finally:
        try:
            if acquired:
                _unlock(fd)
        finally:
            os.close(fd)


@contextlib.contextmanager
def installer_process_probe(
    project_path: Path,
    *,
    timeout_s: float,
) -> Generator[None, None, None]:
    """Probe an existing child-owned installer barrier without creating one."""
    lock_path = project_path.resolve() / ".map" / "installer.lock"
    try:
        os.lstat(lock_path.parent)
    except FileNotFoundError:
        # A live controller necessarily created both the directory and lock file
        # before READY, so an absent directory is also an absent barrier.
        yield
        return
    except OSError as exc:
        raise _lock_security_error(lock_path) from exc
    try:
        fd = _open_lock_file(lock_path, create=False)
    except FileNotFoundError:
        # An authorized installer controller creates and owns this file before GO.
        # A controller that has not created it cannot have received GO, and exits
        # on control-pipe EOF if its updater parent is already dead.
        yield
        return
    acquired = False
    try:
        _acquire_fd(fd, lock_path, timeout_s)
        acquired = True
        yield
    finally:
        try:
            if acquired:
                _unlock(fd)
        finally:
            os.close(fd)


def _promote_matching_install_intent(
    project_path: Path,
    state: UpdateState,
    running_version: str,
) -> UpdateState:
    if state.pending_install_version != running_version:
        return state
    promoted = replace(
        state,
        last_installed_version=running_version,
        pending_install_version=None,
        pending_refresh=True,
    )
    write_update_state(project_path, promoted)
    return promoted


def _validate_refresh_phase_for_running_version(
    state: UpdateState,
    running_version: str,
) -> None:
    if state.pending_install_version is not None and (
        state.pending_install_version != running_version
    ):
        raise UpdateLeaseRejected(
            "pending MAP installation does not match the running mapify version"
        )
    if state.pending_refresh and state.last_installed_version != running_version:
        raise UpdateLeaseRejected(
            "pending MAP refresh does not match the running mapify version"
        )


@contextlib.contextmanager
def provider_refresh_session(
    project_path: Path,
    *,
    provider: str,
    running_version: str,
    raw_parent_lease: str | None,
    timeout_s: float,
    detected_providers: tuple[str, ...] = (),
) -> Generator[None, None, None]:
    """Serialize one complete ``init --refresh-existing`` mutation."""
    project = project_path.resolve()
    if raw_parent_lease is not None:
        # Intent: The parent retains update.lock; the child owns only the orphan
        # barrier, avoiding a recursive acquisition deadlock. Validate only after
        # acquiring that barrier: if the parent dies in between, a delayed child
        # cannot cross a replacement updater's already-completed barrier probe.
        with provider_refresh_lock(project, timeout_s=timeout_s):
            if not validate_parent_update_lease(
                project,
                provider,
                running_version,
                raw_parent_lease,
            ):
                raise UpdateLeaseRejected("invalid parent update lease")
            state = read_update_state(project)
            if not _state_authorizes_provider_child(state, provider, running_version):
                raise UpdateLeaseRejected("invalid parent update lease state")
            _promote_matching_install_intent(project, state, running_version)
            yield
        return

    # Intent: Standalone recovery follows update -> installer -> provider order.
    # The installer probe prevents a direct recovery command from refreshing files
    # while a package-manager child outlives its updater parent.
    with (
        project_update_lock(project, timeout_s=timeout_s),
        installer_process_probe(project, timeout_s=timeout_s),
        provider_refresh_lock(project, timeout_s=timeout_s),
    ):
        state = read_update_state(project)
        _validate_refresh_phase_for_running_version(state, running_version)
        if state.pending_refresh and not state.pending_providers:
            if (
                not detected_providers
                or provider not in detected_providers
                or any(
                    detected_provider not in _PROVIDERS
                    for detected_provider in detected_providers
                )
                or len(set(detected_providers)) != len(detected_providers)
            ):
                raise UpdateLeaseRejected(
                    "legacy pending MAP refresh has no canonical installed provider set"
                )
            # Intent: v1 allowed a provider-less pending refresh. Persist full
            # provider authority under both locks before any standalone mutation,
            # so each successful init can narrow and eventually clear the state.
            state = replace(state, pending_providers=detected_providers)
            write_update_state(project, state)
        _promote_matching_install_intent(project, state, running_version)
        yield


@contextlib.contextmanager
def project_update_lock(
    project_path: Path,
    *,
    timeout_s: float,
) -> Generator[ProjectUpdateLease, None, None]:
    project = project_path.resolve()
    lock_path = project / ".map" / "update.lock"
    fd = _open_lock_file(lock_path, create=True)
    acquired = False
    context_token: contextvars.Token[ProjectUpdateLease | None] | None = None
    try:
        _acquire_fd(fd, lock_path, timeout_s)
        acquired = True
        lease = ProjectUpdateLease(
            token=secrets.token_urlsafe(32),
            owner_pid=os.getpid(),
            project=project,
        )
        _write_lock_record(fd, lock_path, lease)
        context_token = _CURRENT_UPDATE_LEASE.set(lease)
        yield lease
    finally:
        try:
            if context_token is not None:
                _CURRENT_UPDATE_LEASE.reset(context_token)
            if acquired:
                try:
                    with contextlib.suppress(OSError):
                        _write_fd(fd, lock_path, b"")
                finally:
                    _unlock(fd)
        finally:
            os.close(fd)
