"""Repeated-run aggregation for trajectory outcome eval.

Anchored on AgentLens: a single run is noisy, so the evaluation unit for a
fixture is the DISTRIBUTION of composites across repeated runs.  This module
reduces a list of ``TrajectoryEvalRecord`` (grouped by fixture) into medians,
variance, hard-pass counts, and an explicit flaky-scenario flag.

Pure stats — no I/O, no clock/random (INV-2).  Never raises: a fixture with a
single run yields stddev 0.0 and a ``single_run`` note rather than an error.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

from mapify_cli.skills_eval.trajectory.eval_schema import (
    COMPONENT_NAMES,
    FLAKY_STDDEV_THRESHOLD,
    TrajectoryEvalRecord,
)


def _safe_stddev(values: list[float]) -> float:
    """Population stddev; 0.0 for fewer than 2 samples."""
    if len(values) < 2:
        return 0.0
    return statistics.pstdev(values)


@dataclass
class FixtureAggregate:
    """Per-fixture rollup across repeated runs."""

    fixture: str
    n: int
    composite_median: float
    composite_mean: float
    composite_stddev: float
    hard_pass_count: int
    hard_pass_rate: float
    component_medians: dict[str, float] = field(default_factory=dict)
    flaky: bool = False
    flaky_reasons: list[str] = field(default_factory=list)
    run_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixture": self.fixture,
            "n": self.n,
            "composite_median": round(self.composite_median, 4),
            "composite_mean": round(self.composite_mean, 4),
            "composite_stddev": round(self.composite_stddev, 4),
            "hard_pass_count": self.hard_pass_count,
            "hard_pass_rate": round(self.hard_pass_rate, 4),
            "component_medians": {k: round(v, 4) for k, v in self.component_medians.items()},
            "flaky": self.flaky,
            "flaky_reasons": list(self.flaky_reasons),
            "run_ids": list(self.run_ids),
        }


@dataclass
class RunAggregate:
    """All-fixture rollup."""

    fixtures: list[FixtureAggregate] = field(default_factory=list)
    total_runs: int = 0
    overall_hard_pass_rate: float = 0.0
    n_flaky: int = 0

    def fixture(self, name: str) -> FixtureAggregate | None:
        for f in self.fixtures:
            if f.fixture == name:
                return f
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixtures": [f.to_dict() for f in self.fixtures],
            "total_runs": self.total_runs,
            "overall_hard_pass_rate": round(self.overall_hard_pass_rate, 4),
            "n_flaky": self.n_flaky,
        }


def _component_scores_by_name(
    records: list[TrajectoryEvalRecord],
) -> dict[str, list[float]]:
    """Collect per-component score lists across records (missing => absent)."""
    by_name: dict[str, list[float]] = {name: [] for name in COMPONENT_NAMES}
    for rec in records:
        present = {c.name: c.score for c in rec.components}
        for name in COMPONENT_NAMES:
            if name in present:
                by_name[name].append(float(present[name]))
    return by_name


def aggregate_fixture(records: list[TrajectoryEvalRecord]) -> FixtureAggregate:
    """Aggregate all records for ONE fixture into a ``FixtureAggregate``."""
    if not records:
        raise ValueError("aggregate_fixture: records must be non-empty")
    fixture_name = records[0].fixture
    composites = [float(r.composite) for r in records]
    hard_passes = [bool(r.hard_pass) for r in records]
    hard_pass_count = sum(1 for hp in hard_passes if hp)
    stddev = _safe_stddev(composites)

    reasons: list[str] = []
    if stddev > FLAKY_STDDEV_THRESHOLD:
        reasons.append(
            f"composite stddev {stddev:.3f} > {FLAKY_STDDEV_THRESHOLD}"
        )
    # Mix of hard_pass True/False across runs is itself a flakiness signal.
    if any(hard_passes) and not all(hard_passes):
        reasons.append(
            f"hard_pass inconsistent across runs ({hard_pass_count}/{len(hard_passes)})"
        )

    component_medians: dict[str, float] = {}
    for name, scores in _component_scores_by_name(records).items():
        if scores:
            component_medians[name] = statistics.median(scores)

    return FixtureAggregate(
        fixture=fixture_name,
        n=len(records),
        composite_median=statistics.median(composites),
        composite_mean=statistics.fmean(composites),
        composite_stddev=stddev,
        hard_pass_count=hard_pass_count,
        hard_pass_rate=hard_pass_count / len(records),
        component_medians=component_medians,
        flaky=bool(reasons),
        flaky_reasons=reasons,
        run_ids=[r.run_id for r in records],
    )


def aggregate_repeated(records: list[TrajectoryEvalRecord]) -> RunAggregate:
    """Group *records* by fixture and aggregate each group."""
    if not records:
        return RunAggregate()
    groups: dict[str, list[TrajectoryEvalRecord]] = {}
    order: list[str] = []
    for rec in records:
        if rec.fixture not in groups:
            groups[rec.fixture] = []
            order.append(rec.fixture)
        groups[rec.fixture].append(rec)

    fixture_aggs = [aggregate_fixture(groups[name]) for name in order]
    total = len(records)
    total_hp = sum(f.hard_pass_count for f in fixture_aggs)
    n_flaky = sum(1 for f in fixture_aggs if f.flaky)
    return RunAggregate(
        fixtures=fixture_aggs,
        total_runs=total,
        overall_hard_pass_rate=(total_hp / total) if total else 0.0,
        n_flaky=n_flaky,
    )
