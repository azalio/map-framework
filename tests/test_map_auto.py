"""AC-7 matrix-completeness meta-test for the /map-auto autopilot feature.

ST-010 closes AC-7 by proving the test matrix accumulated across ST-001..
ST-009 is provably complete: each of AC-7's seven required areas must map to
at least one existing NAMED covering test. This file does NOT duplicate the
underlying tests -- it only asserts the named tests are still defined in
their owning suite, so a future rename or deletion of a covering test fails
this meta-test loudly instead of leaving a silent coverage hole.

Test names are discovered by AST parsing (not import) of the owning test
modules. AST parsing is chosen over importing the modules because it needs
no side effects (no sys.path mutation, no pulling in map_step_runner.py or
package extras) and cannot accidentally re-execute another test module's
top-level code -- it only reads which `test_*` functions are defined.
"""

import ast
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent


def _defined_test_names(module_filename: str) -> set[str]:
    """Return every `test_*` function name defined anywhere in the module
    (module-level or nested inside a `Test*` class), via AST parsing.
    """
    source = (_TESTS_DIR / module_filename).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=module_filename)
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    }


_STEP_RUNNER_TESTS = _defined_test_names("test_map_step_runner.py")
_ARTIFACT_SCHEMA_TESTS = _defined_test_names("test_artifact_schemas.py")
_SKILLS_TESTS = _defined_test_names("test_skills.py")
_TEMPLATE_RENDER_TESTS = _defined_test_names("test_template_render.py")


# area -> (set of test names actually defined in the owning suite(s),
# list of covering test names this area depends on). Every listed name must
# be present in the defined-names set -- if a name is renamed or deleted the
# corresponding area's check fails loudly rather than silently degrading to
# "at least one other test still covers it".
_AC7_MATRIX: dict[str, tuple[set[str], list[str]]] = {
    # (a) routing tiers, incl. 1b complete-state, tier-2 out-of-vocabulary
    # fallthrough, and tier-3 task_plan-without-blueprint.
    "routing_tiers": (
        _STEP_RUNNER_TESTS,
        [
            "test_select_route_tier1a_pending_step_state_yields_map_resume",
            "test_select_route_tier1b_all_complete_step_state_yields_map_check",
            "test_select_route_tier2_workflow_fit_map_efficient_is_honored",
            "test_select_route_tier2_out_of_vocabulary_falls_through_and_is_recorded",
            "test_select_route_tier3_resume_with_blueprint_yields_map_efficient",
            "test_select_route_tier3b_resume_without_blueprint_yields_map_plan",
            "test_select_route_tier4_trivial_bracket_yields_map_fast",
            "test_select_route_tier5_default_bare_branch_yields_map_plan",
        ],
    ),
    # (b) dry-run write isolation.
    "dry_run_write_isolation": (
        _STEP_RUNNER_TESTS,
        [
            "test_route_task_dry_run_sets_executed_false_and_recommended_only",
            "test_route_task_dry_run_write_isolation",
            "test_route_task_never_calls_record_workflow_fit_or_create_approval_hold",
        ],
    ),
    # (c) hold auto-approve vs hard-stop split.
    "hold_auto_approve_vs_hard_stop": (
        _STEP_RUNNER_TESTS,
        [
            "test_auto_approvable_and_hard_stop_kinds_partition_approval_hold_kinds",
            "test_auto_decide_holds_approves_every_auto_approvable_kind",
            "test_auto_decide_holds_leaves_hard_stop_kinds_pending",
            "test_auto_decide_holds_never_invokes_decide_approval_hold_on_hard_stop_kind",
        ],
    ),
    # (d) phase ledger + chain_status transitions + in-progress re-route refusal.
    "phase_ledger_and_reroute_refusal": (
        _STEP_RUNNER_TESTS,
        [
            "test_record_auto_phase_appends_one_schema_valid_six_field_entry",
            "test_record_auto_phase_terminal_success_status_completes_chain",
            "test_record_auto_phase_abort_class_status_aborts_chain",
            "test_record_auto_phase_attempt_counter_and_third_attempt_refused",
            "test_route_task_refuses_in_progress_chain_and_leaves_artifact_untouched",
            "test_route_task_reroutes_when_prior_status_allows",
        ],
    ),
    # (e) AUTO_ROUTE_SCHEMA golden-artifact validation.
    "auto_route_schema_golden": (
        _ARTIFACT_SCHEMA_TESTS,
        [
            "test_validate_auto_route_schema_golden",
            "test_validate_auto_route_schema_rejects_unknown_chain_status",
            "test_validate_auto_route_schema_rejects_unknown_selected_route",
            "test_validate_auto_route_schema_evidence_missing_source_fails",
            "test_validate_auto_route_schema_phases_missing_attempt_fails",
        ],
    ),
    # (f) skill registration + body budget.
    "skill_registration_and_body_budget": (
        _SKILLS_TESTS,
        [
            "test_map_auto_is_default_on_with_no_gating_flag",
            "test_skill_body_within_default_budget",
            "test_every_non_high_traffic_skill_body_within_default_budget",
        ],
    ),
    # (g) render parity.
    "render_parity": (
        _SKILLS_TESTS | _TEMPLATE_RENDER_TESTS,
        [
            "test_skill_templates_in_sync",
            "test_skill_supporting_files_in_sync",
            "test_real_repo_trees_in_sync",
        ],
    ),
}


def test_ac7_matrix_covers_exactly_seven_areas() -> None:
    """Guard against the matrix itself silently shrinking or growing."""
    assert len(_AC7_MATRIX) == 7, (
        f"AC-7 defines exactly seven required test areas; matrix currently "
        f"has {len(_AC7_MATRIX)}: {sorted(_AC7_MATRIX)}"
    )


@pytest.mark.parametrize("area", sorted(_AC7_MATRIX))
def test_ac7_area_has_named_covering_tests(area: str) -> None:
    """VC1 [AC-7]: every area maps to >=1 existing named covering test and
    fails if any listed covering test has been renamed or deleted."""
    defined_names, required_names = _AC7_MATRIX[area]
    assert required_names, f"AC-7 area {area!r} has no required test names configured."
    missing = [name for name in required_names if name not in defined_names]
    assert not missing, (
        f"AC-7 area {area!r} lost covering test(s) {missing} -- restore the "
        "test, or if it was deliberately renamed, update this matrix. An "
        "AC-7 area must never silently drop to zero covering tests."
    )
