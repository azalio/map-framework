#!/usr/bin/env python3
"""Helper script for user-prompt-submit hook: Query playbook and format bullets.

This script:
1. Takes user message as input
2. Calls 'mapify playbook query' CLI with JSON format
3. Parses results and formats top bullets as markdown
4. Outputs JSON for Claude Code prompt injection

Note: This script CANNOT call MCP tools (runs outside Claude context).
It relies on the mapify CLI which uses local playbook search.
"""

import sys
import json
import subprocess
import argparse
from typing import Dict, List, Optional


def extract_keywords(message: str, max_keywords: int = 10) -> str:
    """Extract key terms from user message for search query.

    Simple approach: Remove common words, take first N words.
    Future enhancement: Use NLP for better keyword extraction.

    Args:
        message: User's input message
        max_keywords: Maximum number of keywords to extract

    Returns:
        Space-separated keywords suitable for search
    """
    # Common stop words to filter out
    stop_words = {
        "the",
        "a",
        "an",
        "and",
        "or",
        "but",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "with",
        "by",
        "from",
        "up",
        "about",
        "into",
        "through",
        "during",
        "please",
        "can",
        "you",
        "could",
        "would",
        "should",
        "help",
        "me",
        "i",
        "my",
        "we",
        "need",
        "want",
        "like",
        "make",
        "get",
        "use",
        "do",
        "does",
    }

    # Basic tokenization and filtering
    words = message.lower().split()
    keywords = [
        word.strip(".,!?;:\"'")
        for word in words
        if word.lower() not in stop_words and len(word) > 2
    ]

    # Take first max_keywords unique keywords
    seen = set()
    unique_keywords = []
    for keyword in keywords:
        if keyword not in seen:
            seen.add(keyword)
            unique_keywords.append(keyword)
            if len(unique_keywords) >= max_keywords:
                break

    return " ".join(unique_keywords[:max_keywords])


def query_playbook(query: str, limit: int = 5) -> Optional[Dict]:
    """Query playbook using mapify CLI.

    Args:
        query: Search query string
        limit: Maximum number of results

    Returns:
        Parsed JSON response from mapify CLI or None on error
    """
    try:
        # Call mapify playbook query with JSON output
        result = subprocess.run(
            [
                "mapify",
                "playbook",
                "query",
                query,
                "--format",
                "json",
                "--limit",
                str(limit),
            ],
            capture_output=True,
            text=True,
            timeout=10,  # 10 second timeout
        )

        if result.returncode != 0:
            print(
                f"[inject_playbook_bullets] mapify command failed: {result.stderr}",
                file=sys.stderr,
            )
            return None

        # Parse JSON output
        # Note: mapify outputs some progress to stderr, JSON to stdout
        return json.loads(result.stdout)

    except subprocess.TimeoutExpired:
        print("[inject_playbook_bullets] mapify query timed out", file=sys.stderr)
        return None
    except json.JSONDecodeError as e:
        print(f"[inject_playbook_bullets] Failed to parse JSON: {e}", file=sys.stderr)
        print(
            f"[inject_playbook_bullets] Output was: {result.stdout[:200]}",
            file=sys.stderr,
        )
        return None
    except Exception as e:
        print(f"[inject_playbook_bullets] Unexpected error: {e}", file=sys.stderr)
        return None


def format_bullets_as_markdown(results: List[Dict]) -> str:
    """Format playbook bullets as markdown for injection.

    Args:
        results: List of result dicts from mapify query

    Returns:
        Formatted markdown string
    """
    if not results:
        return ""

    lines = ["# Relevant Playbook Patterns\n"]
    lines.append(
        "*The following patterns from your project playbook may be relevant to this task:*\n"
    )

    for i, result in enumerate(results, 1):
        bullet_id = result.get("id", "unknown")
        section = result.get("section", "GENERAL")
        content = result.get("content", "")
        quality_score = result.get("quality_score", 0)
        relevance_score = result.get("relevance_score", 0)

        # Format bullet with metadata
        lines.append(f"\n## {i}. [{bullet_id}] {section}")
        lines.append(
            f"*Quality: {quality_score}/10 | Relevance: {relevance_score:.2f}*\n"
        )
        lines.append(content)

        # Include code example if available
        code_example = result.get("code_example", "")
        if code_example and code_example.strip():
            lines.append(f"\n**Example:**\n{code_example}")

        lines.append("\n---")

    return "\n".join(lines)


def main():
    """Main entry point for helper script."""
    parser = argparse.ArgumentParser(
        description="Query playbook and format bullets for Claude Code injection"
    )
    parser.add_argument(
        "--message",
        required=False,
        help="User message to analyze (deprecated: use stdin instead)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Maximum number of bullets to inject (default: 5)",
    )

    args = parser.parse_args()

    # SECURITY FIX: Support both stdin (preferred) and --message (backward compatibility)
    # Check --message first for backward compatibility with existing tests/callers
    if args.message:
        # Backward compatibility: --message argument still works
        message = args.message
        print(
            "[inject_playbook_bullets] Using --message argument (legacy mode)",
            file=sys.stderr,
        )
    elif not sys.stdin.isatty():
        # New secure approach: stdin input (preferred when no --message)
        message = sys.stdin.read().strip()
        print(
            "[inject_playbook_bullets] Reading from stdin (secure mode)",
            file=sys.stderr,
        )
    else:
        print(
            "[inject_playbook_bullets] No input provided (stdin or --message)",
            file=sys.stderr,
        )
        print(json.dumps({"continue": True}))
        return 0

    # Extract keywords from message
    keywords = extract_keywords(message)

    if not keywords:
        print(
            "[inject_playbook_bullets] No keywords extracted from message",
            file=sys.stderr,
        )
        print(json.dumps({"continue": True}))
        return 0

    print(f"[inject_playbook_bullets] Extracted keywords: {keywords}", file=sys.stderr)

    # Query playbook
    response = query_playbook(keywords, args.limit)

    if not response:
        print(
            "[inject_playbook_bullets] No response from playbook query", file=sys.stderr
        )
        print(json.dumps({"continue": True}))
        return 0

    # Check if we have results
    results = response.get("results", [])
    if not results:
        print("[inject_playbook_bullets] No relevant bullets found", file=sys.stderr)
        print(json.dumps({"continue": True}))
        return 0

    print(
        f"[inject_playbook_bullets] Found {len(results)} relevant bullets",
        file=sys.stderr,
    )

    # Format bullets as markdown
    additional_context = format_bullets_as_markdown(results)

    # Output JSON for Claude Code UserPromptSubmit hook
    # Format: {"continue": true, "additionalContext": "..."}
    if not additional_context:
        output = {"continue": True}
    else:
        output = {"continue": True, "additionalContext": additional_context}
    print(json.dumps(output, indent=2))

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"[inject_playbook_bullets] Fatal error: {e}", file=sys.stderr)
        print(json.dumps({"continue": True}))
        sys.exit(0)  # Always exit 0 to avoid blocking user prompt
