#!/usr/bin/env python3
"""
Pytest tests for .claude/hooks/block-dangerous.sh PreToolUse hook.
Tests all validation criteria and edge cases.
"""
import json
import subprocess
from pathlib import Path

import pytest

# Path to the hook script
HOOK_PATH = Path(__file__).parent.parent.parent / ".claude" / "hooks" / "block-dangerous.sh"


def run_hook(command: str) -> tuple[int, str, str]:
    """Execute the hook with given bash command."""
    input_data = {
        "tool_name": "Bash",
        "tool_input": {"command": command}
    }
    result = subprocess.run(
        ["bash", str(HOOK_PATH)],
        input=json.dumps(input_data),
        capture_output=True,
        text=True
    )
    return result.returncode, result.stdout, result.stderr


# =============================================================================
# Validation Criteria Tests
# =============================================================================

class TestValidationCriteria:
    """Tests for the validation criteria from task decomposition."""

    def test_criterion_1_rm_rf_blocked(self):
        """VC1: Bash command 'rm -rf /' is blocked with exit code 2."""
        exit_code, _, stderr = run_hook("rm -rf /")
        assert exit_code == 2, f"Expected exit 2, got {exit_code}"
        assert "Blocked" in stderr, f"Expected 'Blocked' in stderr: {stderr}"

    def test_criterion_2_force_push_main_blocked(self):
        """VC2: git push --force origin main is blocked."""
        exit_code, _, stderr = run_hook("git push --force origin main")
        assert exit_code == 2, f"Expected exit 2, got {exit_code}"
        assert "Blocked" in stderr

    def test_criterion_3_reset_hard_blocked(self):
        """VC3: git reset --hard is blocked."""
        exit_code, _, stderr = run_hook("git reset --hard")
        assert exit_code == 2, f"Expected exit 2, got {exit_code}"
        assert "Blocked" in stderr

    def test_criterion_4_force_push_feature_allowed(self):
        """VC4: git push --force origin feature-branch is allowed."""
        exit_code, _, _ = run_hook("git push --force origin feature-branch")
        assert exit_code == 0, "Force push to feature branch should be allowed"

    def test_criterion_5_legitimate_allowed(self):
        """VC5: Legitimate commands like 'pytest' are allowed."""
        exit_code, _, _ = run_hook("pytest")
        assert exit_code == 0, "pytest should be allowed"


# =============================================================================
# rm -rf Blocking Tests
# =============================================================================

class TestRmRfBlocking:
    """Test rm -rf and variants are blocked."""

    @pytest.mark.parametrize("command", [
        "rm -rf /",
        "rm -rf ~",
        "rm -rf .",
        "rm -rf /home/user",
        "rm -rf ./src",
        "rm -fr /",         # reversed flags
        "rm -r -f /tmp",    # separated flags
        "rm -f -r /tmp",
    ])
    def test_rm_rf_variants_blocked(self, command):
        exit_code, _, stderr = run_hook(command)
        assert exit_code == 2, f"'{command}' should be blocked"
        assert "rm -rf" in stderr.lower() or "blocked" in stderr.lower()

    def test_rm_without_rf_allowed(self):
        """rm without -rf should be allowed."""
        exit_code, _, _ = run_hook("rm file.txt")
        assert exit_code == 0, "rm without -rf should be allowed"

    def test_rm_r_only_allowed(self):
        """rm -r without -f should be allowed (prompts for confirmation)."""
        exit_code, _, _ = run_hook("rm -r directory")
        assert exit_code == 0, "rm -r (without -f) should be allowed"


# =============================================================================
# Git Force Push Blocking Tests
# =============================================================================

class TestGitForcePushBlocking:
    """Test git force push to main/master is blocked."""

    @pytest.mark.parametrize("command", [
        "git push --force origin main",
        "git push -f origin main",
        "git push --force origin master",
        "git push -f origin master",
        "git push origin main --force",
        "git push origin master -f",
        "git push --force upstream main",
        "git push -f upstream master",
    ])
    def test_force_push_protected_blocked(self, command):
        exit_code, _, stderr = run_hook(command)
        assert exit_code == 2, f"'{command}' should be blocked"
        assert "Blocked" in stderr

    @pytest.mark.parametrize("command", [
        "git push --force origin feature-branch",
        "git push -f origin my-feature",
        "git push --force origin fix/bug-123",
        "git push origin develop --force",
        "git push --force origin dev",
    ])
    def test_force_push_feature_allowed(self, command):
        exit_code, _, _ = run_hook(command)
        assert exit_code == 0, f"'{command}' should be allowed"

    def test_regular_push_main_allowed(self):
        """Regular push (without --force) to main should be allowed."""
        exit_code, _, _ = run_hook("git push origin main")
        assert exit_code == 0, "Regular push to main should be allowed"


# =============================================================================
# Git Reset Hard Blocking Tests
# =============================================================================

class TestGitResetHardBlocking:
    """Test git reset --hard is blocked."""

    @pytest.mark.parametrize("command", [
        "git reset --hard",
        "git reset --hard HEAD",
        "git reset --hard HEAD~1",
        "git reset --hard origin/main",
        "git reset --hard abc123",
    ])
    def test_reset_hard_variants_blocked(self, command):
        exit_code, _, stderr = run_hook(command)
        assert exit_code == 2, f"'{command}' should be blocked"
        assert "Blocked" in stderr

    @pytest.mark.parametrize("command", [
        "git reset --soft HEAD~1",
        "git reset --mixed HEAD~1",
        "git reset HEAD~1",
        "git reset HEAD -- file.txt",
    ])
    def test_reset_soft_allowed(self, command):
        exit_code, _, _ = run_hook(command)
        assert exit_code == 0, f"'{command}' should be allowed"


# =============================================================================
# Legitimate Commands Tests
# =============================================================================

class TestLegitimateCommands:
    """Test that safe commands are allowed."""

    @pytest.mark.parametrize("command", [
        "pytest",
        "pytest -v tests/",
        "python -m pytest",
        "make lint",
        "make test",
        "npm install",
        "npm run build",
        "go test ./...",
        "cargo build",
        "git status",
        "git diff",
        "git log --oneline",
        "git add .",
        "git commit -m 'test'",
        "git push origin feature",
        "ls -la",
        "cat file.txt",
        "echo hello",
        "cd /tmp && ls",
    ])
    def test_safe_commands_allowed(self, command):
        exit_code, _, stderr = run_hook(command)
        assert exit_code == 0, f"'{command}' should be allowed. stderr: {stderr}"


# =============================================================================
# Tool Interception Tests
# =============================================================================

class TestToolInterception:
    """Test that only Bash tool is intercepted."""

    def test_non_bash_tool_allowed(self):
        """Non-Bash tools should pass through."""
        input_data = {
            "tool_name": "Read",
            "tool_input": {"file_path": "rm -rf /"}
        }
        result = subprocess.run(
            ["bash", str(HOOK_PATH)],
            input=json.dumps(input_data),
            capture_output=True,
            text=True
        )
        assert result.returncode == 0, "Non-Bash tools should be allowed"


# =============================================================================
# Error Handling Tests
# =============================================================================

class TestErrorHandling:
    """Test edge cases and error handling."""

    def test_empty_command(self):
        """Empty command should be allowed."""
        exit_code, _, _ = run_hook("")
        assert exit_code == 0

    def test_missing_command_field(self):
        """Missing command field should be allowed."""
        input_data = {"tool_name": "Bash", "tool_input": {}}
        result = subprocess.run(
            ["bash", str(HOOK_PATH)],
            input=json.dumps(input_data),
            capture_output=True,
            text=True
        )
        assert result.returncode == 0


# =============================================================================
# Additional Dangerous Commands Tests
# =============================================================================

class TestAdditionalDangerousCommands:
    """Test additional dangerous commands are blocked."""

    @pytest.mark.parametrize("command", [
        "chmod -R 777 /",
        "chown -R root:root /",
    ])
    def test_recursive_permissions_on_root_blocked(self, command):
        exit_code, _, _ = run_hook(command)
        assert exit_code == 2, f"'{command}' should be blocked"

    def test_dd_to_device_blocked(self):
        """dd writing to /dev/ should be blocked."""
        exit_code, _, _ = run_hook("dd if=/dev/zero of=/dev/sda")
        assert exit_code == 2, "dd to device should be blocked"

    def test_mkfs_blocked(self):
        """mkfs should be blocked."""
        exit_code, _, _ = run_hook("mkfs.ext4 /dev/sda1")
        assert exit_code == 2, "mkfs should be blocked"


# =============================================================================
# Output Format Tests
# =============================================================================

class TestOutputFormat:
    """Test that error output follows expected JSON structure."""

    def test_error_json_structure(self):
        """Blocked command should output valid JSON to stderr."""
        _, _, stderr = run_hook("rm -rf /")
        error_data = json.loads(stderr)
        assert "hookSpecificOutput" in error_data
        assert error_data["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
        assert "error" in error_data["hookSpecificOutput"]
        assert "Blocked" in error_data["hookSpecificOutput"]["error"]
