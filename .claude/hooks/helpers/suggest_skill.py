#!/usr/bin/env python3
"""Helper script for skill suggestion: Match user message against skill rules.

This script:
1. Takes user message as input (via stdin or --message argument)
2. Loads skill-rules.json
3. Matches message against keywords and intent patterns
4. Returns suggested skill with reason (if match found)
5. Tracks suggestions per session to avoid repeats

Session Tracking:
- Stores suggested skill IDs in .claude/cache/skill_suggestions_session.txt
- One skill ID per line
- Prevents suggesting same skill multiple times in a session
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


def load_skill_rules(rules_path: Path) -> Optional[Dict]:
    """Load and parse skill-rules.json.

    Args:
        rules_path: Path to skill-rules.json

    Returns:
        Parsed JSON dict or None on error
    """
    try:
        if not rules_path.exists():
            print(
                f"[suggest_skill] Rules file not found: {rules_path}", file=sys.stderr
            )
            return None

        with open(rules_path, "r", encoding="utf-8") as f:
            rules = json.load(f)

        # Validate structure
        if "skills" not in rules:
            print(
                "[suggest_skill] Invalid rules: missing 'skills' key", file=sys.stderr
            )
            return None

        # SECURITY: Validate all regex patterns in skill rules
        for skill_id, config in rules.get("skills", {}).items():
            patterns = config.get("promptTriggers", {}).get("intentPatterns", [])
            valid_patterns = []
            for pattern in patterns:
                is_valid, error = validate_regex_pattern(pattern)
                if not is_valid:
                    print(
                        f"[suggest_skill] Invalid pattern in '{skill_id}': {error}",
                        file=sys.stderr,
                    )
                else:
                    valid_patterns.append(pattern)
            # Replace with only valid patterns
            config["promptTriggers"]["intentPatterns"] = valid_patterns

        return rules

    except json.JSONDecodeError as e:
        print(f"[suggest_skill] Failed to parse rules JSON: {e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[suggest_skill] Error loading rules: {e}", file=sys.stderr)
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
                    f"[suggest_skill] Skipping invalid pattern: {error}",
                    file=sys.stderr,
                )
                continue

            # SECURITY: Set alarm for regex timeout (Unix-like systems only)
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
                    f"[suggest_skill] Regex timeout for pattern '{pattern}'",
                    file=sys.stderr,
                )
                continue
            finally:
                # Always cancel alarm
                if hasattr(signal, "SIGALRM"):
                    signal.alarm(0)

        except re.error as e:
            print(
                f"[suggest_skill] Invalid regex pattern '{pattern}': {e}",
                file=sys.stderr,
            )
            continue

    return None


def match_skill(message: str, skill_config: Dict) -> Tuple[bool, Optional[str]]:
    """Check if message matches a skill's trigger conditions.

    Args:
        message: User's input message
        skill_config: Skill configuration dict

    Returns:
        (matched, reason) tuple
    """
    prompt_triggers = skill_config.get("promptTriggers", {})

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
        Path to .claude/cache/skill_suggestions_session.txt
    """
    cache_dir = Path.cwd() / ".claude" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / "skill_suggestions_session.txt"


def load_session_suggestions() -> set:
    """Load skill IDs already suggested in this session.

    Returns:
        Set of skill IDs
    """
    session_file = get_session_file()

    if not session_file.exists():
        return set()

    try:
        with open(session_file, "r", encoding="utf-8") as f:
            # One skill ID per line, strip whitespace
            return {line.strip() for line in f if line.strip()}
    except Exception as e:
        print(f"[suggest_skill] Error loading session file: {e}", file=sys.stderr)
        return set()


def save_session_suggestion(skill_id: str):
    """Record skill suggestion in session tracking file.

    Args:
        skill_id: ID of suggested skill (e.g., 'map-workflows-guide')
    """
    session_file = get_session_file()

    try:
        with open(session_file, "a", encoding="utf-8") as f:
            f.write(f"{skill_id}\n")
    except Exception as e:
        print(f"[suggest_skill] Error saving to session file: {e}", file=sys.stderr)


def find_best_skill(message: str, rules: Dict) -> Optional[Tuple[str, str, str]]:
    """Find best matching skill for user message.

    Matches skills against message and returns highest priority match.
    Skips skills already suggested in this session.

    Args:
        message: User's input message
        rules: Parsed skill-rules.json

    Returns:
        (skill_id, description, reason) tuple or None
    """
    skills = rules.get("skills", {})
    already_suggested = load_session_suggestions()

    # Priority order (high > medium > low)
    priority_order = {"high": 3, "medium": 2, "low": 1}

    matches = []

    for skill_id, config in skills.items():
        # Skip if already suggested in this session
        if skill_id in already_suggested:
            print(
                f"[suggest_skill] Skipping {skill_id} (already suggested)",
                file=sys.stderr,
            )
            continue

        matched, reason = match_skill(message, config)

        if matched:
            priority = config.get("priority", "low")
            priority_value = priority_order.get(priority, 0)
            description = config.get("description", skill_id)

            matches.append((skill_id, description, reason, priority_value))

    if not matches:
        return None

    # Sort by priority (highest first)
    matches.sort(key=lambda x: x[3], reverse=True)

    # Return best match (skill_id, description, reason)
    best = matches[0]
    return best[0], best[1], best[2]


def main():
    """Main entry point for skill suggestion helper."""
    parser = argparse.ArgumentParser(
        description="Match user message against skill rules and suggest best skill"
    )
    parser.add_argument(
        "--message",
        required=False,
        help="User message to analyze (deprecated: use stdin instead)",
    )
    parser.add_argument(
        "--rules",
        default=".claude/skills/skill-rules.json",
        help="Path to skill rules JSON (default: .claude/skills/skill-rules.json)",
    )

    args = parser.parse_args()

    # SECURITY FIX: Support both stdin (preferred) and --message (backward compatibility)
    if args.message:
        message = args.message
        print("[suggest_skill] Using --message argument (legacy mode)", file=sys.stderr)
    elif not sys.stdin.isatty():
        message = sys.stdin.read().strip()
        print("[suggest_skill] Reading from stdin (secure mode)", file=sys.stderr)
    else:
        print("[suggest_skill] No input provided (stdin or --message)", file=sys.stderr)
        print(json.dumps({}))
        return 0

    # Load skill rules
    rules_path = Path(args.rules)
    rules = load_skill_rules(rules_path)

    if not rules:
        print("[suggest_skill] No rules loaded, skipping suggestion", file=sys.stderr)
        print(json.dumps({}))
        return 0

    # Find best matching skill
    match = find_best_skill(message, rules)

    if not match:
        print("[suggest_skill] No skill match found", file=sys.stderr)
        print(json.dumps({}))
        return 0

    skill_id, description, reason = match

    # Save to session tracking
    save_session_suggestion(skill_id)

    print(f"[suggest_skill] Matched skill: {skill_id} ({reason})", file=sys.stderr)

    # Output JSON with skill suggestion
    output = {"skill": skill_id, "description": description, "reason": reason}

    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"[suggest_skill] Fatal error: {e}", file=sys.stderr)
        print(json.dumps({}))
        sys.exit(0)
