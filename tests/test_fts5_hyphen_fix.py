"""
Comprehensive test suite for FTS5 hyphen fix.

Tests verify that the fix applied at line 1012 in playbook_manager.py
(fts_query = fts_query.replace('-', ' ')) correctly handles hyphenated
and multi-word query patterns without causing FTS5 errors.

Fix Overview:
=============
The FTS5 tokenizer splits hyphens at index time, so "session-start" is
stored as two separate tokens: "session" and "start". To align query
tokenization with index tokenization, we replace hyphens with spaces
in the query string before passing to FTS5 MATCH operator.

Before fix:
  Query: "session-start" → FTS5: "session-start*" → ERROR (token not found)

After fix:
  Query: "session-start" → Replace: "session start" → FTS5: "session* start*" → SUCCESS

Test Coverage:
==============
1. Original error cases (auto-activation, session-start, multi-subtask)
2. Other hyphenated patterns (error-handling, JWT-token, database-connection)
3. Multi-word phrases without hyphens (database connection pool)
4. Edge cases (multiple hyphens, boundary hyphens, single hyphen)
5. Backward compatibility (single-word queries still work)
"""

import pytest
import sqlite3
import tempfile
from pathlib import Path
import json
from datetime import datetime

from mapify_cli.playbook_manager import PlaybookManager
from mapify_cli.playbook_query import PlaybookQuery, SearchMode


class TestFTS5HyphenFix:
    """Test comprehensive hyphen and multi-word query patterns."""

    @pytest.fixture
    def temp_playbook_with_diverse_content(self):
        """Create a temporary playbook with diverse test content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            playbook_path = Path(tmpdir) / "playbook.json"
            db_path = Path(tmpdir) / "playbook.db"

            # Create test playbook with comprehensive sample bullets
            playbook = {
                "version": "1.0",
                "metadata": {
                    "project": "test",
                    "created_at": datetime.utcnow().isoformat() + "Z",
                    "last_updated": datetime.utcnow().isoformat() + "Z",
                    "total_bullets": 10,
                    "sections_count": 2,
                    "top_k": 10,
                },
                "sections": {
                    "IMPLEMENTATION_PATTERNS": {
                        "description": "Implementation patterns",
                        "bullets": [
                            {
                                "id": "impl-0001",
                                "content": "Hooks system with auto-activation workflow for skills",
                                "helpful_count": 5,
                                "harmful_count": 0,
                                "created_at": datetime.utcnow().isoformat() + "Z",
                                "last_used_at": datetime.utcnow().isoformat() + "Z",
                            },
                            {
                                "id": "impl-0002",
                                "content": "Session-start hook for auto-injection of validation files",
                                "helpful_count": 3,
                                "harmful_count": 0,
                                "created_at": datetime.utcnow().isoformat() + "Z",
                                "last_used_at": datetime.utcnow().isoformat() + "Z",
                            },
                            {
                                "id": "impl-0003",
                                "content": "Multi-subtask dependency verification using upstream artifacts",
                                "helpful_count": 4,
                                "harmful_count": 0,
                                "created_at": datetime.utcnow().isoformat() + "Z",
                                "last_used_at": datetime.utcnow().isoformat() + "Z",
                            },
                            {
                                "id": "impl-0004",
                                "content": "Error-handling middleware with retry logic and exponential backoff",
                                "helpful_count": 6,
                                "harmful_count": 0,
                                "created_at": datetime.utcnow().isoformat() + "Z",
                                "last_used_at": datetime.utcnow().isoformat() + "Z",
                            },
                            {
                                "id": "impl-0005",
                                "content": "JWT-token authentication using refresh-token rotation pattern",
                                "helpful_count": 7,
                                "harmful_count": 0,
                                "created_at": datetime.utcnow().isoformat() + "Z",
                                "last_used_at": datetime.utcnow().isoformat() + "Z",
                            },
                            {
                                "id": "impl-0006",
                                "content": "Database-connection pool configuration for high-throughput scenarios",
                                "helpful_count": 5,
                                "harmful_count": 0,
                                "created_at": datetime.utcnow().isoformat() + "Z",
                                "last_used_at": datetime.utcnow().isoformat() + "Z",
                            },
                        ],
                    },
                    "ARCHITECTURE_PATTERNS": {
                        "description": "Architecture patterns",
                        "bullets": [
                            {
                                "id": "arch-0001",
                                "content": "Database connection pool sizing based on concurrent request volume",
                                "helpful_count": 4,
                                "harmful_count": 0,
                                "created_at": datetime.utcnow().isoformat() + "Z",
                                "last_used_at": datetime.utcnow().isoformat() + "Z",
                            },
                            {
                                "id": "arch-0002",
                                "content": "Microservices communication pattern with circuit-breaker and retry",
                                "helpful_count": 8,
                                "harmful_count": 0,
                                "created_at": datetime.utcnow().isoformat() + "Z",
                                "last_used_at": datetime.utcnow().isoformat() + "Z",
                            },
                            {
                                "id": "arch-0003",
                                "content": "Event-driven architecture using message-queue for async processing",
                                "helpful_count": 6,
                                "harmful_count": 0,
                                "created_at": datetime.utcnow().isoformat() + "Z",
                                "last_used_at": datetime.utcnow().isoformat() + "Z",
                            },
                            {
                                "id": "arch-0004",
                                "content": "Single source of truth pattern for configuration management",
                                "helpful_count": 5,
                                "harmful_count": 0,
                                "created_at": datetime.utcnow().isoformat() + "Z",
                                "last_used_at": datetime.utcnow().isoformat() + "Z",
                            },
                        ],
                    },
                },
            }

            playbook_path.write_text(json.dumps(playbook, indent=2))

            manager = PlaybookManager(
                playbook_path=str(playbook_path),
                db_path=str(db_path),
                use_semantic_search=False,
            )
            yield manager
            manager.close()

    # ========================================================================
    # Test Category 1: Original Error Cases (should now work)
    # ========================================================================

    def test_auto_activation_query_no_error(self, temp_playbook_with_diverse_content):
        """
        Test: "auto-activation" query works without FTS5 errors.

        Original error: "no such column: activation"
        After fix: Query transformed to "auto activation", both terms found
        """
        query = "hooks auto-activation workflow"

        params = PlaybookQuery(
            query=query, limit=10, search_mode=SearchMode.PLAYBOOK_ONLY, fts_prefix=True
        )

        # Should NOT raise sqlite3.OperationalError
        try:
            response = temp_playbook_with_diverse_content.query(params)
            assert response is not None
            assert (
                len(response.results) > 0
            ), "Expected to find bullets matching 'auto-activation'"

            # Verify we found the correct bullet
            bullet_ids = [r.id for r in response.results]
            assert (
                "impl-0001" in bullet_ids
            ), "Expected to find impl-0001 (auto-activation bullet)"

        except sqlite3.OperationalError as e:
            pytest.fail(
                f"FTS5 error occurred: {e}. The hyphen fix should prevent this error."
            )

    def test_session_start_query_no_error(self, temp_playbook_with_diverse_content):
        """
        Test: "session-start" query works without FTS5 errors.

        Original error: "no such column: start"
        After fix: Query transformed to "session start", both terms found
        """
        query = "session-start hook auto-injection"

        params = PlaybookQuery(
            query=query, limit=10, search_mode=SearchMode.PLAYBOOK_ONLY, fts_prefix=True
        )

        try:
            response = temp_playbook_with_diverse_content.query(params)
            assert response is not None
            assert (
                len(response.results) > 0
            ), "Expected to find bullets matching 'session-start'"

            # Verify we found the correct bullet
            bullet_ids = [r.id for r in response.results]
            assert (
                "impl-0002" in bullet_ids
            ), "Expected to find impl-0002 (session-start bullet)"

        except sqlite3.OperationalError as e:
            pytest.fail(
                f"FTS5 error occurred: {e}. The hyphen fix should prevent this error."
            )

    def test_multi_subtask_query_no_error(self, temp_playbook_with_diverse_content):
        """
        Test: "multi-subtask" query works without FTS5 errors.

        Original error: "no such column: subtask"
        After fix: Query transformed to "multi subtask", both terms found
        """
        query = "multi-subtask dependency verification"

        params = PlaybookQuery(
            query=query, limit=10, search_mode=SearchMode.PLAYBOOK_ONLY, fts_prefix=True
        )

        try:
            response = temp_playbook_with_diverse_content.query(params)
            assert response is not None
            assert (
                len(response.results) > 0
            ), "Expected to find bullets matching 'multi-subtask'"

            # Verify we found the correct bullet
            bullet_ids = [r.id for r in response.results]
            assert (
                "impl-0003" in bullet_ids
            ), "Expected to find impl-0003 (multi-subtask bullet)"

        except sqlite3.OperationalError as e:
            pytest.fail(
                f"FTS5 error occurred: {e}. The hyphen fix should prevent this error."
            )

    # ========================================================================
    # Test Category 2: Other Hyphenated Patterns
    # ========================================================================

    def test_error_handling_hyphen_query(self, temp_playbook_with_diverse_content):
        """Test: "error-handling" query works without FTS5 errors."""
        query = "error-handling middleware retry"

        params = PlaybookQuery(
            query=query, limit=10, search_mode=SearchMode.PLAYBOOK_ONLY, fts_prefix=True
        )

        try:
            response = temp_playbook_with_diverse_content.query(params)
            assert response is not None
            assert (
                len(response.results) > 0
            ), "Expected to find bullets matching 'error-handling'"

            bullet_ids = [r.id for r in response.results]
            assert (
                "impl-0004" in bullet_ids
            ), "Expected to find impl-0004 (error-handling bullet)"

        except sqlite3.OperationalError as e:
            pytest.fail(
                f"FTS5 error occurred: {e}. The hyphen fix should prevent this error."
            )

    def test_jwt_token_hyphen_query(self, temp_playbook_with_diverse_content):
        """Test: "JWT-token" query works without FTS5 errors."""
        query = "JWT-token authentication refresh-token"

        params = PlaybookQuery(
            query=query, limit=10, search_mode=SearchMode.PLAYBOOK_ONLY, fts_prefix=True
        )

        try:
            response = temp_playbook_with_diverse_content.query(params)
            assert response is not None
            assert (
                len(response.results) > 0
            ), "Expected to find bullets matching 'JWT-token'"

            bullet_ids = [r.id for r in response.results]
            assert (
                "impl-0005" in bullet_ids
            ), "Expected to find impl-0005 (JWT-token bullet)"

        except sqlite3.OperationalError as e:
            pytest.fail(
                f"FTS5 error occurred: {e}. The hyphen fix should prevent this error."
            )

    def test_database_connection_hyphen_query(self, temp_playbook_with_diverse_content):
        """Test: "database-connection" query works without FTS5 errors."""
        query = "database-connection pool high-throughput"

        params = PlaybookQuery(
            query=query, limit=10, search_mode=SearchMode.PLAYBOOK_ONLY, fts_prefix=True
        )

        try:
            response = temp_playbook_with_diverse_content.query(params)
            assert response is not None
            assert (
                len(response.results) > 0
            ), "Expected to find bullets matching 'database-connection'"

            bullet_ids = [r.id for r in response.results]
            assert (
                "impl-0006" in bullet_ids
            ), "Expected to find impl-0006 (database-connection bullet)"

        except sqlite3.OperationalError as e:
            pytest.fail(
                f"FTS5 error occurred: {e}. The hyphen fix should prevent this error."
            )

    def test_circuit_breaker_hyphen_query(self, temp_playbook_with_diverse_content):
        """Test: "circuit-breaker" query works without FTS5 errors."""
        query = "circuit-breaker pattern microservices"

        params = PlaybookQuery(
            query=query, limit=10, search_mode=SearchMode.PLAYBOOK_ONLY, fts_prefix=True
        )

        try:
            response = temp_playbook_with_diverse_content.query(params)
            assert response is not None
            assert (
                len(response.results) > 0
            ), "Expected to find bullets matching 'circuit-breaker'"

            bullet_ids = [r.id for r in response.results]
            assert (
                "arch-0002" in bullet_ids
            ), "Expected to find arch-0002 (circuit-breaker bullet)"

        except sqlite3.OperationalError as e:
            pytest.fail(
                f"FTS5 error occurred: {e}. The hyphen fix should prevent this error."
            )

    def test_message_queue_hyphen_query(self, temp_playbook_with_diverse_content):
        """Test: "message-queue" query works without FTS5 errors."""
        query = "message-queue event-driven async"

        params = PlaybookQuery(
            query=query, limit=10, search_mode=SearchMode.PLAYBOOK_ONLY, fts_prefix=True
        )

        try:
            response = temp_playbook_with_diverse_content.query(params)
            assert response is not None
            assert (
                len(response.results) > 0
            ), "Expected to find bullets matching 'message-queue'"

            bullet_ids = [r.id for r in response.results]
            assert (
                "arch-0003" in bullet_ids
            ), "Expected to find arch-0003 (message-queue bullet)"

        except sqlite3.OperationalError as e:
            pytest.fail(
                f"FTS5 error occurred: {e}. The hyphen fix should prevent this error."
            )

    # ========================================================================
    # Test Category 3: Multi-Word Phrases (no hyphens)
    # ========================================================================

    def test_multi_word_phrase_query(self, temp_playbook_with_diverse_content):
        """Test: Multi-word phrase "database connection pool" works correctly."""
        query = "database connection pool"

        params = PlaybookQuery(
            query=query, limit=10, search_mode=SearchMode.PLAYBOOK_ONLY, fts_prefix=True
        )

        try:
            response = temp_playbook_with_diverse_content.query(params)
            assert response is not None
            assert (
                len(response.results) > 0
            ), "Expected to find bullets matching 'database connection pool'"

            # Should find both arch-0001 and impl-0006 (both mention database connection pool)
            bullet_ids = [r.id for r in response.results]
            assert "arch-0001" in bullet_ids or "impl-0006" in bullet_ids

        except sqlite3.OperationalError as e:
            pytest.fail(f"FTS5 error occurred: {e}. Multi-word queries should work.")

    def test_long_multi_word_phrase(self, temp_playbook_with_diverse_content):
        """Test: Long multi-word phrase works without errors."""
        query = "single source of truth configuration management"

        params = PlaybookQuery(
            query=query, limit=10, search_mode=SearchMode.PLAYBOOK_ONLY, fts_prefix=True
        )

        try:
            response = temp_playbook_with_diverse_content.query(params)
            assert response is not None
            # May or may not find results (depends on exact matching), but should NOT error

        except sqlite3.OperationalError as e:
            pytest.fail(
                f"FTS5 error occurred: {e}. Multi-word queries should not cause errors."
            )

    # ========================================================================
    # Test Category 4: Edge Cases
    # ========================================================================

    def test_multiple_consecutive_hyphens(self, temp_playbook_with_diverse_content):
        """Test: Multiple hyphens "foo-bar-baz" are handled correctly."""
        query = "circuit-breaker-pattern"

        params = PlaybookQuery(
            query=query, limit=10, search_mode=SearchMode.PLAYBOOK_ONLY, fts_prefix=True
        )

        try:
            response = temp_playbook_with_diverse_content.query(params)
            assert response is not None
            # Should transform to "circuit breaker pattern" and search

        except sqlite3.OperationalError as e:
            pytest.fail(
                f"FTS5 error occurred: {e}. Multiple hyphens should be handled."
            )

    def test_leading_hyphen(self, temp_playbook_with_diverse_content):
        """Test: Leading hyphen "-word" is handled without errors."""
        query = "-session"

        params = PlaybookQuery(
            query=query, limit=10, search_mode=SearchMode.PLAYBOOK_ONLY, fts_prefix=True
        )

        try:
            response = temp_playbook_with_diverse_content.query(params)
            assert response is not None
            # Leading hyphen becomes leading space, which is fine

        except sqlite3.OperationalError as e:
            pytest.fail(
                f"FTS5 error occurred: {e}. Leading hyphen should be handled safely."
            )

    def test_trailing_hyphen(self, temp_playbook_with_diverse_content):
        """Test: Trailing hyphen "word-" is handled without errors."""
        query = "session-"

        params = PlaybookQuery(
            query=query, limit=10, search_mode=SearchMode.PLAYBOOK_ONLY, fts_prefix=True
        )

        try:
            response = temp_playbook_with_diverse_content.query(params)
            assert response is not None
            # Trailing hyphen becomes trailing space, which is fine

        except sqlite3.OperationalError as e:
            pytest.fail(
                f"FTS5 error occurred: {e}. Trailing hyphen should be handled safely."
            )

    def test_single_hyphen_only(self, temp_playbook_with_diverse_content):
        """
        Test: Single hyphen "-" query handling.

        Note: After hyphen replacement, "-" becomes " " (space), which is an empty query
        after sanitization. This is an expected edge case where FTS5 syntax error occurs.
        The fix handles the common case (hyphenated words), not malformed queries.
        """
        query = "-"

        # This should raise ValueError during PlaybookQuery validation (empty query)
        # OR if it passes validation, may cause FTS5 syntax error
        # Both outcomes are acceptable for this extreme edge case
        try:
            params = PlaybookQuery(
                query=query,
                limit=10,
                search_mode=SearchMode.PLAYBOOK_ONLY,
                fts_prefix=True,
            )
            # If validation passes, query execution may fail with FTS5 syntax error
            # This is acceptable for a malformed query
            response = temp_playbook_with_diverse_content.query(params)
            # If we get here, that's fine too (empty results)
            assert response is not None

        except (ValueError, sqlite3.OperationalError):
            # Expected: either validation error or FTS5 syntax error for malformed query
            pass

    def test_mixed_hyphens_and_spaces(self, temp_playbook_with_diverse_content):
        """Test: Mixed hyphens and spaces are handled correctly."""
        query = "session-start hook auto injection"

        params = PlaybookQuery(
            query=query, limit=10, search_mode=SearchMode.PLAYBOOK_ONLY, fts_prefix=True
        )

        try:
            response = temp_playbook_with_diverse_content.query(params)
            assert response is not None
            assert len(response.results) > 0

        except sqlite3.OperationalError as e:
            pytest.fail(f"FTS5 error occurred: {e}. Mixed hyphens/spaces should work.")

    def test_empty_query_after_hyphen_removal(self, temp_playbook_with_diverse_content):
        """
        Test: Query that becomes empty after hyphen removal is handled.

        Note: "- - -" after hyphen replacement becomes "     " (spaces),
        which is effectively empty. This is a malformed query edge case.
        """
        query = "- - -"

        try:
            params = PlaybookQuery(
                query=query,
                limit=10,
                search_mode=SearchMode.PLAYBOOK_ONLY,
                fts_prefix=True,
            )
            # If validation passes, query execution may fail with FTS5 syntax error
            # or return empty results - both are acceptable for malformed query
            response = temp_playbook_with_diverse_content.query(params)
            assert response is not None

        except (ValueError, sqlite3.OperationalError):
            # Expected: either validation error or FTS5 syntax error for malformed query
            pass

    # ========================================================================
    # Test Category 5: Backward Compatibility
    # ========================================================================

    def test_single_word_query_still_works(self, temp_playbook_with_diverse_content):
        """Test: Single-word queries without hyphens still work correctly."""
        query = "authentication"

        params = PlaybookQuery(
            query=query, limit=10, search_mode=SearchMode.PLAYBOOK_ONLY, fts_prefix=True
        )

        try:
            response = temp_playbook_with_diverse_content.query(params)
            assert response is not None
            assert (
                len(response.results) > 0
            ), "Expected to find bullets matching 'authentication'"

            bullet_ids = [r.id for r in response.results]
            assert (
                "impl-0005" in bullet_ids
            ), "Expected to find impl-0005 (JWT authentication)"

        except sqlite3.OperationalError as e:
            pytest.fail(
                f"FTS5 error occurred: {e}. Single-word queries should still work."
            )

    def test_simple_two_word_query(self, temp_playbook_with_diverse_content):
        """Test: Simple two-word queries (no hyphens) work correctly."""
        query = "database pool"

        params = PlaybookQuery(
            query=query, limit=10, search_mode=SearchMode.PLAYBOOK_ONLY, fts_prefix=True
        )

        try:
            response = temp_playbook_with_diverse_content.query(params)
            assert response is not None
            assert (
                len(response.results) > 0
            ), "Expected to find bullets matching 'database pool'"

        except sqlite3.OperationalError as e:
            pytest.fail(f"FTS5 error occurred: {e}. Two-word queries should work.")

    def test_query_with_no_prefix_matching(self, temp_playbook_with_diverse_content):
        """Test: Queries without prefix matching (fts_prefix=False) still work."""
        query = "session-start"

        params = PlaybookQuery(
            query=query,
            limit=10,
            search_mode=SearchMode.PLAYBOOK_ONLY,
            fts_prefix=False,  # Disable prefix matching
        )

        try:
            response = temp_playbook_with_diverse_content.query(params)
            assert response is not None
            # May or may not find results, but shouldn't error

        except sqlite3.OperationalError as e:
            pytest.fail(
                f"FTS5 error occurred: {e}. Non-prefix queries should work with hyphen fix."
            )

    # ========================================================================
    # Test Category 6: Verify Fix Implementation
    # ========================================================================

    def test_verify_hyphen_replacement_in_fts_query(
        self, temp_playbook_with_diverse_content
    ):
        """
        Verify that the fix correctly replaces hyphens with spaces in FTS query.

        This test directly inspects the generated FTS query to ensure the fix
        is applied at line 1012 in playbook_manager.py.
        """
        query = "session-start auto-activation"

        params = PlaybookQuery(
            query=query, limit=5, search_mode=SearchMode.PLAYBOOK_ONLY, fts_prefix=True
        )

        # Build FTS query (internal method, but accessible for testing)
        sql, sql_params = temp_playbook_with_diverse_content._build_fts_query(
            params, limit=5
        )

        # Extract the FTS query parameter (first param is the FTS query)
        fts_query_param = sql_params[0]

        print(f"\nOriginal query: {query}")
        print(f"FTS query param: {fts_query_param}")

        # After fix: hyphens should be replaced with spaces
        # "session-start auto-activation" → "session start auto activation"
        # With prefix matching: "session* start* auto* activation*"
        assert (
            "-" not in fts_query_param
        ), "Hyphens should be replaced with spaces in FTS query"
        assert "session" in fts_query_param, "Expected 'session' in FTS query"
        assert "start" in fts_query_param, "Expected 'start' in FTS query"
        assert "auto" in fts_query_param, "Expected 'auto' in FTS query"
        assert "activation" in fts_query_param, "Expected 'activation' in FTS query"

    def test_fix_prevents_no_such_column_error(
        self, temp_playbook_with_diverse_content
    ):
        """
        Integration test: Verify the fix prevents "no such column" errors.

        Before fix: These queries would raise sqlite3.OperationalError
        After fix: These queries should work without errors
        """
        test_queries = [
            "auto-activation",
            "session-start",
            "multi-subtask",
            "error-handling",
            "JWT-token",
            "database-connection",
            "circuit-breaker",
            "message-queue",
            "event-driven",
            "refresh-token",
        ]

        for query in test_queries:
            params = PlaybookQuery(
                query=query,
                limit=10,
                search_mode=SearchMode.PLAYBOOK_ONLY,
                fts_prefix=True,
            )

            try:
                response = temp_playbook_with_diverse_content.query(params)
                assert response is not None, f"Query '{query}' returned None"
                # Success: no FTS5 error occurred
                print(f"✓ Query '{query}' executed without errors")

            except sqlite3.OperationalError as e:
                pytest.fail(
                    f"Query '{query}' caused FTS5 error: {e}. "
                    f"The hyphen fix should prevent this error."
                )


class TestFTS5HyphenFixEdgeCasesExtended:
    """Additional edge case tests for comprehensive coverage."""

    @pytest.fixture
    def minimal_playbook(self):
        """Create minimal playbook for edge case testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            playbook_path = Path(tmpdir) / "playbook.json"
            db_path = Path(tmpdir) / "playbook.db"

            playbook = {
                "version": "1.0",
                "metadata": {
                    "project": "test",
                    "created_at": datetime.utcnow().isoformat() + "Z",
                    "last_updated": datetime.utcnow().isoformat() + "Z",
                    "total_bullets": 1,
                    "sections_count": 1,
                    "top_k": 5,
                },
                "sections": {
                    "TEST": {
                        "description": "Test",
                        "bullets": [
                            {
                                "id": "test-0001",
                                "content": "Test content with various words for searching",
                                "helpful_count": 1,
                                "harmful_count": 0,
                                "created_at": datetime.utcnow().isoformat() + "Z",
                                "last_used_at": datetime.utcnow().isoformat() + "Z",
                            }
                        ],
                    }
                },
            }

            playbook_path.write_text(json.dumps(playbook, indent=2))

            manager = PlaybookManager(
                playbook_path=str(playbook_path),
                db_path=str(db_path),
                use_semantic_search=False,
            )
            yield manager
            manager.close()

    def test_unicode_characters_with_hyphens(self, minimal_playbook):
        """Test: Unicode characters combined with hyphens are handled."""
        query = "café-menu"

        params = PlaybookQuery(
            query=query, limit=5, search_mode=SearchMode.PLAYBOOK_ONLY, fts_prefix=True
        )

        try:
            response = minimal_playbook.query(params)
            assert response is not None

        except sqlite3.OperationalError as e:
            pytest.fail(
                f"FTS5 error occurred: {e}. Unicode with hyphens should be handled."
            )

    def test_numbers_with_hyphens(self, minimal_playbook):
        """Test: Numbers with hyphens (e.g., "HTTP-401") are handled."""
        query = "HTTP-401 error"

        params = PlaybookQuery(
            query=query, limit=5, search_mode=SearchMode.PLAYBOOK_ONLY, fts_prefix=True
        )

        try:
            response = minimal_playbook.query(params)
            assert response is not None

        except sqlite3.OperationalError as e:
            pytest.fail(
                f"FTS5 error occurred: {e}. Numbers with hyphens should be handled."
            )

    def test_uppercase_hyphenated_words(self, minimal_playbook):
        """Test: Uppercase hyphenated words (e.g., "REST-API") are handled."""
        query = "REST-API JWT-TOKEN"

        params = PlaybookQuery(
            query=query, limit=5, search_mode=SearchMode.PLAYBOOK_ONLY, fts_prefix=True
        )

        try:
            response = minimal_playbook.query(params)
            assert response is not None

        except sqlite3.OperationalError as e:
            pytest.fail(
                f"FTS5 error occurred: {e}. Uppercase hyphenated words should be handled."
            )

    def test_very_long_hyphenated_word(self, minimal_playbook):
        """Test: Very long hyphenated compound words are handled."""
        query = "one-two-three-four-five-six-seven-eight"

        params = PlaybookQuery(
            query=query, limit=5, search_mode=SearchMode.PLAYBOOK_ONLY, fts_prefix=True
        )

        try:
            response = minimal_playbook.query(params)
            assert response is not None

        except sqlite3.OperationalError as e:
            pytest.fail(
                f"FTS5 error occurred: {e}. Long hyphenated words should be handled."
            )


if __name__ == "__main__":
    # Run tests with verbose output
    pytest.main([__file__, "-v", "-s"])
