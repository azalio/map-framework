"""
Unit tests for PlaybookManager SQLite migration functionality.

Tests the automatic migration from JSON to SQLite storage and
schema idempotency.
"""

import json
import sqlite3
import pytest
from mapify_cli.playbook_manager import PlaybookManager


@pytest.fixture
def temp_playbook_dir(tmp_path):
    """Create a temporary playbook directory"""
    playbook_dir = tmp_path / ".claude"
    playbook_dir.mkdir()
    return playbook_dir


class TestMigrationJSONToSQLite:
    """Test migration from playbook.json to SQLite database"""

    def test_migration_creates_database(self, temp_playbook_dir):
        """Migration creates playbook.db file"""
        json_path = temp_playbook_dir / "playbook.json"
        db_path = temp_playbook_dir / "playbook.db"

        # Create a JSON playbook
        playbook_data = {
            "version": "1.0",
            "metadata": {
                "project": "test-project",
                "total_bullets": 2,
                "top_k": 5
            },
            "sections": {
                "IMPLEMENTATION_PATTERNS": {
                    "bullets": [
                        {
                            "id": "impl-0001",
                            "content": "Test pattern 1",
                            "helpful_count": 3,
                            "harmful_count": 0,
                            "created_at": "2025-01-01T00:00:00Z",
                            "last_used_at": "2025-01-01T00:00:00Z",
                            "tags": ["test"],
                            "related_bullets": []
                        },
                        {
                            "id": "impl-0002",
                            "content": "Test pattern 2",
                            "code_example": "print('hello')",
                            "helpful_count": 5,
                            "harmful_count": 1,
                            "created_at": "2025-01-01T00:00:00Z",
                            "last_used_at": "2025-01-01T00:00:00Z",
                            "tags": ["test", "code"],
                            "related_bullets": ["impl-0001"]
                        }
                    ]
                }
            }
        }

        json_path.write_text(json.dumps(playbook_data))

        # Create PlaybookManager - should trigger migration
        manager = PlaybookManager(playbook_path=str(json_path), use_semantic_search=False)

        # Verify database was created
        assert db_path.exists()

        # Verify backup was created
        backup_files = list(temp_playbook_dir.glob("playbook.json.backup.*"))
        assert len(backup_files) == 1

        manager.close()

    def test_migration_preserves_all_bullets(self, temp_playbook_dir):
        """Migration preserves all bullet data"""
        json_path = temp_playbook_dir / "playbook.json"
        db_path = temp_playbook_dir / "playbook.db"

        playbook_data = {
            "version": "1.0",
            "metadata": {"project": "test", "total_bullets": 3, "top_k": 5},
            "sections": {
                "SECURITY_PATTERNS": {
                    "bullets": [
                        {
                            "id": "sec-0001",
                            "content": "Security pattern 1",
                            "helpful_count": 2,
                            "harmful_count": 0,
                            "created_at": "2025-01-01T00:00:00Z",
                            "last_used_at": "2025-01-01T00:00:00Z",
                            "tags": [],
                            "related_bullets": []
                        }
                    ]
                },
                "IMPLEMENTATION_PATTERNS": {
                    "bullets": [
                        {
                            "id": "impl-0001",
                            "content": "Implementation pattern 1",
                            "helpful_count": 1,
                            "harmful_count": 0,
                            "created_at": "2025-01-01T00:00:00Z",
                            "last_used_at": "2025-01-01T00:00:00Z",
                            "tags": [],
                            "related_bullets": []
                        },
                        {
                            "id": "impl-0002",
                            "content": "Implementation pattern 2",
                            "helpful_count": 3,
                            "harmful_count": 0,
                            "created_at": "2025-01-01T00:00:00Z",
                            "last_used_at": "2025-01-01T00:00:00Z",
                            "tags": [],
                            "related_bullets": []
                        }
                    ]
                }
            }
        }

        json_path.write_text(json.dumps(playbook_data))

        # Migrate
        manager = PlaybookManager(playbook_path=str(json_path), use_semantic_search=False)

        # Verify all bullets in database
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM bullets")
        count = cursor.fetchone()[0]
        conn.close()
        manager.close()

        assert count == 3

    def test_migration_preserves_metadata(self, temp_playbook_dir):
        """Migration preserves metadata fields"""
        json_path = temp_playbook_dir / "playbook.json"
        db_path = temp_playbook_dir / "playbook.db"

        playbook_data = {
            "version": "1.0",
            "metadata": {
                "project": "test-project",
                "total_bullets": 0,
                "top_k": 7
            },
            "sections": {
                "IMPLEMENTATION_PATTERNS": {"bullets": []}
            }
        }

        json_path.write_text(json.dumps(playbook_data))

        # Migrate
        manager = PlaybookManager(playbook_path=str(json_path), use_semantic_search=False)

        # Verify metadata
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM metadata WHERE key = 'version'")
        version = cursor.fetchone()[0]
        cursor.execute("SELECT value FROM metadata WHERE key = 'top_k'")
        top_k = cursor.fetchone()[0]
        conn.close()
        manager.close()

        assert version == "1.0"
        assert top_k == "7"

    def test_migration_preserves_complex_fields(self, temp_playbook_dir):
        """Migration preserves tags, related_bullets, code_example"""
        json_path = temp_playbook_dir / "playbook.json"
        db_path = temp_playbook_dir / "playbook.db"

        playbook_data = {
            "version": "1.0",
            "metadata": {"project": "test", "total_bullets": 1, "top_k": 5},
            "sections": {
                "IMPLEMENTATION_PATTERNS": {
                    "bullets": [
                        {
                            "id": "impl-0001",
                            "content": "Complex pattern",
                            "code_example": "def foo():\n    return 42",
                            "helpful_count": 5,
                            "harmful_count": 0,
                            "created_at": "2025-01-01T00:00:00Z",
                            "last_used_at": "2025-01-01T00:00:00Z",
                            "tags": ["python", "functions", "testing"],
                            "related_bullets": ["impl-0002", "impl-0003"]
                        }
                    ]
                }
            }
        }

        json_path.write_text(json.dumps(playbook_data))

        # Migrate
        manager = PlaybookManager(playbook_path=str(json_path), use_semantic_search=False)

        # Verify complex fields
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM bullets WHERE id = 'impl-0001'")
        row = cursor.fetchone()
        conn.close()
        manager.close()

        assert row['code_example'] == "def foo():\n    return 42"
        assert json.loads(row['tags']) == ["python", "functions", "testing"]
        assert json.loads(row['related_bullets']) == ["impl-0002", "impl-0003"]


class TestSchemaIdempotency:
    """Test schema creation idempotency"""

    def test_schema_creation_idempotent(self, temp_playbook_dir):
        """Schema can be created multiple times without errors"""
        db_path = temp_playbook_dir / "playbook.db"
        json_path = temp_playbook_dir / "playbook.json"

        # Create manager (creates schema)
        manager1 = PlaybookManager(playbook_path=str(json_path), use_semantic_search=False)
        manager1.close()

        # Create another manager (schema already exists)
        manager2 = PlaybookManager(playbook_path=str(json_path), use_semantic_search=False)
        manager2.close()

        # Verify database still works
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM bullets")
        count = cursor.fetchone()[0]
        conn.close()

        assert count == 0  # No bullets added, just schema


class TestFTS5Integration:
    """Test FTS5 full-text search index"""

    def test_fts_index_created(self, temp_playbook_dir):
        """FTS5 index is created during migration"""
        json_path = temp_playbook_dir / "playbook.json"
        db_path = temp_playbook_dir / "playbook.db"

        playbook_data = {
            "version": "1.0",
            "metadata": {"project": "test", "total_bullets": 1, "top_k": 5},
            "sections": {
                "IMPLEMENTATION_PATTERNS": {
                    "bullets": [
                        {
                            "id": "impl-0001",
                            "content": "JWT authentication pattern",
                            "helpful_count": 5,
                            "harmful_count": 0,
                            "created_at": "2025-01-01T00:00:00Z",
                            "last_used_at": "2025-01-01T00:00:00Z",
                            "tags": [],
                            "related_bullets": []
                        }
                    ]
                }
            }
        }

        json_path.write_text(json.dumps(playbook_data))

        # Migrate
        manager = PlaybookManager(playbook_path=str(json_path), use_semantic_search=False)

        # Verify FTS index works
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("""
            SELECT b.id, b.content
            FROM bullets b
            JOIN bullets_fts fts ON b.rowid = fts.rowid
            WHERE fts.bullets_fts MATCH 'JWT'
        """)
        results = cursor.fetchall()
        conn.close()
        manager.close()

        assert len(results) == 1
        assert results[0][0] == "impl-0001"

    def test_fts_triggers_work(self, temp_playbook_dir):
        """FTS triggers automatically update index on INSERT"""
        json_path = temp_playbook_dir / "playbook.json"
        db_path = temp_playbook_dir / "playbook.db"

        # Create empty playbook
        manager = PlaybookManager(playbook_path=str(json_path), use_semantic_search=False)

        # Add bullet via manager
        manager._add_bullet(
            section="IMPLEMENTATION_PATTERNS",
            content="Database connection pooling",
            tags=["database", "performance"]
        )

        # Query via FTS
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("""
            SELECT b.content
            FROM bullets b
            JOIN bullets_fts fts ON b.rowid = fts.rowid
            WHERE fts.bullets_fts MATCH 'pooling'
        """)
        results = cursor.fetchall()
        conn.close()
        manager.close()

        assert len(results) == 1
        assert "pooling" in results[0][0].lower()


class TestBackwardCompatibility:
    """Test backward compatibility with existing code"""

    def test_playbook_dict_available(self, temp_playbook_dir):
        """PlaybookManager still provides self.playbook dict"""
        json_path = temp_playbook_dir / "playbook.json"

        playbook_data = {
            "version": "1.0",
            "metadata": {"project": "test", "total_bullets": 1, "top_k": 5},
            "sections": {
                "IMPLEMENTATION_PATTERNS": {
                    "bullets": [
                        {
                            "id": "impl-0001",
                            "content": "Test pattern",
                            "helpful_count": 1,
                            "harmful_count": 0,
                            "created_at": "2025-01-01T00:00:00Z",
                            "last_used_at": "2025-01-01T00:00:00Z",
                            "tags": [],
                            "related_bullets": []
                        }
                    ]
                }
            }
        }

        json_path.write_text(json.dumps(playbook_data))

        manager = PlaybookManager(playbook_path=str(json_path), use_semantic_search=False)

        # Verify playbook dict available
        assert "metadata" in manager.playbook
        assert "sections" in manager.playbook
        assert manager.playbook["metadata"]["top_k"] == 5
        assert len(manager.playbook["sections"]["IMPLEMENTATION_PATTERNS"]["bullets"]) == 1

        manager.close()

    def test_get_relevant_bullets_still_works(self, temp_playbook_dir):
        """Existing get_relevant_bullets() API still works"""
        json_path = temp_playbook_dir / "playbook.json"

        manager = PlaybookManager(playbook_path=str(json_path), use_semantic_search=False)

        # Add bullets
        manager._add_bullet(
            section="IMPLEMENTATION_PATTERNS",
            content="Pattern about database optimization",
            tags=["database"]
        )
        manager._add_bullet(
            section="IMPLEMENTATION_PATTERNS",
            content="Pattern about authentication",
            tags=["security"]
        )

        # Query using old API
        results = manager.get_relevant_bullets("database", limit=5)

        assert len(results) >= 1
        assert any("database" in r["content"].lower() for r in results)

        manager.close()
