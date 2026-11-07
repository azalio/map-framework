"""One load-tolerant deadline shared by process-spawning tests.

Wall-clock windows of a few seconds are met in isolation but missed when the
suite runs under xdist on a saturated host (interpreter start-up alone can take
several seconds). Waits that poll for an explicit readiness signal use this
bound; it is only ever reached when something is genuinely hung.
"""

import os
import subprocess

LOAD_DEADLINE = float(os.environ.get("MAP_TEST_LOAD_DEADLINE", "90"))
PS_ATTEMPTS = 3


def run_ps(argv: list[str], *, attempts: int = PS_ATTEMPTS,
           timeout: float = LOAD_DEADLINE / PS_ATTEMPTS) -> "subprocess.CompletedProcess[str]":
    """Run a process-inspection command; retry a timeout, never a real failure."""
    for attempt in range(attempts):
        try:
            return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=True)
        except subprocess.TimeoutExpired:
            if attempt == attempts - 1:
                raise
    raise AssertionError("unreachable")
