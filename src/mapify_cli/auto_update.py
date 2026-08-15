"""Central policy orchestration for automatic and manual MAP updates."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

import httpx

from mapify_cli import create_ssl_context
from mapify_cli.config import load_map_config
from mapify_cli.update_install import (
    InstallKind,
    PackageUpdateError,
    ProjectRefreshError,
    detect_install_kind,
    install_exact_version,
    installed_providers,
    refresh_installed_providers,
)
from mapify_cli.update_state import (
    UpdateLockBusy,
    UpdateLockSecurityError,
    UpdateState,
    automatic_check_due,
    installer_process_probe,
    project_update_lock,
    provider_refresh_lock,
    read_update_state,
    write_update_state,
)
from mapify_cli.update_versions import (
    ReleaseHighlights,
    StableVersion,
    VersionTargets,
    fetch_release_highlights,
    fetch_version_targets,
)

_DEFAULT_INSTALL_EXACT_VERSION = install_exact_version

LOCK_TIMEOUT_SECONDS = 0.0
REFRESH_BARRIER_TIMEOUT_SECONDS = 0.0


class UpdateMode(StrEnum):
    """Whether an update check was initiated by a skill or explicitly by a user."""

    AUTOMATIC = "automatic"
    MANUAL = "manual"


class UpdateStatus(StrEnum):
    """Machine-readable outcome of an update check."""

    CURRENT = "current"
    SKIPPED = "skipped"
    UPDATED = "updated"
    MAJOR_AVAILABLE = "major_available"
    ERROR = "error"


@dataclass(frozen=True)
class UpdateResult:
    """Bounded structured result consumed by the hidden CLI adapter."""

    status: UpdateStatus
    current_version: str
    installed_version: str | None = None
    major: ReleaseHighlights | None = None
    message: str | None = None
    refreshed_providers: tuple[str, ...] = ()
    reload_current_skill: bool = False
    refresh_complete: bool = False

    def to_dict(self) -> dict[str, object]:
        """Return the stable JSON-facing representation of this result."""
        payload: dict[str, object] = {
            "status": self.status.value,
            "current_version": self.current_version,
        }
        if self.installed_version is not None:
            payload["installed_version"] = self.installed_version
        if self.message is not None:
            payload["message"] = self.message
        if self.refreshed_providers:
            payload["refreshed_providers"] = list(self.refreshed_providers)
        payload["reload_current_skill"] = self.reload_current_skill
        if self.major is not None:
            payload["major"] = {
                "version": str(self.major.version),
                "title": self.major.title,
                "body": self.major.body,
                "url": self.major.url,
            }
        return payload


@dataclass
class _UpdateProgress:
    """Mutable in-call progress retained when a later operation fails."""

    state: UpdateState
    installed_version: str | None = None
    refreshed_providers: tuple[str, ...] = ()
    reload_current_skill: bool = False
    recovered_refresh: bool = False
    refresh_complete: bool = False


def _error(current_version: str, message: str) -> UpdateResult:
    return UpdateResult(UpdateStatus.ERROR, current_version, message=message)


def _error_with_progress(
    current_version: str,
    message: str,
    progress: _UpdateProgress,
) -> UpdateResult:
    return UpdateResult(
        UpdateStatus.ERROR,
        current_version,
        installed_version=progress.installed_version,
        message=message,
        refreshed_providers=progress.refreshed_providers,
        reload_current_skill=progress.reload_current_skill,
        refresh_complete=progress.refresh_complete,
    )


def _timestamp(now: datetime) -> str:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("The update clock must be timezone-aware.")
    return now.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _highest_target(targets: VersionTargets) -> StableVersion | None:
    candidates = tuple(
        target
        for target in (targets.same_major, targets.next_major)
        if target is not None
    )
    return max(candidates, default=None)


def _validate_targets(targets: VersionTargets, current: StableVersion) -> None:
    same_major = targets.same_major
    if same_major is not None and (
        same_major.major != current.major or same_major <= current
    ):
        raise ValueError(
            f"Discovered same-major target {same_major} is not newer within "
            f"major {current.major}."
        )
    next_major = targets.next_major
    if next_major is not None and (
        next_major.major <= current.major or next_major <= current
    ):
        raise ValueError(
            f"Discovered higher-major target {next_major} is not newer than "
            f"major {current.major}."
        )


def _merge_providers(
    first: tuple[str, ...],
    second: tuple[str, ...],
) -> tuple[str, ...]:
    return tuple(dict.fromkeys((*first, *second)))


def _install_and_refresh(
    project_path: Path,
    progress: _UpdateProgress,
    target: StableVersion,
) -> None:
    providers = installed_providers(project_path)
    if not providers:
        raise RuntimeError(
            "No installed MAP provider surface was found; initialize a Claude or "
            "Codex provider before updating mapify-cli."
        )

    # Intent: The installer controller acquires its child-owned barrier and signals
    # READY before this callback persists mutation authority. Only a successful
    # write authorizes GO, so an intent-write failure cannot launch the package.
    install_intent = replace(
        progress.state,
        pending_install_version=str(target),
        pending_refresh=False,
        pending_providers=providers,
    )

    def authorize_install_start() -> None:
        write_update_state(project_path, install_intent)
        progress.state = install_intent

    if install_exact_version is _DEFAULT_INSTALL_EXACT_VERSION:
        install_exact_version(
            project_path,
            target,
            authorize_start=authorize_install_start,
        )
    else:
        # Injected installers used by embedders and tests predate the controller
        # callback. Preserve their boundary while keeping intent durable first.
        authorize_install_start()
        install_exact_version(project_path, target)
    progress.installed_version = str(target)
    refresh_pending = replace(
        progress.state,
        last_installed_version=str(target),
        pending_install_version=None,
        pending_refresh=True,
    )
    write_update_state(project_path, refresh_pending)
    progress.state = refresh_pending
    try:
        refreshed = refresh_installed_providers(project_path, providers)
    except ProjectRefreshError as exc:
        progress.refreshed_providers = _merge_providers(
            progress.refreshed_providers,
            exc.refreshed_providers,
        )
        progress.reload_current_skill = bool(progress.refreshed_providers)
        progress.state = replace(
            progress.state,
            pending_refresh=True,
            pending_providers=exc.pending_providers,
        )
        write_update_state(project_path, progress.state)
        raise
    progress.refreshed_providers = _merge_providers(
        progress.refreshed_providers,
        refreshed,
    )
    progress.reload_current_skill = True
    progress.refresh_complete = True
    progress.state = replace(
        progress.state,
        pending_install_version=None,
        pending_refresh=False,
        pending_providers=(),
    )
    write_update_state(project_path, progress.state)


def _pending_recovery_commands(providers: tuple[str, ...]) -> str:
    return "\n".join(
        f"mapify init . --force --no-git --provider {provider} --refresh-existing"
        for provider in providers
    )


def _actionable_error_message(
    exc: Exception,
    mode: UpdateMode,
    state: UpdateState,
) -> str:
    message = f"MAP update failed: {exc}"
    if mode is not UpdateMode.MANUAL:
        return message

    if isinstance(exc, UpdateLockSecurityError):
        return (
            "MAP update failed: unsafe MAP update lock path was rejected: "
            f"{exc}. Remove the unsafe path so MAP can create a regular, "
            "project-local lock file, then retry map-upgrade."
        )
    if state.pending_install_version is not None:
        return (
            f"{message}. The package installation outcome is uncertain and the "
            "project was not refreshed. Start a fresh MAP invocation and run "
            "map-upgrade again so the installed version can be reconciled safely."
        )
    if state.pending_refresh and state.pending_providers:
        commands = _pending_recovery_commands(state.pending_providers)
        return (
            f"{message}. The package is installed, but project refresh is "
            f"incomplete. Run each pending recovery command:\n{commands}"
        )
    if isinstance(exc, httpx.HTTPError):
        return f"{message}. Check the network connection and retry the manual update."
    if isinstance(exc, PackageUpdateError):
        return f"{message}. Resolve the package-manager error and retry."
    return f"{message}. Retry the manual update after resolving the reported error."


def _operational_error(
    project_path: Path,
    current_version: str,
    mode: UpdateMode,
    progress: _UpdateProgress,
    exc: Exception,
) -> UpdateResult:
    try:
        persisted_state = read_update_state(project_path)
    except Exception:  # noqa: BLE001 - retain the original operational failure
        persisted_state = progress.state
    message_state = (
        progress.state if progress.state.pending_refresh else persisted_state
    )
    installed_version = progress.installed_version
    if installed_version is None and persisted_state.pending_refresh:
        installed_version = persisted_state.last_installed_version
    return UpdateResult(
        UpdateStatus.ERROR,
        current_version,
        installed_version=installed_version,
        message=_actionable_error_message(exc, mode, message_state),
        refreshed_providers=progress.refreshed_providers,
        reload_current_skill=progress.reload_current_skill,
        refresh_complete=progress.refresh_complete,
    )


def _metadata_unavailable_result(
    mode: UpdateMode,
    current_version: str,
    *,
    installed_version: str | None,
    refreshed_providers: tuple[str, ...],
    reload_current_skill: bool,
    refresh_complete: bool,
) -> UpdateResult:
    if mode is UpdateMode.AUTOMATIC:
        status = (
            UpdateStatus.UPDATED
            if reload_current_skill or installed_version is not None
            else UpdateStatus.CURRENT
        )
        return UpdateResult(
            status,
            current_version,
            installed_version=installed_version,
            refreshed_providers=refreshed_providers,
            reload_current_skill=reload_current_skill,
            refresh_complete=refresh_complete,
        )
    return UpdateResult(
        UpdateStatus.ERROR,
        current_version,
        installed_version=installed_version,
        message=(
            "The newer major cannot be offered safely because its official "
            "release highlights could not be retrieved. Retry the manual check."
        ),
        refreshed_providers=refreshed_providers,
        reload_current_skill=reload_current_skill,
        refresh_complete=refresh_complete,
    )


def _check_locked(
    project_path: Path,
    current_version: str,
    mode: UpdateMode,
    approved_major: str | None,
    effective_now: datetime,
) -> UpdateResult:
    current = StableVersion.parse(current_version)
    if current is None:
        return _error(
            current_version,
            "Installed MAP version is not a stable MAJOR.MINOR.PATCH value.",
        )

    progress = _UpdateProgress(read_update_state(project_path))
    try:
        if progress.state.pending_install_version is not None:
            pending_target = progress.state.pending_install_version
            if pending_target == str(current):
                # Intent: A fresh target-version process is proof that the prior
                # package mutation landed; promote locally before any throttle or I/O.
                promoted = replace(
                    progress.state,
                    last_installed_version=pending_target,
                    pending_install_version=None,
                    pending_refresh=True,
                )
                write_update_state(project_path, promoted)
                progress.state = promoted
                progress.installed_version = pending_target
            else:
                if mode is UpdateMode.AUTOMATIC and not automatic_check_due(
                    progress.state,
                    effective_now,
                ):
                    return UpdateResult(UpdateStatus.SKIPPED, current_version)
                # Intent: Persisted intent is evidence, never install authority.
                # A mismatch re-enters freshly fetched policy (and major consent).
                cleared = replace(
                    progress.state,
                    pending_install_version=None,
                    pending_providers=(),
                )
                write_update_state(project_path, cleared)
                progress.state = cleared

        if progress.state.pending_refresh:
            progress.installed_version = progress.state.last_installed_version
            providers = progress.state.pending_providers or installed_providers(
                project_path
            )
            if not providers:
                raise RuntimeError(
                    "No installed MAP provider surface was found for the pending "
                    "project refresh."
                )
            if not progress.state.pending_providers:
                # Intent: Normalize the sole provider-less v1 recovery shape into
                # strict v2 authority before a leased child can be launched.
                canonical = replace(
                    progress.state,
                    pending_providers=providers,
                )
                write_update_state(project_path, canonical)
                progress.state = canonical
            try:
                refreshed = refresh_installed_providers(project_path, providers)
            except ProjectRefreshError as exc:
                progress.refreshed_providers = _merge_providers(
                    progress.refreshed_providers,
                    exc.refreshed_providers,
                )
                progress.reload_current_skill = bool(progress.refreshed_providers)
                progress.state = replace(
                    progress.state,
                    pending_refresh=True,
                    pending_providers=exc.pending_providers,
                )
                write_update_state(project_path, progress.state)
                raise
            progress.refreshed_providers = _merge_providers(
                progress.refreshed_providers,
                refreshed,
            )
            progress.reload_current_skill = True
            progress.refresh_complete = True
            progress.state = replace(
                progress.state,
                pending_install_version=None,
                pending_refresh=False,
                pending_providers=(),
            )
            write_update_state(project_path, progress.state)
            if mode is UpdateMode.AUTOMATIC:
                return UpdateResult(
                    UpdateStatus.UPDATED,
                    current_version,
                    installed_version=progress.installed_version,
                    refreshed_providers=progress.refreshed_providers,
                    reload_current_skill=True,
                    refresh_complete=True,
                )
            progress.recovered_refresh = True

        if mode is UpdateMode.AUTOMATIC and not automatic_check_due(
            progress.state,
            effective_now,
        ):
            return UpdateResult(UpdateStatus.SKIPPED, current_version)

        approved = None
        if approved_major is not None:
            approved = StableVersion.parse(approved_major)
            if approved is None:
                return _error_with_progress(
                    current_version,
                    "The approved major is not a stable MAJOR.MINOR.PATCH value.",
                    progress,
                )

        if mode is UpdateMode.AUTOMATIC:
            progress.state = replace(
                progress.state,
                last_attempt_at=_timestamp(effective_now),
            )
            write_update_state(project_path, progress.state)

        with httpx.Client(verify=create_ssl_context()) as client:
            targets = fetch_version_targets(current, client)
            _validate_targets(targets, current)
            highest = _highest_target(targets)
            if highest is not None:
                progress.state = replace(
                    progress.state,
                    last_observed_version=str(highest),
                )
                write_update_state(project_path, progress.state)

            if approved is not None:
                if targets.next_major != approved:
                    available = (
                        str(targets.next_major)
                        if targets.next_major is not None
                        else "none"
                    )
                    return _error_with_progress(
                        current_version,
                        f"Approved major {approved} is not the freshly available "
                        f"major target ({available}); request fresh consent.",
                        progress,
                    )
                highlights = fetch_release_highlights(approved, client)
                if highlights is None:
                    return _metadata_unavailable_result(
                        mode,
                        current_version,
                        installed_version=progress.installed_version,
                        refreshed_providers=progress.refreshed_providers,
                        reload_current_skill=progress.reload_current_skill,
                        refresh_complete=progress.refresh_complete,
                    )
                _install_and_refresh(project_path, progress, approved)
                return UpdateResult(
                    UpdateStatus.UPDATED,
                    current_version,
                    installed_version=str(approved),
                    refreshed_providers=progress.refreshed_providers,
                    reload_current_skill=True,
                    refresh_complete=progress.refresh_complete,
                )

            if targets.same_major is not None:
                _install_and_refresh(project_path, progress, targets.same_major)

            if targets.next_major is not None:
                try:
                    highlights = fetch_release_highlights(targets.next_major, client)
                except Exception:
                    if (
                        mode is UpdateMode.AUTOMATIC
                        and progress.installed_version is not None
                        and progress.reload_current_skill
                        and not progress.state.pending_refresh
                    ):
                        return UpdateResult(
                            UpdateStatus.UPDATED,
                            current_version,
                            installed_version=progress.installed_version,
                            refreshed_providers=progress.refreshed_providers,
                            reload_current_skill=True,
                            refresh_complete=progress.refresh_complete,
                        )
                    raise
                if highlights is None:
                    return _metadata_unavailable_result(
                        mode,
                        current_version,
                        installed_version=progress.installed_version,
                        refreshed_providers=progress.refreshed_providers,
                        reload_current_skill=progress.reload_current_skill,
                        refresh_complete=progress.refresh_complete,
                    )
                return UpdateResult(
                    UpdateStatus.MAJOR_AVAILABLE,
                    current_version,
                    installed_version=progress.installed_version,
                    major=highlights,
                    refreshed_providers=progress.refreshed_providers,
                    reload_current_skill=progress.reload_current_skill,
                    refresh_complete=progress.refresh_complete,
                )

        if progress.installed_version is not None or progress.recovered_refresh:
            return UpdateResult(
                UpdateStatus.UPDATED,
                current_version,
                installed_version=progress.installed_version,
                refreshed_providers=progress.refreshed_providers,
                reload_current_skill=progress.reload_current_skill,
                refresh_complete=progress.refresh_complete,
            )
        return UpdateResult(UpdateStatus.CURRENT, current_version)
    except Exception as exc:  # noqa: BLE001 - preserve partial update progress
        return _operational_error(
            project_path,
            current_version,
            mode,
            progress,
            exc,
        )


def check_and_update(
    project_path: Path,
    current_version: str,
    mode: UpdateMode,
    approved_major: str | None = None,
    now: datetime | None = None,
) -> UpdateResult:
    """Check policy and apply eligible stable MAP updates for one project."""
    project_path = Path(project_path)
    effective_now = now or datetime.now(UTC)

    if approved_major is not None and mode is not UpdateMode.MANUAL:
        return _error(
            current_version, "A major version can be approved only in manual mode."
        )

    completed_result: UpdateResult | None = None
    try:
        if (
            mode is UpdateMode.AUTOMATIC
            and not load_map_config(project_path).updates_auto
        ):
            return UpdateResult(UpdateStatus.SKIPPED, current_version)

        install_kind = detect_install_kind(Path(__file__).with_name("__init__.py"))
        if install_kind is InstallKind.SOURCE:
            if mode is UpdateMode.AUTOMATIC:
                return UpdateResult(UpdateStatus.SKIPPED, current_version)
            return _error(
                current_version,
                "This mapify-cli installation is an owner-managed source checkout; "
                "update it from that source checkout and retry.",
            )

        try:
            with project_update_lock(project_path, timeout_s=LOCK_TIMEOUT_SECONDS):
                # Intent: Under update.lock, probe child-owned barriers before
                # reading recovery state or starting any package/provider mutation.
                with installer_process_probe(
                    project_path,
                    timeout_s=REFRESH_BARRIER_TIMEOUT_SECONDS,
                ):
                    pass
                with provider_refresh_lock(
                    project_path,
                    timeout_s=REFRESH_BARRIER_TIMEOUT_SECONDS,
                ):
                    pass
                completed_result = _check_locked(
                    project_path,
                    current_version,
                    mode,
                    approved_major,
                    effective_now,
                )
            return completed_result
        except UpdateLockBusy:
            if mode is UpdateMode.AUTOMATIC:
                return UpdateResult(UpdateStatus.SKIPPED, current_version)
            return _error(
                current_version,
                "Another MAP update is already running for this project; retry when it finishes.",
            )
    except Exception as exc:  # noqa: BLE001 - service-level result boundary
        try:
            state = read_update_state(project_path)
        except Exception:  # noqa: BLE001 - retain the original boundary failure
            state = UpdateState()
        return UpdateResult(
            UpdateStatus.ERROR,
            current_version,
            installed_version=(
                completed_result.installed_version
                if completed_result is not None
                and completed_result.installed_version is not None
                else state.last_installed_version if state.pending_refresh else None
            ),
            message=_actionable_error_message(exc, mode, state),
            refreshed_providers=(
                completed_result.refreshed_providers
                if completed_result is not None
                else ()
            ),
            reload_current_skill=(
                completed_result.reload_current_skill
                if completed_result is not None
                else False
            ),
            refresh_complete=(
                completed_result.refresh_complete
                if completed_result is not None
                else False
            ),
        )
