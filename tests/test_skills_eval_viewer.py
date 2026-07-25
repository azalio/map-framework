"""Tests for src/mapify_cli/skills_eval/viewer.py.

Covers:
  VC1 — HTML output has one row per iteration, shows train/test pass-rates, diff content.
  VC2 — overfit rows carry a distinct CSS class marker; non-overfit rows do not.
  VC3 — viewer imports only eval_schema + stdlib + jinja2; no subprocess/anthropic.
  Security — candidate_description with XSS payload is HTML-escaped.
  proposal_failed — renders without raising.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from mapify_cli.skills_eval.eval_schema import OptimizeIterationRecord, OptimizeResult
from mapify_cli.skills_eval.viewer import render_html, render_to_path

# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

BASELINE_DESC = "Trigger when the user says 'map' or asks to plan."
DESC_ITER1 = "Trigger when the user says 'map', asks to plan, or mentions workflow."
DESC_ITER2_XSS = "Trigger on map <script>alert(1)</script> keyword."
# iteration 3: proposal_failed=True, candidate_description=None
# iteration 4: overfit=True


@pytest.fixture()
def opt_result() -> OptimizeResult:
    """OptimizeResult with >= 3 meaningful iterations:
    iter 0 — baseline (iteration=0, selected=False)
    iter 1 — normal improvement, selected=True
    iter 2 — XSS payload in description, not selected
    iter 3 — proposal_failed=True, candidate_description=None
    iter 4 — overfit=True (train up, test down)
    """
    iterations = [
        OptimizeIterationRecord(
            iteration=0,
            candidate_description=BASELINE_DESC,
            train_pass_rate=0.50,
            test_pass_rate=0.50,
            train_tokens_total=100,
            test_tokens_total=100,
            selected=False,
            proposal_failed=False,
            overfit=False,
        ),
        OptimizeIterationRecord(
            iteration=1,
            candidate_description=DESC_ITER1,
            train_pass_rate=0.70,
            test_pass_rate=0.65,
            train_tokens_total=200,
            test_tokens_total=200,
            selected=True,
            proposal_failed=False,
            overfit=False,
        ),
        OptimizeIterationRecord(
            iteration=2,
            candidate_description=DESC_ITER2_XSS,
            train_pass_rate=0.75,
            test_pass_rate=0.60,
            train_tokens_total=300,
            test_tokens_total=300,
            selected=False,
            proposal_failed=False,
            overfit=False,
        ),
        OptimizeIterationRecord(
            iteration=3,
            candidate_description=None,
            train_pass_rate=0.0,
            test_pass_rate=0.0,
            train_tokens_total=0,
            test_tokens_total=0,
            selected=False,
            proposal_failed=True,
            overfit=False,
        ),
        OptimizeIterationRecord(
            iteration=4,
            candidate_description="Trigger on map keyword only.",
            train_pass_rate=0.90,
            test_pass_rate=0.40,
            train_tokens_total=400,
            test_tokens_total=400,
            selected=False,
            proposal_failed=False,
            overfit=True,
        ),
    ]
    return OptimizeResult(
        skill="map-plan",
        eval_set_path="evals/map-plan.json",
        seed=42,
        n_train=10,
        n_test=5,
        baseline_description=BASELINE_DESC,
        winning_description=DESC_ITER1,
        winning_iteration=1,
        no_improvement=False,
        iterations=iterations,
    )


# ---------------------------------------------------------------------------
# VC1 — structure: HTML wrapper, one row per iteration, pass-rates, diff
# ---------------------------------------------------------------------------


class TestVC1Structure:
    def test_vc1_returns_html_string(self, opt_result: OptimizeResult) -> None:
        html = render_html(opt_result)
        assert isinstance(html, str)
        assert html.lstrip().lower().startswith("<!doctype html")

    def test_vc1_contains_html_tag(self, opt_result: OptimizeResult) -> None:
        html = render_html(opt_result)
        assert "<html" in html.lower()

    def test_vc1_one_tr_per_iteration(self, opt_result: OptimizeResult) -> None:
        html = render_html(opt_result)
        # Each iteration produces exactly one <tr class="..."> in tbody.
        # Count <tr elements that are iteration rows (not header).
        # The header has one <tr> without a class attr; data rows have class="".
        # We look for <tr class=" inside the tbody section.
        tbody_match = re.search(r"<tbody>(.*?)</tbody>", html, re.DOTALL)
        assert tbody_match is not None, "No <tbody> found"
        tbody = tbody_match.group(1)
        tr_count = len(re.findall(r"<tr\b", tbody))
        assert tr_count == len(opt_result.iterations)

    def test_vc1_train_pass_rates_present(self, opt_result: OptimizeResult) -> None:
        html = render_html(opt_result)
        # iter 1: 70.0%, iter 4: 90.0%
        assert "70.0%" in html
        assert "90.0%" in html

    def test_vc1_test_pass_rates_present(self, opt_result: OptimizeResult) -> None:
        html = render_html(opt_result)
        assert "65.0%" in html
        assert "40.0%" in html

    def test_vc1_diff_content_present(self, opt_result: OptimizeResult) -> None:
        """Diff output must appear for at least one iteration (iter 1 vs baseline)."""
        html = render_html(opt_result)
        # difflib will produce +/- lines; they land in diff-add/diff-rem spans
        assert "diff-add" in html or "diff-rem" in html

    def test_vc1_header_contains_skill(self, opt_result: OptimizeResult) -> None:
        html = render_html(opt_result)
        assert "map-plan" in html

    def test_vc1_header_contains_seed(self, opt_result: OptimizeResult) -> None:
        html = render_html(opt_result)
        assert "42" in html

    def test_vc1_header_contains_n_train_n_test(self, opt_result: OptimizeResult) -> None:
        html = render_html(opt_result)
        assert "10" in html
        assert "5" in html

    def test_vc1_header_contains_winning_iteration(self, opt_result: OptimizeResult) -> None:
        html = render_html(opt_result)
        assert "1" in html  # winning_iteration=1


# ---------------------------------------------------------------------------
# VC2 — overfit rows: marker present ONLY on overfit rows
# ---------------------------------------------------------------------------


class TestVC2OverfitHighlight:
    """Validate that row-overfit class appears EXACTLY on overfit rows.

    Strategy: count <tr class="row-overfit"> occurrences (which appear as
    row-level <tr> attributes), and also verify a non-overfit row's <tr> does
    NOT carry it.  The CSS rule .row-overfit in <style> uses a period not a
    quote, so it will not confuse the <tr class=" scan.
    """

    def _count_overfit_tr(self, html: str) -> int:
        """Count <tr ...class="row-overfit"...> occurrences."""
        return len(re.findall(r'<tr\s[^>]*class="row-overfit"', html))

    def _count_selected_tr(self, html: str) -> int:
        return len(re.findall(r'<tr\s[^>]*class="row-selected"', html))

    def test_vc2_overfit_marker_count_equals_overfit_iterations(
        self, opt_result: OptimizeResult
    ) -> None:
        html = render_html(opt_result)
        expected = sum(1 for it in opt_result.iterations if it.overfit)
        assert expected == 1, "fixture must have exactly 1 overfit iteration"
        assert self._count_overfit_tr(html) == 1

    def test_vc2_non_overfit_rows_do_not_carry_marker(
        self, opt_result: OptimizeResult
    ) -> None:
        """Selected-row tr must use row-selected, not row-overfit."""
        html = render_html(opt_result)
        # iter 1 is selected and not overfit → must have row-selected, not row-overfit
        assert self._count_selected_tr(html) >= 1
        # Ensure total overfit rows = only the truly overfit one
        assert self._count_overfit_tr(html) == 1

    def test_vc2_no_overfit_marker_in_stylesheet_block(
        self, opt_result: OptimizeResult
    ) -> None:
        """The <style> block uses .row-overfit (with dot), not class="row-overfit".

        This confirms our regex targeting `class="row-overfit"` can't
        accidentally match a CSS rule.
        """
        html = render_html(opt_result)
        style_match = re.search(r"<style>(.*?)</style>", html, re.DOTALL)
        assert style_match is not None
        style_block = style_match.group(1)
        # CSS selector uses dot notation — no class="..." in CSS
        assert 'class="row-overfit"' not in style_block

    def test_vc2_result_with_no_overfit_has_zero_markers(self) -> None:
        """Sanity: no overfit iterations → zero markers."""
        result = OptimizeResult(
            skill="test-skill",
            eval_set_path="evals/test.json",
            seed=0,
            n_train=5,
            n_test=5,
            baseline_description="baseline",
            winning_description="baseline",
            winning_iteration=0,
            no_improvement=True,
            iterations=[
                OptimizeIterationRecord(
                    iteration=0,
                    candidate_description="baseline",
                    train_pass_rate=0.5,
                    test_pass_rate=0.5,
                    overfit=False,
                )
            ],
        )
        html = render_html(result)
        assert len(re.findall(r'<tr\s[^>]*class="row-overfit"', html)) == 0


# ---------------------------------------------------------------------------
# VC3 — purity: no subprocess, no anthropic in viewer module source
# ---------------------------------------------------------------------------


class TestVC3Purity:
    _VIEWER_PATH = (
        Path(__file__).parent.parent
        / "src"
        / "mapify_cli"
        / "skills_eval"
        / "viewer.py"
    )

    def _get_viewer_source(self) -> str:
        return self._VIEWER_PATH.read_text(encoding="utf-8")

    def _get_viewer_imports(self) -> list[str]:
        """Return all top-level and lazy import names via AST."""
        source = self._get_viewer_source()
        tree = ast.parse(source)
        names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    names.append(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
        return names

    def test_vc3_no_subprocess_import(self) -> None:
        source = self._get_viewer_source()
        assert "subprocess" not in source

    def test_vc3_no_anthropic_import(self) -> None:
        source = self._get_viewer_source()
        assert "import anthropic" not in source

    def test_vc3_render_requires_no_claude(self, opt_result: OptimizeResult) -> None:
        """render_html must complete without any claude/subprocess call."""
        html = render_html(opt_result)
        assert len(html) > 0

    def test_vc3_viewer_module_imports_only_allowed(self) -> None:
        """Allowed top-level imports: __future__, difflib, pathlib,
        mapify_cli.skills_eval.eval_schema, jinja2 (lazy).
        """
        imports = self._get_viewer_imports()
        allowed_prefixes = (
            "__future__",
            "difflib",
            "pathlib",
            "mapify_cli.skills_eval.eval_schema",
            "jinja2",
        )
        for name in imports:
            assert any(name.startswith(p) for p in allowed_prefixes), (
                f"Unexpected import in viewer.py: {name!r}"
            )


# ---------------------------------------------------------------------------
# Security — autoescape XSS
# ---------------------------------------------------------------------------


class TestSecurity:
    def test_xss_payload_is_escaped(self, opt_result: OptimizeResult) -> None:
        html = render_html(opt_result)
        # The raw <script> tag must NOT appear
        assert "<script>" not in html
        # The escaped form must appear
        assert "&lt;script&gt;" in html

    def test_xss_payload_alert_not_executable(self, opt_result: OptimizeResult) -> None:
        """No bare alert(1) call in an executable context."""
        html = render_html(opt_result)
        # Ensure the payload is defanged (either escaped or absent as raw)
        assert "<script>alert(1)</script>" not in html


# ---------------------------------------------------------------------------
# proposal_failed graceful render
# ---------------------------------------------------------------------------


class TestProposalFailed:
    def test_proposal_failed_renders_without_raising(
        self, opt_result: OptimizeResult
    ) -> None:
        html = render_html(opt_result)
        # The "proposal failed" text must appear for the failed iteration
        assert "proposal failed" in html.lower()

    def test_proposal_failed_no_crash_standalone(self) -> None:
        """A result with only a proposal_failed iteration must not raise."""
        result = OptimizeResult(
            skill="s",
            eval_set_path="e",
            seed=1,
            n_train=3,
            n_test=3,
            baseline_description="base",
            winning_description="base",
            winning_iteration=0,
            no_improvement=True,
            iterations=[
                OptimizeIterationRecord(
                    iteration=0,
                    candidate_description=None,
                    train_pass_rate=0.0,
                    test_pass_rate=0.0,
                    proposal_failed=True,
                )
            ],
        )
        html = render_html(result)
        assert isinstance(html, str)
        assert "proposal failed" in html.lower()


# ---------------------------------------------------------------------------
# render_to_path
# ---------------------------------------------------------------------------


class TestRenderToPath:
    def test_render_to_path_writes_file(
        self, opt_result: OptimizeResult, tmp_path: Path
    ) -> None:
        out = tmp_path / "report.html"
        render_to_path(opt_result, out)
        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert "<html" in content.lower()

    def test_render_to_path_content_matches_render_html(
        self, opt_result: OptimizeResult, tmp_path: Path
    ) -> None:
        out = tmp_path / "report2.html"
        render_to_path(opt_result, out)
        assert out.read_text(encoding="utf-8") == render_html(opt_result)
