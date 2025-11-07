"""Pytest fixtures for integration tests."""

import os
import pytest

# Set environment variables before any imports
os.environ["TRANSFORMERS_NO_TF"] = "1"
os.environ["TF_USE_LEGACY_KERAS"] = "1"
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"

from mapify_cli.playbook_manager import PlaybookManager, SEMANTIC_SEARCH_AVAILABLE


@pytest.fixture(scope="module")
def manager(tmp_path_factory):
    """Create PlaybookManager with semantic search for integration tests."""
    if not SEMANTIC_SEARCH_AVAILABLE:
        pytest.skip("sentence-transformers not installed")

    # Create temporary directory for test playbook
    test_dir = tmp_path_factory.mktemp("semantic_test")
    playbook_path = test_dir / "playbook_test.json"

    # Initialize manager
    manager = PlaybookManager(
        playbook_path=str(playbook_path), use_semantic_search=True
    )

    yield manager

    # Cleanup
    if playbook_path.exists():
        playbook_path.unlink()
