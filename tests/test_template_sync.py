"""
Tests for template synchronization between .claude/agents/ and src/mapify_cli/templates/agents/.

This test ensures that agent templates are always in sync between the development
directory (.claude/agents/) and the distribution templates (src/mapify_cli/templates/agents/).

When templates are out of sync:
- New users running 'mapify init' get outdated templates
- Development and production behavior diverge
- This violates the project's template synchronization requirements

See .claude/CLAUDE.md for the template synchronization process.
"""

import filecmp
import pytest
from pathlib import Path


class TestTemplateSynchronization:
    """Test that agent templates are synchronized between .claude/ and templates/."""

    @pytest.fixture
    def project_root(self):
        """Get project root directory."""
        return Path(__file__).parent.parent

    @pytest.fixture
    def claude_agents_dir(self, project_root):
        """Get .claude/agents directory (development source)."""
        return project_root / ".claude" / "agents"

    @pytest.fixture
    def templates_agents_dir(self, project_root):
        """Get src/mapify_cli/templates/agents directory (distribution target)."""
        return project_root / "src" / "mapify_cli" / "templates" / "agents"

    @pytest.fixture
    def expected_agents(self):
        """List of expected agent template files."""
        return [
            "actor.md",
            "monitor.md",
            "predictor.md",
            "evaluator.md",
            "curator.md",
            "reflector.md",
            "task-decomposer.md",
            "documentation-reviewer.md",
        ]

    def test_all_agents_exist_in_both_directories(
        self, claude_agents_dir, templates_agents_dir, expected_agents
    ):
        """Test that all expected agent files exist in both directories."""
        for agent in expected_agents:
            claude_file = claude_agents_dir / agent
            template_file = templates_agents_dir / agent

            assert claude_file.exists(), (
                f"{agent} missing from .claude/agents/. " f"Expected at: {claude_file}"
            )
            assert template_file.exists(), (
                f"{agent} missing from templates/agents/. "
                f"Run: cp .claude/agents/{agent} src/mapify_cli/templates/agents/"
            )

    def test_no_orphaned_files_in_templates(
        self, claude_agents_dir, templates_agents_dir
    ):
        """Test that templates/ doesn't have files that don't exist in .claude/agents/."""
        if not templates_agents_dir.exists():
            pytest.skip("Templates directory doesn't exist")

        claude_files = (
            {f.name for f in claude_agents_dir.glob("*.md")}
            if claude_agents_dir.exists()
            else set()
        )
        template_files = {f.name for f in templates_agents_dir.glob("*.md")}

        orphaned = template_files - claude_files
        assert not orphaned, (
            f"Orphaned files in templates/agents/ that don't exist in .claude/agents/: {orphaned}. "
            f"These files should be removed from src/mapify_cli/templates/agents/"
        )

    def test_no_missing_files_in_templates(
        self, claude_agents_dir, templates_agents_dir
    ):
        """Test that all files from .claude/agents/ exist in templates/."""
        if not claude_agents_dir.exists():
            pytest.skip(".claude/agents/ directory doesn't exist")

        claude_files = {f.name for f in claude_agents_dir.glob("*.md")}
        template_files = (
            {f.name for f in templates_agents_dir.glob("*.md")}
            if templates_agents_dir.exists()
            else set()
        )

        missing = claude_files - template_files
        assert not missing, (
            f"Files in .claude/agents/ missing from templates/agents/: {missing}. "
            f"Run: cp .claude/agents/{{file}} src/mapify_cli/templates/agents/"
        )

    @pytest.mark.parametrize(
        "agent",
        [
            "actor.md",
            "monitor.md",
            "predictor.md",
            "evaluator.md",
            "curator.md",
            "reflector.md",
            "task-decomposer.md",
            "documentation-reviewer.md",
        ],
    )
    def test_agent_content_matches(
        self, claude_agents_dir, templates_agents_dir, agent
    ):
        """Test that agent file content is identical between directories."""
        claude_file = claude_agents_dir / agent
        template_file = templates_agents_dir / agent

        if not claude_file.exists() or not template_file.exists():
            pytest.skip(f"{agent} doesn't exist in both directories")

        assert filecmp.cmp(claude_file, template_file, shallow=False), (
            f"{agent} content differs between .claude/agents/ and templates/agents/. "
            f"Run: cp .claude/agents/{agent} src/mapify_cli/templates/agents/"
        )

    def test_file_count_matches(self, claude_agents_dir, templates_agents_dir):
        """Test that both directories have the same number of .md files."""
        if not claude_agents_dir.exists() or not templates_agents_dir.exists():
            pytest.skip("One or both directories don't exist")

        claude_count = len(list(claude_agents_dir.glob("*.md")))
        template_count = len(list(templates_agents_dir.glob("*.md")))

        assert claude_count == template_count, (
            f"File count mismatch: .claude/agents/ has {claude_count} files, "
            f"templates/agents/ has {template_count} files. "
            f"Ensure all agents are synchronized."
        )

    def test_agent_frontmatter_no_deleted_changelog(
        self, claude_agents_dir, expected_agents
    ):
        """Test that agent frontmatter doesn't reference deleted CHANGELOG.md."""
        for agent in expected_agents:
            agent_file = claude_agents_dir / agent
            if not agent_file.exists():
                continue

            content = agent_file.read_text()
            # Check frontmatter (between first two ---)
            if content.startswith("---"):
                frontmatter_end = content.find("---", 4)
                if frontmatter_end > 0:
                    frontmatter = content[4:frontmatter_end]
                    assert "changelog:" not in frontmatter.lower(), (
                        f"{agent} has 'changelog:' in frontmatter pointing to deleted file. "
                        f"Remove the changelog field from the frontmatter."
                    )
