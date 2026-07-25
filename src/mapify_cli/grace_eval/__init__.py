"""grace_eval — GRACE semantic code-contract anchor evaluation.

Exports the shared data contracts and sweep utilities.  This module is a
pure data + deterministic-logic layer for slice 1; no external model calls,
no I/O, no subprocess, no clock access (INV-2/INV-3).
"""

from __future__ import annotations

from mapify_cli.grace_eval.schema import (
    CODE_LOCAL_VARIANTS,
    NO_ANCHOR_VARIANTS,
    PROMPT_INJECTED_VARIANTS,
    VARIANT_NAMES,
    GraceFixture,
    GraceReport,
    SweepFinding,
    VariantAggregate,
    VariantRunRecord,
    aggregate_runs,
    make_run_id,
)
from mapify_cli.grace_eval.sweep import (
    sweep_source,
    sweep_variant_sources,
)

__all__ = [
    "CODE_LOCAL_VARIANTS",
    "NO_ANCHOR_VARIANTS",
    "PROMPT_INJECTED_VARIANTS",
    "VARIANT_NAMES",
    "GraceFixture",
    "GraceReport",
    "SweepFinding",
    "VariantAggregate",
    "VariantRunRecord",
    "aggregate_runs",
    "make_run_id",
    "sweep_source",
    "sweep_variant_sources",
]
