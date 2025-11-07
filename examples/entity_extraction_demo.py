#!/usr/bin/env python3
"""
Entity Extraction Demo

Demonstrates the entity_extractor module capabilities with real-world examples.
"""

from mapify_cli.entity_extractor import extract_entities, EntityType


def print_entities(text: str, title: str):
    """Extract and print entities from text."""
    print(f"\n{'='*80}")
    print(f"{title}")
    print(f"{'='*80}")
    print(f"\nInput text:\n{text}\n")

    entities = extract_entities(text)

    if not entities:
        print("No entities extracted.")
        return

    print(f"Extracted {len(entities)} entities:\n")

    # Group by type
    by_type = {}
    for entity in entities:
        if entity.type not in by_type:
            by_type[entity.type] = []
        by_type[entity.type].append(entity)

    # Print grouped
    for entity_type in EntityType:
        if entity_type in by_type:
            print(f"\n{entity_type.value}:")
            for entity in sorted(
                by_type[entity_type], key=lambda e: e.confidence, reverse=True
            ):
                print(
                    f"  - {entity.name:30} (confidence: {entity.confidence:.2f}, id: {entity.id})"
                )


def main():
    """Run entity extraction demonstrations."""

    # Example 1: Testing playbook bullet
    print_entities(
        text="""
        Use `pytest` for testing with comprehensive coverage.
        Implement retry pattern with exponential backoff for API calls.
        Never use generic-exception handlers - be specific.
        """,
        title="Example 1: Testing Best Practices",
    )

    # Example 2: Architecture discussion
    print_entities(
        text="""
        Built microservices architecture using Python and FastAPI.
        Deploy to Kubernetes with CI/CD pipeline via GitHub Actions.
        Use circuit-breaker pattern to prevent cascading failures.
        Ensure idempotency for all API endpoints.
        """,
        title="Example 2: Architecture Description",
    )

    # Example 3: Error handling discussion
    print_entities(
        text="""
        Fixed race-condition causing deadlock in payment processing.
        Resolved memory-leak in event processing loop.
        Added proper null-pointer exception handling.
        Implemented mutex-lock to prevent concurrent access issues.
        """,
        title="Example 3: Bug Fixes and Error Handling",
    )

    # Example 4: Code snippet with imports
    print_entities(
        text="""
        ```python
        import pytest
        from flask import Flask, request
        from sqlalchemy import create_engine

        def test_api_endpoint():
            # Test with retry logic
            pass
        ```
        """,
        title="Example 4: Code Snippet with Imports",
    )

    # Example 5: Workflow and antipatterns
    print_entities(
        text="""
        Follow TDD methodology with code-review process.
        Use map-feature workflow for new implementations.
        Avoid magic-number antipattern and hardcoded values.
        Never use silent-failure patterns - log errors explicitly.
        """,
        title="Example 5: Workflows and Antipatterns",
    )

    # Example 6: Mixed content
    print_entities(
        text="""
        Migrate from JSON-storage to `SQLite` with FTS5 for better search.
        Implement feature-flag pattern for gradual rollout.
        Use eventual-consistency model for distributed cache.
        Deploy with blue-green deployment strategy to minimize downtime.
        Handle timeout-error gracefully with fallback to cached data.
        """,
        title="Example 6: Migration and Deployment Strategy",
    )

    print("\n" + "=" * 80)
    print("Demo complete!")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
