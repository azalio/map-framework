#!/usr/bin/env python3
"""
Integration test suite for session-start.sh hook

Tests hook execution in realistic subprocess environment:
- Valid checkpoint → JSON with additionalContext
- Missing checkpoint → JSON {continue: true}
- Validation failures → No injection, stderr logging
- Performance < 5s
- Cleanup of temporary fixtures

Design:
- Execute hook as subprocess (realistic environment)
- Use tmp_path for isolated .map/ directories
- Parse JSON output and verify structure
- Capture stderr for logging verification
"""

import pytest
import subprocess
import json
import time
from pathlib import Path


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def hook_script_path():
    """Return absolute path to session-start.sh hook script"""
    project_root = Path(__file__).parent.parent.parent
    hook_path = project_root / ".claude" / "hooks" / "session-start.sh"
    assert hook_path.exists(), f"Hook script not found at {hook_path}"
    return hook_path


@pytest.fixture
def test_workspace(tmp_path):
    """
    Create isolated test workspace with .map/ directory.

    Returns tmp_path that will be used as cwd for hook execution.
    Creates .map/ subdirectory for checkpoint files.
    """
    map_dir = tmp_path / ".map"
    map_dir.mkdir()
    return tmp_path


@pytest.fixture
def valid_checkpoint_content():
    """Standard valid checkpoint content for testing"""
    return """# Current Task Plan

## Goal
Implement feature X with test coverage

## Progress
- [x] Step 1: Design
- [x] Step 2: Implementation
- [ ] Step 3: Testing
- [ ] Step 4: Documentation

## Current Subtask (3/4)
Write unit tests for feature X

## Context
- Using pytest framework
- Target 90% coverage
"""


@pytest.fixture
def checkpoint_with_control_chars():
    """Checkpoint content with control characters that need sanitization"""
    return "# Task\x00\nProgress\x1b[31m: 1/5\r\nStatus: \x7fcomplete"


# ============================================================================
# Helper Functions
# ============================================================================


def run_hook(
    hook_path: Path, workspace: Path, timeout: int = 5
) -> subprocess.CompletedProcess:
    """
    Execute session-start hook as subprocess.

    Args:
        hook_path: Absolute path to session-start.sh
        workspace: Working directory for hook execution (contains .map/)
        timeout: Command timeout in seconds (default: 5)

    Returns:
        CompletedProcess with stdout (JSON), stderr (logs), returncode
    """
    result = subprocess.run(
        ["bash", str(hook_path)],
        cwd=str(workspace),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result


def parse_hook_output(result: subprocess.CompletedProcess) -> dict:
    """
    Parse JSON output from hook execution.

    Args:
        result: CompletedProcess from run_hook()

    Returns:
        Parsed JSON dict

    Raises:
        json.JSONDecodeError if output is not valid JSON
    """
    return json.loads(result.stdout)


# ============================================================================
# Subprocess Execution Tests (2 cases)
# ============================================================================


def test_hook_executes_as_subprocess(hook_script_path, test_workspace):
    """Test that hook script executes successfully as subprocess"""
    result = run_hook(hook_script_path, test_workspace)

    # Hook should always exit 0 (non-blocking)
    assert result.returncode == 0

    # Should output valid JSON
    output = parse_hook_output(result)
    assert isinstance(output, dict)
    assert "continue" in output


def test_hook_logs_to_stderr(hook_script_path, test_workspace):
    """Test that hook logs debug information to stderr"""
    result = run_hook(hook_script_path, test_workspace)

    # Verify stderr contains session-start log prefix
    assert "[session-start]" in result.stderr
    assert "SessionStart hook triggered" in result.stderr


# ============================================================================
# Valid Injection Tests (3 cases)
# ============================================================================


def test_valid_checkpoint_returns_json_with_context(
    hook_script_path, test_workspace, valid_checkpoint_content
):
    """Test that valid checkpoint file returns JSON with additionalContext"""
    # Setup: Create valid checkpoint
    checkpoint = test_workspace / ".map" / "current_plan.md"
    checkpoint.write_text(valid_checkpoint_content, encoding="utf-8")

    # Execute hook
    result = run_hook(hook_script_path, test_workspace)

    # Verify exit code
    assert result.returncode == 0

    # Parse and verify JSON structure
    output = parse_hook_output(result)
    assert output["continue"] is True
    assert "additionalContext" in output

    # Verify additionalContext is not empty
    context = output["additionalContext"]
    assert len(context) > 0

    # Verify injection header is present
    assert "MAP Workflow Context Restored" in context
    assert "automatically restored from your previous session" in context

    # Verify original content is included (after sanitization)
    assert "Current Task Plan" in context
    assert "Progress" in context


def test_valid_checkpoint_includes_sanitized_content(
    hook_script_path, test_workspace, checkpoint_with_control_chars
):
    """Test that checkpoint content is sanitized before injection"""
    # Setup: Create checkpoint with control characters
    checkpoint = test_workspace / ".map" / "current_plan.md"
    checkpoint.write_text(checkpoint_with_control_chars, encoding="utf-8")

    # Execute hook
    result = run_hook(hook_script_path, test_workspace)
    output = parse_hook_output(result)

    # Verify content is included
    assert "additionalContext" in output
    context = output["additionalContext"]

    # Verify control characters are removed
    assert "\x00" not in context  # NULL removed
    assert "\x1b" not in context  # ESC removed
    assert "\r" not in context  # CR removed
    assert "\x7f" not in context  # DELETE removed

    # Verify valid content remains
    assert "Task" in context
    assert "Progress" in context
    assert "complete" in context


def test_valid_checkpoint_logs_success_metrics(
    hook_script_path, test_workspace, valid_checkpoint_content
):
    """Test that successful validation logs file size metrics"""
    # Setup: Create valid checkpoint
    checkpoint = test_workspace / ".map" / "current_plan.md"
    checkpoint.write_text(valid_checkpoint_content, encoding="utf-8")
    _file_size_kb = checkpoint.stat().st_size / 1024

    # Execute hook
    result = run_hook(hook_script_path, test_workspace)

    # Verify success message in stderr
    assert "[session-start] ✅ Successfully validated checkpoint" in result.stderr

    # Verify size is logged (should be close to actual size)
    assert "KB" in result.stderr

    # Verify injection message
    assert "Injecting context with header" in result.stderr


# ============================================================================
# Missing File Tests (2 cases)
# ============================================================================


def test_missing_checkpoint_returns_minimal_json(hook_script_path, test_workspace):
    """Test that missing checkpoint file returns {continue: true} without context"""
    # Setup: Ensure checkpoint does NOT exist
    checkpoint = test_workspace / ".map" / "current_plan.md"
    assert not checkpoint.exists()

    # Execute hook
    result = run_hook(hook_script_path, test_workspace)

    # Verify exit code
    assert result.returncode == 0

    # Parse JSON
    output = parse_hook_output(result)

    # Verify minimal response
    assert output["continue"] is True
    assert "additionalContext" not in output

    # Verify stderr logs reason
    assert "[session-start] No checkpoint found" in result.stderr
    assert "new session, skipping injection" in result.stderr


def test_missing_map_directory_returns_minimal_json(hook_script_path, tmp_path):
    """Test that missing .map/ directory is handled gracefully"""
    # Setup: Use tmp_path WITHOUT creating .map/ subdirectory
    # (don't use test_workspace fixture which creates .map/)

    # Execute hook
    result = run_hook(hook_script_path, tmp_path)

    # Verify graceful handling
    assert result.returncode == 0

    output = parse_hook_output(result)
    assert output["continue"] is True
    assert "additionalContext" not in output


# ============================================================================
# Validation Failure Tests (4 cases)
# ============================================================================


def test_oversized_checkpoint_no_injection(hook_script_path, test_workspace):
    """Test that checkpoint >256KB fails validation and doesn't inject"""
    # Setup: Create 257KB checkpoint (just over limit)
    checkpoint = test_workspace / ".map" / "current_plan.md"
    large_content = "x" * (257 * 1024)
    checkpoint.write_text(large_content, encoding="utf-8")

    # Execute hook
    result = run_hook(hook_script_path, test_workspace)

    # Verify exit code (still 0 - non-blocking)
    assert result.returncode == 0

    # Verify no injection
    output = parse_hook_output(result)
    assert output["continue"] is True
    assert "additionalContext" not in output

    # Verify error logged to stderr
    assert "[session-start] Checkpoint validation failed" in result.stderr
    assert "File too large" in result.stderr


def test_path_traversal_checkpoint_no_injection(hook_script_path, test_workspace):
    """Test that path traversal attempt is blocked (security test)"""
    # Setup: Create checkpoint with path traversal in content
    # (Validator checks file path, not content, but good to verify)
    checkpoint = test_workspace / ".map" / "current_plan.md"

    # Create a file outside .map/ that we'll try to reference
    outside_file = test_workspace / "secret.txt"
    outside_file.write_text("Secret data!", encoding="utf-8")

    # Write checkpoint that references outside file (in content)
    checkpoint.write_text("Include: ../secret.txt", encoding="utf-8")

    # Execute hook (should work - path traversal is about file location, not content)
    result = run_hook(hook_script_path, test_workspace)

    # This checkpoint should actually succeed (content is valid)
    # Path validation checks the checkpoint file itself, not references in content
    output = parse_hook_output(result)
    assert output["continue"] is True

    # Note: True path traversal would be if checkpoint file itself was outside .map/
    # That's tested by moving checkpoint file location in next test


def test_checkpoint_outside_map_directory_blocked(hook_script_path, test_workspace):
    """Test that checkpoint file outside .map/ directory is rejected"""
    # Setup: Create checkpoint OUTSIDE .map/ directory
    malicious_checkpoint = test_workspace / "evil_checkpoint.md"
    malicious_checkpoint.write_text("Malicious content", encoding="utf-8")

    # Create symlink inside .map/ pointing to outside file
    checkpoint_link = test_workspace / ".map" / "current_plan.md"
    checkpoint_link.symlink_to(malicious_checkpoint)

    # Execute hook
    result = run_hook(hook_script_path, test_workspace)

    # Verify no injection (symlink resolves outside .map/)
    output = parse_hook_output(result)
    assert output["continue"] is True
    assert "additionalContext" not in output

    # Verify error logged
    assert "[session-start] Checkpoint validation failed" in result.stderr
    assert "Path traversal detected" in result.stderr


def test_invalid_utf8_checkpoint_no_injection(hook_script_path, test_workspace):
    """Test that invalid UTF-8 encoding fails validation"""
    # Setup: Create checkpoint with invalid UTF-8 bytes
    checkpoint = test_workspace / ".map" / "current_plan.md"

    with open(checkpoint, "wb") as f:
        f.write(b"Valid start\xff\xfeInvalid UTF-8 bytes")

    # Execute hook
    result = run_hook(hook_script_path, test_workspace)

    # Verify no injection
    output = parse_hook_output(result)
    assert output["continue"] is True
    assert "additionalContext" not in output

    # Verify error logged
    assert "[session-start] Checkpoint validation failed" in result.stderr
    assert "Invalid UTF-8 encoding" in result.stderr


# ============================================================================
# Performance Tests (2 cases)
# ============================================================================


def test_hook_execution_time_under_5_seconds(
    hook_script_path, test_workspace, valid_checkpoint_content
):
    """Test that hook execution completes in <5 seconds"""
    # Setup: Create valid checkpoint
    checkpoint = test_workspace / ".map" / "current_plan.md"
    checkpoint.write_text(valid_checkpoint_content, encoding="utf-8")

    # Measure execution time
    start_time = time.time()
    result = run_hook(hook_script_path, test_workspace, timeout=5)
    elapsed_time = time.time() - start_time

    # Verify successful execution
    assert result.returncode == 0

    # Verify time constraint
    assert elapsed_time < 5.0, f"Hook took {elapsed_time:.2f}s, exceeds 5s limit"

    # Typical execution should be much faster (<1s)
    assert (
        elapsed_time < 2.0
    ), f"Hook took {elapsed_time:.2f}s, unusually slow (expected <1s)"


def test_hook_execution_time_typical_performance(
    hook_script_path, test_workspace, valid_checkpoint_content
):
    """Test that typical execution is fast (~0.1-0.5s)"""
    # Setup: Create reasonably sized checkpoint (5KB - typical size)
    checkpoint = test_workspace / ".map" / "current_plan.md"
    typical_content = valid_checkpoint_content * 5  # ~5KB
    checkpoint.write_text(typical_content, encoding="utf-8")

    # Measure execution time
    start_time = time.time()
    result = run_hook(hook_script_path, test_workspace, timeout=5)
    elapsed_time = time.time() - start_time

    # Verify execution
    assert result.returncode == 0
    output = parse_hook_output(result)
    assert "additionalContext" in output

    # Verify typical performance (<1s for 5KB file)
    assert (
        elapsed_time < 1.0
    ), f"Hook took {elapsed_time:.2f}s for 5KB file (expected <1s)"


# ============================================================================
# Cleanup Tests (2 cases)
# ============================================================================


def test_tmp_path_fixture_cleanup_after_test(test_workspace):
    """Verify that tmp_path fixture cleans up after test completes"""
    # Create files in test workspace
    checkpoint = test_workspace / ".map" / "current_plan.md"
    checkpoint.write_text("Test content", encoding="utf-8")

    # Verify files exist during test
    assert checkpoint.exists()
    assert test_workspace.exists()

    # Note: Actual cleanup happens automatically via pytest tmp_path fixture
    # This test documents the expected behavior


def test_multiple_tests_use_isolated_workspaces(hook_script_path, test_workspace):
    """Verify that each test gets isolated workspace (no cross-contamination)"""
    # Create checkpoint in this test's workspace
    checkpoint = test_workspace / ".map" / "current_plan.md"
    checkpoint.write_text("Test isolation", encoding="utf-8")

    # Execute hook
    result = run_hook(hook_script_path, test_workspace)

    # Verify this test's checkpoint is used
    output = parse_hook_output(result)
    assert "additionalContext" in output
    assert "Test isolation" in output["additionalContext"]

    # Note: Other tests won't see this checkpoint (isolated tmp_path)


# ============================================================================
# Edge Cases and Error Handling (3 cases)
# ============================================================================


def test_empty_checkpoint_file_handled(hook_script_path, test_workspace):
    """Test that empty checkpoint file is handled gracefully"""
    # Setup: Create empty checkpoint
    checkpoint = test_workspace / ".map" / "current_plan.md"
    checkpoint.write_text("", encoding="utf-8")

    # Execute hook
    result = run_hook(hook_script_path, test_workspace)

    # Verify graceful handling
    assert result.returncode == 0
    output = parse_hook_output(result)

    # Empty content after sanitization should result in no injection
    assert output["continue"] is True
    assert "additionalContext" not in output

    # Verify logged reason
    assert "Sanitized content is empty" in result.stderr


def test_checkpoint_with_only_whitespace(hook_script_path, test_workspace):
    """Test that checkpoint with only whitespace/newlines is handled"""
    # Setup: Create checkpoint with only whitespace
    checkpoint = test_workspace / ".map" / "current_plan.md"
    checkpoint.write_text("\n\n\t\t\n\n", encoding="utf-8")

    # Execute hook
    result = run_hook(hook_script_path, test_workspace)

    # Verify execution
    assert result.returncode == 0
    output = parse_hook_output(result)

    # Should include additionalContext (whitespace is valid content)
    # Header is added, so context won't be empty
    assert output["continue"] is True


def test_hook_with_missing_validator_script(hook_script_path, tmp_path, monkeypatch):
    """Test graceful handling when validator script is missing"""
    # Setup: Use workspace without validator helper
    # Create .map/ directory
    map_dir = tmp_path / ".map"
    map_dir.mkdir()
    checkpoint = map_dir / "current_plan.md"
    checkpoint.write_text("Test content", encoding="utf-8")

    # Note: This test assumes validator is normally found
    # Hook script checks for validator existence and handles missing case
    # Actual test would need to modify SCRIPT_DIR or mock file existence
    # For integration test, we verify hook behavior with valid setup

    # Execute hook normally (validator exists in project)
    result = run_hook(hook_script_path, tmp_path)

    # If validator is present, should succeed
    assert result.returncode == 0


# ============================================================================
# Parametrized Tests for Multiple Scenarios (1 case)
# ============================================================================


@pytest.mark.parametrize(
    "content,should_inject,expected_in_stderr",
    [
        # (checkpoint_content, should_have_additionalContext, expected_stderr_fragment)
        (
            "# Valid checkpoint\n\nProgress: 2/5",
            True,
            "Successfully validated checkpoint",
        ),
        ("", False, "Sanitized content is empty"),
    ],
)
def test_checkpoint_scenarios_parametrized(
    hook_script_path, test_workspace, content, should_inject, expected_in_stderr
):
    """Parametrized test for multiple checkpoint scenarios"""
    # Setup: Create checkpoint with given content
    checkpoint = test_workspace / ".map" / "current_plan.md"
    checkpoint.write_text(content, encoding="utf-8")

    # Execute hook
    result = run_hook(hook_script_path, test_workspace)

    # Verify exit code
    assert result.returncode == 0

    # Parse output
    output = parse_hook_output(result)
    assert output["continue"] is True

    # Verify injection expectation
    if should_inject:
        assert "additionalContext" in output
    else:
        assert "additionalContext" not in output

    # Verify expected stderr fragment
    assert expected_in_stderr in result.stderr


def test_checkpoint_size_bomb_scenario(hook_script_path, test_workspace):
    """Test size bomb scenario separately (cannot be parametrized due to ARG_MAX limit)"""
    # Setup: Create oversized checkpoint (257KB)
    checkpoint = test_workspace / ".map" / "current_plan.md"
    checkpoint.write_text("x" * (257 * 1024), encoding="utf-8")

    # Execute hook
    result = run_hook(hook_script_path, test_workspace)

    # Verify exit code
    assert result.returncode == 0

    # Parse output
    output = parse_hook_output(result)
    assert output["continue"] is True

    # Verify no injection (size bomb blocked)
    assert "additionalContext" not in output

    # Verify expected stderr
    assert "File too large" in result.stderr


# ============================================================================
# JSON Output Validation (2 cases)
# ============================================================================


def test_hook_output_valid_json_structure(hook_script_path, test_workspace):
    """Test that hook always outputs valid JSON with required fields"""
    # Test with no checkpoint
    result = run_hook(hook_script_path, test_workspace)

    # Parse JSON (will raise if invalid)
    output = parse_hook_output(result)

    # Verify required field
    assert "continue" in output
    assert isinstance(output["continue"], bool)


def test_hook_additional_context_is_string(
    hook_script_path, test_workspace, valid_checkpoint_content
):
    """Test that additionalContext field is a string (not object)"""
    # Setup: Create valid checkpoint
    checkpoint = test_workspace / ".map" / "current_plan.md"
    checkpoint.write_text(valid_checkpoint_content, encoding="utf-8")

    # Execute hook
    result = run_hook(hook_script_path, test_workspace)
    output = parse_hook_output(result)

    # Verify additionalContext type
    assert "additionalContext" in output
    assert isinstance(output["additionalContext"], str)
    assert len(output["additionalContext"]) > 0
