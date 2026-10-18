"""Bound review-test waits without signalling detached or persisted PIDs.

This is not emergency containment: restore registered faults, allow runtime
ownership cleanup, and fail with retained artifacts if quiescence is unproven.
"""

import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from types import TracebackType


class ReviewProcessLifecycle:
    def __init__(self, root: Path, timeout: float = 12):
        self.root = root.resolve()
        self.timeout = timeout
        self._recoveries: list[Callable[[], object]] = []

    def __enter__(self):
        return self

    def __exit__(self, _kind: type[BaseException] | None, error: BaseException | None,
                 _traceback: TracebackType | None) -> None:
        try:
            self.close()
        except Exception as cleanup_error:
            if error is None:
                raise
            # Preserve the original failure while making failed teardown visible.
            error.add_note(f"Review process teardown failed: {cleanup_error}")

    def recover(self, callback: Callable[[], object]) -> None:
        self._recoveries.append(callback)

    def run(self, command: list[str], *, timeout: float = 30,
            cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        self.root.mkdir(parents=True, exist_ok=True)
        # Files, not PIPEs: inherited descriptors cannot trap communicate() after
        # killing the immediate child on TimeoutExpired. Keep evidence on disk.
        with tempfile.NamedTemporaryFile(dir=self.root, prefix="process-", suffix=".stdout",
                                         delete=False) as stdout:
            stderr_path = Path(stdout.name).with_suffix(".stderr")
            stdout_path = Path(stdout.name)
            with stderr_path.open("wb") as stderr:
                process = subprocess.run(command, cwd=cwd, stdout=stdout, stderr=stderr,
                                         timeout=timeout, check=False)
            return subprocess.CompletedProcess(command, process.returncode,
                                               stdout_path.read_text(errors="replace"),
                                               stderr_path.read_text(errors="replace"))

    def live_processes(self) -> list[str]:
        result = subprocess.run(["/bin/ps", "-ww", "-axo", "pid=,ppid=,pgid=,stat=,command="],
                                capture_output=True, text=True, timeout=2, check=True)
        rows = [line.split(None, 4) for line in result.stdout.splitlines() if line.strip()]
        if not rows or any(len(row) != 5 or not all(value.isdigit() for value in row[:3]) for row in rows):
            raise RuntimeError("Cannot parse process ownership inspection")
        # Observation only. No PID from this snapshot is ever signalled. Include
        # zombie anchors to retain group association until runtime reaps them.
        owners = [row for row in rows if "review_check_supervisor.py" in row[4]
                  and str(self.root) + "/" in row[4]]
        groups = {row[2] for row in owners}
        owned = {row[0] for row in owners}
        while True:
            descendants = {row[0] for row in rows if row[1] in owned or row[2] in groups}
            if descendants <= owned:
                break
            owned |= descendants
        return [" ".join(row) for row in rows if row[0] in owned and not row[3].startswith("Z")]

    @staticmethod
    def wait_for_file(path: Path, *, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while not path.exists():
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out waiting for {path}")
            time.sleep(.02)

    def close(self) -> None:
        failures = []
        for callback in reversed(self._recoveries):
            try:
                callback()
            except (OSError, RuntimeError, ValueError) as exc:
                failures.append(str(exc))
        self._recoveries.clear()
        deadline = time.monotonic() + self.timeout
        while True:
            live = self.live_processes()
            if not live:
                break
            if time.monotonic() >= deadline:
                failures.append("Owned processes still live: " + repr(live))
                break
            time.sleep(.05)
        if failures:
            raise AssertionError(f"Review teardown failed; evidence retained in {self.root}: {failures}")
