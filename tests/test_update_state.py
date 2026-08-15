from __future__ import annotations

import contextlib
import hashlib
import json
import os
import queue
import re
import stat
import subprocess
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any, cast

import pytest

import mapify_cli.update_state as update_state_module
from mapify_cli.update_state import (
    STATE_SCHEMA_VERSION,
    UpdateLockBusy,
    UpdateLockSecurityError,
    UpdateState,
    automatic_check_due,
    project_update_lock,
    read_update_state,
    write_update_state,
)

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)

LOCK_HOLDER = """
import sys
from pathlib import Path

from mapify_cli.update_state import project_update_lock

with project_update_lock(Path(sys.argv[1]), timeout_s=0.0):
    print("READY", flush=True)
    input()
"""


def test_state_round_trip_is_project_local(tmp_path: Path) -> None:
    state = UpdateState(
        last_attempt_at="2026-08-13T11:00:00Z",
        last_installed_version="3.25.1",
    )

    write_update_state(tmp_path, state)

    assert read_update_state(tmp_path) == state
    assert (tmp_path / ".map" / "update-state.json").is_file()


def test_state_write_replaces_the_previous_document(tmp_path: Path) -> None:
    write_update_state(tmp_path, UpdateState(last_observed_version="3.25.1"))

    write_update_state(
        tmp_path,
        UpdateState(
            last_observed_version="3.26.0",
            last_installed_version="3.26.0",
            pending_refresh=True,
            pending_providers=("claude",),
        ),
    )

    payload = json.loads(
        (tmp_path / ".map" / "update-state.json").read_text(encoding="utf-8")
    )
    assert payload == {
        "last_attempt_at": None,
        "last_installed_version": "3.26.0",
        "last_observed_version": "3.26.0",
        "pending_install_version": None,
        "pending_providers": ["claude"],
        "pending_refresh": True,
        "schema_version": 2,
    }


def test_schema_v1_idle_state_migrates_strictly_to_v2(tmp_path: Path) -> None:
    state_path = tmp_path / ".map" / "update-state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "last_attempt_at": "2026-08-13T11:00:00Z",
                "last_observed_version": "3.26.0",
                "last_installed_version": "3.25.1",
                "pending_refresh": False,
                "pending_providers": [],
            }
        ),
        encoding="utf-8",
    )

    assert read_update_state(tmp_path) == UpdateState(
        schema_version=2,
        last_attempt_at="2026-08-13T11:00:00Z",
        last_observed_version="3.26.0",
        last_installed_version="3.25.1",
        pending_install_version=None,
        pending_refresh=False,
        pending_providers=(),
    )
    assert STATE_SCHEMA_VERSION == 2


def test_schema_v1_refresh_state_migrates_strictly_to_v2(tmp_path: Path) -> None:
    state_path = tmp_path / ".map" / "update-state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "last_attempt_at": None,
                "last_observed_version": "3.26.0",
                "last_installed_version": "3.26.0",
                "pending_refresh": True,
                "pending_providers": ["claude", "codex"],
            }
        ),
        encoding="utf-8",
    )

    assert read_update_state(tmp_path) == UpdateState(
        schema_version=2,
        last_observed_version="3.26.0",
        last_installed_version="3.26.0",
        pending_refresh=True,
        pending_providers=("claude", "codex"),
    )


def test_schema_v1_refresh_without_providers_remains_transitional_for_discovery(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / ".map" / "update-state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "last_attempt_at": "2026-08-13T11:00:00Z",
                "last_observed_version": "3.26.0",
                "last_installed_version": "3.26.0",
                "pending_refresh": True,
                "pending_providers": [],
            }
        ),
        encoding="utf-8",
    )

    assert read_update_state(tmp_path) == UpdateState(
        schema_version=2,
        last_attempt_at="2026-08-13T11:00:00Z",
        last_observed_version="3.26.0",
        last_installed_version="3.26.0",
        pending_refresh=True,
        pending_providers=(),
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("last_observed_version", "3.26.0rc1"),
        ("last_installed_version", "3.26.0rc1"),
    ],
)
def test_schema_v1_providerless_transition_still_rejects_unstable_versions(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    payload: dict[str, object] = {
        "schema_version": 1,
        "last_attempt_at": "2026-08-13T11:00:00Z",
        "last_observed_version": "3.26.0",
        "last_installed_version": "3.26.0",
        "pending_refresh": True,
        "pending_providers": [],
    }
    payload[field] = value
    state_path = tmp_path / ".map" / "update-state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps(payload), encoding="utf-8")

    assert read_update_state(tmp_path) == UpdateState()


@pytest.mark.parametrize(
    "state",
    [
        UpdateState(
            pending_install_version="3.26.0",
            pending_refresh=True,
            pending_providers=("claude",),
        ),
        UpdateState(pending_install_version="3.26.0"),
        UpdateState(pending_providers=("claude",)),
        UpdateState(
            pending_refresh=True,
            pending_providers=("claude",),
        ),
        UpdateState(
            last_installed_version="3.26.0",
            pending_refresh=True,
        ),
        UpdateState(
            pending_install_version="3.26.0rc1",
            pending_providers=("claude",),
        ),
        UpdateState(
            pending_install_version="3.26.0",
            pending_providers=("unknown",),
        ),
        UpdateState(
            pending_install_version="3.26.0",
            pending_providers=("claude", "claude"),
        ),
    ],
)
def test_write_rejects_invalid_or_mixed_update_phases(
    tmp_path: Path,
    state: UpdateState,
) -> None:
    with pytest.raises(ValueError, match="invalid MAP update state"):
        write_update_state(tmp_path, state)

    assert not (tmp_path / ".map" / "update-state.json").exists()


def test_failed_state_replace_preserves_old_state_and_removes_tempfile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path = tmp_path / ".map" / "update-state.json"
    original_state = UpdateState(last_observed_version="3.25.1")
    write_update_state(tmp_path, original_state)

    replace_error = OSError("replace failed")

    def fail_replace(source: Path, destination: Path) -> None:
        raise replace_error

    monkeypatch.setattr(update_state_module.os, "replace", fail_replace)

    with pytest.raises(OSError) as caught:
        write_update_state(
            tmp_path,
            UpdateState(last_observed_version="3.26.0"),
        )

    assert caught.value is replace_error
    assert read_update_state(tmp_path) == original_state
    assert list(state_path.parent.glob(f".{state_path.name}.*.tmp")) == []


@pytest.mark.parametrize(
    "payload",
    [
        "not-json",
        "[]",
        '{"schema_version": 2}',
        '{"schema_version": true}',
        '{"schema_version": 1, "last_attempt_at": 123}',
        '{"schema_version": 1, "last_observed_version": []}',
        '{"schema_version": 1, "last_installed_version": false}',
        '{"schema_version": 1, "pending_refresh": 1}',
        '{"schema_version": 1, "pending_providers": ["codex", 2]}',
        ('{"schema_version": 1, "last_attempt_at": "2026-08-13T11:00:00Z"}'),
    ],
)
def test_corrupt_state_becomes_default_cache_miss(
    tmp_path: Path,
    payload: str,
) -> None:
    path = tmp_path / ".map" / "update-state.json"
    path.parent.mkdir(parents=True)
    path.write_text(payload, encoding="utf-8")

    assert read_update_state(tmp_path) == UpdateState()


def test_missing_state_is_a_default_cache_miss(tmp_path: Path) -> None:
    assert read_update_state(tmp_path) == UpdateState()


def test_pending_refresh_state_requires_flag_version_and_provider_membership(
    tmp_path: Path,
) -> None:
    pending_refresh_state = getattr(
        update_state_module,
        "pending_refresh_state",
        None,
    )
    assert callable(
        pending_refresh_state
    ), "pending provider recovery needs an explicit validated-state boundary"
    valid = UpdateState(
        last_installed_version="3.26.0",
        pending_refresh=True,
        pending_providers=("claude",),
    )
    write_update_state(tmp_path, valid)
    assert pending_refresh_state(tmp_path, "claude") == valid

    invalid_states = (
        UpdateState(
            last_installed_version="3.26.0",
            pending_refresh=False,
            pending_providers=("claude",),
        ),
        UpdateState(
            pending_refresh=True,
            pending_providers=("claude",),
        ),
        UpdateState(
            last_installed_version="3.26.0",
            pending_refresh=True,
            pending_providers=("codex",),
        ),
    )
    for state in invalid_states:
        state_path = tmp_path / ".map" / "update-state.json"
        state_path.write_text(
            json.dumps(
                {
                    "schema_version": state.schema_version,
                    "last_attempt_at": state.last_attempt_at,
                    "last_observed_version": state.last_observed_version,
                    "last_installed_version": state.last_installed_version,
                    "pending_install_version": state.pending_install_version,
                    "pending_refresh": state.pending_refresh,
                    "pending_providers": list(state.pending_providers),
                }
            ),
            encoding="utf-8",
        )
        assert pending_refresh_state(tmp_path, "claude") is None


def test_complete_pending_provider_refresh_narrows_then_clears_state(
    tmp_path: Path,
) -> None:
    complete_pending_provider_refresh = getattr(
        update_state_module,
        "complete_pending_provider_refresh",
        None,
    )
    assert callable(
        complete_pending_provider_refresh
    ), "successful standalone recovery needs a provider completion transition"
    write_update_state(
        tmp_path,
        UpdateState(
            last_installed_version="3.26.0",
            pending_refresh=True,
            pending_providers=("claude", "codex"),
        ),
    )

    narrowed = complete_pending_provider_refresh(tmp_path, "claude")

    assert narrowed.pending_refresh is True
    assert narrowed.pending_providers == ("codex",)
    assert read_update_state(tmp_path) == narrowed

    completed = complete_pending_provider_refresh(tmp_path, "codex")

    assert completed.pending_refresh is False
    assert completed.pending_providers == ()
    assert completed.last_installed_version == "3.26.0"
    assert read_update_state(tmp_path) == completed


@pytest.mark.parametrize(
    ("last_attempt_at", "expected"),
    [
        (None, True),
        ("invalid", True),
        ("2026-08-12T11:59:59Z", True),
        ("2026-08-12T12:00:00Z", True),
        ("2026-08-12T12:00:01Z", False),
    ],
)
def test_automatic_check_due_uses_rolling_24_hours(
    last_attempt_at: str | None,
    expected: bool,
) -> None:
    state = UpdateState(last_attempt_at=last_attempt_at)

    assert automatic_check_due(state, NOW) is expected


def test_second_project_lock_is_busy(tmp_path: Path) -> None:
    with (
        project_update_lock(tmp_path, timeout_s=0.0),
        pytest.raises(UpdateLockBusy),
        project_update_lock(tmp_path, timeout_s=0.0),
    ):
        raise AssertionError("contender must not acquire")


def test_lock_refuses_symlink(tmp_path: Path) -> None:
    map_dir = tmp_path / ".map"
    map_dir.mkdir()
    (map_dir / "target").touch()
    (map_dir / "update.lock").symlink_to(map_dir / "target")

    with (
        pytest.raises(UpdateLockSecurityError),
        project_update_lock(tmp_path, timeout_s=0.0),
    ):
        raise AssertionError("symlink lock must not open")


@pytest.mark.parametrize(
    "lock_name", ["update.lock", "installer.lock", "provider-refresh.lock"]
)
def test_lock_refuses_symlinked_map_ancestor_without_outside_creation(
    tmp_path: Path,
    lock_name: str,
) -> None:
    outside = tmp_path / "outside-map"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_bytes(b"outside-bytes")
    (tmp_path / ".map").symlink_to(outside, target_is_directory=True)
    lock = {
        "update.lock": project_update_lock,
        "installer.lock": update_state_module.installer_process_lock,
        "provider-refresh.lock": update_state_module.provider_refresh_lock,
    }[lock_name]

    with pytest.raises(UpdateLockSecurityError), lock(tmp_path, timeout_s=0.0):
        raise AssertionError("a symlinked .map ancestor must not be used")

    assert sentinel.read_bytes() == b"outside-bytes"
    assert not (outside / lock_name).exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX hardlink security contract")
@pytest.mark.parametrize(
    "lock_name", ["update.lock", "installer.lock", "provider-refresh.lock"]
)
def test_lock_refuses_hardlinked_sentinel_without_mutating_outside_file(
    tmp_path: Path,
    lock_name: str,
) -> None:
    map_dir = tmp_path / ".map"
    map_dir.mkdir()
    outside = tmp_path / f"outside-{lock_name}"
    outside.write_bytes(b"outside-lock-sentinel")
    outside.chmod(0o644)
    try:
        os.link(outside, map_dir / lock_name)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"hardlinks unavailable: {exc}")
    lock = {
        "update.lock": project_update_lock,
        "installer.lock": update_state_module.installer_process_lock,
        "provider-refresh.lock": update_state_module.provider_refresh_lock,
    }[lock_name]

    with pytest.raises(UpdateLockSecurityError), lock(tmp_path, timeout_s=0.0):
        raise AssertionError("a hardlinked lock must not open")

    assert outside.read_bytes() == b"outside-lock-sentinel"
    assert stat.S_IMODE(outside.stat().st_mode) == 0o644


@pytest.mark.parametrize(
    "lock_name", ["update.lock", "installer.lock", "provider-refresh.lock"]
)
def test_lock_refuses_nonregular_path(tmp_path: Path, lock_name: str) -> None:
    map_dir = tmp_path / ".map"
    map_dir.mkdir()
    lock_path = map_dir / lock_name
    lock_path.mkdir()
    lock = {
        "update.lock": project_update_lock,
        "installer.lock": update_state_module.installer_process_lock,
        "provider-refresh.lock": update_state_module.provider_refresh_lock,
    }[lock_name]

    with pytest.raises(UpdateLockSecurityError), lock(tmp_path, timeout_s=0.0):
        raise AssertionError("a non-regular lock must not open")

    assert lock_path.is_dir()


def test_lock_file_persists_with_owner_only_permissions(tmp_path: Path) -> None:
    lock_path = tmp_path / ".map" / "update.lock"

    with project_update_lock(tmp_path, timeout_s=0.0):
        assert lock_path.is_file()

    assert lock_path.is_file()
    if os.name != "nt":
        assert stat.S_IMODE(lock_path.stat().st_mode) == 0o600


def test_project_lock_yields_random_lease_without_persisting_raw_secret(
    tmp_path: Path,
) -> None:
    with project_update_lock(tmp_path, timeout_s=0.0) as first:
        assert re.fullmatch(r"[A-Za-z0-9_-]{43}", first.token)
        assert first.owner_pid == os.getpid()
        record_text = (tmp_path / ".map" / "update.lock").read_text(encoding="utf-8")
        record = json.loads(record_text)
        assert first.token not in record_text
        assert record == {
            "lease_digest": hashlib.sha256(first.token.encode()).hexdigest(),
            "owner_pid": os.getpid(),
            "project": str(tmp_path.resolve()),
            "schema_version": 1,
        }

    with project_update_lock(tmp_path, timeout_s=0.0) as second:
        assert second.token != first.token


def test_parent_lease_requires_active_lock_exact_parent_project_and_refresh_phase(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validate = getattr(update_state_module, "validate_parent_update_lease", None)
    assert callable(validate), "provider children need a validated lease boundary"
    write_update_state(
        tmp_path,
        UpdateState(
            last_installed_version="3.26.0",
            pending_refresh=True,
            pending_providers=("claude",),
        ),
    )

    with project_update_lock(tmp_path, timeout_s=0.0) as lease:
        monkeypatch.setattr(update_state_module.os, "getppid", lambda: lease.owner_pid)
        assert validate(tmp_path, "claude", "3.26.0", lease.token) is True
        assert validate(tmp_path, "claude", "3.26.0", None) is False
        assert validate(tmp_path, "claude", "3.26.0", "x" * 43) is False
        assert validate(tmp_path, "codex", "3.26.0", lease.token) is False
        assert validate(tmp_path, "claude", "3.25.0", lease.token) is False
        assert validate(tmp_path / "other", "claude", "3.26.0", lease.token) is False
        monkeypatch.setattr(
            update_state_module.os, "getppid", lambda: lease.owner_pid + 1
        )
        assert validate(tmp_path, "claude", "3.26.0", lease.token) is False

    monkeypatch.setattr(update_state_module.os, "getppid", lambda: lease.owner_pid)
    assert validate(tmp_path, "claude", "3.26.0", lease.token) is False


def test_parent_lease_accepts_only_matching_install_intent_phase(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validate = getattr(update_state_module, "validate_parent_update_lease", None)
    assert callable(validate)
    write_update_state(
        tmp_path,
        UpdateState(
            pending_install_version="3.26.0",
            pending_providers=("claude",),
        ),
    )

    with project_update_lock(tmp_path, timeout_s=0.0) as lease:
        monkeypatch.setattr(update_state_module.os, "getppid", lambda: lease.owner_pid)
        assert validate(tmp_path, "claude", "3.26.0", lease.token) is True
        assert validate(tmp_path, "claude", "3.25.0", lease.token) is False


def test_provider_refresh_lock_is_an_independent_orphan_barrier(
    tmp_path: Path,
) -> None:
    refresh_lock = getattr(update_state_module, "provider_refresh_lock", None)
    assert callable(refresh_lock), "orphan refreshes need their own barrier lock"

    with (
        refresh_lock(tmp_path, timeout_s=0.0),
        pytest.raises(UpdateLockBusy),
        refresh_lock(tmp_path, timeout_s=0.0),
    ):
        raise AssertionError("a second provider refresh must not overlap")

    with (
        project_update_lock(tmp_path, timeout_s=0.0),
        refresh_lock(tmp_path, timeout_s=0.0),
    ):
        assert (tmp_path / ".map" / "provider-refresh.lock").is_file()


def test_installer_process_lock_is_an_independent_orphan_barrier(
    tmp_path: Path,
) -> None:
    installer_lock = getattr(update_state_module, "installer_process_lock", None)
    assert callable(installer_lock), "orphan installers need their own barrier lock"

    with (
        installer_lock(tmp_path, timeout_s=0.0),
        pytest.raises(UpdateLockBusy),
        installer_lock(tmp_path, timeout_s=0.0),
    ):
        raise AssertionError("a second installer must not cross the barrier")


def test_installer_probe_does_not_create_barrier_when_no_controller_exists(
    tmp_path: Path,
) -> None:
    probe = getattr(update_state_module, "installer_process_probe", None)
    assert callable(probe)
    (tmp_path / ".map").mkdir()

    with probe(tmp_path, timeout_s=0.0):
        pass

    assert not (tmp_path / ".map" / "installer.lock").exists()


def test_standalone_provider_refresh_session_owns_locks_in_global_order(
    tmp_path: Path,
) -> None:
    session = getattr(update_state_module, "provider_refresh_session", None)
    assert callable(session), "refresh-existing needs a serialized session boundary"

    with session(
        tmp_path,
        provider="claude",
        running_version="3.26.0",
        raw_parent_lease=None,
        timeout_s=0.0,
    ):
        with (
            pytest.raises(UpdateLockBusy),
            project_update_lock(tmp_path, timeout_s=0.0),
        ):
            raise AssertionError("standalone refresh must own update.lock")
        with (
            pytest.raises(UpdateLockBusy),
            update_state_module.provider_refresh_lock(tmp_path, timeout_s=0.0),
        ):
            raise AssertionError("standalone refresh must own provider-refresh.lock")


def test_standalone_provider_refresh_waits_for_orphan_installer(
    tmp_path: Path,
) -> None:
    installer_lock = getattr(update_state_module, "installer_process_lock", None)
    session = getattr(update_state_module, "provider_refresh_session", None)
    assert callable(installer_lock)
    assert callable(session)
    write_update_state(
        tmp_path,
        UpdateState(
            last_installed_version="3.26.0",
            pending_refresh=True,
            pending_providers=("claude",),
        ),
    )

    with (
        installer_lock(tmp_path, timeout_s=0.0),
        pytest.raises(UpdateLockBusy),
        session(
            tmp_path,
            provider="claude",
            running_version="3.26.0",
            raw_parent_lease=None,
            timeout_s=0.0,
        ),
    ):
        raise AssertionError("refresh must not overlap an orphan installer")


def test_borrowed_provider_refresh_session_promotes_matching_intent_without_deadlock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = getattr(update_state_module, "provider_refresh_session", None)
    assert callable(session)
    write_update_state(
        tmp_path,
        UpdateState(
            pending_install_version="3.26.0",
            pending_providers=("claude", "codex"),
        ),
    )

    with project_update_lock(tmp_path, timeout_s=0.0) as lease:
        monkeypatch.setattr(update_state_module.os, "getppid", lambda: lease.owner_pid)
        with session(
            tmp_path,
            provider="claude",
            running_version="3.26.0",
            raw_parent_lease=lease.token,
            timeout_s=0.0,
        ):
            state = read_update_state(tmp_path)
            assert state.pending_install_version is None
            assert state.last_installed_version == "3.26.0"
            assert state.pending_refresh is True
            assert state.pending_providers == ("claude", "codex")


def test_borrowed_refresh_revalidates_parent_inside_provider_barrier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_update_state(
        tmp_path,
        UpdateState(
            last_installed_version="3.26.0",
            pending_refresh=True,
            pending_providers=("claude",),
        ),
    )
    barrier_held = False

    @contextlib.contextmanager
    def observed_provider_barrier(
        _project_path: Path,
        *,
        timeout_s: float,
    ) -> Any:
        nonlocal barrier_held
        assert timeout_s == 0.0
        barrier_held = True
        try:
            yield
        finally:
            barrier_held = False

    def validate_inside_barrier(*_args: object, **_kwargs: object) -> bool:
        assert barrier_held, (
            "parent death after validation must not let a delayed child cross a "
            "replacement updater's completed barrier probe"
        )
        return True

    monkeypatch.setattr(
        update_state_module,
        "provider_refresh_lock",
        observed_provider_barrier,
    )
    monkeypatch.setattr(
        update_state_module,
        "validate_parent_update_lease",
        validate_inside_barrier,
    )

    with update_state_module.provider_refresh_session(
        tmp_path,
        provider="claude",
        running_version="3.26.0",
        raw_parent_lease="x" * 43,
        timeout_s=0.0,
    ):
        assert barrier_held


@pytest.mark.parametrize("raw_lease", [None, "x" * 43])
def test_parent_refresh_session_rejects_missing_or_forged_lease_under_contention(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    raw_lease: str | None,
) -> None:
    session = getattr(update_state_module, "provider_refresh_session", None)
    rejection = getattr(update_state_module, "UpdateLeaseRejected", RuntimeError)
    assert callable(session)
    write_update_state(
        tmp_path,
        UpdateState(
            last_installed_version="3.26.0",
            pending_refresh=True,
            pending_providers=("claude",),
        ),
    )

    with project_update_lock(tmp_path, timeout_s=0.0) as lease:
        monkeypatch.setattr(update_state_module.os, "getppid", lambda: lease.owner_pid)
        if raw_lease is None:
            with (
                pytest.raises(UpdateLockBusy),
                session(
                    tmp_path,
                    provider="claude",
                    running_version="3.26.0",
                    raw_parent_lease=None,
                    timeout_s=0.0,
                ),
            ):
                raise AssertionError("missing lease must not borrow")
        else:
            with (
                pytest.raises(rejection, match="invalid parent update lease"),
                session(
                    tmp_path,
                    provider="claude",
                    running_version="3.26.0",
                    raw_parent_lease=raw_lease,
                    timeout_s=0.0,
                ),
            ):
                raise AssertionError("forged lease must not borrow")


def _readline_with_timeout(stream: IO[Any], timeout_s: float) -> str:
    result: queue.Queue[str] = queue.Queue(maxsize=1)

    def read_line() -> None:
        result.put(cast(str, stream.readline()))

    reader = threading.Thread(target=read_line, daemon=True)
    reader.start()
    try:
        return result.get(timeout=timeout_s)
    except queue.Empty as exc:
        raise TimeoutError("lock holder did not become ready") from exc


@pytest.mark.timeout(10)
def test_separate_process_lock_contention_is_busy(tmp_path: Path) -> None:
    process = subprocess.Popen(
        [sys.executable, "-c", LOCK_HOLDER, str(tmp_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        assert _readline_with_timeout(process.stdout, 5.0) == "READY\n"

        with (
            pytest.raises(UpdateLockBusy),
            project_update_lock(tmp_path, timeout_s=0.0),
        ):
            raise AssertionError("parent must not acquire the child lock")

        assert process.stdin is not None
        process.stdin.write("\n")
        process.stdin.flush()
        assert process.wait(timeout=5.0) == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5.0)

    assert process.stderr is not None
    assert process.stderr.read() == ""
