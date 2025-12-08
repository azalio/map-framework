"""
Unit tests for hooks merge logic in mapify init command.

Tests load_settings_with_merge() and merge_hooks_settings() functions
covering all edge cases specified in ST-003 acceptance criteria.
"""

import json
import pytest
from unittest import mock
from mapify_cli import load_settings_with_merge, merge_hooks_settings


@pytest.fixture
def template_settings():
    """Template settings with default hooks structure."""
    return {
        "hooks": {
            "UserPromptSubmit": [
                {"matcher": "Bash\\(.*\\)", "message": "Template validation message"}
            ],
            "SessionStart": [{"matcher": "", "message": "Session start template"}],
        }
    }


@pytest.fixture
def user_settings_with_hooks():
    """Existing user settings with custom hooks."""
    return {
        "permissions": {"auto_approve": ["Read", "Glob"]},
        "hooks": {
            "UserPromptSubmit": [
                {"matcher": "Write\\(.*\\)", "message": "User custom write hook"}
            ],
            "PreToolUse": [
                {"matcher": "Edit\\(.*\\)", "message": "User custom edit hook"}
            ],
        },
    }


class TestLoadSettingsWithMerge:
    """Test load_settings_with_merge() edge cases."""

    def test_valid_json_file_returns_dict(self, tmp_path):
        """Valid JSON file returns parsed dictionary."""
        settings_file = tmp_path / "settings.json"
        test_data = {"key": "value", "nested": {"data": 123}}

        with open(settings_file, "w", encoding="utf-8") as f:
            json.dump(test_data, f)

        result = load_settings_with_merge(settings_file)

        assert result == test_data
        assert isinstance(result, dict)

    def test_missing_file_returns_empty_dict(self, tmp_path):
        """Missing file returns empty dict without error."""
        settings_file = tmp_path / "nonexistent.json"

        result = load_settings_with_merge(settings_file)

        assert result == {}
        assert isinstance(result, dict)

    def test_corrupted_json_returns_empty_dict_with_warning(self, tmp_path):
        """Corrupted JSON returns empty dict and prints warning."""
        settings_file = tmp_path / "settings.json"

        # Write invalid JSON
        with open(settings_file, "w", encoding="utf-8") as f:
            f.write('{"invalid": json syntax}')

        with mock.patch("mapify_cli.console.print") as mock_print:
            result = load_settings_with_merge(settings_file)

        assert result == {}
        mock_print.assert_called_once()
        warning_message = str(mock_print.call_args[0][0])
        assert "Warning" in warning_message
        assert "Corrupted" in warning_message
        assert "settings.json" in warning_message

    def test_empty_file_returns_empty_dict_with_warning(self, tmp_path):
        """Empty file returns empty dict and prints warning."""
        settings_file = tmp_path / "settings.json"

        # Create empty file
        settings_file.touch()

        with mock.patch("mapify_cli.console.print") as mock_print:
            result = load_settings_with_merge(settings_file)

        assert result == {}
        mock_print.assert_called_once()

    def test_file_with_whitespace_only_returns_empty_dict(self, tmp_path):
        """File with only whitespace returns empty dict with warning."""
        settings_file = tmp_path / "settings.json"

        with open(settings_file, "w", encoding="utf-8") as f:
            f.write("   \n\t  ")

        with mock.patch("mapify_cli.console.print") as mock_print:
            result = load_settings_with_merge(settings_file)

        assert result == {}
        mock_print.assert_called_once()


class TestMergeHooksSettings:
    """Test merge_hooks_settings() edge cases."""

    def test_empty_existing_returns_template_hooks(self, template_settings):
        """Empty existing settings returns template hooks entirely."""
        existing = {}

        result = merge_hooks_settings(existing, template_settings)

        assert "hooks" in result
        assert result["hooks"] == template_settings["hooks"]
        assert "UserPromptSubmit" in result["hooks"]
        assert "SessionStart" in result["hooks"]

    def test_empty_template_preserves_existing(self, user_settings_with_hooks):
        """Empty template preserves existing settings unchanged."""
        template = {}

        result = merge_hooks_settings(user_settings_with_hooks, template)

        assert result == user_settings_with_hooks
        assert "hooks" in result
        assert "PreToolUse" in result["hooks"]

    def test_matcher_deduplication_no_duplicates(self):
        """Matcher deduplication prevents duplicate hooks when same matcher."""
        existing = {
            "hooks": {
                "UserPromptSubmit": [
                    {"matcher": "Bash\\(.*\\)", "message": "User existing bash hook"}
                ]
            }
        }

        template = {
            "hooks": {
                "UserPromptSubmit": [
                    {
                        "matcher": "Bash\\(.*\\)",
                        "message": "Template bash hook (should not duplicate)",
                    }
                ]
            }
        }

        result = merge_hooks_settings(existing, template)

        # Should have only 1 hook (existing preserved, template not added)
        assert len(result["hooks"]["UserPromptSubmit"]) == 1
        assert (
            result["hooks"]["UserPromptSubmit"][0]["message"]
            == "User existing bash hook"
        )

    def test_custom_hooks_preserved(self, template_settings):
        """User's custom hooks not in template are preserved."""
        existing = {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "sqlite3\\(.*\\)",
                        "message": "User custom SQLite validation",
                    }
                ],
                "Stop": [{"matcher": "", "message": "User custom stop hook"}],
            }
        }

        result = merge_hooks_settings(existing, template_settings)

        # User's PreToolUse and Stop hooks should be preserved
        assert "PreToolUse" in result["hooks"]
        assert len(result["hooks"]["PreToolUse"]) == 1
        assert (
            result["hooks"]["PreToolUse"][0]["message"]
            == "User custom SQLite validation"
        )

        assert "Stop" in result["hooks"]
        assert len(result["hooks"]["Stop"]) == 1

        # Template hooks should be added
        assert "UserPromptSubmit" in result["hooks"]
        assert "SessionStart" in result["hooks"]

    def test_permissions_preserved(self, user_settings_with_hooks, template_settings):
        """Top-level keys like permissions are unchanged."""
        result = merge_hooks_settings(user_settings_with_hooks, template_settings)

        assert "permissions" in result
        assert result["permissions"] == user_settings_with_hooks["permissions"]
        assert result["permissions"]["auto_approve"] == ["Read", "Glob"]

    def test_no_matcher_full_json_comparison_works(self):
        """Hooks without matcher use full JSON comparison for deduplication."""
        existing = {
            "hooks": {
                "SessionStart": [
                    {
                        "matcher": "",
                        "message": "Welcome message",
                        "custom_field": "value",
                    }
                ]
            }
        }

        template_duplicate = {
            "hooks": {
                "SessionStart": [
                    {
                        "matcher": "",
                        "message": "Welcome message",
                        "custom_field": "value",
                    }
                ]
            }
        }

        template_different = {
            "hooks": {
                "SessionStart": [
                    {
                        "matcher": "",
                        "message": "Different welcome message",
                        "custom_field": "value",
                    }
                ]
            }
        }

        # Exact duplicate should not be added
        result_duplicate = merge_hooks_settings(existing, template_duplicate)
        assert len(result_duplicate["hooks"]["SessionStart"]) == 1

        # Different hook should be added
        result_different = merge_hooks_settings(existing, template_different)
        assert len(result_different["hooks"]["SessionStart"]) == 2

    def test_malformed_template_hooks_skipped_with_warning(self):
        """Malformed template hooks (not a list) are skipped with warning."""
        existing = {"hooks": {"UserPromptSubmit": []}}

        template = {
            "hooks": {
                "UserPromptSubmit": "not a list",  # Malformed
                "SessionStart": [{"matcher": "", "message": "Valid"}],
            }
        }

        with mock.patch("mapify_cli.console.print") as mock_print:
            result = merge_hooks_settings(existing, template)

        # UserPromptSubmit should remain unchanged
        assert result["hooks"]["UserPromptSubmit"] == []

        # SessionStart should be added
        assert "SessionStart" in result["hooks"]

        # Warning should be printed
        mock_print.assert_called_once()
        warning_message = str(mock_print.call_args[0][0])
        assert "Warning" in warning_message
        assert "malformed" in warning_message.lower()

    def test_malformed_user_hooks_reset_with_warning(self, template_settings):
        """Malformed user hooks (not a list) are reset with warning."""
        existing = {"hooks": {"UserPromptSubmit": {"not": "a list"}}}  # Malformed

        with mock.patch("mapify_cli.console.print") as mock_print:
            result = merge_hooks_settings(existing, template_settings)

        # UserPromptSubmit should be reset and template added
        assert isinstance(result["hooks"]["UserPromptSubmit"], list)
        assert len(result["hooks"]["UserPromptSubmit"]) == 1
        assert result["hooks"]["UserPromptSubmit"][0]["matcher"] == "Bash\\(.*\\)"

        # Warning should be printed
        mock_print.assert_called_once()
        warning_message = str(mock_print.call_args[0][0])
        assert "Warning" in warning_message
        assert "Resetting" in warning_message

    def test_no_hooks_in_existing_adds_template_hooks(self, template_settings):
        """If user has no hooks section at all, template hooks added entirely."""
        existing = {"permissions": {"auto_approve": ["Read"]}}

        result = merge_hooks_settings(existing, template_settings)

        assert "hooks" in result
        assert result["hooks"] == template_settings["hooks"]
        assert "permissions" in result  # Preserved

    def test_no_hooks_in_template_preserves_existing(self):
        """If template has no hooks, existing hooks unchanged but permissions merged."""
        existing = {
            "hooks": {"UserPromptSubmit": [{"matcher": "Test", "message": "User hook"}]}
        }

        template = {"permissions": {"allow": ["Write"]}}

        result = merge_hooks_settings(existing, template)

        assert result["hooks"] == existing["hooks"]
        # Template permissions ARE now merged (additive merge for permissions.allow)
        assert "permissions" in result
        assert "Write" in result["permissions"]["allow"]

    def test_hook_type_not_in_existing_adds_template_array(self, template_settings):
        """If user doesn't have specific hook type, template's entire array added."""
        existing = {
            "hooks": {"PreToolUse": [{"matcher": "Edit", "message": "User edit hook"}]}
        }

        result = merge_hooks_settings(existing, template_settings)

        # User's PreToolUse preserved
        assert "PreToolUse" in result["hooks"]
        assert len(result["hooks"]["PreToolUse"]) == 1

        # Template's UserPromptSubmit and SessionStart added
        assert "UserPromptSubmit" in result["hooks"]
        assert len(result["hooks"]["UserPromptSubmit"]) == 1
        assert result["hooks"]["UserPromptSubmit"][0]["matcher"] == "Bash\\(.*\\)"

        assert "SessionStart" in result["hooks"]
        assert len(result["hooks"]["SessionStart"]) == 1

    def test_deep_copy_prevents_mutation(
        self, user_settings_with_hooks, template_settings
    ):
        """Merge doesn't mutate original existing_settings."""
        import copy

        original_existing = copy.deepcopy(user_settings_with_hooks)

        result = merge_hooks_settings(user_settings_with_hooks, template_settings)

        # Original should be unchanged
        assert user_settings_with_hooks == original_existing

        # Result should have merged hooks
        assert "UserPromptSubmit" in result["hooks"]
        assert len(result["hooks"]["UserPromptSubmit"]) == 2  # User + template

    def test_multiple_hooks_same_type_all_preserved(self):
        """Multiple hooks of same type all preserved, duplicates filtered."""
        existing = {
            "hooks": {
                "UserPromptSubmit": [
                    {"matcher": "Read\\(.*\\)", "message": "User read"},
                    {"matcher": "Write\\(.*\\)", "message": "User write"},
                ]
            }
        }

        template = {
            "hooks": {
                "UserPromptSubmit": [
                    {"matcher": "Bash\\(.*\\)", "message": "Template bash"},
                    {"matcher": "Read\\(.*\\)", "message": "Template read (duplicate)"},
                ]
            }
        }

        result = merge_hooks_settings(existing, template)

        # Should have 3 hooks: User read, User write, Template bash
        # Template read should NOT be added (duplicate matcher)
        assert len(result["hooks"]["UserPromptSubmit"]) == 3

        matchers = [hook["matcher"] for hook in result["hooks"]["UserPromptSubmit"]]
        assert "Read\\(.*\\)" in matchers
        assert "Write\\(.*\\)" in matchers
        assert "Bash\\(.*\\)" in matchers

    def test_empty_matcher_string_uses_json_comparison(self):
        """Empty string matcher "" uses full JSON comparison."""
        existing = {"hooks": {"SessionStart": [{"matcher": "", "message": "Msg A"}]}}

        template = {
            "hooks": {
                "SessionStart": [
                    {"matcher": "", "message": "Msg A"},  # Duplicate
                    {"matcher": "", "message": "Msg B"},  # Different
                ]
            }
        }

        result = merge_hooks_settings(existing, template)

        # Should have 2 hooks: existing Msg A, template Msg B
        # Template Msg A should not be added (duplicate via JSON comparison)
        assert len(result["hooks"]["SessionStart"]) == 2

        messages = [hook["message"] for hook in result["hooks"]["SessionStart"]]
        assert messages.count("Msg A") == 1
        assert "Msg B" in messages

    def test_non_dict_hook_groups_skipped(self):
        """Non-dict hook groups in template are skipped gracefully."""
        existing = {"hooks": {"UserPromptSubmit": []}}

        template = {
            "hooks": {
                "UserPromptSubmit": [
                    "not a dict",
                    {"matcher": "Valid", "message": "Valid hook"},
                    123,
                    None,
                ]
            }
        }

        result = merge_hooks_settings(existing, template)

        # Only valid dict hook should be added
        assert len(result["hooks"]["UserPromptSubmit"]) == 1
        assert result["hooks"]["UserPromptSubmit"][0]["message"] == "Valid hook"

    def test_complex_nested_structure_preserved(self):
        """Complex nested structures in hooks preserved correctly."""
        existing = {
            "permissions": {
                "auto_approve": ["Read", "Write"],
                "require_approval": ["Bash"],
            },
            "hooks": {
                "UserPromptSubmit": [
                    {
                        "matcher": "Complex\\(.*\\)",
                        "message": "Complex hook",
                        "nested": {"data": [1, 2, 3], "config": {"key": "value"}},
                    }
                ]
            },
            "custom_section": {"user_data": "should be preserved"},
        }

        template = {
            "hooks": {
                "UserPromptSubmit": [{"matcher": "Simple", "message": "Simple hook"}]
            }
        }

        result = merge_hooks_settings(existing, template)

        # All existing structure preserved
        assert result["permissions"] == existing["permissions"]
        assert result["custom_section"] == existing["custom_section"]

        # Existing hook preserved with nested structure
        complex_hook = [
            h
            for h in result["hooks"]["UserPromptSubmit"]
            if h.get("matcher") == "Complex\\(.*\\)"
        ][0]
        assert complex_hook["nested"]["data"] == [1, 2, 3]
        assert complex_hook["nested"]["config"]["key"] == "value"

        # Template hook added
        assert len(result["hooks"]["UserPromptSubmit"]) == 2


class TestPermissionsMerge:
    """Tests for permissions.allow additive merging behavior."""

    def test_merge_into_empty_permissions(self):
        """Template permissions added when user has no permissions."""
        existing = {"hooks": {}}
        template = {"permissions": {"allow": ["Bash(test:*)", "mcp__cipher__search"]}}

        result = merge_hooks_settings(existing, template)

        assert "permissions" in result
        assert "allow" in result["permissions"]
        assert "Bash(test:*)" in result["permissions"]["allow"]
        assert "mcp__cipher__search" in result["permissions"]["allow"]

    def test_merge_preserves_existing_rules(self):
        """User's existing allow rules preserved during merge."""
        existing = {"permissions": {"allow": ["Bash(custom:*)", "Read(~/.zshrc)"]}}
        template = {"permissions": {"allow": ["Bash(test:*)", "mcp__cipher__search"]}}

        result = merge_hooks_settings(existing, template)

        # User rules preserved
        assert "Bash(custom:*)" in result["permissions"]["allow"]
        assert "Read(~/.zshrc)" in result["permissions"]["allow"]
        # Template rules added
        assert "Bash(test:*)" in result["permissions"]["allow"]
        assert "mcp__cipher__search" in result["permissions"]["allow"]

    def test_merge_no_duplicates(self):
        """Duplicate rules not added during merge."""
        existing = {"permissions": {"allow": ["Bash(test:*)", "Bash(custom:*)"]}}
        template = {"permissions": {"allow": ["Bash(test:*)", "mcp__cipher__search"]}}

        result = merge_hooks_settings(existing, template)

        # Should have 3 unique rules, not 4
        assert len(result["permissions"]["allow"]) == 3
        assert result["permissions"]["allow"].count("Bash(test:*)") == 1

    def test_preserves_deny_rules(self):
        """User's deny rules preserved unchanged."""
        existing = {
            "permissions": {
                "allow": ["Bash(git:*)"],
                "deny": ["Bash(rm:*)", "Read(.env)"],
            }
        }
        template = {"permissions": {"allow": ["mcp__cipher__search"]}}

        result = merge_hooks_settings(existing, template)

        # Deny rules unchanged
        assert result["permissions"]["deny"] == ["Bash(rm:*)", "Read(.env)"]
        # Allow rules merged
        assert "Bash(git:*)" in result["permissions"]["allow"]
        assert "mcp__cipher__search" in result["permissions"]["allow"]

    def test_malformed_allow_reset_with_warning(self, capsys):
        """Malformed permissions.allow reset to empty list with warning."""
        existing = {"permissions": {"allow": "not a list"}}  # Invalid - string
        template = {"permissions": {"allow": ["mcp__cipher__search"]}}

        result = merge_hooks_settings(existing, template)

        # Should have template rule
        assert "mcp__cipher__search" in result["permissions"]["allow"]
        # Warning should be printed
        captured = capsys.readouterr()
        assert (
            "malformed" in captured.out.lower()
            or len(result["permissions"]["allow"]) == 1
        )

    def test_no_permissions_in_template_preserves_existing(self):
        """If template has no permissions, existing permissions unchanged."""
        existing = {
            "permissions": {"allow": ["Bash(custom:*)"], "deny": ["Bash(rm:*)"]}
        }
        template = {"hooks": {"UserPromptSubmit": []}}

        result = merge_hooks_settings(existing, template)

        assert result["permissions"] == existing["permissions"]
