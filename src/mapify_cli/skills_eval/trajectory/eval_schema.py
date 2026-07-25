"""Data contracts for the trajectory outcome evaluator.

Pure data layer — no I/O, no dispatch, no subprocess, no clock/random
(INV-2).  Producers and consumers both import from here (INV-6).

The component model mirrors AgentLens (arXiv:2607.06624): the primary
evaluation unit is the full trajectory, scored across COMPONENT metrics
rather than a single opaque pass/fail.  Each component produces structured
evidence lines so a reviewer can jump from an aggregate score to the exact
trajectory evidence (issue #351).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Schema version — bump on incompatible record-shape changes.
# ---------------------------------------------------------------------------
_BUNDLE_SCHEMA_VERSION = "1.0"
_EVAL_SCHEMA_VERSION = "1.0"

# ---------------------------------------------------------------------------
# Constants shared by gates / runner / report.
# ---------------------------------------------------------------------------

#: The six component metrics, in canonical order.  Deterministic components
#: are scored from artifacts/gates; judge components from one batched
#: ``claude -p`` call.  Order is stable for reporting and side-by-side diff.
COMPONENT_NAMES: tuple[str, ...] = (
    "formal",
    "end_result",
    "tool_use",
    "instruction_compliance",
    "pitfalls",
    "reporting_trust",
)

DETERMINISTIC_COMPONENTS: tuple[str, ...] = ("formal", "end_result", "tool_use")
JUDGE_COMPONENTS: tuple[str, ...] = (
    "instruction_compliance",
    "pitfalls",
    "reporting_trust",
)

#: Composite >= this AND formal+end_result pass => hard_pass.
HARD_PASS_COMPOSITE_THRESHOLD = 0.8

#: Side-by-side |Δ composite| below this => "tie" (noise band).
TIE_EPSILON = 0.05

#: Side-by-side composite drop beyond this => "regression".
REGRESSION_DELTA = 0.10

#: Per-run stddev above this across repeated runs => flaky scenario.
FLAKY_STDDEV_THRESHOLD = 0.05

#: Workflow artifact side-files ignored by the source-change scope check
#: (mirrors spike_runner.ARTIFACT_GLOBS).
ARTIFACT_GLOBS: tuple[str, ...] = ("code-review-", "qa-", "pr-draft")

_SENTINEL: object = object()


# ---------------------------------------------------------------------------
# EvidenceLine
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvidenceLine:
    """One piece of cited evidence backing a component score.

    ``ref`` points at the trajectory artifact a reviewer should open, e.g.
    ``"git:src/utils.py"``, ``"step_state.json:retry_count"``, or
    ``"response:paragraph-3"``.  ``severity`` gates how the side-by-side
    reporter renders the line.
    """

    severity: str  # "info" | "warning" | "critical"
    ref: str
    detail: str

    def __post_init__(self) -> None:
        if self.severity not in ("info", "warning", "critical"):
            raise ValueError(
                f"EvidenceLine.severity must be info|warning|critical, got {self.severity!r}"
            )
        if not isinstance(self.ref, str) or not self.ref:
            raise ValueError("EvidenceLine.ref must be a non-empty str")
        if not isinstance(self.detail, str):
            raise ValueError("EvidenceLine.detail must be str")

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "ref": self.ref,
            "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> EvidenceLine:
        return cls(
            severity=str(d["severity"]),
            ref=str(d["ref"]),
            detail=str(d["detail"]),
        )


# ---------------------------------------------------------------------------
# ComponentScore
# ---------------------------------------------------------------------------


@dataclass
class ComponentScore:
    """One component metric result.

    ``score`` is normalized to ``[0.0, 1.0]`` so heterogeneous components
    (deterministic pass/fail and 0..5 judge scales) compose into one
    composite.  ``evidence`` is never empty for a real run — even a clean
    pass cites the artifact that proved it.
    """

    name: str
    kind: str  # "deterministic" | "judge"
    score: float
    evidence: list[EvidenceLine] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.name not in COMPONENT_NAMES:
            raise ValueError(
                f"ComponentScore.name must be one of {COMPONENT_NAMES}, got {self.name!r}"
            )
        if self.kind not in ("deterministic", "judge"):
            raise ValueError(
                f"ComponentScore.kind must be deterministic|judge, got {self.kind!r}"
            )
        if not isinstance(self.score, (int, float)):
            raise ValueError("ComponentScore.score must be numeric")
        if self.score < 0.0 or self.score > 1.0:
            raise ValueError(
                f"ComponentScore.score must be within [0,1], got {self.score!r}"
            )
        if not isinstance(self.evidence, list):
            raise ValueError("ComponentScore.evidence must be a list")

    @property
    def is_judge(self) -> bool:
        return self.kind == "judge"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "score": float(self.score),
            "evidence": [e.to_dict() for e in self.evidence],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ComponentScore:
        return cls(
            name=str(d["name"]),
            kind=str(d["kind"]),
            score=float(d["score"]),
            evidence=[EvidenceLine.from_dict(e) for e in d.get("evidence", [])],
        )


# ---------------------------------------------------------------------------
# TrajectoryBundle
# ---------------------------------------------------------------------------


@dataclass
class TrajectoryBundle:
    """Normalized snapshot of one completed run's trajectory evidence.

    Built by ``bundle.collect_bundle`` after a run finishes: git scope,
    verification result, MAP ``.map/<branch>/`` artifacts (read, never
    created), resiliency signals, and the agent's final response.  The bundle
    is what gates and the judge score; it is also persisted alongside the
    JSONL so a side-by-side comparator can re-open it.
    """

    fixture: str
    scenario: str
    branch: str
    collected_at: str
    final_response: str
    git: dict[str, Any]
    verification: dict[str, Any]
    map_artifacts: dict[str, Any] = field(default_factory=dict)
    resiliency_signals: dict[str, Any] = field(default_factory=dict)
    run_meta: dict[str, Any] = field(default_factory=dict)
    schema_version: str = _BUNDLE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "fixture": self.fixture,
            "scenario": self.scenario,
            "branch": self.branch,
            "collected_at": self.collected_at,
            "final_response": self.final_response,
            "git": dict(self.git),
            "verification": dict(self.verification),
            "map_artifacts": dict(self.map_artifacts),
            "resiliency_signals": dict(self.resiliency_signals),
            "run_meta": dict(self.run_meta),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TrajectoryBundle:
        return cls(
            schema_version=str(d.get("schema_version", _BUNDLE_SCHEMA_VERSION)),
            fixture=str(d["fixture"]),
            scenario=str(d["scenario"]),
            branch=str(d["branch"]),
            collected_at=str(d["collected_at"]),
            final_response=str(d.get("final_response", "")),
            git=dict(d.get("git", {})),
            verification=dict(d.get("verification", {})),
            map_artifacts=dict(d.get("map_artifacts", {})),
            resiliency_signals=dict(d.get("resiliency_signals", {})),
            run_meta=dict(d.get("run_meta", {})),
        )


# ---------------------------------------------------------------------------
# JudgeMeta
# ---------------------------------------------------------------------------


@dataclass
class JudgeMeta:
    """Provenance + caveats for the batched judge call.

    Recorded on every eval row so a reader never mistakes a judge score for
    ground truth: model, prompt version, ordering, and the known LLM-judge
    caveats (self-preference / positional bias per AgentLens).  ``skipped``
    marks dry-run / ``--no-judge`` rows where judge components are absent.
    """

    prompt_version: str
    ordering: str
    skipped: bool
    model: str | None = None
    caveats: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "prompt_version": self.prompt_version,
            "ordering": self.ordering,
            "skipped": self.skipped,
            "caveats": list(self.caveats),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> JudgeMeta:
        return cls(
            model=d.get("model"),
            prompt_version=str(d["prompt_version"]),
            ordering=str(d["ordering"]),
            skipped=bool(d["skipped"]),
            caveats=list(d.get("caveats", [])),
        )


# ---------------------------------------------------------------------------
# TrajectoryEvalRecord  (append-only .jsonl row)
# ---------------------------------------------------------------------------


@dataclass
class TrajectoryEvalRecord:
    """One scored trajectory outcome-eval row.

    One JSON object per line in
    ``.map/eval-runs/trajectory/<skill>/<ts>.jsonl``.  ``composite`` is a
    normalized 0..1 quality index across ``components``; ``hard_pass`` marks
    formal+end_result success plus a passing composite.  ``bundle_summary``
    is a compact projection (scope + verification) so a reader can scan a
    row without loading the full bundle.
    """

    run_id: str
    fixture: str
    run: int
    ts: str
    components: list[ComponentScore]
    composite: float
    hard_pass: bool
    expected_outcome: str
    judge_meta: JudgeMeta
    error: str | None = None
    bundle_summary: dict[str, Any] = field(default_factory=dict)
    schema_version: str = _EVAL_SCHEMA_VERSION

    def component_by_name(self, name: str) -> ComponentScore | None:
        for c in self.components:
            if c.name == name:
                return c
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "fixture": self.fixture,
            "run": self.run,
            "ts": self.ts,
            "components": [c.to_dict() for c in self.components],
            "composite": float(self.composite),
            "hard_pass": bool(self.hard_pass),
            "expected_outcome": self.expected_outcome,
            "judge_meta": self.judge_meta.to_dict(),
            "bundle_summary": dict(self.bundle_summary),
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TrajectoryEvalRecord:
        return cls(
            schema_version=str(d.get("schema_version", _EVAL_SCHEMA_VERSION)),
            run_id=str(d["run_id"]),
            fixture=str(d["fixture"]),
            run=int(d["run"]),
            ts=str(d["ts"]),
            components=[
                ComponentScore.from_dict(c) for c in d.get("components", [])
            ],
            composite=float(d["composite"]),
            hard_pass=bool(d["hard_pass"]),
            expected_outcome=str(d.get("expected_outcome", "complete")),
            judge_meta=JudgeMeta.from_dict(d.get("judge_meta", {})),
            error=d.get("error"),
            bundle_summary=dict(d.get("bundle_summary", {})),
        )


# ---------------------------------------------------------------------------
# Composite + run_id helpers
# ---------------------------------------------------------------------------


def compute_composite(components: list[ComponentScore]) -> float:
    """Normalized 0..1 quality index across components.

    Deterministic components (formal, end_result, tool_use) and judge
    components (instruction_compliance, pitfalls, reporting_trust) are each
    averaged then combined 50/50, so a formal failure can still be partially
    offset by good process — but never enough to mask a hard gate failure
    (``hard_pass`` is decided separately and requires formal+end_result to
    pass).  Missing a whole class (e.g. judge skipped) collapses to the
    present class so a dry-run still yields a meaningful number.
    """
    det = [c.score for c in components if c.kind == "deterministic"]
    jud = [c.score for c in components if c.kind == "judge"]
    det_avg = statistics.fmean(det) if det else 0.0
    jud_avg = statistics.fmean(jud) if jud else 0.0
    if det and jud:
        composite = 0.5 * det_avg + 0.5 * jud_avg
    elif det:
        composite = det_avg
    elif jud:
        composite = jud_avg
    else:
        composite = 0.0
    return round(max(0.0, min(1.0, composite)), 4)


def is_hard_pass(components: list[ComponentScore], composite: float) -> bool:
    """Hard pass = formal+end_result both pass AND composite clears threshold.

    A run that cheats the formal gate (scope violation, failing tests) is
    never a hard pass, regardless of how high the judge half scores it.
    """
    if composite < HARD_PASS_COMPOSITE_THRESHOLD:
        return False
    formal = next((c for c in components if c.name == "formal"), None)
    end = next((c for c in components if c.name == "end_result"), None)
    if formal is None or end is None:
        return False
    return formal.score >= 1.0 and end.score >= 1.0


def make_run_id(fixture: str, run: int) -> str:
    """Deterministic run identifier for resume + side-by-side matching."""
    slug = "".join(ch if ch.isalnum() else "-" for ch in fixture).strip("-")
    return f"f{slug}-r{run}"
