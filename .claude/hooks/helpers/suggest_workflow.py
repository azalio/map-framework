#!/usr/bin/env python3
"""Helper script for workflow suggestion: Match user message against workflow rules.

This script:
1. Takes user message as input (via stdin or --message argument)
2. Loads workflow-rules.json
3. Matches message against keywords and intent patterns
4. Returns suggested workflow with reason (if match found)
5. Tracks suggestions per session to avoid repeats

Session Tracking:
- Stores suggested workflow IDs in .claude/cache/workflow_suggestions_session.txt
- One workflow ID per line
- Prevents suggesting same workflow multiple times in a session
"""

import sys
import json
import re
import argparse
import signal
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# SECURITY: Regex timeout protection against ReDoS attacks
REGEX_TIMEOUT_SECONDS = 2

# SECURITY: Maximum regex pattern length to prevent complexity attacks
MAX_REGEX_LENGTH = 200


class TimeoutException(Exception):
    """Exception raised when regex matching times out."""

    pass


def timeout_handler(signum, frame):
    """Signal handler for regex timeout."""
    raise TimeoutException("Regex matching timed out")


def validate_regex_pattern(pattern: str) -> Tuple[bool, Optional[str]]:
    """Validate regex pattern for safety.

    Checks for:
    - Pattern length (prevent complexity attacks)
    - Compilation errors
    - Potentially dangerous patterns (nested quantifiers, catastrophic backtracking)

    Args:
        pattern: Regex pattern to validate

    Returns:
        (is_valid, error_message) tuple
    """
    # Check pattern length
    if len(pattern) > MAX_REGEX_LENGTH:
        return False, f"Pattern too long ({len(pattern)} > {MAX_REGEX_LENGTH})"

    # Try to compile pattern
    try:
        re.compile(pattern)
    except re.error as e:
        return False, f"Invalid regex: {e}"

    # Check for potentially dangerous patterns (nested quantifiers)
    # Patterns like (a+)+, (a*)*, (a+)* can cause catastrophic backtracking
    dangerous_patterns = [
        r"\([^)]*[+*]\)[+*]",  # Nested quantifiers: (a+)* or (a*)+ etc
        r"\([^)]*[+*][^)]*\)[+*]",  # More complex nested quantifiers
    ]

    for dangerous in dangerous_patterns:
        if re.search(dangerous, pattern):
            return (
                False,
                f"Potentially dangerous pattern (nested quantifiers): {pattern}",
            )

    return True, None


def load_workflow_rules(rules_path: Path) -> Optional[Dict]:
    """Load and parse workflow-rules.json.

    Args:
        rules_path: Path to workflow-rules.json

    Returns:
        Parsed JSON dict or None on error
    """
    try:
        if not rules_path.exists():
            print(
                f"[suggest_workflow] Rules file not found: {rules_path}",
                file=sys.stderr,
            )
            return None

        with open(rules_path, "r", encoding="utf-8") as f:
            rules = json.load(f)

        # Validate structure
        if "workflows" not in rules:
            print(
                "[suggest_workflow] Invalid rules: missing 'workflows' key",
                file=sys.stderr,
            )
            return None

        # SECURITY: Validate all regex patterns in workflow rules
        for workflow_id, config in rules.get("workflows", {}).items():
            patterns = config.get("promptTriggers", {}).get("intentPatterns", [])
            valid_patterns = []
            for pattern in patterns:
                is_valid, error = validate_regex_pattern(pattern)
                if not is_valid:
                    print(
                        f"[suggest_workflow] Invalid pattern in '{workflow_id}': {error}",
                        file=sys.stderr,
                    )
                else:
                    valid_patterns.append(pattern)
            # Replace with only valid patterns
            config["promptTriggers"]["intentPatterns"] = valid_patterns

        return rules

    except json.JSONDecodeError as e:
        print(f"[suggest_workflow] Failed to parse rules JSON: {e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[suggest_workflow] Error loading rules: {e}", file=sys.stderr)
        return None


def match_keywords(message: str, keywords: List[str]) -> bool:
    """Check if any keyword appears in message (case-insensitive).

    Args:
        message: User's input message
        keywords: List of keywords to search for

    Returns:
        True if any keyword found
    """
    message_lower = message.lower()
    return any(keyword.lower() in message_lower for keyword in keywords)


def match_intent_patterns(message: str, patterns: List[str]) -> Optional[str]:
    """Check if message matches any intent regex pattern.

    SECURITY: Uses timeout protection to prevent ReDoS attacks.

    Args:
        message: User's input message
        patterns: List of regex patterns to test

    Returns:
        Matched pattern string or None
    """
    for pattern in patterns:
        try:
            # SECURITY: Validate pattern before use
            is_valid, error = validate_regex_pattern(pattern)
            if not is_valid:
                print(
                    f"[suggest_workflow] Skipping invalid pattern: {error}",
                    file=sys.stderr,
                )
                continue

            # SECURITY: Set alarm for regex timeout (Unix-like systems only)
            # This prevents ReDoS attacks from malicious patterns
            if hasattr(signal, "SIGALRM"):
                signal.signal(signal.SIGALRM, timeout_handler)
                signal.alarm(REGEX_TIMEOUT_SECONDS)

            try:
                # Perform regex match with timeout protection
                if re.search(pattern, message, re.IGNORECASE):
                    if hasattr(signal, "SIGALRM"):
                        signal.alarm(0)  # Cancel alarm
                    return pattern
            except TimeoutException:
                print(
                    f"[suggest_workflow] Regex timeout for pattern '{pattern}'",
                    file=sys.stderr,
                )
                continue
            finally:
                # Always cancel alarm
                if hasattr(signal, "SIGALRM"):
                    signal.alarm(0)

        except re.error as e:
            print(
                f"[suggest_workflow] Invalid regex pattern '{pattern}': {e}",
                file=sys.stderr,
            )
            continue

    return None


def match_workflow(message: str, workflow_config: Dict) -> Tuple[bool, Optional[str]]:
    """Check if message matches a workflow's trigger conditions.

    Args:
        message: User's input message
        workflow_config: Workflow configuration dict

    Returns:
        (matched, reason) tuple
    """
    prompt_triggers = workflow_config.get("promptTriggers", {})

    # Check keywords
    keywords = prompt_triggers.get("keywords", [])
    if keywords and match_keywords(message, keywords):
        matched_keywords = [kw for kw in keywords if kw.lower() in message.lower()]
        return True, f"Keywords: {', '.join(matched_keywords[:3])}"

    # Check intent patterns
    intent_patterns = prompt_triggers.get("intentPatterns", [])
    if intent_patterns:
        matched_pattern = match_intent_patterns(message, intent_patterns)
        if matched_pattern:
            return True, f"Intent pattern: {matched_pattern}"

    return False, None


def get_session_file() -> Path:
    """Get path to session tracking file.

    Returns:
        Path to .claude/cache/workflow_suggestions_session.txt
    """
    cache_dir = Path.cwd() / ".claude" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / "workflow_suggestions_session.txt"


def load_session_suggestions() -> set:
    """Load workflow IDs already suggested in this session.

    Returns:
        Set of workflow IDs
    """
    session_file = get_session_file()

    if not session_file.exists():
        return set()

    try:
        with open(session_file, "r", encoding="utf-8") as f:
            # One workflow ID per line, strip whitespace
            return {line.strip() for line in f if line.strip()}
    except Exception as e:
        print(f"[suggest_workflow] Error loading session file: {e}", file=sys.stderr)
        return set()


def save_session_suggestion(workflow_id: str):
    """Record workflow suggestion in session tracking file.

    Args:
        workflow_id: ID of suggested workflow (e.g., 'map-debug')
    """
    session_file = get_session_file()

    try:
        with open(session_file, "a", encoding="utf-8") as f:
            f.write(f"{workflow_id}\n")
    except Exception as e:
        print(f"[suggest_workflow] Error saving to session file: {e}", file=sys.stderr)


def find_best_workflow(message: str, rules: Dict) -> Optional[Tuple[str, str, str]]:
    """Find best matching workflow for user message.

    Matches workflows against message and returns highest priority match.
    Skips workflows already suggested in this session.

    Args:
        message: User's input message
        rules: Parsed workflow-rules.json

    Returns:
        (workflow_id, description, reason) tuple or None
    """
    workflows = rules.get("workflows", {})
    already_suggested = load_session_suggestions()

    # Priority order (high > medium > low)
    priority_order = {"high": 3, "medium": 2, "low": 1}

    matches = []

    for workflow_id, config in workflows.items():
        # Skip if already suggested in this session
        if workflow_id in already_suggested:
            print(
                f"[suggest_workflow] Skipping {workflow_id} (already suggested)",
                file=sys.stderr,
            )
            continue

        matched, reason = match_workflow(message, config)

        if matched:
            priority = config.get("priority", "low")
            priority_value = priority_order.get(priority, 0)
            description = config.get("description", workflow_id)

            matches.append((workflow_id, description, reason, priority_value))

    if not matches:
        return None

    # Sort by priority (highest first)
    matches.sort(key=lambda x: x[3], reverse=True)

    # Return best match (workflow_id, description, reason)
    best = matches[0]
    return best[0], best[1], best[2]


def main():
    """Main entry point for workflow suggestion helper."""
    parser = argparse.ArgumentParser(
        description="Match user message against workflow rules and suggest best workflow"
    )
    parser.add_argument(
        "--message",
        required=False,
        help="User message to analyze (deprecated: use stdin instead)",
    )
    parser.add_argument(
        "--rules",
        default=".claude/workflow-rules.json",
        help="Path to workflow rules JSON (default: .claude/workflow-rules.json)",
    )

    args = parser.parse_args()

    # SECURITY FIX: Support both stdin (preferred) and --message (backward compatibility)
    # Check --message first for backward compatibility with existing tests/callers
    if args.message:
        # Backward compatibility: --message argument still works
        message = args.message
        print(
            "[suggest_workflow] Using --message argument (legacy mode)", file=sys.stderr
        )
    elif not sys.stdin.isatty():
        # New secure approach: stdin input (preferred when no --message)
        message = sys.stdin.read().strip()
        print("[suggest_workflow] Reading from stdin (secure mode)", file=sys.stderr)
    else:
        print(
            "[suggest_workflow] No input provided (stdin or --message)", file=sys.stderr
        )
        print(json.dumps({}))
        return 0

    # Load workflow rules
    rules_path = Path(args.rules)
    rules = load_workflow_rules(rules_path)

    if not rules:
        # No rules file or parsing failed - return empty result
        print(
            "[suggest_workflow] No rules loaded, skipping suggestion", file=sys.stderr
        )
        print(json.dumps({}))
        return 0

    # Find best matching workflow
    match = find_best_workflow(message, rules)

    if not match:
        # No match or all matches already suggested
        print("[suggest_workflow] No workflow match found", file=sys.stderr)
        print(json.dumps({}))
        return 0

    workflow_id, description, reason = match

    # Save to session tracking
    save_session_suggestion(workflow_id)

    print(
        f"[suggest_workflow] Matched workflow: {workflow_id} ({reason})",
        file=sys.stderr,
    )

    # Output JSON with workflow suggestion
    output = {"workflow": workflow_id, "description": description, "reason": reason}

    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"[suggest_workflow] Fatal error: {e}", file=sys.stderr)
        print(json.dumps({}))  # Empty result on error
        sys.exit(0)  # Always exit 0 to avoid blocking
