"""
ACE-style Playbook Manager for MAP Framework.

Handles deterministic merging of delta operations, deduplication of bullets,
and retrieval of relevant knowledge bullets for Agent context.

Based on research: Agentic Context Engineering (ACE) - arXiv:2510.04618v1
"""

import json
import hashlib
import sys
import sqlite3
import shutil
import time
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple
from pathlib import Path
import re

from .schemas import SCHEMA_V3_0_SQL

# Import query API dataclasses
from mapify_cli.playbook_query import (
    PlaybookQuery,
    PlaybookResult,
    PlaybookQueryResponse,
    SearchMode,
    VALID_SECTIONS,
)

# Optional: Semantic search with sentence-transformers
try:
    from mapify_cli.semantic_search import SemanticSearchEngine

    SEMANTIC_SEARCH_AVAILABLE = True
except (ImportError, ValueError) as e:
    # Handle both ImportError and ValueError (e.g., Keras compatibility issues)
    SEMANTIC_SEARCH_AVAILABLE = False
    SemanticSearchEngine = None  # Define placeholder
    # Debug: Print error if verbose mode
    import os

    if os.environ.get("DEBUG_SEMANTIC_SEARCH"):
        print(f"Semantic search unavailable: {type(e).__name__}: {e}")


# Quality score normalization constants
QUALITY_SCORE_MAX = 10.0  # Typical max quality score for bullets
RELEVANCE_WEIGHT = 0.7  # Weight for relevance in combined score
QUALITY_WEIGHT = 0.3  # Weight for quality in combined score

# Schema version constants
CURRENT_SCHEMA_VERSION = (
    "3.0"  # Added Knowledge Graph tables (entities, relationships, provenance)
)


class PlaybookManager:
    """Manages ACE-style playbook with incremental delta updates."""

    def __init__(
        self,
        playbook_path: Optional[
            str
        ] = None,  # DEPRECATED: kept for backward compatibility
        db_path: Optional[str] = None,
        use_semantic_search: bool = True,
    ):
        # Handle legacy playbook_path parameter
        if playbook_path is not None:
            self.playbook_path = Path(playbook_path)
            # If db_path not explicitly provided, derive from playbook_path
            if db_path is None:
                self.db_path = self.playbook_path.parent / "playbook.db"
            else:
                self.db_path = Path(db_path)
        else:
            # New behavior: db_path is primary, playbook_path is legacy
            if db_path is None:
                self.db_path = Path(".claude/playbook.db")
            else:
                self.db_path = Path(db_path)
            self.playbook_path = (
                self.db_path.parent / "playbook.json"
            )  # For migration check only

        # Check if DB exists, if not but JSON exists → migrate
        if not self.db_path.exists() and self.playbook_path.exists():
            print(
                f"First run: migrating {self.playbook_path} to SQLite...",
                file=sys.stderr,
            )
            self._migrate_json_to_sqlite()
        elif not self.db_path.exists():
            # Create new empty database
            self._create_schema()

        # Create SQLite connection with WAL mode for better concurrency
        self.db_conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.db_conn.row_factory = sqlite3.Row
        # Enable WAL mode for better concurrency
        self.db_conn.execute("PRAGMA journal_mode=WAL")
        # Enable foreign key constraints (required for KG schema CASCADE deletes)
        self.db_conn.execute("PRAGMA foreign_keys=ON")

        # Run schema migrations if needed
        self._migrate_schema()

        # Load playbook structure from SQLite for backward compatibility
        self.playbook = self._load_playbook_from_db()

        # Initialize semantic search engine if available
        self.semantic_engine = None
        if use_semantic_search and SEMANTIC_SEARCH_AVAILABLE:
            try:
                self.semantic_engine = SemanticSearchEngine()
                print("✓ Semantic search enabled", file=sys.stderr)
            except Exception as e:
                print(
                    f"Warning: Could not initialize semantic search: {e}",
                    file=sys.stderr,
                )
                print("  Falling back to keyword matching", file=sys.stderr)

        # Lazy initialization for Knowledge Graph query interface
        self._kg_query = None

    @property
    def kg_query(self):
        """
        Lazy-initialized Knowledge Graph query interface.

        Provides access to graph traversal operations (find_paths, get_neighbors,
        entities_since, etc.) without requiring immediate initialization.

        Returns:
            KnowledgeGraphQuery instance

        Example:
            >>> from mapify_cli.playbook_manager import PlaybookManager
            >>> pm = PlaybookManager()
            >>> paths = pm.kg_query.find_paths('ent-pytest', 'ent-python')
            >>> neighbors = pm.kg_query.get_neighbors('ent-pytest', direction='outgoing')
        """
        if self._kg_query is None:
            from mapify_cli.graph_query import KnowledgeGraphQuery

            self._kg_query = KnowledgeGraphQuery(self.db_conn)
        return self._kg_query

    def _create_empty_playbook(self) -> Dict:
        """Create empty playbook structure."""
        return {
            "version": "1.0",
            "metadata": {
                "project": "map-framework",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "total_bullets": 0,
                "sections_count": 10,
                # Phase 1.3: Limit playbook patterns to reduce context distraction and save ~15% tokens
                "top_k": 5,
            },
            "sections": {
                "ARCHITECTURE_PATTERNS": {
                    "description": "Proven architectural decisions",
                    "bullets": [],
                },
                "IMPLEMENTATION_PATTERNS": {
                    "description": "Code patterns for common tasks",
                    "bullets": [],
                },
                "SECURITY_PATTERNS": {
                    "description": "Security best practices",
                    "bullets": [],
                },
                "PERFORMANCE_PATTERNS": {
                    "description": "Optimization techniques",
                    "bullets": [],
                },
                "ERROR_PATTERNS": {
                    "description": "Common errors and solutions",
                    "bullets": [],
                },
                "TESTING_STRATEGIES": {
                    "description": "Test patterns and coverage",
                    "bullets": [],
                },
                "CODE_QUALITY_RULES": {
                    "description": "Style guides and maintainability",
                    "bullets": [],
                },
                "TOOL_USAGE": {
                    "description": "Library and framework usage",
                    "bullets": [],
                },
                "DEBUGGING_TECHNIQUES": {
                    "description": "Troubleshooting workflows",
                    "bullets": [],
                },
                "CLI_TOOL_PATTERNS": {
                    "description": "Patterns for building reliable CLI tools",
                    "bullets": [],
                },
            },
        }

    def _create_schema(self) -> None:
        """Create SQLite schema with FTS5 support."""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        # Main bullets table
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

        # Indexes for fast filtering
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_section ON bullets(section)")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_quality ON bullets(quality_score)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_deprecated ON bullets(deprecated)"
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_created ON bullets(created_at)")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_last_used ON bullets(last_used_at)"
        )

        # Full-text search (FTS5)
        cursor.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS bullets_fts USING fts5(
                content,
                code_example,
                content=bullets,
                content_rowid=rowid,
                tokenize='porter unicode61'
            )
        """
        )

        # Triggers to keep FTS index in sync
        cursor.execute(
            """
            CREATE TRIGGER IF NOT EXISTS bullets_ai AFTER INSERT ON bullets BEGIN
                INSERT INTO bullets_fts(rowid, content, code_example)
                VALUES (new.rowid, new.content, new.code_example);
            END
        """
        )

        cursor.execute(
            """
            CREATE TRIGGER IF NOT EXISTS bullets_ad AFTER DELETE ON bullets BEGIN
                INSERT INTO bullets_fts(bullets_fts, rowid)
                VALUES ('delete', old.rowid);
            END
        """
        )

        cursor.execute(
            """
            CREATE TRIGGER IF NOT EXISTS bullets_au AFTER UPDATE ON bullets BEGIN
                INSERT INTO bullets_fts(bullets_fts, rowid)
                VALUES ('delete', old.rowid);
                INSERT INTO bullets_fts(rowid, content, code_example)
                VALUES (new.rowid, new.content, new.code_example);
            END
        """
        )

        # Metadata table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """
        )

        # Insert default metadata (schema_version will be set by schema_v3.0.sql)
        now = datetime.now(timezone.utc).isoformat()
        cursor.execute("INSERT OR IGNORE INTO metadata VALUES ('version', '1.0')")
        cursor.execute(
            f"INSERT OR IGNORE INTO metadata VALUES ('last_updated', '{now}')"
        )
        cursor.execute("INSERT OR IGNORE INTO metadata VALUES ('total_bullets', '0')")
        cursor.execute("INSERT OR IGNORE INTO metadata VALUES ('top_k', '5')")

        # Add Knowledge Graph tables (schema v3.0)
        # Schema is embedded in code (schemas.py) to ensure availability in packaged installations
        try:
            cursor.executescript(SCHEMA_V3_0_SQL)
            print("✓ Knowledge Graph tables created (schema v3.0)", file=sys.stderr)
        except Exception as e:
            conn.rollback()
            conn.close()
            raise RuntimeError(f"Failed to create Knowledge Graph schema: {e}") from e

        conn.commit()
        conn.close()

    def _migrate_schema(self) -> None:
        """
        Run schema migrations to upgrade database to current version.

        Migrations are idempotent and safe to run multiple times.
        Each migration checks schema_version before applying changes.
        """
        cursor = self.db_conn.cursor()

        # Get current schema version
        cursor.execute("SELECT value FROM metadata WHERE key = 'schema_version'")
        result = cursor.fetchone()
        current_version = (
            result[0] if result else "2.0"
        )  # Default for old DBs without version

        # Migration: 2.0 -> 2.1 (add executable_scripts field)
        if current_version == "2.0":
            print(
                "Migrating schema from 2.0 to 2.1 (adding executable_scripts field)...",
                file=sys.stderr,
            )

            # Check if column already exists (idempotency)
            cursor.execute("PRAGMA table_info(bullets)")
            columns = [row[1] for row in cursor.fetchall()]

            if "executable_scripts" not in columns:
                # Add new column with NULL default (backward compatible)
                cursor.execute("ALTER TABLE bullets ADD COLUMN executable_scripts TEXT")
                print(
                    "✓ Added executable_scripts column to bullets table",
                    file=sys.stderr,
                )
            else:
                print(
                    "✓ executable_scripts column already exists, skipping",
                    file=sys.stderr,
                )

            # Update schema version
            cursor.execute(
                "UPDATE metadata SET value = '2.1' WHERE key = 'schema_version'"
            )
            self.db_conn.commit()
            print("✓ Schema migration complete (2.0 -> 2.1)", file=sys.stderr)
            current_version = "2.1"  # Proceed to next migration if needed

        # Migration: 2.1 -> 3.0 (add Knowledge Graph tables)
        if current_version == "2.1":
            print(
                "Migrating schema from 2.1 to 3.0 (adding Knowledge Graph tables)...",
                file=sys.stderr,
            )

            try:
                # Execute embedded schema SQL (from schemas.py)
                # executescript() operates in autocommit mode and commits after each statement
                # No explicit commit needed here - changes are already committed
                cursor.executescript(SCHEMA_V3_0_SQL)

                # Verify tables were created
                cursor.execute(
                    """
                    SELECT name FROM sqlite_master
                    WHERE type='table' AND name IN ('entities', 'relationships', 'provenance')
                    ORDER BY name
                """
                )
                created_tables = [row[0] for row in cursor.fetchall()]

                if len(created_tables) == 3:
                    print(
                        f"✓ Created KG tables: {', '.join(created_tables)}",
                        file=sys.stderr,
                    )
                else:
                    print(
                        f"⚠ Warning: Expected 3 KG tables, found {len(created_tables)}: {created_tables}",
                        file=sys.stderr,
                    )

                # Verify schema version was updated (schema_v3.0.sql includes this)
                cursor.execute(
                    "SELECT value FROM metadata WHERE key = 'schema_version'"
                )
                new_version = cursor.fetchone()[0]

                if new_version == "3.0":
                    print("✓ Schema migration complete (2.1 -> 3.0)", file=sys.stderr)
                else:
                    raise RuntimeError(
                        f"Schema version not updated correctly. Expected '3.0', got '{new_version}'"
                    )

            except sqlite3.Error as e:
                self.db_conn.rollback()
                raise RuntimeError(
                    f"Failed to execute schema migration SQL: {e}\n"
                    f"\n"
                    f"Recovery steps:\n"
                    f"1. Check error above for root cause (disk space, permissions, etc.)\n"
                    f"2. Fix underlying issue\n"
                    f"3. Restart application - migration will retry safely (uses IF NOT EXISTS guards)\n"
                    f"4. If issue persists, restore from backup: .claude/playbook.db.backup.*\n"
                    f"5. See docs/knowledge_graph/MIGRATION_ROLLBACK.md for detailed rollback instructions"
                ) from e
            except Exception as e:
                self.db_conn.rollback()
                raise RuntimeError(
                    f"Unexpected error during schema migration: {e}\n"
                    f"\n"
                    f"Recovery: Restore from backup (.claude/playbook.db.backup.*) or see MIGRATION_ROLLBACK.md"
                ) from e

        elif current_version == CURRENT_SCHEMA_VERSION:
            # Already at current version, no migration needed
            pass

        else:
            # Future version or unknown version
            print(
                f"Warning: Unknown schema version {current_version}, expected {CURRENT_SCHEMA_VERSION}",
                file=sys.stderr,
            )

    def _migrate_json_to_sqlite(self) -> None:
        """
        Migrate existing playbook.json to SQLite database.

        Steps:
        1. Load playbook.json
        2. Create SQLite schema
        3. Insert all bullets into bullets table
        4. Insert metadata
        5. Create backup of playbook.json
        """
        # Load JSON playbook with corruption handling
        try:
            with open(self.playbook_path, "r", encoding="utf-8") as f:
                playbook = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"Corrupted playbook.json at line {e.lineno}, column {e.colno}: {e.msg}\n"
                f"\n"
                f"Recovery options:\n"
                f"1. Fix the JSON syntax error in {self.playbook_path}\n"
                f"2. Rename playbook.json to playbook.json.backup and run 'mapify init' again\n"
                f"3. Delete playbook.json if you want to start fresh (data will be lost)\n"
                f"\n"
                f"Tip: Validate JSON at https://jsonlint.com/"
            ) from e

        # Create schema
        self._create_schema()

        # Connect to database
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        # Insert bullets (skip duplicates)
        total_bullets = 0
        skipped_duplicates = []
        for section_name, section_data in playbook["sections"].items():
            for bullet in section_data["bullets"]:
                # Handle None values explicitly (dict.get() returns None if key exists with null value)
                now = datetime.now(timezone.utc).isoformat()
                created_at = bullet.get("created_at") or now
                last_used_at = bullet.get("last_used_at") or now

                try:
                    cursor.execute(
                        """
                        INSERT INTO bullets (id, section, content, code_example,
                                              helpful_count, harmful_count,
                                              created_at, last_used_at,
                                              deprecated, deprecation_reason,
                                              tags, related_bullets, executable_scripts)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                        (
                            bullet["id"],
                            section_name,
                            bullet["content"],
                            bullet.get("code_example"),
                            bullet.get("helpful_count", 0),
                            bullet.get("harmful_count", 0),
                            created_at,
                            last_used_at,
                            1 if bullet.get("deprecated", False) else 0,
                            bullet.get("deprecation_reason"),
                            json.dumps(bullet.get("tags", [])),
                            json.dumps(bullet.get("related_bullets", [])),
                            (
                                json.dumps(bullet.get("executable_scripts", []))
                                if bullet.get("executable_scripts")
                                else None
                            ),
                        ),
                    )
                    total_bullets += 1
                except sqlite3.IntegrityError as e:
                    if "UNIQUE constraint failed" in str(e):
                        skipped_duplicates.append(bullet["id"])
                        print(
                            f"Warning: Skipped duplicate bullet {bullet['id']}",
                            file=sys.stderr,
                        )
                    else:
                        raise

        # Update metadata
        metadata = playbook.get("metadata", {})
        cursor.execute(
            "UPDATE metadata SET value = ? WHERE key = 'version'",
            (metadata.get("version", "1.0"),),
        )
        cursor.execute(
            "UPDATE metadata SET value = ? WHERE key = 'last_updated'",
            (metadata.get("last_updated", datetime.now(timezone.utc).isoformat()),),
        )
        cursor.execute(
            "UPDATE metadata SET value = ? WHERE key = 'total_bullets'",
            (str(total_bullets),),
        )
        cursor.execute(
            "UPDATE metadata SET value = ? WHERE key = 'top_k'",
            (str(metadata.get("top_k", 5)),),
        )

        conn.commit()

        # Verify migration
        cursor.execute("SELECT COUNT(*) FROM bullets")
        db_count = cursor.fetchone()[0]

        if db_count != total_bullets:
            conn.close()
            raise ValueError(
                f"Migration failed: {db_count} rows in DB, {total_bullets} in JSON"
            )

        conn.close()

        # Create backup of JSON
        backup_path = (
            str(self.playbook_path)
            + f".backup.{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        )
        shutil.copy(str(self.playbook_path), backup_path)

        print(
            f"✅ Migrated {db_count} bullets from {self.playbook_path} to {self.db_path}",
            file=sys.stderr,
        )
        print(f"✅ JSON backup saved to {backup_path}", file=sys.stderr)

    def _load_playbook_from_db(self) -> Dict:
        """Load playbook structure from SQLite database for backward compatibility."""
        cursor = self.db_conn.cursor()

        # Load metadata
        cursor.execute("SELECT key, value FROM metadata")
        metadata_rows = cursor.fetchall()
        metadata = {row["key"]: row["value"] for row in metadata_rows}

        # Load bullets grouped by section
        cursor.execute(
            """
            SELECT section, id, content, code_example,
                   helpful_count, harmful_count, quality_score,
                   created_at, last_used_at, deprecated, deprecation_reason,
                   tags, related_bullets, executable_scripts
            FROM bullets
            ORDER BY section, quality_score DESC
        """
        )

        sections = {}
        # Initialize all standard sections
        for section_name in [
            "ARCHITECTURE_PATTERNS",
            "IMPLEMENTATION_PATTERNS",
            "SECURITY_PATTERNS",
            "PERFORMANCE_PATTERNS",
            "ERROR_PATTERNS",
            "TESTING_STRATEGIES",
            "CODE_QUALITY_RULES",
            "TOOL_USAGE",
            "DEBUGGING_TECHNIQUES",
            "CLI_TOOL_PATTERNS",
        ]:
            sections[section_name] = {"bullets": []}

        for row in cursor.fetchall():
            section_name = row["section"]
            if section_name not in sections:
                sections[section_name] = {"bullets": []}

            bullet = {
                "id": row["id"],
                "content": row["content"],
                "helpful_count": row["helpful_count"],
                "harmful_count": row["harmful_count"],
                "created_at": row["created_at"],
                "last_used_at": row["last_used_at"],
            }

            if row["code_example"]:
                bullet["code_example"] = row["code_example"]
            if row["deprecated"]:
                bullet["deprecated"] = True
                bullet["deprecation_reason"] = row["deprecation_reason"]
            if row["tags"]:
                bullet["tags"] = json.loads(row["tags"])
            if row["related_bullets"]:
                bullet["related_bullets"] = json.loads(row["related_bullets"])
            if row["executable_scripts"]:
                bullet["executable_scripts"] = json.loads(row["executable_scripts"])

            sections[section_name]["bullets"].append(bullet)

        # Build playbook dict
        playbook = {
            "version": metadata.get("version", "1.0"),
            "metadata": {
                "version": metadata.get("version", "1.0"),
                "last_updated": metadata.get(
                    "last_updated", datetime.now(timezone.utc).isoformat()
                ),
                "total_bullets": int(metadata.get("total_bullets", 0)),
                "sections_count": 10,
                "top_k": int(metadata.get("top_k", 5)),
            },
            "sections": sections,
        }

        return playbook

    def apply_delta(self, operations: List[Dict]) -> Dict:
        """
        Apply incremental delta updates (ACE-style).

        Args:
            operations: List of delta operations from Curator

        Returns:
            Summary of applied operations

        Example:
            operations = [
                {"type": "ADD", "section": "SECURITY_PATTERNS", "content": "..."},
                {"type": "UPDATE", "bullet_id": "sec-0012", "increment_helpful": 1}
            ]
        """
        summary = {"added": 0, "updated": 0, "deprecated": 0, "errors": []}

        for op in operations:
            try:
                op_type = op.get("type")

                if op_type == "ADD":
                    self._add_bullet(
                        section=op["section"],
                        content=op["content"],
                        code_example=op.get("code_example"),
                        related_to=op.get("related_to", []),
                        tags=op.get("tags", []),
                        executable_scripts=op.get("executable_scripts", []),
                    )
                    summary["added"] += 1

                elif op_type == "UPDATE":
                    self._update_bullet(
                        bullet_id=op["bullet_id"],
                        increment_helpful=op.get("increment_helpful", 0),
                        increment_harmful=op.get("increment_harmful", 0),
                    )
                    summary["updated"] += 1

                elif op_type == "DEPRECATE":
                    self._deprecate_bullet(
                        bullet_id=op["bullet_id"],
                        reason=op.get("reason", "Marked as harmful"),
                    )
                    summary["deprecated"] += 1

                else:
                    summary["errors"].append(f"Unknown operation type: {op_type}")

            except Exception as e:
                summary["errors"].append(f"Error applying {op}: {str(e)}")

        # Run deduplication after applying all operations
        if summary["added"] > 0:
            dedup_summary = self._deduplicate()
            summary["deduplicated"] = dedup_summary.get("removed", 0)

        self._save_playbook(self.playbook)
        return summary

    def _add_bullet(
        self,
        section: str,
        content: str,
        code_example: Optional[str] = None,
        related_to: List[str] = None,
        tags: List[str] = None,
        executable_scripts: List[str] = None,
    ) -> str:
        """Add new bullet to section (saves to SQLite)."""
        if section not in self.playbook["sections"]:
            raise ValueError(f"Unknown section: {section}")

        bullet_id = self._generate_id(section)
        now = datetime.now(timezone.utc).isoformat()

        # Insert into SQLite
        cursor = self.db_conn.cursor()
        cursor.execute(
            """
            INSERT INTO bullets (id, section, content, code_example,
                                  helpful_count, harmful_count,
                                  created_at, last_used_at,
                                  deprecated, deprecation_reason,
                                  tags, related_bullets, executable_scripts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                bullet_id,
                section,
                content,
                code_example,
                0,  # helpful_count
                0,  # harmful_count
                now,
                now,
                0,  # deprecated
                None,
                json.dumps(tags or []),
                json.dumps(related_to or []),
                json.dumps(executable_scripts) if executable_scripts else None,
            ),
        )

        # Update metadata
        cursor.execute(
            "UPDATE metadata SET value = CAST((CAST(value AS INTEGER) + 1) AS TEXT) WHERE key = 'total_bullets'"
        )
        cursor.execute(
            "UPDATE metadata SET value = ? WHERE key = 'last_updated'", (now,)
        )

        self.db_conn.commit()

        # Update in-memory playbook for backward compatibility
        bullet = {
            "id": bullet_id,
            "content": content,
            "code_example": code_example,
            "helpful_count": 0,
            "harmful_count": 0,
            "created_at": now,
            "last_used_at": now,
            "related_bullets": related_to or [],
            "tags": tags or [],
            "deprecated": False,
            "deprecation_reason": None,
        }
        if executable_scripts:
            bullet["executable_scripts"] = executable_scripts

        self.playbook["sections"][section]["bullets"].append(bullet)
        self.playbook["metadata"]["total_bullets"] += 1

        return bullet_id

    def _update_bullet(
        self, bullet_id: str, increment_helpful: int = 0, increment_harmful: int = 0
    ) -> bool:
        """Update bullet counters (saves to SQLite)."""
        # Check if bullet exists
        cursor = self.db_conn.cursor()
        cursor.execute(
            "SELECT helpful_count, harmful_count FROM bullets WHERE id = ?",
            (bullet_id,),
        )
        row = cursor.fetchone()

        if not row:
            return False

        now = datetime.now(timezone.utc).isoformat()
        new_helpful = row["helpful_count"] + increment_helpful
        new_harmful = row["harmful_count"] + increment_harmful

        # Update in SQLite
        cursor.execute(
            """
            UPDATE bullets
            SET helpful_count = ?,
                harmful_count = ?,
                last_used_at = ?
            WHERE id = ?
        """,
            (new_helpful, new_harmful, now, bullet_id),
        )

        # Auto-deprecate if harmful_count >= 3
        if new_harmful >= 3:
            cursor.execute(
                """
                UPDATE bullets
                SET deprecated = 1,
                    deprecation_reason = ?
                WHERE id = ? AND deprecated = 0
            """,
                (f"High harmful count ({new_harmful})", bullet_id),
            )

        cursor.execute(
            "UPDATE metadata SET value = ? WHERE key = 'last_updated'", (now,)
        )
        self.db_conn.commit()

        # Update in-memory playbook for backward compatibility
        bullet = self._find_bullet(bullet_id)
        if bullet:
            bullet["helpful_count"] = new_helpful
            bullet["harmful_count"] = new_harmful
            bullet["last_used_at"] = now
            if new_harmful >= 3 and not bullet.get("deprecated", False):
                bullet["deprecated"] = True
                bullet["deprecation_reason"] = f"High harmful count ({new_harmful})"

        return True

    def _deprecate_bullet(self, bullet_id: str, reason: str) -> bool:
        """Mark bullet as deprecated (saves to SQLite)."""
        # Update in SQLite
        cursor = self.db_conn.cursor()
        cursor.execute("SELECT id FROM bullets WHERE id = ?", (bullet_id,))
        if not cursor.fetchone():
            return False

        now = datetime.now(timezone.utc).isoformat()
        cursor.execute(
            """
            UPDATE bullets
            SET deprecated = 1,
                deprecation_reason = ?
            WHERE id = ?
        """,
            (reason, bullet_id),
        )

        cursor.execute(
            "UPDATE metadata SET value = ? WHERE key = 'last_updated'", (now,)
        )
        self.db_conn.commit()

        # Update in-memory playbook for backward compatibility
        bullet = self._find_bullet(bullet_id)
        if bullet:
            bullet["deprecated"] = True
            bullet["deprecation_reason"] = reason

        return True

    def _find_bullet(self, bullet_id: str) -> Optional[Dict]:
        """Find bullet by ID across all sections."""
        for section in self.playbook["sections"].values():
            for bullet in section["bullets"]:
                if bullet["id"] == bullet_id:
                    return bullet
        return None

    def _generate_id(self, section: str) -> str:
        """Generate unique bullet ID."""
        # Extract prefix from section name (first 4 chars, lowercase)
        prefix = re.sub(r"[^a-z]", "", section.lower())[:4]

        # Find max existing ID number in section from SQLite (source of truth)
        cursor = self.db_conn.cursor()
        cursor.execute(
            """
            SELECT id FROM bullets
            WHERE section = ? AND id LIKE ?
            ORDER BY id DESC LIMIT 1
        """,
            (section, f"{prefix}-%"),
        )

        result = cursor.fetchone()
        if result:
            # Extract number from ID like "impl-0042" -> 42
            last_id = result[0]
            try:
                last_num = int(last_id.split("-")[1])
                next_num = last_num + 1
            except (IndexError, ValueError):
                # Fallback to count if ID format is unexpected
                cursor.execute(
                    "SELECT COUNT(*) FROM bullets WHERE section = ?", (section,)
                )
                next_num = cursor.fetchone()[0]
        else:
            next_num = 0

        return f"{prefix}-{next_num:04d}"

    def _deduplicate(self, threshold: float = 0.9) -> Dict:
        """
        Remove semantic duplicates using semantic similarity or content comparison.

        Uses semantic search if available, otherwise falls back to exact matching.

        Args:
            threshold: Similarity threshold for duplicates (0.9 = 90% similar)

        Returns:
            Summary dict with removed/merged counts
        """
        summary = {"removed": 0, "merged": 0}

        for section_name, section in self.playbook["sections"].items():
            bullets = section["bullets"]

            if not bullets:
                continue

            # Use semantic deduplication if available
            if self.semantic_engine:
                unique_bullets, duplicates = self.semantic_engine.deduplicate_bullets(
                    bullets, threshold=threshold
                )

                # Merge counters from duplicates into originals
                for idx1, idx2, similarity in duplicates:
                    bullets[idx1]["helpful_count"] += bullets[idx2]["helpful_count"]
                    bullets[idx1]["harmful_count"] += bullets[idx2]["harmful_count"]
                    summary["merged"] += 1

                # Replace section bullets with unique ones
                section["bullets"] = unique_bullets
                summary["removed"] += len(bullets) - len(unique_bullets)
                self.playbook["metadata"]["total_bullets"] -= len(bullets) - len(
                    unique_bullets
                )

            else:
                # Fallback: exact content hash matching
                seen_content = {}
                to_remove = []

                for i, bullet in enumerate(bullets):
                    content_hash = hashlib.md5(bullet["content"].encode()).hexdigest()

                    if content_hash in seen_content:
                        # Duplicate found - merge counters
                        orig_idx = seen_content[content_hash]
                        bullets[orig_idx]["helpful_count"] += bullet["helpful_count"]
                        bullets[orig_idx]["harmful_count"] += bullet["harmful_count"]
                        to_remove.append(i)
                        summary["merged"] += 1
                    else:
                        seen_content[content_hash] = i

                # Remove duplicates (reverse order to preserve indices)
                for idx in reversed(to_remove):
                    bullets.pop(idx)
                    summary["removed"] += 1
                    self.playbook["metadata"]["total_bullets"] -= 1

        return summary

    def get_relevant_bullets(
        self,
        query: str,
        limit: Optional[int] = None,
        min_quality_score: int = 0,
        similarity_threshold: float = 0.3,
    ) -> List[Dict]:
        """
        Retrieve relevant bullets for Actor context.

        BACKWARD COMPATIBLE: This method wraps the new query() API
        to maintain compatibility with existing code.

        Args:
            query: Task description or keywords
            limit: Maximum bullets to return (defaults to playbook metadata top_k)
            min_quality_score: Minimum (helpful - harmful) score
            similarity_threshold: Minimum semantic similarity (0-1, only for semantic search)

        Returns:
            List of bullet dicts sorted by relevance and quality score
        """
        # Create PlaybookQuery from params
        params = PlaybookQuery(
            query=query,
            limit=limit,
            min_quality_score=min_quality_score,
            similarity_threshold=similarity_threshold,
            sections=None,  # Search all sections
            exclude_deprecated=True,
            search_mode=SearchMode.PLAYBOOK_ONLY,
            fts_prefix=True,
        )

        # Call new query() method
        response = self.query(params)

        # Convert PlaybookResult objects to dict format (backward compatible)
        return [
            {
                "id": r.id,
                "content": r.content,
                "code_example": r.code_example,
                "helpful_count": r.helpful_count,
                "harmful_count": r.harmful_count,
                "quality_score": r.quality_score,
                "related_bullets": r.related_bullets,
                "tags": r.tags,
                "created_at": r.created_at,
                "last_used_at": r.last_used_at,
            }
            for r in response.results
        ]

    def _calculate_relevance(self, query: str, bullet: Dict) -> float:
        """
        Calculate relevance score (placeholder).

        TODO: Replace with semantic similarity using embeddings.
        """
        query_lower = query.lower()
        content_lower = bullet["content"].lower()

        # Count keyword matches
        query_words = set(re.findall(r"\w+", query_lower))
        content_words = set(re.findall(r"\w+", content_lower))

        if not query_words:
            return 0.0

        matches = query_words & content_words
        return len(matches) / len(query_words)

    def get_bullets_for_sync(self, threshold: int = 5) -> List[Dict]:
        """Get high-quality bullets for syncing to cipher."""
        sync_bullets = []

        for section_name, section in self.playbook["sections"].items():
            for bullet in section["bullets"]:
                if bullet.get("deprecated", False):
                    continue

                quality_score = bullet.get("helpful_count", 0) - bullet.get(
                    "harmful_count", 0
                )

                if quality_score >= threshold:
                    sync_bullets.append({"section": section_name, **bullet})

        return sync_bullets

    def _save_playbook(self, playbook: Optional[Dict] = None) -> None:
        """
        Save playbook metadata to SQLite.

        Note: Individual bullet operations are saved immediately via
        _add_bullet, _update_bullet, _deprecate_bullet. This method
        just updates the last_updated timestamp.
        """
        now = datetime.now(timezone.utc).isoformat()
        cursor = self.db_conn.cursor()
        cursor.execute(
            "UPDATE metadata SET value = ? WHERE key = 'last_updated'", (now,)
        )
        self.db_conn.commit()

        # Update in-memory playbook
        if playbook is None:
            playbook = self.playbook
        playbook["metadata"]["last_updated"] = now

    def query(self, params: PlaybookQuery) -> PlaybookQueryResponse:
        """
        Query playbook using SQLite FTS5 and optional semantic search.

        Execution strategy:
        1. Stage 1: Query cipher (if HYBRID or CIPHER_ONLY)
        2. Stage 2: Query local playbook (if HYBRID or PLAYBOOK_ONLY)
        3. Stage 3: Merge and deduplicate results (>85% similarity = duplicate)
        4. Calculate combined scores (quality * 0.3 + relevance * 0.7)
        5. Sort by combined score
        6. Return top-k results

        Performance (270KB playbook, 111 bullets):
        - FTS5 query: <50ms (indexed search)
        - Semantic re-ranking: <100ms (if enabled)
        - Cipher query: <200ms (parallel, network latency)
        - Sorting/limiting: <20ms
        - Total: <200ms (local only), <400ms (with cipher)

        Args:
            params: PlaybookQuery with search parameters

        Returns:
            PlaybookQueryResponse with results and metadata
        """
        start_time = time.time()

        # Get limit from params or use playbook default top_k
        limit = (
            params.limit
            if params.limit is not None
            else self.playbook["metadata"]["top_k"]
        )

        # Stage 1: Query cipher (if HYBRID or CIPHER_ONLY)
        cipher_results = []
        cipher_time_ms = 0
        if params.search_mode in (SearchMode.CIPHER_ONLY, SearchMode.HYBRID):
            cipher_start = time.time()
            cipher_results = self._query_cipher(params.query, limit)
            cipher_time_ms = int((time.time() - cipher_start) * 1000)

        # Stage 2: Query local playbook (if HYBRID or PLAYBOOK_ONLY)
        playbook_results = []
        playbook_time_ms = 0
        if params.search_mode in (SearchMode.PLAYBOOK_ONLY, SearchMode.HYBRID):
            playbook_start = time.time()

            # Build and execute FTS5 SQL query
            sql, sql_params = self._build_fts_query(params, limit)
            cursor = self.db_conn.cursor()
            cursor.execute(sql, sql_params)
            rows = cursor.fetchall()

            # Convert rows to PlaybookResult objects
            for row in rows:
                # Calculate relevance from FTS5 rank (normalize to 0-1 range)
                # FTS5 rank is negative (closer to 0 = more relevant)
                relevance_score = 1.0 / (1.0 + abs(row["fts_rank"]))

                result = PlaybookResult(
                    id=row["id"],
                    section=row["section"],
                    content=row["content"],
                    code_example=row["code_example"],
                    helpful_count=row["helpful_count"],
                    harmful_count=row["harmful_count"],
                    quality_score=row["quality_score"],
                    relevance_score=relevance_score,
                    source="playbook",
                    combined_score=0.0,  # Will be calculated below
                    related_bullets=(
                        json.loads(row["related_bullets"])
                        if row["related_bullets"]
                        else []
                    ),
                    tags=json.loads(row["tags"]) if row["tags"] else [],
                    created_at=row["created_at"],
                    last_used_at=row["last_used_at"],
                )
                playbook_results.append(result)

            # Optional: Semantic re-ranking if semantic engine available
            if self.semantic_engine and len(playbook_results) > 0:
                playbook_results = self._semantic_rerank(
                    params.query, playbook_results, params.similarity_threshold
                )

            playbook_time_ms = int((time.time() - playbook_start) * 1000)

        # Stage 3: Merge and deduplicate results
        merged_results = self._merge_results(cipher_results, playbook_results)

        # Calculate combined scores: relevance * 0.7 + quality * 0.3
        # Quality normalized to 0-1 range (assuming quality_score typically 0-10)
        for result in merged_results:
            quality_normalized = max(
                0.0, min(1.0, result.quality_score / QUALITY_SCORE_MAX)
            )
            result.combined_score = (
                result.relevance_score * RELEVANCE_WEIGHT
                + quality_normalized * QUALITY_WEIGHT
            )

        # Sort by combined score
        merged_results.sort(key=lambda r: r.combined_score, reverse=True)

        # Limit results
        merged_results = merged_results[:limit]

        total_time_ms = int((time.time() - start_time) * 1000)

        # Build metadata
        sections_searched = params.sections if params.sections else list(VALID_SECTIONS)
        search_method = "fts5"
        if self.semantic_engine and params.search_mode != SearchMode.CIPHER_ONLY:
            search_method = "fts5+semantic"

        dedup_count = len(cipher_results) + len(playbook_results) - len(merged_results)

        return PlaybookQueryResponse(
            results=merged_results,
            metadata={
                "total_candidates": len(cipher_results) + len(playbook_results),
                "total_time_ms": total_time_ms,
                "cipher_time_ms": cipher_time_ms if cipher_results else 0,
                "playbook_time_ms": playbook_time_ms if playbook_results else 0,
                "search_time_ms": total_time_ms,  # For backward compatibility
                "search_method": search_method,
                "cipher_results_count": len(cipher_results),
                "playbook_results_count": len(playbook_results),
                "cipher_results": len(cipher_results),  # For backward compatibility
                "playbook_results": len(merged_results),  # For backward compatibility
                "deduplicated_count": dedup_count,
                "search_mode": params.search_mode.value,
                "sections_searched": sections_searched,
            },
        )

    def _build_fts_query(self, params: PlaybookQuery, limit: int) -> Tuple[str, List]:
        """
        Build parameterized SQL query with FTS5 and filters.

        Args:
            params: PlaybookQuery with search parameters
            limit: Result limit

        Returns:
            (sql_string, parameters)
        """
        # Sanitize query for FTS5 (remove special characters that cause syntax errors)

        fts_query = params.query

        # FTS5 tokenizer splits hyphens at index time ("session-start" → ["session", "start"])
        # Align query tokenization by replacing hyphens with spaces
        fts_query = fts_query.replace("-", " ")

        # Remove FTS5 special characters: @ # ( ) " ' :
        fts_special_chars = "@#()\"':"
        for char in fts_special_chars:
            fts_query = fts_query.replace(char, " ")

        # Convert to FTS5 format (add prefix matching if enabled)
        if params.fts_prefix:
            # Convert "JWT auth" to "JWT* auth*" for prefix matching
            # Keep words >= 2 chars to avoid FTS5 errors with single-char tokens
            words = fts_query.split()
            fts_query = " ".join([f"{word}*" for word in words if len(word) >= 2])

        # If query becomes empty after sanitization, fall back to original
        if not fts_query.strip():
            fts_query = params.query

        sql_parts = [
            "SELECT b.id, b.section, b.content, b.code_example,",
            "       b.helpful_count, b.harmful_count, b.quality_score,",
            "       b.created_at, b.last_used_at, b.tags, b.related_bullets,",
            "       fts.rank AS fts_rank",
            "FROM bullets b",
            "JOIN bullets_fts fts ON b.rowid = fts.rowid",
            "WHERE fts.bullets_fts MATCH ?",
        ]
        sql_params = [fts_query]

        # Section filter
        if params.sections:
            placeholders = ",".join("?" * len(params.sections))
            sql_parts.append(f"AND b.section IN ({placeholders})")
            sql_params.extend(params.sections)

        # Quality filter
        sql_parts.append("AND b.quality_score >= ?")
        sql_params.append(params.min_quality_score)

        # Deprecated filter
        if params.exclude_deprecated:
            sql_parts.append("AND b.deprecated = 0")

        # Order by FTS rank (negative values, lower = better)
        sql_parts.append("ORDER BY fts.rank")

        # Limit (over-fetch for semantic re-ranking if available)
        if self.semantic_engine:
            over_fetch_limit = limit * 2
        else:
            over_fetch_limit = limit

        sql_parts.append(f"LIMIT {over_fetch_limit}")

        return ("\n".join(sql_parts), sql_params)

    def _semantic_rerank(
        self, query: str, results: List[PlaybookResult], threshold: float
    ) -> List[PlaybookResult]:
        """
        Re-rank results using semantic similarity.

        Args:
            query: Search query
            results: Initial FTS5 results
            threshold: Minimum similarity threshold

        Returns:
            Re-ranked results with updated relevance_score
        """
        # Convert results to bullet format for semantic engine
        bullets = [
            {
                "id": r.id,
                "content": r.content,
                "code_example": r.code_example,
                "quality_score": r.quality_score,
            }
            for r in results
        ]

        # Find semantically similar bullets
        similar_results = self.semantic_engine.find_similar(
            query=query,
            bullets=bullets,
            top_k=len(bullets),  # Rank all candidates
            threshold=threshold,
        )

        # Update relevance scores based on semantic similarity
        similarity_map = {
            bullet["id"]: similarity for bullet, similarity in similar_results
        }

        for result in results:
            if result.id in similarity_map:
                # Combine FTS score with semantic similarity
                fts_score = result.relevance_score
                semantic_score = similarity_map[result.id]
                # Weighted average: 50% FTS, 50% semantic
                result.relevance_score = (fts_score * 0.5) + (semantic_score * 0.5)
            # If not in similarity_map, keep original FTS score

        return results

    def _query_cipher(self, query: str, limit: int) -> List[PlaybookResult]:
        """
        Query cipher MCP for cross-project patterns.

        This method integrates with the cipher memory system via the
        mcp__cipher__cipher_memory_search MCP tool. When running in a
        Claude environment with MCP enabled, this provides access to
        cross-project knowledge patterns.

        Args:
            query: Search query
            limit: Maximum results to return

        Returns:
            List of PlaybookResult objects from cipher (source='cipher')

        Graceful degradation:
        - If MCP not available: returns empty list
        - If cipher times out: returns empty list (5s timeout)
        - If connection error: returns empty list

        Note: This method is designed to be called by MAP agents running
        in Claude. For standalone Python usage, cipher results will be
        empty unless a custom cipher backend is provided.
        """
        try:
            # Check if cipher callback is registered (for testing/custom backends)
            if hasattr(self, "_cipher_callback") and callable(self._cipher_callback):
                raw_results = self._cipher_callback(query=query, top_k=limit)
            else:
                # In production, this would be called via MCP tool invocation
                # by Claude's orchestration layer. For library usage without
                # MCP, return empty results gracefully.
                return []

            # Convert cipher results to PlaybookResult format
            results = []
            for item in raw_results:
                # Handle different result formats from cipher
                text = item.get("text") or item.get("content", "")
                item_id = item.get("id", hash(text))
                similarity = item.get("similarity", 0.5)

                cipher_id = f"cipher-{item_id}"

                result = PlaybookResult(
                    id=cipher_id,
                    section="CIPHER",
                    content=text,
                    code_example=None,
                    helpful_count=0,
                    harmful_count=0,
                    quality_score=0,
                    relevance_score=similarity,
                    source="cipher",
                    combined_score=0.0,  # Will be calculated later
                    related_bullets=[],
                    tags=item.get("tags", []),
                    created_at="",
                    last_used_at="",
                )
                results.append(result)

            return results

        except (TimeoutError, ConnectionError) as e:
            # Graceful degradation: cipher unavailable, continue with local
            print(
                f"Warning: Cipher query failed: {e}, using local playbook only",
                file=sys.stderr,
            )
            return []
        except Exception as e:
            # Catch-all for any other errors
            print(
                f"Warning: Unexpected cipher error: {e}, using local playbook only",
                file=sys.stderr,
            )
            return []

    def set_cipher_callback(self, callback):
        """
        Set a custom cipher query callback for testing or custom backends.

        Args:
            callback: Function with signature: callback(query: str, top_k: int) -> List[Dict]
                      Should return list of dicts with keys: text, id, similarity, tags

        Example:
            def mock_cipher(query, top_k):
                return [{'text': 'Mock result', 'id': 1, 'similarity': 0.9, 'tags': []}]

            manager.set_cipher_callback(mock_cipher)
        """
        self._cipher_callback = callback

    def _merge_results(
        self,
        cipher_results: List[PlaybookResult],
        playbook_results: List[PlaybookResult],
        similarity_threshold: float = 0.85,
    ) -> List[PlaybookResult]:
        """
        Merge and deduplicate cipher + playbook results.

        Deduplication strategy:
        - If cipher result and playbook result have >85% similarity,
          keep playbook version (project-specific context wins)
        - Add unique cipher results to merged list

        Args:
            cipher_results: Results from cipher query
            playbook_results: Results from local playbook query
            similarity_threshold: Threshold for considering results duplicates (default: 0.85)

        Returns:
            Merged and deduplicated list of PlaybookResult
        """
        if not cipher_results:
            return playbook_results

        if not playbook_results:
            return cipher_results

        # Start with all playbook results (local wins)
        merged = list(playbook_results)

        # Check each cipher result for duplicates with playbook
        for cipher_result in cipher_results:
            is_duplicate = False

            # Compare with all playbook results
            for playbook_result in playbook_results:
                similarity = self._calculate_text_similarity(
                    cipher_result.content, playbook_result.content
                )

                if similarity > similarity_threshold:
                    # Found duplicate - skip cipher result (playbook wins)
                    is_duplicate = True
                    break

            # Only add cipher result if it's unique
            if not is_duplicate:
                merged.append(cipher_result)

        return merged

    def _calculate_text_similarity(self, text1: str, text2: str) -> float:
        """
        Calculate text similarity using simple token overlap (Jaccard similarity).

        For production: use semantic similarity if available.

        Args:
            text1: First text
            text2: Second text

        Returns:
            Similarity score (0.0-1.0)
        """
        # Use semantic engine if available for better similarity
        if self.semantic_engine:
            try:
                # Create dummy bullets for comparison
                bullets = [{"id": "1", "content": text1}, {"id": "2", "content": text2}]
                similar = self.semantic_engine.find_similar(
                    query=text1, bullets=bullets, top_k=2, threshold=0.0
                )
                # Find similarity for text2
                for bullet, sim in similar:
                    if bullet["id"] == "2":
                        return sim
            except Exception:
                pass  # Fall back to simple method

        # Simple token-based similarity (Jaccard)
        tokens1 = set(text1.lower().split())
        tokens2 = set(text2.lower().split())

        if not tokens1 or not tokens2:
            return 0.0

        intersection = tokens1 & tokens2
        union = tokens1 | tokens2

        return len(intersection) / len(union) if union else 0.0

    def export_for_actor(self, bullets: List[Dict]) -> str:
        """
        Format bullets for Actor context.

        Returns markdown-formatted playbook excerpt.
        """
        if not bullets:
            return "No relevant patterns found in playbook."

        output = "# PLAYBOOK CONTEXT\n\n"
        output += "Relevant patterns from past successful implementations:\n\n"

        for bullet in bullets:
            output += f"## [{bullet['id']}] Quality: {bullet['quality_score']}\n\n"
            output += f"{bullet['content']}\n\n"

            if bullet.get("code_example"):
                output += f"{bullet['code_example']}\n\n"

            if bullet.get("related_bullets"):
                output += f"*Related: {', '.join(bullet['related_bullets'])}*\n\n"

            output += "---\n\n"

        return output

    def close(self) -> None:
        """Close database connection."""
        if hasattr(self, "db_conn") and self.db_conn:
            self.db_conn.close()

    def __del__(self):
        """Cleanup database connection on object destruction."""
        self.close()


# CLI interface for testing
if __name__ == "__main__":
    import sys

    manager = PlaybookManager()

    if len(sys.argv) > 1:
        command = sys.argv[1]

        if command == "stats":
            print(json.dumps(manager.playbook["metadata"], indent=2))

        elif command == "search":
            if len(sys.argv) < 3:
                print("Usage: playbook_manager.py search <query>")
                sys.exit(1)

            query = " ".join(sys.argv[2:])
            bullets = manager.get_relevant_bullets(query, limit=5)
            print(manager.export_for_actor(bullets))

        elif command == "sync":
            bullets = manager.get_bullets_for_sync(threshold=5)
            print(f"Found {len(bullets)} bullets ready for cipher sync:")
            for b in bullets:
                print(f"  - [{b['id']}] {b['content'][:80]}...")

    else:
        print("Usage: playbook_manager.py {stats|search|sync}")
