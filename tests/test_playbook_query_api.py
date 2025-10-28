"""
Unit tests for Playbook Query API - FTS5 implementation

Tests the new query() method with PlaybookQuery dataclasses,
FTS5 full-text search, and backward compatibility.
"""

import json
import pytest
from pathlib import Path
from mapify_cli.playbook_manager import PlaybookManager
from mapify_cli.playbook_query import (
    PlaybookQuery,
    PlaybookResult,
    PlaybookQueryResponse,
    SearchMode,
    VALID_SECTIONS
)


@pytest.fixture
def temp_playbook(tmp_path):
    """Create a temporary playbook directory"""
    playbook_dir = tmp_path / ".claude"
    playbook_dir.mkdir()
    return playbook_dir / "playbook.json"


@pytest.fixture
def manager_with_bullets(temp_playbook):
    """Create PlaybookManager with test bullets"""
    manager = PlaybookManager(playbook_path=str(temp_playbook), use_semantic_search=False)

    # Add test bullets for JWT authentication
    manager._add_bullet(
        section="SECURITY_PATTERNS",
        content="Always set JWT exp claim for token expiration",
        code_example="jwt.encode({'exp': datetime.utcnow() + timedelta(hours=1)})",
        tags=["security", "jwt", "authentication"]
    )

    manager._add_bullet(
        section="SECURITY_PATTERNS",
        content="Use httpOnly cookies for refresh token storage",
        tags=["security", "cookies", "authentication"]
    )

    manager._add_bullet(
        section="IMPLEMENTATION_PATTERNS",
        content="Implement JWT token validation middleware",
        code_example="@app.middleware('http')\nasync def validate_jwt(request, call_next): ...",
        tags=["jwt", "middleware"]
    )

    # Add bullets for database optimization
    manager._add_bullet(
        section="PERFORMANCE_PATTERNS",
        content="Add indexes to frequently queried columns",
        code_example="CREATE INDEX idx_user_email ON users(email);",
        tags=["database", "performance", "optimization"]
    )

    manager._add_bullet(
        section="DEBUGGING_TECHNIQUES",
        content="Use EXPLAIN ANALYZE to profile database queries",
        tags=["database", "debugging"]
    )

    # Add a deprecated bullet
    deprecated_id = manager._add_bullet(
        section="ERROR_PATTERNS",
        content="Old authentication pattern (deprecated)",
        tags=["authentication"]
    )
    manager._deprecate_bullet(deprecated_id, "Replaced by JWT")

    # Add high quality bullet
    high_quality_id = manager._add_bullet(
        section="TESTING_STRATEGIES",
        content="Always test authentication flows with invalid tokens",
        tags=["testing", "authentication"]
    )
    manager._update_bullet(high_quality_id, increment_helpful=5)

    return manager


class TestPlaybookQueryDataclass:
    """Test PlaybookQuery dataclass validation"""

    def test_valid_query_creation(self):
        """Valid query should be created without errors"""
        query = PlaybookQuery(
            query="JWT authentication",
            sections=["SECURITY_PATTERNS"],
            min_quality_score=0,
            limit=5
        )

        assert query.query == "JWT authentication"
        assert query.sections == ["SECURITY_PATTERNS"]
        assert query.min_quality_score == 0
        assert query.limit == 5

    def test_empty_query_raises_error(self):
        """Empty query string should raise ValueError"""
        with pytest.raises(ValueError, match="Query string cannot be empty"):
            PlaybookQuery(query="")

        with pytest.raises(ValueError, match="Query string cannot be empty"):
            PlaybookQuery(query="   ")

    def test_long_query_raises_error(self):
        """Query >1000 chars should raise ValueError"""
        long_query = "a" * 1001
        with pytest.raises(ValueError, match="Query string too long"):
            PlaybookQuery(query=long_query)

    def test_invalid_sections_raise_error(self):
        """Invalid section names should raise ValueError"""
        with pytest.raises(ValueError, match="Invalid sections"):
            PlaybookQuery(
                query="test",
                sections=["INVALID_SECTION", "ANOTHER_INVALID"]
            )

    def test_valid_sections_accepted(self):
        """Valid section names should be accepted"""
        query = PlaybookQuery(
            query="test",
            sections=["SECURITY_PATTERNS", "IMPLEMENTATION_PATTERNS"]
        )
        assert query.sections == ["SECURITY_PATTERNS", "IMPLEMENTATION_PATTERNS"]

    def test_similarity_threshold_clamped(self):
        """Similarity threshold should be clamped to 0.0-1.0"""
        query1 = PlaybookQuery(query="test", similarity_threshold=-0.5)
        assert query1.similarity_threshold == 0.0

        query2 = PlaybookQuery(query="test", similarity_threshold=1.5)
        assert query2.similarity_threshold == 1.0

    def test_limit_validation(self):
        """Limit must be >= 1"""
        with pytest.raises(ValueError, match="Limit must be >= 1"):
            PlaybookQuery(query="test", limit=0)

        with pytest.raises(ValueError, match="Limit must be >= 1"):
            PlaybookQuery(query="test", limit=-5)

    def test_default_values(self):
        """Test default values for optional parameters"""
        query = PlaybookQuery(query="test")

        assert query.sections is None
        assert query.min_quality_score == 0
        assert query.exclude_deprecated is True
        assert query.limit is None
        assert query.similarity_threshold == 0.3
        assert query.search_mode == SearchMode.PLAYBOOK_ONLY
        assert query.fts_prefix is True


class TestQueryAPIBasic:
    """Test basic query() API functionality"""

    def test_query_simple_search(self, manager_with_bullets):
        """Test simple FTS5 query"""
        params = PlaybookQuery(
            query="JWT",
            limit=5
        )

        response = manager_with_bullets.query(params)

        assert isinstance(response, PlaybookQueryResponse)
        assert len(response.results) > 0
        assert all(isinstance(r, PlaybookResult) for r in response.results)

        # Should find JWT-related bullets
        jwt_contents = [r.content for r in response.results]
        assert any("JWT" in content for content in jwt_contents)

    def test_query_with_section_filter(self, manager_with_bullets):
        """Test query with section filtering"""
        params = PlaybookQuery(
            query="authentication",
            sections=["SECURITY_PATTERNS"],
            limit=10
        )

        response = manager_with_bullets.query(params)

        # All results should be from SECURITY_PATTERNS section
        for result in response.results:
            assert result.section == "SECURITY_PATTERNS"

    def test_query_with_quality_filter(self, manager_with_bullets):
        """Test query with minimum quality score filter"""
        params = PlaybookQuery(
            query="authentication",
            min_quality_score=3,
            limit=10
        )

        response = manager_with_bullets.query(params)

        # All results should have quality_score >= 3
        for result in response.results:
            assert result.quality_score >= 3

    def test_query_excludes_deprecated(self, manager_with_bullets):
        """Test that deprecated bullets are excluded by default"""
        params = PlaybookQuery(
            query="authentication",
            limit=10
        )

        response = manager_with_bullets.query(params)

        # No deprecated bullets should be in results
        for result in response.results:
            assert "deprecated" not in result.content.lower() or \
                   "Old authentication pattern" not in result.content

    def test_query_with_limit(self, manager_with_bullets):
        """Test query respects limit parameter"""
        params = PlaybookQuery(
            query="database",
            limit=1
        )

        response = manager_with_bullets.query(params)

        assert len(response.results) <= 1

    def test_query_uses_default_top_k(self, manager_with_bullets):
        """Test query uses playbook top_k when limit not specified"""
        # Set top_k to 3
        manager_with_bullets.playbook["metadata"]["top_k"] = 3

        params = PlaybookQuery(
            query="authentication"
            # Note: no limit specified
        )

        response = manager_with_bullets.query(params)

        # Should return at most 3 results (top_k)
        assert len(response.results) <= 3


class TestQueryAPIMetadata:
    """Test query response metadata"""

    def test_metadata_structure(self, manager_with_bullets):
        """Test response metadata has required fields"""
        params = PlaybookQuery(query="JWT", limit=5)
        response = manager_with_bullets.query(params)

        assert "total_candidates" in response.metadata
        assert "search_time_ms" in response.metadata
        assert "search_method" in response.metadata
        assert "cipher_results" in response.metadata
        assert "playbook_results" in response.metadata
        assert "sections_searched" in response.metadata

    def test_metadata_search_method(self, manager_with_bullets):
        """Test search_method metadata"""
        params = PlaybookQuery(query="JWT", limit=5)
        response = manager_with_bullets.query(params)

        # Without semantic search, should be "fts5"
        assert response.metadata["search_method"] in ["fts5", "fts5+semantic"]

    def test_metadata_search_time(self, manager_with_bullets):
        """Test search_time_ms is reasonable"""
        params = PlaybookQuery(query="JWT", limit=5)
        response = manager_with_bullets.query(params)

        # Should complete in reasonable time (<500ms for test data)
        assert response.metadata["search_time_ms"] < 500
        assert response.metadata["search_time_ms"] >= 0  # Can be 0 for very fast queries

    def test_metadata_sections_searched(self, manager_with_bullets):
        """Test sections_searched metadata"""
        params = PlaybookQuery(
            query="JWT",
            sections=["SECURITY_PATTERNS", "IMPLEMENTATION_PATTERNS"],
            limit=5
        )
        response = manager_with_bullets.query(params)

        assert response.metadata["sections_searched"] == [
            "SECURITY_PATTERNS",
            "IMPLEMENTATION_PATTERNS"
        ]


class TestPlaybookResultStructure:
    """Test PlaybookResult dataclass structure"""

    def test_result_has_all_fields(self, manager_with_bullets):
        """Test result has all required fields"""
        params = PlaybookQuery(query="JWT", limit=1)
        response = manager_with_bullets.query(params)

        assert len(response.results) > 0
        result = response.results[0]

        # Check all required fields exist
        assert hasattr(result, 'id')
        assert hasattr(result, 'section')
        assert hasattr(result, 'content')
        assert hasattr(result, 'code_example')
        assert hasattr(result, 'helpful_count')
        assert hasattr(result, 'harmful_count')
        assert hasattr(result, 'quality_score')
        assert hasattr(result, 'relevance_score')
        assert hasattr(result, 'source')
        assert hasattr(result, 'combined_score')
        assert hasattr(result, 'related_bullets')
        assert hasattr(result, 'tags')
        assert hasattr(result, 'created_at')
        assert hasattr(result, 'last_used_at')

    def test_result_scores_valid_range(self, manager_with_bullets):
        """Test scores are in valid ranges"""
        params = PlaybookQuery(query="JWT", limit=5)
        response = manager_with_bullets.query(params)

        for result in response.results:
            # Relevance score should be 0.0-1.0
            assert 0.0 <= result.relevance_score <= 1.0
            # Combined score should be 0.0-1.0
            assert 0.0 <= result.combined_score <= 1.0
            # Quality score can be negative
            assert isinstance(result.quality_score, int)

    def test_result_source_is_playbook(self, manager_with_bullets):
        """Test source field is set correctly"""
        params = PlaybookQuery(query="JWT", limit=5)
        response = manager_with_bullets.query(params)

        for result in response.results:
            assert result.source == "playbook"


class TestBackwardCompatibility:
    """Test backward compatibility with get_relevant_bullets()"""

    def test_get_relevant_bullets_uses_query(self, manager_with_bullets):
        """Test get_relevant_bullets() wraps query() correctly"""
        results = manager_with_bullets.get_relevant_bullets(
            query="JWT authentication",
            limit=5,
            min_quality_score=0
        )

        # Should return list of dicts (old format)
        assert isinstance(results, list)
        assert all(isinstance(r, dict) for r in results)

        # Should have expected fields
        if results:
            assert "id" in results[0]
            assert "content" in results[0]
            assert "quality_score" in results[0]

    def test_get_relevant_bullets_same_results_as_query(self, manager_with_bullets):
        """Test get_relevant_bullets() returns same data as query()"""
        # Call get_relevant_bullets()
        old_results = manager_with_bullets.get_relevant_bullets(
            query="JWT",
            limit=3,
            min_quality_score=0
        )

        # Call query() with same params
        new_response = manager_with_bullets.query(PlaybookQuery(
            query="JWT",
            limit=3,
            min_quality_score=0
        ))

        # Should return same number of results
        assert len(old_results) == len(new_response.results)

        # IDs should match
        old_ids = {r["id"] for r in old_results}
        new_ids = {r.id for r in new_response.results}
        assert old_ids == new_ids

    def test_get_relevant_bullets_respects_top_k(self, manager_with_bullets):
        """Test get_relevant_bullets() respects playbook top_k"""
        manager_with_bullets.playbook["metadata"]["top_k"] = 2

        results = manager_with_bullets.get_relevant_bullets("authentication")

        # Should return at most top_k results
        assert len(results) <= 2

    def test_get_relevant_bullets_backward_compatible_signature(self, manager_with_bullets):
        """Test method signature is backward compatible"""
        # Old-style positional call
        try:
            manager_with_bullets.get_relevant_bullets("test", 5)
        except TypeError:
            pytest.fail("Positional arguments not supported (backward compatibility broken)")

        # Old-style keyword call
        try:
            manager_with_bullets.get_relevant_bullets(
                query="test",
                limit=5,
                min_quality_score=0,
                similarity_threshold=0.3
            )
        except TypeError:
            pytest.fail("Keyword arguments not supported (backward compatibility broken)")


class TestFTS5PrefixMatching:
    """Test FTS5 prefix matching functionality"""

    def test_prefix_matching_enabled(self, manager_with_bullets):
        """Test FTS5 prefix matching finds partial matches"""
        # Add a bullet with "authentication"
        manager_with_bullets._add_bullet(
            section="SECURITY_PATTERNS",
            content="Authentication flows require proper token handling"
        )

        # Query with "auth" should match "authentication" with prefix matching
        params = PlaybookQuery(
            query="auth",
            fts_prefix=True,
            limit=10
        )

        response = manager_with_bullets.query(params)

        # Should find bullets containing "authentication"
        assert len(response.results) > 0
        assert any("authentication" in r.content.lower() for r in response.results)

    def test_prefix_matching_disabled(self, manager_with_bullets):
        """Test disabling prefix matching"""
        params = PlaybookQuery(
            query="auth",
            fts_prefix=False,
            limit=10
        )

        response = manager_with_bullets.query(params)

        # Without prefix matching, "auth" should not match "authentication"
        # (though may match if "auth" appears as standalone word)
        # This test validates that fts_prefix parameter is accepted
        assert isinstance(response, PlaybookQueryResponse)


class TestMultiSectionSearch:
    """Test searching across multiple sections"""

    def test_search_all_sections(self, manager_with_bullets):
        """Test searching all sections when sections=None"""
        params = PlaybookQuery(
            query="authentication",
            sections=None,  # All sections
            limit=10
        )

        response = manager_with_bullets.query(params)

        # Should return results from multiple sections
        sections_found = {r.section for r in response.results}
        assert len(sections_found) >= 1

    def test_search_specific_sections(self, manager_with_bullets):
        """Test filtering by specific sections"""
        params = PlaybookQuery(
            query="database",
            sections=["PERFORMANCE_PATTERNS", "DEBUGGING_TECHNIQUES"],
            limit=10
        )

        response = manager_with_bullets.query(params)

        # All results should be from specified sections
        for result in response.results:
            assert result.section in ["PERFORMANCE_PATTERNS", "DEBUGGING_TECHNIQUES"]


class TestEdgeCases:
    """Test edge cases and error handling"""

    def test_query_with_no_results(self, manager_with_bullets):
        """Test query that matches no bullets"""
        params = PlaybookQuery(
            query="nonexistent_term_xyz123",
            limit=10
        )

        response = manager_with_bullets.query(params)

        # Should return empty results, not raise error
        assert len(response.results) == 0
        assert response.metadata["total_candidates"] == 0

    def test_query_empty_playbook(self, temp_playbook):
        """Test query on empty playbook"""
        manager = PlaybookManager(playbook_path=str(temp_playbook), use_semantic_search=False)

        params = PlaybookQuery(query="test", limit=5)
        response = manager.query(params)

        assert len(response.results) == 0

    def test_query_with_special_characters(self, manager_with_bullets):
        """Test query with special characters"""
        params = PlaybookQuery(
            query="JWT @authentication #token",
            limit=5
        )

        # Should not raise error
        response = manager_with_bullets.query(params)
        assert isinstance(response, PlaybookQueryResponse)

    def test_result_ordering_by_combined_score(self, manager_with_bullets):
        """Test results are ordered by combined score"""
        params = PlaybookQuery(
            query="authentication",
            limit=10
        )

        response = manager_with_bullets.query(params)

        # Results should be in descending order of combined_score
        if len(response.results) > 1:
            for i in range(len(response.results) - 1):
                assert response.results[i].combined_score >= response.results[i + 1].combined_score
