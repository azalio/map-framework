"""Dormant observability scaffolding for parallel-wave execution.

This module defines:
  - The canonical, stable reason-code constants for worktree fallback and
    parallel-dispatch decisions (consumed by the runner in ST-009 and Slice 5).
  - The ``ParallelismReport`` TypedDict schema for
    ``.map/runs/<run_id>/parallelism.json``.
  - A ``write_parallelism_report`` writer that is NO-OP by default (gated on
    an explicit ``enabled=True`` argument or the ST-003 observability toggle).

Slice 5 will add the runtime writer/detection logic and must resolve the
runner-vs-CLI runtime-locality concern: the runner (.jinja template installed
in user repos) cannot import this CLI-side module in installed repos.  Slice 5
should either (a) duplicate the write path inside the runner .jinja with this
module as the canonical schema reference, or (b) expose a subprocess-callable
entry point that the runner shells out to.  Decide in the Slice 5 spike.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Canonical reason-code constants
# ---------------------------------------------------------------------------
# Worktree-fallback codes — values MUST match the runner's _WT_REASON_* in
# map_step_runner.py.jinja (a parity test in test_parallelism_observability.py
# enforces this invariant to prevent silent drift).

REASON_NOT_GIT_REPO: str = "not_git_repo"
REASON_WORKTREE_UNSUPPORTED: str = "worktree_unsupported"
REASON_WORKTREE_CREATE_FAILED: str = "worktree_create_failed"
REASON_DIRTY_MERGE_TARGET: str = "dirty_merge_target"

# Dispatch / observability codes (Slice 5+ consumers)
REASON_DISPATCH_SERIAL: str = "dispatch_serial"
REASON_PARALLEL_CAPPED_BY_MAX_ACTORS: str = "parallel_capped_by_max_actors"
REASON_MONITOR_REJECTED_SUBTASK: str = "monitor_rejected_subtask"
REASON_MERGE_CONFLICT: str = "merge_conflict"
REASON_POST_WAVE_GATE_FAILED: str = "post_wave_gate_failed"

# Validation set — all 9 canonical codes in one place.
ALL_REASON_CODES: frozenset[str] = frozenset(
    {
        REASON_NOT_GIT_REPO,
        REASON_WORKTREE_UNSUPPORTED,
        REASON_WORKTREE_CREATE_FAILED,
        REASON_DIRTY_MERGE_TARGET,
        REASON_DISPATCH_SERIAL,
        REASON_PARALLEL_CAPPED_BY_MAX_ACTORS,
        REASON_MONITOR_REJECTED_SUBTASK,
        REASON_MERGE_CONFLICT,
        REASON_POST_WAVE_GATE_FAILED,
    }
)

# ---------------------------------------------------------------------------
# Schema: ParallelismReport
# ---------------------------------------------------------------------------
# Defined once here (TypedDict per the contract-first learned rule).
# Slice 5 imports this type to populate and write the report.

from typing import TypedDict  # noqa: E402 — grouped after constants for readability


class ColorGroupDecision(TypedDict):
    """Per color-group (wave sub-group) dispatch decision record."""

    group_id: str
    """Identifier for this color group within the wave."""

    planned_mode: str
    """Mode selected by the config predicate: 'sequential' | 'parallel'."""

    actual_mode: str
    """Mode actually executed after fallback resolution."""

    worktree_status: str
    """Worktree probe outcome: 'ok' | 'skipped' | reason_code."""

    reason_code: Optional[str]
    """Populated when actual_mode != planned_mode; one of ALL_REASON_CODES."""

    dispatch_count: int
    """Number of subtasks dispatched in this group."""


class ParallelismReport(TypedDict):
    """Schema for .map/runs/<run_id>/parallelism.json.

    Caller (Slice 5) supplies ``run_id`` and ``generated_at``; this module
    never calls ``datetime.now()`` (clock-free per the learned rule).
    """

    schema_version: str
    """Semver for this schema — bump when fields are added/removed."""

    run_id: str
    """Unique run identifier; matches the ``.map/runs/<run_id>/`` directory."""

    generated_at: str
    """ISO-8601 timestamp, supplied by the caller (not generated here)."""

    # Plan summary
    total_subtasks: int
    total_edges: int
    total_waves: int
    max_wave_width: int
    """Width of the widest wave (max parallel color groups)."""

    color_group_breakdown: list[ColorGroupDecision]
    """One entry per color group, in wave-then-group order."""


# ---------------------------------------------------------------------------
# Dormant writer — NO-OP by default (, SC-1)
# ---------------------------------------------------------------------------


def write_parallelism_report(
    report: ParallelismReport,
    out_path: Path,
    *,
    enabled: bool = False,
) -> bool:
    """Write ``report`` as JSON to ``out_path``.

    DORMANT by default (``enabled=False``): returns ``False`` without creating
    or touching the file.  Slice 5 activates this by passing ``enabled=True``
    (driven by the ST-003 ``observability.parallelism`` toggle).

    Clock-free: caller supplies ``out_path`` and ``report['generated_at']``.
    Does NOT call ``datetime.now()`` internally.

    Args:
        report: A ``ParallelismReport`` dict to serialize.
        out_path: Destination path for ``parallelism.json``.
        enabled: Gate flag.  Default ``False`` keeps the writer dormant.

    Returns:
        ``True`` if the file was written, ``False`` if dormant/disabled.
    """
    if not enabled:
        return False

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return True
