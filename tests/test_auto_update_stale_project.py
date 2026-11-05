"""#643: automatic update must refresh project files older than the running CLI."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest

from mapify_cli import auto_update
from mapify_cli.auto_update import UpdateMode, UpdateStatus, check_and_update
from mapify_cli.update_install import InstallKind
from mapify_cli.update_state import UpdateState, write_update_state
from mapify_cli.update_versions import VersionTargets

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _installed_package(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        auto_update,
        "detect_install_kind",
        lambda module_file: InstallKind.PIP,
    )
    # CLI == PyPI latest: discovery alone offers nothing.
    monkeypatch.setattr(
        auto_update,
        "fetch_version_targets",
        Mock(return_value=VersionTargets(None, None)),
    )


def _install_project(
    project: Path, installed_version: str, *, claude: bool = True
) -> None:
    """Write a lock claiming *installed_version* plus a Claude provider surface."""
    if claude:
        (project / ".claude" / "skills").mkdir(parents=True)
    (project / ".map").mkdir(exist_ok=True)
    (project / ".map" / "mapify.lock.json").write_text(
        json.dumps(
            {
                "mapify_version": installed_version,
                "provider": "claude",
                "installed_at": "2026-08-01T00:00:00Z",
                "entries": [],
            }
        ),
        encoding="utf-8",
    )


def _refresh_rewriting_lock(version: str) -> Mock:
    """Model `mapify init --refresh-existing`: it rewrites the lock version."""

    def refresh(project: Path, providers: tuple[str, ...]) -> tuple[str, ...]:
        _install_project(project, version, claude=False)
        return tuple(providers)

    return Mock(side_effect=refresh)


def _forbidden_refresh() -> Mock:
    return Mock(side_effect=AssertionError("provider refresh must not run"))


def test_stale_project_is_refreshed_when_cli_is_already_latest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_project(tmp_path, "3.35.2")
    refresh = _refresh_rewriting_lock("3.36.0")
    monkeypatch.setattr(auto_update, "refresh_installed_providers", refresh)

    first = check_and_update(tmp_path, "3.36.0", UpdateMode.AUTOMATIC, now=NOW)
    second = check_and_update(
        tmp_path, "3.36.0", UpdateMode.AUTOMATIC, now=NOW + timedelta(days=2)
    )

    assert first.status is UpdateStatus.UPDATED
    assert first.refreshed_providers == ("claude",)
    assert first.reload_current_skill is True
    assert second.status is UpdateStatus.CURRENT
    assert refresh.call_count == 1


def test_stale_project_refreshes_inside_the_automatic_throttle_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_project(tmp_path, "3.35.2")
    write_update_state(tmp_path, UpdateState(last_attempt_at="2026-08-13T11:00:00Z"))
    refresh = _refresh_rewriting_lock("3.36.0")
    monkeypatch.setattr(auto_update, "refresh_installed_providers", refresh)

    result = check_and_update(tmp_path, "3.36.0", UpdateMode.AUTOMATIC, now=NOW)

    assert result.status is UpdateStatus.UPDATED
    refresh.assert_called_once()


def test_project_at_cli_version_stays_current(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_project(tmp_path, "3.36.0")
    monkeypatch.setattr(auto_update, "refresh_installed_providers", _forbidden_refresh())

    result = check_and_update(tmp_path, "3.36.0", UpdateMode.AUTOMATIC, now=NOW)

    assert result.status is UpdateStatus.CURRENT


def test_project_newer_than_cli_is_never_downgraded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_project(tmp_path, "3.37.0")
    monkeypatch.setattr(auto_update, "refresh_installed_providers", _forbidden_refresh())

    result = check_and_update(tmp_path, "3.36.0", UpdateMode.AUTOMATIC, now=NOW)

    assert result.status is UpdateStatus.CURRENT


def test_stale_framework_source_repo_is_still_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "src" / "mapify_cli" / "templates_src").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "mapify-cli"\nversion = "0.0.0"\n', encoding="utf-8"
    )
    _install_project(tmp_path, "3.35.2")
    monkeypatch.setattr(auto_update, "refresh_installed_providers", _forbidden_refresh())

    result = check_and_update(tmp_path, "3.36.0", UpdateMode.AUTOMATIC, now=NOW)

    assert result.status is UpdateStatus.SKIPPED


def test_major_behind_project_needs_manual_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_project(tmp_path, "2.9.0")
    refresh = _refresh_rewriting_lock("3.36.0")
    monkeypatch.setattr(auto_update, "refresh_installed_providers", refresh)

    automatic = check_and_update(tmp_path, "3.36.0", UpdateMode.AUTOMATIC, now=NOW)
    refresh.assert_not_called()
    manual = check_and_update(tmp_path, "3.36.0", UpdateMode.MANUAL, now=NOW)

    assert automatic.status is UpdateStatus.CURRENT
    assert manual.status is UpdateStatus.UPDATED
    refresh.assert_called_once()
