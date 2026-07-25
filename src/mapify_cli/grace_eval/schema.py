"""Data contracts for the GRACE semantic code-contract anchor eval.

Pure data layer — no I/O, no dispatch, no subprocess, no clock/random.
Producers and consumers both import from here (contract-first pattern).

GRACE variants (from the upstream experiment notes in issue #339):
  - baseline : no semantic anchors beyond normal code/docs
  - inline   : code-local contracts near relevant implementation points
  - lex      : inline contracts enriched with domain terms / bug symptoms
  - min      : trap-only anchors around non-obvious or bug-prone paths
  - inj      : top contracts injected into prompt, not placed near code
  - lie      : controlled stale/false-anchor variant for sweep/audit tests
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

_SCHEMA_VERSION = "1.0"
_SENTINEL: object = object()

# Canonical variant names in canonical order.
VARIANT_NAMES: tuple[str, ...] = (
    "baseline",
    "inline",
    "lex",
    "min",
    "inj",
    "lie",
)

# Anchor-placement strategies (split used in side-by-side reporting).
CODE_LOCAL_VARIANTS: frozenset[str] = frozenset({"inline", "lex", "min", "lie"})
PROMPT_INJECTED_VARIANTS: frozenset[str] = frozenset({"inj"})
NO_ANCHOR_VARIANTS: frozenset[str] = frozenset({"baseline"})


# ---------------------------------------------------------------------------
# GraceFixture  — defines one bug-fix task
# ---------------------------------------------------------------------------


@dataclass
class GraceFixture:
    """Description of one bug-fix eval task.

    Loaded from ``<fixture-id>/fixture.json``; the variant subdirectories
    (``variants/<name>/``) supply the annotated source files for code-local
    variants, and ``variants/inj/prompt_fragment.txt`` supplies the contract
    text for the ``inj`` variant.

    ``expected_changed_files`` is a list of repo-relative glob patterns that
    the agent is expected to modify when the fix is complete.  Used by the
    (future) deterministic scope gate — not validated in slice 1.
    """

    fixture_id: str
    title: str
    description: str
    bug_summary: str
    expected_changed_files: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.fixture_id, str) or not self.fixture_id:
            raise ValueError("GraceFixture.fixture_id must be a non-empty str")
        if not isinstance(self.title, str) or not self.title:
            raise ValueError("GraceFixture.title must be a non-empty str")
        if not isinstance(self.description, str):
            raise ValueError("GraceFixture.description must be str")
        if not isinstance(self.bug_summary, str):
            raise ValueError("GraceFixture.bug_summary must be str")
        if not isinstance(self.expected_changed_files, list):
            raise ValueError("GraceFixture.expected_changed_files must be a list")
        if not isinstance(self.tags, list):
            raise ValueError("GraceFixture.tags must be a list")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "fixture_id": self.fixture_id,
            "title": self.title,
            "description": self.description,
            "bug_summary": self.bug_summary,
            "expected_changed_files": list(self.expected_changed_files),
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> GraceFixture:
        return cls(
            fixture_id=str(d["fixture_id"]),
            title=str(d["title"]),
            description=str(d.get("description", "")),
            bug_summary=str(d.get("bug_summary", "")),
            expected_changed_files=list(d.get("expected_changed_files", [])),
            tags=list(d.get("tags", [])),
        )


# ---------------------------------------------------------------------------
# VariantRunRecord  — one (fixture, variant, run) result row
# ---------------------------------------------------------------------------


@dataclass
class VariantRunRecord:
    """One completed GRACE run result.

    Append-only JSONL row keyed by ``run_id``.  In slice 1 this is populated
    by fixture-driven mock runners only; in later slices a real dispatcher
    fills ``total_tokens``, ``repeated_reads``, and ``retry_count`` from
    token_log.jsonl and ``step_state.json``.

    ``stale_detection`` is meaningful only for the ``lie`` variant: True when
    the sweep flagged a contradicted or stale contract in the variant source.
    """

    run_id: str
    fixture_id: str
    variant: str
    success: bool
    retry_count: int = 0
    total_tokens: int = 0
    output_tokens: int = 0
    repeated_reads: int = 0
    stale_detection: bool = False
    error: str | None = None

    def __post_init__(self) -> None:
        if self.variant not in VARIANT_NAMES:
            raise ValueError(
                f"VariantRunRecord.variant must be one of {VARIANT_NAMES}, "
                f"got {self.variant!r}"
            )
        if not isinstance(self.run_id, str) or not self.run_id:
            raise ValueError("VariantRunRecord.run_id must be a non-empty str")
        if not isinstance(self.fixture_id, str) or not self.fixture_id:
            raise ValueError("VariantRunRecord.fixture_id must be a non-empty str")
        if not isinstance(self.retry_count, int) or self.retry_count < 0:
            raise ValueError("VariantRunRecord.retry_count must be a non-negative int")
        if not isinstance(self.total_tokens, int) or self.total_tokens < 0:
            raise ValueError("VariantRunRecord.total_tokens must be a non-negative int")

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "fixture_id": self.fixture_id,
            "variant": self.variant,
            "success": bool(self.success),
            "retry_count": self.retry_count,
            "total_tokens": self.total_tokens,
            "output_tokens": self.output_tokens,
            "repeated_reads": self.repeated_reads,
            "stale_detection": bool(self.stale_detection),
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> VariantRunRecord:
        raw_err = d.get("error", _SENTINEL)
        error: str | None = None if (raw_err is _SENTINEL or raw_err is None) else str(raw_err)
        return cls(
            run_id=str(d["run_id"]),
            fixture_id=str(d["fixture_id"]),
            variant=str(d["variant"]),
            success=bool(d["success"]),
            retry_count=int(d.get("retry_count", 0)),
            total_tokens=int(d.get("total_tokens", 0)),
            output_tokens=int(d.get("output_tokens", 0)),
            repeated_reads=int(d.get("repeated_reads", 0)),
            stale_detection=bool(d.get("stale_detection", False)),
            error=error,
        )


# ---------------------------------------------------------------------------
# VariantAggregate  — rolled-up stats across N runs for one variant
# ---------------------------------------------------------------------------


@dataclass
class VariantAggregate:
    """Aggregated statistics for one variant across all runs.

    ``vs_baseline`` is ``None`` for the baseline variant itself (no self-diff).
    ``trajectory_delta_note`` classifies the token-trajectory change relative
    to baseline: ``improvement``, ``regression``, ``tie``, or ``no_baseline``.
    """

    variant: str
    n: int
    success_rate: float
    mean_retries: float
    mean_total_tokens: float
    mean_repeated_reads: float
    stale_detections: int
    vs_baseline_correctness_delta: float | None = None
    vs_baseline_tokens_delta: float | None = None
    trajectory_delta_note: str = "no_baseline"

    def __post_init__(self) -> None:
        if self.variant not in VARIANT_NAMES:
            raise ValueError(
                f"VariantAggregate.variant must be one of {VARIANT_NAMES}, "
                f"got {self.variant!r}"
            )
        valid_notes = {"improvement", "regression", "tie", "no_baseline"}
        if self.trajectory_delta_note not in valid_notes:
            raise ValueError(
                f"VariantAggregate.trajectory_delta_note must be one of {valid_notes}, "
                f"got {self.trajectory_delta_note!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "variant": self.variant,
            "n": self.n,
            "success_rate": round(self.success_rate, 4),
            "mean_retries": round(self.mean_retries, 4),
            "mean_total_tokens": round(self.mean_total_tokens, 2),
            "mean_repeated_reads": round(self.mean_repeated_reads, 4),
            "stale_detections": self.stale_detections,
            "vs_baseline_correctness_delta": (
                round(self.vs_baseline_correctness_delta, 4)
                if self.vs_baseline_correctness_delta is not None
                else None
            ),
            "vs_baseline_tokens_delta": (
                round(self.vs_baseline_tokens_delta, 2)
                if self.vs_baseline_tokens_delta is not None
                else None
            ),
            "trajectory_delta_note": self.trajectory_delta_note,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> VariantAggregate:
        raw_cd = d.get("vs_baseline_correctness_delta", _SENTINEL)
        cd: float | None = None if (raw_cd is _SENTINEL or raw_cd is None) else float(raw_cd)
        raw_td = d.get("vs_baseline_tokens_delta", _SENTINEL)
        td: float | None = None if (raw_td is _SENTINEL or raw_td is None) else float(raw_td)
        return cls(
            variant=str(d["variant"]),
            n=int(d["n"]),
            success_rate=float(d["success_rate"]),
            mean_retries=float(d["mean_retries"]),
            mean_total_tokens=float(d["mean_total_tokens"]),
            mean_repeated_reads=float(d["mean_repeated_reads"]),
            stale_detections=int(d.get("stale_detections", 0)),
            vs_baseline_correctness_delta=cd,
            vs_baseline_tokens_delta=td,
            trajectory_delta_note=str(d.get("trajectory_delta_note", "no_baseline")),
        )


# ---------------------------------------------------------------------------
# SweepFinding  — stale/contradictory contract detected by the sweep
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SweepFinding:
    """One stale or contradictory contract detected by the sweep checker.

    ``severity``: ``warning`` (mild drift) or ``critical`` (outright contradiction).
    ``location``: file path + line range, e.g. ``"src/utils.py:L42-45"``.
    ``detail``: human-readable description of the conflict.
    ``variant``: which variant source the finding was detected in.
    """

    severity: str
    location: str
    detail: str
    variant: str

    def __post_init__(self) -> None:
        if self.severity not in ("warning", "critical"):
            raise ValueError(
                f"SweepFinding.severity must be warning|critical, got {self.severity!r}"
            )
        if self.variant not in VARIANT_NAMES:
            raise ValueError(
                f"SweepFinding.variant must be one of {VARIANT_NAMES}, "
                f"got {self.variant!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "location": self.location,
            "detail": self.detail,
            "variant": self.variant,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SweepFinding:
        return cls(
            severity=str(d["severity"]),
            location=str(d["location"]),
            detail=str(d["detail"]),
            variant=str(d["variant"]),
        )


# ---------------------------------------------------------------------------
# GraceReport  — root report object
# ---------------------------------------------------------------------------


@dataclass
class GraceReport:
    """Root GRACE eval report object.

    Written to ``.map/grace-eval/<fixture-id>/report.json`` after an eval run.
    ``aggregates`` is keyed by variant name in VARIANT_NAMES order.
    ``sweep_findings`` lists stale/contradictory contract detections (empty when
    the sweep finds no issues).
    ``generated_at`` is an ISO-8601 timestamp supplied by the CLI boundary
    (not by this module — INV-2: no clock access in the data layer).
    """

    fixture_id: str
    generated_at: str
    aggregates: list[VariantAggregate]
    sweep_findings: list[SweepFinding] = field(default_factory=list)
    schema_version: str = _SCHEMA_VERSION
    notes: str = ""

    def aggregate_for(self, variant: str) -> VariantAggregate | None:
        for agg in self.aggregates:
            if agg.variant == variant:
                return agg
        return None

    @property
    def n_stale_detections(self) -> int:
        return sum(agg.stale_detections for agg in self.aggregates)

    @property
    def n_sweep_findings(self) -> int:
        return len(self.sweep_findings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "fixture_id": self.fixture_id,
            "generated_at": self.generated_at,
            "aggregates": [a.to_dict() for a in self.aggregates],
            "sweep_findings": [f.to_dict() for f in self.sweep_findings],
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> GraceReport:
        return cls(
            schema_version=str(d.get("schema_version", _SCHEMA_VERSION)),
            fixture_id=str(d["fixture_id"]),
            generated_at=str(d["generated_at"]),
            aggregates=[VariantAggregate.from_dict(a) for a in d.get("aggregates", [])],
            sweep_findings=[SweepFinding.from_dict(f) for f in d.get("sweep_findings", [])],
            notes=str(d.get("notes", "")),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_run_id(fixture_id: str, variant: str, run: int) -> str:
    """Deterministic, human-readable run identifier.

    Example: ``make_run_id("off-by-one", "lex", 2)`` → ``"off-by-one-lex-r2"``
    """
    slug = "".join(ch if ch.isalnum() or ch == "-" else "-" for ch in fixture_id)
    return f"{slug}-{variant}-r{run}"


def aggregate_runs(
    records: list[VariantRunRecord],
    baseline_agg: VariantAggregate | None = None,
) -> VariantAggregate:
    """Aggregate a list of same-fixture, same-variant run records.

    All records must share the same ``variant`` and ``fixture_id``.
    Raises ``ValueError`` on empty list or mixed variants.
    ``baseline_agg`` supplies the baseline aggregate used for delta fields; pass
    ``None`` when aggregating the baseline variant itself.
    """
    if not records:
        raise ValueError("aggregate_runs requires at least one record")
    variants = {r.variant for r in records}
    if len(variants) > 1:
        raise ValueError(f"aggregate_runs: mixed variants {variants!r}")
    variant = records[0].variant

    n = len(records)
    success_rate = sum(1 for r in records if r.success) / n
    mean_retries = sum(r.retry_count for r in records) / n
    mean_total_tokens = sum(r.total_tokens for r in records) / n
    mean_repeated_reads = sum(r.repeated_reads for r in records) / n
    stale_detections = sum(1 for r in records if r.stale_detection)

    vs_cd: float | None = None
    vs_td: float | None = None
    note = "no_baseline"

    if baseline_agg is not None and variant != "baseline":
        vs_cd = round(success_rate - baseline_agg.success_rate, 4)
        vs_td = round(mean_total_tokens - baseline_agg.mean_total_tokens, 2)
        _TOKEN_TIE_EPSILON = 500.0
        _TOKEN_REGRESSION_DELTA = 2000.0
        if abs(vs_td) < _TOKEN_TIE_EPSILON:
            note = "tie"
        elif vs_td <= -_TOKEN_REGRESSION_DELTA:
            note = "improvement"
        elif vs_td >= _TOKEN_REGRESSION_DELTA:
            note = "regression"
        else:
            note = "tie"
    elif variant == "baseline":
        note = "no_baseline"

    return VariantAggregate(
        variant=variant,
        n=n,
        success_rate=success_rate,
        mean_retries=mean_retries,
        mean_total_tokens=mean_total_tokens,
        mean_repeated_reads=mean_repeated_reads,
        stale_detections=stale_detections,
        vs_baseline_correctness_delta=vs_cd,
        vs_baseline_tokens_delta=vs_td,
        trajectory_delta_note=note,
    )
