"""HTML report renderer for OptimizeResult.

Pure render module — no dispatch, no shell calls, no anthropic.
INV-6: imports OptimizeResult/OptimizeIterationRecord from eval_schema only.
Security: jinja2.Environment(autoescape=True); candidate_description is
untrusted (claude -p output) and MUST be escaped.
"""

from __future__ import annotations

import difflib
from pathlib import Path

from mapify_cli.skills_eval.eval_schema import OptimizeResult

# ---------------------------------------------------------------------------
# HTML template (module-level string)
# ---------------------------------------------------------------------------

_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Skill Optimization Report — {{ result.skill | e }}</title>
  <style>
    body { font-family: system-ui, sans-serif; margin: 2rem; color: #1a1a1a; }
    h1 { font-size: 1.4rem; margin-bottom: 0.5rem; }
    .meta { font-size: 0.9rem; color: #555; margin-bottom: 1.5rem; }
    .no-improvement { background: #fff3cd; padding: 0.5rem 1rem;
                      border-left: 4px solid #ffc107; margin-bottom: 1rem; }
    table { border-collapse: collapse; width: 100%; font-size: 0.85rem; }
    th { background: #f0f0f0; padding: 0.5rem 0.75rem; text-align: left;
         border-bottom: 2px solid #ccc; }
    td { padding: 0.5rem 0.75rem; border-bottom: 1px solid #e0e0e0;
         vertical-align: top; }
    tr.row-selected td { background: #e8f5e9; }
    tr.row-overfit td { background: #ffebee; }
    .badge { display: inline-block; padding: 0.1rem 0.4rem; border-radius: 3px;
             font-size: 0.75rem; margin-left: 0.3rem; }
    .badge-selected { background: #4caf50; color: #fff; }
    .badge-overfit  { background: #f44336; color: #fff; }
    .badge-failed   { background: #9e9e9e; color: #fff; }
    .diff-block { font-family: monospace; white-space: pre-wrap;
                  font-size: 0.8rem; line-height: 1.4; }
    .diff-add { background: #e6ffed; color: #1a7f37; }
    .diff-rem { background: #ffebe9; color: #cf222e; }
    .diff-ctx { color: #555; }
    .diff-sep { color: #999; font-style: italic; }
  </style>
</head>
<body>
  <h1>Skill Optimization Report</h1>
  <div class="meta">
    <strong>Skill:</strong> {{ result.skill | e }} &nbsp;|&nbsp;
    <strong>Seed:</strong> {{ result.seed }} &nbsp;|&nbsp;
    <strong>Train / Test:</strong> {{ result.n_train }} / {{ result.n_test }} &nbsp;|&nbsp;
    <strong>Winning iteration:</strong> {{ result.winning_iteration }}
  </div>
  {% if result.no_improvement %}
  <div class="no-improvement">No improvement found — baseline retained.</div>
  {% endif %}
  <table>
    <thead>
      <tr>
        <th>#</th>
        <th>Status</th>
        <th>Train %</th>
        <th>Test %</th>
        <th>Train tok</th>
        <th>Test tok</th>
        <th>Description diff vs prior</th>
      </tr>
    </thead>
    <tbody>
      {% for row in rows %}
      <tr class="{% if row.overfit %}row-overfit{% elif row.selected %}row-selected{% endif %}">
        <td>{{ row.iteration }}</td>
        <td>
          {% if row.selected %}<span class="badge badge-selected">selected</span>{% endif %}
          {% if row.overfit  %}<span class="badge badge-overfit">overfit</span>{% endif %}
          {% if row.proposal_failed %}<span class="badge badge-failed">failed</span>{% endif %}
        </td>
        <td>{{ "%.1f"|format(row.train_pass_rate * 100) }}%</td>
        <td>{{ "%.1f"|format(row.test_pass_rate  * 100) }}%</td>
        <td>{{ row.train_tokens_total }}</td>
        <td>{{ row.test_tokens_total  }}</td>
        <td>
          {% if row.proposal_failed %}
            <em>proposal failed — no candidate</em>
          {% elif row.diff_lines %}
            <div class="diff-block">
              {% for dl in row.diff_lines %}
                {% if dl.kind == "add" %}<span class="diff-add">{{ dl.text | e }}</span>
                {% elif dl.kind == "rem" %}<span class="diff-rem">{{ dl.text | e }}</span>
                {% elif dl.kind == "sep" %}<span class="diff-sep">{{ dl.text | e }}</span>
                {% else %}<span class="diff-ctx">{{ dl.text | e }}</span>
                {% endif %}
              {% endfor %}
            </div>
          {% else %}
            <div class="diff-block">{{ row.description | e }}</div>
          {% endif %}
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Diff helpers
# ---------------------------------------------------------------------------


class _DiffLine:
    """One diff line with a kind tag for template branching."""

    __slots__ = ("kind", "text")

    def __init__(self, kind: str, text: str) -> None:
        self.kind = kind
        self.text = text


def _compute_diff(prior: str, current: str) -> list[_DiffLine]:
    """Return unified-diff lines tagged by kind: add / rem / ctx / sep."""
    prior_lines = prior.splitlines(keepends=True)
    current_lines = current.splitlines(keepends=True)
    diff = list(
        difflib.unified_diff(prior_lines, current_lines, lineterm="", n=2)
    )
    if not diff:
        # identical — show nothing; caller will fall back to plain description
        return []

    result: list[_DiffLine] = []
    for raw in diff:
        if raw.startswith(("+++", "---")):
            # skip file-header lines produced by unified_diff
            continue
        if raw.startswith("@@"):
            result.append(_DiffLine("sep", raw.rstrip("\n")))
        elif raw.startswith("+"):
            result.append(_DiffLine("add", raw[1:].rstrip("\n")))
        elif raw.startswith("-"):
            result.append(_DiffLine("rem", raw[1:].rstrip("\n")))
        else:
            result.append(_DiffLine("ctx", raw.rstrip("\n")))
    return result


# ---------------------------------------------------------------------------
# Row builder
# ---------------------------------------------------------------------------


def _build_rows(result: OptimizeResult) -> list[dict[str, object]]:
    """Build per-iteration row dicts for template rendering."""
    rows: list[dict[str, object]] = []
    # Always a str: seeded from baseline_description and only ever reassigned to a
    # non-None candidate_description below (so the baseline row diffs against itself).
    prior_desc: str = result.baseline_description

    for rec in result.iterations:
        diff_lines: list[_DiffLine] = []
        description = rec.candidate_description or ""

        if rec.proposal_failed or rec.candidate_description is None:
            # No candidate — nothing to diff
            pass
        elif rec.iteration == 0:
            # Baseline iteration has no prior — show the description as-is
            pass
        else:
            diff_lines = _compute_diff(prior_desc, rec.candidate_description)

        row: dict[str, object] = {
            "iteration": rec.iteration,
            "train_pass_rate": rec.train_pass_rate,
            "test_pass_rate": rec.test_pass_rate,
            "train_tokens_total": rec.train_tokens_total,
            "test_tokens_total": rec.test_tokens_total,
            "selected": rec.selected,
            "overfit": rec.overfit,
            "proposal_failed": rec.proposal_failed,
            "diff_lines": diff_lines,
            "description": description,
        }
        rows.append(row)

        # Advance prior only when a valid candidate exists
        if rec.candidate_description is not None and not rec.proposal_failed:
            prior_desc = rec.candidate_description

    return rows


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_html(result: OptimizeResult) -> str:
    """Render an OptimizeResult to an HTML string.

    Uses jinja2.Environment(autoescape=True) so candidate_description values
    (untrusted claude -p output) are HTML-escaped automatically.
    """
    import jinja2

    rows = _build_rows(result)
    env = jinja2.Environment(autoescape=True)  # SECURITY: autoescape mandatory
    tmpl = env.from_string(_HTML)
    return tmpl.render(result=result, rows=rows)


def render_to_path(result: OptimizeResult, html_path: Path) -> None:
    """Render result to HTML and write to html_path."""
    html_path.write_text(render_html(result), encoding="utf-8")
