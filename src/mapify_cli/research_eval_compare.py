"""Structural-discovery ROI comparison for MAP research-eval.

Compares two ResearchEvidence runs (baseline vs treatment) for the same
fixture task, scoring both quality and exploration-cost metrics separately.

This answers: "Does structural/provider-backed discovery reduce exploration
cost while preserving localization quality?"

Pass criteria (hard)
--------------------
- The treatment arm must meet the *quality floor* (file-level and line-level
  F1).  A treatment that cuts locations by returning fewer but wrong ones is
  still a regression.
- The treatment arm must not return more stale/missing-file paths than the
  baseline (stale paths contaminate Actor context with phantom evidence).

Pass criteria (advisory / warn)
--------------------------------
- Precision or recall regression vs baseline emits a warning even when
  the absolute floor is met.
- Overbroad location count increase emits a warning.

Metrics tracked (separate from quality)
----------------------------------------
- location_count — total locations returned.
- stale_count — locations whose paths do not exist in repo_root.
- overbroad_count — locations whose line span exceeds overbroad_line_threshold.
- malformed_count — citations that could not be normalized.
- avg_span — average line span across valid locations.

These exploration-cost metrics are returned alongside quality scores so
operators can verify that token/context reduction does not come at the
expense of evidence quality.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mapify_cli.research_eval import (
    ResearchLocalizationScore,
    ResearchLocation,
    load_expected_locations,
    parse_research_locations,
    score_research_output,
)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class DiscoveryMetrics:
    """Exploration-cost metrics for one ResearchEvidence arm.

    These are independent of quality (precision/recall/F1) and should be
    reported alongside quality scores to prevent token-only wins.
    """

    location_count: int
    stale_count: int
    overbroad_count: int
    malformed_count: int
    avg_span: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "location_count": self.location_count,
            "stale_count": self.stale_count,
            "overbroad_count": self.overbroad_count,
            "malformed_count": self.malformed_count,
            "avg_span": round(self.avg_span, 2),
        }


@dataclass
class ArmScore:
    """Combined quality + exploration-cost score for one eval arm."""

    arm_name: str
    quality: ResearchLocalizationScore
    discovery: DiscoveryMetrics

    def as_dict(self) -> dict[str, Any]:
        from mapify_cli.research_eval import score_to_dict

        return {
            "arm_name": self.arm_name,
            "quality": score_to_dict(self.quality),
            "discovery": self.discovery.as_dict(),
        }


@dataclass
class CompareReport:
    """Side-by-side comparison of baseline and treatment arms."""

    baseline: ArmScore
    treatment: ArmScore
    warnings: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failures

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "passed": self.passed,
            "warnings": self.warnings,
            "failures": self.failures,
            "baseline": self.baseline.as_dict(),
            "treatment": self.treatment.as_dict(),
            "deltas": self._deltas(),
        }

    def _deltas(self) -> dict[str, Any]:
        bq = self.baseline.quality
        tq = self.treatment.quality
        bd = self.baseline.discovery
        td = self.treatment.discovery
        return {
            "file_f1_delta": round(tq.file_level.f1 - bq.file_level.f1, 4),
            "line_f1_delta": round(tq.line_level.f1 - bq.line_level.f1, 4),
            "location_count_delta": td.location_count - bd.location_count,
            "stale_count_delta": td.stale_count - bd.stale_count,
            "overbroad_count_delta": td.overbroad_count - bd.overbroad_count,
            "avg_span_delta": round(td.avg_span - bd.avg_span, 2),
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _discovery_metrics(
    locations: Sequence[ResearchLocation],
    malformed_count: int,
    overbroad_line_threshold: int,
    repo_root: Path | None,
) -> DiscoveryMetrics:
    stale = 0
    overbroad = 0
    total_span = 0
    for loc in locations:
        span = loc.end_line - loc.start_line + 1
        total_span += span
        if span > overbroad_line_threshold:
            overbroad += 1
        if repo_root is not None:
            candidate = repo_root / Path(*loc.path.split("/"))
            if not candidate.is_file():
                stale += 1
    avg_span = total_span / len(locations) if locations else 0.0
    return DiscoveryMetrics(
        location_count=len(locations),
        stale_count=stale,
        overbroad_count=overbroad,
        malformed_count=malformed_count,
        avg_span=avg_span,
    )


def _score_arm(
    arm_name: str,
    output_text: str,
    expected: list[dict[str, Any]],
    *,
    repo_root: Path | None,
    overbroad_line_threshold: int,
) -> ArmScore:
    # Parse without repo_root to obtain ALL raw locations (existence filtering
    # happens inside parse when repo_root is set, turning missing files into
    # malformed entries — we need the raw list for stale counting).
    raw_parsed = parse_research_locations(output_text, repo_root=None)
    quality = score_research_output(
        output_text,
        expected,
        repo_root=repo_root,
        overbroad_line_threshold=overbroad_line_threshold,
    )
    discovery = _discovery_metrics(
        raw_parsed.locations,
        malformed_count=len(raw_parsed.malformed),
        overbroad_line_threshold=overbroad_line_threshold,
        repo_root=repo_root,
    )
    return ArmScore(arm_name=arm_name, quality=quality, discovery=discovery)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compare_research_runs(
    baseline_output: str,
    treatment_output: str,
    expected_locations: list[dict[str, Any]],
    *,
    baseline_name: str = "baseline",
    treatment_name: str = "treatment",
    repo_root: Path | None = None,
    overbroad_line_threshold: int = 50,
    min_treatment_file_f1: float = 0.0,
    min_treatment_line_f1: float = 0.0,
    max_stale_regression: int = 0,
    warn_on_quality_regression: bool = True,
) -> CompareReport:
    """Compare two ResearchEvidence runs side-by-side.

    Quality metrics (precision/recall/F1) and exploration-cost metrics
    (location_count, stale_count, overbroad_count) are scored separately.

    Args:
        baseline_output: ResearchEvidence text/JSON from the baseline arm
            (e.g. glob_grep discovery).
        treatment_output: ResearchEvidence text/JSON from the treatment arm
            (e.g. structural-map/code-graph discovery).
        expected_locations: List of expected file/line-range dicts.
        baseline_name: Display name for the baseline arm.
        treatment_name: Display name for the treatment arm.
        repo_root: Optional repo root for path existence checks (stale
            detection) and line-range validation.
        overbroad_line_threshold: Location line spans above this are counted
            as over-broad.
        min_treatment_file_f1: Hard floor on treatment file-level F1.  A
            treatment that fails this floor triggers a FAIL even if it
            returns fewer locations.
        min_treatment_line_f1: Hard floor on treatment line-level F1.
        max_stale_regression: Maximum increase in stale-path count allowed
            for the treatment arm relative to the baseline.  0 means the
            treatment must not introduce new stale paths.
        warn_on_quality_regression: Emit a warning when treatment F1 drops
            below baseline F1 (even if the absolute floor is met).

    Returns:
        :class:`CompareReport` with per-arm scores, deltas, warnings, and
        failures.  ``report.passed`` is ``True`` only when no hard failures
        occurred.
    """
    baseline = _score_arm(
        baseline_name,
        baseline_output,
        expected_locations,
        repo_root=repo_root,
        overbroad_line_threshold=overbroad_line_threshold,
    )
    treatment = _score_arm(
        treatment_name,
        treatment_output,
        expected_locations,
        repo_root=repo_root,
        overbroad_line_threshold=overbroad_line_threshold,
    )

    report = CompareReport(baseline=baseline, treatment=treatment)

    # Hard failure: treatment quality floor
    if treatment.quality.file_level.f1 < min_treatment_file_f1:
        report.failures.append(
            f"QUALITY_FLOOR: treatment file-level F1 "
            f"{treatment.quality.file_level.f1:.3f} "
            f"< floor {min_treatment_file_f1:.3f}. "
            "Token/LOC reduction cannot compensate for lower precision/recall."
        )
    if treatment.quality.line_level.f1 < min_treatment_line_f1:
        report.failures.append(
            f"QUALITY_FLOOR: treatment line-level F1 "
            f"{treatment.quality.line_level.f1:.3f} "
            f"< floor {min_treatment_line_f1:.3f}. "
            "Token/LOC reduction cannot compensate for lower precision/recall."
        )

    # Hard failure: stale regression
    stale_delta = treatment.discovery.stale_count - baseline.discovery.stale_count
    if stale_delta > max_stale_regression:
        report.failures.append(
            f"STALE_REGRESSION: treatment introduced {stale_delta} additional "
            f"stale/missing-path location(s) vs baseline "
            f"({treatment.discovery.stale_count} vs {baseline.discovery.stale_count}). "
            "Stale paths contaminate Actor context with phantom evidence."
        )

    # Advisory warnings: quality regression vs baseline
    if warn_on_quality_regression:
        file_delta = treatment.quality.file_level.f1 - baseline.quality.file_level.f1
        if file_delta < 0:
            report.warnings.append(
                f"QUALITY_REGRESSION: treatment file-level F1 dropped by "
                f"{abs(file_delta):.3f} vs baseline "
                f"({treatment.quality.file_level.f1:.3f} vs "
                f"{baseline.quality.file_level.f1:.3f})."
            )
        line_delta = treatment.quality.line_level.f1 - baseline.quality.line_level.f1
        if line_delta < 0:
            report.warnings.append(
                f"QUALITY_REGRESSION: treatment line-level F1 dropped by "
                f"{abs(line_delta):.3f} vs baseline "
                f"({treatment.quality.line_level.f1:.3f} vs "
                f"{baseline.quality.line_level.f1:.3f})."
            )

    # Advisory: overbroad regression
    overbroad_delta = (
        treatment.discovery.overbroad_count - baseline.discovery.overbroad_count
    )
    if overbroad_delta > 0:
        report.warnings.append(
            f"OVERBROAD_INCREASE: treatment returned {overbroad_delta} more "
            f"over-broad location(s) vs baseline "
            f"({treatment.discovery.overbroad_count} vs "
            f"{baseline.discovery.overbroad_count})."
        )

    return report


def compare_research_files(
    baseline_path: Path,
    treatment_path: Path,
    expected_path: Path,
    *,
    baseline_name: str = "baseline",
    treatment_name: str = "treatment",
    repo_root: Path | None = None,
    overbroad_line_threshold: int = 50,
    min_treatment_file_f1: float = 0.0,
    min_treatment_line_f1: float = 0.0,
    max_stale_regression: int = 0,
    warn_on_quality_regression: bool = True,
) -> CompareReport:
    """Compare two ResearchEvidence files and expected locations from disk.

    Convenience wrapper around :func:`compare_research_runs` that handles
    file I/O and expected-location loading.
    """
    baseline_output = baseline_path.read_text(encoding="utf-8")
    treatment_output = treatment_path.read_text(encoding="utf-8")
    expected = load_expected_locations(expected_path)
    return compare_research_runs(
        baseline_output,
        treatment_output,
        expected,
        baseline_name=baseline_name,
        treatment_name=treatment_name,
        repo_root=repo_root,
        overbroad_line_threshold=overbroad_line_threshold,
        min_treatment_file_f1=min_treatment_file_f1,
        min_treatment_line_f1=min_treatment_line_f1,
        max_stale_regression=max_stale_regression,
        warn_on_quality_regression=warn_on_quality_regression,
    )


def default_compare_path(root: Path, iso_timestamp: str) -> Path:
    """Return the default output path for a research-eval comparison run.

    The timestamp must be supplied by the CLI caller (clock-free core).
    """
    return (
        root / ".map" / "eval-runs" / "research-compare" / f"{iso_timestamp}.json"
    )


# ---------------------------------------------------------------------------
# Fixture corpus helpers
# ---------------------------------------------------------------------------

#: Minimal fixture ResearchEvidence for tests.  Both fixtures cover the
#: same expected locations with the same quality so comparisons produce
#: deterministic deltas.  Tests inject different location counts to
#: exercise exploration-cost metrics.

FIXTURE_EXPECTED: list[dict[str, Any]] = [
    {"path": "src/mapify_cli/research_eval.py", "lines": [85, 128]},
    {"path": "src/mapify_cli/research_eval.py", "lines": [131, 147]},
]


def _make_evidence_json(locations: list[dict[str, Any]]) -> str:
    return json.dumps({"relevant_locations": locations})


FIXTURE_BASELINE_OUTPUT: str = _make_evidence_json(
    [
        {"path": "src/mapify_cli/research_eval.py", "lines": [85, 128]},
        {"path": "src/mapify_cli/research_eval.py", "lines": [131, 147]},
        {"path": "src/mapify_cli/research_eval.py", "lines": [1, 50]},
        {"path": "src/mapify_cli/research_eval.py", "lines": [51, 83]},
    ]
)

FIXTURE_TREATMENT_OUTPUT: str = _make_evidence_json(
    [
        {"path": "src/mapify_cli/research_eval.py", "lines": [85, 128]},
        {"path": "src/mapify_cli/research_eval.py", "lines": [131, 147]},
    ]
)
