#!/usr/bin/env python3
"""
Claude Code PreToolUse Hook: Block Sensitive File Access
Intercepts Read/Edit/Write tool calls and prevents access to sensitive files
like .env files, credentials, private keys, and secrets.

USAGE:
  This hook runs automatically before Read/Edit/Write tool calls.
  No manual invocation needed - Claude Code handles hook execution.

BLOCKED FILE PATTERNS:
  - .env, .env.local, .env.production (environment variables)
  - *credentials*, *secret* (credential/secret files)
  - *.pem, *_(private|secret|rsa|dsa|ecdsa).key (private keys)
  - *_rsa, *_dsa, *_ecdsa, *_ed25519 (SSH keys without extension)
  - *.p12, *.pfx, *.keystore, *.jks (certificates/keystores)
  - *.ppk (PuTTY keys)

ALLOWED FILE PATTERNS:
  - *.pub (public keys - safe to read)
  - license.key, api.key (generic .key files without private key indicators)

HOOK BEHAVIOR:
  - Exit code 0: Allow tool execution (non-sensitive file)
  - Exit code 2: Block tool execution (sensitive file detected)

TESTING:
  echo '{"tool_name": "Read", "tool_input": {"file_path": ".env"}}' | python3 block-secrets.py
  # Expected: Exit code 2, JSON error on stderr

PERFORMANCE:
  Target: <100ms per invocation
  Actual: ~27ms average (measured with 100 iterations)
"""
import json
import sys
import re
from pathlib import Path

# Sensitive file patterns (PRE-COMPILED for performance)
SENSITIVE_PATTERNS = [
    re.compile(r"\.env.*", re.IGNORECASE),  # .env, .env.local, .env.production, etc.
    re.compile(
        r".*credentials.*", re.IGNORECASE
    ),  # credentials.json, aws-credentials, etc.
    re.compile(r".*secret.*", re.IGNORECASE),  # secrets.yaml, secret-key.txt, etc.
    re.compile(r".*\.pem$", re.IGNORECASE),  # Private key files
    re.compile(
        r".*_(private|secret|rsa|dsa|ecdsa)\.key$", re.IGNORECASE
    ),  # Specific private key files only
    re.compile(r".*_rsa$", re.IGNORECASE),  # SSH keys without extension
    re.compile(r".*_dsa$", re.IGNORECASE),  # DSA keys
    re.compile(r".*_ecdsa$", re.IGNORECASE),  # ECDSA keys
    re.compile(r".*_ed25519$", re.IGNORECASE),  # Ed25519 keys
    re.compile(r".*\.p12$", re.IGNORECASE),  # PKCS#12 certificate files
    re.compile(r".*\.pfx$", re.IGNORECASE),  # PKCS#12 certificate files (Windows)
    re.compile(r".*\.keystore$", re.IGNORECASE),  # Java keystores
    re.compile(r".*\.jks$", re.IGNORECASE),  # Java keystores
    re.compile(r".*\.ppk$", re.IGNORECASE),  # PuTTY private keys
]


def is_sensitive_file(file_path: str) -> bool:
    """Check if file path matches any sensitive file pattern.

    Checks ALL path components (not just filename) to catch patterns
    in directory names or parent paths.
    """
    path_obj = Path(file_path)

    # Check each path component against all patterns
    for part in path_obj.parts:
        for pattern in SENSITIVE_PATTERNS:
            if pattern.match(part):
                return True
    return False


def block_access(file_path: str, tool_name: str):
    """Block tool execution and output error message."""
    error_output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "error": f"Blocked: Access to sensitive file '{file_path}' is prohibited",
            "details": f"Tool '{tool_name}' attempted to access a protected file. Sensitive files include: .env*, *credentials*, *secret*, private keys (*.pem, *.key, *_rsa, etc.)",
            "suggestion": "If you need to work with sensitive data, use environment variables or a secrets management system instead of reading raw credential files.",
        }
    }
    print(json.dumps(error_output), file=sys.stderr)
    sys.exit(2)  # Exit code 2 blocks execution


def main():
    """Main hook execution logic."""
    # Load input from stdin
    try:
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON input: {e}", file=sys.stderr)
        sys.exit(1)

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})

    # Only intercept Read, Edit, Write tools
    if tool_name not in ["Read", "Edit", "Write"]:
        sys.exit(0)  # Allow other tools

    # Extract file_path from tool_input
    file_path = tool_input.get("file_path", "")

    # If no file_path, allow (shouldn't happen for Read/Edit/Write, but be safe)
    if not file_path:
        sys.exit(0)

    # Check if file is sensitive
    if is_sensitive_file(file_path):
        block_access(file_path, tool_name)

    # Allow non-sensitive files
    sys.exit(0)


if __name__ == "__main__":
    main()
