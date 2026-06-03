"""Matrix runner for skill eval: prompts x runs -> durable resumable .jsonl.

Public API (plain functions; no Typer -- CLI wiring is ST-007):
- ``load_eval_set(path)``                      -- parse a JSON eval-set file.
- ``run_eval(...)``                             -- execute the p x r matrix, append results.
- ``default_run_path(root, skill, timestamp)`` -- canonical .jsonl path helper.
- ``latest_run_path(root, skill)``              -- find most-recent .jsonl for --resume.

Design invariants respected:
- INV-3: no ``import anthropic``, no ANTHROPIC_API_KEY access.
- INV-7: ``triggered_skill`` is consumed from ``DispatchResult.triggered_skill``
         (the dispatcher is the SINGLE source of trigger detection).  The runner
         does NOT parse transcripts.
- D10:   variant_id is always 1 (no variants loop).
- INV-4: each cell is flushed to disk immediately (durable per-cell append).
- VC3:   resume reads existing cell_ids, skips already-written cells, appends only
         missing ones to the SAME file.
- VC4:   a per-cell dispatch error is recorded (not raised); matrix continues.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from mapify_cli.skills_eval.assertions import run_assertions
from mapify_cli.skills_eval.dispatcher import VariantDispatcher
from mapify_cli.skills_eval.eval_schema import (
    DispatchResult,
    EvalResultRecord,
    EvalSetEntry,
    make_cell_id,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Intent: fixed variant_id per D10 -- never enter a variants loop.
_VARIANT_ID: int = 1


# ---------------------------------------------------------------------------
# load_eval_set
# ---------------------------------------------------------------------------


def load_eval_set(path: Path) -> list[EvalSetEntry]:
    """Parse a JSON eval-set file and return a list of ``EvalSetEntry`` rows.

    Expected JSON shape::

        {
            "entries": [
                {
                    "prompt": "<str>",
                    "should_trigger": "<str or null>",
                    "should_not_trigger": "<str or null>",
                    "assertions": [ {"type": "...", ...}, ... ]
                },
                ...
            ]
        }

    Parameters
    ----------
    path:
        Filesystem path to the ``.json`` eval-set file.

    Returns
    -------
    list[EvalSetEntry]
        Non-empty list of parsed rows.

    Raises
    ------
    ValueError
        On: missing file, file not valid JSON, missing or empty "entries" key,
        or any row that fails ``EvalSetEntry.__post_init__`` validation.
    """
    if not path.exists():
        raise ValueError(f"eval-set file not found: {path}")

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"could not read eval-set file {path}: {exc}") from exc

    try:
        data: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"eval-set file is not valid JSON ({path}): {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(
            f"eval-set file must be a JSON object (got {type(data).__name__!r}): {path}"
        )

    raw_entries: Any = data.get("entries")
    if raw_entries is None:
        raise ValueError(f'eval-set file missing required "entries" key: {path}')
    if not isinstance(raw_entries, list):
        raise ValueError(
            f'"entries" must be a JSON array (got {type(raw_entries).__name__!r}): {path}'
        )
    if len(raw_entries) == 0:
        raise ValueError(f'"entries" list must not be empty: {path}')

    entries: list[EvalSetEntry] = []
    for row_index, raw_row in enumerate(raw_entries):
        if not isinstance(raw_row, dict):
            raise ValueError(
                f"entries[{row_index}] must be a JSON object "
                f"(got {type(raw_row).__name__!r}): {path}"
            )
        prompt: Any = raw_row.get("prompt")
        if prompt is None:
            raise ValueError(
                f'entries[{row_index}] missing required "prompt" key: {path}'
            )
        should_trigger: str | None = raw_row.get("should_trigger", None)
        should_not_trigger: str | None = raw_row.get("should_not_trigger", None)
        raw_assertions: Any = raw_row.get("assertions", [])
        if not isinstance(raw_assertions, list):
            raise ValueError(
                f"entries[{row_index}].assertions must be a JSON array "
                f"(got {type(raw_assertions).__name__!r}): {path}"
            )
        try:
            entry = EvalSetEntry(
                prompt=prompt,
                should_trigger=should_trigger,
                should_not_trigger=should_not_trigger,
                assertions=raw_assertions,
            )
        except ValueError as exc:
            raise ValueError(
                f"entries[{row_index}] failed validation: {exc}"
            ) from exc
        entries.append(entry)

    return entries


# ---------------------------------------------------------------------------
# _read_present_cell_ids  (resume helper)
# ---------------------------------------------------------------------------


def _read_present_cell_ids(out_path: Path) -> set[str]:
    """Return the set of ``cell_id`` values already in *out_path*.

    Skips blank lines and JSON-malformed lines defensively so a partial last
    line (write interrupted mid-flush) does not crash resume.
    """
    present: set[str] = set()
    try:
        with open(out_path, encoding="utf-8") as fh:
            for raw_line in fh:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    row: Any = json.loads(raw_line)
                except json.JSONDecodeError:
                    logger.debug(
                        "_read_present_cell_ids: skipping malformed line in %s", out_path
                    )
                    continue
                if not isinstance(row, dict):
                    continue
                cell_id_val = row.get("cell_id")
                if isinstance(cell_id_val, str) and cell_id_val:
                    present.add(cell_id_val)
    except OSError as exc:
        logger.warning(
            "_read_present_cell_ids: could not read %s: %s -- treating as empty",
            out_path,
            exc,
        )
    return present


# ---------------------------------------------------------------------------
# _build_assertion_specs  (per-cell helper)
# ---------------------------------------------------------------------------


def _build_assertion_specs(entry: EvalSetEntry) -> list[dict[str, object]]:
    """Combine explicit assertions with trigger/not_trigger expectations.

    The result is the complete spec list passed to ``run_assertions``.
    """
    specs: list[dict[str, object]] = list(entry.assertions)
    if entry.should_trigger is not None:
        specs.append({"type": "trigger", "skill": entry.should_trigger})
    if entry.should_not_trigger is not None:
        specs.append({"type": "not_trigger", "skill": entry.should_not_trigger})
    return specs


# ---------------------------------------------------------------------------
# run_eval
# ---------------------------------------------------------------------------


def evaluate_cell(
    *,
    skill: str,
    entry: EvalSetEntry,
    prompt_index: int,
    run_number: int,
    dispatcher: VariantDispatcher,
) -> EvalResultRecord:
    """Dispatch one (entry, prompt_index, run_number) cell and return the record.

    Does NOT write to disk — the caller is responsible for durable persistence
    (INV-4).  Shared by ``run_eval`` (sequential) and ``bounded_run``
    (concurrent) so dispatch+assertion logic is defined exactly once (DRY).

    Design invariants
    -----------------
    - D10: variant_id is always ``_VARIANT_ID`` (1).
    - INV-7: ``triggered_skill`` is read from ``DispatchResult.triggered_skill``
             only -- the runner never parses transcripts.
    - VC4: per-cell ``DispatchResult.error`` is recorded (not raised); callers
           decide whether to abort or continue.
    """
    cell_id = make_cell_id(prompt_index, _VARIANT_ID, run_number)

    # Dispatch -- must not raise (VariantDispatcher contract).
    dispatch_result: DispatchResult = dispatcher.dispatch(entry.prompt)

    # Build assertion specs: explicit assertions + trigger expectations.
    assertion_specs = _build_assertion_specs(entry)

    if dispatch_result.error is not None:
        # VC4: record the error as a synthetic failed assertion; do not abort.
        passed_list: list[str] = []
        failed_list: list[str] = [f"dispatch_error: {dispatch_result.error}"]
        logger.warning(
            "evaluate_cell: cell %s dispatch error (skill=%s run=%d): %s",
            cell_id,
            skill,
            run_number,
            dispatch_result.error,
        )
    else:
        passed_list, failed_list = run_assertions(assertion_specs, dispatch_result)

    return EvalResultRecord(
        cell_id=cell_id,
        prompt=entry.prompt,
        triggered_skill=dispatch_result.triggered_skill,
        token_usage=dispatch_result.token_usage,
        duration_s=dispatch_result.duration_s,
        assertions_passed=passed_list,
        assertions_failed=failed_list,
        raw_output=dispatch_result.raw_output,
    )


def run_eval(
    *,
    skill: str,
    entries: list[EvalSetEntry],
    dispatcher: VariantDispatcher,
    runs: int,
    out_path: Path,
    resume: bool = False,
) -> list[EvalResultRecord]:
    """Execute the prompts x runs evaluation matrix and write results to *out_path*.

    Parameters
    ----------
    skill:
        Name of the skill under evaluation (used for logging only).
    entries:
        Eval-set rows from ``load_eval_set``.
    dispatcher:
        ``VariantDispatcher`` instance (``MockDispatcher`` in tests,
        ``ClaudeSubprocessDispatcher`` in production).
    runs:
        Number of runs per prompt (``range(runs)``).
    out_path:
        Absolute path to the ``.jsonl`` output file.  Created (with parent
        dirs) if absent; APPENDED to if *resume* is True.
    resume:
        If True, read already-present ``cell_id`` values from *out_path* and
        skip those cells.  Missing cells are appended to the SAME file.
        If False (default), *out_path* is a fresh file (caller's responsibility
        to pass a new path -- the function does not truncate an existing file).

    Returns
    -------
    list[EvalResultRecord]
        Records written *during this call* (skipped/resumed cells are not
        included -- callers that need the full result set should read out_path).

    Design invariants
    -----------------
    - D10: variant_id is always ``_VARIANT_ID`` (1) -- NO variants loop.
    - INV-7: ``triggered_skill`` is read from ``DispatchResult.triggered_skill``
             only -- the runner never parses transcripts.
    - INV-4: each record is flushed to *out_path* immediately after building.
    - VC4: per-cell ``DispatchResult.error`` is recorded; matrix is never aborted.
    """
    # Resolve set of already-written cells for resume mode.
    present_cell_ids: set[str] = set()
    if resume and out_path.exists():
        present_cell_ids = _read_present_cell_ids(out_path)
        logger.info(
            "run_eval: resume mode -- %d cells already present in %s",
            len(present_cell_ids),
            out_path,
        )

    # Ensure output directory exists before first write.
    out_path.parent.mkdir(parents=True, exist_ok=True)

    written_records: list[EvalResultRecord] = []

    # Intent: outer loop is prompts, inner loop is runs -- matrix p x r with D10 variant=1.
    for prompt_index, entry in enumerate(entries):
        for run_number in range(runs):
            cell_id = make_cell_id(prompt_index, _VARIANT_ID, run_number)

            if cell_id in present_cell_ids:
                logger.debug(
                    "run_eval: skipping cell %s (already present in %s)",
                    cell_id,
                    out_path,
                )
                continue

            record = evaluate_cell(
                skill=skill,
                entry=entry,
                prompt_index=prompt_index,
                run_number=run_number,
                dispatcher=dispatcher,
            )

            # INV-4: durable per-cell append-and-flush before advancing.
            _append_record(out_path, record)

            written_records.append(record)

    logger.info(
        "run_eval: finished skill=%s entries=%d runs=%d cells_written=%d out=%s",
        skill,
        len(entries),
        runs,
        len(written_records),
        out_path,
    )

    return written_records


# ---------------------------------------------------------------------------
# _append_record  (durable per-cell write)
# ---------------------------------------------------------------------------


def _append_record(out_path: Path, record: EvalResultRecord) -> None:
    """Append *record* as a single JSON line to *out_path* and flush.

    Uses the ``open(path, "a", ...)`` append precedent from
    ``memory/capture.py:446``.  Calls ``flush()`` after write to ensure the OS
    buffer is flushed; ``os.fsync`` is intentionally omitted to avoid blocking
    the matrix on every cell -- the OS buffer flush is sufficient for the
    sequential use-case.
    """
    line = json.dumps(record.to_dict()) + "\n"
    with open(out_path, "a", encoding="utf-8") as fh:
        fh.write(line)
        fh.flush()


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def default_run_path(root: Path, skill: str, timestamp: str) -> Path:
    """Return the canonical .jsonl path for a new eval run.

    Parameters
    ----------
    root:
        Project root (the directory that contains ``.map/``).
    skill:
        Skill name (used as a subdirectory component).
    timestamp:
        Caller-supplied timestamp string, e.g.
        ``datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")``.
        Kept in the runner to make ``run_eval`` clock-free (testable).

    Returns
    -------
    Path
        ``<root>/.map/eval-runs/<skill>/<timestamp>.jsonl``
    """
    return root / ".map" / "eval-runs" / skill / f"{timestamp}.jsonl"


def latest_run_path(root: Path, skill: str) -> Path | None:
    """Return the most-recent ``.jsonl`` path for *skill*, or ``None``.

    Scans ``<root>/.map/eval-runs/<skill>/`` for ``*.jsonl`` files and returns
    the lexicographically last one (ISO-timestamp filenames sort correctly).
    Returns ``None`` if the directory does not exist or is empty.
    """
    run_dir = root / ".map" / "eval-runs" / skill
    if not run_dir.is_dir():
        return None
    candidates = sorted(run_dir.glob("*.jsonl"))
    if not candidates:
        return None
    return candidates[-1]
