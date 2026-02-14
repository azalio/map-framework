#!/usr/bin/env python3
"""
Safety Guardrails - PreToolUse Hook

Merged hook that blocks:
- Access to sensitive files (.env, credentials, private keys)
- Dangerous shell commands (rm -rf /, force push, etc.)

Trigger: Edit|Write|Bash
Exit codes:
  0 - Allow
  2 - Block (with error message)
"""

import json
import re
import sys

# Dangerous file patterns (case-insensitive)
DANGEROUS_FILE_PATTERNS = [
    r"\.env($|\.)",  # .env, .env.local, .env.production
    r"credentials",
    r"private[_-]?key",
    r"\.pem$",
    r"secrets?\.(json|ya?ml|toml)",
    r"id_rsa",
    r"id_ed25519",
    r"\.key$",
    r"password",
    r"token",
]

# Dangerous bash command patterns
DANGEROUS_COMMANDS = [
    r"rm\s+-rf\s+/",  # rm -rf /
    r"rm\s+-rf\s+\*",  # rm -rf *
    r"rm\s+-rf\s+\.\.",  # rm -rf ..
    r"git\s+push.*--force.*main",
    r"git\s+push.*--force.*master",
    r"git\s+push\s+-f.*main",
    r"git\s+push\s+-f.*master",
    r"git\s+reset\s+--hard",
    r":\(\)\s*\{\s*:\|:&\s*\}\s*;:",  # Fork bomb
    r"chmod\s+-R\s+777\s+/",
    r">\s*/dev/sd",  # Writing to disk devices
]

# Safe path prefixes (skip checks for known safe directories)
SAFE_PATH_PREFIXES = ["src/", "lib/", "test/", "tests/", "docs/", "pkg/", "cmd/", "internal/"]


def is_safe_path(path: str) -> bool:
    """Check if path is in known safe directory."""
    return any(path.startswith(prefix) for prefix in SAFE_PATH_PREFIXES)


def check_file_safety(path: str) -> tuple[bool, str]:
    """Check if file path is safe to access. Returns (is_safe, reason)."""
    if not path:
        return True, ""

    # Fast path: known safe directories
    if is_safe_path(path):
        return True, ""

    # Check dangerous patterns
    path_lower = path.lower()
    for pattern in DANGEROUS_FILE_PATTERNS:
        if re.search(pattern, path_lower, re.IGNORECASE):
            return False, f"Blocked: Access to sensitive file pattern '{pattern}' in path: {path}"

    return True, ""


def check_command_safety(command: str) -> tuple[bool, str]:
    """Check if bash command is safe. Returns (is_safe, reason)."""
    if not command:
        return True, ""

    for pattern in DANGEROUS_COMMANDS:
        if re.search(pattern, command, re.IGNORECASE):
            return False, f"Blocked: Dangerous command pattern detected: {pattern}"

    return True, ""


def block_access(reason: str, tool_name: str) -> None:
    """Block tool execution with error message."""
    error_output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "error": reason,
            "details": f"Tool '{tool_name}' blocked by safety guardrails",
        }
    }
    print(json.dumps(error_output), file=sys.stderr)
    sys.exit(2)


def main() -> None:
    try:
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError:
        print("{}")
        sys.exit(0)

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})

    # Check file-based tools
    if tool_name in ("Edit", "Write", "Read"):
        file_path = tool_input.get("file_path", "") or tool_input.get("path", "")
        is_safe, reason = check_file_safety(file_path)
        if not is_safe:
            block_access(reason, tool_name)

    # Check bash commands
    elif tool_name == "Bash":
        command = tool_input.get("command", "")
        is_safe, reason = check_command_safety(command)
        if not is_safe:
            block_access(reason, tool_name)

    print("{}")
    sys.exit(0)


if __name__ == "__main__":
    main()
