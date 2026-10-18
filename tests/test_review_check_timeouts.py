"""Public runner checks use admission-bound execution deadlines."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests.review_process_lifecycle import ReviewProcessLifecycle

pytestmark = pytest.mark.timeout(120)

RUNNER = Path(__file__).resolve().parents[1] / "src/mapify_cli/templates/map/scripts/map_step_runner.py"


@pytest.fixture()
def check_workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-b", "main"], check=True, capture_output=True)
    for key, value in (("user.email", "test@example.com"), ("user.name", "Test")):
        subprocess.run(["git", "config", key, value], check=True)
    Path(".gitignore").write_text(".map/\n")
    Path("writer.py").write_text("VALUE = 1\n")
    subprocess.run(["git", "add", "."], check=True)
    subprocess.run(["git", "commit", "-m", "base"], check=True, capture_output=True)
    with ReviewProcessLifecycle(tmp_path) as lifecycle:
        lifecycle.recover(lambda: (tmp_path / ".map/main/signal-fault").unlink(missing_ok=True))
        lifecycle.recover(lambda: (tmp_path / ".map/main/inspection-fault").unlink(missing_ok=True))
        lifecycle.recover(lambda: (tmp_path / ".map/main/release").touch()
                          if (tmp_path / ".map/main").exists() else None)
        yield tmp_path / ".map/main/review-verdict-ledger.json"


def _cli(*args):
    process = ReviewProcessLifecycle(Path.cwd() / ".map").run([sys.executable, str(RUNNER), *args])
    assert process.stdout, process.stderr
    return json.loads(process.stdout)


def _admit(timeout):
    return _cli("begin_review_run", "--mode", "lightweight", "--round-id", "timeout",
                "--required-check", "suite", "--check-specs-json",
                json.dumps({"suite": [sys.executable, "-c", "import time; time.sleep(0.15)"]}),
                "--check-timeouts-json", json.dumps({"suite": timeout}))


def test_custom_check_timeout_is_enforced_and_frozen(check_workspace):
    admission = _admit(0.02)
    assert admission["status"] == "success", admission
    result = _cli("run_test_gate", "--check-id", "suite")
    assert result["passed"] is False and result["exit_code"] is None, result
    ledger = json.loads(check_workspace.read_text())
    assert ledger["execution_checks"]["suite"]["status"] == "timeout"
    assert ledger["execution_checks"]["suite"]["timeout_seconds"] == 0.02
    assert ledger["convergence"]["rounds"][0]["binding"]["check_timeouts"] == {"suite": 0.02}
    before = check_workspace.read_bytes()
    changed = _admit(2)
    assert changed["status"] == "error", changed
    assert check_workspace.read_bytes() == before


def test_custom_check_timeout_allows_success(check_workspace):
    del check_workspace
    assert _admit(2)["status"] == "success"
    result = _cli("run_test_gate", "--check-id", "suite")
    assert result["passed"] is True and result["exit_code"] == 0, result


@pytest.mark.parametrize("timeout", [0, -1, True, "2", None, float("nan"), float("inf")])
def test_invalid_check_timeout_rejected_without_admission(check_workspace, timeout):
    result = _admit(timeout)
    assert result["status"] == "error", result
    assert not check_workspace.exists()


def _alive(pid):
    result = subprocess.run(["/bin/ps", "-p", str(pid), "-o", "stat="], capture_output=True,
                            text=True, check=False, timeout=2)
    return bool(result.stdout.strip()) and not result.stdout.strip().startswith("Z")


@pytest.mark.parametrize("kill_runner", [False, True])
def test_nested_check_keeps_lease_until_descendant_stops(check_workspace, kill_runner):
    marker = check_workspace.parent / "child.pid"
    release = check_workspace.parent / "release"
    child = ("import os,time; from pathlib import Path; "
             f"Path({str(marker)!r}).write_text(str(os.getpid())); "
             f"release=Path({str(release)!r}); "
             "exec('while not release.exists(): time.sleep(.02)')")
    wrapper = ("import subprocess,sys; "
               f"subprocess.run([sys.executable, '-c', {child!r}], "
               "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)")
    admitted = _cli("begin_review_run", "--mode", "lightweight", "--round-id", "nested",
                    "--required-check", "suite", "--check-specs-json",
                    json.dumps({"suite": [sys.executable, "-c", wrapper]}),
                    "--check-timeouts-json", json.dumps({"suite": 1.5}))
    assert admitted["status"] == "success", admitted
    process = subprocess.Popen([sys.executable, str(RUNNER), "run_test_gate", "--check-id", "suite"],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(.02)
        assert marker.exists()
        pid = int(marker.read_text())
        first = json.loads(check_workspace.read_text())["execution_checks"]["suite"]["attempt_id"]
        if kill_runner:
            process.kill()
            process.wait(timeout=3)
            assert _alive(pid)
            blocked = _cli("run_test_gate", "--check-id", "suite")
            assert blocked["status"] == "error" and "still running" in blocked["message"], blocked
            deadline = time.monotonic() + 5
            while _alive(pid) and time.monotonic() < deadline:
                time.sleep(.02)
        else:
            stdout, stderr = process.communicate(timeout=8)
            assert stdout, stderr
            result = json.loads(stdout)
            assert result["passed"] is False and result["exit_code"] is None, result
        assert not _alive(pid), "lease was released while ordinary nested check survived"
        release.touch()
        retried = _cli("run_test_gate", "--check-id", "suite")
        assert retried["passed"] is True, retried
        assert retried["attempt_id"] != first
        if kill_runner:
            history = json.loads(check_workspace.read_text())["execution_check_history"]
            assert any(row["attempt_id"] == first and row["state"] == "interrupted" for row in history)
    finally:
        release.touch()
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)


@pytest.mark.parametrize("exit_code", [0, 7])
def test_wrapper_exit_cleans_live_background_child(check_workspace, exit_code):
    marker = check_workspace.parent / "background.pid"
    child = f"import os,time; from pathlib import Path; Path({str(marker)!r}).write_text(str(os.getpid())); time.sleep(10)"
    wrapper = ("import subprocess,sys,time; from pathlib import Path; "
               f"subprocess.Popen([sys.executable,'-c',{child!r}], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); "
               f"\nwhile not Path({str(marker)!r}).exists(): time.sleep(.01)\nsys.exit({exit_code})")
    assert _cli("begin_review_run", "--mode", "lightweight", "--required-check", "suite", "--check-specs-json",
                json.dumps({"suite": [sys.executable, "-c", wrapper]}),
                "--check-timeouts-json", '{"suite": 5}')["status"] == "success"
    result = _cli("run_test_gate", "--check-id", "suite")
    pid = int(marker.read_text())
    assert result["exit_code"] == exit_code, result
    assert result["passed"] == (exit_code == 0), result
    assert not _alive(pid)


@pytest.mark.parametrize("signal_delivered", [True, False])
def test_signal_permission_error_releases_only_quiescent_group(check_workspace, monkeypatch, signal_delivered):
    directory = check_workspace.parent
    fault = directory / "signal-fault"
    directory.mkdir(parents=True)
    fault.touch()
    injection = directory / "python-fault"
    injection.mkdir()
    (injection / "sitecustomize.py").write_text(
        "import os, sys, time\nfrom pathlib import Path\n"
        "if sys.argv[0].endswith('review_check_supervisor.py') and 'supervise' in sys.argv:\n"
        "    original = os.killpg\n"
        "    def denied(group, sig):\n"
        f"        if Path({str(fault)!r}).exists():\n"
        f"            if {signal_delivered!r}:\n"
        "                original(group, sig)\n"
        "                time.sleep(0.05)\n"
        "            raise PermissionError(1, 'injected signal permission error')\n"
        "        return original(group, sig)\n"
        "    os.killpg = denied\n"
    )
    monkeypatch.setenv("PYTHONPATH", str(injection))
    assert _admit(2)["status"] == "success"
    try:
        result = _cli("run_test_gate", "--check-id", "suite")
        if signal_delivered:
            assert result["passed"] is True and result["state"] == "finished", result
            retried = _cli("run_test_gate", "--check-id", "suite")
            assert retried["passed"] is True, retried
            assert retried["attempt_id"] != result["attempt_id"]
        else:
            assert result["status"] == "cleanup_blocked" and result["passed"] is False, result
            assert result["state"] == "running"
            blocked = _cli("run_test_gate", "--check-id", "suite")
            assert blocked["status"] == "error" and "still running" in blocked["message"], blocked
    finally:
        fault.unlink(missing_ok=True)
    deadline = time.monotonic() + 5
    recovered = {"passed": False}
    while time.monotonic() < deadline:
        recovered = _cli("run_test_gate", "--check-id", "suite")
        if recovered.get("passed"):
            break
        time.sleep(.05)
    assert recovered["passed"] is True, recovered


def test_cleanup_inspection_failure_is_visible_and_recovers(check_workspace, monkeypatch):
    directory = check_workspace.parent
    fault = directory / "inspection-fault"
    shim = directory / "bin"
    shim.mkdir(parents=True)
    ps = shim / "ps"
    ps.write_text(f"#!/bin/sh\nif [ -e '{fault}' ]; then exit 1; fi\nexec /bin/ps \"$@\"\n")
    ps.chmod(0o755)
    monkeypatch.setenv("PATH", str(shim) + os.pathsep + os.environ["PATH"])
    command = [sys.executable, "-c", f"from pathlib import Path; Path({str(fault)!r}).touch()"]
    assert _cli("begin_review_run", "--mode", "lightweight", "--required-check", "suite", "--check-specs-json",
                json.dumps({"suite": command}), "--check-timeouts-json", '{"suite": 5}')["status"] == "success"
    try:
        result = _cli("run_test_gate", "--check-id", "suite")
        assert result["status"] == "cleanup_blocked" and result["passed"] is False, result
        assert result["state"] == "running"
        first = result["attempt_id"]
        assert "restore process inspection" in result["message"]
        blocked = _cli("run_test_gate", "--check-id", "suite")
        assert blocked["status"] == "error" and "still running" in blocked["message"], blocked
    finally:
        fault.unlink(missing_ok=True)
        ps.write_text('#!/bin/sh\nexec /bin/ps "$@"\n')
    deadline = time.monotonic() + 5
    retried = {"passed": False, "message": "Retry deadline expired"}
    while time.monotonic() < deadline:
        retried = _cli("run_test_gate", "--check-id", "suite")
        if retried.get("attempt_id") != first and retried.get("passed"):
            break
        time.sleep(.05)
    assert retried["passed"] is True, retried
    history = json.loads(check_workspace.read_text())["execution_check_history"]
    assert any(row["attempt_id"] == first and row["state"] == "interrupted" for row in history)


def test_inspection_preflight_failure_does_not_launch_check(check_workspace, monkeypatch):
    directory = check_workspace.parent
    shim = directory / "bin"
    shim.mkdir(parents=True)
    ps = shim / "ps"
    ps.write_text("#!/bin/sh\nexit 1\n")
    ps.chmod(0o755)
    monkeypatch.setenv("PATH", str(shim) + os.pathsep + os.environ["PATH"])
    marker = directory / "must-not-run"
    command = [sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).touch()"]
    assert _cli("begin_review_run", "--mode", "lightweight", "--required-check", "suite", "--check-specs-json",
                json.dumps({"suite": command}), "--check-timeouts-json", '{"suite": 5}')["status"] == "success"
    result = _cli("run_test_gate", "--check-id", "suite")
    assert result["passed"] is False and result["state"] == "finished", result
    assert not marker.exists()
    ps.write_text('#!/bin/sh\nexec /bin/ps "$@"\n')
    assert _cli("run_test_gate", "--check-id", "suite")["passed"] is True
    assert marker.exists()


def test_missing_check_executable_releases_ownership(check_workspace):
    missing = str(check_workspace.parent / "no-such-command")
    assert _cli("begin_review_run", "--mode", "lightweight", "--required-check", "suite", "--check-specs-json",
                json.dumps({"suite": [missing]}))["status"] == "success"
    first = _cli("run_test_gate", "--check-id", "suite")
    second = _cli("run_test_gate", "--check-id", "suite")
    assert first["passed"] is False and first["state"] == "finished", first
    assert second["passed"] is False and second["state"] == "finished", second
    assert first["attempt_id"] != second["attempt_id"]


def test_timeout_for_unadmitted_check_rejected(check_workspace):
    result = _cli("begin_review_run", "--mode", "lightweight", "--check-timeouts-json", '{"missing": 2}')
    assert result["status"] == "error", result
    assert not check_workspace.exists()
