"""skills_eval — skill trigger evaluation data contracts and dispatchers.

Exports the shared types used by every eval component (dispatcher, assertions,
runner, aggregator) and the concrete dispatcher implementations.
"""

from __future__ import annotations

from mapify_cli.skills_eval.aggregator import (
    AggregateSummary,
    aggregate,
    bounded_run,
)
from mapify_cli.skills_eval.assertions import (
    AssertionResult,
    run_assertion,
    run_assertions,
)
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
from mapify_cli.skills_eval.runner import (
    default_run_path,
    evaluate_cell,
    latest_run_path,
    load_eval_set,
    run_eval,
)

__all__ = [
    "AggregateSummary",
    "AssertionResult",
    "ClaudeSubprocessDispatcher",
    "DispatchResult",
    "EvalResultRecord",
    "EvalSetEntry",
    "MockDispatcher",
    "VariantDispatcher",
    "aggregate",
    "bounded_run",
    "default_run_path",
    "evaluate_cell",
    "latest_run_path",
    "load_eval_set",
    "make_cell_id",
    "run_assertion",
    "run_assertions",
    "run_eval",
]
