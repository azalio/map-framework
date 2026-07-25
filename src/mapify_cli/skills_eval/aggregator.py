"""Aggregation and bounded-concurrency runner for skills_eval.

Public API:
- ``AggregateSummary``  -- frozen dataclass summarising a completed eval run.
- ``aggregate(records)`` -- compute summary stats from a list of EvalResultRecord.
- ``bounded_run(...)``  -- parallel cell dispatch with serialised durable writes.

Design invariants respected:
- INV-3: no ``import anthropic``, no ANTHROPIC_API_KEY access.
- INV-5: ClaudeSubprocessDispatcher isolation is automatic (each dispatch creates
         its own mkdtemp cwd); no extra isolation code is needed here.
- VC1:   pass_rate = passed_cells / total_cells (0.0 when total==0, never divide-by-zero).
- VC2:   token mean/stddev use statistics.mean/stdev; n<2 → stddev 0.0; n==0 → None.
- VC3:   bounded_run serialises writes under a threading.Lock (no .jsonl corruption).
- VC4:   aggregate never raises on empty list or all-null token_usage records.
- SC-1:  max_concurrency controls ThreadPoolExecutor workers; default 1 (sequential).
"""

from __future__ import annotations

import concurrent.futures
import dataclasses
import logging
import statistics
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeAlias

from mapify_cli.skills_eval.dispatcher import VariantDispatcher
from mapify_cli.skills_eval.eval_schema import EvalResultRecord, EvalSetEntry
from mapify_cli.skills_eval.runner import (
    _append_record,
    _read_present_cell_ids,
    evaluate_cell,
    make_cell_id,
)

logger = logging.getLogger(__name__)

# Intent: fixed variant_id per D10 -- matches the constant in runner.py.
_VARIANT_ID: int = 1

# Re-export make_cell_id so callers who import from aggregator get it too.
__all__ = ["AggregateSummary", "aggregate", "bounded_run"]

# Intent: module-level TypeAlias so pyright can resolve it in function annotations.
_WorkItem: TypeAlias = tuple[int, int, EvalSetEntry]


# ---------------------------------------------------------------------------
# AggregateSummary
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AggregateSummary:
    """Aggregate statistics over a completed eval run.

    JSON-serialisable via ``to_dict()``.  All float fields that can be absent
    (token stats, duration when no records) are typed ``float | None``.

    Fields
    ------
    total_cells:
        Total number of ``EvalResultRecord`` objects in the input.
    passed_cells:
        Count of records whose ``assertions_failed`` list is EMPTY.
    pass_rate:
        ``passed_cells / total_cells``; 0.0 when ``total_cells == 0``.
    token_sample_size:
        Count of records where ``token_usage`` is not None.
    tokens_mean:
        Arithmetic mean of ``token_usage.total`` over the token sample.
        ``None`` when ``token_sample_size == 0``.
    tokens_stddev:
        Sample standard deviation of ``token_usage.total``; 0.0 when
        ``token_sample_size < 2``; ``None`` when ``token_sample_size == 0``.
    duration_mean:
        Arithmetic mean of ``record.duration_s`` over all records.
        ``None`` when ``total_cells == 0``.
    duration_stddev:
        Sample standard deviation of ``duration_s``; 0.0 when
        ``total_cells < 2``; ``None`` when ``total_cells == 0``.
    """

    total_cells: int
    passed_cells: int
    pass_rate: float
    token_sample_size: int
    tokens_mean: float | None
    tokens_stddev: float | None
    duration_mean: float | None
    duration_stddev: float | None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dict for this summary."""
        return dataclasses.asdict(self)


# ---------------------------------------------------------------------------
# _safe_stddev  (n<2 guard, shared by token and duration paths)
# ---------------------------------------------------------------------------


def _safe_stddev(xs: list[float]) -> float:
    """Return sample stdev of *xs*, guarding against n<2 with 0.0.

    ``statistics.stdev`` raises ``StatisticsError`` on n<2; we normalise that
    to 0.0 because a single-sample (or zero-sample) collection has no spread.
    The caller guarantees ``len(xs) >= 1`` (use 0.0 for empty at the call site).
    """
    if len(xs) < 2:
        return 0.0
    return statistics.stdev(xs)


# ---------------------------------------------------------------------------
# aggregate
# ---------------------------------------------------------------------------


def aggregate(records: list[EvalResultRecord]) -> AggregateSummary:
    """Compute aggregate statistics over *records*.

    Never raises, even for an empty list or all-null ``token_usage`` records.

    Parameters
    ----------
    records:
        List of ``EvalResultRecord`` objects from a completed (or partial) run.
        May be empty.

    Returns
    -------
    AggregateSummary
        Populated summary.  When ``records`` is empty:
        ``total_cells=0, passed_cells=0, pass_rate=0.0,
        token_sample_size=0, tokens_mean=None, tokens_stddev=None,
        duration_mean=None, duration_stddev=None``.
    """
    total_cells = len(records)

    # VC1: pass_rate --- cells with EMPTY assertions_failed are "passed".
    passed_cells = sum(1 for r in records if len(r.assertions_failed) == 0)
    # Intent: explicit zero-guard so we never divide by zero.
    pass_rate = passed_cells / total_cells if total_cells > 0 else 0.0

    # VC2/VC4: token stats --- only over records with non-null token_usage.
    token_totals: list[float] = [
        float(r.token_usage.total) for r in records if r.token_usage is not None
    ]
    token_sample_size = len(token_totals)
    if token_sample_size == 0:
        # VC4: all-null token_usage → both stats are None; pass_rate+duration still valid.
        tokens_mean: float | None = None
        tokens_stddev: float | None = None
    else:
        tokens_mean = statistics.mean(token_totals)
        tokens_stddev = _safe_stddev(token_totals)

    # Duration stats --- duration_s is always present on every record.
    if total_cells == 0:
        duration_mean: float | None = None
        duration_stddev: float | None = None
    else:
        durations: list[float] = [r.duration_s for r in records]
        duration_mean = statistics.mean(durations)
        duration_stddev = _safe_stddev(durations)

    return AggregateSummary(
        total_cells=total_cells,
        passed_cells=passed_cells,
        pass_rate=pass_rate,
        token_sample_size=token_sample_size,
        tokens_mean=tokens_mean,
        tokens_stddev=tokens_stddev,
        duration_mean=duration_mean,
        duration_stddev=duration_stddev,
    )


# ---------------------------------------------------------------------------
# bounded_run
# ---------------------------------------------------------------------------


def bounded_run(
    *,
    skill: str,
    entries: list[EvalSetEntry],
    dispatcher: VariantDispatcher,
    runs: int,
    out_path: Path,
    resume: bool = False,
    max_concurrency: int = 1,
) -> list[EvalResultRecord]:
    """Run the prompts x runs matrix with bounded parallel dispatch.

    Mirrors ``run_eval`` but executes cells in a ``ThreadPoolExecutor`` with up
    to *max_concurrency* worker threads.  All .jsonl writes are serialised under
    a ``threading.Lock`` so the output file is never corrupted (VC3).

    Parameters
    ----------
    skill:
        Skill name (used for logging).
    entries:
        Eval-set rows (``EvalSetEntry`` objects).
    dispatcher:
        Dispatcher instance.  Each ``evaluate_cell`` call invokes
        ``dispatcher.dispatch()``.  For ``ClaudeSubprocessDispatcher``, INV-5
        isolation is automatic — each dispatch creates its own ``mkdtemp`` cwd
        so concurrent dispatches never share working directories.
    runs:
        Number of runs per prompt.
    out_path:
        Absolute path to the ``.jsonl`` output file.
    resume:
        If True, skip cells already present in *out_path* (keyed on cell_id).
    max_concurrency:
        Maximum number of concurrent worker threads.  ``1`` (default) makes
        this effectively sequential while sharing the same code path as
        parallel execution.

    Returns
    -------
    list[EvalResultRecord]
        All records dispatched during THIS call (resumed/skipped cells excluded).
        Write order in the .jsonl may be nondeterministic at concurrency>1, but
        the SET of cell_ids is always complete and unique.
    """
    # Determine the complete set of cells to skip (resume mode).
    present_cell_ids: set[str] = set()
    if resume and out_path.exists():
        present_cell_ids = _read_present_cell_ids(out_path)
        logger.info(
            "bounded_run: resume mode -- %d cells already present in %s",
            len(present_cell_ids),
            out_path,
        )

    # Ensure output directory exists before any worker touches the file.
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Build the work list: (prompt_index, run_number, entry) for missing cells only.
    work_items: list[_WorkItem] = []
    for prompt_index, entry in enumerate(entries):
        for run_number in range(runs):
            cell_id = make_cell_id(prompt_index, _VARIANT_ID, run_number)
            if cell_id not in present_cell_ids:
                work_items.append((prompt_index, run_number, entry))
            else:
                logger.debug(
                    "bounded_run: skipping cell %s (already present in %s)",
                    cell_id,
                    out_path,
                )

    # Intent: serialised-write lock -- only one thread may append to the .jsonl
    # at a time, preventing interleaved/corrupted writes (VC3).
    write_lock = threading.Lock()
    collected: list[EvalResultRecord] = []

    def _dispatch_and_record(item: _WorkItem) -> EvalResultRecord:
        """Worker: evaluate one cell and serialise the write."""
        prompt_idx, run_num, cell_entry = item
        record = evaluate_cell(
            skill=skill,
            entry=cell_entry,
            prompt_index=prompt_idx,
            run_number=run_num,
            dispatcher=dispatcher,
        )
        with write_lock:
            # INV-4: durable per-cell append-and-flush, serialised.
            _append_record(out_path, record)
            collected.append(record)
        return record

    workers = max(1, max_concurrency)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(_dispatch_and_record, item) for item in work_items]
        # Intent: iterate futures as they complete; re-raise any unexpected exception
        # so the caller can detect programming errors (dispatcher must not raise, per
        # its contract, but the lock/append path theoretically could).
        for future in concurrent.futures.as_completed(futures):
            future.result()  # propagates any unexpected exception

    logger.info(
        "bounded_run: finished skill=%s entries=%d runs=%d cells_written=%d out=%s",
        skill,
        len(entries),
        runs,
        len(collected),
        out_path,
    )

    return collected
