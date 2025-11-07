#!/usr/bin/env python3
"""Helper script for checkpoint file validation with security checks.

This script validates checkpoint files from .map/ directory with multiple
security layers to prevent:
- Path traversal attacks (../, absolute paths)
- Size bomb attacks (files >256KB)
- Control character injection (terminal escape codes)
- UTF-8 encoding errors

Security Design (Defense-in-Depth):
1. Path validation: Ensure file is within .map/ directory only
2. Size validation: Reject files >256KB before reading
3. Content sanitization: Strip control characters except newlines/tabs
4. UTF-8 validation: Handle encoding errors gracefully

All checks use AND logic - file must pass ALL layers to be valid.
"""

import sys
import json
import re
import argparse
from pathlib import Path
from typing import Dict, Any

# Security constants
MAX_FILE_SIZE_BYTES = 256 * 1024  # 256KB
ALLOWED_BASE_DIR = ".map"  # Only allow files from .map/ directory

# Regex to strip control characters except newline (\n) and tab (\t)
# Removes: \x00-\x08, \x0b-\x0d (includes \r), \x0e-\x1f, \x7f (DELETE)
# Also removes Unicode control characters: \u0080-\u009f, \u2028, \u2029
CONTROL_CHAR_PATTERN = re.compile(
    r"[\x00-\x08\x0b-\x0d\x0e-\x1f\x7f\u0080-\u009f\u2028\u2029]"
)


def validate_path_security(
    file_path: str, base_dir: str = ALLOWED_BASE_DIR
) -> Dict[str, Any]:
    """Validate file path is within allowed directory (prevents path traversal).

    Security checks:
    1. Resolve to absolute path (handles .., symlinks)
    2. Verify resolved path starts with base_dir absolute path
    3. Reject absolute paths that escape base_dir

    Args:
        file_path: User-provided file path (can be relative or absolute)
        base_dir: Allowed base directory (default: .map/)

    Returns:
        Dict with:
        - valid: bool (True if path is safe)
        - error: str (error message if invalid, None if valid)
        - resolved_path: Path (resolved absolute path if valid, None if invalid)
    """
    try:
        # Convert to Path objects
        user_path = Path(file_path)
        base_path = Path(base_dir).resolve()

        # Resolve user path to absolute (follows symlinks, resolves ..)
        # If file doesn't exist, resolve() still works for path validation
        resolved = user_path.resolve()

        # Security check: Ensure resolved path is within base_dir
        # Use is_relative_to() if Python 3.9+, else check with string prefix
        try:
            # Python 3.9+
            if not resolved.is_relative_to(base_path):
                return {
                    "valid": False,
                    "error": f"Path traversal detected: {file_path} escapes {base_dir}/ directory",
                    "resolved_path": None,
                }
        except AttributeError:
            # Python 3.8 fallback: Check if resolved path starts with base_path
            try:
                resolved.relative_to(base_path)
            except ValueError:
                return {
                    "valid": False,
                    "error": f"Path traversal detected: {file_path} escapes {base_dir}/ directory",
                    "resolved_path": None,
                }

        return {"valid": True, "error": None, "resolved_path": resolved}

    except Exception as e:
        return {
            "valid": False,
            "error": f"Path validation error: {str(e)}",
            "resolved_path": None,
        }


def validate_file_size(
    file_path: Path, max_size: int = MAX_FILE_SIZE_BYTES
) -> Dict[str, Any]:
    """Validate file size is within allowed limit (prevents size bomb attacks).

    Security: Check size BEFORE reading file into memory.

    Args:
        file_path: Resolved path to file
        max_size: Maximum allowed size in bytes (default: 256KB)

    Returns:
        Dict with:
        - valid: bool (True if size acceptable)
        - error: str (error message if too large, None if valid)
        - size_bytes: int (actual file size)
    """
    try:
        # Check file exists
        if not file_path.exists():
            return {
                "valid": False,
                "error": f"File not found: {file_path}",
                "size_bytes": 0,
            }

        if not file_path.is_file():
            return {
                "valid": False,
                "error": f"Not a regular file: {file_path}",
                "size_bytes": 0,
            }

        # Get file size without reading content
        size_bytes = file_path.stat().st_size

        if size_bytes > max_size:
            size_kb = size_bytes / 1024
            max_kb = max_size / 1024
            return {
                "valid": False,
                "error": f"File too large: {size_kb:.1f}KB exceeds {max_kb:.0f}KB limit",
                "size_bytes": size_bytes,
            }

        return {"valid": True, "error": None, "size_bytes": size_bytes}

    except Exception as e:
        return {
            "valid": False,
            "error": f"Size validation error: {str(e)}",
            "size_bytes": 0,
        }


def sanitize_content(content: str) -> str:
    """Sanitize file content by removing control characters.

    Security: Strip control characters that could cause terminal injection
    or break JSON parsing, while preserving newlines and tabs.

    Removes:
    - \x00-\x08: NULL, control codes
    - \x0b-\x0c: Vertical tab, form feed
    - \x0e-\x1f: More control codes (including ESC)
    - \x7f: DELETE character

    Preserves:
    - \x09: Tab (\t)
    - \x0a: Newline (\n)

    (Carriage return \r is REMOVED for terminal safety)

    Args:
        content: Raw file content

    Returns:
        Sanitized content with control characters removed
    """
    return CONTROL_CHAR_PATTERN.sub("", content)


def read_and_validate_content(file_path: Path) -> Dict[str, Any]:
    """Read file and validate UTF-8 encoding.

    Args:
        file_path: Resolved path to file

    Returns:
        Dict with:
        - valid: bool (True if content readable)
        - error: str (error message if unreadable, None if valid)
        - content: str (raw file content if valid, None if invalid)
    """
    try:
        # Read with explicit UTF-8 encoding and error handling
        content = file_path.read_text(encoding="utf-8", errors="strict")

        return {"valid": True, "error": None, "content": content}

    except UnicodeDecodeError as e:
        return {
            "valid": False,
            "error": f"Invalid UTF-8 encoding: {str(e)}",
            "content": None,
        }
    except Exception as e:
        return {
            "valid": False,
            "error": f"Failed to read file: {str(e)}",
            "content": None,
        }


def validate_checkpoint_file(
    file_path: str,
    base_dir: str = ALLOWED_BASE_DIR,
    max_size: int = MAX_FILE_SIZE_BYTES,
) -> Dict[str, Any]:
    """Validate checkpoint file with multiple security layers (defense-in-depth).

    Security layers (all must pass - AND logic):
    1. Path validation: Ensure file is within specified base directory
    2. Size validation: Reject files exceeding size limit
    3. Content reading: Validate UTF-8 encoding
    4. Sanitization: Strip control characters

    Args:
        file_path: User-provided file path
        base_dir: Allowed base directory (default: .map/)
        max_size: Maximum file size in bytes (default: 256KB)

    Returns:
        Dict with:
        - valid: bool (True only if ALL checks pass)
        - error: str (first error encountered, None if all pass)
        - sanitized_content: str (sanitized content if valid, empty if invalid)
        - metadata: dict (validation details: size, path)
    """
    metadata = {"original_path": file_path, "resolved_path": None, "size_bytes": 0}

    # Layer 1: Path security validation
    path_result = validate_path_security(file_path, base_dir)
    if not path_result["valid"]:
        return {
            "valid": False,
            "error": path_result["error"],
            "sanitized_content": "",
            "metadata": metadata,
        }

    resolved_path = path_result["resolved_path"]
    metadata["resolved_path"] = str(resolved_path)

    # Layer 2: Size validation (before reading)
    size_result = validate_file_size(resolved_path, max_size)
    if not size_result["valid"]:
        return {
            "valid": False,
            "error": size_result["error"],
            "sanitized_content": "",
            "metadata": metadata,
        }

    metadata["size_bytes"] = size_result["size_bytes"]

    # Layer 3: Read content with UTF-8 validation
    content_result = read_and_validate_content(resolved_path)
    if not content_result["valid"]:
        return {
            "valid": False,
            "error": content_result["error"],
            "sanitized_content": "",
            "metadata": metadata,
        }

    # Layer 4: Sanitize content (remove control characters)
    sanitized = sanitize_content(content_result["content"])

    # All layers passed - return sanitized content
    return {
        "valid": True,
        "error": None,
        "sanitized_content": sanitized,
        "metadata": metadata,
    }


def main():
    """Main entry point for validation helper script."""
    parser = argparse.ArgumentParser(
        description="Validate checkpoint file with security checks"
    )
    parser.add_argument(
        "--file",
        required=True,
        help="Path to checkpoint file (must be in .map/ directory)",
    )
    parser.add_argument(
        "--base-dir",
        default=ALLOWED_BASE_DIR,
        help=f"Base directory for validation (default: {ALLOWED_BASE_DIR})",
    )
    parser.add_argument(
        "--max-size-kb",
        type=int,
        default=256,
        help="Maximum file size in KB (default: 256)",
    )

    args = parser.parse_args()

    # Convert max_size_kb to bytes
    max_size_bytes = args.max_size_kb * 1024

    # Validate file with custom parameters
    result = validate_checkpoint_file(args.file, args.base_dir, max_size_bytes)

    # Log to stderr for debugging
    if result["valid"]:
        size_kb = result["metadata"]["size_bytes"] / 1024
        print(
            f"[validate_checkpoint_file] ✓ Valid file: {args.file} ({size_kb:.1f}KB)",
            file=sys.stderr,
        )
    else:
        print(
            f"[validate_checkpoint_file] ✗ Invalid file: {result['error']}",
            file=sys.stderr,
        )

    # Output JSON to stdout
    print(json.dumps(result, indent=2))

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        # Fatal error - output error JSON and exit cleanly
        print(f"[validate_checkpoint_file] Fatal error: {e}", file=sys.stderr)
        error_result = {
            "valid": False,
            "error": f"Unexpected error: {str(e)}",
            "sanitized_content": "",
            "metadata": {},
        }
        print(json.dumps(error_result, indent=2))
        sys.exit(0)  # Exit 0 to avoid blocking hooks
