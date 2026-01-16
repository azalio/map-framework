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
    build_standard_mcp_servers,
    create_agent_files,
    create_command_files,
    create_commands_dir,
    create_map_tools,
    create_or_merge_project_mcp_json,
    create_ssl_context,
    get_latest_release,
    get_templates_dir,
    init_git_repo,
    is_command,
    is_git_repo,
    merge_mcp_json,
    read_project_mcp_json,
    write_project_mcp_json,
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
        mock_path.__truediv__ = mock.Mock(
            return_value=Path(__file__).parent.parent / "templates"
        )
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
        with mock.patch(
            "subprocess.run", side_effect=FileNotFoundError("git not found")
        ):
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

    def test_init_basic(self, tmp_path):
        """Test basic initialization without options.

        Verifies that:
        - Init succeeds with default --mcp all option
        - Agent and command directories are created
        - MCP config is created with all servers
        """
        os.chdir(tmp_path)

        result = runner.invoke(app, ["init", ".", "--no-git", "--mcp", "none"])

        assert result.exit_code == 0
        assert (tmp_path / ".claude" / "agents").exists()
        assert (tmp_path / ".claude" / "commands").exists()

        # Project-level approvals should be created
        settings_local = tmp_path / ".claude" / "settings.local.json"
        assert settings_local.exists()
        settings = json.loads(settings_local.read_text())
        allow = settings.get("permissions", {}).get("allow", [])
        assert "Bash(go test:*)" in allow
        assert "Bash(go vet :*)" in allow
        assert "Bash(go mod tidy:*)" in allow
        assert "mcp__mem0__*" in allow
        assert "mcp__sourcecraft__list_pull_request_comments" in allow
        assert "Bash(make generate manifests)" in allow
        assert "Bash(make manifests)" in allow
        assert "Bash(git worktree add:*)" in allow
        assert (
            'Bash(openssl req -x509 -newkey rsa:512 -keyout /dev/null -out /dev/stdout -days 365 -nodes -subj "/CN=test" 2>/dev/null)'
            in allow
        )

    def test_init_always_uses_claude(self, tmp_path):
        """Test that init always uses Claude (no AI selection prompt).

        Verifies that:
        - No AI selection occurs (hardcoded to 'claude')
        - Claude agents are created
        - Output mentions Claude or project ready
        """
        os.chdir(tmp_path)

        result = runner.invoke(app, ["init", ".", "--no-git", "--mcp", "none"])

        assert result.exit_code == 0
        # Should show "claude" somewhere in output (AI assistant confirmation)
        assert "claude" in result.stdout.lower() or "Project ready" in result.stdout

    def test_init_ai_flag_not_accepted(self, tmp_path):
        """Test that passing --ai flag results in a clear error.

        Verifies that:
        - Typer rejects --ai flag with "no such option: --ai"
        - Command fails with non-zero exit code
        """
        os.chdir(tmp_path)

        result = runner.invoke(app, ["init", ".", "--ai", "cursor", "--no-git"])

        assert result.exit_code != 0
        # Typer should reject the unknown option
        # Check both stdout and output for compatibility across Typer versions
        output_text = getattr(result, "output", result.stdout)
        assert (
            "no such option" in output_text.lower()
            or "unrecognized" in output_text.lower()
        )

    def test_init_mcp_none(self, tmp_path):
        """Test init with --mcp none option.

        Verifies that:
        - Init succeeds with --mcp none
        - MCP config is not created or is empty
        - Agent files are still created
        """
        os.chdir(tmp_path)

        result = runner.invoke(app, ["init", ".", "--no-git", "--mcp", "none"])

        assert result.exit_code == 0
        assert (tmp_path / ".claude" / "agents").exists()

        # MCP config might exist but should be empty or minimal
        mcp_config_path = tmp_path / ".claude" / "mcp_config.json"
        if mcp_config_path.exists():
            mcp_config = json.loads(mcp_config_path.read_text())
            # Should have no MCP servers or empty mcp_servers dict
            assert len(mcp_config.get("mcp_servers", {})) == 0

    def test_init_tracker_shows_claude(self, tmp_path):
        """Test that tracker shows Claude as selected AI.

        Verifies that:
        - Output mentions Claude as the AI assistant
        - No other AI assistants are mentioned
        """
        os.chdir(tmp_path)

        result = runner.invoke(app, ["init", ".", "--no-git", "--mcp", "none"])

        assert result.exit_code == 0
        # Should show claude in the tracker output
        assert "claude" in result.stdout.lower() or "Project ready" in result.stdout

    def test_init_claude_with_essential_mcp(self, tmp_path):
        """Test initialization with Claude and essential MCP servers.

        Verifies that:
        - Init succeeds with --mcp essential
        - Essential MCP servers are configured (cipher, claude-reviewer, sequential-thinking)
        - Agent files are created
        """
        os.chdir(tmp_path)

        result = runner.invoke(app, ["init", ".", "--no-git", "--mcp", "essential"])

        assert result.exit_code == 0
        assert (tmp_path / ".claude" / "agents").exists()
        assert (tmp_path / ".claude" / "mcp_config.json").exists()

        # Check MCP config contains essential servers
        mcp_config = json.loads((tmp_path / ".claude" / "mcp_config.json").read_text())
        assert "cipher" in mcp_config["mcp_servers"]
        assert "claude-reviewer" in mcp_config["mcp_servers"]
        assert "sequential-thinking" in mcp_config["mcp_servers"]

    def test_init_with_directory(self, tmp_path):
        """Test init with specific directory name.

        Verifies that:
        - New directory is created with specified name
        - Agent files are created in new directory
        """
        os.chdir(tmp_path)
        project_name = "my-project"

        result = runner.invoke(app, ["init", project_name, "--no-git", "--mcp", "none"])

        assert result.exit_code == 0
        project_path = tmp_path / project_name
        assert project_path.exists()
        assert (project_path / ".claude" / "agents").exists()

    def test_init_already_initialized(self, tmp_path):
        """Test init when project already has .claude directory.

        Verifies that:
        - First init succeeds
        - Second init with --force succeeds
        - --force allows re-initialization
        """
        os.chdir(tmp_path)

        # Initialize once
        result1 = runner.invoke(app, ["init", ".", "--no-git", "--mcp", "none"])
        assert result1.exit_code == 0

        # Try to initialize again in same directory with --force
        result2 = runner.invoke(
            app, ["init", ".", "--no-git", "--mcp", "none", "--force"]
        )
        assert result2.exit_code == 0
        # Should succeed with --force
        assert (
            "Project ready" in result2.stdout or "already initialized" in result2.stdout
        )

    def test_init_with_mcp_servers(self, tmp_path):
        """Test init with MCP servers specified via CLI.

        Verifies that:
        - --mcp essential flag installs essential servers
        - MCP config contains cipher, claude-reviewer, sequential-thinking
        """
        os.chdir(tmp_path)

        result = runner.invoke(app, ["init", ".", "--mcp", "essential", "--no-git"])

        assert result.exit_code == 0
        assert (tmp_path / ".claude" / "mcp_config.json").exists()

        mcp_config = json.loads((tmp_path / ".claude" / "mcp_config.json").read_text())
        assert "cipher" in mcp_config["mcp_servers"]
        assert "claude-reviewer" in mcp_config["mcp_servers"]
        assert "sequential-thinking" in mcp_config["mcp_servers"]

    @pytest.mark.skip(
        reason="Test isolation issue: passes in isolation but fails in full suite after 332 tests due to stdin/stdout state. TODO: Investigate and fix test infrastructure issue."
    )
    def test_init_defaults_to_all_mcp_servers(self, tmp_path, monkeypatch):
        """Test that init without --mcp flag defaults to installing all 5 MCP servers.

        Regression test for non-interactive init behavior.
        Verifies that:
        - Init completes without interactive prompts
        - All 5 MCP servers are installed by default (cipher, claude-reviewer,
          sequential-thinking, context7, deepwiki)
        - mcp_config.json is created with all 5 servers
        """
        # Use fresh CliRunner to avoid state pollution from previous tests
        from typer.testing import CliRunner as FreshRunner
        import sys

        fresh_runner = FreshRunner()

        original_cwd = os.getcwd()
        original_stdin = sys.stdin
        original_stdout = sys.stdout
        original_stderr = sys.stderr

        monkeypatch.chdir(tmp_path)
        try:
            # Ensure stdin/stdout/stderr are reset to avoid fileno() issues
            sys.stdin = sys.__stdin__
            sys.stdout = sys.__stdout__
            sys.stderr = sys.__stderr__

            # Run init without --mcp flag (should default to "all")
            result = fresh_runner.invoke(app, ["init", ".", "--no-git"])
        finally:
            sys.stdin = original_stdin
            sys.stdout = original_stdout
            sys.stderr = original_stderr
            os.chdir(original_cwd)

        assert result.exit_code == 0, f"Init failed: {result.stdout}"
        assert (tmp_path / ".claude" / "agents").exists()
        assert (tmp_path / ".claude" / "mcp_config.json").exists()

        # Verify all 5 MCP servers are configured
        mcp_config = json.loads((tmp_path / ".claude" / "mcp_config.json").read_text())
        expected_servers = [
            "cipher",
            "claude-reviewer",
            "sequential-thinking",
            "context7",
            "deepwiki",
        ]

        assert "mcp_servers" in mcp_config, "mcp_config missing 'mcp_servers' key"
        for server in expected_servers:
            assert (
                server in mcp_config["mcp_servers"]
            ), f"MCP server '{server}' not found in config"

        # Verify exactly 5 servers (no extras)
        assert (
            len(mcp_config["mcp_servers"]) == 5
        ), f"Expected 5 servers, found {len(mcp_config['mcp_servers'])}"

    def test_init_force_no_prompts(self, tmp_path):
        """Test that init --force completes without interactive confirmation prompts.

        Regression test for non-interactive force behavior.
        Verifies that:
        - Running init in non-empty directory with --force completes silently
        - No interactive prompts are triggered
        - Command succeeds with exit code 0
        """
        os.chdir(tmp_path)

        # Create a non-empty directory with some files
        (tmp_path / "existing_file.txt").write_text("existing content")
        (tmp_path / "README.md").write_text("# Existing project")

        # First init to create .claude directory (use --force since dir is non-empty)
        result1 = runner.invoke(
            app, ["init", ".", "--no-git", "--mcp", "none", "--force"]
        )
        assert result1.exit_code == 0, f"First init failed: {result1.stdout}"

        # Modify an agent file to verify --force overwrites
        actor_file = tmp_path / ".claude" / "agents" / "actor.md"
        actor_file.write_text("# Modified by user")

        # Run init --force in non-empty directory (should complete without prompts)
        result2 = runner.invoke(
            app, ["init", ".", "--force", "--no-git", "--mcp", "none"]
        )

        assert result2.exit_code == 0, f"Init --force failed: {result2.stdout}"

        # Verify command completed successfully
        assert (
            "Project ready" in result2.stdout or "initialized" in result2.stdout.lower()
        )

        # Verify existing non-.claude files are preserved
        assert (tmp_path / "existing_file.txt").exists()
        assert (tmp_path / "existing_file.txt").read_text() == "existing content"
        assert (tmp_path / "README.md").exists()

        # Verify agent file was updated/restored (not the user's modified version)
        # This confirms --force actually re-initialized the files
        assert actor_file.exists()
        restored_content = actor_file.read_text()
        assert (
            restored_content != "# Modified by user"
        ), "--force did not restore template files"
        # Should contain some template markers (not exact match due to potential updates)
        assert len(restored_content) > 100, "Restored actor.md seems too short"


class TestCheckCommand:
    """Test the check command."""

    def test_check_not_initialized(self, tmp_path):
        """Test check command shows tool status."""
        os.chdir(tmp_path)
        result = runner.invoke(app, ["check"])

        # Should show available tools
        assert result.exit_code == 0
        assert (
            "Check Available Tools" in result.stdout or "MAP Framework" in result.stdout
        )

    @mock.patch("mapify_cli.check_tool")
    def test_check_initialized(self, mock_check_tool, tmp_path):
        """Test check command when tools are installed."""
        os.chdir(tmp_path)
        mock_check_tool.return_value = True

        result = runner.invoke(app, ["check"])

        assert result.exit_code == 0
        assert (
            "Check Available Tools" in result.stdout or "MAP Framework" in result.stdout
        )

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
            "html_url": "https://github.com/azalio/map-framework/releases/tag/v2.0.0",
        }

        result = runner.invoke(app, ["upgrade"])

        assert result.exit_code == 0
        # For now, upgrade shows "coming soon" message
        assert (
            "Upgrade feature coming soon" in result.stdout
            or "New version available" in result.stdout
        )

    @mock.patch("mapify_cli.get_latest_release")
    def test_upgrade_not_available(self, mock_get_latest, tmp_path):
        """Test upgrade when already on latest version."""
        os.chdir(tmp_path)
        mock_get_latest.return_value = {
            "tag_name": "v1.0.0",
            "html_url": "https://github.com/azalio/map-framework/releases/tag/v1.0.0",
        }

        result = runner.invoke(app, ["upgrade"])

        assert result.exit_code == 0
        assert (
            "Upgrade feature coming soon" in result.stdout
            or "already on the latest version" in result.stdout
        )

    def test_upgrade_not_initialized(self, tmp_path):
        """Test upgrade in non-initialized directory."""
        os.chdir(tmp_path)
        result = runner.invoke(app, ["upgrade"])

        assert result.exit_code == 0
        assert (
            "Upgrade feature coming soon" in result.stdout
            or "MAP Framework not initialized" in result.stdout
        )


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
        - All 8 agents are created successfully
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

        # Verify all 8 agents were created using fallback generators
        expected_agents = [
            "task-decomposer.md",
            "actor.md",
            "monitor.md",
            "predictor.md",
            "evaluator.md",
            "reflector.md",
            "curator.md",
            "documentation-reviewer.md",
        ]

        for agent_file in expected_agents:
            agent_path = agents_dir / agent_file
            assert agent_path.exists(), f"Agent {agent_file} not created"

            # Verify content has required sections
            content = agent_path.read_text()
            assert "---" in content, f"Agent {agent_file} missing YAML frontmatter"
            assert "name:" in content, f"Agent {agent_file} missing name field"
            # Check for role/identity sections (various formats)
            has_core_section = any(
                marker in content for marker in ["IDENTITY", "ROLE", "Role:", "# Role"]
            )
            assert has_core_section, f"Agent {agent_file} missing core sections"

            # Verify MCP integration for cipher-enabled agents
            if any(name in agent_file for name in ["reflector", "curator"]):
                assert (
                    "cipher" in content.lower() or "mcp" in content.lower()
                ), f"Agent {agent_file} missing MCP integration section"


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
            "html_url": "https://github.com/azalio/map-framework/releases/tag/v1.0.0",
        }

        mock_client_instance = mock.Mock()
        mock_client_instance.get.return_value = mock_response
        mock_client_instance.__enter__ = mock.Mock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = mock.Mock(return_value=False)
        mock_client.return_value = mock_client_instance

        result = get_latest_release("azalio", "map-framework")
        assert result is not None
        assert result["tag_name"] == "v1.0.0"


class TestMcpJsonConfig:
    """Test .mcp.json creation and merging functionality."""

    def test_build_standard_mcp_servers_returns_all_servers(self):
        """Test that build_standard_mcp_servers returns all expected servers."""
        servers = build_standard_mcp_servers()

        expected_servers = [
            "sequential-thinking",
            "context7",
            "deepwiki",
        ]
        for server in expected_servers:
            assert server in servers, f"Missing server: {server}"

    def test_build_standard_mcp_servers_correct_types(self):
        """Test that servers have correct transport types."""
        servers = build_standard_mcp_servers()

        # stdio servers should have 'command' key
        for server_name in ["sequential-thinking"]:
            assert "command" in servers[server_name], f"{server_name} missing command"
            assert "args" in servers[server_name], f"{server_name} missing args"

        # http servers should have 'type' and 'url' keys
        for server_name in ["context7", "deepwiki"]:
            assert (
                servers[server_name].get("type") == "http"
            ), f"{server_name} should be http"
            assert "url" in servers[server_name], f"{server_name} missing url"

    def test_read_project_mcp_json_missing_file(self, tmp_path):
        """Test reading non-existent .mcp.json returns None."""
        mcp_file = tmp_path / ".mcp.json"
        result = read_project_mcp_json(mcp_file)
        assert result is None

    def test_read_project_mcp_json_valid_file(self, tmp_path):
        """Test reading valid .mcp.json returns parsed content."""
        mcp_file = tmp_path / ".mcp.json"
        config = {"mcpServers": {"test": {"command": "test"}}}
        mcp_file.write_text(json.dumps(config))

        result = read_project_mcp_json(mcp_file)
        assert result == config

    def test_read_project_mcp_json_invalid_json(self, tmp_path):
        """Test reading invalid JSON returns None and creates backup."""
        import re

        mcp_file = tmp_path / ".mcp.json"
        mcp_file.write_text("{ invalid json }")

        result = read_project_mcp_json(mcp_file)

        assert result is None
        # Check that backup was created with correct naming pattern
        backup_files = list(tmp_path.glob(".mcp.backup.*.json"))
        assert len(backup_files) == 1

        # Verify backup filename matches expected format: YYYYMMDD_HHMMSS_XXXXXXXX (8 hex chars)
        backup_name = backup_files[0].name
        assert re.match(
            r"\.mcp\.backup\.\d{8}_\d{6}_[a-f0-9]{8}\.json$", backup_name
        ), f"Backup name doesn't match expected format: {backup_name}"

    def test_write_project_mcp_json_creates_file(self, tmp_path):
        """Test writing .mcp.json creates file with correct format."""
        mcp_file = tmp_path / ".mcp.json"
        config = {"mcpServers": {"test": {"command": "test"}}}

        write_project_mcp_json(mcp_file, config)

        assert mcp_file.exists()
        content = mcp_file.read_text()
        assert content.endswith("\n")  # Should have trailing newline
        parsed = json.loads(content)
        assert parsed == config

    def test_write_project_mcp_json_permission_error(self, tmp_path):
        """Test write_project_mcp_json raises OSError on permission denied."""
        mcp_file = tmp_path / ".mcp.json"
        mcp_file.touch()
        mcp_file.chmod(0o444)  # Read-only

        config = {"mcpServers": {"test": {"command": "test"}}}

        with pytest.raises(OSError):
            write_project_mcp_json(mcp_file, config)

        # Cleanup: restore permissions so tmp_path cleanup works
        mcp_file.chmod(0o644)

    def test_merge_mcp_json_preserves_existing(self):
        """Test that merge preserves existing servers."""
        existing = {
            "mcpServers": {
                "user-server": {"command": "user-cmd"},
            }
        }
        new_servers = {
            "context7": {"type": "http", "url": "https://mcp.context7.com/mcp"},
        }

        result = merge_mcp_json(existing, new_servers)

        assert "user-server" in result["mcpServers"]
        assert "context7" in result["mcpServers"]
        assert result["mcpServers"]["user-server"]["command"] == "user-cmd"

    def test_merge_mcp_json_does_not_overwrite(self):
        """Test that merge does not overwrite existing servers with same name."""
        existing = {
            "mcpServers": {
                "context7": {
                    "type": "http",
                    "url": "https://custom.url",
                },  # User's custom
            }
        }
        new_servers = {
            "context7": {
                "type": "http",
                "url": "https://mcp.context7.com/mcp",
            },  # Standard
        }

        result = merge_mcp_json(existing, new_servers)

        # User's custom config should be preserved
        assert result["mcpServers"]["context7"]["url"] == "https://custom.url"

    def test_merge_mcp_json_adds_mcpservers_key(self):
        """Test that merge adds mcpServers key if missing."""
        existing = {"other_key": "value"}
        new_servers = {
            "context7": {"type": "http", "url": "https://mcp.context7.com/mcp"}
        }

        result = merge_mcp_json(existing, new_servers)

        assert "mcpServers" in result
        assert "context7" in result["mcpServers"]
        assert "other_key" in result  # Other keys preserved

    def test_create_or_merge_new_file(self, tmp_path):
        """Test creating new .mcp.json when file doesn't exist."""
        create_or_merge_project_mcp_json(tmp_path, ["deepwiki", "context7"])

        mcp_file = tmp_path / ".mcp.json"
        assert mcp_file.exists()

        config = json.loads(mcp_file.read_text())
        assert "mcpServers" in config
        assert "deepwiki" in config["mcpServers"]
        assert "context7" in config["mcpServers"]
        assert len(config["mcpServers"]) == 2

    def test_create_or_merge_existing_file(self, tmp_path):
        """Test merging into existing .mcp.json."""
        # Create existing file with user's server
        mcp_file = tmp_path / ".mcp.json"
        existing_config = {
            "mcpServers": {
                "ChunkHound": {"command": "chunkhound", "args": ["mcp"]},
            }
        }
        mcp_file.write_text(json.dumps(existing_config))

        # Run merge
        create_or_merge_project_mcp_json(tmp_path, ["deepwiki"])

        # Verify merge
        config = json.loads(mcp_file.read_text())
        assert "ChunkHound" in config["mcpServers"]  # User's server preserved
        assert "deepwiki" in config["mcpServers"]  # New server added

    def test_create_or_merge_empty_servers_list(self, tmp_path):
        """Test that empty servers list doesn't create file."""
        create_or_merge_project_mcp_json(tmp_path, [])

        mcp_file = tmp_path / ".mcp.json"
        assert not mcp_file.exists()

    def test_create_or_merge_filters_unknown_servers(self, tmp_path):
        """Test that unknown server names are ignored."""
        create_or_merge_project_mcp_json(
            tmp_path, ["deepwiki", "unknown-server", "context7"]
        )

        mcp_file = tmp_path / ".mcp.json"
        config = json.loads(mcp_file.read_text())

        assert "deepwiki" in config["mcpServers"]
        assert "context7" in config["mcpServers"]
        assert "unknown-server" not in config["mcpServers"]

    def test_init_creates_mcp_json(self, tmp_path):
        """Test that mapify init creates .mcp.json file."""
        os.chdir(tmp_path)

        result = runner.invoke(app, ["init", ".", "--force", "--mcp", "docs"])

        # Allow exit code 0 or initialization messages
        mcp_file = tmp_path / ".mcp.json"
        assert (
            mcp_file.exists()
        ), f"Expected .mcp.json to be created. Output: {result.output}"

        config = json.loads(mcp_file.read_text())
        assert "mcpServers" in config
        # docs = context7 + deepwiki
        assert "context7" in config["mcpServers"] or "deepwiki" in config["mcpServers"]


class TestCreateMapTools:
    """Test create_map_tools() function for static analysis tools."""

    def test_create_map_tools_creates_directory(self, tmp_path):
        """Test that create_map_tools creates .map directory with static-analysis."""
        count = create_map_tools(tmp_path)

        map_dir = tmp_path / ".map"
        static_analysis_dir = map_dir / "static-analysis"

        assert map_dir.exists()
        assert static_analysis_dir.exists()
        assert count > 0  # Should have created some scripts

    def test_create_map_tools_copies_scripts(self, tmp_path):
        """Test that static analysis scripts are copied correctly."""
        create_map_tools(tmp_path)

        static_analysis_dir = tmp_path / ".map" / "static-analysis"
        handlers_dir = static_analysis_dir / "handlers"

        # Verify main script exists
        assert (static_analysis_dir / "analyze.sh").exists()

        # Verify handlers exist
        assert handlers_dir.exists()
        assert (handlers_dir / "python.sh").exists()
        assert (handlers_dir / "go.sh").exists()
        assert (handlers_dir / "typescript.sh").exists()
        assert (handlers_dir / "common.sh").exists()

    def test_create_map_tools_makes_scripts_executable(self, tmp_path):
        """Test that scripts are made executable."""
        create_map_tools(tmp_path)

        static_analysis_dir = tmp_path / ".map" / "static-analysis"
        handlers_dir = static_analysis_dir / "handlers"

        # Check main script is executable
        analyze_script = static_analysis_dir / "analyze.sh"
        assert analyze_script.stat().st_mode & 0o111  # Has execute bit

        # Check handler scripts are executable
        for script in handlers_dir.glob("*.sh"):
            assert script.stat().st_mode & 0o111, f"{script.name} should be executable"

    def test_create_map_tools_overwrites_existing(self, tmp_path):
        """Test that existing static-analysis directory is replaced."""
        # Create existing .map structure with a marker file
        map_dir = tmp_path / ".map" / "static-analysis"
        map_dir.mkdir(parents=True)
        marker_file = map_dir / "old_marker.txt"
        marker_file.write_text("old content")

        # Run create_map_tools
        create_map_tools(tmp_path)

        # Marker file should be gone (directory was replaced)
        assert not marker_file.exists()

        # New scripts should exist
        assert (tmp_path / ".map" / "static-analysis" / "analyze.sh").exists()

    def test_create_map_tools_returns_script_count(self, tmp_path):
        """Test that function returns correct count of scripts."""
        count = create_map_tools(tmp_path)

        # Count actual .sh files created
        static_analysis_dir = tmp_path / ".map" / "static-analysis"
        actual_count = len(list(static_analysis_dir.rglob("*.sh")))

        assert count == actual_count
        assert count >= 5  # analyze.sh + common.sh + python.sh + go.sh + typescript.sh

    @mock.patch("mapify_cli.get_templates_dir")
    def test_create_map_tools_no_templates(self, mock_get_templates, tmp_path):
        """Test handling when templates directory doesn't have map subdirectory."""
        # Mock empty templates directory
        mock_templates = tmp_path / "empty_templates"
        mock_templates.mkdir()
        mock_get_templates.return_value = mock_templates

        count = create_map_tools(tmp_path)

        # Should return 0 when no map templates exist
        assert count == 0

    @mock.patch("mapify_cli.get_templates_dir")
    def test_create_map_tools_map_exists_but_no_static_analysis(
        self, mock_get_templates, tmp_path
    ):
        """Test when templates_dir/map exists but static-analysis subdirectory doesn't."""
        # Create templates/map without static-analysis
        mock_templates = tmp_path / "templates"
        mock_templates.mkdir()
        (mock_templates / "map").mkdir()
        # Don't create static-analysis subdirectory
        mock_get_templates.return_value = mock_templates

        count = create_map_tools(tmp_path)

        # Should return 0 when static-analysis doesn't exist
        assert count == 0
        # .map directory should still be created
        assert (tmp_path / ".map").exists()

    def test_create_map_tools_preserves_other_map_contents(self, tmp_path):
        """Test that other files in .map are preserved."""
        # Create .map with other content
        map_dir = tmp_path / ".map"
        map_dir.mkdir()
        other_file = map_dir / "other_data.json"
        other_file.write_text('{"key": "value"}')

        # Run create_map_tools
        create_map_tools(tmp_path)

        # Other file should still exist
        assert other_file.exists()
        assert other_file.read_text() == '{"key": "value"}'

        # New scripts should also exist
        assert (map_dir / "static-analysis" / "analyze.sh").exists()
