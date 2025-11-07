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
            "metadata": {"project": "test-project", "total_bullets": 2, "top_k": 5},
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
                            "related_bullets": [],
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
                            "related_bullets": ["impl-0001"],
                        },
                    ]
                }
            },
        }

        json_path.write_text(json.dumps(playbook_data))

        # Create PlaybookManager - should trigger migration
        manager = PlaybookManager(
            playbook_path=str(json_path), use_semantic_search=False
        )

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
                            "related_bullets": [],
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
                            "related_bullets": [],
                        },
                        {
                            "id": "impl-0002",
                            "content": "Implementation pattern 2",
                            "helpful_count": 3,
                            "harmful_count": 0,
                            "created_at": "2025-01-01T00:00:00Z",
                            "last_used_at": "2025-01-01T00:00:00Z",
                            "tags": [],
                            "related_bullets": [],
                        },
                    ]
                },
            },
        }

        json_path.write_text(json.dumps(playbook_data))

        # Migrate
        manager = PlaybookManager(
            playbook_path=str(json_path), use_semantic_search=False
        )

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
            "metadata": {"project": "test-project", "total_bullets": 0, "top_k": 7},
            "sections": {"IMPLEMENTATION_PATTERNS": {"bullets": []}},
        }

        json_path.write_text(json.dumps(playbook_data))

        # Migrate
        manager = PlaybookManager(
            playbook_path=str(json_path), use_semantic_search=False
        )

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
                            "related_bullets": ["impl-0002", "impl-0003"],
                        }
                    ]
                }
            },
        }

        json_path.write_text(json.dumps(playbook_data))

        # Migrate
        manager = PlaybookManager(
            playbook_path=str(json_path), use_semantic_search=False
        )

        # Verify complex fields
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM bullets WHERE id = 'impl-0001'")
        row = cursor.fetchone()
        conn.close()
        manager.close()

        assert row["code_example"] == "def foo():\n    return 42"
        assert json.loads(row["tags"]) == ["python", "functions", "testing"]
        assert json.loads(row["related_bullets"]) == ["impl-0002", "impl-0003"]


class TestSchemaIdempotency:
    """Test schema creation idempotency"""

    def test_schema_creation_idempotent(self, temp_playbook_dir):
        """Schema can be created multiple times without errors"""
        db_path = temp_playbook_dir / "playbook.db"
        json_path = temp_playbook_dir / "playbook.json"

        # Create manager (creates schema)
        manager1 = PlaybookManager(
            playbook_path=str(json_path), use_semantic_search=False
        )
        manager1.close()

        # Create another manager (schema already exists)
        manager2 = PlaybookManager(
            playbook_path=str(json_path), use_semantic_search=False
        )
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
                            "related_bullets": [],
                        }
                    ]
                }
            },
        }

        json_path.write_text(json.dumps(playbook_data))

        # Migrate
        manager = PlaybookManager(
            playbook_path=str(json_path), use_semantic_search=False
        )

        # Verify FTS index works
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT b.id, b.content
            FROM bullets b
            JOIN bullets_fts fts ON b.rowid = fts.rowid
            WHERE fts.bullets_fts MATCH 'JWT'
        """
        )
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
        manager = PlaybookManager(
            playbook_path=str(json_path), use_semantic_search=False
        )

        # Add bullet via manager
        manager._add_bullet(
            section="IMPLEMENTATION_PATTERNS",
            content="Database connection pooling",
            tags=["database", "performance"],
        )

        # Query via FTS
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT b.content
            FROM bullets b
            JOIN bullets_fts fts ON b.rowid = fts.rowid
            WHERE fts.bullets_fts MATCH 'pooling'
        """
        )
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
                            "related_bullets": [],
                        }
                    ]
                }
            },
        }

        json_path.write_text(json.dumps(playbook_data))

        manager = PlaybookManager(
            playbook_path=str(json_path), use_semantic_search=False
        )

        # Verify playbook dict available
        assert "metadata" in manager.playbook
        assert "sections" in manager.playbook
        assert manager.playbook["metadata"]["top_k"] == 5
        assert (
            len(manager.playbook["sections"]["IMPLEMENTATION_PATTERNS"]["bullets"]) == 1
        )

        manager.close()

    def test_get_relevant_bullets_still_works(self, temp_playbook_dir):
        """Existing get_relevant_bullets() API still works"""
        json_path = temp_playbook_dir / "playbook.json"

        manager = PlaybookManager(
            playbook_path=str(json_path), use_semantic_search=False
        )

        # Add bullets
        manager._add_bullet(
            section="IMPLEMENTATION_PATTERNS",
            content="Pattern about database optimization",
            tags=["database"],
        )
        manager._add_bullet(
            section="IMPLEMENTATION_PATTERNS",
            content="Pattern about authentication",
            tags=["security"],
        )

        # Query using old API
        results = manager.get_relevant_bullets("database", limit=5)

        assert len(results) >= 1
        assert any("database" in r["content"].lower() for r in results)

        manager.close()


class TestSchemaMigration:
    """Test schema version migration from 2.0 to 2.1"""

    def test_migration_adds_executable_scripts_field(self, temp_playbook_dir):
        """Migration from 2.0 to 2.1 to 3.0 adds executable_scripts column and KG tables"""
        db_path = temp_playbook_dir / "playbook.db"

        # Create a 2.0 schema database manually (without executable_scripts)
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        # Create old schema (2.0) without executable_scripts
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS bullets (
                id TEXT PRIMARY KEY,
                section TEXT NOT NULL,
                content TEXT NOT NULL,
                code_example TEXT,
                helpful_count INTEGER DEFAULT 0,
                harmful_count INTEGER DEFAULT 0,
                quality_score INTEGER GENERATED ALWAYS AS (helpful_count - harmful_count) VIRTUAL,
                created_at TEXT NOT NULL,
                last_used_at TEXT NOT NULL,
                deprecated INTEGER DEFAULT 0,
                deprecation_reason TEXT,
                tags TEXT,
                related_bullets TEXT
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """
        )

        # Set schema version to 2.0
        cursor.execute("INSERT INTO metadata VALUES ('schema_version', '2.0')")

        # Add a test bullet
        cursor.execute(
            """
            INSERT INTO bullets (id, section, content, created_at, last_used_at, tags, related_bullets)
            VALUES ('impl-0001', 'IMPLEMENTATION_PATTERNS', 'Test pattern', '2025-01-01T00:00:00Z', '2025-01-01T00:00:00Z', '[]', '[]')
        """
        )

        conn.commit()
        conn.close()

        # Create PlaybookManager - should trigger migration to 2.1 then 3.0
        json_path = temp_playbook_dir / "playbook.json"
        manager = PlaybookManager(
            playbook_path=str(json_path),
            db_path=str(db_path),
            use_semantic_search=False,
        )

        # Verify schema version updated to 3.0 (migration chain: 2.0 -> 2.1 -> 3.0)
        cursor = manager.db_conn.cursor()
        cursor.execute("SELECT value FROM metadata WHERE key = 'schema_version'")
        version = cursor.fetchone()[0]
        assert version == "3.0", f"Expected final schema version 3.0, got {version}"

        # Verify executable_scripts column exists (from 2.1 migration)
        cursor.execute("PRAGMA table_info(bullets)")
        columns = [row[1] for row in cursor.fetchall()]
        assert "executable_scripts" in columns

        # Verify existing data preserved
        cursor.execute("SELECT id, content FROM bullets WHERE id = 'impl-0001'")
        row = cursor.fetchone()
        assert row[0] == "impl-0001"
        assert row[1] == "Test pattern"

        # Verify KG tables exist (from 3.0 migration)
        cursor.execute(
            """
            SELECT COUNT(*) FROM sqlite_master
            WHERE type='table' AND name IN ('entities', 'relationships', 'provenance')
        """
        )
        kg_table_count = cursor.fetchone()[0]
        assert kg_table_count == 3, "KG tables not created during migration chain"

        manager.close()

    def test_migration_idempotent(self, temp_playbook_dir):
        """Migration can be run multiple times without errors"""
        db_path = temp_playbook_dir / "playbook.db"

        # Create a 2.0 schema database
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS bullets (
                id TEXT PRIMARY KEY,
                section TEXT NOT NULL,
                content TEXT NOT NULL,
                code_example TEXT,
                helpful_count INTEGER DEFAULT 0,
                harmful_count INTEGER DEFAULT 0,
                quality_score INTEGER GENERATED ALWAYS AS (helpful_count - harmful_count) VIRTUAL,
                created_at TEXT NOT NULL,
                last_used_at TEXT NOT NULL,
                deprecated INTEGER DEFAULT 0,
                deprecation_reason TEXT,
                tags TEXT,
                related_bullets TEXT
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """
        )

        cursor.execute("INSERT INTO metadata VALUES ('schema_version', '2.0')")
        conn.commit()
        conn.close()

        # First migration (2.0 -> 2.1 -> 3.0)
        json_path = temp_playbook_dir / "playbook.json"
        manager1 = PlaybookManager(
            playbook_path=str(json_path),
            db_path=str(db_path),
            use_semantic_search=False,
        )
        manager1.close()

        # Second migration (should be no-op, already at 3.0)
        manager2 = PlaybookManager(
            playbook_path=str(json_path),
            db_path=str(db_path),
            use_semantic_search=False,
        )

        # Verify at 3.0 (migration chain completed)
        cursor = manager2.db_conn.cursor()
        cursor.execute("SELECT value FROM metadata WHERE key = 'schema_version'")
        version = cursor.fetchone()[0]
        assert version == "3.0", f"Expected schema version 3.0, got {version}"

        manager2.close()

    def test_executable_scripts_nullable(self, temp_playbook_dir):
        """New executable_scripts field allows NULL for existing bullets"""
        json_path = temp_playbook_dir / "playbook.json"

        manager = PlaybookManager(
            playbook_path=str(json_path), use_semantic_search=False
        )

        # Add bullet without executable_scripts
        manager._add_bullet(
            section="IMPLEMENTATION_PATTERNS", content="Test pattern without scripts"
        )

        # Verify it was added with NULL executable_scripts
        cursor = manager.db_conn.cursor()
        cursor.execute("SELECT executable_scripts FROM bullets LIMIT 1")
        result = cursor.fetchone()
        assert result[0] is None

        manager.close()

    def test_new_bullets_accept_executable_scripts(self, temp_playbook_dir):
        """New bullets can store executable_scripts data"""
        json_path = temp_playbook_dir / "playbook.json"

        manager = PlaybookManager(
            playbook_path=str(json_path), use_semantic_search=False
        )

        # Add bullet with executable_scripts
        scripts = ["scripts/test.sh", "scripts/validate.py"]
        bullet_id = manager._add_bullet(
            section="IMPLEMENTATION_PATTERNS",
            content="Test pattern with scripts",
            executable_scripts=scripts,
        )

        # Verify it was stored correctly
        cursor = manager.db_conn.cursor()
        cursor.execute(
            "SELECT executable_scripts FROM bullets WHERE id = ?", (bullet_id,)
        )
        stored = cursor.fetchone()[0]
        assert json.loads(stored) == scripts

        # Verify in-memory playbook also has it
        bullet = manager._find_bullet(bullet_id)
        assert bullet["executable_scripts"] == scripts

        manager.close()

    def test_migration_2_1_to_3_0_creates_kg_tables(self, temp_playbook_dir):
        """Migration from 2.1 to 3.0 adds Knowledge Graph tables"""
        db_path = temp_playbook_dir / "playbook.db"

        # Create a 2.1 schema database manually (with executable_scripts but no KG tables)
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        # Create 2.1 schema (with executable_scripts)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS bullets (
                id TEXT PRIMARY KEY,
                section TEXT NOT NULL,
                content TEXT NOT NULL,
                code_example TEXT,
                helpful_count INTEGER DEFAULT 0,
                harmful_count INTEGER DEFAULT 0,
                quality_score INTEGER GENERATED ALWAYS AS (helpful_count - harmful_count) VIRTUAL,
                created_at TEXT NOT NULL,
                last_used_at TEXT NOT NULL,
                deprecated INTEGER DEFAULT 0,
                deprecation_reason TEXT,
                tags TEXT,
                related_bullets TEXT,
                executable_scripts TEXT
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """
        )

        # Set schema version to 2.1
        cursor.execute("INSERT INTO metadata VALUES ('schema_version', '2.1')")

        # Add a test bullet
        cursor.execute(
            """
            INSERT INTO bullets (id, section, content, created_at, last_used_at, tags, related_bullets)
            VALUES ('impl-0001', 'IMPLEMENTATION_PATTERNS', 'Test pattern', '2025-01-01T00:00:00Z', '2025-01-01T00:00:00Z', '[]', '[]')
        """
        )

        conn.commit()
        conn.close()

        # Create PlaybookManager - should trigger migration to 3.0
        json_path = temp_playbook_dir / "playbook.json"
        manager = PlaybookManager(
            playbook_path=str(json_path),
            db_path=str(db_path),
            use_semantic_search=False,
        )

        # Verify schema version updated to 3.0
        cursor = manager.db_conn.cursor()
        cursor.execute("SELECT value FROM metadata WHERE key = 'schema_version'")
        version = cursor.fetchone()[0]
        assert version == "3.0", f"Expected schema version 3.0, got {version}"

        # Verify KG tables exist
        cursor.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='table' AND name IN ('entities', 'relationships', 'provenance')
            ORDER BY name
        """
        )
        kg_tables = [row[0] for row in cursor.fetchall()]
        assert (
            len(kg_tables) == 3
        ), f"Expected 3 KG tables, found {len(kg_tables)}: {kg_tables}"
        assert "entities" in kg_tables
        assert "relationships" in kg_tables
        assert "provenance" in kg_tables

        # Verify FTS table for entities exists
        cursor.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='table' AND name = 'entities_fts'
        """
        )
        fts_table = cursor.fetchone()
        assert fts_table is not None, "entities_fts table not created"

        # Verify existing bullet data preserved
        cursor.execute("SELECT id, content FROM bullets WHERE id = 'impl-0001'")
        row = cursor.fetchone()
        assert row[0] == "impl-0001"
        assert row[1] == "Test pattern"

        # Verify metadata keys added
        cursor.execute("SELECT value FROM metadata WHERE key = 'kg_enabled'")
        kg_enabled = cursor.fetchone()
        assert kg_enabled is not None
        assert kg_enabled[0] == "1"

        manager.close()

    def test_migration_3_0_idempotent(self, temp_playbook_dir):
        """Migration to 3.0 can be run multiple times without errors"""
        db_path = temp_playbook_dir / "playbook.db"

        # Create a 2.1 schema database
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS bullets (
                id TEXT PRIMARY KEY,
                section TEXT NOT NULL,
                content TEXT NOT NULL,
                code_example TEXT,
                helpful_count INTEGER DEFAULT 0,
                harmful_count INTEGER DEFAULT 0,
                quality_score INTEGER GENERATED ALWAYS AS (helpful_count - harmful_count) VIRTUAL,
                created_at TEXT NOT NULL,
                last_used_at TEXT NOT NULL,
                deprecated INTEGER DEFAULT 0,
                deprecation_reason TEXT,
                tags TEXT,
                related_bullets TEXT,
                executable_scripts TEXT
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """
        )

        cursor.execute("INSERT INTO metadata VALUES ('schema_version', '2.1')")
        conn.commit()
        conn.close()

        # First migration to 3.0
        json_path = temp_playbook_dir / "playbook.json"
        manager1 = PlaybookManager(
            playbook_path=str(json_path),
            db_path=str(db_path),
            use_semantic_search=False,
        )
        manager1.close()

        # Second instantiation (should be no-op, already at 3.0)
        manager2 = PlaybookManager(
            playbook_path=str(json_path),
            db_path=str(db_path),
            use_semantic_search=False,
        )

        # Verify still at 3.0
        cursor = manager2.db_conn.cursor()
        cursor.execute("SELECT value FROM metadata WHERE key = 'schema_version'")
        version = cursor.fetchone()[0]
        assert version == "3.0"

        # Verify tables still exist
        cursor.execute(
            """
            SELECT COUNT(*) FROM sqlite_master
            WHERE type='table' AND name IN ('entities', 'relationships', 'provenance')
        """
        )
        table_count = cursor.fetchone()[0]
        assert table_count == 3

        manager2.close()

    def test_foreign_keys_enabled(self, temp_playbook_dir):
        """Verify foreign key constraints are enabled (required for KG CASCADE deletes)"""
        json_path = temp_playbook_dir / "playbook.json"

        manager = PlaybookManager(
            playbook_path=str(json_path), use_semantic_search=False
        )

        # Check PRAGMA foreign_keys
        cursor = manager.db_conn.cursor()
        cursor.execute("PRAGMA foreign_keys")
        foreign_keys_enabled = cursor.fetchone()[0]
        assert (
            foreign_keys_enabled == 1
        ), "Foreign keys not enabled! Required for KG schema CASCADE deletes."

        manager.close()

    def test_apply_delta_supports_executable_scripts(self, temp_playbook_dir):
        """apply_delta ADD operation supports executable_scripts"""
        json_path = temp_playbook_dir / "playbook.json"

        manager = PlaybookManager(
            playbook_path=str(json_path), use_semantic_search=False
        )

        operations = [
            {
                "type": "ADD",
                "section": "IMPLEMENTATION_PATTERNS",
                "content": "Pattern with attached scripts",
                "executable_scripts": ["scripts/deploy.sh", "scripts/rollback.sh"],
            }
        ]

        summary = manager.apply_delta(operations)
        assert summary["added"] == 1
        assert summary["errors"] == []

        # Verify scripts were stored
        bullets = manager.playbook["sections"]["IMPLEMENTATION_PATTERNS"]["bullets"]
        assert len(bullets) == 1
        assert bullets[0]["executable_scripts"] == [
            "scripts/deploy.sh",
            "scripts/rollback.sh",
        ]

        manager.close()
