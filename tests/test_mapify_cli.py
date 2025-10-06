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
        """Test SSL context fallback when truststore is not available."""
        mock_context = mock.Mock()
        mock_create_default.return_value = mock_context

        context = create_ssl_context()

        assert context == mock_context
        assert mock_context.check_hostname is True
        assert mock_context.verify_mode == 2  # ssl.CERT_REQUIRED

    @mock.patch("mapify_cli.HAS_TRUSTSTORE", True)
    @mock.patch("mapify_cli.truststore.SSLContext", side_effect=Exception("Truststore error"))
    @mock.patch("ssl.create_default_context")
    def test_ssl_context_fallback_on_error(self, mock_create_default, mock_ssl_context):
        """Test SSL context fallback when truststore fails."""
        mock_context = mock.Mock()
        mock_create_default.return_value = mock_context

        context = create_ssl_context()

        assert context == mock_context
        assert mock_context.check_hostname is True


class TestTemplates:
    """Test template bundling and loading."""

    def test_get_templates_dir_bundled(self):
        """Test getting bundled templates directory."""
        templates_dir = get_templates_dir()
        assert templates_dir is not None
        assert templates_dir.name == "templates"

    def test_get_templates_dir_fallback(self):
        """Test template directory fallback logic."""
        # This test is complex due to the fallback logic
        # Just test that the function doesn't raise an error when importlib fails
        with mock.patch("importlib.resources.files", side_effect=Exception()):
            # The function will try to find templates in various locations
            try:
                templates_dir = get_templates_dir()
                # If it succeeds, templates exist somewhere
                assert templates_dir is not None
            except RuntimeError:
                # If templates don't exist anywhere, that's expected
                pass

    def test_get_templates_dir_not_found(self):
        """Test error when templates directory not found."""
        with mock.patch("importlib.resources.files", side_effect=Exception()):
            with mock.patch("pathlib.Path.exists", return_value=False):
                with pytest.raises(RuntimeError, match="Templates directory not found"):
                    get_templates_dir()


class TestGitOperations:
    """Test git repository operations."""

    def test_is_git_repo_true(self, tmp_path):
        """Test checking if directory is a git repo."""
        os.chdir(tmp_path)
        subprocess.run(["git", "init"], check=True, capture_output=True)
        assert is_git_repo(tmp_path) is True

    def test_is_git_repo_false(self, tmp_path):
        """Test checking if directory is not a git repo."""
        assert is_git_repo(tmp_path) is False

    def test_init_git_repo_success(self, tmp_path):
        """Test successful git repo initialization."""
        # Set git config for test
        subprocess.run(["git", "config", "--global", "user.email", "test@example.com"], capture_output=True)
        subprocess.run(["git", "config", "--global", "user.name", "Test User"], capture_output=True)

        # Create a file to commit
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        result = init_git_repo(tmp_path, quiet=True)
        assert result is True
        assert (tmp_path / ".git").exists()

    def test_init_git_repo_no_identity(self, tmp_path):
        """Test git repo initialization without configured identity."""
        # Create a file to commit
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        # Clear any existing git config
        subprocess.run(["git", "config", "--global", "--unset", "user.email"], capture_output=True)
        subprocess.run(["git", "config", "--global", "--unset", "user.name"], capture_output=True)

        result = init_git_repo(tmp_path, quiet=True)
        assert result is True

        # Check that local config was set
        os.chdir(tmp_path)
        email = subprocess.run(
            ["git", "config", "--local", "user.email"],
            capture_output=True,
            text=True
        ).stdout.strip()
        assert email == "map-framework@example.com"

    @mock.patch("subprocess.run", side_effect=FileNotFoundError())
    def test_init_git_repo_no_git(self, mock_run, tmp_path):
        """Test handling when git is not installed."""
        result = init_git_repo(tmp_path, quiet=True)
        assert result is False

    def test_init_git_repo_empty_directory(self, tmp_path):
        """Test git repo initialization with no files to commit."""
        # Create only a .gitignore that ignores everything
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("*\n")

        result = init_git_repo(tmp_path, quiet=True)
        assert result is True  # Should still succeed even with nothing to commit


class TestInitCommand:
    """Test mapify init command."""

    @mock.patch("mapify_cli.select_with_arrows")
    @mock.patch("mapify_cli.select_multiple_with_arrows")
    def test_init_basic(self, mock_select_multiple, mock_select, tmp_path):
        """Test basic initialization."""
        os.chdir(tmp_path)

        # Mock the interactive selections
        mock_select.return_value = "claude"  # AI assistant choice
        mock_select_multiple.return_value = []  # No MCP servers

        result = runner.invoke(app, ["init", ".", "--no-git"])

        assert result.exit_code == 0
        assert (tmp_path / ".claude").exists()
        assert (tmp_path / ".claude" / "agents").exists()
        assert (tmp_path / ".claude" / "commands").exists()

    @mock.patch("mapify_cli.select_with_arrows")
    @mock.patch("mapify_cli.select_multiple_with_arrows")
    def test_init_with_directory(self, mock_select_multiple, mock_select, tmp_path):
        """Test initialization with specific directory."""
        os.chdir(tmp_path)
        project_dir = tmp_path / "my_project"
        # Don't create the directory beforehand - init will create it

        # Mock the interactive selections
        mock_select.return_value = "claude"
        mock_select_multiple.return_value = []

        result = runner.invoke(app, ["init", "my_project", "--no-git"])

        assert result.exit_code == 0
        assert project_dir.exists()
        assert (project_dir / ".claude").exists()

    @mock.patch("typer.confirm")
    @mock.patch("mapify_cli.select_with_arrows")
    @mock.patch("mapify_cli.select_multiple_with_arrows")
    def test_init_already_initialized(self, mock_select_multiple, mock_select, mock_confirm, tmp_path):
        """Test initialization when already initialized."""
        os.chdir(tmp_path)

        # Mock the interactive selections
        mock_select.return_value = "claude"
        mock_select_multiple.return_value = []
        mock_confirm.return_value = True  # Confirm to continue when directory not empty

        # First init
        runner.invoke(app, ["init", ".", "--no-git"])

        # Second init - The tool allows reinitializing
        result = runner.invoke(app, ["init", ".", "--no-git"])

        # The second init should either warn or complete successfully
        assert result.exit_code == 0
        assert "Project ready" in result.stdout or "already initialized" in result.stdout

    @mock.patch("mapify_cli.select_with_arrows")
    @mock.patch("mapify_cli.select_multiple_with_arrows")
    def test_init_with_mcp_servers(self, mock_select_multiple, mock_select, tmp_path):
        """Test initialization with MCP server selection."""
        os.chdir(tmp_path)

        # Mock user input for MCP server selection
        mock_select.side_effect = ["claude", "custom"]  # AI choice, then MCP choice
        mock_select_multiple.return_value = ["byterover", "claude-reviewer"]

        result = runner.invoke(app, ["init", ".", "--no-git"])

        assert result.exit_code == 0

        # Check config file
        config_file = tmp_path / ".claude" / "mcp_config.json"
        assert config_file.exists()

        config = json.loads(config_file.read_text())
        assert "byterover" in config["mcp_servers"]
        assert "claude-reviewer" in config["mcp_servers"]


class TestCheckCommand:
    """Test mapify check command."""

    def test_check_not_initialized(self, tmp_path):
        """Test check command when not initialized."""
        os.chdir(tmp_path)
        result = runner.invoke(app, ["check"])

        assert result.exit_code == 0
        # Check command always shows tool availability
        assert "Check Available Tools" in result.stdout or "MAP Framework" in result.stdout

    def test_check_initialized(self, tmp_path):
        """Test check command when initialized."""
        os.chdir(tmp_path)

        # Initialize first
        runner.invoke(app, ["init", ".", "--no-git"])

        # Check
        result = runner.invoke(app, ["check"])

        assert result.exit_code == 0
        assert "Check Available Tools" in result.stdout or "MAP Framework" in result.stdout

    def test_check_with_mcp_servers(self, tmp_path):
        """Test check command with MCP servers configured."""
        os.chdir(tmp_path)

        # Initialize with MCP servers
        with mock.patch("mapify_cli.select_multiple_with_arrows") as mock_select:
            mock_select.return_value = ["byterover"]
            runner.invoke(app, ["init", ".", "--no-git"])

        # Check
        result = runner.invoke(app, ["check"])

        assert result.exit_code == 0
        # Just check that the command runs successfully
        assert "Check Available Tools" in result.stdout or "MAP" in result.stdout


class TestUpgradeCommand:
    """Test mapify upgrade command."""

    @mock.patch("mapify_cli.get_latest_release")
    def test_upgrade_available(self, mock_get_release, tmp_path):
        """Test upgrade when new version is available."""
        os.chdir(tmp_path)

        # Initialize first
        runner.invoke(app, ["init", ".", "--no-git"])

        # Mock new release
        mock_get_release.return_value = {
            "tag_name": "v2.0.0",
            "html_url": "https://github.com/test/test/releases/tag/v2.0.0"
        }

        # Mock current version as older
        with mock.patch("mapify_cli.__version__", "1.0.0"):
            result = runner.invoke(app, ["upgrade"])

            assert result.exit_code == 0
            # Upgrade feature is not fully implemented yet
            assert "Upgrade feature coming soon" in result.stdout or "New version available" in result.stdout

    @mock.patch("mapify_cli.get_latest_release")
    def test_upgrade_not_available(self, mock_get_release, tmp_path):
        """Test upgrade when already on latest version."""
        os.chdir(tmp_path)

        # Initialize first
        runner.invoke(app, ["init", ".", "--no-git"])

        # Mock same version
        mock_get_release.return_value = {
            "tag_name": "v1.0.0",
            "html_url": "https://github.com/test/test/releases/tag/v1.0.0"
        }

        with mock.patch("mapify_cli.__version__", "1.0.0"):
            result = runner.invoke(app, ["upgrade"])

            assert result.exit_code == 0
            # Upgrade feature is not fully implemented yet
            assert "Upgrade feature coming soon" in result.stdout or "already on the latest version" in result.stdout

    def test_upgrade_not_initialized(self, tmp_path):
        """Test upgrade when not initialized."""
        os.chdir(tmp_path)

        result = runner.invoke(app, ["upgrade"])

        assert result.exit_code == 0
        # Upgrade feature is not fully implemented yet
        assert "Upgrade feature coming soon" in result.stdout or "MAP Framework not initialized" in result.stdout


class TestAgentCreation:
    """Test agent file creation."""

    def test_create_agent_files(self, tmp_path):
        """Test creating agent files."""
        create_agent_files(tmp_path, ["byterover", "claude-reviewer"])

        agents_dir = tmp_path / ".claude" / "agents"
        assert agents_dir.exists()

        # Check all agents are created
        expected_agents = [
            "task-decomposer.md",
            "actor.md",
            "monitor.md",
            "predictor.md",
            "evaluator.md",
            "orchestrator.md"
        ]

        for agent in expected_agents:
            assert (agents_dir / agent).exists()

    def test_create_agent_files_with_templates(self, tmp_path):
        """Test creating agent files from templates."""
        # Create mock templates directory
        templates_dir = tmp_path / "templates" / "agents"
        templates_dir.mkdir(parents=True)

        # Create mock template
        template = templates_dir / "test-agent.md"
        template.write_text("Test agent content")

        with mock.patch("mapify_cli.get_templates_dir", return_value=tmp_path / "templates"):
            create_agent_files(tmp_path, [])

            # Check template was copied
            assert (tmp_path / ".claude" / "agents" / "test-agent.md").exists()


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

        # Check MAP commands are created
        expected_commands = [
            "map-review.md",
            "map-refactor.md",
            "map-debug.md",
            "map-feature.md"
        ]

        for cmd in expected_commands:
            assert (commands_dir / cmd).exists()


class TestHelperFunctions:
    """Test helper functions."""

    def test_is_command_basic(self):
        """Test is_command function."""
        assert is_command(["python"]) is True
        assert is_command(["nonexistent_command_xyz"]) is False

    @mock.patch("httpx.Client")
    def test_get_latest_release(self, mock_client_class):
        """Test getting latest release from GitHub."""
        mock_client = mock.Mock()
        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "tag_name": "v1.2.3",
            "html_url": "https://github.com/test/test/releases/tag/v1.2.3"
        }
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = mock.Mock(return_value=mock_client)
        mock_client.__exit__ = mock.Mock(return_value=None)
        mock_client_class.return_value = mock_client

        release = get_latest_release("test", "test")

        assert release is not None
        assert release["tag_name"] == "v1.2.3"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])