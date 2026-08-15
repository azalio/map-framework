"""Exact package installation and installed-provider refresh boundaries."""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from enum import StrEnum
from pathlib import Path

from mapify_cli.update_state import (
    MAP_UPDATE_PARENT_LEASE_ENV,
    current_project_update_lease,
    installer_process_lock,
)
from mapify_cli.update_versions import StableVersion

COMMAND_TIMEOUT_SECONDS = 300.0
MAX_ERROR_OUTPUT_CHARS = 4_096
INSTALLER_HANDSHAKE_TIMEOUT_SECONDS = 5.0
INSTALLER_RESULT_GRACE_SECONDS = 5.0
_LEASE_ASSIGNMENT_RE = re.compile(rf"{re.escape(MAP_UPDATE_PARENT_LEASE_ENV)}=[^\s,;]+")
_INSTALL_WORKER_PROJECT_ENV = "MAP_UPDATE_INSTALL_PROJECT"
_INSTALL_WORKER_COMMAND_ENV = "MAP_UPDATE_INSTALL_COMMAND"
_INSTALL_WORKER_TIMEOUT_ENV = "MAP_UPDATE_INSTALL_TIMEOUT"
_INSTALL_WORKER_READY_ENV = "MAP_UPDATE_INSTALL_READY"
_INSTALL_WORKER_ENV_NAMES = (
    _INSTALL_WORKER_PROJECT_ENV,
    _INSTALL_WORKER_COMMAND_ENV,
    _INSTALL_WORKER_TIMEOUT_ENV,
    _INSTALL_WORKER_READY_ENV,
)
_INSTALL_WORKER_BOOTSTRAP = """
import sys

sys.path.insert(0, sys.argv[1])
from mapify_cli.update_install import _installer_worker_main

raise SystemExit(_installer_worker_main())
"""

CommandRunner = Callable[
    [list[str], Path, float, Mapping[str, str]],
    subprocess.CompletedProcess[str],
]
InstallStartAuthorizer = Callable[[], None]


class InstallKind(StrEnum):
    """Supported mapify-cli installation layouts."""

    UV_TOOL = "uv-tool"
    PIP = "pip"
    SOURCE = "source"


class PackageUpdateError(RuntimeError):
    """Exact package installation failed."""


class ProjectRefreshError(RuntimeError):
    """One or more installed provider surfaces could not be refreshed."""

    def __init__(
        self,
        message: str,
        *,
        refreshed_providers: tuple[str, ...] = (),
        pending_providers: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.refreshed_providers = refreshed_providers
        self.pending_providers = pending_providers


class _InstallAuthorizationFailure(RuntimeError):
    """Carry an intent-write error across controller cleanup unchanged."""

    def __init__(self, original: Exception) -> None:
        super().__init__(str(original))
        self.original = original


def run_command(
    command: list[str],
    cwd: Path,
    timeout: float,
    env: Mapping[str, str],
) -> subprocess.CompletedProcess[str]:
    """Run one bounded command while capturing text output for diagnostics."""
    return subprocess.run(
        command,
        cwd=cwd,
        timeout=timeout,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def _child_environment(parent_lease: str | None = None) -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop(MAP_UPDATE_PARENT_LEASE_ENV, None)
    if parent_lease is not None:
        environment[MAP_UPDATE_PARENT_LEASE_ENV] = parent_lease
    return environment


def detect_install_kind(module_file: str | Path) -> InstallKind:
    """Classify a package module path like the existing public upgrade command."""
    package_path = str(Path(module_file).resolve()).replace("\\", "/")
    if "/uv/tools/" in package_path:
        return InstallKind.UV_TOOL
    if "/site-packages/" in package_path or "/dist-packages/" in package_path:
        return InstallKind.PIP
    return InstallKind.SOURCE


def build_package_install_command(
    kind: InstallKind,
    version: StableVersion,
    *,
    python_executable: str | None = None,
) -> list[str] | None:
    """Build the exact, argument-array package installation command."""
    requirement = f"mapify-cli=={version}"
    if kind is InstallKind.UV_TOOL:
        uv = shutil.which("uv")
        if uv is None:
            return None
        return [uv, "tool", "install", "--force", requirement]
    if kind is InstallKind.PIP:
        return [
            python_executable or sys.executable,
            "-I",
            "-m",
            "pip",
            "install",
            "--upgrade",
            requirement,
        ]
    return None


def _redacted_diagnostic(
    output: str | bytes | None,
    sensitive_values: Sequence[str],
) -> str:
    if isinstance(output, bytes):
        value = output.decode(errors="replace")
    else:
        value = output or ""
    for sensitive in sensitive_values:
        if sensitive:
            value = value.replace(sensitive, "<redacted>")
    return _LEASE_ASSIGNMENT_RE.sub(
        f"{MAP_UPDATE_PARENT_LEASE_ENV}=<redacted>",
        value,
    ).strip()


def _bounded_subprocess_diagnostic(
    stderr: str | bytes | None,
    stdout: str | bytes | None = None,
    *,
    sensitive_values: Sequence[str] = (),
) -> str:
    """Return bounded, stderr-first subprocess diagnostics with secrets removed."""
    value = _redacted_diagnostic(stderr, sensitive_values)
    if not value:
        value = _redacted_diagnostic(stdout, sensitive_values)
    if not value:
        return "no stdout/stderr output"
    return value[:MAX_ERROR_OUTPUT_CHARS]


def _clean_installer_environment(environment: Mapping[str, str]) -> dict[str, str]:
    cleaned = dict(environment)
    cleaned.pop(MAP_UPDATE_PARENT_LEASE_ENV, None)
    for name in _INSTALL_WORKER_ENV_NAMES:
        cleaned.pop(name, None)
    return cleaned


def _write_worker_result(payload: Mapping[str, object]) -> None:
    """Write one bounded controller result without abandoning the barrier early."""
    with contextlib.suppress(BrokenPipeError, OSError):
        sys.stdout.write(json.dumps(dict(payload), sort_keys=True) + "\n")
        sys.stdout.flush()


def _installer_worker_main() -> int:
    """Own installer.lock across the real package-manager child lifetime."""
    try:
        project = Path(os.environ[_INSTALL_WORKER_PROJECT_ENV]).resolve()
        command_payload = json.loads(os.environ[_INSTALL_WORKER_COMMAND_ENV])
        timeout = float(os.environ[_INSTALL_WORKER_TIMEOUT_ENV])
        ready_path = Path(os.environ[_INSTALL_WORKER_READY_ENV])
        if (
            not isinstance(command_payload, list)
            or not command_payload
            or not all(isinstance(arg, str) and arg for arg in command_payload)
            or timeout <= 0
        ):
            raise ValueError("invalid installer controller request")
        command = list(command_payload)

        with installer_process_lock(
            project,
            timeout_s=INSTALLER_HANDSHAKE_TIMEOUT_SECONDS,
        ):
            ready_path.write_text("ready\n", encoding="utf-8")
            # EOF means the updater died before authorizing package mutation.
            if sys.stdin.readline() != "GO\n":
                return 0
            try:
                result = run_command(
                    command,
                    project,
                    timeout,
                    _clean_installer_environment(os.environ),
                )
            except subprocess.TimeoutExpired as exc:
                _write_worker_result(
                    {
                        "status": "timeout",
                        "stdout": _redacted_diagnostic(exc.stdout, ())[
                            :MAX_ERROR_OUTPUT_CHARS
                        ],
                        "stderr": _redacted_diagnostic(exc.stderr, ())[
                            :MAX_ERROR_OUTPUT_CHARS
                        ],
                    }
                )
                return 0
            except OSError as exc:
                _write_worker_result(
                    {
                        "status": "oserror",
                        "message": _redacted_diagnostic(str(exc), ())[
                            :MAX_ERROR_OUTPUT_CHARS
                        ],
                    }
                )
                return 0

            _write_worker_result(
                {
                    "status": "completed",
                    "returncode": result.returncode,
                    "stdout": _redacted_diagnostic(result.stdout, ())[
                        :MAX_ERROR_OUTPUT_CHARS
                    ],
                    "stderr": _redacted_diagnostic(result.stderr, ())[
                        :MAX_ERROR_OUTPUT_CHARS
                    ],
                }
            )
            return 0
    except Exception as exc:  # noqa: BLE001 - isolated worker protocol boundary
        _write_worker_result(
            {
                "status": "worker_error",
                "message": _redacted_diagnostic(str(exc), ())[:MAX_ERROR_OUTPUT_CHARS],
            }
        )
        return 1


def _stop_pre_go_worker(process: subprocess.Popen[str]) -> None:
    """Close authorization input and reap a controller that cannot have run pip."""
    if process.stdin is not None:
        with contextlib.suppress(BrokenPipeError, OSError):
            process.stdin.close()
        process.stdin = None
    try:
        process.wait(timeout=INSTALLER_HANDSHAKE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=INSTALLER_HANDSHAKE_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=INSTALLER_HANDSHAKE_TIMEOUT_SECONDS)


def run_installer_controller(
    command: list[str],
    cwd: Path,
    timeout: float,
    env: Mapping[str, str],
    *,
    authorize_start: InstallStartAuthorizer,
) -> subprocess.CompletedProcess[str]:
    """Handshake with a child-owned installer barrier before authorizing GO."""
    project = cwd.resolve()
    with tempfile.TemporaryDirectory(prefix="mapify-installer-") as handshake_dir:
        ready_path = Path(handshake_dir) / "ready"
        worker_environment = _clean_installer_environment(env)
        worker_environment.update(
            {
                _INSTALL_WORKER_PROJECT_ENV: str(project),
                _INSTALL_WORKER_COMMAND_ENV: json.dumps(command),
                _INSTALL_WORKER_TIMEOUT_ENV: str(timeout),
                _INSTALL_WORKER_READY_ENV: str(ready_path),
            }
        )
        process = subprocess.Popen(
            [
                sys.executable,
                "-I",
                "-c",
                _INSTALL_WORKER_BOOTSTRAP,
                str(Path(__file__).resolve().parent.parent),
            ],
            cwd=project,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=worker_environment,
        )

        deadline = time.monotonic() + INSTALLER_HANDSHAKE_TIMEOUT_SECONDS
        while not ready_path.is_file():
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                diagnostic = _bounded_subprocess_diagnostic(stderr, stdout)
                raise OSError("installer controller exited before READY: " + diagnostic)
            if time.monotonic() >= deadline:
                _stop_pre_go_worker(process)
                raise OSError(
                    "installer controller did not acquire its project barrier "
                    f"within {INSTALLER_HANDSHAKE_TIMEOUT_SECONDS:g} seconds"
                )
            time.sleep(0.01)

        try:
            authorize_start()
        except Exception as exc:
            _stop_pre_go_worker(process)
            raise _InstallAuthorizationFailure(exc) from exc
        except BaseException:
            _stop_pre_go_worker(process)
            raise

        try:
            assert process.stdin is not None
            process.stdin.write("GO\n")
            process.stdin.flush()
            process.stdin.close()
            process.stdin = None
        except (BrokenPipeError, OSError) as exc:
            stdout, stderr = process.communicate()
            diagnostic = _bounded_subprocess_diagnostic(stderr, stdout)
            raise OSError(f"installer controller rejected GO: {diagnostic}") from exc

        # Do not kill the controller on timeout: if its package child is still
        # alive, the controller must retain installer.lock until that child exits.
        stdout, stderr = process.communicate(
            timeout=timeout + INSTALLER_RESULT_GRACE_SECONDS
        )

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        diagnostic = _bounded_subprocess_diagnostic(stderr, stdout)
        raise OSError(f"invalid installer controller result: {diagnostic}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("status"), str):
        raise OSError("invalid installer controller result")
    status = payload["status"]
    if status == "completed":
        returncode = payload.get("returncode")
        if type(returncode) is not int:
            raise OSError("invalid installer controller completion result")
        return subprocess.CompletedProcess(
            command,
            returncode,
            str(payload.get("stdout", "")),
            str(payload.get("stderr", "")),
        )
    if status == "timeout":
        raise subprocess.TimeoutExpired(
            command,
            timeout,
            output=str(payload.get("stdout", "")),
            stderr=str(payload.get("stderr", "")),
        )
    message = str(payload.get("message", "installer controller failed"))
    raise OSError(message[:MAX_ERROR_OUTPUT_CHARS])


def install_exact_version(
    project_path: Path,
    version: StableVersion,
    *,
    module_file: str | Path | None = None,
    runner: CommandRunner = run_command,
    authorize_start: InstallStartAuthorizer = lambda: None,
) -> None:
    """Install one exact stable mapify-cli version in the current environment."""
    package_module = module_file or Path(__file__).with_name("__init__.py")
    install_kind = detect_install_kind(package_module)
    command = build_package_install_command(install_kind, version)
    if command is None:
        if install_kind is InstallKind.SOURCE:
            raise PackageUpdateError(
                "mapify-cli is running from a source checkout; update the checkout "
                "manually before refreshing this project"
            )
        raise PackageUpdateError(
            "mapify-cli is installed as a uv tool, but the uv executable could not "
            "be found; install uv or update mapify-cli manually"
        )

    try:
        # Intent: The production controller owns installer.lock before the durable
        # authorization callback, and receives GO only after that callback succeeds.
        # Test runners retain the same authorize-before-package boundary in-process.
        if runner is run_command:
            result = run_installer_controller(
                command,
                project_path,
                COMMAND_TIMEOUT_SECONDS,
                _child_environment(),
                authorize_start=authorize_start,
            )
        else:
            with installer_process_lock(project_path, timeout_s=0.0):
                try:
                    authorize_start()
                except Exception as exc:
                    raise _InstallAuthorizationFailure(exc) from exc
                result = runner(
                    command,
                    project_path,
                    COMMAND_TIMEOUT_SECONDS,
                    _child_environment(),
                )
    except _InstallAuthorizationFailure as exc:
        raise exc.original
    except subprocess.TimeoutExpired as exc:
        raise PackageUpdateError(
            f"Exact mapify-cli {version} installation timed out after "
            f"{COMMAND_TIMEOUT_SECONDS:g} seconds: "
            f"{_bounded_subprocess_diagnostic(exc.stderr, exc.stdout)}"
        ) from exc
    except OSError as exc:
        raise PackageUpdateError(
            f"Exact mapify-cli {version} installation could not be started: {exc}"
        ) from exc
    if result.returncode != 0:
        raise PackageUpdateError(
            f"Exact mapify-cli {version} installation failed with exit "
            f"{result.returncode}: "
            f"{_bounded_subprocess_diagnostic(result.stderr, result.stdout)}"
        )


def installed_providers(project_path: Path) -> tuple[str, ...]:
    """Return complete installed provider layouts in canonical order."""
    providers: list[str] = []
    if (project_path / ".claude" / "skills").is_dir():
        providers.append("claude")
    if (project_path / ".codex" / "config.toml").is_file() and (
        project_path / ".agents" / "skills"
    ).is_dir():
        providers.append("codex")
    return tuple(providers)


def resolve_mapify_executable() -> str:
    """Resolve mapify from the current interpreter environment before PATH."""
    executable_name = "mapify.exe" if os.name == "nt" else "mapify"
    environment_mapify = Path(sys.executable).with_name(executable_name)
    if environment_mapify.is_file():
        return str(environment_mapify)

    path_mapify = shutil.which("mapify")
    if path_mapify is not None:
        return path_mapify

    raise ProjectRefreshError(
        "Could not find the mapify executable in the current Python environment "
        "or on PATH; reinstall mapify-cli in this environment and retry"
    )


def refresh_installed_providers(
    project_path: Path,
    providers: Sequence[str],
    *,
    mapify_executable: str | Path | None = None,
    runner: CommandRunner = run_command,
) -> tuple[str, ...]:
    """Refresh each installed provider in a newly launched mapify process."""
    pending = tuple(providers)
    if mapify_executable is not None:
        executable = str(mapify_executable)
    else:
        try:
            executable = resolve_mapify_executable()
        except ProjectRefreshError as exc:
            raise ProjectRefreshError(str(exc), pending_providers=pending) from exc
    refreshed: list[str] = []
    parent_lease = current_project_update_lease(project_path)
    sensitive_values = (parent_lease.token,) if parent_lease is not None else ()
    child_environment = _child_environment(
        parent_lease.token if parent_lease is not None else None
    )

    for index, provider in enumerate(pending):
        command = [
            executable,
            "init",
            ".",
            "--force",
            "--no-git",
            "--provider",
            provider,
            "--refresh-existing",
        ]
        remaining = pending[index:]
        try:
            result = runner(
                command,
                project_path,
                COMMAND_TIMEOUT_SECONDS,
                child_environment,
            )
        except subprocess.TimeoutExpired as exc:
            raise ProjectRefreshError(
                f"Refreshing the {provider} provider timed out after "
                f"{COMMAND_TIMEOUT_SECONDS:g} seconds: "
                f"{_bounded_subprocess_diagnostic(exc.stderr, exc.stdout, sensitive_values=sensitive_values)}",
                refreshed_providers=tuple(refreshed),
                pending_providers=remaining,
            ) from exc
        except OSError as exc:
            diagnostic = _redacted_diagnostic(str(exc), sensitive_values)
            raise ProjectRefreshError(
                f"Refreshing the {provider} provider could not be started: "
                f"{diagnostic[:MAX_ERROR_OUTPUT_CHARS]}",
                refreshed_providers=tuple(refreshed),
                pending_providers=remaining,
            ) from exc

        if result.returncode != 0:
            raise ProjectRefreshError(
                f"Refreshing the {provider} provider failed with exit "
                f"{result.returncode}: "
                f"{_bounded_subprocess_diagnostic(result.stderr, result.stdout, sensitive_values=sensitive_values)}",
                refreshed_providers=tuple(refreshed),
                pending_providers=remaining,
            )
        refreshed.append(provider)

    return tuple(refreshed)


if __name__ == "__main__":
    raise SystemExit(_installer_worker_main())
