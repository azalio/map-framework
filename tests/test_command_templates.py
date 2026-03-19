"""
Tests for slash command templates.

Validates that workflow variant commands (map-fast, map-efficient) exist
and are properly formatted in the templates directory (canonical source).

Note: .claude/commands/ is gitignored (generated via mapify init), so tests
only validate src/mapify_cli/templates/commands/ which is the source of truth.
"""

import json
import pytest
from pathlib import Path


class TestCommandTemplates:
    """Test command template existence and format."""

    @pytest.fixture
    def project_root(self):
        """Get project root directory."""
        return Path(__file__).parent.parent

    @pytest.fixture
    def templates_commands_dir(self, project_root):
        """Get src/mapify_cli/templates/commands directory (canonical source)."""
        return project_root / "src" / "mapify_cli" / "templates" / "commands"

    def test_map_fast_exists_in_templates(self, templates_commands_dir):
        """Test that map-fast.md exists in templates/commands/."""
        map_fast = templates_commands_dir / "map-fast.md"
        assert map_fast.exists(), f"map-fast.md not found in {templates_commands_dir}"
        assert map_fast.is_file(), "map-fast.md should be a file"

    def test_map_efficient_exists_in_templates(self, templates_commands_dir):
        """Test that map-efficient.md exists in templates/commands/."""
        map_efficient = templates_commands_dir / "map-efficient.md"
        assert map_efficient.exists(), (
            f"map-efficient.md not found in {templates_commands_dir}"
        )
        assert map_efficient.is_file(), "map-efficient.md should be a file"

    def test_map_fast_has_frontmatter(self, templates_commands_dir):
        """Test that map-fast.md has proper frontmatter with description."""
        map_fast = templates_commands_dir / "map-fast.md"
        content = map_fast.read_text()

        assert content.startswith("---"), "map-fast.md should start with frontmatter"
        assert "description:" in content[:200], (
            "Frontmatter should contain description field"
        )
        assert content.split("---")[1].strip(), "Frontmatter should not be empty"

    def test_map_efficient_has_frontmatter(self, templates_commands_dir):
        """Test that map-efficient.md has proper frontmatter with description."""
        map_efficient = templates_commands_dir / "map-efficient.md"
        content = map_efficient.read_text()

        assert content.startswith("---"), (
            "map-efficient.md should start with frontmatter"
        )
        assert "description:" in content[:200], (
            "Frontmatter should contain description field"
        )
        assert content.split("---")[1].strip(), "Frontmatter should not be empty"

    def test_map_fast_contains_warning(self, templates_commands_dir):
        """Test that map-fast.md contains prominent warnings about limitations."""
        map_fast = templates_commands_dir / "map-fast.md"
        content = map_fast.read_text()

        # Check for warning markers
        assert "⚠️" in content or "WARNING" in content, (
            "map-fast.md should contain warning indicators"
        )
        assert "low-risk" in content.lower() or "low risk" in content.lower(), (
            "map-fast.md should indicate low-risk use only"
        )
        assert "NO learning" in content or "no learning" in content, (
            "Should mention no learning"
        )

    def test_map_efficient_suggests_map_learn(self, templates_commands_dir):
        """Test that map-efficient.md suggests optional /map-learn for learning."""
        map_efficient = templates_commands_dir / "map-efficient.md"
        content = map_efficient.read_text()

        # Learning is now in separate /map-learn command
        # map-efficient should suggest it as optional
        assert "/map-learn" in content, "Should suggest /map-learn for learning"
        assert "optional" in content.lower(), "Should mention /map-learn is optional"

    def test_all_command_templates_exist(self, templates_commands_dir):
        """Test that all 12 expected command template files exist."""
        expected_commands = [
            "map-check.md",  # Quality gates
            "map-debate.md",  # Multi-variant with Opus arbiter
            "map-debug.md",  # Debugging workflow
            "map-efficient.md",  # Recommended workflow
            "map-fast.md",  # Minimal workflow
            "map-learn.md",  # Optional learning
            "map-plan.md",  # Decomposition only
            "map-release.md",  # Release workflow
            "map-resume.md",  # Resume interrupted workflow
            "map-review.md",  # Code review
            "map-task.md",  # Single subtask execution
            "map-tdd.md",  # Test-first implementation
        ]

        for command in expected_commands:
            command_path = templates_commands_dir / command
            assert command_path.exists(), (
                f"Expected command template {command} not found in {templates_commands_dir}"
            )

        actual_commands = sorted(
            path.name for path in templates_commands_dir.glob("map-*.md")
        )
        assert sorted(expected_commands) == actual_commands

    def test_readme_lists_all_shipped_slash_commands(
        self, project_root, templates_commands_dir
    ):
        """README command table should mention every shipped slash command."""
        readme = (project_root / "README.md").read_text(encoding="utf-8")
        commands = [path.stem for path in templates_commands_dir.glob("map-*.md")]

        for command in commands:
            assert f"`/{command}`" in readme, f"README missing /{command}"

    def test_readme_mentions_canonical_flows(self, project_root):
        """README should document the standard and TDD canonical flows."""
        readme = (project_root / "README.md").read_text(encoding="utf-8")

        assert (
            "/map-plan` -> `/map-efficient` -> `/map-check` -> `/map-review" in readme
        )
        assert "/map-plan` -> `/map-tdd` -> `/map-check` -> `/map-review" in readme

    def test_usage_mentions_targeted_subtask_tdd_flow(self, project_root):
        """Usage guide should document the targeted subtask TDD flow."""
        content = (project_root / "docs" / "USAGE.md").read_text(encoding="utf-8")

        assert "/map-tdd ST-001" in content
        assert "/map-task ST-001" in content

    def test_cli_reference_json_matches_root_commands(self, project_root):
        """Machine-readable CLI reference should match root CLI commands."""
        reference = json.loads(
            (project_root / "docs" / "CLI_REFERENCE.json").read_text(encoding="utf-8")
        )
        root_commands = set(reference["commands"]["root"]["commands"].keys())
        assert root_commands == {"init", "check", "doctor", "upgrade"}

    def test_cli_reference_markdown_mentions_all_root_commands(self, project_root):
        """Human-readable CLI reference should stay aligned with root commands."""
        content = (project_root / "docs" / "CLI_COMMAND_REFERENCE.md").read_text(
            encoding="utf-8"
        )
        for command in [
            "mapify init",
            "mapify check",
            "mapify doctor",
            "mapify upgrade",
        ]:
            assert command in content

    def test_map_fast_workflow_structure(self, templates_commands_dir):
        """Test that map-fast.md has correct workflow structure (minimal agents)."""
        map_fast = templates_commands_dir / "map-fast.md"
        content = map_fast.read_text()

        # Should mention TaskDecomposer, Actor, Monitor
        assert "TaskDecomposer" in content or "task-decomposer" in content
        assert "Actor" in content or "actor" in content
        assert "Monitor" in content or "monitor" in content

        # Check that Reflector is mentioned as SKIPPED
        assert "reflector" in content.lower(), "Should mention Reflector (as skipped)"
        assert "skipped" in content.lower() or "no learning" in content.lower(), (
            "Should indicate learning is skipped"
        )

    def test_map_efficient_workflow_structure(self, templates_commands_dir):
        """Test that map-efficient.md has correct workflow structure (optional learning)."""
        map_efficient = templates_commands_dir / "map-efficient.md"
        content = map_efficient.read_text()

        # Should mention key agents
        assert "TaskDecomposer" in content or "task-decomposer" in content
        assert "Actor" in content or "actor" in content
        assert "Monitor" in content or "monitor" in content
        assert "Predictor" in content or "predictor" in content

        # Should mention /map-learn as optional
        assert "/map-learn" in content, "Should reference optional /map-learn command"

        # Should mention conditional Predictor
        assert "conditional" in content.lower()

    def test_map_fast_token_savings_mentioned(self, templates_commands_dir):
        """Test that map-fast.md mentions token savings percentage."""
        map_fast = templates_commands_dir / "map-fast.md"
        content = map_fast.read_text()

        # Should mention 40-50% savings
        assert (
            "40" in content
            and "50" in content
            and ("%" in content or "percent" in content.lower())
        )

    def test_map_efficient_is_token_efficient(self, templates_commands_dir):
        """Test that map-efficient.md describes itself as token-efficient."""
        map_efficient = templates_commands_dir / "map-efficient.md"
        content = map_efficient.read_text()

        # Should describe itself as token-efficient in description
        assert "token-efficient" in content.lower() or "efficient" in content.lower(), (
            "Should describe itself as efficient"
        )

    def test_map_plan_writes_human_artifacts(self, templates_commands_dir):
        """/map-plan should maintain branch-scoped human-readable artifacts."""
        content = (templates_commands_dir / "map-plan.md").read_text()

        assert "research.md" in content
        assert "implementation-plan.md" in content
        assert "decision-log.md" in content
        assert "pr-draft.md" in content
        assert "plan-review-00N.md" in content
        assert "plan-gate.json" in content

    def test_map_efficient_tracks_review_loop_artifacts(self, templates_commands_dir):
        """/map-efficient should preserve review/devlog/qa artifacts in branch workspace."""
        content = (templates_commands_dir / "map-efficient.md").read_text()

        assert "devlog-001.md" in content
        assert "session-log.md" in content
        assert "code-review-001.md" in content
        assert "qa-001.md" in content
        assert "code-review-XXX.md" in content

    def test_map_tdd_uses_shared_execution_artifacts(self, templates_commands_dir):
        """/map-tdd should reuse the same branch-scoped artifact model as map-efficient."""
        content = (templates_commands_dir / "map-tdd.md").read_text()

        assert "code-review-00N.md" in content
        assert "session-log.md" in content
        assert "pr-draft.md" in content

    def test_map_task_uses_shared_execution_artifacts(self, templates_commands_dir):
        """/map-task should keep using shared branch execution artifacts."""
        content = (templates_commands_dir / "map-task.md").read_text()

        assert "code-review-00N.md" in content
        assert "session-log.md" in content
        assert "qa-001.md" in content

    def test_map_check_writes_verification_summary(self, templates_commands_dir):
        """/map-check should produce a human-readable verification summary artifact."""
        content = (templates_commands_dir / "map-check.md").read_text()

        assert "verification-summary.md" in content
        assert "READY FOR REVIEW" in content
        assert "NEEDS WORK" in content

    def test_map_resume_reads_human_artifact_history(self, templates_commands_dir):
        """/map-resume should use session and verification artifacts for handoff."""
        content = (templates_commands_dir / "map-resume.md").read_text()

        assert "session-log.md" in content
        assert "verification-summary.md" in content

    def test_map_check_rebuilds_pr_draft_from_handoff_bundle(
        self, templates_commands_dir
    ):
        """/map-check should rebuild PR draft from deterministic artifact bundle."""
        content = (templates_commands_dir / "map-check.md").read_text()

        assert "build_handoff_bundle" in content
        assert "write_pr_draft" in content

    def test_map_review_refreshes_pr_draft(self, templates_commands_dir):
        """/map-review should refresh PR handoff after review verdict."""
        content = (templates_commands_dir / "map-review.md").read_text()

        assert "build_handoff_bundle" in content
        assert "pr-draft.md" in content
        assert "code-review-00N.md" in content
        assert "write_stage_gate" in content
        assert "build_review_handoff" in content
        assert "active-issues.json" in content

    def test_map_resume_is_briefing_oriented(self, templates_commands_dir):
        """/map-resume should surface resume briefing and next action guidance."""
        content = (templates_commands_dir / "map-resume.md").read_text()

        assert "Resume Briefing" in content
        assert "Immediate next action" in content
        assert "Do not improvise a new plan" in content

    def test_map_check_records_run_summaries_and_known_issues(
        self, templates_commands_dir
    ):
        """/map-check should mention run summaries and known issues accounting."""
        content = (templates_commands_dir / "map-check.md").read_text()

        assert "diagnostics.py summarize" in content
        assert "known-issues.json" in content
        assert "add_known_issue" in content
        assert "runs/<timestamp>/RESULTS.md" in content
        assert "write_stage_gate" in content
        assert "replace_active_issues" in content


class TestMapReviewStructure:
    """Test structural properties of the map-review command template."""

    @pytest.fixture
    def project_root(self):
        return Path(__file__).parent.parent

    @pytest.fixture
    def templates_commands_dir(self, project_root):
        return project_root / "src" / "mapify_cli" / "templates" / "commands"

    @pytest.fixture
    def review_content(self, templates_commands_dir):
        return (templates_commands_dir / "map-review.md").read_text()

    def test_has_frontmatter(self, review_content):
        """map-review.md starts with YAML frontmatter containing description."""
        assert review_content.startswith("---")
        assert "description:" in review_content[:200]

    def test_has_arguments_placeholder(self, review_content):
        """Command references $ARGUMENTS for user input."""
        assert "$ARGUMENTS" in review_content

    def test_has_review_section_protocol(self, review_content):
        """Review Section Protocol is defined once and referenced by sections."""
        assert "Review Section Protocol" in review_content

    def test_has_four_section_headings(self, review_content):
        """All 4 review sections are present."""
        assert "Section 1: Architecture" in review_content
        assert "Section 2: Code Quality" in review_content
        assert "Section 3: Tests" in review_content
        assert "Section 4: Performance" in review_content

    @pytest.mark.parametrize("prefix", ["ARCH", "QUALITY", "TESTS", "PERF"])
    def test_section_prefixes_present(self, review_content, prefix):
        """Each section defines its issue prefix."""
        assert prefix in review_content

    @pytest.mark.parametrize(
        "section,source",
        [
            ("Section 1: Architecture", "Predictor"),
            ("Section 2: Code Quality", "Monitor"),
            ("Section 3: Tests", "Monitor"),
            ("Section 4: Performance", "Monitor"),
        ],
    )
    def test_primary_source_mapping(self, review_content, section, source):
        """Each section references its primary source agent."""
        # Find the section and check the source is mentioned nearby
        idx = review_content.index(section)
        section_block = review_content[idx : idx + 500]
        assert source in section_block, (
            f"{section} should reference {source} as primary source"
        )

    def test_three_agent_task_calls(self, review_content):
        """Command includes Task calls for all 3 agents."""
        assert 'subagent_type="monitor"' in review_content
        assert 'subagent_type="predictor"' in review_content
        assert 'subagent_type="evaluator"' in review_content

    def test_ci_mode_flag(self, review_content):
        """Command documents --ci flag for CI mode."""
        assert "--ci" in review_content

    def test_ask_user_question_mentioned(self, review_content):
        """Command uses AskUserQuestion for interactive presentation."""
        assert "AskUserQuestion" in review_content

    def test_review_preferences_section(self, review_content):
        """Command includes Review Preferences section."""
        assert "Review Preferences" in review_content

    def test_schema_documentation(self, review_content):
        """Command documents expected agent output schemas."""
        assert "Expected Agent Output Schemas" in review_content

    def test_map_learn_suggestion(self, review_content):
        """Command suggests /map-learn for preserving review learnings."""
        assert "/map-learn" in review_content

    def test_parallel_execution_instruction(self, review_content):
        """Command instructs parallel execution of agents."""
        content_lower = review_content.lower()
        assert "parallel" in content_lower

    def test_previous_section_summary(self, review_content):
        """Command instructs summarizing decisions before next section."""
        assert (
            "Summarize decisions" in review_content
            or "summarize" in review_content.lower()
        )


class TestMapReviewVerdictLogic:
    """Test verdict logic conditions in map-review command."""

    @pytest.fixture
    def project_root(self):
        return Path(__file__).parent.parent

    @pytest.fixture
    def templates_commands_dir(self, project_root):
        return project_root / "src" / "mapify_cli" / "templates" / "commands"

    @pytest.fixture
    def review_content(self, templates_commands_dir):
        return (templates_commands_dir / "map-review.md").read_text()

    def test_proceed_conditions(self, review_content):
        """PROCEED requires Monitor approved + Evaluator proceed."""
        assert "PROCEED" in review_content
        assert "Monitor.verdict" in review_content
        assert "'approved'" in review_content
        assert "Evaluator.recommendation" in review_content
        assert "'proceed'" in review_content

    def test_revise_conditions(self, review_content):
        """REVISE triggered by needs_revision or improve."""
        assert "REVISE" in review_content
        assert "'needs_revision'" in review_content
        assert "'improve'" in review_content

    def test_block_conditions(self, review_content):
        """BLOCK triggered by rejected, reconsider, or critical thresholds."""
        assert "BLOCK" in review_content
        assert "'rejected'" in review_content
        assert "'reconsider'" in review_content

    def test_block_security_threshold(self, review_content):
        """BLOCK includes security score < 5 condition."""
        assert "security < 5" in review_content or "security<5" in review_content

    def test_block_functionality_threshold(self, review_content):
        """BLOCK includes functionality score < 5 condition."""
        assert (
            "functionality < 5" in review_content or "functionality<5" in review_content
        )

    def test_block_predictor_risk(self, review_content):
        """BLOCK includes high risk + breaking changes condition."""
        assert "risk_assessment" in review_content
        assert "breaking_changes" in review_content

    def test_priority_ordering(self, review_content):
        """Verdict priority is BLOCK > REVISE > PROCEED."""
        assert "BLOCK > REVISE > PROCEED" in review_content

    def test_references_monitor_valid(self, review_content):
        """Verdict references Monitor.valid field."""
        assert "Monitor.valid" in review_content

    def test_references_evaluator_overall_score(self, review_content):
        """Verdict section references Evaluator overall_score."""
        assert "overall_score" in review_content

    def test_references_predictor_risk_assessment(self, review_content):
        """Verdict references Predictor risk_assessment."""
        assert "Predictor.risk_assessment" in review_content or (
            "Predictor" in review_content and "risk_assessment" in review_content
        )


class TestAgentSchemaFieldsPresent:
    """Test that agent template files contain expected schema fields."""

    @pytest.fixture
    def project_root(self):
        return Path(__file__).parent.parent

    @pytest.fixture
    def claude_agents_dir(self, project_root):
        """Use .claude/agents/ (development source) for field verification."""
        return project_root / ".claude" / "agents"

    def test_monitor_has_valid_field(self, claude_agents_dir):
        """Monitor agent template contains 'valid' field."""
        content = (claude_agents_dir / "monitor.md").read_text()
        assert "valid" in content

    def test_monitor_has_issues_field(self, claude_agents_dir):
        """Monitor agent template contains 'issues' field."""
        content = (claude_agents_dir / "monitor.md").read_text()
        assert "issues" in content

    def test_predictor_has_risk_assessment(self, claude_agents_dir):
        """Predictor agent template contains 'risk_assessment' field."""
        content = (claude_agents_dir / "predictor.md").read_text()
        assert "risk_assessment" in content

    def test_predictor_has_breaking_changes(self, claude_agents_dir):
        """Predictor agent template contains 'breaking_changes' field."""
        content = (claude_agents_dir / "predictor.md").read_text()
        assert "breaking_changes" in content

    def test_evaluator_has_scores(self, claude_agents_dir):
        """Evaluator agent template contains 'scores' field."""
        content = (claude_agents_dir / "evaluator.md").read_text()
        assert "scores" in content

    def test_evaluator_has_recommendation(self, claude_agents_dir):
        """Evaluator agent template contains 'recommendation' field."""
        content = (claude_agents_dir / "evaluator.md").read_text()
        assert "recommendation" in content
