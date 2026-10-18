"""Exercise the finalizer used by review integration-test workspaces."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.review_process_lifecycle import ReviewProcessLifecycle

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
