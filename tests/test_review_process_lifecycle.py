"""Exercise the finalizer used by review integration-test workspaces."""

import fcntl
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests.review_process_lifecycle import ReviewProcessLifecycle

pytestmark = pytest.mark.timeout(120)

SUPERVISOR = (Path(__file__).resolve().parents[1]
              / "src/mapify_cli/templates/map/scripts/review_check_supervisor.py")


def test_process_inspection_requests_unlimited_command_width(tmp_path, monkeypatch):
    lifecycle = ReviewProcessLifecycle(tmp_path / ("long-workspace-" * 10))
    command = ("/very/long/interpreter/" + "nested/" * 40
               + f"python {SUPERVISOR} supervise {lifecycle.root}/attempt 3 5 python -c pass")

    def snapshot(argv, **kwargs):
        assert kwargs["timeout"] == 2
        # Deterministically model Linux ps width truncation on every platform.
        visible_command = command if "-ww" in argv else command[:80]
        output = (f"900 1 900 Ss {visible_command}\n"
                  "901 900 901 Ss python anchor\n"
                  "902 901 901 S python worker\n")
        return subprocess.CompletedProcess(argv, 0, output, "")

    monkeypatch.setattr(subprocess, "run", snapshot)
    found = lifecycle.live_processes()
    assert {row.split()[0] for row in found} == {"900", "901", "902"}


@pytest.mark.parametrize(("outcome", "long_root"), [
    ("normal", False), ("assertion", False), ("timeout", False),
    ("noop-finalizer", False), ("noop-finalizer", True),
])
def test_review_finalizer_restores_fault_and_waits_for_owned_processes(tmp_path, outcome, long_root, monkeypatch):
    if long_root:
        tmp_path = tmp_path / ("long-workspace-" * 10) / ("long-attempt-parent-" * 8)
        tmp_path.mkdir(parents=True)
    fault = tmp_path / "inspection-fault"
    shim = tmp_path / "bin"
    shim.mkdir()
    ps = shim / "ps"
    ps.write_text(f'#!/bin/sh\nif [ -e "{fault}" ]; then exit 1; fi\nexec /bin/ps "$@"\n')
    ps.chmod(0o755)
    attempt = tmp_path / "attempt"
    attempt.mkdir()
    owner = None
    lifecycle = ReviewProcessLifecycle(tmp_path)
    if outcome == "noop-finalizer":
        monkeypatch.setattr(lifecycle, "close", lambda: None)
    try:
        with lifecycle:
            lifecycle.recover(lambda: fault.unlink(missing_ok=True))
            with (tmp_path / "lease").open("w") as lease:
                owner = subprocess.Popen(
                    [sys.executable, str(SUPERVISOR), "supervise", str(attempt),
                     str(lease.fileno()), "5", sys.executable, "-c",
                     f"from pathlib import Path; Path({str(fault)!r}).touch()"],
                    pass_fds=(lease.fileno(),), start_new_session=True,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    env={**os.environ, "PATH": str(shim) + os.pathsep + os.environ["PATH"]},
                )
            lifecycle.wait_for_file(attempt / "supervisor.json", timeout=8)
            receipt = json.loads((attempt / "supervisor.json").read_text())
            assert receipt["status"] == "cleanup_blocked", receipt
            assert fault.exists(), "check must activate the inspection fault"
            assert owner.poll() is None, "fault must retain the ownership guard"
            if outcome == "assertion":
                raise AssertionError("original assertion")
            if outcome == "timeout":
                lifecycle.run([sys.executable, "-c", "import time; time.sleep(60)"], timeout=0.1)
    except AssertionError as exc:
        if outcome != "assertion" or str(exc) != "original assertion":
            raise
    except subprocess.TimeoutExpired:
        if outcome != "timeout":
            raise
    else:
        assert outcome in {"normal", "noop-finalizer"}
        if outcome == "noop-finalizer":
            assert fault.exists()
            assert owner is not None and owner.poll() is None
            assert lifecycle.live_processes(), "negative control must detect the retained guard"
    finally:
        try:
            if outcome != "noop-finalizer":
                assert not fault.exists(), "finalizer must restore the fault before fallback cleanup"
                assert lifecycle.live_processes() == [], "finalizer must wait for owned processes"
        finally:
            fault.unlink(missing_ok=True)
            if owner is not None:
                owner.wait(timeout=8)
    assert not fault.exists()
    assert lifecycle.live_processes() == []


def _runtime_snapshot(pids):
    """Observe known identities even after their supervisor has disappeared."""
    result = subprocess.run(
        ["/bin/ps", "-ww", "-axo", "pid=,ppid=,pgid=,stat=,command="],
        capture_output=True, text=True, timeout=2, check=True,
    )
    return [line.strip() for line in result.stdout.splitlines()
            if line.strip() and int(line.split()[0]) in pids]


@pytest.mark.parametrize("outcome", ["success", "failure", "timeout", "parent-exit", "parent-sigkill"])
def test_runtime_cleanup_precedes_fixture_teardown(tmp_path, outcome):
    """The actual detached runtime, not fixture recovery, must end its group."""
    attempt = tmp_path / "attempt"
    attempt.mkdir()
    marker = tmp_path / "identities.json"
    ready = tmp_path / "supervisor.pid"
    release = tmp_path / "release"
    lease_path = tmp_path / "lease"
    # Success/failure exercise cleanup, not startup speed under CI scheduling.
    check_timeout = 15 if outcome in {"success", "failure"} else 2
    # An ordinary grandchild closes inherited FDs. Keep it alive past wrapper
    # success/failure so command completion alone cannot satisfy the assertion.
    child = (
        "import os,time; from pathlib import Path; "
        f"Path({str(tmp_path / 'child.pid')!r}).write_text(str(os.getpid())); "
        "time.sleep(30)"
    )
    wrapper = (
        "import json,os,subprocess,sys,time; from pathlib import Path\n"
        f"child=subprocess.Popen([sys.executable,'-c',{child!r}], close_fds=True, "
        "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        f"while not Path({str(tmp_path / 'child.pid')!r}).exists(): time.sleep(.01)\n"
        f"Path({str(marker)!r}).write_text(json.dumps(dict(anchor=os.getppid(), "
        "wrapper=os.getpid(), child=child.pid)))\n"
        f"while not Path({str(release)!r}).exists(): time.sleep(.01)\n"
        f"sys.exit({7 if outcome == 'failure' else 0})\n"
    )
    parent_code = (
        "import fcntl,subprocess,sys,time; from pathlib import Path\n"
        f"with Path({str(lease_path)!r}).open('w') as lease:\n"
        " fcntl.flock(lease, fcntl.LOCK_EX)\n"
        f" owner=subprocess.Popen([sys.executable,{str(SUPERVISOR)!r},'supervise',"
        f"{str(attempt)!r},str(lease.fileno()),{str(check_timeout)!r},sys.executable,'-c',{wrapper!r}],"
        "pass_fds=(lease.fileno(),),start_new_session=True,"
        "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\n"
        f" Path({str(ready)!r}).write_text(str(owner.pid))\n"
        f" while not Path({str(marker)!r}).exists(): time.sleep(.01)\n"
        + (" time.sleep(30)\n" if outcome == "parent-sigkill" else
           "" if outcome == "parent-exit" else f" owner.wait(timeout={check_timeout + 8})\n")
    )
    lifecycle = ReviewProcessLifecycle(tmp_path, timeout=check_timeout + 8)
    with lifecycle:
        lifecycle.recover(release.touch)
        with subprocess.Popen([sys.executable, "-c", parent_code]) as parent:
            try:
                lifecycle.wait_for_file(marker, timeout=8)
                identities = json.loads(marker.read_text())
                identities.update(supervisor=int(ready.read_text()), parent=parent.pid)
                before = _runtime_snapshot(set(identities.values()))
                assert len(before) >= 4, before
                if outcome == "parent-sigkill":
                    parent.kill()
                if outcome in {"parent-exit", "parent-sigkill"}:
                    assert parent.wait(timeout=3) == (-9 if outcome == "parent-sigkill" else 0)
                else:
                    assert parent.poll() is None, "ordinary caller must wait for supervision"
                # Caller exit must NOT release ownership of the live group.
                with lease_path.open() as lease, pytest.raises(BlockingIOError):
                    fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
                if outcome in {"success", "failure"}:
                    release.touch()
                lifecycle.wait_for_file(attempt / "supervisor.json", timeout=8)
                receipt = json.loads((attempt / "supervisor.json").read_text())
                parent_exit = parent.wait(timeout=3)
                assert parent_exit == (-9 if outcome == "parent-sigkill" else 0)
                deadline = time.monotonic() + 3
                while True:
                    after = _runtime_snapshot(set(identities.values()))
                    live = [row for row in after if not row.split()[3].startswith("Z")]
                    if not live or time.monotonic() >= deadline:
                        break
                    time.sleep(.02)
                evidence = {"identities": identities, "parent_exit": parent_exit,
                            "before": before, "after": after, "receipt": receipt}
                # Persist and assert BEFORE the context manager's recovery callbacks.
                (tmp_path / "runtime-evidence.json").write_text(json.dumps(evidence, indent=2))
                assert not live, evidence
                assert all(int(row.split()[0]) != identities["anchor"] for row in after), evidence
                assert receipt["status"] == ("success" if outcome in {"success", "failure"} else "timeout"), evidence
                assert receipt["passed"] == (outcome == "success"), evidence
                with lease_path.open() as lease:
                    fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                if parent.poll() is None:
                    parent.kill()
                parent.wait(timeout=3)


@pytest.mark.parametrize("fault_kind", ["preflight", "missing-command", "cleanup-inspection"])
def test_abnormal_supervisor_releases_only_after_runtime_recovery(tmp_path, fault_kind):
    attempt = tmp_path / "attempt"
    attempt.mkdir()
    fault = tmp_path / "inspection-fault"
    shim = tmp_path / "bin"
    shim.mkdir()
    ps = shim / "ps"
    ps.write_text(f'#!/bin/sh\nif [ -e "{fault}" ]; then exit 1; fi\nexec /bin/ps "$@"\n')
    ps.chmod(0o755)
    marker = tmp_path / "ran"
    if fault_kind == "preflight":
        fault.touch()
    command = ([str(tmp_path / "absent-executable")] if fault_kind == "missing-command" else
               [sys.executable, "-c", "from pathlib import Path; "
                f"Path({str(marker)!r}).touch(); "
                + (f"Path({str(fault)!r}).touch()" if fault_kind == "cleanup-inspection" else "pass")])
    lifecycle = ReviewProcessLifecycle(tmp_path)
    with lifecycle:
        lifecycle.recover(lambda: fault.unlink(missing_ok=True))
        with (tmp_path / "lease").open("w") as lease:
            fcntl.flock(lease, fcntl.LOCK_EX)
            owner = subprocess.Popen(
                [sys.executable, str(SUPERVISOR), "supervise", str(attempt),
                 str(lease.fileno()), "2", *command],
                pass_fds=(lease.fileno(),), start_new_session=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                env={**os.environ, "PATH": str(shim) + os.pathsep + os.environ["PATH"]},
            )
        try:
            lifecycle.wait_for_file(attempt / "supervisor.json", timeout=8)
            blocked = json.loads((attempt / "supervisor.json").read_text())
            before = lifecycle.live_processes()
            if fault_kind == "cleanup-inspection":
                assert blocked["status"] == "cleanup_blocked", blocked
                assert owner.poll() is None
                with (tmp_path / "lease").open() as lease, pytest.raises(BlockingIOError):
                    fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fault.unlink()  # Explicit runtime recovery, NOT fixture teardown.
            exit_code = owner.wait(timeout=8)
            after = _runtime_snapshot({owner.pid, *(int(row.split()[0]) for row in before)})
            receipt = json.loads((attempt / "supervisor.json").read_text())
            evidence = {"pid": owner.pid, "exit_code": exit_code, "before": before,
                        "after": after, "initial_receipt": blocked, "receipt": receipt}
            (tmp_path / "runtime-evidence.json").write_text(json.dumps(evidence, indent=2))
            assert exit_code == 0 and not after, evidence
            assert receipt["status"] == ("success" if fault_kind == "cleanup-inspection" else "error"), evidence
            assert marker.exists() == (fault_kind == "cleanup-inspection")
            with (tmp_path / "lease").open() as lease:
                fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            fault.unlink(missing_ok=True)
            owner.wait(timeout=8)
