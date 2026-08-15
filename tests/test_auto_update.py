"""Policy-state-machine tests for automatic and manual MAP updates."""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable, Generator
from datetime import UTC, datetime
from pathlib import Path
from typing import Self
from unittest.mock import Mock

import httpx
import pytest

from mapify_cli import auto_update
from mapify_cli.auto_update import (
    UpdateMode,
    UpdateResult,
    UpdateStatus,
    check_and_update,
)
from mapify_cli.update_install import (
    InstallKind,
    PackageUpdateError,
    ProjectRefreshError,
)
from mapify_cli.update_state import (
    UpdateLockBusy,
    UpdateLockSecurityError,
    UpdateState,
    installer_process_lock,
    provider_refresh_lock,
    read_update_state,
    write_update_state,
)
from mapify_cli.update_versions import ReleaseHighlights, StableVersion, VersionTargets

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _installed_package(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep policy tests independent from this repository's source checkout."""
    monkeypatch.setattr(
        auto_update,
        "detect_install_kind",
        lambda module_file: InstallKind.PIP,
    )


def _write_config(project: Path, body: str) -> None:
    config_path = project / ".map" / "config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(body, encoding="utf-8")


def _authorized_installer(
    effect: Callable[[Path, StableVersion], None],
) -> Callable[..., None]:
    """Model READY -> durable intent -> GO without mocking the authorization."""

    def install(
        project: Path,
        version: StableVersion,
        *,
        authorize_start: Callable[[], None] | None = None,
    ) -> None:
        if authorize_start is not None:
            authorize_start()
        effect(project, version)

    return install


def test_result_serializes_only_present_optional_fields() -> None:
    highlights = ReleaseHighlights(
        StableVersion(4, 0, 0),
        "MAP 4",
        "New planning engine",
        "https://example.test/v4",
    )

    payload = UpdateResult(
        UpdateStatus.MAJOR_AVAILABLE,
        "3.25.0",
        installed_version="3.26.0",
        major=highlights,
        refreshed_providers=("claude", "codex"),
        reload_current_skill=True,
    ).to_dict()

    assert payload == {
        "status": "major_available",
        "current_version": "3.25.0",
        "installed_version": "3.26.0",
        "refreshed_providers": ["claude", "codex"],
        "reload_current_skill": True,
        "major": {
            "version": "4.0.0",
            "title": "MAP 4",
            "body": "New planning engine",
            "url": "https://example.test/v4",
        },
    }


def test_automatic_disabled_skips_without_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_config(tmp_path, "updates.auto: false\n")
    fetch = Mock(side_effect=AssertionError("network must not run"))
    monkeypatch.setattr(auto_update, "fetch_version_targets", fetch)

    result = check_and_update(tmp_path, "3.25.0", UpdateMode.AUTOMATIC, now=NOW)

    assert result.status is UpdateStatus.SKIPPED
    fetch.assert_not_called()


def test_automatic_throttle_skips_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_update_state(
        tmp_path,
        UpdateState(last_attempt_at="2026-08-13T11:00:00Z"),
    )
    fetch = Mock(side_effect=AssertionError("network must not run"))
    monkeypatch.setattr(auto_update, "fetch_version_targets", fetch)

    result = check_and_update(tmp_path, "3.25.0", UpdateMode.AUTOMATIC, now=NOW)

    assert result.status is UpdateStatus.SKIPPED
    fetch.assert_not_called()


@pytest.mark.parametrize(
    ("last_attempt_at", "expected_status"),
    [
        ("2026-08-12T12:00:01Z", UpdateStatus.SKIPPED),
        ("2026-08-12T12:00:00Z", UpdateStatus.CURRENT),
    ],
)
def test_automatic_throttle_uses_a_rolling_24_hour_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    last_attempt_at: str,
    expected_status: UpdateStatus,
) -> None:
    write_update_state(tmp_path, UpdateState(last_attempt_at=last_attempt_at))
    fetch = Mock(return_value=VersionTargets(None, None))
    monkeypatch.setattr(auto_update, "fetch_version_targets", fetch)

    result = check_and_update(tmp_path, "3.25.0", UpdateMode.AUTOMATIC, now=NOW)

    assert result.status is expected_status
    assert fetch.call_count == (1 if expected_status is UpdateStatus.CURRENT else 0)


def test_pending_refresh_retries_before_throttle_and_requests_reload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_update_state(
        tmp_path,
        UpdateState(
            last_attempt_at="2026-08-13T11:00:00Z",
            last_installed_version="3.26.0",
            pending_refresh=True,
            pending_providers=("codex",),
        ),
    )
    refresh = Mock(return_value=("codex",))
    fetch = Mock(side_effect=AssertionError("pending refresh must not fetch"))
    monkeypatch.setattr(auto_update, "refresh_installed_providers", refresh)
    monkeypatch.setattr(auto_update, "fetch_version_targets", fetch)

    result = check_and_update(tmp_path, "3.26.0", UpdateMode.AUTOMATIC, now=NOW)

    assert result.status is UpdateStatus.UPDATED
    assert result.installed_version == "3.26.0"
    assert result.refreshed_providers == ("codex",)
    assert result.reload_current_skill is True
    assert read_update_state(tmp_path).pending_refresh is False
    fetch.assert_not_called()


def test_legacy_pending_refresh_discovers_and_persists_providers_before_refresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path = tmp_path / ".map" / "update-state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        """{"schema_version":1,"last_attempt_at":null,"last_observed_version":null,"last_installed_version":"3.26.0","pending_refresh":true,"pending_providers":[]}\n""",
        encoding="utf-8",
    )
    monkeypatch.setattr(auto_update, "installed_providers", lambda project: ("claude",))

    def refresh(project: Path, providers: tuple[str, ...]) -> tuple[str, ...]:
        assert providers == ("claude",)
        canonical = read_update_state(project)
        assert canonical.pending_refresh is True
        assert canonical.pending_providers == ("claude",)
        return providers

    fetch = Mock(side_effect=AssertionError("recovery must precede network"))
    monkeypatch.setattr(auto_update, "refresh_installed_providers", refresh)
    monkeypatch.setattr(auto_update, "fetch_version_targets", fetch)

    result = check_and_update(tmp_path, "3.26.0", UpdateMode.AUTOMATIC, now=NOW)

    assert result.status is UpdateStatus.UPDATED
    assert result.refreshed_providers == ("claude",)
    assert read_update_state(tmp_path).pending_refresh is False
    fetch.assert_not_called()


def test_manual_bypasses_disabled_config_and_throttle_without_changing_timestamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_config(tmp_path, "updates.auto: false\n")
    previous_attempt = "2026-08-13T11:00:00Z"
    write_update_state(tmp_path, UpdateState(last_attempt_at=previous_attempt))
    fetch = Mock(return_value=VersionTargets(None, None))
    monkeypatch.setattr(auto_update, "fetch_version_targets", fetch)

    result = check_and_update(tmp_path, "3.25.0", UpdateMode.MANUAL, now=NOW)

    assert result.status is UpdateStatus.CURRENT
    fetch.assert_called_once()
    assert read_update_state(tmp_path).last_attempt_at == previous_attempt


def test_source_install_is_silent_skip_automatically_and_error_manually(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        auto_update,
        "detect_install_kind",
        lambda module_file: InstallKind.SOURCE,
    )

    automatic = check_and_update(
        tmp_path,
        "3.25.0",
        UpdateMode.AUTOMATIC,
        now=NOW,
    )
    manual = check_and_update(tmp_path, "3.25.0", UpdateMode.MANUAL, now=NOW)

    assert automatic.status is UpdateStatus.SKIPPED
    assert manual.status is UpdateStatus.ERROR
    assert manual.message is not None
    assert "source checkout" in manual.message
    assert "owner-managed" in manual.message


def test_lock_contention_skips_automatic_and_errors_manual(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    @contextlib.contextmanager
    def busy_lock(
        project: Path,
        *,
        timeout_s: float,
    ) -> Generator[None, None, None]:
        del project, timeout_s
        raise UpdateLockBusy("busy")
        yield

    monkeypatch.setattr(auto_update, "project_update_lock", busy_lock)

    automatic = check_and_update(
        tmp_path,
        "3.25.0",
        UpdateMode.AUTOMATIC,
        now=NOW,
    )
    manual = check_and_update(tmp_path, "3.25.0", UpdateMode.MANUAL, now=NOW)

    assert automatic.status is UpdateStatus.SKIPPED
    assert manual.status is UpdateStatus.ERROR
    assert manual.message is not None and "already running" in manual.message


@pytest.mark.parametrize(
    "lock_name", ["update.lock", "installer.lock", "provider-refresh.lock"]
)
def test_manual_unsafe_lock_path_is_actionable_before_state_or_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    lock_name: str,
) -> None:
    map_dir = tmp_path / ".map"
    map_dir.mkdir()
    target = map_dir / f"{lock_name}.target"
    target.write_text("not a MAP lock\n", encoding="utf-8")
    (map_dir / lock_name).symlink_to(target)
    fetch = Mock(side_effect=AssertionError("unsafe lock must precede network"))
    monkeypatch.setattr(auto_update, "fetch_version_targets", fetch)

    result = check_and_update(tmp_path, "3.25.0", UpdateMode.MANUAL, now=NOW)

    assert result.status is UpdateStatus.ERROR
    assert result.message is not None
    assert "unsafe MAP update lock path" in result.message
    assert lock_name in result.message
    assert "Remove the unsafe path" in result.message
    assert not (tmp_path / ".map" / "update-state.json").exists()
    fetch.assert_not_called()


@pytest.mark.parametrize(
    ("mode", "expected_status"),
    [
        (UpdateMode.AUTOMATIC, UpdateStatus.SKIPPED),
        (UpdateMode.MANUAL, UpdateStatus.ERROR),
    ],
)
@pytest.mark.timeout(1)
def test_provider_refresh_barrier_contention_is_failfast_before_state_or_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: UpdateMode,
    expected_status: UpdateStatus,
) -> None:
    fetch = Mock(side_effect=AssertionError("busy barrier must precede network"))
    monkeypatch.setattr(auto_update, "fetch_version_targets", fetch)

    with provider_refresh_lock(tmp_path, timeout_s=0.0):
        started = time.monotonic()
        result = check_and_update(tmp_path, "3.25.0", mode, now=NOW)
        elapsed = time.monotonic() - started

    assert elapsed < 0.5
    assert result.status is expected_status
    if mode is UpdateMode.MANUAL:
        assert result.message is not None and "already running" in result.message
    assert not (tmp_path / ".map" / "update-state.json").exists()
    fetch.assert_not_called()


@pytest.mark.parametrize(
    ("mode", "expected_status"),
    [
        (UpdateMode.AUTOMATIC, UpdateStatus.SKIPPED),
        (UpdateMode.MANUAL, UpdateStatus.ERROR),
    ],
)
@pytest.mark.timeout(1)
def test_installer_barrier_contention_is_failfast_before_state_or_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: UpdateMode,
    expected_status: UpdateStatus,
) -> None:
    fetch = Mock(side_effect=AssertionError("busy installer must precede network"))
    refresh = Mock(side_effect=AssertionError("busy installer must precede refresh"))
    install = Mock(side_effect=AssertionError("busy installer must precede install"))
    monkeypatch.setattr(auto_update, "fetch_version_targets", fetch)
    monkeypatch.setattr(auto_update, "refresh_installed_providers", refresh)
    monkeypatch.setattr(auto_update, "install_exact_version", install)

    with installer_process_lock(tmp_path, timeout_s=0.0):
        started = time.monotonic()
        result = check_and_update(tmp_path, "3.25.0", mode, now=NOW)
        elapsed = time.monotonic() - started

    assert elapsed < 0.5
    assert result.status is expected_status
    if mode is UpdateMode.MANUAL:
        assert result.message is not None and "already running" in result.message
    assert not (tmp_path / ".map" / "update-state.json").exists()
    fetch.assert_not_called()
    refresh.assert_not_called()
    install.assert_not_called()


@pytest.mark.parametrize("mode", [UpdateMode.AUTOMATIC, UpdateMode.MANUAL])
def test_unstable_current_version_is_rejected_before_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: UpdateMode,
) -> None:
    fetch = Mock(side_effect=AssertionError("network must not run"))
    monkeypatch.setattr(auto_update, "fetch_version_targets", fetch)

    result = check_and_update(tmp_path, "3.25.0rc1", mode, now=NOW)

    assert result.status is UpdateStatus.ERROR
    assert result.message == (
        "Installed MAP version is not a stable MAJOR.MINOR.PATCH value."
    )
    fetch.assert_not_called()


def test_approved_major_requires_manual_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fetch = Mock(side_effect=AssertionError("network must not run"))
    monkeypatch.setattr(auto_update, "fetch_version_targets", fetch)

    result = check_and_update(
        tmp_path,
        "3.25.0",
        UpdateMode.AUTOMATIC,
        approved_major="4.0.0",
        now=NOW,
    )

    assert result.status is UpdateStatus.ERROR
    assert result.message is not None and "manual mode" in result.message
    fetch.assert_not_called()


def test_same_major_installs_refreshes_then_offers_major(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        auto_update,
        "fetch_version_targets",
        lambda current, client: VersionTargets(
            StableVersion(3, 26, 0),
            StableVersion(4, 0, 0),
        ),
    )
    monkeypatch.setattr(
        auto_update,
        "install_exact_version",
        _authorized_installer(
            lambda project, version: calls.append(f"install:{version}")
        ),
        raising=False,
    )
    monkeypatch.setattr(
        auto_update,
        "installed_providers",
        lambda project: ("claude", "codex"),
    )
    monkeypatch.setattr(
        auto_update,
        "refresh_installed_providers",
        lambda project, providers: tuple(providers),
    )
    monkeypatch.setattr(
        auto_update,
        "fetch_release_highlights",
        lambda version, client: ReleaseHighlights(
            version,
            "MAP 4",
            "New planning engine",
            "https://example.test/v4",
        ),
        raising=False,
    )

    result = check_and_update(tmp_path, "3.25.0", UpdateMode.AUTOMATIC, now=NOW)

    assert calls == ["install:3.26.0"]
    assert result.status is UpdateStatus.MAJOR_AVAILABLE
    assert result.installed_version == "3.26.0"
    assert result.major is not None and str(result.major.version) == "4.0.0"
    assert result.refreshed_providers == ("claude", "codex")
    assert result.reload_current_skill is True
    assert read_update_state(tmp_path) == UpdateState(
        last_attempt_at="2026-08-13T12:00:00Z",
        last_observed_version="4.0.0",
        last_installed_version="3.26.0",
    )


def test_same_major_requires_an_installed_provider_before_package_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        auto_update,
        "fetch_version_targets",
        lambda current, client: VersionTargets(StableVersion(3, 26, 0), None),
    )
    monkeypatch.setattr(auto_update, "installed_providers", lambda project: ())
    install = Mock()
    monkeypatch.setattr(
        auto_update,
        "install_exact_version",
        install,
        raising=False,
    )

    result = check_and_update(tmp_path, "3.25.0", UpdateMode.AUTOMATIC, now=NOW)

    assert result.status is UpdateStatus.ERROR
    assert result.message is not None and "provider" in result.message
    install.assert_not_called()


def test_same_major_without_higher_major_returns_updated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        auto_update,
        "fetch_version_targets",
        lambda current, client: VersionTargets(StableVersion(3, 25, 1), None),
    )
    monkeypatch.setattr(
        auto_update,
        "install_exact_version",
        _authorized_installer(lambda project, version: None),
        raising=False,
    )
    monkeypatch.setattr(
        auto_update,
        "installed_providers",
        lambda project: ("claude",),
    )
    monkeypatch.setattr(
        auto_update,
        "refresh_installed_providers",
        lambda project, providers: ("claude",),
    )

    result = check_and_update(tmp_path, "3.25.0", UpdateMode.AUTOMATIC, now=NOW)

    assert result.status is UpdateStatus.UPDATED
    assert result.installed_version == "3.25.1"
    assert result.refreshed_providers == ("claude",)
    assert result.reload_current_skill is True
    assert result.refresh_complete is True


def test_major_is_offered_but_never_installed_without_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = StableVersion(4, 0, 0)
    monkeypatch.setattr(
        auto_update,
        "fetch_version_targets",
        lambda current, client: VersionTargets(None, target),
    )
    monkeypatch.setattr(
        auto_update,
        "fetch_release_highlights",
        lambda version, client: ReleaseHighlights(
            version,
            "MAP 4",
            "New planning engine",
            "https://example.test/v4",
        ),
        raising=False,
    )
    install = Mock()
    monkeypatch.setattr(
        auto_update,
        "install_exact_version",
        install,
        raising=False,
    )

    result = check_and_update(tmp_path, "3.25.0", UpdateMode.AUTOMATIC, now=NOW)

    assert result.status is UpdateStatus.MAJOR_AVAILABLE
    assert result.major is not None and result.major.version == target
    assert result.installed_version is None
    install.assert_not_called()


@pytest.mark.parametrize(
    ("mode", "expected_status"),
    [
        (UpdateMode.AUTOMATIC, UpdateStatus.CURRENT),
        (UpdateMode.MANUAL, UpdateStatus.ERROR),
    ],
)
def test_major_without_official_metadata_is_not_offered(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: UpdateMode,
    expected_status: UpdateStatus,
) -> None:
    monkeypatch.setattr(
        auto_update,
        "fetch_version_targets",
        lambda current, client: VersionTargets(None, StableVersion(4, 0, 0)),
    )
    monkeypatch.setattr(
        auto_update,
        "fetch_release_highlights",
        lambda version, client: None,
        raising=False,
    )

    result = check_and_update(tmp_path, "3.25.0", mode, now=NOW)

    assert result.status is expected_status
    assert result.major is None
    if mode is UpdateMode.MANUAL:
        assert result.message is not None
        assert "official release highlights" in result.message


def test_missing_major_metadata_after_same_major_update_preserves_updated_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        auto_update,
        "fetch_version_targets",
        lambda current, client: VersionTargets(
            StableVersion(3, 26, 0),
            StableVersion(4, 0, 0),
        ),
    )
    monkeypatch.setattr(
        auto_update,
        "install_exact_version",
        _authorized_installer(lambda project, version: None),
        raising=False,
    )
    monkeypatch.setattr(
        auto_update,
        "installed_providers",
        lambda project: ("codex",),
    )
    monkeypatch.setattr(
        auto_update,
        "refresh_installed_providers",
        lambda project, providers: ("codex",),
    )
    monkeypatch.setattr(
        auto_update,
        "fetch_release_highlights",
        lambda version, client: None,
        raising=False,
    )

    result = check_and_update(tmp_path, "3.25.0", UpdateMode.AUTOMATIC, now=NOW)

    assert result.status is UpdateStatus.UPDATED
    assert result.installed_version == "3.26.0"
    assert result.reload_current_skill is True


def test_invalid_approved_major_is_rejected_without_network_or_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fetch = Mock(side_effect=AssertionError("network must not run"))
    install = Mock()
    monkeypatch.setattr(auto_update, "fetch_version_targets", fetch)
    monkeypatch.setattr(
        auto_update,
        "install_exact_version",
        install,
        raising=False,
    )

    result = check_and_update(
        tmp_path,
        "3.25.0",
        UpdateMode.MANUAL,
        approved_major="4.0.0rc1",
        now=NOW,
    )

    assert result.status is UpdateStatus.ERROR
    assert result.message is not None and "stable MAJOR.MINOR.PATCH" in result.message
    fetch.assert_not_called()
    install.assert_not_called()


def test_approved_major_is_revalidated_before_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        auto_update,
        "fetch_version_targets",
        lambda current, client: VersionTargets(None, StableVersion(4, 1, 0)),
    )
    install = Mock()
    monkeypatch.setattr(
        auto_update,
        "install_exact_version",
        install,
        raising=False,
    )

    result = check_and_update(
        tmp_path,
        "3.25.0",
        UpdateMode.MANUAL,
        approved_major="4.0.0",
        now=NOW,
    )

    assert result.status is UpdateStatus.ERROR
    assert result.message is not None and "freshly available major" in result.message
    install.assert_not_called()


def test_approved_major_skips_new_same_major_and_installs_only_exact_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installed: list[str] = []
    monkeypatch.setattr(
        auto_update,
        "fetch_version_targets",
        lambda current, client: VersionTargets(
            StableVersion(3, 26, 0),
            StableVersion(4, 0, 0),
        ),
    )
    monkeypatch.setattr(
        auto_update,
        "fetch_release_highlights",
        lambda version, client: ReleaseHighlights(
            version,
            "MAP 4",
            "New planning engine",
            "https://example.test/v4",
        ),
        raising=False,
    )
    monkeypatch.setattr(
        auto_update,
        "install_exact_version",
        _authorized_installer(lambda project, version: installed.append(str(version))),
        raising=False,
    )
    monkeypatch.setattr(
        auto_update,
        "installed_providers",
        lambda project: ("claude",),
    )
    monkeypatch.setattr(
        auto_update,
        "refresh_installed_providers",
        lambda project, providers: ("claude",),
    )

    result = check_and_update(
        tmp_path,
        "3.25.0",
        UpdateMode.MANUAL,
        approved_major="4.0.0",
        now=NOW,
    )

    assert result.status is UpdateStatus.UPDATED
    assert result.installed_version == "4.0.0"
    assert result.reload_current_skill is True
    assert installed == ["4.0.0"]


def test_approved_major_requires_fresh_official_highlights_before_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        auto_update,
        "fetch_version_targets",
        lambda current, client: VersionTargets(None, StableVersion(4, 0, 0)),
    )
    monkeypatch.setattr(
        auto_update,
        "fetch_release_highlights",
        lambda version, client: None,
        raising=False,
    )
    install = Mock()
    monkeypatch.setattr(
        auto_update,
        "install_exact_version",
        install,
        raising=False,
    )

    result = check_and_update(
        tmp_path,
        "3.25.0",
        UpdateMode.MANUAL,
        approved_major="4.0.0",
        now=NOW,
    )

    assert result.status is UpdateStatus.ERROR
    assert (
        result.message is not None and "official release highlights" in result.message
    )
    install.assert_not_called()


def test_invalid_target_tier_is_rejected_instead_of_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        auto_update,
        "fetch_version_targets",
        lambda current, client: VersionTargets(StableVersion(4, 0, 0), None),
    )
    install = Mock()
    monkeypatch.setattr(
        auto_update,
        "install_exact_version",
        install,
        raising=False,
    )

    result = check_and_update(tmp_path, "3.25.0", UpdateMode.AUTOMATIC, now=NOW)

    assert result.status is UpdateStatus.ERROR
    assert result.message is not None and "same-major target" in result.message
    install.assert_not_called()


def test_discovery_and_highlights_share_one_verified_http_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ssl_context = object()
    clients: list[object] = []

    class Client:
        def __init__(self, *, verify: object) -> None:
            assert verify is ssl_context
            clients.append(self)

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    def fetch_targets(current: StableVersion, client: object) -> VersionTargets:
        assert client is clients[0]
        return VersionTargets(None, StableVersion(4, 0, 0))

    def fetch_highlights(
        version: StableVersion,
        client: object,
    ) -> ReleaseHighlights:
        assert client is clients[0]
        return ReleaseHighlights(
            version,
            "MAP 4",
            "New planning engine",
            "https://example.test/v4",
        )

    monkeypatch.setattr(auto_update, "create_ssl_context", lambda: ssl_context)
    monkeypatch.setattr(auto_update.httpx, "Client", Client)
    monkeypatch.setattr(auto_update, "fetch_version_targets", fetch_targets)
    monkeypatch.setattr(
        auto_update,
        "fetch_release_highlights",
        fetch_highlights,
        raising=False,
    )

    result = check_and_update(tmp_path, "3.25.0", UpdateMode.AUTOMATIC, now=NOW)

    assert result.status is UpdateStatus.MAJOR_AVAILABLE
    assert len(clients) == 1
    assert read_update_state(tmp_path).last_observed_version == "4.0.0"


def test_automatic_records_attempt_before_fetch_even_when_fetch_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fetch(current: StableVersion, client: object) -> VersionTargets:
        del current, client
        assert read_update_state(tmp_path).last_attempt_at == "2026-08-13T12:00:00Z"
        raise httpx.TimeoutException("offline")

    monkeypatch.setattr(auto_update, "fetch_version_targets", fetch)

    result = check_and_update(tmp_path, "3.25.0", UpdateMode.AUTOMATIC, now=NOW)

    assert result.status is UpdateStatus.ERROR
    assert result.message is not None and "offline" in result.message
    assert read_update_state(tmp_path).last_attempt_at == "2026-08-13T12:00:00Z"


def test_failed_manual_fetch_does_not_change_automatic_attempt_timestamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    previous_attempt = "2026-08-12T09:30:00Z"
    write_update_state(tmp_path, UpdateState(last_attempt_at=previous_attempt))
    monkeypatch.setattr(
        auto_update,
        "fetch_version_targets",
        Mock(side_effect=httpx.TimeoutException("offline")),
    )

    result = check_and_update(tmp_path, "3.25.0", UpdateMode.MANUAL, now=NOW)

    assert result.status is UpdateStatus.ERROR
    assert result.message is not None
    assert "Check the network connection and retry" in result.message
    assert read_update_state(tmp_path).last_attempt_at == previous_attempt


def test_package_install_failure_preserves_ambiguous_install_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        auto_update,
        "fetch_version_targets",
        lambda current, client: VersionTargets(StableVersion(3, 26, 0), None),
    )
    monkeypatch.setattr(
        auto_update,
        "installed_providers",
        lambda project: ("claude",),
    )
    monkeypatch.setattr(
        auto_update,
        "install_exact_version",
        _authorized_installer(Mock(side_effect=PackageUpdateError("pip failed"))),
    )

    result = check_and_update(tmp_path, "3.25.0", UpdateMode.MANUAL, now=NOW)

    assert result.status is UpdateStatus.ERROR
    assert result.installed_version is None
    assert result.reload_current_skill is False
    assert result.message is not None and "pip failed" in result.message
    state = read_update_state(tmp_path)
    assert state.last_observed_version == "3.26.0"
    assert state.last_installed_version is None
    assert state.pending_install_version == "3.26.0"
    assert state.pending_refresh is False
    assert state.pending_providers == ("claude",)
    assert result.message is not None and "outcome is uncertain" in result.message


def test_package_success_is_persisted_as_pending_before_refresh_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        auto_update,
        "fetch_version_targets",
        lambda current, client: VersionTargets(StableVersion(3, 26, 0), None),
    )
    monkeypatch.setattr(
        auto_update,
        "installed_providers",
        lambda project: ("claude", "codex"),
    )

    def install_effect(project: Path, version: StableVersion) -> None:
        assert version == StableVersion(3, 26, 0)
        assert read_update_state(project) == UpdateState(
            last_attempt_at="2026-08-13T12:00:00Z",
            last_observed_version="3.26.0",
            pending_install_version="3.26.0",
            pending_providers=("claude", "codex"),
        )

    monkeypatch.setattr(
        auto_update,
        "install_exact_version",
        _authorized_installer(install_effect),
    )

    def refresh(project: Path, providers: tuple[str, ...]) -> tuple[str, ...]:
        assert providers == ("claude", "codex")
        assert read_update_state(project) == UpdateState(
            last_attempt_at="2026-08-13T12:00:00Z",
            last_observed_version="3.26.0",
            last_installed_version="3.26.0",
            pending_refresh=True,
            pending_providers=("claude", "codex"),
        )
        return providers

    monkeypatch.setattr(auto_update, "refresh_installed_providers", refresh)

    result = check_and_update(tmp_path, "3.25.0", UpdateMode.AUTOMATIC, now=NOW)

    assert result.status is UpdateStatus.UPDATED


def test_install_intent_write_failure_never_calls_package_installer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_write = auto_update.write_update_state
    package_installer = Mock(
        side_effect=AssertionError("package must wait for durable intent")
    )
    installer = _authorized_installer(package_installer)

    def fail_intent_write(project: Path, state: UpdateState) -> None:
        if state.pending_install_version is not None:
            raise OSError("intent disk full")
        real_write(project, state)

    monkeypatch.setattr(
        auto_update,
        "fetch_version_targets",
        lambda current, client: VersionTargets(StableVersion(3, 26, 0), None),
    )
    monkeypatch.setattr(auto_update, "installed_providers", lambda project: ("codex",))
    monkeypatch.setattr(auto_update, "install_exact_version", installer)
    monkeypatch.setattr(auto_update, "write_update_state", fail_intent_write)

    result = check_and_update(tmp_path, "3.25.0", UpdateMode.MANUAL, now=NOW)

    assert result.status is UpdateStatus.ERROR
    assert result.installed_version is None
    assert result.message is not None and "intent disk full" in result.message
    package_installer.assert_not_called()


def test_promotion_write_failure_retains_intent_for_fresh_invocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_write = auto_update.write_update_state
    write_calls = 0
    refresh = Mock(side_effect=AssertionError("refresh must wait for durable state"))

    def fail_pending_write(project: Path, state: UpdateState) -> None:
        nonlocal write_calls
        write_calls += 1
        if state.pending_refresh:
            raise OSError("state disk full")
        real_write(project, state)

    monkeypatch.setattr(
        auto_update,
        "fetch_version_targets",
        lambda current, client: VersionTargets(StableVersion(3, 26, 0), None),
    )
    monkeypatch.setattr(
        auto_update,
        "installed_providers",
        lambda project: ("codex",),
    )
    monkeypatch.setattr(
        auto_update,
        "install_exact_version",
        _authorized_installer(lambda project, version: None),
    )
    monkeypatch.setattr(auto_update, "refresh_installed_providers", refresh)
    monkeypatch.setattr(auto_update, "write_update_state", fail_pending_write)

    result = check_and_update(tmp_path, "3.25.0", UpdateMode.MANUAL, now=NOW)

    assert write_calls == 3
    assert result.status is UpdateStatus.ERROR
    assert result.installed_version == "3.26.0"
    assert result.reload_current_skill is False
    assert result.message is not None
    assert "run map-upgrade again" in result.message
    persisted = read_update_state(tmp_path)
    assert persisted.pending_install_version == "3.26.0"
    assert persisted.pending_refresh is False
    assert persisted.pending_providers == ("codex",)
    refresh.assert_not_called()


def test_matching_install_intent_promotes_and_refreshes_before_throttle_or_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_update_state(
        tmp_path,
        UpdateState(
            last_attempt_at="2026-08-13T11:00:00Z",
            last_observed_version="3.26.0",
            pending_install_version="3.26.0",
            pending_providers=("codex",),
        ),
    )
    fetch = Mock(side_effect=AssertionError("local recovery precedes network"))

    def refresh(project: Path, providers: tuple[str, ...]) -> tuple[str, ...]:
        assert providers == ("codex",)
        state = read_update_state(project)
        assert state.pending_install_version is None
        assert state.last_installed_version == "3.26.0"
        assert state.pending_refresh is True
        return providers

    monkeypatch.setattr(auto_update, "refresh_installed_providers", refresh)
    monkeypatch.setattr(auto_update, "fetch_version_targets", fetch)

    result = check_and_update(tmp_path, "3.26.0", UpdateMode.AUTOMATIC, now=NOW)

    assert result.status is UpdateStatus.UPDATED
    assert result.installed_version == "3.26.0"
    assert result.refreshed_providers == ("codex",)
    assert result.reload_current_skill is True
    final = read_update_state(tmp_path)
    assert final.pending_install_version is None
    assert final.pending_refresh is False
    assert final.pending_providers == ()
    fetch.assert_not_called()


def test_second_fresh_invocation_recovers_after_promotion_write_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_write = auto_update.write_update_state
    fail_promotion = True
    installs: list[str] = []

    def write_with_one_crash(project: Path, state: UpdateState) -> None:
        nonlocal fail_promotion
        if fail_promotion and state.pending_refresh:
            fail_promotion = False
            raise OSError("simulated crash before promotion")
        real_write(project, state)

    monkeypatch.setattr(
        auto_update,
        "fetch_version_targets",
        lambda current, client: VersionTargets(StableVersion(3, 26, 0), None),
    )
    monkeypatch.setattr(auto_update, "installed_providers", lambda project: ("claude",))
    monkeypatch.setattr(
        auto_update,
        "install_exact_version",
        _authorized_installer(lambda project, version: installs.append(str(version))),
    )
    monkeypatch.setattr(auto_update, "write_update_state", write_with_one_crash)
    monkeypatch.setattr(
        auto_update,
        "refresh_installed_providers",
        lambda project, providers: tuple(providers),
    )

    first = check_and_update(tmp_path, "3.25.0", UpdateMode.MANUAL, now=NOW)
    assert first.status is UpdateStatus.ERROR
    assert read_update_state(tmp_path).pending_install_version == "3.26.0"

    monkeypatch.setattr(
        auto_update,
        "fetch_version_targets",
        Mock(side_effect=AssertionError("fresh recovery must not fetch")),
    )
    second = check_and_update(tmp_path, "3.26.0", UpdateMode.AUTOMATIC, now=NOW)

    assert installs == ["3.26.0"]
    assert second.status is UpdateStatus.UPDATED
    assert second.refresh_complete is True
    assert read_update_state(tmp_path).pending_refresh is False


def test_mismatched_install_intent_respects_automatic_throttle_without_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = UpdateState(
        last_attempt_at="2026-08-13T11:00:00Z",
        pending_install_version="4.0.0",
        pending_providers=("claude",),
    )
    write_update_state(tmp_path, original)
    fetch = Mock(side_effect=AssertionError("throttle must precede network"))
    install = Mock(side_effect=AssertionError("state target must never install"))
    monkeypatch.setattr(auto_update, "fetch_version_targets", fetch)
    monkeypatch.setattr(auto_update, "install_exact_version", install)

    result = check_and_update(tmp_path, "3.25.0", UpdateMode.AUTOMATIC, now=NOW)

    assert result.status is UpdateStatus.SKIPPED
    assert read_update_state(tmp_path) == original
    fetch.assert_not_called()
    install.assert_not_called()


def test_mismatched_major_intent_requires_fresh_policy_and_consent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_update_state(
        tmp_path,
        UpdateState(
            pending_install_version="4.0.0",
            pending_providers=("claude",),
        ),
    )
    target = StableVersion(4, 0, 0)
    install = Mock(side_effect=AssertionError("persisted major is not consent"))
    monkeypatch.setattr(
        auto_update,
        "fetch_version_targets",
        lambda current, client: VersionTargets(None, target),
    )
    monkeypatch.setattr(
        auto_update,
        "fetch_release_highlights",
        lambda version, client: ReleaseHighlights(
            version,
            "MAP 4",
            "New planning engine",
            "https://example.test/v4",
        ),
    )
    monkeypatch.setattr(auto_update, "install_exact_version", install)

    result = check_and_update(tmp_path, "3.25.0", UpdateMode.MANUAL, now=NOW)

    assert result.status is UpdateStatus.MAJOR_AVAILABLE
    assert result.major is not None and result.major.version == target
    state = read_update_state(tmp_path)
    assert state.pending_install_version is None
    assert state.pending_providers == ()
    install.assert_not_called()


@pytest.mark.parametrize("mode", [UpdateMode.AUTOMATIC, UpdateMode.MANUAL])
def test_package_success_refresh_failure_sets_exact_pending_state_and_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: UpdateMode,
) -> None:
    previous_attempt = "2026-08-12T09:30:00Z"
    write_update_state(tmp_path, UpdateState(last_attempt_at=previous_attempt))
    monkeypatch.setattr(
        auto_update,
        "fetch_version_targets",
        lambda current, client: VersionTargets(StableVersion(3, 26, 0), None),
    )
    monkeypatch.setattr(
        auto_update,
        "install_exact_version",
        _authorized_installer(lambda project, version: None),
    )
    monkeypatch.setattr(
        auto_update,
        "installed_providers",
        lambda project: ("claude", "codex"),
    )
    monkeypatch.setattr(
        auto_update,
        "refresh_installed_providers",
        Mock(
            side_effect=ProjectRefreshError(
                "codex failed",
                refreshed_providers=("claude",),
                pending_providers=("codex",),
            )
        ),
    )

    result = check_and_update(tmp_path, "3.25.0", mode, now=NOW)

    assert result.status is UpdateStatus.ERROR
    assert result.installed_version == "3.26.0"
    assert result.refreshed_providers == ("claude",)
    assert result.reload_current_skill is True
    assert result.refresh_complete is False
    state = read_update_state(tmp_path)
    assert state.last_installed_version == "3.26.0"
    assert state.pending_refresh is True
    assert state.pending_providers == ("codex",)
    if mode is UpdateMode.MANUAL:
        assert result.message is not None
        assert (
            "mapify init . --force --no-git --provider codex --refresh-existing"
            in result.message
        )
        assert "--provider claude" not in result.message
        assert state.last_attempt_at == previous_attempt
    else:
        assert state.last_attempt_at == "2026-08-13T12:00:00Z"


def test_failed_automatic_pending_recovery_does_not_fetch_or_change_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_update_state(
        tmp_path,
        UpdateState(
            last_attempt_at="2026-08-13T11:00:00Z",
            last_installed_version="3.26.0",
            pending_refresh=True,
            pending_providers=("claude", "codex"),
        ),
    )
    monkeypatch.setattr(
        auto_update,
        "refresh_installed_providers",
        Mock(
            side_effect=ProjectRefreshError(
                "codex failed",
                refreshed_providers=("claude",),
                pending_providers=("codex",),
            )
        ),
    )
    fetch = Mock(side_effect=AssertionError("recovery must finish first"))
    monkeypatch.setattr(auto_update, "fetch_version_targets", fetch)

    result = check_and_update(tmp_path, "3.26.0", UpdateMode.AUTOMATIC, now=NOW)

    assert result.status is UpdateStatus.ERROR
    assert result.installed_version == "3.26.0"
    assert result.refreshed_providers == ("claude",)
    assert result.reload_current_skill is True
    state = read_update_state(tmp_path)
    assert state.last_attempt_at == "2026-08-13T11:00:00Z"
    assert state.pending_providers == ("codex",)
    fetch.assert_not_called()


def test_manual_pending_recovery_continues_network_check_and_returns_updated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    previous_attempt = "2026-08-13T11:00:00Z"
    write_update_state(
        tmp_path,
        UpdateState(
            last_attempt_at=previous_attempt,
            last_installed_version="3.26.0",
            pending_refresh=True,
            pending_providers=("codex",),
        ),
    )
    refresh = Mock(return_value=("codex",))
    fetch = Mock(return_value=VersionTargets(None, None))
    monkeypatch.setattr(auto_update, "refresh_installed_providers", refresh)
    monkeypatch.setattr(auto_update, "fetch_version_targets", fetch)

    result = check_and_update(tmp_path, "3.26.0", UpdateMode.MANUAL, now=NOW)

    assert result.status is UpdateStatus.UPDATED
    assert result.installed_version == "3.26.0"
    assert result.refreshed_providers == ("codex",)
    assert result.reload_current_skill is True
    fetch.assert_called_once()
    assert read_update_state(tmp_path).last_attempt_at == previous_attempt


def test_manual_pending_recovery_major_offer_keeps_reload_and_refresh_details(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_update_state(
        tmp_path,
        UpdateState(
            last_installed_version="3.26.0",
            pending_refresh=True,
            pending_providers=("claude",),
        ),
    )
    target = StableVersion(4, 0, 0)
    monkeypatch.setattr(
        auto_update,
        "refresh_installed_providers",
        lambda project, providers: ("claude",),
    )
    monkeypatch.setattr(
        auto_update,
        "fetch_version_targets",
        lambda current, client: VersionTargets(None, target),
    )
    monkeypatch.setattr(
        auto_update,
        "fetch_release_highlights",
        lambda version, client: ReleaseHighlights(
            version,
            "MAP 4",
            "New planning engine",
            "https://example.test/v4",
        ),
    )

    result = check_and_update(tmp_path, "3.26.0", UpdateMode.MANUAL, now=NOW)

    assert result.status is UpdateStatus.MAJOR_AVAILABLE
    assert result.installed_version == "3.26.0"
    assert result.refreshed_providers == ("claude",)
    assert result.reload_current_skill is True


def test_manual_pending_recovery_then_fetch_failure_preserves_recovered_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_update_state(
        tmp_path,
        UpdateState(
            last_installed_version="3.26.0",
            pending_refresh=True,
            pending_providers=("codex",),
        ),
    )
    monkeypatch.setattr(
        auto_update,
        "refresh_installed_providers",
        lambda project, providers: ("codex",),
    )
    monkeypatch.setattr(
        auto_update,
        "fetch_version_targets",
        Mock(side_effect=httpx.TimeoutException("offline")),
    )

    result = check_and_update(tmp_path, "3.26.0", UpdateMode.MANUAL, now=NOW)

    assert result.status is UpdateStatus.ERROR
    assert result.installed_version == "3.26.0"
    assert result.refreshed_providers == ("codex",)
    assert result.reload_current_skill is True
    assert read_update_state(tmp_path).pending_refresh is False


def test_manual_pending_recovery_failure_has_exact_recovery_commands_and_no_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_update_state(
        tmp_path,
        UpdateState(
            last_installed_version="3.26.0",
            pending_refresh=True,
            pending_providers=("claude", "codex"),
        ),
    )
    monkeypatch.setattr(
        auto_update,
        "refresh_installed_providers",
        Mock(
            side_effect=ProjectRefreshError(
                "refresh failed",
                pending_providers=("claude", "codex"),
            )
        ),
    )
    fetch = Mock(side_effect=AssertionError("network must not run"))
    monkeypatch.setattr(auto_update, "fetch_version_targets", fetch)

    result = check_and_update(tmp_path, "3.26.0", UpdateMode.MANUAL, now=NOW)

    assert result.status is UpdateStatus.ERROR
    assert result.message is not None
    assert (
        "mapify init . --force --no-git --provider claude --refresh-existing"
        in result.message
    )
    assert (
        "mapify init . --force --no-git --provider codex --refresh-existing"
        in result.message
    )
    fetch.assert_not_called()


def test_manual_successful_update_never_changes_automatic_attempt_timestamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    previous_attempt = "2026-08-12T09:30:00Z"
    write_update_state(tmp_path, UpdateState(last_attempt_at=previous_attempt))
    monkeypatch.setattr(
        auto_update,
        "fetch_version_targets",
        lambda current, client: VersionTargets(StableVersion(3, 26, 0), None),
    )
    monkeypatch.setattr(
        auto_update,
        "installed_providers",
        lambda project: ("claude",),
    )
    monkeypatch.setattr(
        auto_update,
        "install_exact_version",
        _authorized_installer(lambda project, version: None),
    )
    monkeypatch.setattr(
        auto_update,
        "refresh_installed_providers",
        lambda project, providers: ("claude",),
    )

    result = check_and_update(tmp_path, "3.25.0", UpdateMode.MANUAL, now=NOW)

    assert result.status is UpdateStatus.UPDATED
    assert read_update_state(tmp_path).last_attempt_at == previous_attempt


def test_highlights_fetch_failure_is_an_operational_error_not_a_major_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        auto_update,
        "fetch_version_targets",
        lambda current, client: VersionTargets(None, StableVersion(4, 0, 0)),
    )
    monkeypatch.setattr(
        auto_update,
        "fetch_release_highlights",
        Mock(side_effect=httpx.TimeoutException("GitHub offline")),
    )

    result = check_and_update(tmp_path, "3.25.0", UpdateMode.AUTOMATIC, now=NOW)

    assert result.status is UpdateStatus.ERROR
    assert result.message is not None and "GitHub offline" in result.message


@pytest.mark.parametrize("failure_boundary", ["config", "install-kind", "lock"])
def test_automatic_outer_boundary_failures_return_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_boundary: str,
) -> None:
    if failure_boundary == "config":
        monkeypatch.setattr(
            auto_update,
            "load_map_config",
            Mock(side_effect=OSError("config unreadable")),
        )
    elif failure_boundary == "install-kind":
        monkeypatch.setattr(
            auto_update,
            "detect_install_kind",
            Mock(side_effect=OSError("environment unreadable")),
        )
    else:

        @contextlib.contextmanager
        def insecure_lock(
            project: Path,
            *,
            timeout_s: float,
        ) -> Generator[None, None, None]:
            del project, timeout_s
            raise UpdateLockSecurityError("unsafe lock")
            yield

        monkeypatch.setattr(auto_update, "project_update_lock", insecure_lock)

    result = check_and_update(tmp_path, "3.25.0", UpdateMode.AUTOMATIC, now=NOW)

    assert result.status is UpdateStatus.ERROR
    assert result.message is not None


def test_manual_outer_boundary_failure_is_actionable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        auto_update,
        "detect_install_kind",
        Mock(side_effect=OSError("environment unreadable")),
    )

    result = check_and_update(tmp_path, "3.25.0", UpdateMode.MANUAL, now=NOW)

    assert result.status is UpdateStatus.ERROR
    assert result.message is not None
    assert "Retry the manual update" in result.message


@pytest.mark.parametrize("mode", [UpdateMode.AUTOMATIC, UpdateMode.MANUAL])
def test_lock_cleanup_failure_preserves_completed_update_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: UpdateMode,
) -> None:
    @contextlib.contextmanager
    def failing_cleanup_lock(
        project: Path,
        *,
        timeout_s: float,
    ) -> Generator[None, None, None]:
        del project, timeout_s
        yield
        raise OSError("lock cleanup failed")

    monkeypatch.setattr(auto_update, "project_update_lock", failing_cleanup_lock)
    monkeypatch.setattr(
        auto_update,
        "fetch_version_targets",
        lambda current, client: VersionTargets(StableVersion(3, 26, 0), None),
    )
    monkeypatch.setattr(
        auto_update,
        "installed_providers",
        lambda project: ("claude",),
    )
    monkeypatch.setattr(
        auto_update,
        "install_exact_version",
        _authorized_installer(lambda project, version: None),
    )
    monkeypatch.setattr(
        auto_update,
        "refresh_installed_providers",
        lambda project, providers: ("claude",),
    )

    result = check_and_update(tmp_path, "3.25.0", mode, now=NOW)

    assert result.status is UpdateStatus.ERROR
    assert result.installed_version == "3.26.0"
    assert result.refreshed_providers == ("claude",)
    assert result.reload_current_skill is True
    assert result.refresh_complete is True
    assert result.message is not None and "lock cleanup failed" in result.message
    if mode is UpdateMode.MANUAL:
        assert "Retry the manual update" in result.message
    state = read_update_state(tmp_path)
    assert state.last_installed_version == "3.26.0"
    assert state.pending_refresh is False
    assert state.pending_providers == ()


def test_failure_after_same_major_refresh_preserves_all_completed_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        auto_update,
        "fetch_version_targets",
        lambda current, client: VersionTargets(
            StableVersion(3, 26, 0),
            StableVersion(4, 0, 0),
        ),
    )
    monkeypatch.setattr(
        auto_update,
        "installed_providers",
        lambda project: ("claude", "codex"),
    )
    monkeypatch.setattr(
        auto_update,
        "install_exact_version",
        _authorized_installer(lambda project, version: None),
    )
    monkeypatch.setattr(
        auto_update,
        "refresh_installed_providers",
        lambda project, providers: ("claude", "codex"),
    )
    monkeypatch.setattr(
        auto_update,
        "fetch_release_highlights",
        Mock(side_effect=httpx.TimeoutException("GitHub offline")),
    )

    result = check_and_update(tmp_path, "3.25.0", UpdateMode.MANUAL, now=NOW)

    assert result.status is UpdateStatus.ERROR
    assert result.installed_version == "3.26.0"
    assert result.refreshed_providers == ("claude", "codex")
    assert result.reload_current_skill is True
    assert read_update_state(tmp_path).pending_refresh is False
    assert (
        result.message is not None and "Check the network connection" in result.message
    )


def test_automatic_late_highlight_failure_returns_message_free_updated_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        auto_update,
        "fetch_version_targets",
        lambda current, client: VersionTargets(
            StableVersion(3, 26, 0),
            StableVersion(4, 0, 0),
        ),
    )
    monkeypatch.setattr(
        auto_update,
        "installed_providers",
        lambda project: ("claude", "codex"),
    )
    monkeypatch.setattr(
        auto_update,
        "install_exact_version",
        _authorized_installer(lambda project, version: None),
    )
    monkeypatch.setattr(
        auto_update,
        "refresh_installed_providers",
        lambda project, providers: ("claude", "codex"),
    )
    monkeypatch.setattr(
        auto_update,
        "fetch_release_highlights",
        Mock(side_effect=httpx.TimeoutException("GitHub offline")),
    )

    result = check_and_update(tmp_path, "3.25.0", UpdateMode.AUTOMATIC, now=NOW)

    assert result == UpdateResult(
        UpdateStatus.UPDATED,
        "3.25.0",
        installed_version="3.26.0",
        refreshed_providers=("claude", "codex"),
        reload_current_skill=True,
        refresh_complete=True,
    )
    assert read_update_state(tmp_path).pending_refresh is False


def test_approved_major_refresh_failure_uses_the_same_durable_recovery_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = StableVersion(4, 0, 0)
    monkeypatch.setattr(
        auto_update,
        "fetch_version_targets",
        lambda current, client: VersionTargets(StableVersion(3, 26, 0), target),
    )
    monkeypatch.setattr(
        auto_update,
        "fetch_release_highlights",
        lambda version, client: ReleaseHighlights(
            version,
            "MAP 4",
            "New planning engine",
            "https://example.test/v4",
        ),
    )
    monkeypatch.setattr(
        auto_update,
        "installed_providers",
        lambda project: ("codex",),
    )
    monkeypatch.setattr(
        auto_update,
        "install_exact_version",
        _authorized_installer(lambda project, version: None),
    )
    monkeypatch.setattr(
        auto_update,
        "refresh_installed_providers",
        Mock(
            side_effect=ProjectRefreshError(
                "codex failed",
                pending_providers=("codex",),
            )
        ),
    )

    result = check_and_update(
        tmp_path,
        "3.25.0",
        UpdateMode.MANUAL,
        approved_major="4.0.0",
        now=NOW,
    )

    assert result.status is UpdateStatus.ERROR
    assert result.installed_version == "4.0.0"
    assert read_update_state(tmp_path).pending_providers == ("codex",)
    assert result.message is not None
    assert (
        "mapify init . --force --no-git --provider codex --refresh-existing"
        in result.message
    )


def test_manual_recovery_then_second_refresh_failure_merges_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_update_state(
        tmp_path,
        UpdateState(
            last_installed_version="3.25.1",
            pending_refresh=True,
            pending_providers=("claude",),
        ),
    )
    refresh_calls = 0

    def refresh(project: Path, providers: tuple[str, ...]) -> tuple[str, ...]:
        nonlocal refresh_calls
        del project
        refresh_calls += 1
        if refresh_calls == 1:
            assert providers == ("claude",)
            return ("claude",)
        raise ProjectRefreshError(
            "codex failed",
            refreshed_providers=("claude",),
            pending_providers=("codex",),
        )

    monkeypatch.setattr(auto_update, "refresh_installed_providers", refresh)
    monkeypatch.setattr(
        auto_update,
        "fetch_version_targets",
        lambda current, client: VersionTargets(StableVersion(3, 26, 0), None),
    )
    monkeypatch.setattr(
        auto_update,
        "installed_providers",
        lambda project: ("claude", "codex"),
    )
    monkeypatch.setattr(
        auto_update,
        "install_exact_version",
        _authorized_installer(lambda project, version: None),
    )

    result = check_and_update(tmp_path, "3.25.1", UpdateMode.MANUAL, now=NOW)

    assert result.status is UpdateStatus.ERROR
    assert result.installed_version == "3.26.0"
    assert result.refreshed_providers == ("claude",)
    assert result.reload_current_skill is True
    assert read_update_state(tmp_path).pending_providers == ("codex",)
