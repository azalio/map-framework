"""Tests for mapify governance report command and build_governance_report function."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mapify_cli import app
from mapify_cli.delivery.governance_report import (
    CATEGORIES,
    GovernanceAsset,
    GovernanceReport,
    build_governance_report,
)

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_skill_rules(skills_dir: Path, skills: dict | None = None) -> None:
    """Write a minimal skill-rules.json to skills_dir."""
    if skills is None:
        skills = {
            "map-plan": {
                "type": "manual",
                "skillClass": "task",
                "enforcement": "manual",
                "priority": "high",
                "description": "ARCHITECT phase: decompose a complex task",
                "promptTriggers": {"keywords": ["map-plan"], "intentPatterns": []},
            },
            "map-check": {
                "type": "manual",
                "skillClass": "task",
                "enforcement": "manual",
                "priority": "high",
                "description": "Run quality gates",
                "promptTriggers": {"keywords": ["map-check"], "intentPatterns": []},
            },
        }
    (skills_dir / "skill-rules.json").write_text(
        json.dumps({"version": "1.0", "description": "test", "skills": skills}),
        encoding="utf-8",
    )


def _make_skill_dir(skills_dir: Path, name: str) -> None:
    (skills_dir / name).mkdir(parents=True, exist_ok=True)
    (skills_dir / name / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")


def _make_hook(hooks_dir: Path, name: str) -> None:
    (hooks_dir / name).write_text(f"# {name}\n", encoding="utf-8")


def _make_reference(refs_dir: Path, name: str) -> None:
    (refs_dir / name).write_text(f"# {name} reference\n", encoding="utf-8")


def _make_learned_rule(learned_dir: Path, name: str, heading: str = "Title") -> None:
    (learned_dir / name).write_text(f"# {heading}\n\nContent.\n", encoding="utf-8")


@pytest.fixture()
def map_project(tmp_path: Path) -> Path:
    """Build a minimal but complete MAP project layout."""
    claude = tmp_path / ".claude"
    hooks = claude / "hooks"
    skills = claude / "skills"
    refs = claude / "references"
    learned = claude / "rules" / "learned"

    for d in (hooks, skills, refs, learned):
        d.mkdir(parents=True)

    _make_hook(hooks, "safety-guardrails.py")
    _make_hook(hooks, "workflow-gate.py")
    _make_hook(hooks, "map-memory-capture.py")

    _make_skill_rules(skills)
    _make_skill_dir(skills, "map-plan")
    _make_skill_dir(skills, "map-check")

    _make_reference(refs, "escalation-matrix.md")
    _make_reference(refs, "step-state-schema.md")

    _make_learned_rule(learned, "error-patterns.md", "Error Patterns (Learned)")

    return tmp_path


# ---------------------------------------------------------------------------
# Unit tests: build_governance_report
# ---------------------------------------------------------------------------


class TestBuildGovernanceReport:
    def test_returns_empty_report_when_no_claude_dir(self, tmp_path: Path) -> None:
        report = build_governance_report(tmp_path)
        assert report.assets == []
        assert report.gaps == []

    def test_scans_hooks(self, map_project: Path) -> None:
        report = build_governance_report(map_project)
        hook_names = {a.name for a in report.assets if a.kind == "hook"}
        assert "safety-guardrails.py" in hook_names
        assert "workflow-gate.py" in hook_names

    def test_hooks_are_enforced(self, map_project: Path) -> None:
        report = build_governance_report(map_project)
        for asset in report.assets:
            if asset.kind == "hook":
                assert asset.enforcement == "enforced"

    def test_scans_skills(self, map_project: Path) -> None:
        report = build_governance_report(map_project)
        skill_names = {a.name for a in report.assets if a.kind == "skill"}
        assert "map-plan" in skill_names
        assert "map-check" in skill_names

    def test_skills_are_prompt_only(self, map_project: Path) -> None:
        report = build_governance_report(map_project)
        for asset in report.assets:
            if asset.kind == "skill":
                assert asset.enforcement == "prompt-only"

    def test_scans_references(self, map_project: Path) -> None:
        report = build_governance_report(map_project)
        ref_names = {a.name for a in report.assets if a.kind == "reference"}
        assert "escalation-matrix.md" in ref_names
        assert "step-state-schema.md" in ref_names

    def test_references_are_prompt_only(self, map_project: Path) -> None:
        report = build_governance_report(map_project)
        for asset in report.assets:
            if asset.kind == "reference":
                assert asset.enforcement == "prompt-only"

    def test_scans_learned_rules(self, map_project: Path) -> None:
        report = build_governance_report(map_project)
        learned_names = {a.name for a in report.assets if a.kind == "learned-rule"}
        assert "error-patterns.md" in learned_names

    def test_learned_rules_are_learning_category(self, map_project: Path) -> None:
        report = build_governance_report(map_project)
        for asset in report.assets:
            if asset.kind == "learned-rule":
                assert asset.category == "learning"

    def test_reads_skill_rules_version(self, map_project: Path) -> None:
        report = build_governance_report(map_project)
        assert report.skill_rules_version == "1.0"

    def test_safety_guardrails_classified_as_policy(self, map_project: Path) -> None:
        report = build_governance_report(map_project)
        sg = next(a for a in report.assets if a.name == "safety-guardrails.py")
        assert sg.category == "policy"

    def test_workflow_gate_classified_as_harness(self, map_project: Path) -> None:
        report = build_governance_report(map_project)
        wg = next(a for a in report.assets if a.name == "workflow-gate.py")
        assert wg.category == "harness"

    def test_escalation_matrix_classified_as_oversight(self, map_project: Path) -> None:
        report = build_governance_report(map_project)
        em = next(a for a in report.assets if a.name == "escalation-matrix.md")
        assert em.category == "oversight"

    def test_map_memory_capture_classified_as_learning(self, map_project: Path) -> None:
        report = build_governance_report(map_project)
        mmc = next(a for a in report.assets if a.name == "map-memory-capture.py")
        assert mmc.category == "learning"

    def test_map_plan_classified_as_charter(self, map_project: Path) -> None:
        report = build_governance_report(map_project)
        mp = next(a for a in report.assets if a.name == "map-plan")
        assert mp.category == "charter"

    def test_map_wayfind_classified_as_oversight(self, tmp_path: Path) -> None:
        claude = tmp_path / ".claude"
        skills = claude / "skills"
        skills.mkdir(parents=True)
        _make_skill_rules(skills, {
            "map-wayfind": {
                "type": "manual",
                "skillClass": "task",
                "description": "Decision-frontier wayfinding",
            }
        })
        _make_skill_dir(skills, "map-wayfind")
        report = build_governance_report(tmp_path)
        asset = next(a for a in report.assets if a.name == "map-wayfind")
        assert asset.category == "oversight", (
            "map-wayfind must be classified as 'oversight', not the generic 'harness' fallback"
        )

    def test_map_architecture_classified_as_context(self, tmp_path: Path) -> None:
        claude = tmp_path / ".claude"
        skills = claude / "skills"
        skills.mkdir(parents=True)
        _make_skill_rules(skills, {
            "map-architecture": {
                "type": "manual",
                "skillClass": "task",
                "description": "Architecture-deepening report",
            }
        })
        _make_skill_dir(skills, "map-architecture")
        report = build_governance_report(tmp_path)
        asset = next(a for a in report.assets if a.name == "map-architecture")
        assert asset.category == "context", (
            "map-architecture must be classified as 'context', not the generic 'harness' fallback"
        )

    def test_asset_paths_are_relative_to_project(self, map_project: Path) -> None:
        report = build_governance_report(map_project)
        for asset in report.assets:
            assert not Path(asset.path).is_absolute()
            assert asset.path.startswith(".claude/")

    def test_generates_gap_when_both_key_hooks_present(
        self, map_project: Path
    ) -> None:
        report = build_governance_report(map_project)
        # With workflow-gate + safety-guardrails present, the hook-missing gaps should be absent
        hook_gaps = [g for g in report.gaps if "not found" in g]
        assert not hook_gaps

    def test_generates_gap_when_workflow_gate_missing(self, tmp_path: Path) -> None:
        claude = tmp_path / ".claude"
        hooks = claude / "hooks"
        skills = claude / "skills"
        hooks.mkdir(parents=True)
        skills.mkdir(parents=True)
        _make_hook(hooks, "safety-guardrails.py")
        _make_skill_rules(skills)
        _make_skill_dir(skills, "map-plan")
        report = build_governance_report(tmp_path)
        assert any("workflow-gate.py not found" in g for g in report.gaps)

    def test_generates_gap_when_safety_guardrails_missing(self, tmp_path: Path) -> None:
        claude = tmp_path / ".claude"
        hooks = claude / "hooks"
        skills = claude / "skills"
        hooks.mkdir(parents=True)
        skills.mkdir(parents=True)
        _make_hook(hooks, "workflow-gate.py")
        _make_skill_rules(skills)
        _make_skill_dir(skills, "map-plan")
        report = build_governance_report(tmp_path)
        assert any("safety-guardrails.py not found" in g for g in report.gaps)

    def test_unknown_hook_classified_as_harness(self, tmp_path: Path) -> None:
        claude = tmp_path / ".claude"
        hooks = claude / "hooks"
        hooks.mkdir(parents=True)
        _make_hook(hooks, "custom-hook.py")
        report = build_governance_report(tmp_path)
        custom = next((a for a in report.assets if a.name == "custom-hook.py"), None)
        assert custom is not None
        assert custom.category == "harness"

    def test_readme_in_hooks_is_skipped(self, tmp_path: Path) -> None:
        claude = tmp_path / ".claude"
        hooks = claude / "hooks"
        hooks.mkdir(parents=True)
        _make_hook(hooks, "README.md")
        report = build_governance_report(tmp_path)
        assert not any(a.name == "README.md" for a in report.assets)

    def test_description_from_skill_rules_json(self, tmp_path: Path) -> None:
        claude = tmp_path / ".claude"
        skills = claude / "skills"
        skills.mkdir(parents=True)
        _make_skill_rules(
            skills,
            {"my-skill": {"description": "Custom description from rules", "type": "manual"}},
        )
        _make_skill_dir(skills, "my-skill")
        report = build_governance_report(tmp_path)
        asset = next(a for a in report.assets if a.name == "my-skill")
        assert asset.description == "Custom description from rules"

    def test_learned_rule_extracts_heading(self, tmp_path: Path) -> None:
        claude = tmp_path / ".claude"
        learned = claude / "rules" / "learned"
        learned.mkdir(parents=True)
        _make_learned_rule(learned, "my-rules.md", "My Custom Rules")
        report = build_governance_report(tmp_path)
        rule = next(a for a in report.assets if a.name == "my-rules.md")
        assert rule.description == "My Custom Rules"

    def test_invalid_skill_rules_json_falls_through(self, tmp_path: Path) -> None:
        claude = tmp_path / ".claude"
        skills = claude / "skills"
        skills.mkdir(parents=True)
        (skills / "skill-rules.json").write_text("not json {", encoding="utf-8")
        _make_skill_dir(skills, "map-plan")
        report = build_governance_report(tmp_path)
        assert report.skill_rules_version is None
        assert any(a.name == "map-plan" for a in report.assets)


# ---------------------------------------------------------------------------
# Unit tests: GovernanceReport methods
# ---------------------------------------------------------------------------


class TestGovernanceReport:
    def _make_report(self) -> GovernanceReport:
        return GovernanceReport(
            project_path=Path("/fake/project"),
            assets=[
                GovernanceAsset(
                    "safety-guardrails.py",
                    "hook",
                    "policy",
                    "enforced",
                    "Denies dangerous commands",
                    ".claude/hooks/safety-guardrails.py",
                ),
                GovernanceAsset(
                    "workflow-gate.py",
                    "hook",
                    "harness",
                    "enforced",
                    "Phase gate",
                    ".claude/hooks/workflow-gate.py",
                ),
                GovernanceAsset(
                    "map-learn",
                    "skill",
                    "learning",
                    "prompt-only",
                    "Extract lessons",
                    ".claude/skills/map-learn/SKILL.md",
                ),
                GovernanceAsset(
                    "escalation-matrix.md",
                    "reference",
                    "oversight",
                    "prompt-only",
                    "Escalation paths",
                    ".claude/references/escalation-matrix.md",
                ),
            ],
            gaps=["map-plan: no harness gate"],
        )

    def test_by_category_covers_all_categories(self) -> None:
        report = self._make_report()
        by_cat = report.by_category()
        assert set(by_cat.keys()) == set(CATEGORIES)

    def test_by_category_groups_correctly(self) -> None:
        report = self._make_report()
        by_cat = report.by_category()
        assert len(by_cat["policy"]) == 1
        assert len(by_cat["harness"]) == 1
        assert len(by_cat["learning"]) == 1
        assert len(by_cat["oversight"]) == 1

    def test_enforced_count(self) -> None:
        report = self._make_report()
        assert report.enforced_count() == 2

    def test_prompt_only_count(self) -> None:
        report = self._make_report()
        assert report.prompt_only_count() == 2

    def test_as_json_valid(self) -> None:
        report = self._make_report()
        data = json.loads(report.as_json())
        assert data["version"] == "1.0"
        assert data["summary"]["total"] == 4
        assert data["summary"]["enforced"] == 2
        assert data["summary"]["prompt_only"] == 2
        assert len(data["assets"]) == 4
        assert data["gaps"] == ["map-plan: no harness gate"]

    def test_as_json_by_category_sums_correctly(self) -> None:
        report = self._make_report()
        data = json.loads(report.as_json())
        total = sum(data["summary"]["by_category"].values())
        assert total == 4

    def test_as_markdown_starts_with_heading(self) -> None:
        report = self._make_report()
        md = report.as_markdown()
        assert md.startswith("# MAP Governance Report")

    def test_as_markdown_has_all_category_sections(self) -> None:
        report = self._make_report()
        md = report.as_markdown()
        for cat in CATEGORIES:
            assert f"## {cat.capitalize()}" in md

    def test_as_markdown_has_summary_section(self) -> None:
        report = self._make_report()
        md = report.as_markdown()
        assert "## Summary" in md

    def test_as_markdown_has_gaps_section(self) -> None:
        report = self._make_report()
        md = report.as_markdown()
        assert "## Gaps" in md
        assert "map-plan: no harness gate" in md

    def test_as_markdown_has_evidence_section(self) -> None:
        report = self._make_report()
        md = report.as_markdown()
        assert "## Evidence Artifacts" in md

    def test_as_markdown_labels_enforced(self) -> None:
        report = self._make_report()
        md = report.as_markdown()
        assert "**enforced**" in md

    def test_as_markdown_labels_prompt_only(self) -> None:
        report = self._make_report()
        md = report.as_markdown()
        assert "prompt-only" in md

    def test_as_json_asset_has_required_fields(self) -> None:
        report = self._make_report()
        data = json.loads(report.as_json())
        for asset in data["assets"]:
            for field in ("name", "kind", "category", "enforcement", "description", "path"):
                assert field in asset


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------


class TestGovernanceReportCli:
    def test_report_on_empty_dir_exits_1(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["governance", "report", str(tmp_path)])
        assert result.exit_code == 1
        assert "No MAP assets found" in result.output

    def test_report_nonexistent_path_exits_1(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["governance", "report", str(tmp_path / "nope")])
        assert result.exit_code == 1
        assert "does not exist" in result.output

    def test_report_on_map_project_exits_0(self, map_project: Path) -> None:
        result = runner.invoke(app, ["governance", "report", str(map_project)])
        assert result.exit_code == 0, result.output

    def test_report_outputs_markdown_by_default(self, map_project: Path) -> None:
        result = runner.invoke(app, ["governance", "report", str(map_project)])
        assert "# MAP Governance Report" in result.output

    def test_report_json_flag_outputs_valid_json(self, map_project: Path) -> None:
        result = runner.invoke(app, ["governance", "report", str(map_project), "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "assets" in data
        assert "summary" in data

    def test_report_writes_to_out_file(self, map_project: Path, tmp_path: Path) -> None:
        out_file = tmp_path / "report.md"
        result = runner.invoke(
            app, ["governance", "report", str(map_project), "--out", str(out_file)]
        )
        assert result.exit_code == 0, result.output
        assert out_file.exists()
        content = out_file.read_text()
        assert "# MAP Governance Report" in content

    def test_report_json_out_file(self, map_project: Path, tmp_path: Path) -> None:
        out_file = tmp_path / "report.json"
        result = runner.invoke(
            app,
            ["governance", "report", str(map_project), "--json", "--out", str(out_file)],
        )
        assert result.exit_code == 0, result.output
        assert out_file.exists()
        data = json.loads(out_file.read_text())
        assert data["version"] == "1.0"

    def test_report_uses_cwd_by_default(
        self, map_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(map_project)
        result = runner.invoke(app, ["governance", "report"])
        assert result.exit_code == 0, result.output
        assert "# MAP Governance Report" in result.output

    def test_report_contains_asset_counts(self, map_project: Path) -> None:
        result = runner.invoke(app, ["governance", "report", str(map_project)])
        assert result.exit_code == 0, result.output
        # Summary section contains count info
        assert "Assets:" in result.output

    def test_report_on_real_framework_repo(self) -> None:
        """Smoke test: run against this actual framework repo's .claude/ directory."""
        repo_root = Path(__file__).parent.parent
        result = runner.invoke(app, ["governance", "report", str(repo_root)])
        assert result.exit_code == 0, result.output
        assert "# MAP Governance Report" in result.output
        # Real repo should have enforced and prompt-only assets
        assert "**enforced**" in result.output
        assert "prompt-only" in result.output

    def test_report_json_on_real_framework_repo(self) -> None:
        """Smoke test: JSON output against the real framework repo."""
        repo_root = Path(__file__).parent.parent
        result = runner.invoke(app, ["governance", "report", str(repo_root), "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["summary"]["total"] > 0
        assert data["summary"]["enforced"] > 0
        assert data["summary"]["prompt_only"] > 0
