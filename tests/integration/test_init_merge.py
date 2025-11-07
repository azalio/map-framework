"""
Integration test for mapify init hooks merge functionality.

Tests that running `mapify init` preserves user customizations in settings.json
while adding new template hooks.
"""

import json
from pathlib import Path
import pytest
from mapify_cli import install_hooks


@pytest.fixture
def mock_project(tmp_path):
    """Create a mock project directory with .claude structure."""
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    return tmp_path


@pytest.fixture
def user_custom_settings():
    """User's customized settings.json with permissions and custom hooks."""
    return {
        "$schema": "https://json.schemastore.org/claude-code-settings.json",
        "description": "User's custom configuration",
        "permissions": {
            "allow": ["Bash(git status:*)", "Bash(custom-command:*)"],
            "deny": ["Bash(rm:*)"],
        },
        "hooks": {
            "UserPromptSubmit": [
                {
                    "matcher": "custom-pattern",
                    "description": "User's custom hook",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "python3 /custom/script.py",
                            "timeout": 10,
                        }
                    ],
                }
            ],
            "PreToolUse": [
                {
                    "matcher": "Edit|Write",
                    "description": "User's validation hook",
                    "hooks": [
                        {
                            "type": "command",
                            "command": ".custom/hooks/validate.sh",
                            "timeout": 5,
                        }
                    ],
                }
            ],
        },
        "customKey": "userValue",
    }


class TestInitMerge:
    """Integration tests for mapify init merge behavior."""

    def test_fresh_install_creates_settings(self, mock_project):
        """Test that fresh install creates settings.json with template hooks."""
        # Run install_hooks
        hooks_count = install_hooks(mock_project, with_hooks=True)

        assert hooks_count > 0, "Should install hook scripts"

        # Verify settings.json created
        settings_file = mock_project / ".claude" / "settings.json"
        assert settings_file.exists(), "Should create settings.json"

        # Read and validate settings
        with open(settings_file, "r", encoding="utf-8") as f:
            settings = json.load(f)

        assert "hooks" in settings, "Should have hooks section"
        assert (
            "UserPromptSubmit" in settings["hooks"]
        ), "Should have UserPromptSubmit hooks"
        assert "SessionStart" in settings["hooks"], "Should have SessionStart hooks"

    def test_preserves_user_permissions(self, mock_project, user_custom_settings):
        """Test that user's permissions section is preserved during merge."""
        # Setup: Create existing settings with custom permissions
        settings_file = mock_project / ".claude" / "settings.json"
        with open(settings_file, "w", encoding="utf-8") as f:
            json.dump(user_custom_settings, f, indent=2)

        # Run install_hooks
        install_hooks(mock_project, with_hooks=True)

        # Verify permissions preserved
        with open(settings_file, "r", encoding="utf-8") as f:
            merged_settings = json.load(f)

        assert "permissions" in merged_settings, "Should preserve permissions section"
        assert (
            merged_settings["permissions"] == user_custom_settings["permissions"]
        ), "Permissions should be unchanged"

    def test_preserves_custom_hooks(self, mock_project, user_custom_settings):
        """Test that user's custom hooks are preserved during merge."""
        # Setup
        settings_file = mock_project / ".claude" / "settings.json"
        with open(settings_file, "w", encoding="utf-8") as f:
            json.dump(user_custom_settings, f, indent=2)

        # Run install_hooks
        install_hooks(mock_project, with_hooks=True)

        # Verify custom hooks preserved
        with open(settings_file, "r", encoding="utf-8") as f:
            merged_settings = json.load(f)

        # User's custom UserPromptSubmit hook should still be there
        user_prompt_hooks = merged_settings["hooks"]["UserPromptSubmit"]
        custom_hook = next(
            (h for h in user_prompt_hooks if h["matcher"] == "custom-pattern"), None
        )
        assert custom_hook is not None, "Should preserve user's custom hook"
        assert custom_hook["hooks"][0]["command"] == "python3 /custom/script.py"

        # User's PreToolUse hook should still be there
        assert (
            "PreToolUse" in merged_settings["hooks"]
        ), "Should preserve PreToolUse hooks"
        pre_tool_hooks = merged_settings["hooks"]["PreToolUse"]
        user_hook = next(
            (h for h in pre_tool_hooks if h["matcher"] == "Edit|Write"), None
        )
        assert user_hook is not None, "Should preserve user's PreToolUse hook"

    def test_adds_new_template_hooks(self, mock_project, user_custom_settings):
        """Test that new template hooks are added to existing settings."""
        # Setup
        settings_file = mock_project / ".claude" / "settings.json"
        with open(settings_file, "w", encoding="utf-8") as f:
            json.dump(user_custom_settings, f, indent=2)

        # Run install_hooks
        install_hooks(mock_project, with_hooks=True)

        # Verify template hooks added
        with open(settings_file, "r", encoding="utf-8") as f:
            merged_settings = json.load(f)

        # Should have SessionStart from template (not in user settings)
        assert (
            "SessionStart" in merged_settings["hooks"]
        ), "Should add SessionStart from template"

        # Should have MAP Framework UserPromptSubmit hook (matcher="") added
        user_prompt_hooks = merged_settings["hooks"]["UserPromptSubmit"]
        assert len(user_prompt_hooks) >= 2, "Should have both user and template hooks"

        # Find template hook (empty matcher)
        template_hook = next(
            (h for h in user_prompt_hooks if h.get("matcher") == ""), None
        )
        assert template_hook is not None, "Should add template hook with empty matcher"

    def test_preserves_custom_top_level_keys(self, mock_project, user_custom_settings):
        """Test that user's custom top-level keys are preserved."""
        # Setup
        settings_file = mock_project / ".claude" / "settings.json"
        with open(settings_file, "w", encoding="utf-8") as f:
            json.dump(user_custom_settings, f, indent=2)

        # Run install_hooks
        install_hooks(mock_project, with_hooks=True)

        # Verify custom keys preserved
        with open(settings_file, "r", encoding="utf-8") as f:
            merged_settings = json.load(f)

        assert "customKey" in merged_settings, "Should preserve custom top-level key"
        assert (
            merged_settings["customKey"] == "userValue"
        ), "Custom key value should be unchanged"
        assert (
            merged_settings["description"] == "User's custom configuration"
        ), "Should preserve user's description"

    def test_no_duplicate_hooks_created(self, mock_project):
        """Test that running init twice doesn't create duplicate hooks."""
        # First init
        install_hooks(mock_project, with_hooks=True)

        settings_file = mock_project / ".claude" / "settings.json"
        with open(settings_file, "r", encoding="utf-8") as f:
            first_settings = json.load(f)

        first_count = len(first_settings["hooks"]["UserPromptSubmit"])

        # Second init (simulating user running mapify init --force)
        install_hooks(mock_project, with_hooks=True)

        with open(settings_file, "r", encoding="utf-8") as f:
            second_settings = json.load(f)

        second_count = len(second_settings["hooks"]["UserPromptSubmit"])

        # Should have same count (no duplicates)
        assert (
            second_count == first_count
        ), f"Should not create duplicates: first={first_count}, second={second_count}"

    def test_handles_corrupted_existing_settings(self, mock_project):
        """Test that corrupted existing settings.json is handled gracefully."""
        # Setup: Create corrupted settings
        settings_file = mock_project / ".claude" / "settings.json"
        settings_file.write_text("{invalid json")

        # Run install_hooks (should not crash)
        hooks_count = install_hooks(mock_project, with_hooks=True)

        assert hooks_count > 0, "Should still install hooks"

        # Verify new settings created
        with open(settings_file, "r", encoding="utf-8") as f:
            settings = json.load(f)

        assert "hooks" in settings, "Should create valid settings despite corruption"
