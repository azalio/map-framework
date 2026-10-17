"""Own a review check's process group and lease independently of its runner.

Ordinary descendants are contained even when they close inherited descriptors.
Explicit setsid/setpgid escapes and killing both ownership processes are outside
this contract. Never recover ownership by killing a PID saved on disk.
"""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def _write(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as handle:
        json.dump(value, handle)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def _live_group(group: int) -> bool:
    scan = subprocess.run(["ps", "-axo", "pid=,pgid=,stat="], capture_output=True,
                          text=True, timeout=5, check=True)
    rows = [line.split() for line in scan.stdout.splitlines() if line.strip()]
    if not rows or any(len(row) != 3 or not row[0].isdigit() or not row[1].isdigit() for row in rows):
        raise ValueError("Cannot parse process-group inspection")
    return any(int(row[1]) == group and not row[2].startswith("Z") for row in rows)


def _anchor(directory: Path, command: list[str]) -> None:
    # This process stays alive even after the command returns. Its PID/PGID
    # remains reserved until the supervisor finishes group cleanup and reaps it.
    try:
        result = subprocess.run(command, check=False)
        value = {"status": "success", "passed": result.returncode == 0, "exit_code": result.returncode}
    except OSError as exc:
        value = {"status": "error", "passed": False, "exit_code": None, "message": str(exc)}
    _write(directory / "command.json", value)
    while True:
        time.sleep(60)


def _supervise(directory: Path, lease_fd: int, timeout: float, command: list[str]) -> None:
    result_path = directory / "supervisor.json"
    anchor = None
    result = {"status": "timeout", "passed": False, "exit_code": None}
    deadline = time.monotonic() + timeout
    try:
        _live_group(-1)  # Fail before starting a check if inspection is unavailable.
        with (directory / "stdout").open("wb") as stdout, (directory / "stderr").open("wb") as stderr:
            anchor = subprocess.Popen(
                [sys.executable, __file__, "anchor", str(directory), *command],
                stdout=stdout, stderr=stderr, stdin=subprocess.DEVNULL,
                start_new_session=True, pass_fds=(lease_fd,),
            )
        while time.monotonic() < deadline:
            if (directory / "command.json").exists():
                result = json.loads((directory / "command.json").read_text())
                break
            time.sleep(0.02)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        result = {"status": "error", "passed": False, "exit_code": None, "message": str(exc)}
    finally:
        if anchor is not None:
            # Do not poll/wait the anchor here: even an exited leader must remain
            # unreaped so no unrelated process can reuse its PGID during cleanup.
            cleanup_started = time.monotonic()
            signalled = False
            while True:
                try:
                    if not signalled:
                        try:
                            os.killpg(anchor.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        signalled = True
                    if not _live_group(anchor.pid):
                        break
                    signalled = False  # Catch a descendant fork racing the first group signal.
                    if time.monotonic() - cleanup_started < 1:
                        time.sleep(0.02)
                        continue
                    reason = "Check process group has not stopped"
                except (OSError, ValueError, subprocess.SubprocessError) as exc:
                    reason = f"Cannot prove check process-group quiescence: {exc}"
                blocked = {"status": "cleanup_blocked", "passed": False, "exit_code": None,
                           "message": reason + "; restore process inspection and retry; do not delete the lock",
                           "supervisor_pid": os.getpid(), "process_group": anchor.pid}
                # A storage failure must not unwind ownership while children live.
                try:
                    _write(result_path, blocked)
                except OSError:
                    pass
                time.sleep(0.1)
            anchor.wait()
    _write(result_path, result)


if __name__ == "__main__":
    if sys.argv[1] == "anchor":
        _anchor(Path(sys.argv[2]), sys.argv[3:])
    else:
        _supervise(Path(sys.argv[2]), int(sys.argv[3]), float(sys.argv[4]), sys.argv[5:])
