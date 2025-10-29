#!/usr/bin/env python3
"""
Comprehensive test suite for validate_checkpoint_file.py helper

Tests 4 security layers:
1. Path validation (path traversal, absolute paths, symlinks)
2. Size validation (256KB limit with boundary conditions)
3. Content sanitization (control characters, Unicode)
4. UTF-8 validation (encoding errors)

Coverage Target: >90% for all validation functions
"""

import pytest
import sys
from pathlib import Path
from unittest import mock

# Import validation functions from helpers
sys.path.insert(0, str(Path(__file__).parent.parent.parent / ".claude" / "hooks" / "helpers"))
from validate_checkpoint_file import (
    validate_path_security,
    validate_file_size,
    sanitize_content,
    read_and_validate_content,
    validate_checkpoint_file,
    MAX_FILE_SIZE_BYTES,
    ALLOWED_BASE_DIR,
    CONTROL_CHAR_PATTERN
)


# ============================================================================
# Test Fixtures
# ============================================================================

@pytest.fixture
def mock_map_dir(tmp_path):
    """Create a temporary .map directory for testing"""
    map_dir = tmp_path / ".map"
    map_dir.mkdir()
    return map_dir


@pytest.fixture
def valid_checkpoint_file(mock_map_dir):
    """Create a valid checkpoint file for testing"""
    checkpoint = mock_map_dir / "checkpoint.json"
    checkpoint.write_text('{"step": 1, "status": "complete"}', encoding='utf-8')
    return checkpoint


@pytest.fixture
def large_file(mock_map_dir):
    """Create a file just over the size limit (257KB)"""
    large_file = mock_map_dir / "large.txt"
    # Create 257KB file (256KB + 1KB over limit)
    content = "a" * (257 * 1024)
    large_file.write_text(content, encoding='utf-8')
    return large_file


@pytest.fixture
def file_at_limit(mock_map_dir):
    """Create a file exactly at the size limit (256KB)"""
    limit_file = mock_map_dir / "at_limit.txt"
    # Create exactly 256KB file
    content = "b" * (256 * 1024)
    limit_file.write_text(content, encoding='utf-8')
    return limit_file


@pytest.fixture
def file_under_limit(mock_map_dir):
    """Create a file just under the size limit (255KB)"""
    under_file = mock_map_dir / "under_limit.txt"
    # Create 255KB file
    content = "c" * (255 * 1024)
    under_file.write_text(content, encoding='utf-8')
    return under_file


# ============================================================================
# Path Security Tests (6 cases)
# ============================================================================

def test_path_security_valid_path_in_map_dir(valid_checkpoint_file, tmp_path):
    """Test that a valid path within .map/ directory passes validation"""
    result = validate_path_security(
        str(valid_checkpoint_file),
        base_dir=str(tmp_path / ".map")
    )

    assert result["valid"] is True
    assert result["error"] is None
    assert result["resolved_path"] is not None
    assert result["resolved_path"].is_absolute()


def test_path_security_blocks_path_traversal_parent_dir(mock_map_dir, tmp_path):
    """Test that path traversal using ../ is blocked"""
    # Attempt to escape .map/ directory using ../
    malicious_path = str(mock_map_dir / ".." / "etc" / "passwd")

    result = validate_path_security(
        malicious_path,
        base_dir=str(tmp_path / ".map")
    )

    assert result["valid"] is False
    assert "Path traversal detected" in result["error"]
    assert result["resolved_path"] is None


def test_path_security_blocks_absolute_path_outside_map(tmp_path):
    """Test that absolute paths outside .map/ are blocked"""
    # Try to access /etc/passwd directly
    malicious_path = "/etc/passwd"

    result = validate_path_security(
        malicious_path,
        base_dir=str(tmp_path / ".map")
    )

    assert result["valid"] is False
    assert "Path traversal detected" in result["error"]
    assert result["resolved_path"] is None


def test_path_security_blocks_symlink_escape(mock_map_dir, tmp_path):
    """Test that symlinks pointing outside .map/ are blocked"""
    # Create a symlink inside .map/ pointing to /tmp
    symlink = mock_map_dir / "escape_symlink"
    target = tmp_path.parent / "outside.txt"
    target.write_text("Escaped!", encoding='utf-8')

    symlink.symlink_to(target)

    result = validate_path_security(
        str(symlink),
        base_dir=str(tmp_path / ".map")
    )

    # Symlink resolves to target outside .map/, should fail
    assert result["valid"] is False
    assert "Path traversal detected" in result["error"]


def test_path_security_nonexistent_file_passes_path_check(mock_map_dir, tmp_path):
    """Test that non-existent file in .map/ passes path check (caught later by size check)"""
    # Path validation should pass even if file doesn't exist
    nonexistent = mock_map_dir / "nonexistent.json"

    result = validate_path_security(
        str(nonexistent),
        base_dir=str(tmp_path / ".map")
    )

    # Path validation passes (file is within .map/)
    # File existence is checked in size validation
    assert result["valid"] is True
    assert result["error"] is None


def test_path_security_relative_path_within_map(mock_map_dir, tmp_path):
    """Test that relative paths within .map/ are resolved correctly"""
    # Create nested structure
    nested = mock_map_dir / "subdir"
    nested.mkdir()
    checkpoint = nested / "checkpoint.json"
    checkpoint.write_text('{"data": "test"}', encoding='utf-8')

    # Use relative path with ./ prefix
    relative_path = f".map/subdir/checkpoint.json"

    result = validate_path_security(
        relative_path,
        base_dir=".map"
    )

    assert result["valid"] is True
    assert result["error"] is None
    assert "subdir" in str(result["resolved_path"])


# ============================================================================
# Size Validation Tests (4 cases)
# ============================================================================

def test_size_validation_file_at_limit_passes(file_at_limit):
    """Test that a file exactly at 256KB limit passes validation"""
    result = validate_file_size(file_at_limit, MAX_FILE_SIZE_BYTES)

    assert result["valid"] is True
    assert result["error"] is None
    assert result["size_bytes"] == 256 * 1024


def test_size_validation_file_under_limit_passes(file_under_limit):
    """Test that a file under 256KB limit passes validation"""
    result = validate_file_size(file_under_limit, MAX_FILE_SIZE_BYTES)

    assert result["valid"] is True
    assert result["error"] is None
    assert result["size_bytes"] == 255 * 1024


def test_size_validation_file_over_limit_fails(large_file):
    """Test that a file over 256KB limit fails validation"""
    result = validate_file_size(large_file, MAX_FILE_SIZE_BYTES)

    assert result["valid"] is False
    assert "File too large" in result["error"]
    assert "257.0KB exceeds 256KB limit" in result["error"]
    assert result["size_bytes"] == 257 * 1024


def test_size_validation_nonexistent_file_fails(mock_map_dir):
    """Test that size validation fails for non-existent files"""
    nonexistent = mock_map_dir / "does_not_exist.json"

    result = validate_file_size(nonexistent, MAX_FILE_SIZE_BYTES)

    assert result["valid"] is False
    assert "File not found" in result["error"]
    assert result["size_bytes"] == 0


def test_size_validation_directory_fails(mock_map_dir):
    """Test that size validation fails for directories"""
    result = validate_file_size(mock_map_dir, MAX_FILE_SIZE_BYTES)

    assert result["valid"] is False
    assert "Not a regular file" in result["error"]


# ============================================================================
# Sanitization Tests (6 cases)
# ============================================================================

def test_sanitize_removes_null_bytes():
    """Test that NULL bytes (\\x00) are removed"""
    content = "Hello\x00World\x00"
    sanitized = sanitize_content(content)
    assert sanitized == "HelloWorld"
    assert "\x00" not in sanitized


def test_sanitize_removes_control_codes():
    """Test that control codes (\\x01-\\x08) are removed"""
    content = "Start\x01\x02\x03\x04\x05\x06\x07\x08End"
    sanitized = sanitize_content(content)
    assert sanitized == "StartEnd"


def test_sanitize_removes_escape_character():
    """Test that ESC character (\\x1b) is removed"""
    # ESC sequences could inject terminal commands
    content = "Normal\x1b[31mRed Text\x1b[0m"
    sanitized = sanitize_content(content)
    assert sanitized == "Normal[31mRed Text[0m"
    assert "\x1b" not in sanitized


def test_sanitize_removes_delete_character():
    """Test that DELETE character (\\x7f) is removed"""
    content = "Hello\x7fWorld"
    sanitized = sanitize_content(content)
    assert sanitized == "HelloWorld"


def test_sanitize_removes_unicode_control_chars():
    """Test that Unicode control characters (\\u2028, \\u2029) are removed"""
    # Line/paragraph separators can break JSON parsing
    content = "Line1\u2028Line2\u2029Paragraph"
    sanitized = sanitize_content(content)
    assert sanitized == "Line1Line2Paragraph"
    assert "\u2028" not in sanitized
    assert "\u2029" not in sanitized


def test_sanitize_removes_carriage_return():
    """Test that carriage return (\\r) is removed for terminal safety"""
    # Carriage return can overwrite terminal output
    content = "Overwrite this\rHacked!"
    sanitized = sanitize_content(content)
    assert sanitized == "Overwrite thisHacked!"
    assert "\r" not in sanitized


def test_sanitize_preserves_newlines_and_tabs():
    """Test that newlines (\\n) and tabs (\\t) are preserved"""
    content = "Line1\nLine2\tTabbed"
    sanitized = sanitize_content(content)
    assert sanitized == "Line1\nLine2\tTabbed"
    assert "\n" in sanitized
    assert "\t" in sanitized


def test_sanitize_mixed_content():
    """Test sanitization with mixed valid and invalid characters"""
    content = "Valid text\nwith newline\tand tab\x00but null\x1band escape"
    sanitized = sanitize_content(content)

    # Verify valid chars preserved
    assert "Valid text" in sanitized
    assert "\n" in sanitized
    assert "\t" in sanitized

    # Verify invalid chars removed
    assert "\x00" not in sanitized
    assert "\x1b" not in sanitized


# ============================================================================
# UTF-8 Validation Tests (2 cases)
# ============================================================================

def test_read_content_valid_utf8_with_emoji(mock_map_dir):
    """Test that valid UTF-8 content with emojis is read correctly"""
    file_path = mock_map_dir / "emoji.txt"
    content = "Hello 👋 World 🌍 Test 🚀"
    file_path.write_text(content, encoding='utf-8')

    result = read_and_validate_content(file_path)

    assert result["valid"] is True
    assert result["error"] is None
    assert result["content"] == content
    assert "👋" in result["content"]


def test_read_content_invalid_utf8_fails(mock_map_dir):
    """Test that invalid UTF-8 byte sequences fail validation"""
    file_path = mock_map_dir / "invalid_utf8.txt"

    # Write invalid UTF-8 bytes directly
    with open(file_path, 'wb') as f:
        f.write(b'Valid start\xFF\xFEInvalid bytes')

    result = read_and_validate_content(file_path)

    assert result["valid"] is False
    assert "Invalid UTF-8 encoding" in result["error"]
    assert result["content"] is None


# ============================================================================
# Integration Tests (2 cases)
# ============================================================================

def test_validate_checkpoint_end_to_end_success(valid_checkpoint_file, tmp_path):
    """Test end-to-end validation with a valid checkpoint file"""
    result = validate_checkpoint_file(
        str(valid_checkpoint_file),
        base_dir=str(tmp_path / ".map"),
        max_size=MAX_FILE_SIZE_BYTES
    )

    assert result["valid"] is True
    assert result["error"] is None
    assert result["sanitized_content"] == '{"step": 1, "status": "complete"}'
    assert result["metadata"]["size_bytes"] > 0
    assert result["metadata"]["resolved_path"] is not None


def test_validate_checkpoint_end_to_end_with_control_chars(mock_map_dir, tmp_path):
    """Test end-to-end validation with content containing control characters"""
    file_path = mock_map_dir / "dirty.json"
    # Content with control characters that should be stripped
    dirty_content = '{"step": 1\x00,\x1b "status": "complete\r"}'
    file_path.write_text(dirty_content, encoding='utf-8')

    result = validate_checkpoint_file(
        str(file_path),
        base_dir=str(tmp_path / ".map"),
        max_size=MAX_FILE_SIZE_BYTES
    )

    assert result["valid"] is True
    assert result["error"] is None
    # Control chars should be removed
    assert "\x00" not in result["sanitized_content"]
    assert "\x1b" not in result["sanitized_content"]
    assert "\r" not in result["sanitized_content"]
    # Valid content should remain
    assert '"step": 1' in result["sanitized_content"]
    assert '"status":' in result["sanitized_content"]
    assert 'complete' in result["sanitized_content"]


def test_validate_checkpoint_multiple_violations_reports_first(large_file, tmp_path):
    """Test that validation reports first error when multiple violations exist"""
    # Move file outside .map/ to trigger path violation
    outside_file = tmp_path / "outside.txt"
    large_file.rename(outside_file)

    result = validate_checkpoint_file(
        str(outside_file),
        base_dir=str(tmp_path / ".map"),
        max_size=MAX_FILE_SIZE_BYTES
    )

    # Should fail on path check (first layer), not reach size check
    assert result["valid"] is False
    assert "Path traversal detected" in result["error"]
    # Should not mention size (didn't reach that layer)
    assert "File too large" not in result["error"]


def test_validate_checkpoint_size_violation_second_layer(large_file, tmp_path):
    """Test that size violation is caught in second layer after path passes"""
    result = validate_checkpoint_file(
        str(large_file),
        base_dir=str(tmp_path / ".map"),
        max_size=MAX_FILE_SIZE_BYTES
    )

    # Path check passes, size check fails
    assert result["valid"] is False
    assert "File too large" in result["error"]
    assert "257.0KB exceeds 256KB limit" in result["error"]


# ============================================================================
# Edge Case Tests (3 additional cases for >90% coverage)
# ============================================================================

def test_sanitize_empty_string():
    """Test sanitization of empty string"""
    sanitized = sanitize_content("")
    assert sanitized == ""


def test_sanitize_only_control_chars():
    """Test sanitization when content is only control characters"""
    content = "\x00\x01\x1b\x7f\r"
    sanitized = sanitize_content(content)
    assert sanitized == ""


def test_validate_checkpoint_utf8_error_third_layer(mock_map_dir, tmp_path):
    """Test that UTF-8 validation error is caught in third layer"""
    file_path = mock_map_dir / "invalid.txt"

    # Write invalid UTF-8
    with open(file_path, 'wb') as f:
        f.write(b'\xFF\xFE')

    result = validate_checkpoint_file(
        str(file_path),
        base_dir=str(tmp_path / ".map"),
        max_size=MAX_FILE_SIZE_BYTES
    )

    # Path and size pass, UTF-8 validation fails
    assert result["valid"] is False
    assert "Invalid UTF-8 encoding" in result["error"]


# ============================================================================
# Parametrized Tests for Control Characters
# ============================================================================

@pytest.mark.parametrize("control_char,name", [
    ("\x00", "NULL"),
    ("\x01", "SOH"),
    ("\x08", "BACKSPACE"),
    ("\x0b", "VERTICAL_TAB"),
    ("\x0c", "FORM_FEED"),
    ("\x0d", "CARRIAGE_RETURN"),
    ("\x1b", "ESCAPE"),
    ("\x7f", "DELETE"),
])
def test_sanitize_removes_specific_control_chars(control_char, name):
    """Parametrized test for specific control character removal"""
    content = f"Before{control_char}After"
    sanitized = sanitize_content(content)
    assert sanitized == "BeforeAfter", f"Failed to remove {name}"
    assert control_char not in sanitized


@pytest.mark.parametrize("size_kb,should_pass", [
    (255, True),   # Just under limit
    (256, True),   # Exactly at limit
    (257, False),  # Just over limit
    (1024, False), # Way over limit
])
def test_size_validation_boundary_conditions(mock_map_dir, size_kb, should_pass):
    """Parametrized test for size validation boundary conditions"""
    file_path = mock_map_dir / f"file_{size_kb}kb.txt"
    content = "x" * (size_kb * 1024)
    file_path.write_text(content, encoding='utf-8')

    result = validate_file_size(file_path, MAX_FILE_SIZE_BYTES)

    if should_pass:
        assert result["valid"] is True
        assert result["error"] is None
    else:
        assert result["valid"] is False
        assert "File too large" in result["error"]


# ============================================================================
# Regex Pattern Test
# ============================================================================

def test_control_char_pattern_matches_expected():
    """Test that the control character regex pattern matches expected characters"""
    # Test characters that SHOULD match (be removed)
    should_match = [
        "\x00", "\x01", "\x08",  # NULL, SOH, BACKSPACE
        "\x0b", "\x0c", "\x0d",  # VT, FF, CR
        "\x1b", "\x7f",          # ESC, DELETE
        "\u2028", "\u2029"       # Unicode line/para separators
    ]

    for char in should_match:
        match = CONTROL_CHAR_PATTERN.search(char)
        assert match is not None, f"Pattern should match {repr(char)}"

    # Test characters that SHOULD NOT match (be preserved)
    should_not_match = [
        "\n", "\t",              # Newline, tab (explicitly preserved)
        "a", "Z", "0",           # Alphanumeric
        " ", "!", "@",           # Printable symbols
        "👋", "🌍"               # Emoji
    ]

    for char in should_not_match:
        match = CONTROL_CHAR_PATTERN.search(char)
        assert match is None, f"Pattern should NOT match {repr(char)}"
