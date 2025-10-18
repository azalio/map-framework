"""
Unit tests for PlaybookManager - Phase 1.3 top_k configuration

Tests the top_k parameter functionality that limits playbook patterns
to reduce context distraction and save tokens.
"""

import json
import pytest
from pathlib import Path
from mapify_cli.playbook_manager import PlaybookManager


@pytest.fixture
def temp_playbook(tmp_path):
    """Create a temporary playbook directory"""
    playbook_dir = tmp_path / ".claude"
    playbook_dir.mkdir()
    return playbook_dir / "playbook.json"


@pytest.fixture
def manager_with_playbook(temp_playbook):
    """Create PlaybookManager with temporary playbook"""
    return PlaybookManager(playbook_path=str(temp_playbook), use_semantic_search=False)


class TestTopKConfiguration:
    """Test top_k configuration functionality (Phase 1.3)"""

    def test_empty_playbook_creation_includes_top_k(self, temp_playbook):
        """New empty playbooks include top_k=5 in metadata"""
        manager = PlaybookManager(playbook_path=str(temp_playbook), use_semantic_search=False)

        assert "top_k" in manager.playbook["metadata"]
        assert manager.playbook["metadata"]["top_k"] == 5

    def test_playbook_file_on_disk_has_top_k(self, temp_playbook):
        """Playbook saved to disk includes top_k in metadata"""
        PlaybookManager(playbook_path=str(temp_playbook), use_semantic_search=False)

        # Read playbook from disk
        with open(temp_playbook, 'r') as f:
            playbook_data = json.load(f)

        assert "top_k" in playbook_data["metadata"]
        assert playbook_data["metadata"]["top_k"] == 5

    def test_loading_playbook_without_top_k_adds_default(self, temp_playbook):
        """Loading legacy playbook without top_k adds default value 5"""
        # Create playbook without top_k (simulate legacy playbook)
        legacy_playbook = {
            "version": "1.0",
            "metadata": {
                "project": "test",
                "total_bullets": 0
            },
            "sections": {
                "TEST_SECTION": {
                    "description": "Test",
                    "bullets": []
                }
            }
        }

        with open(temp_playbook, 'w') as f:
            json.dump(legacy_playbook, f)

        # Load playbook - should add top_k=5
        manager = PlaybookManager(playbook_path=str(temp_playbook), use_semantic_search=False)

        assert "top_k" in manager.playbook["metadata"]
        assert manager.playbook["metadata"]["top_k"] == 5

    def test_loading_playbook_with_custom_top_k_preserves_value(self, temp_playbook):
        """Loading playbook with custom top_k preserves the value"""
        custom_playbook = {
            "version": "1.0",
            "metadata": {
                "project": "test",
                "total_bullets": 0,
                "top_k": 3  # Custom value
            },
            "sections": {
                "TEST_SECTION": {
                    "description": "Test",
                    "bullets": []
                }
            }
        }

        with open(temp_playbook, 'w') as f:
            json.dump(custom_playbook, f)

        manager = PlaybookManager(playbook_path=str(temp_playbook), use_semantic_search=False)

        assert manager.playbook["metadata"]["top_k"] == 3

    def test_get_relevant_bullets_respects_playbook_top_k(self, manager_with_playbook):
        """get_relevant_bullets() uses playbook top_k when limit not specified"""
        # Add 10 test bullets
        for i in range(10):
            manager_with_playbook._add_bullet(
                section="ARCHITECTURE_PATTERNS",
                content=f"Test pattern {i} about architecture and design",
                tags=["test"]
            )

        # Call without explicit limit - should return 5 (default top_k)
        results = manager_with_playbook.get_relevant_bullets("architecture design")

        assert len(results) == 5, f"Expected 5 bullets (top_k default), got {len(results)}"

    def test_explicit_limit_overrides_playbook_top_k(self, manager_with_playbook):
        """Explicit limit parameter overrides playbook top_k"""
        # Add 10 test bullets
        for i in range(10):
            manager_with_playbook._add_bullet(
                section="ARCHITECTURE_PATTERNS",
                content=f"Test pattern {i} about architecture",
                tags=["test"]
            )

        # Call with explicit limit=3 - should return 3 (not top_k=5)
        results = manager_with_playbook.get_relevant_bullets("architecture", limit=3)

        assert len(results) == 3, f"Expected 3 bullets (explicit limit), got {len(results)}"

    def test_explicit_limit_10_overrides_top_k_5(self, manager_with_playbook):
        """Explicit limit=10 overrides playbook top_k=5"""
        # Add 12 test bullets
        for i in range(12):
            manager_with_playbook._add_bullet(
                section="ARCHITECTURE_PATTERNS",
                content=f"Test pattern {i} about architecture",
                tags=["test"]
            )

        # Call with explicit limit=10 - should return 10 (not top_k=5)
        results = manager_with_playbook.get_relevant_bullets("architecture", limit=10)

        assert len(results) == 10, f"Expected 10 bullets (explicit limit), got {len(results)}"

    def test_changing_top_k_affects_retrieval(self, manager_with_playbook):
        """Changing top_k in playbook affects get_relevant_bullets()"""
        # Add 10 test bullets
        for i in range(10):
            manager_with_playbook._add_bullet(
                section="ARCHITECTURE_PATTERNS",
                content=f"Test pattern {i} about architecture",
                tags=["test"]
            )

        # Default top_k=5
        results = manager_with_playbook.get_relevant_bullets("architecture")
        assert len(results) == 5

        # Change top_k to 3
        manager_with_playbook.playbook["metadata"]["top_k"] = 3
        results = manager_with_playbook.get_relevant_bullets("architecture")
        assert len(results) == 3

        # Change top_k to 7
        manager_with_playbook.playbook["metadata"]["top_k"] = 7
        results = manager_with_playbook.get_relevant_bullets("architecture")
        assert len(results) == 7

    def test_top_k_with_fewer_bullets_than_limit(self, manager_with_playbook):
        """When fewer bullets exist than top_k, return all bullets"""
        # Add only 3 bullets (less than top_k=5)
        for i in range(3):
            manager_with_playbook._add_bullet(
                section="ARCHITECTURE_PATTERNS",
                content=f"Test pattern {i} about architecture",
                tags=["test"]
            )

        results = manager_with_playbook.get_relevant_bullets("architecture")

        assert len(results) == 3, f"Expected 3 bullets (all available), got {len(results)}"

    def test_top_k_backward_compatibility(self, manager_with_playbook):
        """Method signature remains backward compatible"""
        # This should not raise any errors
        try:
            # Old-style call with positional limit
            manager_with_playbook.get_relevant_bullets("test", 10)

            # Old-style call with keyword limit
            manager_with_playbook.get_relevant_bullets("test", limit=10)

            # New-style call without limit
            manager_with_playbook.get_relevant_bullets("test")

        except TypeError as e:
            pytest.fail(f"Backward compatibility broken: {e}")


class TestTopKEdgeCases:
    """Test edge cases for top_k configuration"""

    def test_top_k_with_quality_filtering(self, manager_with_playbook):
        """top_k applies after quality filtering"""
        # Add 10 bullets: 5 high quality, 5 low quality
        for i in range(5):
            bullet_id = manager_with_playbook._add_bullet(
                section="ARCHITECTURE_PATTERNS",
                content=f"High quality pattern {i}",
                tags=["test"]
            )
            # Mark as helpful
            manager_with_playbook._update_bullet(bullet_id, increment_helpful=3)

        for i in range(5):
            bullet_id = manager_with_playbook._add_bullet(
                section="ARCHITECTURE_PATTERNS",
                content=f"Low quality pattern {i}",
                tags=["test"]
            )
            # Mark as harmful
            manager_with_playbook._update_bullet(bullet_id, increment_harmful=2)

        # Get bullets with min_quality_score=1 and default top_k=5
        # Should return 5 high-quality bullets (exactly top_k)
        results = manager_with_playbook.get_relevant_bullets(
            "pattern",
            min_quality_score=1
        )

        assert len(results) == 5
        # All results should be high quality
        for bullet in results:
            assert bullet["quality_score"] >= 1

    def test_top_k_with_deprecated_bullets(self, manager_with_playbook):
        """top_k counting excludes deprecated bullets"""
        # Add 8 bullets, deprecate 3 of them
        for i in range(8):
            bullet_id = manager_with_playbook._add_bullet(
                section="ARCHITECTURE_PATTERNS",
                content=f"Pattern {i}",
                tags=["test"]
            )
            if i < 3:
                manager_with_playbook._deprecate_bullet(bullet_id, "Test deprecation")

        # Should return 5 non-deprecated bullets (out of 5 available)
        results = manager_with_playbook.get_relevant_bullets("pattern")

        assert len(results) == 5
        # None should be deprecated
        for bullet in results:
            assert not bullet.get("deprecated", False)
