"""skills_eval — skill trigger evaluation data contracts.

Exports the shared types used by every eval component (dispatcher, assertions,
runner, aggregator).  This package contains ONLY pure data structures; no
dispatch logic, transcript parsing, or assertion execution lives here.
"""

from __future__ import annotations

from mapify_cli.skills_eval.eval_schema import (
    DispatchResult,
    EvalResultRecord,
    EvalSetEntry,
    make_cell_id,
)

__all__ = [
    "DispatchResult",
    "EvalResultRecord",
    "EvalSetEntry",
    "make_cell_id",
]
