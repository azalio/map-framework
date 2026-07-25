"""Tests for boundary_quality_report.py — deterministic boundary-quality eval.

Verification criteria
---------------------
VC1  is_architecture_heavy returns True for refactor+large blueprint.
VC2  is_architecture_heavy returns True when 3+ arch-concern subtasks present.
VC3  is_architecture_heavy returns False for a simple low-risk blueprint.
VC4  FILE_SHARED_ACROSS_BOUNDARIES fires when the same file appears in two
     parallel (unrelated) subtasks.
VC5  FILE_SHARED_ACROSS_BOUNDARIES is suppressed when subtasks are related
     by a dependency edge.
VC6  CROSS_BOUNDARY_DEP_PRESSURE fires for two high-risk subtasks that share
     a directory prefix but have no declared dependency.
VC7  CROSS_BOUNDARY_DEP_PRESSURE is suppressed when one subtask depends on
     the other.
VC8  REFACTOR_WITHOUT_TEST_PAIR fires when a refactor subtask has no test
     subtask that declares it as a dependency.
VC9  REFACTOR_WITHOUT_TEST_PAIR is suppressed when a tests subtask explicitly
     depends on the refactor subtask.
VC10 LOW_COHESION_SUBTASK fires when affected_files span 3+ top-level dirs
     for a non-permissive concern_type.
VC11 LOW_COHESION_SUBTASK is suppressed for concern_type=refactor even when
     files span many directories (cross-cutting is expected for refactors).
VC12 A clean blueprint (well-split, no shared files, clear ownership) produces
     zero findings.
VC13 report_boundary_quality returns a BoundaryQualityReport with the correct
     is_architecture_heavy flag and a summary dict.
VC14 as_dict() produces a JSON-serialisable structure with the expected keys.
"""

from __future__ import annotations

from typing import Any

from mapify_cli.boundary_quality_report import (
    BoundaryQualityReport,
    is_architecture_heavy,
    report_boundary_quality,
)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _subtask(
    sid: str,
    files: list[str],
    concern_type: str = "runtime",
    diff_size: str = "small",
    risk: str = "low",
    deps: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": sid,
        "title": f"Task {sid}",
        "aag_contract": f"Actor -> do_{sid}() -> done",
        "dependencies": deps or [],
        "affected_files": files,
        "expected_diff_size": diff_size,
        "concern_type": concern_type,
        "risk": risk,
        "one_logical_step": True,
        "validation_criteria": [f"VC1 [AC-1]: {sid} works"],
    }


def _blueprint(*subtasks: dict[str, Any]) -> dict[str, Any]:
    return {
        "hard_constraints": [{"id": "AC-1", "description": "It must work"}],
        "soft_constraints": [],
        "subtasks": list(subtasks),
        "coverage_map": {"AC-1": subtasks[0]["id"] if subtasks else "ST-001"},
    }


# ---------------------------------------------------------------------------
# VC1-VC3  is_architecture_heavy
# ---------------------------------------------------------------------------


class TestVC1ArchitectureHeavyRefactorLarge:
    def test_refactor_plus_large_is_heavy(self) -> None:
        bp = _blueprint(_subtask("ST-001", ["src/x.py"], concern_type="refactor", diff_size="large"))
        assert is_architecture_heavy(bp) is True

    def test_refactor_small_is_not_heavy_alone(self) -> None:
        bp = _blueprint(_subtask("ST-001", ["src/x.py"], concern_type="refactor", diff_size="small"))
        assert is_architecture_heavy(bp) is False


class TestVC2ArchitectureHeavyThreeArchConcerns:
    def test_three_arch_concerns_is_heavy(self) -> None:
        bp = _blueprint(
            _subtask("ST-001", ["src/a.py"], concern_type="api"),
            _subtask("ST-002", ["src/b.py"], concern_type="data"),
            _subtask("ST-003", ["src/c.py"], concern_type="refactor"),
        )
        assert is_architecture_heavy(bp) is True

    def test_two_arch_concerns_not_heavy(self) -> None:
        bp = _blueprint(
            _subtask("ST-001", ["src/a.py"], concern_type="api"),
            _subtask("ST-002", ["src/b.py"], concern_type="data"),
            _subtask("ST-003", ["src/c.py"], concern_type="runtime"),
        )
        assert is_architecture_heavy(bp) is False


class TestVC3NotArchitectureHeavy:
    def test_simple_blueprint_not_heavy(self) -> None:
        bp = _blueprint(
            _subtask("ST-001", ["src/a.py"], concern_type="runtime"),
            _subtask("ST-002", ["tests/test_a.py"], concern_type="tests"),
        )
        assert is_architecture_heavy(bp) is False


# ---------------------------------------------------------------------------
# VC4-VC5  FILE_SHARED_ACROSS_BOUNDARIES
# ---------------------------------------------------------------------------


class TestVC4FileSharedAcrossBoundaries:
    def test_shared_file_in_parallel_subtasks_flagged(self) -> None:
        shared = "src/mapify_cli/shared_model.py"
        bp = _blueprint(
            _subtask("ST-001", [shared, "src/mapify_cli/a.py"]),
            _subtask("ST-002", [shared, "src/mapify_cli/b.py"]),
        )
        report = report_boundary_quality(bp)
        codes = [f.code for f in report.findings]
        assert "FILE_SHARED_ACROSS_BOUNDARIES" in codes

    def test_finding_names_both_subtasks(self) -> None:
        shared = "src/mapify_cli/shared_model.py"
        bp = _blueprint(
            _subtask("ST-001", [shared]),
            _subtask("ST-002", [shared]),
        )
        report = report_boundary_quality(bp)
        findings = [f for f in report.findings if f.code == "FILE_SHARED_ACROSS_BOUNDARIES"]
        assert len(findings) == 1
        assert set(findings[0].subtask_ids) == {"ST-001", "ST-002"}
        assert shared in findings[0].evidence

    def test_finding_is_warn_severity(self) -> None:
        shared = "src/mapify_cli/shared_model.py"
        bp = _blueprint(
            _subtask("ST-001", [shared]),
            _subtask("ST-002", [shared]),
        )
        report = report_boundary_quality(bp)
        findings = [f for f in report.findings if f.code == "FILE_SHARED_ACROSS_BOUNDARIES"]
        assert all(f.severity == "warn" for f in findings)


class TestVC5FileSharedSuppressedByDependency:
    def test_no_warning_when_st002_depends_on_st001(self) -> None:
        shared = "src/mapify_cli/shared_model.py"
        bp = _blueprint(
            _subtask("ST-001", [shared]),
            _subtask("ST-002", [shared], deps=["ST-001"]),
        )
        report = report_boundary_quality(bp)
        codes = [f.code for f in report.findings]
        assert "FILE_SHARED_ACROSS_BOUNDARIES" not in codes

    def test_no_warning_when_st001_depends_on_st002(self) -> None:
        shared = "src/mapify_cli/shared_model.py"
        bp = _blueprint(
            _subtask("ST-001", [shared], deps=["ST-002"]),
            _subtask("ST-002", [shared]),
        )
        report = report_boundary_quality(bp)
        codes = [f.code for f in report.findings]
        assert "FILE_SHARED_ACROSS_BOUNDARIES" not in codes


# ---------------------------------------------------------------------------
# VC6-VC7  CROSS_BOUNDARY_DEP_PRESSURE
# ---------------------------------------------------------------------------


class TestVC6CrossBoundaryDepPressure:
    def test_high_risk_subtasks_same_dir_no_dep_flagged(self) -> None:
        bp = _blueprint(
            _subtask("ST-001", ["src/mapify_cli/a.py"], risk="high"),
            _subtask("ST-002", ["src/mapify_cli/b.py"], risk="high"),
        )
        report = report_boundary_quality(bp)
        codes = [f.code for f in report.findings]
        assert "CROSS_BOUNDARY_DEP_PRESSURE" in codes

    def test_large_diff_subtasks_same_dir_flagged(self) -> None:
        bp = _blueprint(
            _subtask("ST-001", ["src/mapify_cli/a.py"], diff_size="large"),
            _subtask("ST-002", ["src/mapify_cli/b.py"], diff_size="large"),
        )
        report = report_boundary_quality(bp)
        codes = [f.code for f in report.findings]
        assert "CROSS_BOUNDARY_DEP_PRESSURE" in codes

    def test_finding_names_shared_directory(self) -> None:
        bp = _blueprint(
            _subtask("ST-001", ["src/mapify_cli/a.py"], risk="high"),
            _subtask("ST-002", ["src/mapify_cli/b.py"], risk="high"),
        )
        report = report_boundary_quality(bp)
        findings = [f for f in report.findings if f.code == "CROSS_BOUNDARY_DEP_PRESSURE"]
        assert len(findings) == 1
        assert "src/mapify_cli" in findings[0].evidence

    def test_low_risk_different_dirs_no_pressure(self) -> None:
        bp = _blueprint(
            _subtask("ST-001", ["src/mapify_cli/a.py"]),
            _subtask("ST-002", ["tests/test_b.py"]),
        )
        report = report_boundary_quality(bp)
        codes = [f.code for f in report.findings]
        assert "CROSS_BOUNDARY_DEP_PRESSURE" not in codes


class TestVC7CrossBoundaryDepPressureSuppressed:
    def test_suppressed_when_subtask_depends_on_other(self) -> None:
        bp = _blueprint(
            _subtask("ST-001", ["src/mapify_cli/a.py"], risk="high"),
            _subtask("ST-002", ["src/mapify_cli/b.py"], risk="high", deps=["ST-001"]),
        )
        report = report_boundary_quality(bp)
        codes = [f.code for f in report.findings]
        assert "CROSS_BOUNDARY_DEP_PRESSURE" not in codes


# ---------------------------------------------------------------------------
# VC8-VC9  REFACTOR_WITHOUT_TEST_PAIR
# ---------------------------------------------------------------------------


class TestVC8RefactorWithoutTestPair:
    def test_refactor_without_test_dep_flagged(self) -> None:
        bp = _blueprint(
            _subtask("ST-001", ["src/x.py"], concern_type="refactor"),
            _subtask("ST-002", ["tests/test_x.py"], concern_type="tests"),
            # ST-002 does NOT depend on ST-001 — test doesn't gate the refactor
        )
        report = report_boundary_quality(bp)
        codes = [f.code for f in report.findings]
        assert "REFACTOR_WITHOUT_TEST_PAIR" in codes

    def test_standalone_refactor_with_no_tests_subtask_flagged(self) -> None:
        bp = _blueprint(
            _subtask("ST-001", ["src/x.py"], concern_type="refactor"),
        )
        report = report_boundary_quality(bp)
        codes = [f.code for f in report.findings]
        assert "REFACTOR_WITHOUT_TEST_PAIR" in codes

    def test_finding_is_info_severity(self) -> None:
        bp = _blueprint(_subtask("ST-001", ["src/x.py"], concern_type="refactor"))
        report = report_boundary_quality(bp)
        findings = [f for f in report.findings if f.code == "REFACTOR_WITHOUT_TEST_PAIR"]
        assert all(f.severity == "info" for f in findings)


class TestVC9RefactorWithTestPairSuppressed:
    def test_suppressed_when_test_depends_on_refactor(self) -> None:
        bp = _blueprint(
            _subtask("ST-001", ["src/x.py"], concern_type="refactor"),
            _subtask("ST-002", ["tests/test_x.py"], concern_type="tests", deps=["ST-001"]),
        )
        report = report_boundary_quality(bp)
        codes = [f.code for f in report.findings]
        assert "REFACTOR_WITHOUT_TEST_PAIR" not in codes


# ---------------------------------------------------------------------------
# VC10-VC11  LOW_COHESION_SUBTASK
# ---------------------------------------------------------------------------


class TestVC10LowCohesionSubtask:
    def test_three_plus_dirs_flagged(self) -> None:
        bp = _blueprint(
            _subtask(
                "ST-001",
                ["src/mapify_cli/a.py", "tests/test_a.py", "docs/README.md", ".claude/hooks/foo.py"],
                concern_type="runtime",
            )
        )
        report = report_boundary_quality(bp)
        codes = [f.code for f in report.findings]
        assert "LOW_COHESION_SUBTASK" in codes

    def test_finding_names_directories(self) -> None:
        bp = _blueprint(
            _subtask(
                "ST-001",
                ["src/mapify_cli/a.py", "tests/test_a.py", "docs/README.md"],
                concern_type="runtime",
            )
        )
        report = report_boundary_quality(bp)
        findings = [f for f in report.findings if f.code == "LOW_COHESION_SUBTASK"]
        assert len(findings) == 1
        assert ".claude" not in findings[0].evidence  # only 3 dirs here

    def test_two_dirs_not_flagged(self) -> None:
        bp = _blueprint(
            _subtask("ST-001", ["src/mapify_cli/a.py", "tests/test_a.py"], concern_type="runtime")
        )
        report = report_boundary_quality(bp)
        codes = [f.code for f in report.findings]
        assert "LOW_COHESION_SUBTASK" not in codes


class TestVC11LowCohesionSuppressedForRefactor:
    def test_refactor_with_many_dirs_not_flagged(self) -> None:
        bp = _blueprint(
            _subtask(
                "ST-001",
                ["src/mapify_cli/a.py", "tests/test_a.py", "docs/arch.md"],
                concern_type="refactor",
            )
        )
        report = report_boundary_quality(bp)
        codes = [f.code for f in report.findings]
        assert "LOW_COHESION_SUBTASK" not in codes

    def test_docs_concern_type_not_flagged(self) -> None:
        bp = _blueprint(
            _subtask(
                "ST-001",
                ["docs/a.md", "docs/b.md", "README.md", "src/x.py"],
                concern_type="docs",
            )
        )
        report = report_boundary_quality(bp)
        codes = [f.code for f in report.findings]
        assert "LOW_COHESION_SUBTASK" not in codes


# ---------------------------------------------------------------------------
# VC12  Clean blueprint produces zero findings
# ---------------------------------------------------------------------------


class TestVC12CleanBlueprintZeroFindings:
    def test_well_split_blueprint_no_findings(self) -> None:
        """A well-designed blueprint: distinct file ownership, test depends on impl."""
        bp = _blueprint(
            _subtask("ST-001", ["src/mapify_cli/a.py"], concern_type="runtime", diff_size="small"),
            _subtask("ST-002", ["src/mapify_cli/b.py"], concern_type="api", diff_size="small"),
            _subtask(
                "ST-003",
                ["tests/test_a.py", "tests/test_b.py"],
                concern_type="tests",
                deps=["ST-001", "ST-002"],
            ),
        )
        report = report_boundary_quality(bp)
        assert report.findings == []

    def test_good_refactor_with_test_no_findings(self) -> None:
        bp = _blueprint(
            _subtask("ST-001", ["src/mapify_cli/a.py"], concern_type="refactor"),
            _subtask("ST-002", ["tests/test_a.py"], concern_type="tests", deps=["ST-001"]),
        )
        report = report_boundary_quality(bp)
        codes = [f.code for f in report.findings]
        assert "REFACTOR_WITHOUT_TEST_PAIR" not in codes
        assert "FILE_SHARED_ACROSS_BOUNDARIES" not in codes


# ---------------------------------------------------------------------------
# VC13  report_boundary_quality contract
# ---------------------------------------------------------------------------


class TestVC13ReportBoundaryQualityContract:
    def test_returns_boundary_quality_report(self) -> None:
        bp = _blueprint(_subtask("ST-001", ["src/x.py"]))
        result = report_boundary_quality(bp)
        assert isinstance(result, BoundaryQualityReport)

    def test_is_architecture_heavy_flag_set_correctly(self) -> None:
        heavy = _blueprint(
            _subtask("ST-001", ["src/x.py"], concern_type="refactor", diff_size="large")
        )
        light = _blueprint(_subtask("ST-001", ["src/x.py"]))
        assert report_boundary_quality(heavy).is_architecture_heavy is True
        assert report_boundary_quality(light).is_architecture_heavy is False

    def test_summary_counts_by_severity(self) -> None:
        shared = "src/mapify_cli/shared.py"
        bp = _blueprint(
            _subtask("ST-001", [shared]),
            _subtask("ST-002", [shared]),
            _subtask("ST-003", ["src/x.py"], concern_type="refactor"),
        )
        report = report_boundary_quality(bp)
        summary = report.summary
        assert summary.get("warn", 0) >= 1
        assert summary.get("info", 0) >= 1

    def test_empty_blueprint_no_crash(self) -> None:
        bp: dict[str, Any] = {
            "hard_constraints": [],
            "soft_constraints": [],
            "subtasks": [],
            "coverage_map": {},
        }
        result = report_boundary_quality(bp)
        assert isinstance(result, BoundaryQualityReport)
        assert result.findings == []


# ---------------------------------------------------------------------------
# VC14  as_dict serialisability
# ---------------------------------------------------------------------------


class TestVC14AsDictSerializability:
    def test_as_dict_has_expected_keys(self) -> None:
        bp = _blueprint(_subtask("ST-001", ["src/x.py"]))
        d = report_boundary_quality(bp).as_dict()
        assert "is_architecture_heavy" in d
        assert "findings" in d
        assert "summary" in d

    def test_as_dict_findings_have_expected_shape(self) -> None:
        shared = "src/mapify_cli/shared.py"
        bp = _blueprint(
            _subtask("ST-001", [shared]),
            _subtask("ST-002", [shared]),
        )
        d = report_boundary_quality(bp).as_dict()
        assert len(d["findings"]) >= 1
        finding = d["findings"][0]
        for key in ("severity", "code", "message", "subtask_ids", "evidence"):
            assert key in finding

    def test_as_dict_is_json_serializable(self) -> None:
        import json

        shared = "src/mapify_cli/shared.py"
        bp = _blueprint(
            _subtask("ST-001", [shared]),
            _subtask("ST-002", [shared]),
        )
        d = report_boundary_quality(bp).as_dict()
        serialized = json.dumps(d)
        assert isinstance(serialized, str)
        parsed = json.loads(serialized)
        assert parsed["findings"][0]["code"] == "FILE_SHARED_ACROSS_BOUNDARIES"
