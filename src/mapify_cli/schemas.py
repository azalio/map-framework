"""
SQLite schema definitions for MAP Framework playbook database.

These schemas are embedded in code to ensure they're available
in packaged installations (uv tool install, pip install).
"""

# Schema v3.0: Knowledge Graph Extension
# Adds entities, relationships, and provenance tables to playbook.db
SCHEMA_V3_0_SQL = """
-- Knowledge Graph Schema Extension v3.0
-- Adds entity-relationship graph capabilities to playbook.db
-- Compatible with existing bullets table (schema v2.1)
-- Migration target: v2.1 -> v3.0
--
-- IMPORTANT: Requires PRAGMA foreign_keys=ON (enforced by playbook_manager.py)
-- This ensures ON DELETE CASCADE behavior works correctly.

-- ============================================================================
-- ENTITIES TABLE
-- ============================================================================
-- Stores nodes in the knowledge graph (tools, patterns, concepts, etc.)

CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,  -- Format: 'ent-{uuid}' or 'ent-{semantic-slug}'
    type TEXT NOT NULL CHECK(type IN (
        'TOOL',          -- CLI tools, libraries, frameworks (e.g., 'pytest', 'SQLite', 'FTS5')
        'PATTERN',       -- Implementation patterns (e.g., 'retry-with-backoff', 'feature-flag')
        'CONCEPT',       -- Abstract ideas (e.g., 'idempotency', 'eventual-consistency')
        'ERROR_TYPE',    -- Error categories (e.g., 'race-condition', 'null-pointer')
        'TECHNOLOGY',    -- Tech stack components (e.g., 'Python', 'Docker', 'CI/CD')
        'WORKFLOW',      -- Process patterns (e.g., 'MAP-debugging', 'TDD-cycle')
        'ANTIPATTERN'    -- Known bad practices (e.g., 'generic-exception-catch')
    )),
    name TEXT NOT NULL,  -- Human-readable name (e.g., 'Exponential Backoff Pattern')

    -- Temporal tracking
    first_seen_at TEXT NOT NULL,  -- ISO8601 timestamp of first extraction
    last_seen_at TEXT NOT NULL,   -- ISO8601 timestamp of last mention (updated on re-extraction)

    -- Quality metrics
    confidence REAL NOT NULL DEFAULT 0.8 CHECK(confidence >= 0.0 AND confidence <= 1.0),

    -- Extensibility
    metadata TEXT,  -- JSON blob for entity-specific attributes

    created_at TEXT NOT NULL,  -- Record creation timestamp
    updated_at TEXT NOT NULL   -- Last modification timestamp
);

-- Indexes for fast entity queries
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type);
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name COLLATE NOCASE);  -- Case-insensitive search
CREATE INDEX IF NOT EXISTS idx_entities_confidence ON entities(confidence DESC);
CREATE INDEX IF NOT EXISTS idx_entities_last_seen ON entities(last_seen_at DESC);

-- Full-text search on entity names (for fuzzy matching)
CREATE VIRTUAL TABLE IF NOT EXISTS entities_fts USING fts5(
    name,
    metadata,
    content=entities,
    content_rowid=rowid,
    tokenize='porter unicode61'
);

-- FTS sync triggers
CREATE TRIGGER IF NOT EXISTS entities_ai AFTER INSERT ON entities BEGIN
    INSERT INTO entities_fts(rowid, name, metadata)
    VALUES (new.rowid, new.name, new.metadata);
END;

CREATE TRIGGER IF NOT EXISTS entities_ad AFTER DELETE ON entities BEGIN
    INSERT INTO entities_fts(entities_fts, rowid)
    VALUES ('delete', old.rowid);
END;

CREATE TRIGGER IF NOT EXISTS entities_au AFTER UPDATE ON entities BEGIN
    INSERT INTO entities_fts(entities_fts, rowid)
    VALUES ('delete', old.rowid);
    INSERT INTO entities_fts(rowid, name, metadata)
    VALUES (new.rowid, new.name, new.metadata);
END;


-- ============================================================================
-- RELATIONSHIPS TABLE
-- ============================================================================
-- Stores edges in the knowledge graph (how entities relate to each other)

CREATE TABLE IF NOT EXISTS relationships (
    id TEXT PRIMARY KEY,  -- Format: 'rel-{uuid}'

    -- Graph structure
    source_entity_id TEXT NOT NULL,
    target_entity_id TEXT NOT NULL,

    type TEXT NOT NULL CHECK(type IN (
        'USES',          -- Entity A uses Entity B (e.g., 'pytest' USES 'Python')
        'DEPENDS_ON',    -- A depends on B (e.g., 'MAP-workflow' DEPENDS_ON 'playbook.db')
        'CONTRADICTS',   -- A contradicts B (e.g., 'generic-exception' CONTRADICTS 'specific-exceptions')
        'SUPERSEDES',    -- A replaces B (e.g., 'playbook.db' SUPERSEDES 'playbook.json')
        'RELATED_TO',    -- Generic relationship (fallback)
        'IMPLEMENTS',    -- A implements pattern B (e.g., 'retry-logic' IMPLEMENTS 'resilience-pattern')
        'CAUSES',        -- A causes B (e.g., 'race-condition' CAUSES 'data-corruption')
        'PREVENTS',      -- A prevents B (e.g., 'mutex-lock' PREVENTS 'race-condition')
        'ALTERNATIVE_TO' -- A is alternative to B (e.g., 'JSON-storage' ALTERNATIVE_TO 'SQLite-storage')
    )),

    -- Provenance (which bullet mentioned this relationship)
    created_from_bullet_id TEXT NOT NULL,

    -- Quality metrics
    confidence REAL NOT NULL DEFAULT 0.8 CHECK(confidence >= 0.0 AND confidence <= 1.0),

    -- Extensibility
    metadata TEXT,  -- JSON blob for relationship-specific context

    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    -- Foreign key constraints with CASCADE delete
    FOREIGN KEY (source_entity_id) REFERENCES entities(id) ON DELETE CASCADE,
    FOREIGN KEY (target_entity_id) REFERENCES entities(id) ON DELETE CASCADE,
    FOREIGN KEY (created_from_bullet_id) REFERENCES bullets(id) ON DELETE CASCADE,

    -- Prevent duplicate relationships (same source+target+type)
    UNIQUE(source_entity_id, target_entity_id, type)
);

-- Indexes for fast graph traversal
CREATE INDEX IF NOT EXISTS idx_rel_source ON relationships(source_entity_id, type);
CREATE INDEX IF NOT EXISTS idx_rel_target ON relationships(target_entity_id, type);
CREATE INDEX IF NOT EXISTS idx_rel_type ON relationships(type);
CREATE INDEX IF NOT EXISTS idx_rel_confidence ON relationships(confidence DESC);
CREATE INDEX IF NOT EXISTS idx_rel_bullet ON relationships(created_from_bullet_id);

-- Composite index for bidirectional graph traversal
CREATE INDEX IF NOT EXISTS idx_rel_bidirectional ON relationships(source_entity_id, target_entity_id);


-- ============================================================================
-- PROVENANCE TABLE
-- ============================================================================
-- Tracks which bullets contributed to which entities/relationships

CREATE TABLE IF NOT EXISTS provenance (
    id TEXT PRIMARY KEY,  -- Format: 'prov-{uuid}'

    -- What was extracted
    entity_id TEXT,  -- NULL if this provenance is for a relationship
    relationship_id TEXT,  -- NULL if this provenance is for an entity

    -- Where it came from
    source_bullet_id TEXT NOT NULL,

    -- How it was extracted
    extraction_method TEXT NOT NULL CHECK(extraction_method IN (
        'MANUAL',        -- Human curator explicitly tagged
        'NLP_REGEX',     -- Pattern matching / regex
        'LLM_GPT4',      -- GPT-4 based extraction
        'LLM_CLAUDE',    -- Claude based extraction
        'RULE_BASED'     -- Heuristic rules (e.g., "code_example mentions 'pytest' -> TOOL entity")
    )),

    extraction_confidence REAL NOT NULL DEFAULT 0.8 CHECK(extraction_confidence >= 0.0 AND extraction_confidence <= 1.0),

    extracted_at TEXT NOT NULL,  -- When extraction occurred

    -- Extensibility
    metadata TEXT,  -- JSON for extraction-specific context

    FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE,
    FOREIGN KEY (relationship_id) REFERENCES relationships(id) ON DELETE CASCADE,
    FOREIGN KEY (source_bullet_id) REFERENCES bullets(id) ON DELETE CASCADE,

    -- Constraint: exactly one of entity_id or relationship_id must be non-null
    CHECK((entity_id IS NOT NULL AND relationship_id IS NULL) OR
          (entity_id IS NULL AND relationship_id IS NOT NULL))
);

-- Indexes for provenance queries
CREATE INDEX IF NOT EXISTS idx_prov_entity ON provenance(entity_id);
CREATE INDEX IF NOT EXISTS idx_prov_relationship ON provenance(relationship_id);
CREATE INDEX IF NOT EXISTS idx_prov_bullet ON provenance(source_bullet_id);
CREATE INDEX IF NOT EXISTS idx_prov_method ON provenance(extraction_method);
CREATE INDEX IF NOT EXISTS idx_prov_extracted_at ON provenance(extracted_at DESC);


-- ============================================================================
-- METADATA UPDATES
-- ============================================================================
-- Update schema version to 3.0 (must use REPLACE to update existing value)
INSERT OR REPLACE INTO metadata (key, value) VALUES ('schema_version', '3.0');
-- Preserve existing settings if already set (use IGNORE to avoid overwriting)
INSERT OR IGNORE INTO metadata (key, value) VALUES ('kg_enabled', '1');
INSERT OR IGNORE INTO metadata (key, value) VALUES ('last_kg_extraction', NULL);
"""
