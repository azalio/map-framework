"""Tests for minimality_eval — deterministic A/B benchmark harness.

All tests are fixture-based (no live model calls, no external services).
"""

import json

from mapify_cli.minimality_eval import (
    _DOCTRINE_TAG_CLOSE,
    _DOCTRINE_TAG_OPEN,
    DEFAULT_CORPUS,
    FULL_ARMS,
    EvalArm,
    MiniEvalTask,
    _loc,
    build_doctrine_block,
    default_run_path,
    run_minimality_eval,
)

# ---------------------------------------------------------------------------
# VC1 — build_doctrine_block returns empty string for off arm
# ---------------------------------------------------------------------------


def test_vc1_doctrine_block_off_is_empty():
    assert build_doctrine_block("off") == ""


# ---------------------------------------------------------------------------
# VC2 — build_doctrine_block contains open/close tags for non-off levels
# ---------------------------------------------------------------------------


def test_vc2_doctrine_block_lite_has_tags():
    block = build_doctrine_block("lite")
    assert _DOCTRINE_TAG_OPEN in block
    assert _DOCTRINE_TAG_CLOSE in block


def test_vc2_doctrine_block_full_has_tags():
    block = build_doctrine_block("full")
    assert _DOCTRINE_TAG_OPEN in block
    assert _DOCTRINE_TAG_CLOSE in block


def test_vc2_doctrine_block_ultra_has_tags():
    block = build_doctrine_block("ultra")
    assert _DOCTRINE_TAG_OPEN in block
    assert _DOCTRINE_TAG_CLOSE in block


def test_vc2_doctrine_block_lite_contains_level_line():
    block = build_doctrine_block("lite")
    assert "Level: lite" in block


def test_vc2_doctrine_block_full_contains_level_line():
    block = build_doctrine_block("full")
    assert "Level: full" in block


# ---------------------------------------------------------------------------
# VC3 — contamination isolation: off arm must lack doctrine, lite must have it
# ---------------------------------------------------------------------------


def test_vc3_off_arm_does_not_have_doctrine():
    block = build_doctrine_block("off")
    assert _DOCTRINE_TAG_OPEN not in block
    assert _DOCTRINE_TAG_CLOSE not in block


def test_vc3_treatment_arm_has_doctrine():
    block = build_doctrine_block("lite")
    assert _DOCTRINE_TAG_OPEN in block


# ---------------------------------------------------------------------------
# VC4 — default corpus / default arms — all tasks pass
# ---------------------------------------------------------------------------


def test_vc4_default_eval_passes():
    report = run_minimality_eval()
    assert report.passed, f"default eval should pass; failures={[t.failures for t in report.tasks]}"


def test_vc4_default_eval_covers_all_corpus_tasks():
    report = run_minimality_eval()
    assert len(report.tasks) == len(DEFAULT_CORPUS)


def test_vc4_default_eval_uses_two_arms():
    report = run_minimality_eval()
    assert report.arms == ["baseline", "treatment_lite"]


# ---------------------------------------------------------------------------
# VC5 — safety patterns must be present in both arm outputs
# ---------------------------------------------------------------------------


def test_vc5_safety_guard_task_passes_required_patterns():
    report = run_minimality_eval()
    safety = next(t for t in report.tasks if t.task_id == "SAFETY_GUARD")
    assert safety.passed, safety.failures
    for ar in safety.arm_results:
        assert not ar.missing_patterns, (
            f"arm {ar.arm_name} missing patterns: {ar.missing_patterns}"
        )


def test_vc5_eval_fails_when_safety_pattern_dropped():
    bad_task = MiniEvalTask(
        task_id="BAD_SAFETY",
        description="Treatment drops PermissionError guard.",
        baseline_code="raise PermissionError('denied')\n",
        treatment_code="pass  # guard removed\n",
        required_patterns=("PermissionError",),
    )
    arms = (
        EvalArm(name="baseline", minimality="off"),
        EvalArm(name="treatment_lite", minimality="lite"),
    )
    report = run_minimality_eval(corpus=(bad_task,), arms=arms)
    assert not report.passed
    task_result = report.tasks[0]
    assert any("SAFETY_PATTERN_MISSING" in f for f in task_result.failures)


# ---------------------------------------------------------------------------
# VC6 — contamination detection: fabricated contamination raises FAIL
# ---------------------------------------------------------------------------


def test_vc6_contaminated_baseline_raises_failure():
    """A task where both arms produce the same treatment code (baseline contaminated)."""
    contaminated_task = MiniEvalTask(
        task_id="CONTAMINATED",
        description="Baseline and treatment produce identical doctrine-containing output.",
        baseline_code="x = 1\n",
        treatment_code="x = 1\n",
        required_patterns=("x",),
    )
    # Create a pair where the baseline arm context is wrongly contaminated.
    # We simulate by providing a treatment arm labeled as baseline (minimality=off)
    # but with a context that would produce doctrine.  We achieve this by
    # creating an arm that expects no doctrine but providing the lite arm context
    # — the score_arm function uses the arm's minimality to build context,
    # so to test contamination we inject the arm directly.
    # Instead: use an arm with minimality="lite" named "baseline" to force
    # contamination (expects_doctrine=True, but the arm is labeled as non-off).
    # Actually the cleanest way is to test with an arm whose minimality is NOT
    # "off" but expects doctrine — this should PASS for treatment.
    # Let's test the opposite: an arm with minimality="off" but named treatment
    # — it should FAIL because the off arm will produce no doctrine but we'd
    # need it to have doctrine if expects_doctrine was True.
    #
    # The real contamination path: EvalArm(minimality="off").expects_doctrine is
    # False; build_doctrine_block("off") returns ""; so doctrine_present=False,
    # contaminated = (False != False) = False.  To trigger contamination we need
    # expects_doctrine != doctrine_present.
    #
    # We inject an arm whose minimality="lite" but name it "baseline" — it
    # expects doctrine (expects_doctrine=True) and doctrine_present=True → no
    # contamination.  Not helpful.
    #
    # Simplest real test: create an arm with minimality="off" whose baseline_code
    # accidentally contains the doctrine tag.  But _score_arm checks the context
    # block, not the code.  So to trigger contamination we need a scenario where
    # the arm context is wrongly tagged.
    #
    # We can test _score_arm directly:
    from mapify_cli.minimality_eval import _score_arm

    arm_off = EvalArm(name="baseline", minimality="off")
    # Fake context that has been contaminated (contains doctrine tag)
    fake_contaminated_ctx = f"{_DOCTRINE_TAG_OPEN}\nLevel: lite\n{_DOCTRINE_TAG_CLOSE}"
    result = _score_arm(contaminated_task, arm_off, fake_contaminated_ctx, "x = 1\n")
    assert result.contaminated, "off arm with doctrine in context must be marked contaminated"


def test_vc6_clean_baseline_not_contaminated():
    from mapify_cli.minimality_eval import _score_arm

    task = MiniEvalTask(
        task_id="CLEAN",
        description="Clean baseline",
        baseline_code="x = 1\n",
        treatment_code="x = 1\n",
        required_patterns=("x",),
    )
    arm_off = EvalArm(name="baseline", minimality="off")
    clean_ctx = ""  # build_doctrine_block("off") returns ""
    result = _score_arm(task, arm_off, clean_ctx, "x = 1\n")
    assert not result.contaminated


# ---------------------------------------------------------------------------
# VC7 — LOC metric: _loc counts non-empty lines only
# ---------------------------------------------------------------------------


def test_vc7_loc_counts_non_empty_lines():
    code = "a = 1\n\nb = 2\n\n\nc = 3\n"
    assert _loc(code) == 3


def test_vc7_loc_empty_string_is_zero():
    assert _loc("") == 0


def test_vc7_over_build_trap_treatment_fewer_loc():
    report = run_minimality_eval()
    obt = next(t for t in report.tasks if t.task_id == "OVER_BUILD_TRAP")
    baseline_ar = next(ar for ar in obt.arm_results if ar.minimality == "off")
    treatment_ar = next(ar for ar in obt.arm_results if ar.minimality != "off")
    assert treatment_ar.loc < baseline_ar.loc, (
        "minimality treatment should produce fewer LOC than baseline for an over-build trap"
    )


# ---------------------------------------------------------------------------
# VC8 — irreducible task: LOC delta within tolerance produces no failure
# ---------------------------------------------------------------------------


def test_vc8_irreducible_task_produces_no_failure():
    report = run_minimality_eval()
    irreducible = next(t for t in report.tasks if t.task_id == "IRREDUCIBLE")
    assert irreducible.passed, irreducible.failures


def test_vc8_irreducible_large_swing_produces_warning():
    big_baseline = "x = 1\n" * 20
    small_treatment = "x = 1\n"
    swinging_task = MiniEvalTask(
        task_id="SWINGING_IRREDUCIBLE",
        description="Irreducible task with unexpected large LOC swing.",
        baseline_code=big_baseline,
        treatment_code=small_treatment,
        required_patterns=("x",),
        is_irreducible=True,
        irreducible_tolerance=2,
    )
    arms = (
        EvalArm(name="baseline", minimality="off"),
        EvalArm(name="treatment_lite", minimality="lite"),
    )
    report = run_minimality_eval(corpus=(swinging_task,), arms=arms)
    task_result = report.tasks[0]
    assert any("IRREDUCIBLE_SWING" in w for w in task_result.warnings)
    assert task_result.passed, "large LOC swing on irreducible is a warning, not a failure"


# ---------------------------------------------------------------------------
# VC9 — report persistence: JSON is valid and round-trips
# ---------------------------------------------------------------------------


def test_vc9_report_persisted_as_valid_json(tmp_path):
    out = tmp_path / "report.json"
    report = run_minimality_eval(out_path=out)
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["schema_version"] == "1.0"
    assert data["summary"]["passed"] == report.passed
    assert len(data["tasks"]) == len(DEFAULT_CORPUS)


def test_vc9_report_arms_listed_correctly(tmp_path):
    out = tmp_path / "report.json"
    run_minimality_eval(out_path=out)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["arms"] == ["baseline", "treatment_lite"]


# ---------------------------------------------------------------------------
# VC10 — no_persist path: run without out_path works fine
# ---------------------------------------------------------------------------


def test_vc10_no_persist_returns_report_without_writing(tmp_path):
    report = run_minimality_eval(out_path=None)
    assert isinstance(report.passed, bool)
    # Nothing written
    assert not list(tmp_path.iterdir())


# ---------------------------------------------------------------------------
# VC11 — full arm support
# ---------------------------------------------------------------------------


def test_vc11_full_arms_include_three_arms():
    report = run_minimality_eval(arms=FULL_ARMS)
    assert set(report.arms) == {"baseline", "treatment_lite", "treatment_full"}


def test_vc11_full_arm_doctrine_block_has_full_level():
    block = build_doctrine_block("full")
    assert "Level: full" in block


# ---------------------------------------------------------------------------
# VC12 — default_run_path helper builds expected path
# ---------------------------------------------------------------------------


def test_vc12_default_run_path_structure(tmp_path):
    path = default_run_path(tmp_path, "20260705T120000Z")
    assert path == tmp_path / ".map" / "eval-runs" / "minimality" / "20260705T120000Z.json"


# ---------------------------------------------------------------------------
# VC13 — MiniEvalReport.summary separates code-size from safety metrics
# ---------------------------------------------------------------------------


def test_vc13_summary_separates_pass_fail_counts():
    report = run_minimality_eval()
    s = report.summary
    assert "task_pass_count" in s
    assert "task_fail_count" in s
    assert "warning_count" in s
    assert "failure_count" in s
    assert s["task_pass_count"] + s["task_fail_count"] == s["task_count"]


# ---------------------------------------------------------------------------
# VC14 — as_dict is JSON-serializable (no non-serializable objects)
# ---------------------------------------------------------------------------


def test_vc14_as_dict_is_json_serializable():
    report = run_minimality_eval()
    raw = json.dumps(report.as_dict())
    parsed = json.loads(raw)
    assert parsed["summary"]["task_count"] == len(DEFAULT_CORPUS)
