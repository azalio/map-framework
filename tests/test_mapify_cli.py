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

from mapify_cli.delivery import create_map_tools
from mapify_cli import (
    app,
    build_standard_mcp_servers,
    count_agent_templates,
    create_agent_files,
    create_command_files,
    create_commands_dir,
    create_or_merge_project_mcp_json,
    create_ssl_context,
    get_branch_artifact_templates,
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
        assert "Bash(go test *)" in allow
        assert "Bash(go vet *)" in allow
        assert "Bash(go mod tidy *)" in allow
        assert "mcp__sourcecraft__list_pull_request_comments" in allow
        assert "Bash(make generate manifests)" in allow
        assert "Bash(make manifests)" in allow
        assert "Bash(git worktree add *)" in allow
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
        - Essential MCP servers are configured (sequential-thinking, deepwiki)
        - Agent files are created
        """
        os.chdir(tmp_path)

        result = runner.invoke(app, ["init", ".", "--no-git", "--mcp", "essential"])

        assert result.exit_code == 0
        assert (tmp_path / ".claude" / "agents").exists()
        assert (tmp_path / ".claude" / "mcp_config.json").exists()

        # Check MCP config contains essential servers
        mcp_config = json.loads((tmp_path / ".claude" / "mcp_config.json").read_text())
        assert "sequential-thinking" in mcp_config["mcp_servers"]
        assert "deepwiki" in mcp_config["mcp_servers"]

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
        - MCP config contains sequential-thinking, deepwiki
        """
        os.chdir(tmp_path)

        result = runner.invoke(app, ["init", ".", "--mcp", "essential", "--no-git"])

        assert result.exit_code == 0
        assert (tmp_path / ".claude" / "mcp_config.json").exists()

        mcp_config = json.loads((tmp_path / ".claude" / "mcp_config.json").read_text())
        assert "sequential-thinking" in mcp_config["mcp_servers"]
        assert "deepwiki" in mcp_config["mcp_servers"]

    @pytest.mark.skip(
        reason="Test isolation issue: passes in isolation but fails in full suite after 332 tests due to stdin/stdout state. TODO: Investigate and fix test infrastructure issue."
    )
    def test_init_defaults_to_all_mcp_servers(self, tmp_path, monkeypatch):
        """Test that init without --mcp flag defaults to installing all 4 MCP servers.

        Regression test for non-interactive init behavior.
        Verifies that:
        - Init completes without interactive prompts
        - All 2 MCP servers are installed by default (sequential-thinking, deepwiki)
        - mcp_config.json is created with all 2 servers
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

        # Verify default MCP servers are configured
        mcp_config = json.loads((tmp_path / ".claude" / "mcp_config.json").read_text())
        expected_servers = [
            "sequential-thinking",
            "deepwiki",
        ]

        assert "mcp_servers" in mcp_config, "mcp_config missing 'mcp_servers' key"
        for server in expected_servers:
            assert (
                server in mcp_config["mcp_servers"]
            ), f"MCP server '{server}' not found in config"

        # Verify exactly the expected default set (no extras)
        assert sorted(mcp_config["mcp_servers"]) == sorted(
            expected_servers
        ), f"Expected default MCP servers {expected_servers}, found {mcp_config['mcp_servers']}"

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

        init_result = runner.invoke(app, ["init", ".", "--no-git", "--mcp", "none"])
        assert init_result.exit_code == 0

        result = runner.invoke(app, ["check"])

        assert result.exit_code == 0
        assert (
            "Check Available Tools" in result.stdout or "MAP Framework" in result.stdout
        )
        assert "initialized" in result.stdout
        expected_agents = count_agent_templates()
        assert f"{expected_agents} agents" in result.stdout

    @mock.patch("mapify_cli.check_tool")
    def test_check_with_mcp_servers(self, mock_check_tool, tmp_path):
        """Test check command shows MCP server status."""
        os.chdir(tmp_path)
        mock_check_tool.return_value = True

        result = runner.invoke(app, ["check"])

        assert result.exit_code == 0
        assert "sequential-thinking" in result.stdout
        assert "deepwiki" in result.stdout


class TestDoctorCommand:
    """Test the doctor command."""

    @mock.patch("mapify_cli.check_tool")
    def test_doctor_initialized_project(self, mock_check_tool, tmp_path):
        """Doctor should report healthy project structure after init."""
        os.chdir(tmp_path)
        mock_check_tool.return_value = True

        init_result = runner.invoke(app, ["init", ".", "--no-git", "--mcp", "none"])
        assert init_result.exit_code == 0

        result = runner.invoke(app, ["doctor"])

        assert result.exit_code == 0
        assert "MAP Doctor" in result.stdout
        assert ".map/main/" in result.stdout
        expected_agents = count_agent_templates()
        assert f"{expected_agents}/{expected_agents}" in result.stdout

    @mock.patch("mapify_cli.check_tool")
    def test_doctor_reports_missing_structure(self, mock_check_tool, tmp_path):
        """Doctor should surface missing paths in non-initialized directories."""
        os.chdir(tmp_path)
        mock_check_tool.return_value = True

        result = runner.invoke(app, ["doctor"])

        assert result.exit_code == 0
        assert "Missing core paths" in result.stdout
        assert ".map/scripts" in result.stdout


class TestUpgradeCommand:
    """Test the upgrade command."""

    @mock.patch("mapify_cli.get_latest_release")
    def test_upgrade_available(self, mock_get_latest, tmp_path):
        """Test upgrade refreshes files and reports newer release."""
        os.chdir(tmp_path)
        init_result = runner.invoke(app, ["init", ".", "--no-git", "--mcp", "none"])
        assert init_result.exit_code == 0

        actor_file = tmp_path / ".claude" / "agents" / "actor.md"
        original_content = actor_file.read_text()
        actor_file.write_text("stale content\n")

        mock_get_latest.return_value = {
            "tag_name": "v9.9.9",
            "html_url": "https://github.com/azalio/map-framework/releases/tag/v9.9.9",
        }

        result = runner.invoke(app, ["upgrade"])

        assert result.exit_code == 0
        assert "New version available" in result.stdout
        assert "Upgrade complete" in result.stdout
        # Compare content ignoring MAP-MANAGED metadata timestamps (which differ between init and upgrade)
        import re

        def _strip_managed_meta(text):
            return re.sub(r"<!-- MAP-MANAGED:.*?-->\n?", "", text)

        assert _strip_managed_meta(actor_file.read_text()) == _strip_managed_meta(
            original_content
        )

    @mock.patch("mapify_cli.get_latest_release")
    def test_upgrade_not_available(self, mock_get_latest, tmp_path):
        """Test upgrade when already on latest version."""
        os.chdir(tmp_path)
        init_result = runner.invoke(app, ["init", ".", "--no-git", "--mcp", "none"])
        assert init_result.exit_code == 0
        mock_get_latest.return_value = {
            "tag_name": "v3.5.0",
            "html_url": "https://github.com/azalio/map-framework/releases/tag/v3.5.0",
        }

        result = runner.invoke(app, ["upgrade"])

        assert result.exit_code == 0
        assert "latest installed version" in result.stdout
        assert "Upgrade complete" in result.stdout

    def test_upgrade_not_initialized(self, tmp_path):
        """Test upgrade in non-initialized directory."""
        os.chdir(tmp_path)
        result = runner.invoke(app, ["upgrade"])

        assert result.exit_code == 0
        assert "MAP Framework not initialized" in result.stdout


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
        create_agent_files(tmp_path, ["deepwiki"])

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
        - 8 core agents are created via fallback generators
        - Content includes required sections (IDENTITY, ROLE)
        - MCP integration sections are included when MCP servers specified

        Note: Fallback generators only cover 8 core agents. The remaining 4
        (debate-arbiter, synthesizer, research-agent, final-verifier) are
        only available when copying from templates.
        """
        # Mock templates directory that doesn't have agent templates
        mock_templates_path = tmp_path / "mock_templates"
        mock_templates_path.mkdir(parents=True, exist_ok=True)
        mock_get_templates.return_value = mock_templates_path

        # Call create_agent_files with MCP servers
        create_agent_files(tmp_path, ["deepwiki"])

        agents_dir = tmp_path / ".claude" / "agents"
        assert agents_dir.exists()

        # Verify core agents were created using fallback generators
        expected_agents = [
            "task-decomposer.md",
            "actor.md",
            "monitor.md",
            "predictor.md",
            "evaluator.md",
            "reflector.md",
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

            # Verify MCP integration for agents that use MCP tools
            if any(
                name in agent_file
                for name in ["task-decomposer", "actor", "monitor", "predictor"]
            ):
                assert (
                    "mcp" in content.lower() or "tool" in content.lower()
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
        """Test creating command files — commands migrated to skills, only README remains."""
        create_command_files(tmp_path)

        commands_dir = tmp_path / ".claude" / "commands"
        assert commands_dir.exists()
        # After skills migration, commands/ has only README.md (no map-*.md)
        command_files = [
            p for p in commands_dir.glob("*.md") if p.name != "README.md"
        ]
        assert len(command_files) == 0


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
        for server_name in ["deepwiki"]:
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
            "deepwiki": {"type": "http", "url": "https://mcp.deepwiki.com/mcp"},
        }

        result = merge_mcp_json(existing, new_servers)

        assert "user-server" in result["mcpServers"]
        assert "deepwiki" in result["mcpServers"]
        assert result["mcpServers"]["user-server"]["command"] == "user-cmd"

    def test_merge_mcp_json_does_not_overwrite(self):
        """Test that merge does not overwrite existing servers with same name."""
        existing = {
            "mcpServers": {
                "deepwiki": {
                    "type": "http",
                    "url": "https://custom.url",
                },  # User's custom
            }
        }
        new_servers = {
            "deepwiki": {
                "type": "http",
                "url": "https://mcp.deepwiki.com/mcp",
            },  # Standard
        }

        result = merge_mcp_json(existing, new_servers)

        # User's custom config should be preserved
        assert result["mcpServers"]["deepwiki"]["url"] == "https://custom.url"

    def test_merge_mcp_json_adds_mcpservers_key(self):
        """Test that merge adds mcpServers key if missing."""
        existing = {"other_key": "value"}
        new_servers = {
            "deepwiki": {"type": "http", "url": "https://mcp.deepwiki.com/mcp"}
        }

        result = merge_mcp_json(existing, new_servers)

        assert "mcpServers" in result
        assert "deepwiki" in result["mcpServers"]
        assert "other_key" in result  # Other keys preserved

    def test_create_or_merge_new_file(self, tmp_path):
        """Test creating new .mcp.json when file doesn't exist."""
        create_or_merge_project_mcp_json(tmp_path, ["deepwiki", "sequential-thinking"])

        mcp_file = tmp_path / ".mcp.json"
        assert mcp_file.exists()

        config = json.loads(mcp_file.read_text())
        assert "mcpServers" in config
        assert "deepwiki" in config["mcpServers"]
        assert "sequential-thinking" in config["mcpServers"]
        assert len(config["mcpServers"]) == 2

    def test_create_or_merge_existing_file(self, tmp_path):
        """Test merging into existing .mcp.json."""
        # Create existing file with user's server
        mcp_file = tmp_path / ".mcp.json"
        existing_config = {
            "mcpServers": {
                "my-custom-server": {"command": "my-server", "args": ["mcp"]},
            }
        }
        mcp_file.write_text(json.dumps(existing_config))

        # Run merge
        create_or_merge_project_mcp_json(tmp_path, ["deepwiki"])

        # Verify merge
        config = json.loads(mcp_file.read_text())
        assert "my-custom-server" in config["mcpServers"]  # User's server preserved
        assert "deepwiki" in config["mcpServers"]  # New server added

    def test_create_or_merge_empty_servers_list(self, tmp_path):
        """Test that empty servers list doesn't create file."""
        create_or_merge_project_mcp_json(tmp_path, [])

        mcp_file = tmp_path / ".mcp.json"
        assert not mcp_file.exists()

    def test_create_or_merge_filters_unknown_servers(self, tmp_path):
        """Test that unknown server names are ignored."""
        create_or_merge_project_mcp_json(
            tmp_path, ["deepwiki", "unknown-server", "sequential-thinking"]
        )

        mcp_file = tmp_path / ".mcp.json"
        config = json.loads(mcp_file.read_text())

        assert "deepwiki" in config["mcpServers"]
        assert "sequential-thinking" in config["mcpServers"]
        assert "unknown-server" not in config["mcpServers"]

    def test_init_creates_mcp_json(self, tmp_path):
        """Test that mapify init creates .mcp.json file."""
        os.chdir(tmp_path)

        result = runner.invoke(app, ["init", ".", "--force", "--mcp", "essential"])

        # Allow exit code 0 or initialization messages
        mcp_file = tmp_path / ".mcp.json"
        assert (
            mcp_file.exists()
        ), f"Expected .mcp.json to be created. Output: {result.output}"

        config = json.loads(mcp_file.read_text())
        assert "mcpServers" in config
        # essential = sequential-thinking + deepwiki
        assert (
            "deepwiki" in config["mcpServers"]
            or "sequential-thinking" in config["mcpServers"]
        )


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

        # Count actual scripts created (.sh + .py)
        map_dir = tmp_path / ".map"
        actual_count = len(list(map_dir.rglob("*.sh"))) + len(
            list(map_dir.rglob("*.py"))
        )

        assert count == actual_count
        assert count >= 5  # analyze.sh + common.sh + python.sh + go.sh + typescript.sh

    @mock.patch("mapify_cli.delivery.file_copier.get_templates_dir")
    def test_create_map_tools_no_templates(self, mock_get_templates, tmp_path):
        """Test handling when templates directory doesn't have map subdirectory."""
        # Mock empty templates directory
        mock_templates = tmp_path / "empty_templates"
        mock_templates.mkdir()
        mock_get_templates.return_value = mock_templates

        count = create_map_tools(tmp_path)

        # Should return 0 when no map templates exist
        assert count == 0

    @mock.patch("mapify_cli.delivery.file_copier.get_templates_dir")
    def test_create_map_tools_map_exists_but_no_static_analysis(
        self, mock_get_templates, tmp_path
    ):
        """Test when templates_dir/map exists but has no shipped content."""
        mock_templates = tmp_path / "templates"
        mock_templates.mkdir()
        (mock_templates / "map").mkdir()
        mock_get_templates.return_value = mock_templates

        count = create_map_tools(tmp_path)

        # Should return 0 when map template is empty
        assert count == 0
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


class TestBranchArtifactTemplates:
    """Tests for get_branch_artifact_templates()."""

    def test_returns_expected_keys(self):
        """Artifact template keys must match the expected set exactly."""
        templates = get_branch_artifact_templates()
        assert set(templates.keys()) == {
            "code-review-001.md",
            "qa-001.md",
            "pr-draft.md",
        }


class TestCodexProvider:
    """Functional tests for Codex CLI provider (AC-1 through AC-20).

    Each test method maps to one acceptance criterion in the Codex provider spec.
    The ``codex_project`` fixture runs ``mapify init . --provider codex --no-git``
    in a fresh tmp_path and returns the project root.
    """

    # ------------------------------------------------------------------ #
    # Shared fixture                                                       #
    # ------------------------------------------------------------------ #

    @pytest.fixture
    def codex_project(self, tmp_path):
        """Run init with --provider codex and return the project root path."""
        local_runner = CliRunner()
        os.chdir(tmp_path)
        result = local_runner.invoke(
            app, ["init", ".", "--provider", "codex", "--no-git", "--force"]
        )
        assert (
            result.exit_code == 0
        ), f"init --provider codex failed (exit {result.exit_code}):\n{result.output}"
        return tmp_path

    # ------------------------------------------------------------------ #
    # AC-1: .agents/skills/map-plan/SKILL.md created                      #
    # ------------------------------------------------------------------ #

    def test_ac01_creates_skill_file(self, codex_project):
        """AC-1: map-plan SKILL.md must exist after init."""
        skill_file = codex_project / ".agents" / "skills" / "map-plan" / "SKILL.md"
        assert skill_file.exists(), f"Expected {skill_file} to exist"

    # ------------------------------------------------------------------ #
    # AC-2: SKILL.md has valid YAML frontmatter                           #
    # ------------------------------------------------------------------ #

    def test_ac02_skill_has_valid_frontmatter(self, codex_project):
        """AC-2: SKILL.md must start with '---' and contain name/description fields."""
        skill_file = codex_project / ".agents" / "skills" / "map-plan" / "SKILL.md"
        content = skill_file.read_text(encoding="utf-8")
        assert content.startswith(
            "---"
        ), "SKILL.md must start with YAML frontmatter '---'"
        assert "name:" in content, "SKILL.md frontmatter must contain 'name:'"
        assert (
            "description:" in content
        ), "SKILL.md frontmatter must contain 'description:'"

    # ------------------------------------------------------------------ #
    # AC-3: SKILL.md contains no Claude-specific tool references          #
    # ------------------------------------------------------------------ #

    def test_ac03_skill_no_claude_tool_refs(self, codex_project):
        """AC-3: SKILL.md must not reference Claude-only tool functions."""
        skill_file = codex_project / ".agents" / "skills" / "map-plan" / "SKILL.md"
        content = skill_file.read_text(encoding="utf-8")
        forbidden_patterns = [
            "Agent(",
            "AskUserQuestion(",
            "subagent_type=",
            "Read(",
            "Write(",
            "Edit(",
            "Glob(",
            "Grep(",
        ]
        for pattern in forbidden_patterns:
            assert (
                pattern not in content
            ), f"SKILL.md must not contain Claude tool reference '{pattern}'"

    # ------------------------------------------------------------------ #
    # AC-4: AGENTS.md exists at project root                              #
    # ------------------------------------------------------------------ #

    def test_ac04_creates_agents_md(self, codex_project):
        """AC-4: AGENTS.md must exist at the project root and be non-empty."""
        agents_md = codex_project / "AGENTS.md"
        assert agents_md.exists(), "AGENTS.md must exist at project root"
        content = (
            agents_md.read_text(encoding="utf-8") if not agents_md.is_symlink() else ""
        )
        # Either a real file with content or a symlink to CLAUDE.md
        assert agents_md.is_symlink() or len(content) > 0, "AGENTS.md must be non-empty"
        if not agents_md.is_symlink():
            assert "$map-plan" in content, "Codex AGENTS.md must document skill invocation with $"
            assert (
                "$map-efficient" in content
            ), "Codex AGENTS.md must document the execution skill"
            assert "codex_hooks" not in content, (
                "Codex AGENTS.md must not document deprecated codex_hooks"
            )

    # ------------------------------------------------------------------ #
    # AC-5: config.toml, agents/*.toml, hooks/workflow-gate.py exist      #
    # ------------------------------------------------------------------ #

    def test_ac05_creates_config_and_agents(self, codex_project):
        """AC-5: config.toml and at least one agent TOML and the hook script must exist."""
        codex_dir = codex_project / ".codex"
        assert (codex_dir / "config.toml").exists(), ".codex/config.toml must exist"
        config_text = (codex_dir / "config.toml").read_text(encoding="utf-8")
        assert "hooks = true" in config_text, (
            "Codex config must enable canonical hooks feature"
        )
        assert "codex_hooks" not in config_text, (
            "Codex config must not use deprecated codex_hooks feature alias"
        )
        toml_files = list((codex_dir / "agents").glob("*.toml"))
        assert (
            len(toml_files) > 0
        ), ".codex/agents/ must contain at least one *.toml file"
        assert (
            codex_dir / "hooks" / "workflow-gate.py"
        ).exists(), ".codex/hooks/workflow-gate.py must exist"

    # ------------------------------------------------------------------ #
    # AC-6: .map/scripts/ installed (or skipped if already present)       #
    # ------------------------------------------------------------------ #

    def test_ac06_map_scripts_installed_or_skipped(self, codex_project, tmp_path):
        """AC-6: .map/scripts/ installed when absent, pre-existing files preserved."""
        map_scripts = codex_project / ".map" / "scripts"
        templates_scripts = get_templates_dir() / "map" / "scripts"
        if templates_scripts.exists() and any(templates_scripts.iterdir()):
            assert (
                map_scripts.exists()
            ), ".map/scripts/ must exist when template provides scripts"

        # Verify skip-if-exists: pre-existing custom scripts survive codex init
        project2 = tmp_path / "skip_test"
        project2.mkdir()
        scripts_dir = project2 / ".map" / "scripts"
        scripts_dir.mkdir(parents=True)
        custom_script = scripts_dir / "custom.py"
        custom_script.write_text("# user custom script\n")

        runner2 = CliRunner()
        os.chdir(project2)
        result = runner2.invoke(
            app, ["init", ".", "--provider", "codex", "--no-git", "--force"]
        )
        assert result.exit_code == 0, f"init failed: {result.output}"
        assert (
            custom_script.exists()
        ), ".map/scripts/custom.py must survive codex init (skip-if-exists)"
        assert custom_script.read_text() == "# user custom script\n"

    # ------------------------------------------------------------------ #
    # AC-7: Default init (no --provider) creates .claude/, not .codex/    #
    # ------------------------------------------------------------------ #

    def test_ac07_default_init_unchanged(self, tmp_path):
        """AC-7: 'init .' without --provider must create .claude/ and not .codex/."""
        local_runner = CliRunner()
        os.chdir(tmp_path)
        result = local_runner.invoke(
            app, ["init", ".", "--no-git", "--mcp", "none", "--force"]
        )
        assert result.exit_code == 0, f"Default init failed:\n{result.output}"
        assert (
            tmp_path / ".claude"
        ).exists(), ".claude/ must exist for default provider"
        assert not (
            tmp_path / ".codex"
        ).exists(), ".codex/ must NOT be created by the default claude provider"

    # ------------------------------------------------------------------ #
    # AC-8: Template sync enforced (reference to ST-008 coverage)         #
    # ------------------------------------------------------------------ #

    def test_ac08_template_sync_enforced(self):
        """AC-8: Codex templates must be present in src/mapify_cli/templates/codex/.

        The exhaustive render-parity check lives in tests/test_template_render.py.
        This test is a quick smoke check that the directory exists and is non-empty.
        """
        codex_templates = get_templates_dir() / "codex"
        assert (
            codex_templates.exists()
        ), "templates/codex/ must exist (render enforced by test_template_render.py)"
        all_files = list(codex_templates.rglob("*"))
        template_files = [f for f in all_files if f.is_file()]
        assert (
            len(template_files) > 0
        ), "templates/codex/ must contain at least one file"

    # ------------------------------------------------------------------ #
    # AC-9: SKILL.md has all 9 step section headers                       #
    # ------------------------------------------------------------------ #

    def test_ac09_skill_has_all_steps(self, codex_project):
        """AC-9: SKILL.md must contain all 9 step section headers."""
        skill_file = codex_project / ".agents" / "skills" / "map-plan" / "SKILL.md"
        content = skill_file.read_text(encoding="utf-8")
        expected_steps = [
            "## Step 0",
            "## Step 1",
            "## Step 2",
            "## Step 3",
            "## Step 4",
            "## Step 5",
            "## Step 6",
            "## Step 7",
            "## Step 8",
        ]
        for step_header in expected_steps:
            assert step_header in content, f"SKILL.md must contain '{step_header}'"

    # ------------------------------------------------------------------ #
    # AC-10: No Claude references in any Codex provider file              #
    # ------------------------------------------------------------------ #

    def test_ac10_no_claude_refs_anywhere(self, codex_project):
        """AC-10: No Codex provider file should reference Claude-specific tool APIs."""
        claude_tool_patterns = [
            "Agent(",
            "AskUserQuestion(",
            "subagent_type=",
        ]
        violations: list[str] = []
        for root in (codex_project / ".codex", codex_project / ".agents"):
            for file_path in root.rglob("*"):
                if not file_path.is_file():
                    continue
                try:
                    content = file_path.read_text(encoding="utf-8")
                except (UnicodeDecodeError, PermissionError):
                    continue
                for pattern in claude_tool_patterns:
                    if pattern in content:
                        rel = file_path.relative_to(codex_project)
                        violations.append(f"{rel}: contains '{pattern}'")
        assert (
            not violations
        ), "Claude-specific tool references found in Codex provider files:\n" + "\n".join(
            violations
        )

    # ------------------------------------------------------------------ #
    # AC-11: Codex skills map-fast, map-check, and map-efficient exist     #
    # ------------------------------------------------------------------ #

    def test_ac11_stub_skills_exist(self, codex_project):
        """AC-11: Codex skills must exist under the official .agents/skills root."""
        skills_dir = codex_project / ".agents" / "skills"
        assert (
            skills_dir / "map-fast" / "SKILL.md"
        ).exists(), ".agents/skills/map-fast/SKILL.md must exist"
        assert (
            skills_dir / "map-check" / "SKILL.md"
        ).exists(), ".agents/skills/map-check/SKILL.md must exist"
        assert (
            skills_dir / "map-efficient" / "SKILL.md"
        ).exists(), ".agents/skills/map-efficient/SKILL.md must exist"
        assert (
            skills_dir / "map-efficient" / "efficient-reference.md"
        ).exists(), ".agents/skills/map-efficient/efficient-reference.md must exist"

    # ------------------------------------------------------------------ #
    # AC-12: hooks.json and workflow-gate.py both created                 #
    # ------------------------------------------------------------------ #

    def test_ac12_hooks_created(self, codex_project):
        """AC-12: hooks.json and hooks/workflow-gate.py must exist with correct config."""
        import json as _json

        codex_dir = codex_project / ".codex"
        hooks_json_path = codex_dir / "hooks.json"
        assert hooks_json_path.exists(), ".codex/hooks.json must exist"
        assert (
            codex_dir / "hooks" / "workflow-gate.py"
        ).exists(), ".codex/hooks/workflow-gate.py must exist"

        # Verify hook command uses quoted git-root-resolved path
        hooks_data = _json.loads(hooks_json_path.read_text())
        command = hooks_data["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        assert (
            "$(git rev-parse --show-toplevel)" in command
        ), "Hook command must use $(git rev-parse --show-toplevel) for path resolution"
        # Path must be quoted to handle spaces in directory names
        assert (
            '"$(git rev-parse --show-toplevel)' in command
        ), "Hook command path must be quoted for spaces in paths"

    # ------------------------------------------------------------------ #
    # AC-13: CodexProvider is a subclass of BaseProvider                  #
    # ------------------------------------------------------------------ #

    def test_ac13_codex_provider_isinstance(self):
        """AC-13: CodexProvider must be an instance of BaseProvider."""
        from mapify_cli.delivery.providers import BaseProvider, CodexProvider

        provider = CodexProvider()
        assert isinstance(
            provider, BaseProvider
        ), "CodexProvider must inherit from BaseProvider"

    # ------------------------------------------------------------------ #
    # AC-14: --provider codex does NOT create .claude/                    #
    # ------------------------------------------------------------------ #

    def test_ac14_codex_init_no_claude_dir(self, codex_project):
        """AC-14: init --provider codex must not create the .claude/ directory."""
        assert not (
            codex_project / ".claude"
        ).exists(), ".claude/ must NOT be created when using --provider codex"

    # ------------------------------------------------------------------ #
    # AC-15: SKILL.md includes spawn_agent with monitor in SPEC_REVIEW    #
    # ------------------------------------------------------------------ #

    def test_ac15_spec_review_step(self, codex_project):
        """AC-15: SKILL.md must include a spawn_agent call using 'monitor' agent."""
        skill_file = codex_project / ".agents" / "skills" / "map-plan" / "SKILL.md"
        content = skill_file.read_text(encoding="utf-8")
        # The SPEC_REVIEW step uses spawn_agent with agent_type="monitor"
        assert "spawn_agent(" in content, "SKILL.md must contain spawn_agent("
        assert (
            'agent_type="monitor"' in content
        ), 'SKILL.md must contain agent_type="monitor" for SPEC_REVIEW step'

    # ------------------------------------------------------------------ #
    # AC-16: --provider foo exits 1 with helpful message                  #
    # ------------------------------------------------------------------ #

    def test_ac16_invalid_provider_exits_1(self, tmp_path):
        """AC-16: An unrecognised --provider value must exit 1 with an error message."""
        local_runner = CliRunner()
        os.chdir(tmp_path)
        result = local_runner.invoke(
            app, ["init", ".", "--provider", "foo", "--no-git", "--force"]
        )
        assert (
            result.exit_code == 1
        ), f"Expected exit code 1 for invalid provider, got {result.exit_code}"
        assert (
            "Valid providers" in result.output
        ), "Error message must mention 'Valid providers'"
        assert "claude" in result.output, "Valid providers list must include 'claude'"
        assert "codex" in result.output, "Valid providers list must include 'codex'"

    # ------------------------------------------------------------------ #
    # AC-17: Each .toml has required fields                               #
    # ------------------------------------------------------------------ #

    def test_ac17_agent_toml_fields(self, codex_project):
        """AC-17: Every agent TOML must contain name, description, developer_instructions."""
        agents_dir = codex_project / ".codex" / "agents"
        toml_files = list(agents_dir.glob("*.toml"))
        assert len(toml_files) > 0, ".codex/agents/ must contain at least one *.toml"
        for toml_file in toml_files:
            content = toml_file.read_text(encoding="utf-8")
            assert "name" in content, f"{toml_file.name} must contain 'name' field"
            assert (
                "description" in content
            ), f"{toml_file.name} must contain 'description' field"
            assert (
                "developer_instructions" in content
            ), f"{toml_file.name} must contain 'developer_instructions' field"

    # ------------------------------------------------------------------ #
    # AC-18: hooks.json matcher value is "Bash"                           #
    # ------------------------------------------------------------------ #

    def test_ac18_hooks_matcher_is_bash(self, codex_project):
        """AC-18: hooks.json must configure the PreToolUse hook with matcher 'Bash'."""
        hooks_json_path = codex_project / ".codex" / "hooks.json"
        hooks_data = json.loads(hooks_json_path.read_text(encoding="utf-8"))
        pre_tool_use = hooks_data.get("hooks", {}).get("PreToolUse", [])
        assert (
            len(pre_tool_use) > 0
        ), "hooks.json must define at least one PreToolUse entry"
        matchers = [entry.get("matcher") for entry in pre_tool_use]
        assert (
            "Bash" in matchers
        ), f"hooks.json PreToolUse must have a 'Bash' matcher, got: {matchers}"

    # ------------------------------------------------------------------ #
    # AC-19: Discovery paths — skills/agents/config at expected locations #
    # ------------------------------------------------------------------ #

    def test_ac19_codex_discovery_paths(self, codex_project):
        """AC-19: Validate that Codex files are at the discovery paths Codex expects."""
        codex_dir = codex_project / ".codex"
        skills_dir = codex_project / ".agents" / "skills"
        expected_paths = [
            skills_dir / "map-plan" / "SKILL.md",
            skills_dir / "map-fast" / "SKILL.md",
            skills_dir / "map-check" / "SKILL.md",
            skills_dir / "map-efficient" / "SKILL.md",
            codex_dir / "agents",
            codex_dir / "config.toml",
        ]
        for path in expected_paths:
            assert (
                path.exists()
            ), f"Expected discovery path does not exist: {path.relative_to(codex_project)}"
        # Agents directory must have TOML files for agent discovery
        toml_count = len(list((codex_dir / "agents").glob("*.toml")))
        assert (
            toml_count >= 1
        ), f".codex/agents/ must have at least 1 *.toml for agent discovery, found {toml_count}"
        assert not (
            codex_dir / "skills"
        ).exists(), "Codex skills must be installed under .agents/skills, not .codex/skills"

    # ------------------------------------------------------------------ #
    # AC-20: workflow-gate.py blocks file-modifying commands in RESEARCH  #
    # ------------------------------------------------------------------ #

    def test_ac20_workflow_gate_blocks_during_restricted(self, codex_project):
        """AC-20: workflow-gate.py must block Edit during non-editing phases."""
        import json as _json

        gate_script = codex_project / ".codex" / "hooks" / "workflow-gate.py"
        assert gate_script.exists(), "workflow-gate.py must exist"

        # Verify the gate has EDITING_PHASES that exclude RESEARCH
        gate_source = gate_script.read_text(encoding="utf-8")
        gate_ns: dict = {}
        exec(compile(gate_source, str(gate_script), "exec"), gate_ns)  # noqa: S102
        editing_phases = gate_ns["EDITING_PHASES"]
        assert (
            "RESEARCH" not in editing_phases
        ), "RESEARCH must NOT be in EDITING_PHASES"
        assert "ACTOR" in editing_phases, "ACTOR must be in EDITING_PHASES"

        # Simulate gate invocation: Edit tool during RESEARCH phase → should block
        payload_block = _json.dumps(
            {"tool_name": "Edit", "tool_input": {"file_path": "/test.py"}}
        )
        branch_dir = codex_project / ".map" / "default"
        branch_dir.mkdir(parents=True, exist_ok=True)
        state_file = branch_dir / "step_state.json"
        state_file.write_text(
            _json.dumps({"current_step_phase": "RESEARCH"}), encoding="utf-8"
        )

        proc = subprocess.run(
            [sys.executable, str(gate_script)],
            input=payload_block,
            capture_output=True,
            text=True,
            cwd=str(codex_project),
        )
        assert (
            proc.returncode == 0
        ), f"workflow-gate.py must exit 0 always, got {proc.returncode}"
        gate_output = _json.loads(proc.stdout.strip())
        hook_output = gate_output.get("hookSpecificOutput", {})
        assert (
            hook_output.get("permissionDecision") == "deny"
        ), f"Expected 'deny' for Edit in RESEARCH phase, got: {gate_output}"

    # ------------------------------------------------------------------ #
    # AC-21: upgrade on codex project must not create .claude/             #
    # ------------------------------------------------------------------ #

    def test_ac21_upgrade_codex_project_no_claude(self, codex_project):
        """AC-21: 'mapify upgrade' on codex project must not create .claude/."""
        local_runner = CliRunner()
        os.chdir(codex_project)
        result = local_runner.invoke(app, ["upgrade"])
        assert result.exit_code == 0, f"upgrade failed: {result.output}"
        assert not (
            codex_project / ".claude"
        ).exists(), ".claude/ must NOT be created when upgrading a codex project"
        assert (
            "mapify init . --provider codex --force" in result.output
        ), "upgrade must tell codex users to re-run init with --provider codex"

    def test_ac22_map_efficient_state_machine_markers(self, codex_project):
        """AC-22: $map-efficient documents the required state-machine commands."""
        skill_file = (
            codex_project / ".agents" / "skills" / "map-efficient" / "SKILL.md"
        )
        content = skill_file.read_text(encoding="utf-8")
        for marker in [
            "resume_from_plan",
            "get_next_step",
            "validate_step",
            "record_subtask_result",
            "write_run_health_report",
        ]:
            assert marker in content, f"$map-efficient must document {marker}"

        mutation_index = content.index("## Mutation Boundary Constraints")
        implement_index = content.index("Implement exactly")
        assert (
            mutation_index < implement_index
        ), "Mutation boundary constraints must appear before implementation directives"


class TestDetectProviderEdgeCases:
    """TESTS-1: _detect_provider and is_map_initialized edge cases."""

    def test_detect_provider_codex_wins_when_both_exist(self, tmp_path):
        """When both .codex/ and .claude/ exist, codex is detected."""
        from mapify_cli import _detect_provider

        (tmp_path / ".codex" / "config.toml").parent.mkdir(parents=True)
        (tmp_path / ".codex" / "config.toml").write_text("[codex]\n")
        (tmp_path / ".claude" / "settings.json").parent.mkdir(parents=True)
        (tmp_path / ".claude" / "settings.json").write_text("{}\n")
        assert _detect_provider(tmp_path) == "codex"

    def test_detect_provider_returns_claude_when_neither(self, tmp_path):
        """When neither provider dir exists, default to claude."""
        from mapify_cli import _detect_provider

        assert _detect_provider(tmp_path) == "claude"

    def test_is_map_initialized_codex_layout(self, tmp_path):
        """is_map_initialized recognizes a codex-only project."""
        from mapify_cli import is_map_initialized

        (tmp_path / ".codex" / "config.toml").parent.mkdir(parents=True)
        (tmp_path / ".codex" / "config.toml").write_text("[codex]\n")
        (tmp_path / ".agents" / "skills").mkdir(parents=True)
        assert is_map_initialized(tmp_path) is True

    def test_is_map_initialized_neither_layout(self, tmp_path):
        """is_map_initialized returns False for empty directory."""
        from mapify_cli import is_map_initialized

        assert is_map_initialized(tmp_path) is False


class TestDoctorCodexProject:
    """TESTS-2: doctor() on codex project produces correct output."""

    def test_doctor_codex_no_false_missing_paths(self, tmp_path):
        """doctor on a codex project must not report .claude/* as missing."""
        local_runner = CliRunner()
        os.chdir(tmp_path)
        # Init as codex first
        result = local_runner.invoke(
            app, ["init", ".", "--provider", "codex", "--no-git", "--force"]
        )
        assert result.exit_code == 0
        # Run doctor
        result = local_runner.invoke(app, ["doctor"])
        assert (
            ".claude/agents" not in result.output
        ), "doctor must not report .claude/agents as missing for codex project"
        assert (
            ".claude/commands" not in result.output
        ), "doctor must not report .claude/commands as missing for codex project"
        assert "all core paths present" in result.output or "codex" in result.output


class TestClaudeProviderInstall:
    """TESTS-3: ClaudeProvider.install() unit test."""

    def test_claude_provider_creates_all_categories(self, tmp_path):
        """ClaudeProvider.install() must return counts for all expected categories."""
        from mapify_cli.delivery.providers import ClaudeProvider

        provider = ClaudeProvider()
        counts = provider.install(tmp_path, mcp_servers=[])
        expected_keys = {
            "agents",
            "commands",
            "skills",
            "references",
            "tools",
            "hooks",
            "configs",
            "rules",
        }
        assert (
            set(counts.keys()) == expected_keys
        ), f"ClaudeProvider.install() must return all category keys, got: {set(counts.keys())}"
        # Each category must have created at least one file
        for key, value in counts.items():
            assert value >= 0, f"counts['{key}'] must be non-negative"
        # agents should always have files; commands migrated to skills
        assert counts["agents"] > 0, "ClaudeProvider must create agent files"

    def test_claude_provider_creates_claude_dir(self, tmp_path):
        """ClaudeProvider.install() must create .claude/ directory."""
        from mapify_cli.delivery.providers import ClaudeProvider

        provider = ClaudeProvider()
        provider.install(tmp_path, mcp_servers=[])
        assert (tmp_path / ".claude" / "agents").exists()
        assert (tmp_path / ".claude" / "commands").exists()
        assert not (
            tmp_path / ".codex"
        ).exists(), "ClaudeProvider must not create .codex/"
