"""
Tests for slash command templates.

Validates that workflow variant commands (map-fast, map-efficient) exist
and are properly formatted.
"""

import pytest
from pathlib import Path


class TestCommandTemplates:
    """Test command template existence and format."""

    @pytest.fixture
    def project_root(self):
        """Get project root directory."""
        return Path(__file__).parent.parent

    @pytest.fixture
    def claude_commands_dir(self, project_root):
        """Get .claude/commands directory."""
        return project_root / ".claude" / "commands"

    @pytest.fixture
    def templates_commands_dir(self, project_root):
        """Get src/mapify_cli/templates/commands directory."""
        return project_root / "src" / "mapify_cli" / "templates" / "commands"

    def test_map_fast_exists_in_claude(self, claude_commands_dir):
        """Test that map-fast.md exists in .claude/commands/."""
        map_fast = claude_commands_dir / "map-fast.md"
        assert map_fast.exists(), f"map-fast.md not found in {claude_commands_dir}"
        assert map_fast.is_file(), "map-fast.md should be a file"

    def test_map_efficient_exists_in_claude(self, claude_commands_dir):
        """Test that map-efficient.md exists in .claude/commands/."""
        map_efficient = claude_commands_dir / "map-efficient.md"
        assert map_efficient.exists(), f"map-efficient.md not found in {claude_commands_dir}"
        assert map_efficient.is_file(), "map-efficient.md should be a file"

    def test_map_fast_exists_in_templates(self, templates_commands_dir):
        """Test that map-fast.md exists in templates/commands/."""
        map_fast = templates_commands_dir / "map-fast.md"
        assert map_fast.exists(), f"map-fast.md not found in {templates_commands_dir}"
        assert map_fast.is_file(), "map-fast.md should be a file"

    def test_map_efficient_exists_in_templates(self, templates_commands_dir):
        """Test that map-efficient.md exists in templates/commands/."""
        map_efficient = templates_commands_dir / "map-efficient.md"
        assert map_efficient.exists(), f"map-efficient.md not found in {templates_commands_dir}"
        assert map_efficient.is_file(), "map-efficient.md should be a file"

    def test_map_fast_has_frontmatter(self, claude_commands_dir):
        """Test that map-fast.md has proper frontmatter with description."""
        map_fast = claude_commands_dir / "map-fast.md"
        content = map_fast.read_text()

        assert content.startswith("---"), "map-fast.md should start with frontmatter"
        assert "description:" in content[:200], "Frontmatter should contain description field"
        assert content.split("---")[1].strip(), "Frontmatter should not be empty"

    def test_map_efficient_has_frontmatter(self, claude_commands_dir):
        """Test that map-efficient.md has proper frontmatter with description."""
        map_efficient = claude_commands_dir / "map-efficient.md"
        content = map_efficient.read_text()

        assert content.startswith("---"), "map-efficient.md should start with frontmatter"
        assert "description:" in content[:200], "Frontmatter should contain description field"
        assert content.split("---")[1].strip(), "Frontmatter should not be empty"

    def test_map_fast_contains_warning(self, claude_commands_dir):
        """Test that map-fast.md contains prominent warnings about limitations."""
        map_fast = claude_commands_dir / "map-fast.md"
        content = map_fast.read_text()

        # Check for warning markers
        assert "⚠️" in content or "WARNING" in content, "map-fast.md should contain warning indicators"
        assert "NOT RECOMMENDED" in content.upper(), "map-fast.md should state NOT RECOMMENDED"
        assert "NO learning" in content or "no learning" in content, "Should mention no learning"

    def test_map_efficient_contains_recommended_label(self, claude_commands_dir):
        """Test that map-efficient.md contains RECOMMENDED label."""
        map_efficient = claude_commands_dir / "map-efficient.md"
        content = map_efficient.read_text()

        assert "RECOMMENDED" in content.upper(), "map-efficient.md should state RECOMMENDED"
        assert "⭐" in content or "recommended" in content.lower(), "Should have recommendation indicator"

    def test_templates_match_claude_commands(self, claude_commands_dir, templates_commands_dir):
        """Test that template files match .claude/commands files."""
        for command_file in ["map-fast.md", "map-efficient.md"]:
            claude_file = claude_commands_dir / command_file
            template_file = templates_commands_dir / command_file

            assert claude_file.exists(), f"{command_file} missing from .claude/commands"
            assert template_file.exists(), f"{command_file} missing from templates/commands"

            claude_content = claude_file.read_text()
            template_content = template_file.read_text()

            assert claude_content == template_content, (
                f"{command_file} differs between .claude/commands and templates/commands. "
                f"Run: cp .claude/commands/{command_file} src/mapify_cli/templates/commands/"
            )

    def test_all_commands_exist(self, claude_commands_dir):
        """Test that all expected command files exist."""
        expected_commands = [
            "map-feature.md",
            "map-debug.md",
            "map-refactor.md",
            "map-review.md",
            "map-efficient.md",  # New
            "map-fast.md",  # New
        ]

        for command in expected_commands:
            command_path = claude_commands_dir / command
            assert command_path.exists(), f"Expected command {command} not found"

    def test_map_fast_workflow_structure(self, claude_commands_dir):
        """Test that map-fast.md has correct workflow structure (minimal agents)."""
        map_fast = claude_commands_dir / "map-fast.md"
        content = map_fast.read_text()

        # Should mention TaskDecomposer, Actor, Monitor
        assert "TaskDecomposer" in content or "task-decomposer" in content
        assert "Actor" in content or "actor" in content
        assert "Monitor" in content or "monitor" in content

        # Check that Reflector/Curator are mentioned as SKIPPED
        assert "reflector" in content.lower(), "Should mention Reflector (as skipped)"
        assert "curator" in content.lower(), "Should mention Curator (as skipped)"
        assert "skipped" in content.lower() or "no learning" in content.lower(), "Should indicate learning is skipped"

    def test_map_efficient_workflow_structure(self, claude_commands_dir):
        """Test that map-efficient.md has correct workflow structure (batched learning)."""
        map_efficient = claude_commands_dir / "map-efficient.md"
        content = map_efficient.read_text()

        # Should mention all key agents
        assert "TaskDecomposer" in content or "task-decomposer" in content
        assert "Actor" in content or "actor" in content
        assert "Monitor" in content or "monitor" in content
        assert "Predictor" in content or "predictor" in content
        assert "Reflector" in content or "reflector" in content
        assert "Curator" in content or "curator" in content

        # Should mention batching
        assert "batch" in content.lower() or "batched" in content.lower()

        # Should mention conditional Predictor
        assert "conditional" in content.lower()

    def test_map_fast_token_savings_mentioned(self, claude_commands_dir):
        """Test that map-fast.md mentions token savings percentage."""
        map_fast = claude_commands_dir / "map-fast.md"
        content = map_fast.read_text()

        # Should mention 40-50% savings
        assert "40" in content and "50" in content and ("%" in content or "percent" in content.lower())

    def test_map_efficient_token_savings_mentioned(self, claude_commands_dir):
        """Test that map-efficient.md mentions token savings percentage."""
        map_efficient = claude_commands_dir / "map-efficient.md"
        content = map_efficient.read_text()

        # Should mention 30-40% savings
        assert "30" in content and "40" in content and ("%" in content or "percent" in content.lower())
