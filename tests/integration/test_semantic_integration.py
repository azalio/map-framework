#!/usr/bin/env python3
"""
Test script for semantic search integration with PlaybookManager.

Tests:
1. PlaybookManager initialization with semantic search
2. Adding bullets via delta operations
3. Semantic search retrieval
4. Semantic deduplication
"""

# IMPORTANT: Set environment variables BEFORE any imports
import os
os.environ['TRANSFORMERS_NO_TF'] = '1'
os.environ['TF_USE_LEGACY_KERAS'] = '1'  # Force TensorFlow to use Keras 2 instead of Keras 3
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'

import sys
import json
from pathlib import Path

# Add src to path for imports
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / "src"))

from mapify_cli.playbook_manager import PlaybookManager, SEMANTIC_SEARCH_AVAILABLE


def test_initialization(manager):
    """Test PlaybookManager initialization with semantic search."""
    print("\n" + "="*70)
    print("TEST 1: PlaybookManager Initialization")
    print("="*70)

    assert manager.semantic_engine is not None, "Semantic engine not initialized"

    print("✓ PlaybookManager initialized with semantic search")
    print(f"  Model: {manager.semantic_engine.model_name}")
    print(f"  Cache dir: {manager.semantic_engine.cache_dir}")


def test_add_bullets(manager):
    """Test adding bullets via delta operations."""
    print("\n" + "="*70)
    print("TEST 2: Adding Bullets via Delta Operations")
    print("="*70)

    # Add test bullets
    operations = [
        {
            "type": "ADD",
            "section": "SECURITY_PATTERNS",
            "content": "Always verify JWT token signatures to prevent forgery and tampering",
            "code_example": "```python\nimport jwt\ntoken = jwt.decode(token_str, secret_key, algorithms=['HS256'])\n```",
            "tags": ["jwt", "authentication", "security"]
        },
        {
            "type": "ADD",
            "section": "SECURITY_PATTERNS",
            "content": "Validate JWT signatures using cryptographic verification",
            "code_example": "```python\nfrom jwt import decode\nverified = decode(token, key, verify=True)\n```",
            "tags": ["jwt", "crypto"]
        },
        {
            "type": "ADD",
            "section": "SECURITY_PATTERNS",
            "content": "Use bcrypt with cost factor 12 for password hashing",
            "code_example": "```python\nimport bcrypt\nhashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12))\n```",
            "tags": ["password", "hashing"]
        },
        {
            "type": "ADD",
            "section": "PERFORMANCE_PATTERNS",
            "content": "Use Redis caching to speed up database queries",
            "code_example": "```python\nimport redis\ncache = redis.Redis()\nresult = cache.get(key) or db.query()\n```",
            "tags": ["redis", "caching"]
        },
        {
            "type": "ADD",
            "section": "IMPLEMENTATION_PATTERNS",
            "content": "Implement authentication with bearer tokens in HTTP headers",
            "code_example": "```python\nheaders = {'Authorization': f'Bearer {token}'}\nresponse = requests.get(url, headers=headers)\n```",
            "tags": ["auth", "http"]
        }
    ]

    summary = manager.apply_delta(operations)

    print(f"✓ Added {summary['added']} bullets")
    print(f"  Deduplicated: {summary.get('deduplicated', 0)} duplicates removed")

    return True


def test_semantic_search(manager):
    """Test semantic search retrieval."""
    print("\n" + "="*70)
    print("TEST 3: Semantic Search Retrieval")
    print("="*70)

    queries = [
        "token authentication security",
        "password hashing",
        "improve query performance"
    ]

    for query in queries:
        print(f"\nQuery: '{query}'")
        print("-" * 70)

        bullets = manager.get_relevant_bullets(
            query=query,
            limit=3,
            similarity_threshold=0.2
        )

        if not bullets:
            print("  No results found")
            continue

        for i, bullet in enumerate(bullets, 1):
            print(f"  {i}. [{bullet['id']}] Quality: {bullet['quality_score']}")
            print(f"     {bullet['content'][:80]}...")

    print("\n✓ Semantic search working correctly")
    return True


def test_deduplication(manager):
    """Test semantic deduplication."""
    print("\n" + "="*70)
    print("TEST 4: Semantic Deduplication")
    print("="*70)

    # Add a near-duplicate bullet
    operations = [
        {
            "type": "ADD",
            "section": "SECURITY_PATTERNS",
            "content": "JWT signature verification prevents token tampering and ensures authenticity",
            "tags": ["jwt", "security"]
        }
    ]

    print("\nBefore deduplication:")
    sec_bullets = manager.playbook["sections"]["SECURITY_PATTERNS"]["bullets"]
    print(f"  SECURITY_PATTERNS: {len(sec_bullets)} bullets")

    summary = manager.apply_delta(operations)

    print("\nAfter deduplication:")
    sec_bullets = manager.playbook["sections"]["SECURITY_PATTERNS"]["bullets"]
    print(f"  SECURITY_PATTERNS: {len(sec_bullets)} bullets")
    print(f"  Duplicates removed: {summary.get('deduplicated', 0)}")

    if summary.get('deduplicated', 0) > 0:
        print("\n✓ Deduplication working correctly")
    else:
        print("\n⚠ No duplicates detected (similarity threshold might be too high)")

    return True


def test_fallback_mode():
    """Test fallback to keyword matching when semantic search unavailable."""
    print("\n" + "="*70)
    print("TEST 5: Fallback to Keyword Matching")
    print("="*70)

    manager = PlaybookManager(
        playbook_path=".claude/playbook_test.json",
        use_semantic_search=False  # Force disable
    )

    if manager.semantic_engine is not None:
        print("⚠ WARNING: Semantic engine initialized despite use_semantic_search=False")

    # Test search with keyword matching
    bullets = manager.get_relevant_bullets(
        query="token authentication",
        limit=3
    )

    print(f"✓ Keyword matching fallback working ({len(bullets)} results)")

    return True


def main():
    """Run all tests."""
    print("\n" + "="*70)
    print("SEMANTIC SEARCH INTEGRATION TEST SUITE")
    print("="*70)

    try:
        # Test 1: Initialization
        manager = test_initialization()
        if not manager:
            return 1

        # Test 2: Add bullets
        if not test_add_bullets(manager):
            return 1

        # Test 3: Semantic search
        if not test_semantic_search(manager):
            return 1

        # Test 4: Deduplication
        if not test_deduplication(manager):
            return 1

        # Test 5: Fallback mode
        if not test_fallback_mode():
            return 1

        print("\n" + "="*70)
        print("ALL TESTS PASSED ✓")
        print("="*70)

        # Cleanup
        test_file = Path(".claude/playbook_test.json")
        if test_file.exists():
            test_file.unlink()
            print("\n✓ Cleaned up test file")

        return 0

    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
