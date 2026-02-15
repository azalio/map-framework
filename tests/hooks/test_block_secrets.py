#!/usr/bin/env python3
"""
Pytest tests for .claude/hooks/block-secrets.py PreToolUse hook.
Tests all validation criteria and edge cases.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

# Path to the hook script
HOOK_PATH = (
    Path(__file__).parent.parent.parent / ".claude" / "hooks" / "block-secrets.py"
)


def run_hook(tool_name: str, file_path: str) -> tuple[int, str, str]:
    """Execute the hook with given tool and file path."""
    input_data = {"tool_name": tool_name, "tool_input": {"file_path": file_path}}
    result = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps(input_data),
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout, result.stderr


def _parse_stdout(stdout: str) -> dict:
    stdout = (stdout or "").strip()
    if not stdout:
        return {}
    return json.loads(stdout)


def _assert_denied(payload: dict, expected_file_fragment: str | None = None) -> None:
    assert payload.get("hookSpecificOutput", {}).get("hookEventName") == "PreToolUse"
    assert payload["hookSpecificOutput"].get("permissionDecision") == "deny"
    reason = payload["hookSpecificOutput"].get("permissionDecisionReason", "")
    assert reason
    if expected_file_fragment:
        assert expected_file_fragment.lower() in reason.lower()


# =============================================================================
# Validation Criteria Tests
# =============================================================================


class TestValidationCriteria:
    """Tests for the 5 validation criteria from the task."""

    def test_criterion_1_env_blocked(self):
        """VC1: Read('.env') is blocked (permissionDecision=deny)."""
        exit_code, stdout, stderr = run_hook("Read", ".env")
        assert exit_code == 0, f"Expected exit 0. stderr: {stderr}"
        payload = _parse_stdout(stdout)
        _assert_denied(payload, expected_file_fragment=".env")

    def test_criterion_2_credentials_blocked(self):
        """VC2: Write('credentials.json') is blocked."""
        exit_code, stdout, stderr = run_hook("Write", "credentials.json")
        assert exit_code == 0, f"Expected exit 0. stderr: {stderr}"
        payload = _parse_stdout(stdout)
        _assert_denied(payload, expected_file_fragment="credentials.json")

    def test_criterion_3_legitimate_allowed(self):
        """VC3: Legitimate files like 'app.py' are allowed."""
        exit_code, _, _ = run_hook("Read", "app.py")
        assert exit_code == 0, "app.py should be allowed"

    def test_criterion_4_performance(self):
        """VC4: Hook execution completes in <100ms."""
        iterations = 10
        total_time = 0
        for _ in range(iterations):
            start = time.perf_counter()
            run_hook("Read", "app.py")
            total_time += time.perf_counter() - start
        avg_ms = (total_time / iterations) * 1000
        assert avg_ms < 100, f"Average {avg_ms:.2f}ms exceeds 100ms target"


# =============================================================================
# Sensitive File Blocking Tests
# =============================================================================


class TestEnvFiles:
    """Test .env file blocking."""

    @pytest.mark.parametrize(
        "filename",
        [
            ".env",
            ".env.local",
            ".env.production",
            ".env.development",
            ".env.test",
            ".ENV",  # case insensitive
        ],
    )
    def test_env_variants_blocked(self, filename):
        exit_code, stdout, stderr = run_hook("Read", filename)
        assert exit_code == 0, f"Expected exit 0. stderr: {stderr}"
        payload = _parse_stdout(stdout)
        _assert_denied(payload, expected_file_fragment=filename)


class TestCredentialFiles:
    """Test credential file blocking."""

    @pytest.mark.parametrize(
        "filename",
        [
            "credentials.json",
            "aws-credentials",
            "gcp_credentials.yaml",
            "database-credentials.txt",
            "CREDENTIALS.JSON",  # case insensitive
        ],
    )
    def test_credentials_blocked(self, filename):
        exit_code, stdout, stderr = run_hook("Read", filename)
        assert exit_code == 0, f"Expected exit 0. stderr: {stderr}"
        payload = _parse_stdout(stdout)
        _assert_denied(payload, expected_file_fragment=filename)


class TestSecretFiles:
    """Test secret file blocking."""

    @pytest.mark.parametrize(
        "filename",
        [
            "secrets.yaml",
            "secret-key.txt",
            "api_secret.json",
            "my-secret",
            "SECRET.yml",  # case insensitive
        ],
    )
    def test_secrets_blocked(self, filename):
        exit_code, stdout, stderr = run_hook("Read", filename)
        assert exit_code == 0, f"Expected exit 0. stderr: {stderr}"
        payload = _parse_stdout(stdout)
        _assert_denied(payload, expected_file_fragment=filename)


class TestPrivateKeys:
    """Test private key file blocking."""

    @pytest.mark.parametrize(
        "filename",
        [
            # PEM files
            "server.pem",
            "private.pem",
            "cert.PEM",
            # Specific .key files (private)
            "server_private.key",
            "app_secret.key",
            "deploy_rsa.key",
            "my_ecdsa.key",
            # SSH keys without extension
            "id_rsa",
            "id_dsa",
            "id_ecdsa",
            "id_ed25519",
            "deploy_rsa",
            # Certificates
            "cert.p12",
            "keystore.pfx",
            "app.keystore",
            "truststore.jks",
            "private.ppk",
        ],
    )
    def test_private_keys_blocked(self, filename):
        exit_code, stdout, stderr = run_hook("Read", filename)
        assert exit_code == 0, f"Expected exit 0. stderr: {stderr}"
        payload = _parse_stdout(stdout)
        _assert_denied(payload, expected_file_fragment=filename)


# =============================================================================
# Allowed File Tests (False Positive Prevention)
# =============================================================================


class TestPublicKeysAllowed:
    """Test that SSH public keys are NOT blocked (Monitor feedback #2)."""

    @pytest.mark.parametrize(
        "filename",
        [
            "id_rsa.pub",
            "id_ecdsa.pub",
            "id_ed25519.pub",
            "deploy_key.pub",
            "server.pub",
        ],
    )
    def test_public_keys_allowed(self, filename):
        exit_code, _, stderr = run_hook("Read", filename)
        assert (
            exit_code == 0
        ), f"Public key {filename} should be ALLOWED, got exit {exit_code}. stderr: {stderr}"


class TestGenericKeyFilesAllowed:
    """Test that generic .key files are NOT blocked (Monitor feedback #3)."""

    @pytest.mark.parametrize(
        "filename",
        [
            "license.key",
            "config.key",
            "api.key",
            "product.key",
            "activation.key",
        ],
    )
    def test_generic_key_files_allowed(self, filename):
        exit_code, _, stderr = run_hook("Read", filename)
        assert (
            exit_code == 0
        ), f"Generic key file {filename} should be ALLOWED, got exit {exit_code}. stderr: {stderr}"


class TestNormalFilesAllowed:
    """Test that normal development files are allowed."""

    @pytest.mark.parametrize(
        "filename",
        [
            "app.py",
            "main.go",
            "index.ts",
            "README.md",
            "package.json",
            "Dockerfile",
            "config.yaml",
            "settings.json",
            "test_main.py",
            "src/utils.js",
        ],
    )
    def test_normal_files_allowed(self, filename):
        exit_code, _, _ = run_hook("Read", filename)
        assert exit_code == 0, f"{filename} should be allowed"


# =============================================================================
# Path Traversal Protection Tests
# =============================================================================


class TestPathTraversal:
    """Test that path traversal attempts are blocked via Path.parts checking."""

    @pytest.mark.parametrize(
        "path",
        [
            ".env/harmless.txt",  # .env as directory
            "config/.env/data.json",  # nested .env directory
            "secrets/api_key.txt",  # secrets directory
            "credentials.json/sub/file.py",  # credentials.json as directory
        ],
    )
    def test_sensitive_path_component_blocked(self, path):
        exit_code, stdout, stderr = run_hook("Read", path)
        assert exit_code == 0, f"Expected exit 0. stderr: {stderr}"
        payload = _parse_stdout(stdout)
        _assert_denied(payload, expected_file_fragment=path)

    def test_relative_traversal_with_env(self):
        """Test ../../../.env style paths."""
        exit_code, stdout, stderr = run_hook("Read", "../../../.env")
        assert exit_code == 0, f"Expected exit 0. stderr: {stderr}"
        payload = _parse_stdout(stdout)
        _assert_denied(payload, expected_file_fragment=".env")


# =============================================================================
# Tool Interception Tests
# =============================================================================


class TestToolInterception:
    """Test that only Read/Edit/Write tools are intercepted."""

    def test_read_intercepted(self):
        exit_code, stdout, stderr = run_hook("Read", ".env")
        assert exit_code == 0, f"Expected exit 0. stderr: {stderr}"
        payload = _parse_stdout(stdout)
        _assert_denied(payload, expected_file_fragment=".env")

    def test_write_intercepted(self):
        exit_code, stdout, stderr = run_hook("Write", ".env")
        assert exit_code == 0, f"Expected exit 0. stderr: {stderr}"
        payload = _parse_stdout(stdout)
        _assert_denied(payload, expected_file_fragment=".env")

    def test_edit_intercepted(self):
        exit_code, stdout, stderr = run_hook("Edit", ".env")
        assert exit_code == 0, f"Expected exit 0. stderr: {stderr}"
        payload = _parse_stdout(stdout)
        _assert_denied(payload, expected_file_fragment=".env")

    def test_bash_not_intercepted(self):
        """Bash tool should not be intercepted (different hook)."""
        exit_code, _, _ = run_hook("Bash", ".env")
        assert exit_code == 0, "Bash tool should not be intercepted by this hook"

    def test_grep_not_intercepted(self):
        exit_code, _, _ = run_hook("Grep", ".env")
        assert exit_code == 0


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestErrorHandling:
    """Test edge cases and error handling."""

    def test_empty_file_path(self):
        """Empty file path should be allowed (safe default)."""
        exit_code, _, _ = run_hook("Read", "")
        assert exit_code == 0

    def test_missing_file_path(self):
        """Missing file_path in tool_input should be allowed."""
        input_data = {"tool_name": "Read", "tool_input": {}}
        result = subprocess.run(
            [sys.executable, str(HOOK_PATH)],
            input=json.dumps(input_data),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0

    def test_invalid_json(self):
        """Invalid JSON should return exit code 1."""
        result = subprocess.run(
            [sys.executable, str(HOOK_PATH)],
            input="not valid json",
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1

    def test_empty_input(self):
        """Empty input should return exit code 1 (JSON decode error)."""
        result = subprocess.run(
            [sys.executable, str(HOOK_PATH)], input="", capture_output=True, text=True
        )
        assert result.returncode == 1


# =============================================================================
# Output Format Tests
# =============================================================================


class TestOutputFormat:
    """Test that error output follows expected JSON structure."""

    def test_error_json_structure(self):
        """Blocked file should output valid JSON to stdout."""
        exit_code, stdout, stderr = run_hook("Read", ".env")
        assert exit_code == 0, f"Expected exit 0. stderr: {stderr}"
        payload = _parse_stdout(stdout)
        _assert_denied(payload, expected_file_fragment=".env")

    def test_error_contains_file_path(self):
        """Error message should mention the blocked file."""
        exit_code, stdout, stderr = run_hook("Read", "credentials.json")
        assert exit_code == 0, f"Expected exit 0. stderr: {stderr}"
        payload = _parse_stdout(stdout)
        _assert_denied(payload, expected_file_fragment="credentials.json")


# =============================================================================
# Case Sensitivity Tests
# =============================================================================


class TestCaseSensitivity:
    """Test that patterns are case-insensitive."""

    @pytest.mark.parametrize(
        "filename",
        [
            ".ENV",
            ".Env",
            "CREDENTIALS.JSON",
            "Credentials.Json",
            "SECRET.YAML",
            "ID_RSA",
            "Server.PEM",
        ],
    )
    def test_case_insensitive_blocking(self, filename):
        exit_code, stdout, stderr = run_hook("Read", filename)
        assert exit_code == 0, f"Expected exit 0. stderr: {stderr}"
        payload = _parse_stdout(stdout)
        _assert_denied(payload, expected_file_fragment=filename)
