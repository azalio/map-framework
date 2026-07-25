"""Reusable fake Task tool for concurrent-dispatch harness tests.

Provides a threading.Barrier(N)-based fake that records started/finished
lifecycle events (matching the ST-002 event vocabulary + a monotonic seq)
and tracks max_in_flight.

Deadlock proof: when N tasks are submitted to a SERIAL runner, the first task
blocks on barrier.wait(timeout=2.0) indefinitely waiting for N participants
to arrive; since the serial runner never reaches task 2..N, barrier.wait()
raises BrokenBarrierError (bounded timeout, not wall-clock perf measurement).
A CONCURRENT runner starts all N tasks in parallel; all arrive at the barrier
simultaneously → barrier releases → all complete → max_in_flight == N.
"""

from __future__ import annotations

import threading
import time
from typing import Any


class FakeTaskTool:
    """Callable fake Task tool backed by a shared threading.Barrier(N).

    Each call (one per simulated actor):
    1. records a 'started' lifecycle event (seq = next monotonic int)
    2. calls barrier.wait(timeout=2.0) — blocks until N tasks are all in-flight
    3. records a 'finished' lifecycle event
    4. tracks max_in_flight under a lock

    Thread-safety: all shared state is guarded by _lock.
    """

    def __init__(self, n_parties: int) -> None:
        """Initialise with a barrier for n_parties concurrent participants."""
        self._barrier: threading.Barrier = threading.Barrier(n_parties)
        self._lock: threading.Lock = threading.Lock()
        self._seq: int = 0
        self._in_flight: int = 0
        self._max_in_flight: int = 0
        self.events: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Public query interface
    # ------------------------------------------------------------------

    @property
    def max_in_flight(self) -> int:
        """Maximum number of concurrently-running tasks observed."""
        with self._lock:
            return self._max_in_flight

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _next_seq(self) -> int:
        """Return the next monotonically-increasing sequence number (lock held by caller)."""
        self._seq += 1
        return self._seq

    def _record(self, event_type: str, subtask_id: str) -> None:
        """Append a lifecycle event dict (lock held by caller)."""
        self.events.append(
            {
                "seq": self._next_seq(),
                "event": event_type,
                "subtask_id": subtask_id,
                "ts": time.monotonic(),  # recorded for debug; classifier ignores ts
            }
        )

    # ------------------------------------------------------------------
    # Callable interface — one call per simulated actor dispatch
    # ------------------------------------------------------------------

    def __call__(self, subtask_id: str = "ST-X") -> dict[str, Any]:
        """Simulate a single actor Task dispatch.

        Args:
            subtask_id: Identifier for the simulated subtask (used in events).

        Returns:
            A dict with status and recorded lifecycle events for this call.

        Raises:
            threading.BrokenBarrierError: When the barrier is broken due to
                timeout (i.e., not enough participants arrived — serial host
                deadlock detected).
        """
        with self._lock:
            self._record("started", subtask_id)
            self._in_flight += 1
            self._max_in_flight = max(self._max_in_flight, self._in_flight)

        # Barrier wait OUTSIDE the lock — must not hold the lock here,
        # otherwise other tasks cannot acquire it to record 'started'.
        # timeout=2.0 s → BrokenBarrierError on serial host (deadlock detector,
        # NOT a wall-clock performance assertion).
        self._barrier.wait(timeout=2.0)

        with self._lock:
            self._in_flight = max(0, self._in_flight - 1)
            self._record("finished", subtask_id)

        return {"status": "success", "subtask_id": subtask_id}
