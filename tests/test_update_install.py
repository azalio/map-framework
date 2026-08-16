"""Exact package installation and installed-provider refresh boundaries."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from unittest.mock import Mock

import pytest

import mapify_cli.update_state as update_state_module
from mapify_cli.update_install import (
    InstallKind,
    PackageUpdateError,
    ProjectRefreshError,
    build_package_install_command,
    detect_install_kind,
    install_exact_version,
    installed_providers,
    refresh_installed_providers,
    resolve_mapify_executable,
    run_command,
    run_installer_controller,
)
from mapify_cli.update_state import (
    UpdateLockBusy,
    installer_process_lock,
    project_update_lock,
)
from mapify_cli.update_versions import StableVersion


@pytest.mark.parametrize(
    ("module_file", "expected"),
    [
        (
            (
                "/home/user/.local/share/uv/tools/mapify-cli/lib/python3.11/"
                "site-packages/mapify_cli/__init__.py"
            ),
            InstallKind.UV_TOOL,
        ),
        (
            "/venv/lib/python3.11/site-packages/mapify_cli/__init__.py",
            InstallKind.PIP,
        ),
        (
            r"C:\venv\Lib\site-packages\mapify_cli\__init__.py",
            InstallKind.PIP,
        ),
        (
            "/usr/lib/python3/dist-packages/mapify_cli/__init__.py",
            InstallKind.PIP,
        ),
        ("/workspace/map-framework/src/mapify_cli/__init__.py", InstallKind.SOURCE),
    ],
)
def test_install_kind_matches_public_upgrade_classification(
    module_file: str, expected: InstallKind
) -> None:
    assert detect_install_kind(module_file) is expected


def test_uv_tool_exact_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        shutil, "which", lambda name: "/usr/bin/uv" if name == "uv" else None
    )

    command = build_package_install_command(
        InstallKind.UV_TOOL, StableVersion(3, 26, 0)
    )

    assert command == [
        "/usr/bin/uv",
        "tool",
        "install",
        "--force",
        "mapify-cli==3.26.0",
    ]


def test_pip_exact_command() -> None:
    command = build_package_install_command(
        InstallKind.PIP,
        StableVersion(3, 26, 0),
        python_executable="/venv/bin/python",
    )

    assert command == [
        "/venv/bin/python",
        "-I",
        "-m",
        "pip",
        "install",
        "--upgrade",
        "mapify-cli==3.26.0",
    ]


def test_source_has_no_install_command() -> None:
    assert (
        build_package_install_command(InstallKind.SOURCE, StableVersion(3, 26, 0))
        is None
    )


def test_install_exact_command_uses_project_and_300_second_timeout(
    tmp_path: Path,
) -> None:
    calls: list[tuple[list[str], Path, float]] = []

    def runner(
        command: list[str], cwd: Path, timeout: float, env: Mapping[str, str]
    ) -> subprocess.CompletedProcess[str]:
        assert "MAP_UPDATE_PARENT_LEASE" not in env
        calls.append((command, cwd, timeout))
        return subprocess.CompletedProcess(command, 0, "installed", "")

    install_exact_version(
        tmp_path,
        StableVersion(3, 26, 0),
        module_file="/venv/lib/python3.11/site-packages/mapify_cli/__init__.py",
        runner=runner,
    )

    assert calls == [
        (
            [
                sys.executable,
                "-I",
                "-m",
                "pip",
                "install",
                "--upgrade",
                "mapify-cli==3.26.0",
            ],
            tmp_path,
            300.0,
        )
    ]


def test_install_authorizer_runs_before_package_start(
    tmp_path: Path,
) -> None:
    events: list[str] = []

    def authorize() -> None:
        events.append("intent-durable")

    def runner(
        command: list[str], cwd: Path, timeout: float, env: Mapping[str, str]
    ) -> subprocess.CompletedProcess[str]:
        del cwd, timeout, env
        assert events == ["intent-durable"]
        events.append("package-started")
        return subprocess.CompletedProcess(command, 0, "", "")

    install_exact_version(
        tmp_path,
        StableVersion(3, 26, 0),
        module_file="/venv/lib/python3.11/site-packages/mapify_cli/__init__.py",
        runner=runner,
        authorize_start=authorize,
    )

    assert events == ["intent-durable", "package-started"]


def test_install_authorizer_failure_prevents_package_start(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "package-started"

    def runner(
        command: list[str], cwd: Path, timeout: float, env: Mapping[str, str]
    ) -> subprocess.CompletedProcess[str]:
        del command, cwd, timeout, env
        marker.write_text("started\n", encoding="utf-8")
        raise AssertionError("package must not start")

    def reject() -> None:
        raise OSError("intent disk full")

    with pytest.raises(OSError, match="intent disk full"):
        install_exact_version(
            tmp_path,
            StableVersion(3, 26, 0),
            module_file="/venv/lib/python3.11/site-packages/mapify_cli/__init__.py",
            runner=runner,
            authorize_start=reject,
        )

    assert not marker.exists()


@pytest.mark.parametrize("shadow_location", ["cwd", "pythonpath"])
def test_controller_launch_ignores_untrusted_mapify_shadow(
    tmp_path: Path, shadow_location: str
) -> None:
    shadow_marker = tmp_path / "shadow-imported"
    package_marker = tmp_path / "trusted-package-started"
    authorized_marker = tmp_path / "intent-authorized"
    shadow_root = tmp_path if shadow_location == "cwd" else tmp_path / "injected"
    shadow_package = shadow_root / "mapify_cli"
    shadow_package.mkdir(parents=True)
    (shadow_package / "__init__.py").write_text("", encoding="utf-8")
    (shadow_package / "update_install.py").write_text(
        """
import json
import os
import sys
from pathlib import Path

Path(os.environ["MAP_TEST_SHADOW_MARKER"]).write_text(
    "shadowed\\n", encoding="utf-8"
)
Path(os.environ["MAP_UPDATE_INSTALL_READY"]).write_text(
    "fake-ready\\n", encoding="utf-8"
)
if sys.stdin.readline() == "GO\\n":
    print(json.dumps({
        "status": "completed",
        "returncode": 0,
        "stdout": "",
        "stderr": "",
    }))
""",
        encoding="utf-8",
    )
    child_code = """
import sys
from pathlib import Path

Path(sys.argv[1]).write_text("trusted\\n", encoding="utf-8")
"""
    environment = os.environ.copy()
    environment["MAP_TEST_SHADOW_MARKER"] = str(shadow_marker)
    if shadow_location == "pythonpath":
        environment["PYTHONPATH"] = str(shadow_root)

    result = run_installer_controller(
        [sys.executable, "-c", child_code, str(package_marker)],
        tmp_path,
        5.0,
        environment,
        authorize_start=lambda: authorized_marker.touch(),
    )

    assert result.returncode == 0
    assert authorized_marker.is_file()
    assert package_marker.is_file()
    assert not shadow_marker.exists()


@pytest.mark.parametrize("shadow_location", ["cwd", "pythonpath"])
def test_pip_launch_ignores_untrusted_module_shadow(
    tmp_path: Path, shadow_location: str
) -> None:
    shadow_marker = tmp_path / "shadow-pip-imported"
    shadow_root = tmp_path if shadow_location == "cwd" else tmp_path / "injected"
    shadow_package = shadow_root / "pip"
    shadow_package.mkdir(parents=True)
    (shadow_package / "__init__.py").write_text("", encoding="utf-8")
    (shadow_package / "__main__.py").write_text(
        """
import os
from pathlib import Path

Path(os.environ["MAP_TEST_PIP_SHADOW_MARKER"]).write_text(
    "shadowed\\n", encoding="utf-8"
)
""",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["MAP_TEST_PIP_SHADOW_MARKER"] = str(shadow_marker)
    if shadow_location == "pythonpath":
        environment["PYTHONPATH"] = str(shadow_root)
    install_command = build_package_install_command(
        InstallKind.PIP,
        StableVersion(3, 26, 0),
        python_executable=str(getattr(sys, "_base_executable", sys.executable)),
    )
    assert install_command is not None
    probe_command = [*install_command[: install_command.index("install")], "--version"]

    result = run_installer_controller(
        probe_command,
        tmp_path,
        5.0,
        environment,
        authorize_start=lambda: None,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("pip ")
    assert not shadow_marker.exists()


def _wait_for_path(path: Path, timeout_s: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.02)
    raise TimeoutError(f"timed out waiting for {path.name}")


ORPHAN_INSTALLER_PARENT = r'''
import os
import sys
from pathlib import Path

from mapify_cli.update_install import run_installer_controller
from mapify_cli.update_state import UpdateState, write_update_state

project = Path(sys.argv[1])
started = Path(sys.argv[2])
release = Path(sys.argv[3])
finished = Path(sys.argv[4])
child_code = r"""
import sys
import time
from pathlib import Path

started = Path(sys.argv[1])
release = Path(sys.argv[2])
finished = Path(sys.argv[3])
started.write_text("started\\n", encoding="utf-8")
while not release.exists():
    time.sleep(0.02)
finished.write_text("finished\\n", encoding="utf-8")
"""

def authorize() -> None:
    write_update_state(
        project,
        UpdateState(
            pending_install_version="3.26.0",
            pending_providers=("claude",),
        ),
    )
    (project / "intent-durable").write_text("ready\\n", encoding="utf-8")

run_installer_controller(
    [sys.executable, "-c", child_code, str(started), str(release), str(finished)],
    project,
    10.0,
    os.environ.copy(),
    authorize_start=authorize,
)
'''


PRE_GO_INSTALLER_PARENT = r'''
import os
import sys
import time
from pathlib import Path

from mapify_cli.update_install import run_installer_controller

project = Path(sys.argv[1])
authorized = Path(sys.argv[2])
package_started = Path(sys.argv[3])
child_code = r"""
import sys
from pathlib import Path

Path(sys.argv[1]).write_text("started\\n", encoding="utf-8")
"""

def authorize() -> None:
    authorized.write_text("ready\\n", encoding="utf-8")
    while True:
        time.sleep(1)

run_installer_controller(
    [sys.executable, "-c", child_code, str(package_started)],
    project,
    10.0,
    os.environ.copy(),
    authorize_start=authorize,
)
'''


@pytest.mark.timeout(15)
def test_parent_death_before_go_releases_barrier_without_starting_package(
    tmp_path: Path,
) -> None:
    authorized = tmp_path / "authorize-entered"
    package_started = tmp_path / "package-started"
    parent = subprocess.Popen(
        [
            sys.executable,
            "-c",
            PRE_GO_INSTALLER_PARENT,
            str(tmp_path),
            str(authorized),
            str(package_started),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_for_path(authorized)
        with (
            pytest.raises(UpdateLockBusy),
            installer_process_lock(tmp_path, timeout_s=0.0),
        ):
            raise AssertionError("READY must mean the controller owns the barrier")

        parent.kill()
        assert parent.wait(timeout=5.0) != 0

        deadline = time.monotonic() + 5.0
        while True:
            try:
                with installer_process_lock(tmp_path, timeout_s=0.0):
                    break
            except UpdateLockBusy:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.02)
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=5.0)

    assert not package_started.exists()
    assert parent.stderr is not None
    assert parent.stderr.read() == ""


@pytest.mark.timeout(15)
def test_orphan_installer_holds_project_barrier_until_package_exits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mapify_cli import auto_update
    from mapify_cli.auto_update import UpdateMode, UpdateStatus, check_and_update

    started = tmp_path / "installer-started"
    release = tmp_path / "release-installer"
    finished = tmp_path / "installer-finished"
    parent = subprocess.Popen(
        [
            sys.executable,
            "-c",
            ORPHAN_INSTALLER_PARENT,
            str(tmp_path),
            str(started),
            str(release),
            str(finished),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_for_path(tmp_path / "intent-durable")
        _wait_for_path(started)
        parent.kill()
        assert parent.wait(timeout=5.0) != 0

        with (
            pytest.raises(UpdateLockBusy),
            installer_process_lock(tmp_path, timeout_s=0.0),
        ):
            raise AssertionError("orphan package manager must retain its barrier")

        fetch = Mock(side_effect=AssertionError("orphan must precede network"))
        install = Mock(side_effect=AssertionError("second install must not start"))
        refresh = Mock(side_effect=AssertionError("refresh must wait for installer"))
        monkeypatch.setattr(
            auto_update,
            "detect_install_kind",
            lambda module_file: InstallKind.PIP,
        )
        monkeypatch.setattr(auto_update, "fetch_version_targets", fetch)
        monkeypatch.setattr(auto_update, "install_exact_version", install)
        monkeypatch.setattr(auto_update, "refresh_installed_providers", refresh)

        automatic = check_and_update(
            tmp_path,
            "3.26.0",
            UpdateMode.AUTOMATIC,
        )
        manual = check_and_update(tmp_path, "3.25.0", UpdateMode.MANUAL)

        assert automatic.status is UpdateStatus.SKIPPED
        assert manual.status is UpdateStatus.ERROR
        assert manual.message is not None and "already running" in manual.message
        fetch.assert_not_called()
        install.assert_not_called()
        refresh.assert_not_called()

        release.write_text("go\n", encoding="utf-8")
        _wait_for_path(finished)

        deadline = time.monotonic() + 5.0
        while True:
            try:
                with installer_process_lock(tmp_path, timeout_s=0.0):
                    break
            except UpdateLockBusy:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.02)

        monkeypatch.setattr(
            auto_update,
            "refresh_installed_providers",
            lambda project, providers: tuple(providers),
        )
        recovered = check_and_update(
            tmp_path,
            "3.26.0",
            UpdateMode.AUTOMATIC,
        )
        assert recovered.status is UpdateStatus.UPDATED
        fetch.assert_not_called()
        install.assert_not_called()
    finally:
        release.write_text("go\n", encoding="utf-8")
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=5.0)

    assert parent.stderr is not None
    assert parent.stderr.read() == ""


def test_install_exact_command_failure_has_bounded_actionable_stderr(
    tmp_path: Path,
) -> None:
    stderr = "installer failed: " + ("x" * 10_000) + "END-OF-STDERR"

    def runner(
        command: list[str], cwd: Path, timeout: float, env: Mapping[str, str]
    ) -> subprocess.CompletedProcess[str]:
        del cwd, timeout, env
        return subprocess.CompletedProcess(command, 23, "", stderr)

    with pytest.raises(PackageUpdateError) as exc_info:
        install_exact_version(
            tmp_path,
            StableVersion(3, 26, 0),
            module_file="/venv/lib/python3.11/site-packages/mapify_cli/__init__.py",
            runner=runner,
        )

    message = str(exc_info.value)
    assert "exit 23" in message
    assert "installer failed:" in message
    assert "END-OF-STDERR" not in message
    assert len(message) < 5_000


def test_install_exact_command_failure_falls_back_to_stdout(tmp_path: Path) -> None:
    def runner(
        command: list[str], cwd: Path, timeout: float, env: Mapping[str, str]
    ) -> subprocess.CompletedProcess[str]:
        del cwd, timeout, env
        return subprocess.CompletedProcess(
            command,
            23,
            "installer explained failure on stdout",
            "",
        )

    with pytest.raises(PackageUpdateError) as exc_info:
        install_exact_version(
            tmp_path,
            StableVersion(3, 26, 0),
            module_file="/venv/lib/python3.11/site-packages/mapify_cli/__init__.py",
            runner=runner,
        )

    assert "installer explained failure on stdout" in str(exc_info.value)


def test_source_install_exact_command_explains_manual_update(tmp_path: Path) -> None:
    with pytest.raises(PackageUpdateError, match="source checkout"):
        install_exact_version(
            tmp_path,
            StableVersion(3, 26, 0),
            module_file="/workspace/map-framework/src/mapify_cli/__init__.py",
        )


def test_install_exact_command_timeout_is_actionable(tmp_path: Path) -> None:
    def runner(
        command: list[str], cwd: Path, timeout: float, env: Mapping[str, str]
    ) -> subprocess.CompletedProcess[str]:
        del cwd, env
        raise subprocess.TimeoutExpired(command, timeout, stderr="network stalled")

    with pytest.raises(PackageUpdateError, match="timed out after 300 seconds"):
        install_exact_version(
            tmp_path,
            StableVersion(3, 26, 0),
            module_file="/venv/lib/python3.11/site-packages/mapify_cli/__init__.py",
            runner=runner,
        )


def test_install_exact_command_missing_runner_executable_is_actionable(
    tmp_path: Path,
) -> None:
    def runner(
        command: list[str], cwd: Path, timeout: float, env: Mapping[str, str]
    ) -> subprocess.CompletedProcess[str]:
        del command, cwd, timeout, env
        raise FileNotFoundError("python vanished")

    with pytest.raises(PackageUpdateError, match="could not be started") as exc_info:
        install_exact_version(
            tmp_path,
            StableVersion(3, 26, 0),
            module_file="/venv/lib/python3.11/site-packages/mapify_cli/__init__.py",
            runner=runner,
        )

    assert "python vanished" in str(exc_info.value)


def test_run_command_captures_text_without_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: dict[str, object] = {}

    def fake_run(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        observed["command"] = command
        observed.update(kwargs)
        return subprocess.CompletedProcess(command, 7, "out", "err")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = run_command(["tool", "arg"], tmp_path, 300.0, env={"SAFE": "1"})

    assert result.returncode == 7
    assert observed == {
        "command": ["tool", "arg"],
        "cwd": tmp_path,
        "timeout": 300.0,
        "check": False,
        "capture_output": True,
        "text": True,
        "env": {"SAFE": "1"},
    }


def test_package_install_strips_parent_lease_from_child_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_name = getattr(
        update_state_module,
        "MAP_UPDATE_PARENT_LEASE_ENV",
        "MAP_UPDATE_PARENT_LEASE",
    )
    monkeypatch.setenv(env_name, "ambient-forged-value")
    observed: dict[str, str] = {}

    def runner(
        command: list[str],
        cwd: Path,
        timeout: float,
        env: Mapping[str, str],
    ) -> subprocess.CompletedProcess[str]:
        del cwd, timeout
        observed.update(env)
        return subprocess.CompletedProcess(command, 0, "", "")

    install_exact_version(
        tmp_path,
        StableVersion(3, 26, 0),
        module_file="/venv/lib/python3.11/site-packages/mapify_cli/__init__.py",
        runner=runner,
    )

    assert env_name not in observed


def test_refresh_passes_active_parent_lease_only_in_provider_child_environment(
    tmp_path: Path,
) -> None:
    env_name = getattr(
        update_state_module,
        "MAP_UPDATE_PARENT_LEASE_ENV",
        "MAP_UPDATE_PARENT_LEASE",
    )
    calls: list[tuple[list[str], Mapping[str, str]]] = []

    def runner(
        command: list[str],
        cwd: Path,
        timeout: float,
        env: Mapping[str, str],
    ) -> subprocess.CompletedProcess[str]:
        del cwd, timeout
        calls.append((command, env))
        return subprocess.CompletedProcess(command, 0, "", "")

    with project_update_lock(tmp_path, timeout_s=0.0) as lease:
        refreshed = refresh_installed_providers(
            tmp_path,
            ("claude", "codex"),
            mapify_executable="/bin/mapify",
            runner=runner,
        )

    assert refreshed == ("claude", "codex")
    assert len(calls) == 2
    for command, env in calls:
        assert lease.token not in command
        assert env[env_name] == lease.token


def test_dual_provider_detection_is_deterministic(tmp_path: Path) -> None:
    (tmp_path / ".claude" / "skills").mkdir(parents=True)
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex" / "config.toml").write_text("", encoding="utf-8")
    (tmp_path / ".agents" / "skills").mkdir(parents=True)

    assert installed_providers(tmp_path) == ("claude", "codex")


def test_provider_detection_requires_complete_layouts(tmp_path: Path) -> None:
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex" / "config.toml").write_text("", encoding="utf-8")

    assert installed_providers(tmp_path) == ()

    (tmp_path / ".agents" / "skills").mkdir(parents=True)

    assert installed_providers(tmp_path) == ("codex",)


def test_refresh_runs_fresh_mapify_init_for_both_providers(tmp_path: Path) -> None:
    calls: list[tuple[list[str], Path, float]] = []

    def runner(
        command: list[str], cwd: Path, timeout: float, env: Mapping[str, str]
    ) -> subprocess.CompletedProcess[str]:
        assert "MAP_UPDATE_PARENT_LEASE" not in env
        calls.append((command, cwd, timeout))
        return subprocess.CompletedProcess(command, 0, "", "")

    refreshed = refresh_installed_providers(
        tmp_path,
        ("claude", "codex"),
        mapify_executable="/bin/mapify",
        runner=runner,
    )

    assert refreshed == ("claude", "codex")
    assert calls == [
        (
            [
                "/bin/mapify",
                "init",
                ".",
                "--force",
                "--no-git",
                "--provider",
                "claude",
                "--refresh-existing",
            ],
            tmp_path,
            300.0,
        ),
        (
            [
                "/bin/mapify",
                "init",
                ".",
                "--force",
                "--no-git",
                "--provider",
                "codex",
                "--refresh-existing",
            ],
            tmp_path,
            300.0,
        ),
    ]


def test_refresh_failure_reports_completed_and_pending_providers(
    tmp_path: Path,
) -> None:
    stderr = "refresh failed: " + ("x" * 10_000) + "END-OF-STDERR"

    def runner(
        command: list[str], cwd: Path, timeout: float, env: Mapping[str, str]
    ) -> subprocess.CompletedProcess[str]:
        del cwd, timeout, env
        if command[command.index("--provider") + 1] == "claude":
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(command, 19, "", stderr)

    with pytest.raises(ProjectRefreshError) as exc_info:
        refresh_installed_providers(
            tmp_path,
            ("claude", "codex"),
            mapify_executable="/bin/mapify",
            runner=runner,
        )

    error = exc_info.value
    assert error.refreshed_providers == ("claude",)
    assert error.pending_providers == ("codex",)
    assert "codex" in str(error)
    assert "exit 19" in str(error)
    assert "refresh failed:" in str(error)
    assert "END-OF-STDERR" not in str(error)
    assert len(str(error)) < 5_000


def test_refresh_failure_falls_back_to_stdout_and_redacts_parent_lease(
    tmp_path: Path,
) -> None:
    env_name = update_state_module.MAP_UPDATE_PARENT_LEASE_ENV

    def runner(
        command: list[str], cwd: Path, timeout: float, env: Mapping[str, str]
    ) -> subprocess.CompletedProcess[str]:
        del cwd, timeout
        lease = env[env_name]
        stdout = (
            f"provider explained failure on stdout; bare={lease}; {env_name}={lease}"
        )
        return subprocess.CompletedProcess(command, 19, stdout, "")

    with (
        project_update_lock(tmp_path, timeout_s=0.0) as lease,
        pytest.raises(ProjectRefreshError) as exc_info,
    ):
        refresh_installed_providers(
            tmp_path,
            ("claude",),
            mapify_executable="/bin/mapify",
            runner=runner,
        )

    message = str(exc_info.value)
    assert "provider explained failure on stdout" in message
    assert lease.token not in message
    assert f"{env_name}=<redacted>" in message


def test_refresh_timeout_preserves_full_pending_state(tmp_path: Path) -> None:
    def runner(
        command: list[str], cwd: Path, timeout: float, env: Mapping[str, str]
    ) -> subprocess.CompletedProcess[str]:
        del cwd, env
        raise subprocess.TimeoutExpired(command, timeout, stderr="too slow")

    with pytest.raises(ProjectRefreshError) as exc_info:
        refresh_installed_providers(
            tmp_path,
            ("claude", "codex"),
            mapify_executable="/bin/mapify",
            runner=runner,
        )

    error = exc_info.value
    assert error.refreshed_providers == ()
    assert error.pending_providers == ("claude", "codex")
    assert "timed out after 300 seconds" in str(error)


def test_refresh_missing_executable_preserves_full_pending_state(
    tmp_path: Path,
) -> None:
    def runner(
        command: list[str], cwd: Path, timeout: float, env: Mapping[str, str]
    ) -> subprocess.CompletedProcess[str]:
        del command, cwd, timeout, env
        raise FileNotFoundError("mapify vanished")

    with pytest.raises(ProjectRefreshError) as exc_info:
        refresh_installed_providers(
            tmp_path,
            ("claude", "codex"),
            mapify_executable="/bin/mapify",
            runner=runner,
        )

    error = exc_info.value
    assert error.refreshed_providers == ()
    assert error.pending_providers == ("claude", "codex")
    assert "could not be started" in str(error)
    assert "mapify vanished" in str(error)


def test_resolve_mapify_prefers_current_interpreter_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    python = tmp_path / ("python.exe" if os.name == "nt" else "python")
    mapify = tmp_path / ("mapify.exe" if os.name == "nt" else "mapify")
    python.touch()
    mapify.touch()
    monkeypatch.setattr(sys, "executable", str(python))
    monkeypatch.setattr(shutil, "which", lambda name: "/other/mapify")

    assert resolve_mapify_executable() == str(mapify)


def test_resolve_mapify_falls_back_to_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    python = tmp_path / ("python.exe" if os.name == "nt" else "python")
    python.touch()
    monkeypatch.setattr(sys, "executable", str(python))
    monkeypatch.setattr(
        shutil, "which", lambda name: "/path/bin/mapify" if name == "mapify" else None
    )

    assert resolve_mapify_executable() == "/path/bin/mapify"


def test_resolve_mapify_missing_is_actionable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    python = tmp_path / ("python.exe" if os.name == "nt" else "python")
    python.touch()
    monkeypatch.setattr(sys, "executable", str(python))
    monkeypatch.setattr(shutil, "which", lambda name: None)

    with pytest.raises(ProjectRefreshError, match="mapify executable") as exc_info:
        resolve_mapify_executable()

    assert "current Python environment" in str(exc_info.value)


def test_refresh_resolution_failure_preserves_all_pending_providers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    python = tmp_path / ("python.exe" if os.name == "nt" else "python")
    python.touch()
    monkeypatch.setattr(sys, "executable", str(python))
    monkeypatch.setattr(shutil, "which", lambda name: None)

    with pytest.raises(ProjectRefreshError) as exc_info:
        refresh_installed_providers(tmp_path, ("claude", "codex"))

    assert exc_info.value.refreshed_providers == ()
    assert exc_info.value.pending_providers == ("claude", "codex")
