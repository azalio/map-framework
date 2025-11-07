"""
Test that recitation_manager prefers playbook.db over playbook.json.

This test verifies the fix for the issue where map-efficient was trying
to read .claude/playbook.json even when .claude/playbook.db already existed.
"""

from pathlib import Path
import json
from mapify_cli.recitation_manager import RecitationManager


def test_recitation_prefers_db_over_json(tmp_path):
    """Test that when both .db and .json exist, .db is used and .json is not read."""
    # Setup: Create .claude directory
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()

    # Create playbook.db (empty but valid SQLite database)
    db_path = claude_dir / "playbook.db"
    import sqlite3

    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT, value TEXT)")
    conn.commit()
    conn.close()

    # Create playbook.json (should NOT be read when .db exists)
    json_path = claude_dir / "playbook.json"
    json_path.write_text(
        json.dumps({"version": "1.0", "metadata": {"total_bullets": 0}, "sections": {}})
    )

    # Test: Initialize RecitationManager
    manager = RecitationManager(project_root=tmp_path)

    # When generating context, it should prefer .db
    # This should NOT raise an error about missing playbook.json
    context_path = manager.generate_context_md()

    # Verify it executed without errors
    assert context_path is not None
    assert Path(context_path).exists()

    # Verify content was generated
    content = Path(context_path).read_text()
    assert len(content) > 0


def test_recitation_migrates_json_to_db_when_only_json_exists(tmp_path):
    """Test that migration happens when only .json exists."""
    # Setup: Create .claude directory
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()

    # Create only playbook.json
    json_path = claude_dir / "playbook.json"
    json_path.write_text(
        json.dumps(
            {
                "version": "1.0",
                "metadata": {
                    "project": "test",
                    "created_at": "2024-01-01T00:00:00Z",
                    "last_updated": "2024-01-01T00:00:00Z",
                    "total_bullets": 1,
                    "sections_count": 10,
                    "top_k": 5,
                },
                "sections": {
                    "IMPLEMENTATION_PATTERNS": {
                        "description": "Code patterns",
                        "bullets": [
                            {
                                "id": "impl-0001",
                                "content": "Test pattern",
                                "helpful_count": 0,
                                "harmful_count": 0,
                                "created_at": "2024-01-01T00:00:00Z",
                                "last_used_at": "2024-01-01T00:00:00Z",
                            }
                        ],
                    }
                },
            }
        )
    )

    # Test: Initialize RecitationManager
    manager = RecitationManager(project_root=tmp_path)

    # Generate context - should trigger migration
    context = manager.generate_context_md()

    # Verify context file was generated and is non-empty
    assert context is not None
    assert Path(context).exists()
    content = Path(context).read_text()
    assert len(content) > 0
    # Verify migration happened
    db_path = claude_dir / "playbook.db"
    assert db_path.exists(), "Migration should create playbook.db"

    # Verify backup was created
    backups = list(claude_dir.glob("playbook.json.backup.*"))
    assert len(backups) > 0, "Migration should create backup of playbook.json"


def test_recitation_handles_missing_playbook_gracefully(tmp_path):
    """Test that missing playbook doesn't cause errors."""
    # Setup: Create .claude directory but no playbook files
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()

    # Test: Initialize RecitationManager
    manager = RecitationManager(project_root=tmp_path)

    # This should NOT raise an error
    context_path = manager.generate_context_md()

    # Verify it executed without errors
    assert context_path is not None
    assert Path(context_path).exists()

    # Verify content was generated
    content = Path(context_path).read_text()
    assert len(content) > 0
