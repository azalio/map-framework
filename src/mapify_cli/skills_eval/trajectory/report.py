"""Side-by-side candidate-vs-anchor regression report.

Anchored on AgentLens: absolute scores are not always enough, so regression
detection compares a candidate run distribution against an anchor run
distribution for the same fixture.  This module produces the comparison
objects and renders an HTML report (jinja2 + autoescape — the candidate text
is untrusted ``claude -p`` output, SECURITY-mandatory per viewer.py).

Pure comparison logic is separated from rendering so it can be unit-tested
without touching jinja2.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mapify_cli.skills_eval.trajectory.eval_schema import (
    COMPONENT_NAMES,
    REGRESSION_DELTA,
    TIE_EPSILON,
)
from mapify_cli.skills_eval.trajectory.repeated import (
    FixtureAggregate,
    aggregate_repeated,
)


def _decision_for_delta(delta: float) -> str:
    """Classify a candidate-vs-anchor delta into a bucket.

    - ``improvement`` : candidate beats anchor beyond REGRESSION_DELTA.
    - ``regression``  : candidate drops below anchor beyond REGRESSION_DELTA.
    - ``tie``         : within TIE_EPSILON (noise band).
    - ``small``       : a real but inconclusive change between the two bands.
    """
    if delta >= REGRESSION_DELTA:
        return "improvement"
    if delta <= -REGRESSION_DELTA:
        return "regression"
    if abs(delta) < TIE_EPSILON:
        return "tie"
    return "small"


@dataclass
class ComponentDelta:
    name: str
    candidate: float | None
    anchor: float | None
    delta: float | None
    decision: str  # improvement|regression|tie|small|missing

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "candidate": self.candidate,
            "anchor": self.anchor,
            "delta": self.delta,
            "decision": self.decision,
        }


@dataclass
class FixtureComparison:
    fixture: str
    candidate: FixtureAggregate
    anchor: FixtureAggregate | None
    composite_delta: float | None
    decision: str  # improvement|regression|tie|small|no_anchor
    component_deltas: list[ComponentDelta] = field(default_factory=list)
    regression_components: list[str] = field(default_factory=list)

    @property
    def is_regression(self) -> bool:
        return self.decision == "regression" or bool(self.regression_components)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixture": self.fixture,
            "candidate": self.candidate.to_dict(),
            "anchor": self.anchor.to_dict() if self.anchor else None,
            "composite_delta": self.composite_delta,
            "decision": self.decision,
            "component_deltas": [d.to_dict() for d in self.component_deltas],
            "regression_components": list(self.regression_components),
        }


@dataclass
class ComparisonReport:
    candidate_path: str
    anchor_path: str
    comparisons: list[FixtureComparison] = field(default_factory=list)

    @property
    def n_regressions(self) -> int:
        return sum(1 for c in self.comparisons if c.is_regression)

    @property
    def n_fixtures(self) -> int:
        return len(self.comparisons)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_path": self.candidate_path,
            "anchor_path": self.anchor_path,
            "comparisons": [c.to_dict() for c in self.comparisons],
        }


# ---------------------------------------------------------------------------
# Comparison construction
# ---------------------------------------------------------------------------


def _component_delta(
    candidate: FixtureAggregate, anchor: FixtureAggregate, name: str
) -> ComponentDelta:
    c_val = candidate.component_medians.get(name)
    a_val = anchor.component_medians.get(name)
    if c_val is None or a_val is None:
        return ComponentDelta(
            name=name,
            candidate=c_val,
            anchor=a_val,
            delta=None,
            decision="missing",
        )
    delta = c_val - a_val
    return ComponentDelta(
        name=name,
        candidate=c_val,
        anchor=a_val,
        delta=delta,
        decision=_decision_for_delta(delta),
    )


def compare(candidate: list, anchor: list) -> dict[str, FixtureComparison]:  # type: ignore[type-arg]
    """Build per-fixture comparisons from candidate + anchor record lists.

    *candidate* and *anchor* are lists of ``TrajectoryEvalRecord``.  Returns a
    dict keyed by fixture name.  Fixtures present only in the candidate get a
    ``no_anchor`` comparison; fixtures only in the anchor are omitted (they are
    not regressions in the candidate).
    """

    cand_agg = aggregate_repeated(candidate)
    anch_agg = aggregate_repeated(anchor)

    out: dict[str, FixtureComparison] = {}
    for cand_fixture in cand_agg.fixtures:
        anchor_fixture = anch_agg.fixture(cand_fixture.fixture)
        if anchor_fixture is None:
            out[cand_fixture.fixture] = FixtureComparison(
                fixture=cand_fixture.fixture,
                candidate=cand_fixture,
                anchor=None,
                composite_delta=None,
                decision="no_anchor",
                component_deltas=[
                    ComponentDelta(
                        name=name,
                        candidate=cand_fixture.component_medians.get(name),
                        anchor=None,
                        delta=None,
                        decision="missing",
                    )
                    for name in COMPONENT_NAMES
                ],
                regression_components=[],
            )
            continue
        composite_delta = cand_fixture.composite_median - anchor_fixture.composite_median
        comp_deltas = [
            _component_delta(cand_fixture, anchor_fixture, name)
            for name in COMPONENT_NAMES
        ]
        regression_components = [
            d.name for d in comp_deltas if d.decision == "regression"
        ]
        out[cand_fixture.fixture] = FixtureComparison(
            fixture=cand_fixture.fixture,
            candidate=cand_fixture,
            anchor=anchor_fixture,
            composite_delta=composite_delta,
            decision=_decision_for_delta(composite_delta),
            component_deltas=comp_deltas,
            regression_components=regression_components,
        )
    return out


def build_report(
    candidate: list,  # type: ignore[type-arg]
    anchor: list,  # type: ignore[type-arg]
    *,
    candidate_path: str,
    anchor_path: str,
) -> ComparisonReport:
    """Build a full ``ComparisonReport`` from candidate + anchor record lists."""
    _validate_records(candidate, "candidate")
    _validate_records(anchor, "anchor")
    comparisons = list(compare(candidate, anchor).values())
    return ComparisonReport(
        candidate_path=candidate_path,
        anchor_path=anchor_path,
        comparisons=comparisons,
    )


def _validate_records(records: list, label: str) -> None:  # type: ignore[type-arg]
    from mapify_cli.skills_eval.trajectory.eval_schema import (
        TrajectoryEvalRecord,
    )

    if not all(isinstance(r, TrajectoryEvalRecord) for r in records):
        raise TypeError(f"{label} must be a list of TrajectoryEvalRecord")


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>MAP Trajectory Eval — Candidate vs Anchor</title>
<style>
  body { font-family: -apple-system, Segoe UI, sans-serif; margin: 2rem; color: #222; }
  h1 { font-size: 1.4rem; }
  .paths { color: #666; font-size: 0.85rem; margin-bottom: 1.5rem; }
  table { border-collapse: collapse; width: 100%%; margin-bottom: 2rem; }
  th, td { border: 1px solid #ddd; padding: 0.45rem 0.6rem; text-align: left; font-size: 0.85rem; }
  th { background: #f5f5f5; }
  .decision-regression { color: #b00020; font-weight: bold; }
  .decision-improvement { color: #1a7f37; font-weight: bold; }
  .decision-tie { color: #6e7781; }
  .decision-small { color: #9a6700; }
  .decision-no_anchor { color: #6e7781; font-style: italic; }
  .regressions { background: #ffeef0; border: 1px solid #ffb3b9; padding: 0.75rem 1rem; border-radius: 6px; margin-bottom: 1.5rem; }
  .ok { background: #effff4; border: 1px solid #b3e6c0; padding: 0.75rem 1rem; border-radius: 6px; margin-bottom: 1.5rem; }
  code { background: #f6f8fa; padding: 0.1rem 0.25rem; border-radius: 3px; }
  .flaky { color: #9a6700; font-size: 0.75rem; }
  details { margin-top: 0.5rem; }
  summary { cursor: pointer; font-size: 0.8rem; }
</style></head><body>
<h1>MAP Trajectory Eval — Candidate vs Anchor</h1>
<div class="paths">
  <div><strong>candidate:</strong> <code>{{ candidate_path }}</code></div>
  <div><strong>anchor:</strong> <code>{{ anchor_path }}</code></div>
</div>
{% if report.n_regressions > 0 %}
<div class="regressions">⚠ <strong>{{ report.n_regressions }}</strong> fixture(s) regressed vs anchor — see decision column.</div>
{% else %}
<div class="ok">No regressions vs anchor across {{ report.n_fixtures }} fixture(s).</div>
{% endif %}
{% for c in report.comparisons %}
<h2>{{ c.fixture }} — <span class="decision-{{ c.decision }}">{{ c.decision }}</span></h2>
<table>
<tr><th>metric</th><th>candidate median</th><th>anchor median</th><th>delta</th><th>decision</th></tr>
<tr>
  <td><strong>composite</strong></td>
  <td>{{ "%.3f"|format(c.candidate.composite_median) }}</td>
  <td>{{ "%.3f"|format(c.anchor.composite_median) if c.anchor else "—" }}</td>
  <td>{{ "%+.3f"|format(c.composite_delta) if c.composite_delta is not none else "—" }}</td>
  <td class="decision-{{ c.decision }}">{{ c.decision }}</td>
</tr>
{% for d in c.component_deltas %}
<tr>
  <td>{{ d.name }}</td>
  <td>{{ "%.3f"|format(d.candidate) if d.candidate is not none else "—" }}</td>
  <td>{{ "%.3f"|format(d.anchor) if d.anchor is not none else "—" }}</td>
  <td>{{ "%+.3f"|format(d.delta) if d.delta is not none else "—" }}</td>
  <td class="decision-{{ d.decision }}">{{ d.decision }}</td>
</tr>
{% endfor %}
</table>
<div>
  candidate: hard_pass {{ c.candidate.hard_pass_count }}/{{ c.candidate.n }},
  stddev {{ "%.3f"|format(c.candidate.composite_stddev) }}
  {% if c.candidate.flaky %}<span class="flaky">⚠ flaky ({{ c.candidate.flaky_reasons|join("; ") }})</span>{% endif %}
</div>
{% if c.regression_components %}
<div class="decision-regression">regressed components: {{ c.regression_components|join(", ") }}</div>
{% endif %}
{% endfor %}
</body></html>"""


def render_comparison_html(report: ComparisonReport) -> str:
    """Render a ``ComparisonReport`` to an HTML string (autoescaped)."""
    import jinja2  # type: ignore[import-untyped]

    env = jinja2.Environment(autoescape=True, undefined=jinja2.StrictUndefined)
    template = env.from_string(_HTML_TEMPLATE)
    # ``html.escape`` import keeps the module's escape capability explicit even
    # though jinja2 autoescape is the primary defense; left available for any
    # future non-template callers.
    _ = html.escape
    return template.render(
        candidate_path=report.candidate_path,
        anchor_path=report.anchor_path,
        report=report,
    )


def render_comparison_to_path(report: ComparisonReport, html_path: Path) -> Path:
    """Render *report* to *html_path*; returns the path. Creates parents."""
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(render_comparison_html(report), encoding="utf-8")
    return html_path
