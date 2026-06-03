"""skills_eval — skill trigger evaluation data contracts and dispatchers.

Exports the shared types used by every eval component (dispatcher, assertions,
runner, aggregator) and the concrete dispatcher implementations.
"""

from __future__ import annotations

from mapify_cli.skills_eval.dispatcher import (
    ClaudeSubprocessDispatcher,
    MockDispatcher,
    VariantDispatcher,
)
from mapify_cli.skills_eval.eval_schema import (
    DispatchResult,
    EvalResultRecord,
    EvalSetEntry,
    make_cell_id,
)

__all__ = [
    "ClaudeSubprocessDispatcher",
    "DispatchResult",
    "EvalResultRecord",
    "EvalSetEntry",
    "MockDispatcher",
    "VariantDispatcher",
    "make_cell_id",
]
