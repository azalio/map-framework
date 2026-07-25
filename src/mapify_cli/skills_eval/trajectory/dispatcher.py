"""Trajectory run dispatcher.

Runs ONE full interactive MAP skill invocation to completion in a seeded
throwaway cwd and returns the run outcome (raw output, usage, duration,
error).  Sibling to ``skills_eval.dispatcher``: that dispatcher measures
TRIGGER accuracy (skill body never executes); this dispatcher EXECUTES the
whole skill body so the trajectory can be scored end-to-end.

Hard constraints (inherited):
- INV-2: ``MockTrajectoryDispatcher`` performs ZERO subprocess work.
- INV-3: no ``import anthropic`` / no ANTHROPIC_API_KEY.
- INV-5: production ``.claude/`` / ``.map/`` never modified — only the
  throwaway seeded copy (seeding.seed_temp).
"""

from __future__ import annotations

import logging
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class RunOutcome:
    """Outcome of one full skill invocation.

    Mirrors the ``run_meta`` bucket the spike wrote per run.  ``error`` is
    set on timeout/OSError/non-zero exit; the runner records it (VC4) rather
    than raising.
    """

    ok: bool
    returncode: int | None
    raw_output: str
    session_id: str | None = None
    duration_s: float = 0.0
    usage: dict[str, Any] = field(default_factory=dict)
    stderr_tail: str = ""
    error: str | None = None


class TrajectoryDispatcher(ABC):
    """Abstract: run *invocation* in *cwd* and return a ``RunOutcome``."""

    @abstractmethod
    def run(
        self,
        invocation: str,
        cwd: Path,
        timeout: float,
    ) -> RunOutcome:
        """Execute the skill invocation. MUST NOT raise (VC4)."""


class MockTrajectoryDispatcher(TrajectoryDispatcher):
    """Zero-subprocess dispatcher for CI tests (INV-2).

    Returns a caller-supplied ``RunOutcome`` (or a clean default) regardless
    of the invocation.  The cwd is NOT modified — tests that need a realistic
    bundle feed artifacts directly or via a fixture.
    """

    def __init__(self, *, outcome: RunOutcome | None = None) -> None:
        self._outcome = outcome or RunOutcome(
            ok=True,
            returncode=0,
            raw_output="mock: completed the task",
            session_id="mock-session",
            duration_s=0.1,
        )

    def run(
        self, invocation: str, cwd: Path, timeout: float
    ) -> RunOutcome:
        del invocation, cwd, timeout  # mock ignores all
        return self._outcome


class ClaudeTrajectoryDispatcher(TrajectoryDispatcher):
    """Real ``claude -p`` invocation executing the full skill body.

    ``acceptEdits`` auto-accepts file edits so the run is not blocked by
    interactive permission prompts in headless mode (spike precedent: without
    this, weaker models stall on permission-denial — an agency artifact that
    confounds any trajectory comparison).  Optional ``orchestrator_model``
    becomes the top-level ``--model`` (sub-agents still use their own
    ``model:`` frontmatter set during seeding).
    """

    def __init__(self, *, orchestrator_model: str | None = None) -> None:
        self._orchestrator_model = orchestrator_model

    def run(self, invocation: str, cwd: Path, timeout: float) -> RunOutcome:
        from mapify_cli.skills_eval.dispatcher import (
            _eval_subprocess_env,
            _parse_envelope,
        )

        argv = [
            "claude",
            "-p",
            invocation,
            "--output-format",
            "json",
            "--permission-mode",
            "acceptEdits",
        ]
        if self._orchestrator_model:
            argv += ["--model", self._orchestrator_model]
        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
                env=_eval_subprocess_env(cwd),
                check=False,
            )
        except subprocess.TimeoutExpired:
            return RunOutcome(
                ok=False,
                returncode=None,
                raw_output="",
                duration_s=time.monotonic() - t0,
                error=f"timeout after {timeout}s",
            )
        except OSError as exc:
            return RunOutcome(
                ok=False,
                returncode=None,
                raw_output="",
                duration_s=time.monotonic() - t0,
                error=f"OSError: {exc}",
            )
        duration = time.monotonic() - t0
        raw, usage, session_id = _parse_envelope(proc.stdout)
        usage_dict: dict[str, Any] = {}
        if usage is not None:
            usage_dict = {
                "input_tokens": usage.input_tokens,
                "cache_read_input_tokens": usage.cache_read_input_tokens,
                "cache_creation_input_tokens": usage.cache_creation_input_tokens,
            }
        return RunOutcome(
            ok=proc.returncode == 0,
            returncode=proc.returncode,
            raw_output=raw,
            session_id=session_id,
            duration_s=duration,
            usage=usage_dict,
            stderr_tail=(proc.stderr[-1500:] if proc.stderr else ""),
            error=(None if proc.returncode == 0 else f"claude exit {proc.returncode}"),
        )
