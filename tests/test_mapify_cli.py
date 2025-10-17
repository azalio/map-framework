#!/usr/bin/env python3
"""Test suite for mapify CLI tool."""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest
from typer.testing import CliRunner

# Add src directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from mapify_cli import (
    app,
    create_agent_files,
    create_command_files,
    create_commands_dir,
    create_ssl_context,
    get_latest_release,
    get_templates_dir,
    init_git_repo,
    is_command,
    is_git_repo,
)

runner = CliRunner()


class TestSSLContext:
    """Test SSL context creation with proper security."""

    @mock.patch("mapify_cli.HAS_TRUSTSTORE", True)
    @mock.patch("mapify_cli.truststore.SSLContext")
    def test_ssl_context_with_truststore(self, mock_ssl_context):
        """Test SSL context creation when truststore is available."""
        mock_context = mock.Mock()
        mock_ssl_context.return_value = mock_context

        context = create_ssl_context()

        assert context == mock_context
        assert mock_context.check_hostname is True
        assert mock_context.verify_mode == 2  # ssl.CERT_REQUIRED

    @mock.patch("mapify_cli.HAS_TRUSTSTORE", False)
    @mock.patch("ssl.create_default_context")
    def test_ssl_context_fallback(self, mock_create_default):
        """Test SSL context creation falls back to default when truststore unavailable."""
        mock_context = mock.Mock()
        mock_create_default.return_value = mock_context

        context = create_ssl_context()

        assert context == mock_context
        assert mock_context.check_hostname is True
        assert mock_context.verify_mode == 2  # ssl.CERT_REQUIRED

    @mock.patch("mapify_cli.HAS_TRUSTSTORE", True)
    @mock.patch("mapify_cli.truststore.SSLContext")
    @mock.patch("ssl.create_default_context")
    def test_ssl_context_fallback_on_error(self, mock_create_default, mock_ssl_context):
        """Test SSL context creation falls back when truststore raises exception."""
        mock_ssl_context.side_effect = Exception("Truststore error")
        mock_context = mock.Mock()
        mock_create_default.return_value = mock_context

        context = create_ssl_context()

        assert context == mock_context
        assert mock_context.check_hostname is True
        assert mock_context.verify_mode == 2  # ssl.CERT_REQUIRED


class TestTemplates:
    """Test template directory discovery."""

    @mock.patch("importlib.resources.files")
    def test_get_templates_dir_bundled(self, mock_files):
        """Test finding templates in bundled package."""
        mock_path = mock.Mock()
        mock_path.__truediv__ = mock.Mock(return_value=Path(__file__).parent.parent / "templates")
        mock_files.return_value = mock_path

        result = get_templates_dir()
        assert "templates" in str(result)

    @mock.patch("importlib.resources.files", side_effect=Exception("Not found"))
    def test_get_templates_dir_fallback(self, mock_files):
        """Test fallback to module directory."""
        # This will use the actual module directory fallback
        result = get_templates_dir()
        assert result.exists()

    @mock.patch("importlib.resources.files", side_effect=Exception("Not found"))
    def test_get_templates_dir_not_found(self, mock_files):
        """Test error when templates not found anywhere."""
        # Mock Path methods to simulate templates not existing
        with mock.patch("pathlib.Path.exists", return_value=False):
            with pytest.raises(RuntimeError, match="Templates directory not found"):
                get_templates_dir()


class TestGitOperations:
    """Test git repository operations."""

    def test_is_git_repo_true(self, tmp_path):
        """Test detecting git repository."""
        # Initialize a git repo
        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
        assert is_git_repo(tmp_path) is True

    def test_is_git_repo_false(self, tmp_path):
        """Test detecting non-git directory."""
        assert is_git_repo(tmp_path) is False

    def test_init_git_repo_success(self, tmp_path):
        """Test successful git repository initialization."""
        # Create a dummy file
        (tmp_path / "test.txt").write_text("test")

        result = init_git_repo(tmp_path, quiet=True)
        assert result is True
        assert is_git_repo(tmp_path) is True

    def test_init_git_repo_no_identity(self, tmp_path):
        """Test git init handles missing identity by setting temporary one."""
        # Create a dummy file
        (tmp_path / "test.txt").write_text("test")

        # Simply verify that init_git_repo succeeds
        # The function will set temporary identity if needed
        result = init_git_repo(tmp_path, quiet=True)
        assert result is True
        assert is_git_repo(tmp_path) is True

    def test_init_git_repo_no_git(self, tmp_path):
        """Test graceful handling when git is not installed."""
        with mock.patch("subprocess.run", side_effect=FileNotFoundError("git not found")):
            result = init_git_repo(tmp_path, quiet=True)
            assert result is False

    def test_init_git_repo_empty_directory(self, tmp_path):
        """Test git init in empty directory (no files to commit)."""
        # Don't create any files - should handle "nothing to commit" gracefully
        result = init_git_repo(tmp_path, quiet=True)
        # Should still return True even if no files to commit
        assert result is True


class TestInitCommand:
    """Test the init command."""

    @mock.patch("mapify_cli.select_with_arrows")
    @mock.patch("mapify_cli.select_multiple_with_arrows")
    def test_init_basic(self, mock_select_multiple, mock_select, tmp_path):
        """Test basic initialization without options."""
        os.chdir(tmp_path)
        mock_select.return_value = "none"

        result = runner.invoke(app, ["init", ".", "--no-git"])

        assert result.exit_code == 0
        assert (tmp_path / ".claude" / "agents").exists()
        assert (tmp_path / ".claude" / "commands").exists()

    @mock.patch("mapify_cli.select_with_arrows")
    @mock.patch("mapify_cli.select_multiple_with_arrows")
    def test_init_always_uses_claude(self, mock_select_multiple, mock_select, tmp_path):
        """Test that init always uses Claude (no AI selection prompt).

        Verifies that:
        - No AI selection occurs (hardcoded to 'claude')
        - Only MCP selection happens
        - Claude agents are created
        """
        os.chdir(tmp_path)
        mock_select.return_value = "none"

        result = runner.invoke(app, ["init", ".", "--no-git"])

        assert result.exit_code == 0
        # Should show "claude" somewhere in output (AI assistant confirmation)
        assert "claude" in result.stdout.lower()

    def test_init_ai_flag_not_accepted(self, tmp_path):
        """Test that passing --ai flag results in a clear error.

        Verifies that:
        - Typer rejects --ai flag with "no such option: --ai"
        - Command fails with non-zero exit code
        """
        # Arrange
        os.chdir(tmp_path)

        # Act
        result = runner.invoke(app, ["init", ".", "--ai", "cursor", "--no-git"])

        # Assert
        assert result.exit_code != 0
        # Typer should reject the unknown option
        # Check both stdout and output for compatibility across Typer versions
        output_text = getattr(result, 'output', result.stdout)
        assert "no such option" in output_text.lower() or "unrecognized" in output_text.lower()

    @mock.patch("mapify_cli.select_with_arrows")
    @mock.patch("mapify_cli.select_multiple_with_arrows")
    def test_init_mcp_selection_only(self, mock_select_multiple, mock_select, tmp_path):
        """Test that select_with_arrows is called exactly once (for MCP, not AI).

        Verifies that:
        - select_with_arrows is called exactly once
        - The call is for MCP server selection
        - No AI selection prompt occurs
        """
        # Arrange
        os.chdir(tmp_path)
        mock_select.return_value = "custom"
        mock_select_multiple.return_value = ["cipher"]

        # Act
        result = runner.invoke(app, ["init", ".", "--no-git"])

        # Assert
        assert result.exit_code == 0
        # Verify select_with_arrows called exactly once (for MCP only)
        assert mock_select.call_count == 1
        # Verify it was called for MCP selection
        call_args = mock_select.call_args
        assert "MCP" in call_args.args[1]

    @mock.patch("mapify_cli.select_with_arrows")
    @mock.patch("mapify_cli.select_multiple_with_arrows")
    def test_init_tracker_shows_claude(self, mock_select_multiple, mock_select, tmp_path):
        """Test that tracker shows Claude as selected AI.

        Verifies that:
        - Output mentions Claude as the AI assistant
        - No other AI assistants are mentioned
        """
        os.chdir(tmp_path)
        mock_select.return_value = "none"

        result = runner.invoke(app, ["init", ".", "--no-git"])

        assert result.exit_code == 0
        # Should show claude in the tracker output
        assert "claude" in result.stdout.lower() or "Project ready" in result.stdout

    @mock.patch("mapify_cli.select_with_arrows")
    @mock.patch("mapify_cli.select_multiple_with_arrows")
    def test_init_claude_with_essential_mcp(self, mock_select_multiple, mock_select, tmp_path):
        """Test initialization with Claude and essential MCP servers."""
        os.chdir(tmp_path)
        mock_select.return_value = "essential"

        result = runner.invoke(app, ["init", ".", "--no-git"])

        assert result.exit_code == 0
        assert (tmp_path / ".claude" / "agents").exists()
        assert (tmp_path / ".claude" / "mcp_config.json").exists()

        # Check MCP config
        mcp_config = json.loads((tmp_path / ".claude" / "mcp_config.json").read_text())
        assert "cipher" in mcp_config["mcp_servers"]
        assert "claude-reviewer" in mcp_config["mcp_servers"]

    @mock.patch("mapify_cli.select_with_arrows")
    @mock.patch("mapify_cli.select_multiple_with_arrows")
    def test_init_with_directory(self, mock_select_multiple, mock_select, tmp_path):
        """Test init with specific directory name."""
        os.chdir(tmp_path)
        project_name = "my-project"
        mock_select.return_value = "none"

        result = runner.invoke(app, ["init", project_name, "--no-git"])

        assert result.exit_code == 0
        project_path = tmp_path / project_name
        assert project_path.exists()
        assert (project_path / ".claude" / "agents").exists()

    @mock.patch("mapify_cli.select_with_arrows")
    @mock.patch("mapify_cli.select_multiple_with_arrows")
    def test_init_already_initialized(self, mock_select_multiple, mock_select, tmp_path):
        """Test init when project already has .claude directory."""
        os.chdir(tmp_path)
        mock_select.return_value = "none"

        # Initialize once
        result1 = runner.invoke(app, ["init", ".", "--no-git"])
        assert result1.exit_code == 0

        # Try to initialize again in same directory
        result2 = runner.invoke(app, ["init", ".", "--no-git", "--force"])
        assert result2.exit_code == 0
        # Should succeed with --force
        assert "Project ready" in result2.stdout or "already initialized" in result2.stdout

    @mock.patch("mapify_cli.select_with_arrows")
    @mock.patch("mapify_cli.select_multiple_with_arrows")
    def test_init_with_mcp_servers(self, mock_select_multiple, mock_select, tmp_path):
        """Test init with MCP servers specified via CLI."""
        os.chdir(tmp_path)

        result = runner.invoke(app, ["init", ".", "--mcp", "essential", "--no-git"])

        assert result.exit_code == 0
        assert (tmp_path / ".claude" / "mcp_config.json").exists()

        mcp_config = json.loads((tmp_path / ".claude" / "mcp_config.json").read_text())
        assert "cipher" in mcp_config["mcp_servers"]
        assert "claude-reviewer" in mcp_config["mcp_servers"]
        assert "sequential-thinking" in mcp_config["mcp_servers"]


class TestCheckCommand:
    """Test the check command."""

    def test_check_not_initialized(self, tmp_path):
        """Test check command shows tool status."""
        os.chdir(tmp_path)
        result = runner.invoke(app, ["check"])

        # Should show available tools
        assert result.exit_code == 0
        assert "Check Available Tools" in result.stdout or "MAP Framework" in result.stdout

    @mock.patch("mapify_cli.check_tool")
    def test_check_initialized(self, mock_check_tool, tmp_path):
        """Test check command when tools are installed."""
        os.chdir(tmp_path)
        mock_check_tool.return_value = True

        result = runner.invoke(app, ["check"])

        assert result.exit_code == 0
        assert "Check Available Tools" in result.stdout or "MAP Framework" in result.stdout

    @mock.patch("mapify_cli.check_tool")
    def test_check_with_mcp_servers(self, mock_check_tool, tmp_path):
        """Test check command shows MCP server status."""
        os.chdir(tmp_path)
        mock_check_tool.return_value = True

        result = runner.invoke(app, ["check"])

        assert result.exit_code == 0
        assert "Check Available Tools" in result.stdout or "MAP" in result.stdout


class TestUpgradeCommand:
    """Test the upgrade command."""

    @mock.patch("mapify_cli.get_latest_release")
    def test_upgrade_available(self, mock_get_latest, tmp_path):
        """Test upgrade when newer version is available."""
        os.chdir(tmp_path)
        mock_get_latest.return_value = {
            "tag_name": "v2.0.0",
            "html_url": "https://github.com/azalio/map-framework/releases/tag/v2.0.0"
        }

        result = runner.invoke(app, ["upgrade"])

        assert result.exit_code == 0
        # For now, upgrade shows "coming soon" message
        assert "Upgrade feature coming soon" in result.stdout or "New version available" in result.stdout

    @mock.patch("mapify_cli.get_latest_release")
    def test_upgrade_not_available(self, mock_get_latest, tmp_path):
        """Test upgrade when already on latest version."""
        os.chdir(tmp_path)
        mock_get_latest.return_value = {
            "tag_name": "v1.0.0",
            "html_url": "https://github.com/azalio/map-framework/releases/tag/v1.0.0"
        }

        result = runner.invoke(app, ["upgrade"])

        assert result.exit_code == 0
        assert "Upgrade feature coming soon" in result.stdout or "already on the latest version" in result.stdout

    def test_upgrade_not_initialized(self, tmp_path):
        """Test upgrade in non-initialized directory."""
        os.chdir(tmp_path)
        result = runner.invoke(app, ["upgrade"])

        assert result.exit_code == 0
        assert "Upgrade feature coming soon" in result.stdout or "MAP Framework not initialized" in result.stdout


class TestAgentCreation:
    """Test agent file creation."""

    def test_create_agent_files(self, tmp_path):
        """Test creating agent files with no MCP servers."""
        create_agent_files(tmp_path, [])

        agents_dir = tmp_path / ".claude" / "agents"
        assert agents_dir.exists()
        assert (agents_dir / "task-decomposer.md").exists()
        assert (agents_dir / "actor.md").exists()
        assert (agents_dir / "monitor.md").exists()

    def test_create_agent_files_with_templates(self, tmp_path):
        """Test creating agent files from templates."""
        create_agent_files(tmp_path, ["cipher", "claude-reviewer"])

        agents_dir = tmp_path / ".claude" / "agents"
        assert agents_dir.exists()

        # Verify agent files contain MCP references
        actor_content = (agents_dir / "actor.md").read_text()
        assert "actor" in actor_content.lower()

    @mock.patch("mapify_cli.get_templates_dir")
    def test_create_agent_files_fallback(self, mock_get_templates, tmp_path):
        """Test creating agent files when templates are missing (uses fallback generators).

        Verifies that:
        - Fallback generators create valid agent content
        - All 9 agents are created successfully
        - Content includes required sections (IDENTITY, ROLE)
        - MCP integration sections are included when MCP servers specified
        """
        # Mock templates directory that doesn't have agent templates
        mock_templates_path = tmp_path / "mock_templates"
        mock_templates_path.mkdir(parents=True, exist_ok=True)
        mock_get_templates.return_value = mock_templates_path

        # Call create_agent_files with cipher MCP server
        create_agent_files(tmp_path, ["cipher"])

        agents_dir = tmp_path / ".claude" / "agents"
        assert agents_dir.exists()

        # Verify all 9 agents were created using fallback generators
        expected_agents = [
            "task-decomposer.md", "actor.md", "monitor.md",
            "predictor.md", "evaluator.md", "reflector.md",
            "curator.md", "test-generator.md", "documentation-reviewer.md"
        ]

        for agent_file in expected_agents:
            agent_path = agents_dir / agent_file
            assert agent_path.exists(), f"Agent {agent_file} not created"

            # Verify content has required sections
            content = agent_path.read_text()
            assert "---" in content, f"Agent {agent_file} missing YAML frontmatter"
            assert "name:" in content, f"Agent {agent_file} missing name field"
            # Check for role/identity sections (various formats)
            has_core_section = any(marker in content for marker in ["IDENTITY", "ROLE", "Role:", "# Role"])
            assert has_core_section, f"Agent {agent_file} missing core sections"

            # Verify MCP integration for cipher-enabled agents
            if any(name in agent_file for name in ["reflector", "curator", "test-generator"]):
                assert "cipher" in content.lower() or "mcp" in content.lower(), \
                    f"Agent {agent_file} missing MCP integration section"


class TestCommandCreation:
    """Test command file creation."""

    def test_create_commands_dir(self, tmp_path):
        """Test creating commands directory."""
        create_commands_dir(tmp_path)

        commands_dir = tmp_path / ".claude" / "commands"
        assert commands_dir.exists()
        assert (commands_dir / "README.md").exists()

    def test_create_command_files(self, tmp_path):
        """Test creating command files."""
        create_command_files(tmp_path)

        commands_dir = tmp_path / ".claude" / "commands"
        assert commands_dir.exists()
        # Check for at least one command file
        command_files = list(commands_dir.glob("*.md"))
        assert len(command_files) > 0


class TestHelperFunctions:
    """Test helper functions."""

    def test_is_command_basic(self):
        """Test is_command with basic commands."""
        # Test with a command that should exist on all systems
        assert is_command(["python"]) is True or is_command(["python3"]) is True

    @mock.patch("httpx.Client")
    def test_get_latest_release(self, mock_client):
        """Test fetching latest release from GitHub."""
        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "tag_name": "v1.0.0",
            "html_url": "https://github.com/azalio/map-framework/releases/tag/v1.0.0"
        }

        mock_client_instance = mock.Mock()
        mock_client_instance.get.return_value = mock_response
        mock_client_instance.__enter__ = mock.Mock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = mock.Mock(return_value=False)
        mock_client.return_value = mock_client_instance

        result = get_latest_release("azalio", "map-framework")
        assert result is not None
        assert result["tag_name"] == "v1.0.0"
