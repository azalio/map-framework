"""Tests for research_eval_compare — structural-discovery ROI comparison.

All tests are fixture-based (no live model calls, no external services).
Fixture data uses pre-defined ResearchEvidence JSON strings.
"""

import json

from typer.testing import CliRunner

from mapify_cli import app
from mapify_cli.research_eval_compare import (
    FIXTURE_BASELINE_OUTPUT,
    FIXTURE_EXPECTED,
    FIXTURE_TREATMENT_OUTPUT,
    DiscoveryMetrics,
    compare_research_runs,
    default_compare_path,
)

runner = CliRunner()


# ---------------------------------------------------------------------------
# VC1 — compare_research_runs: clean comparison with perfect arms passes
# ---------------------------------------------------------------------------


def test_vc1_compare_perfect_arms_passes():
    perfect = json.dumps(
        {
            "relevant_locations": [
                {"path": "src/mapify_cli/research_eval.py", "lines": [85, 128]},
                {"path": "src/mapify_cli/research_eval.py", "lines": [131, 147]},
            ]
        }
    )
    report = compare_research_runs(perfect, perfect, FIXTURE_EXPECTED)
    assert report.passed, report.failures


def test_vc1_compare_fixture_default_passes():
    report = compare_research_runs(
        FIXTURE_BASELINE_OUTPUT, FIXTURE_TREATMENT_OUTPUT, FIXTURE_EXPECTED
    )
    assert report.passed, report.failures


# ---------------------------------------------------------------------------
# VC2 — quality floor: treatment below floor causes FAIL
# ---------------------------------------------------------------------------


def test_vc2_quality_floor_fail_on_empty_treatment():
    empty_treatment = json.dumps({"relevant_locations": []})
    report = compare_research_runs(
        FIXTURE_BASELINE_OUTPUT,
        empty_treatment,
        FIXTURE_EXPECTED,
        min_treatment_file_f1=0.5,
        min_treatment_line_f1=0.5,
    )
    assert not report.passed
    assert any("QUALITY_FLOOR" in f for f in report.failures)


def test_vc2_quality_floor_pass_when_met():
    exact_match = json.dumps(
        {
            "relevant_locations": [
                {"path": "src/mapify_cli/research_eval.py", "lines": [85, 128]},
                {"path": "src/mapify_cli/research_eval.py", "lines": [131, 147]},
            ]
        }
    )
    report = compare_research_runs(
        FIXTURE_BASELINE_OUTPUT,
        exact_match,
        FIXTURE_EXPECTED,
        min_treatment_file_f1=1.0,
        min_treatment_line_f1=1.0,
    )
    assert report.passed, report.failures


# ---------------------------------------------------------------------------
# VC3 — stale path detection: new stale paths in treatment cause FAIL
# ---------------------------------------------------------------------------


def test_vc3_stale_regression_causes_fail(tmp_path):
    stale_treatment = json.dumps(
        {
            "relevant_locations": [
                {"path": "src/mapify_cli/research_eval.py", "lines": [85, 128]},
                {"path": "nonexistent/phantom_file.py", "lines": [1, 10]},
            ]
        }
    )
    # Write a repo_root that has research_eval.py but not phantom_file.py
    (tmp_path / "src" / "mapify_cli").mkdir(parents=True)
    (tmp_path / "src" / "mapify_cli" / "research_eval.py").write_text(
        "# fake\n" * 200, encoding="utf-8"
    )

    report = compare_research_runs(
        FIXTURE_BASELINE_OUTPUT,
        stale_treatment,
        FIXTURE_EXPECTED,
        repo_root=tmp_path,
        max_stale_regression=0,
    )
    assert not report.passed
    assert any("STALE_REGRESSION" in f for f in report.failures)


def test_vc3_stale_regression_within_limit_passes(tmp_path):
    stale_treatment = json.dumps(
        {
            "relevant_locations": [
                {"path": "src/mapify_cli/research_eval.py", "lines": [85, 128]},
                {"path": "nonexistent/phantom_file.py", "lines": [1, 10]},
            ]
        }
    )
    (tmp_path / "src" / "mapify_cli").mkdir(parents=True)
    (tmp_path / "src" / "mapify_cli" / "research_eval.py").write_text(
        "# fake\n" * 200, encoding="utf-8"
    )
    report = compare_research_runs(
        FIXTURE_BASELINE_OUTPUT,
        stale_treatment,
        FIXTURE_EXPECTED,
        repo_root=tmp_path,
        max_stale_regression=2,  # allow up to 2 new stale paths
    )
    assert report.passed, report.failures


# ---------------------------------------------------------------------------
# VC4 — quality regression warning: treatment worse than baseline emits WARN
# ---------------------------------------------------------------------------


def test_vc4_quality_regression_emits_warning():
    worse_treatment = json.dumps({"relevant_locations": []})
    report = compare_research_runs(
        FIXTURE_BASELINE_OUTPUT,
        worse_treatment,
        FIXTURE_EXPECTED,
        warn_on_quality_regression=True,
    )
    assert any("QUALITY_REGRESSION" in w for w in report.warnings)


def test_vc4_no_regression_warning_when_suppressed():
    worse_treatment = json.dumps({"relevant_locations": []})
    report = compare_research_runs(
        FIXTURE_BASELINE_OUTPUT,
        worse_treatment,
        FIXTURE_EXPECTED,
        warn_on_quality_regression=False,
    )
    assert not any("QUALITY_REGRESSION" in w for w in report.warnings)


# ---------------------------------------------------------------------------
# VC5 — exploration-cost metrics: location_count, overbroad, avg_span
# ---------------------------------------------------------------------------


def test_vc5_treatment_fewer_locations():
    report = compare_research_runs(
        FIXTURE_BASELINE_OUTPUT, FIXTURE_TREATMENT_OUTPUT, FIXTURE_EXPECTED
    )
    # baseline has 4 locations, treatment has 2
    assert report.baseline.discovery.location_count == 4
    assert report.treatment.discovery.location_count == 2
    assert report.as_dict()["deltas"]["location_count_delta"] == -2


def test_vc5_overbroad_increase_emits_warning():
    overbroad_treatment = json.dumps(
        {
            "relevant_locations": [
                {"path": "src/mapify_cli/research_eval.py", "lines": [1, 200]},
            ]
        }
    )
    clean_baseline = json.dumps(
        {
            "relevant_locations": [
                {"path": "src/mapify_cli/research_eval.py", "lines": [85, 100]},
            ]
        }
    )
    report = compare_research_runs(
        clean_baseline,
        overbroad_treatment,
        FIXTURE_EXPECTED,
        overbroad_line_threshold=50,
    )
    assert any("OVERBROAD_INCREASE" in w for w in report.warnings)


def test_vc5_discovery_metrics_avg_span_computed():
    output = json.dumps(
        {
            "relevant_locations": [
                {"path": "src/mapify_cli/research_eval.py", "lines": [1, 10]},
                {"path": "src/mapify_cli/research_eval.py", "lines": [20, 30]},
            ]
        }
    )
    report = compare_research_runs(output, output, FIXTURE_EXPECTED)
    # [1,10] → span 10; [20,30] → span 11; avg = 10.5
    assert report.baseline.discovery.avg_span == 10.5


# ---------------------------------------------------------------------------
# VC6 — as_dict schema: both quality and exploration-cost metrics present
# ---------------------------------------------------------------------------


def test_vc6_as_dict_contains_quality_and_discovery():
    report = compare_research_runs(
        FIXTURE_BASELINE_OUTPUT, FIXTURE_TREATMENT_OUTPUT, FIXTURE_EXPECTED
    )
    d = report.as_dict()
    assert "quality" in d["baseline"]
    assert "discovery" in d["baseline"]
    assert "quality" in d["treatment"]
    assert "discovery" in d["treatment"]
    assert "deltas" in d


def test_vc6_as_dict_json_serializable():
    report = compare_research_runs(
        FIXTURE_BASELINE_OUTPUT, FIXTURE_TREATMENT_OUTPUT, FIXTURE_EXPECTED
    )
    raw = json.dumps(report.as_dict())
    parsed = json.loads(raw)
    assert parsed["schema_version"] == "1.0"


# ---------------------------------------------------------------------------
# VC7 — deltas: file_f1_delta and line_f1_delta in report
# ---------------------------------------------------------------------------


def test_vc7_deltas_reported():
    report = compare_research_runs(
        FIXTURE_BASELINE_OUTPUT, FIXTURE_TREATMENT_OUTPUT, FIXTURE_EXPECTED
    )
    deltas = report.as_dict()["deltas"]
    assert "file_f1_delta" in deltas
    assert "line_f1_delta" in deltas
    assert "location_count_delta" in deltas
    assert "stale_count_delta" in deltas
    assert "avg_span_delta" in deltas


# ---------------------------------------------------------------------------
# VC8 — DiscoveryMetrics.as_dict has expected keys
# ---------------------------------------------------------------------------


def test_vc8_discovery_metrics_as_dict_keys():
    dm = DiscoveryMetrics(
        location_count=3,
        stale_count=1,
        overbroad_count=0,
        malformed_count=0,
        avg_span=12.5,
    )
    d = dm.as_dict()
    assert set(d) == {
        "location_count",
        "stale_count",
        "overbroad_count",
        "malformed_count",
        "avg_span",
    }


# ---------------------------------------------------------------------------
# VC9 — default_compare_path helper
# ---------------------------------------------------------------------------


def test_vc9_default_compare_path_structure(tmp_path):
    path = default_compare_path(tmp_path, "20260705T120000Z")
    assert path == (
        tmp_path / ".map" / "eval-runs" / "research-compare" / "20260705T120000Z.json"
    )


# ---------------------------------------------------------------------------
# VC10 — CLI: mapify research-eval compare exits 0 on clean comparison
# ---------------------------------------------------------------------------


def test_vc10_cli_compare_passes(tmp_path):
    baseline = tmp_path / "baseline.json"
    treatment = tmp_path / "treatment.json"
    expected = tmp_path / "expected.json"

    baseline.write_text(FIXTURE_BASELINE_OUTPUT, encoding="utf-8")
    treatment.write_text(FIXTURE_TREATMENT_OUTPUT, encoding="utf-8")
    expected.write_text(
        json.dumps(FIXTURE_EXPECTED), encoding="utf-8"
    )

    result = runner.invoke(
        app,
        [
            "research-eval",
            "compare",
            str(baseline),
            str(treatment),
            str(expected),
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["passed"] is True


def test_vc10_cli_compare_fails_below_quality_floor(tmp_path):
    baseline = tmp_path / "baseline.json"
    empty_treatment = tmp_path / "treatment.json"
    expected = tmp_path / "expected.json"

    baseline.write_text(FIXTURE_BASELINE_OUTPUT, encoding="utf-8")
    empty_treatment.write_text(
        json.dumps({"relevant_locations": []}), encoding="utf-8"
    )
    expected.write_text(json.dumps(FIXTURE_EXPECTED), encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "research-eval",
            "compare",
            str(baseline),
            str(empty_treatment),
            str(expected),
            "--min-file-f1",
            "0.9",
        ],
    )
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert not payload["passed"]
    assert any("QUALITY_FLOOR" in f for f in payload["failures"])


def test_vc10_cli_compare_missing_file_exits_2(tmp_path):
    result = runner.invoke(
        app,
        [
            "research-eval",
            "compare",
            str(tmp_path / "no_baseline.json"),
            str(tmp_path / "no_treatment.json"),
            str(tmp_path / "no_expected.json"),
        ],
    )
    assert result.exit_code == 2


# ---------------------------------------------------------------------------
# VC11 — CLI: --out persists report to file
# ---------------------------------------------------------------------------


def test_vc11_cli_compare_out_flag_persists_report(tmp_path):
    baseline = tmp_path / "baseline.json"
    treatment = tmp_path / "treatment.json"
    expected = tmp_path / "expected.json"
    out_file = tmp_path / "report.json"

    baseline.write_text(FIXTURE_BASELINE_OUTPUT, encoding="utf-8")
    treatment.write_text(FIXTURE_TREATMENT_OUTPUT, encoding="utf-8")
    expected.write_text(json.dumps(FIXTURE_EXPECTED), encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "research-eval",
            "compare",
            str(baseline),
            str(treatment),
            str(expected),
            "--out",
            str(out_file),
        ],
    )
    assert result.exit_code == 0
    assert out_file.exists()
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert data["schema_version"] == "1.0"
