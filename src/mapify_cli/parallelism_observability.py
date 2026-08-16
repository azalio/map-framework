"""Dormant observability scaffolding for parallel-wave execution.

This module defines:
  - The canonical, stable reason-code constants for worktree fallback and
    parallel-dispatch decisions (consumed by the runner in ST-009 and Slice 5).
  - The ``ParallelismReport`` TypedDict schema for
    ``.map/runs/<run_id>/parallelism.json``.
  - A ``write_parallelism_report`` writer that is NO-OP by default (gated on
    an explicit ``enabled=True`` argument or the ST-003 observability toggle).
  - Classification-outcome constants and ``classify_dispatch`` (5b.2) which
    maps typed evidence signals to a single outcome string.
  - ``record_dispatch_actual`` (5b.2) which persists exactly one report per
    wave on the concurrent path; is a no-op on the default/sequential path.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict

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
# Classification-outcome constants (5b.2 — ST-003)
# ---------------------------------------------------------------------------
# These are the classifier verdict strings returned by classify_dispatch().
# Style mirrors the worktree-fallback codes above (SC-1).

DISPATCH_OUTCOME_CONCURRENT_OBSERVED: str = "concurrent_observed"
"""Evidence confirms truly concurrent execution (same-turn count ≥2, max_in_flight ≥2)."""

DISPATCH_OUTCOME_SAME_TURN_BUT_HOST_SEQUENTIAL: str = "same_turn_but_host_sequential"
"""Tasks were dispatched same-turn but host ran them serially (max_in_flight ≤1)."""

DISPATCH_OUTCOME_PHANTOM_PARALLEL: str = "phantom_parallel"
"""Skill claimed concurrency but evidence shows at most one task (possible self-report error)."""

DISPATCH_OUTCOME_SEQUENTIAL_OBSERVED: str = "sequential_observed"
"""Normal sequential execution confirmed (same-turn count ≤1, max_in_flight ≤1)."""

DISPATCH_OUTCOME_ISOLATION_VIOLATION: str = "isolation_violation"
"""Multiple distinct base-SHAs detected across group worktrees — isolation breach."""

DISPATCH_OUTCOME_UNKNOWN: str = "unknown"
"""Evidence is insufficient or contradictory — cannot classify."""

# Validation set for all 6 classifier outcomes.
ALL_DISPATCH_OUTCOMES: frozenset[str] = frozenset(
    {
        DISPATCH_OUTCOME_CONCURRENT_OBSERVED,
        DISPATCH_OUTCOME_SAME_TURN_BUT_HOST_SEQUENTIAL,
        DISPATCH_OUTCOME_PHANTOM_PARALLEL,
        DISPATCH_OUTCOME_SEQUENTIAL_OBSERVED,
        DISPATCH_OUTCOME_ISOLATION_VIOLATION,
        DISPATCH_OUTCOME_UNKNOWN,
    }
)

# ---------------------------------------------------------------------------
# Schema: ParallelismReport
# ---------------------------------------------------------------------------
# Defined once here (TypedDict per the contract-first learned rule).
# Slice 5 imports this type to populate and write the report.

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

    reason_code: str | None
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
# Classifier (5b.2 — ST-003)
# ---------------------------------------------------------------------------


def classify_dispatch(
    same_turn_task_count: int,
    max_in_flight: int,
    base_shas: list[str],
    skill_reported_concurrent: bool,
) -> str:
    """Return a classification-outcome string for a dispatched wave.

    Evidence hierarchy (evaluated top-to-bottom; first match wins):
    1. ``len(set(base_shas)) > 1``  →  isolation_violation
       (different base SHAs across group worktrees: isolation breach)
    2. ``same_turn_task_count >= 2 and max_in_flight >= 2``  →  concurrent_observed
       (both transcript count AND in-flight overlap confirm concurrency)
    3. ``same_turn_task_count >= 2 and max_in_flight <= 1``  →  same_turn_but_host_sequential
       (tasks queued same-turn but host ran them serially)
    4. ``skill_reported_concurrent and same_turn_task_count <= 1 and max_in_flight <= 1``
       →  phantom_parallel (skill self-reported concurrency but ALL objective evidence
       shows ≤1 task; contradictory evidence same_turn<=1 BUT max_in_flight>=2 → unknown)
    5. ``same_turn_task_count <= 1 and max_in_flight <= 1``  →  sequential_observed
       (normal sequential execution)
    6. else  →  unknown

    Contract (HC-5): NO wall-clock timing. Inputs are pre-computed typed ints
    supplied by the runner (producer-owns-parse). Skill self-report is consulted
    ONLY in rule 4 and is NEVER authoritative for a positive concurrency claim.

    Args:
        same_turn_task_count: Number of Task tool calls dispatched in the same
            turn (parsed from the coordinator transcript by the runner).
        max_in_flight: Maximum simultaneously-running tasks derived from
            replayed sorted lifecycle events (runner computes via sweep).
        base_shas: Base-SHA recorded for each group worktree. A healthy group
            has all identical SHAs; >1 distinct SHA indicates isolation drift.
        skill_reported_concurrent: Whether the skill or Actor self-reported
            that concurrent dispatch was used.

    Returns:
        One of the ``DISPATCH_OUTCOME_*`` constants.
    """
    # Rule 1: isolation violation supersedes everything else.
    if len(set(base_shas)) > 1:
        return DISPATCH_OUTCOME_ISOLATION_VIOLATION

    # Rule 2: strongest positive-concurrency evidence (both signals agree).
    if same_turn_task_count >= 2 and max_in_flight >= 2:
        return DISPATCH_OUTCOME_CONCURRENT_OBSERVED

    # Rule 3: same-turn dispatch but host ran them serially.
    if same_turn_task_count >= 2 and max_in_flight <= 1:
        return DISPATCH_OUTCOME_SAME_TURN_BUT_HOST_SEQUENTIAL

    # Rule 4: skill self-report present but ALL objective evidence says ≤1 task.
    # Both same_turn_task_count AND max_in_flight must confirm ≤1; if max_in_flight>=2
    # the evidence is contradictory (skill_reported says concurrent but same-turn says
    # ≤1 while in-flight says ≥2) → fall through to unknown (rule 6).
    # Self-report is consulted ONLY here; never treated as authoritative.
    if skill_reported_concurrent and same_turn_task_count <= 1 and max_in_flight <= 1:
        return DISPATCH_OUTCOME_PHANTOM_PARALLEL

    # Rule 5: normal sequential execution confirmed.
    if same_turn_task_count <= 1 and max_in_flight <= 1:
        return DISPATCH_OUTCOME_SEQUENTIAL_OBSERVED

    # Rule 6: evidence is contradictory or incomplete.
    return DISPATCH_OUTCOME_UNKNOWN


# ---------------------------------------------------------------------------
# Coordinator writer (5b.2 — ST-003)
# ---------------------------------------------------------------------------


def record_dispatch_actual(
    report: ParallelismReport,
    out_path: Path,
    outcome: str,
) -> bool:
    """Persist exactly ONE ParallelismReport per wave — ONLY on the concurrent path.

    Decision rule:
    - ``outcome == DISPATCH_OUTCOME_CONCURRENT_OBSERVED``  →  write (enabled=True)
    - any other outcome  →  no-op (returns False, no file created/touched)

    This is the *only* activation site for ``write_parallelism_report(enabled=True)``
    in 5b.2.  All other callers must keep ``enabled=False`` (the dormant default).

    Args:
        report: Fully-populated ParallelismReport dict (caller supplies run_id,
            generated_at, etc.; this function never calls datetime.now()).
        out_path: Destination path for ``parallelism.json``; parent dirs are
            created by the underlying writer.
        outcome: Result of ``classify_dispatch(...)``; determines whether the
            writer fires.

    Returns:
        ``True`` if the report was written; ``False`` on the no-op path.
    """
    if outcome != DISPATCH_OUTCOME_CONCURRENT_OBSERVED:
        return False
    return write_parallelism_report(report, out_path, enabled=True)


# ---------------------------------------------------------------------------
# Dormant writer — NO-OP by default (SC-1)
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
