# Knowledge Graph Schema Migration Guide: v2.1 → v3.0

## Overview

This guide explains the automatic migration from Playbook Schema v2.1 (JSON-based patterns) to v3.0 (Knowledge Graph with structured entity/relationship extraction).

**Migration Status**: ✅ AUTOMATIC (handled by `PlaybookManager`)

**Data Loss Risk**: ❌ NONE (migration only adds tables, never modifies/deletes existing data)

---

## What's New in v3.0?

### Structural Changes

1. **New Tables** (4 additions):
   - `entities`: Knowledge entities (tools, patterns, concepts, etc.)
   - `relationships`: Typed relationships between entities
   - `provenance`: Tracks extraction sources (which bullet → which entity)
   - `entities_fts`: Full-text search index (FTS5 virtual table)

2. **New Metadata Keys**:
   - `schema_version`: Updated from `'2.1'` to `'3.0'`
   - `kg_enabled`: Set to `'1'` (Knowledge Graph enabled)
   - `last_kg_extraction`: ISO8601 timestamp of last extraction run

3. **Backward Compatibility**:
   - ✅ `bullets` table unchanged (same structure as v2.1)
   - ✅ Existing playbook data preserved
   - ✅ v2.1 queries continue to work
   - ✅ CLI commands remain compatible

---

## Automatic Migration Process

### When Does Migration Run?

Migration triggers automatically when:
- You upgrade to MAP Framework v1.3.0+ (or any version with KG support)
- `PlaybookManager` initializes
- Database schema version is `< 3.0`

### Migration Steps (Internal)

The migration happens in `PlaybookManager._migrate_schema()`:

```python
# 1. Check current schema version
current_version = metadata.get('schema_version', '1.0')

# 2. If version < 3.0, run migration
if current_version in ['2.0', '2.1']:
    # 3. Execute schema_v3.0.sql
    db_conn.executescript(SCHEMA_V3_0_SQL)

    # 4. Update metadata
    db_conn.execute("UPDATE metadata SET value='3.0' WHERE key='schema_version'")
    db_conn.execute("INSERT OR REPLACE INTO metadata (key, value) VALUES ('kg_enabled', '1')")

    # 5. Commit transaction
    db_conn.commit()
```

**Migration Time**: <1 second (idempotent, uses `CREATE TABLE IF NOT EXISTS`)

---

## Pre-Migration Checklist

### Before Upgrading to v1.3.0+

1. **Backup Your Database** (recommended but optional):
   ```bash
   cp .claude/playbook.db .claude/playbook.db.backup-$(date +%Y%m%d)
   ```

2. **Verify Current Schema Version**:
   ```bash
   sqlite3 .claude/playbook.db "SELECT value FROM metadata WHERE key='schema_version';"
   # Expected: 2.1 or 2.0
   ```

3. **Check Disk Space** (minimal requirement):
   ```bash
   du -h .claude/playbook.db
   # Expected increase after migration: +5-10KB (empty KG tables)
   ```

4. **Close Claude Code** (optional, prevents file locks):
   ```bash
   # Close all Claude Code windows using this project
   ```

---

## Post-Migration Verification

### Verify Migration Success

Run these commands after upgrading:

```bash
# 1. Check schema version
sqlite3 .claude/playbook.db "SELECT value FROM metadata WHERE key='schema_version';"
# Expected output: 3.0

# 2. Verify KG tables exist
sqlite3 .claude/playbook.db ".tables" | grep -E '(entities|relationships|provenance)'
# Expected output: entities  provenance  relationships

# 3. Verify FTS5 table exists
sqlite3 .claude/playbook.db "SELECT name FROM sqlite_master WHERE type='table' AND name='entities_fts';"
# Expected output: entities_fts

# 4. Check KG enabled flag
sqlite3 .claude/playbook.db "SELECT value FROM metadata WHERE key='kg_enabled';"
# Expected output: 1

# 5. Verify foreign key enforcement
sqlite3 .claude/playbook.db "PRAGMA foreign_keys;"
# Expected output: 1

# 6. Count existing bullets (should be unchanged)
sqlite3 .claude/playbook.db "SELECT COUNT(*) FROM bullets;"
# Expected output: (your previous bullet count, unchanged)
```

### Test KG Functionality

After migration, test Knowledge Graph features:

```python
from mapify_cli.playbook_manager import PlaybookManager

# Initialize playbook manager (should auto-detect v3.0)
pm = PlaybookManager(db_path=".claude/playbook.db")

# Verify schema version
print(pm.db_conn.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0])
# Expected: 3.0

# Test entity extraction
from mapify_cli.entity_extractor import extract_entities
entities = extract_entities("Use pytest for testing Python applications")
print(f"Extracted {len(entities)} entities")
# Expected: 2-3 entities (pytest, Python, testing)

# Test KG query interface
kg_query = pm.kg_query
tools = kg_query.query_entities(entity_type=EntityType.TOOL)
print(f"Found {len(tools)} tools")
# Expected: 0 (no entities extracted yet)
```

---

## What Happens to Existing Data?

### Preserved Data

✅ **ALL existing data is preserved**:
- Bullets table (unchanged)
- Playbook sections
- Quality scores (helpful_count, harmful_count)
- Code examples
- Timestamps (created_at, last_used_at)
- Tags and related_bullets

### New Data (Initially Empty)

📊 **New tables start empty** (no automatic backfill):
- `entities`: 0 rows
- `relationships`: 0 rows
- `provenance`: 0 rows
- `entities_fts`: 0 indexed documents

**Why no automatic extraction?**
- Entity extraction is compute-intensive
- Extraction happens incrementally as new bullets are added/used
- Reflector agent triggers extraction during MAP workflows

---

## Using the Knowledge Graph After Migration

### Automatic KG Extraction (Recommended)

The simplest way to populate the Knowledge Graph is through normal MAP workflow usage:

```bash
# Run any MAP workflow command
/map-feature implement user authentication with JWT tokens

# KG extraction happens automatically in Reflector → Curator steps:
# 1. Reflector extracts entities and relationships from successes
# 2. Curator updates playbook with new bullets
# 3. PlaybookManager stores entities/relationships in database
# 4. KG query interface becomes available
```

**What gets extracted**:
- Entities: Tools (pytest, JWT), Patterns (authentication), Technologies (Python), etc.
- Relationships: "pytest USES Python", "JWT IMPLEMENTS authentication-pattern"
- Provenance: Each entity tracks which bullet it came from

### Manual KG Extraction (Advanced)

For existing playbook bullets, you can manually trigger extraction:

```python
from mapify_cli.playbook_manager import PlaybookManager
from mapify_cli.entity_extractor import EntityExtractor
from mapify_cli.relationship_detector import RelationshipDetector

pm = PlaybookManager(db_path=".claude/playbook.db")
extractor = EntityExtractor()
detector = RelationshipDetector()

# Get all existing bullets
bullets = pm.db_conn.execute("SELECT id, content FROM bullets").fetchall()

for bullet_id, content in bullets:
    # Extract entities
    entities = extractor.extract_entities(content)

    # Detect relationships
    relationships = detector.detect_relationships(content, entities, bullet_id)

    # Insert into database
    for entity in entities:
        pm.db_conn.execute("""
            INSERT OR IGNORE INTO entities (id, type, name, confidence, first_seen_at, last_seen_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (entity.id, entity.type.value, entity.name, entity.confidence,
              entity.first_seen_at, entity.last_seen_at,
              datetime.now(timezone.utc).isoformat(),
              datetime.now(timezone.utc).isoformat()))

    for rel in relationships:
        pm.db_conn.execute("""
            INSERT OR IGNORE INTO relationships (id, source_entity_id, target_entity_id, type, created_from_bullet_id, confidence, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (rel.id, rel.source_entity_id, rel.target_entity_id, rel.type.value,
              rel.created_from_bullet_id, rel.confidence,
              datetime.now(timezone.utc).isoformat(),
              datetime.now(timezone.utc).isoformat()))

pm.db_conn.commit()
print(f"Extracted entities and relationships from {len(bullets)} bullets")
```

**Warning**: Manual extraction can be slow for large playbooks (100+ bullets). Prefer automatic extraction through workflows.

---

## Querying the Knowledge Graph

### Using KnowledgeGraphQuery API

```python
from mapify_cli.playbook_manager import PlaybookManager
from mapify_cli.entity_extractor import EntityType
from mapify_cli.relationship_detector import RelationshipType

pm = PlaybookManager()
kg = pm.kg_query

# Find all tools
tools = kg.query_entities(entity_type=EntityType.TOOL, min_confidence=0.7)
print(f"Tools: {[e.name for e in tools]}")

# Find dependencies
deps = kg.query_relationships(relationship_type=RelationshipType.DEPENDS_ON)
print(f"Dependencies: {[(r.source_entity_id, r.target_entity_id) for r in deps]}")

# Find path between entities
paths = kg.find_paths('ent-pytest', 'ent-python', max_depth=3)
for path in paths:
    print(f"Path: {' -> '.join(path.entities())}")

# Get entity neighbors
neighbors = kg.get_neighbors('ent-pytest', direction='outgoing')
for entity, relationship in neighbors:
    print(f"pytest {relationship.type.value} {entity.name}")
```

### Using SQL Directly

```sql
-- Find all TOOL entities with confidence > 0.8
SELECT name, confidence FROM entities
WHERE type = 'TOOL' AND confidence > 0.8
ORDER BY confidence DESC;

-- Find all USES relationships
SELECT
    e1.name AS source,
    r.type,
    e2.name AS target,
    r.confidence
FROM relationships r
JOIN entities e1 ON r.source_entity_id = e1.id
JOIN entities e2 ON r.target_entity_id = e2.id
WHERE r.type = 'USES'
ORDER BY r.confidence DESC;

-- Find entities extracted from specific bullet
SELECT e.name, e.type, p.extraction_confidence
FROM provenance p
JOIN entities e ON p.entity_id = e.id
WHERE p.source_bullet_id = 'impl-0001';

-- Full-text search for entities
SELECT name, type, confidence
FROM entities_fts
WHERE entities_fts MATCH 'pytest OR testing'
ORDER BY rank;
```

---

## Rollback Instructions

If you need to revert to v2.1 schema (DATA LOSS WARNING):

See [`MIGRATION_ROLLBACK.md`](./MIGRATION_ROLLBACK.md) for detailed rollback procedures.

**Quick rollback** (if you have backup):
```bash
cp .claude/playbook.db.backup .claude/playbook.db
```

---

## Migration FAQ

### Q: Do I need to manually run migration?
**A:** No, migration is 100% automatic when you upgrade to v1.3.0+.

### Q: Will migration break my existing playbook?
**A:** No, migration only adds tables. Existing bullets and data are untouched.

### Q: How long does migration take?
**A:** <1 second. Migration adds empty tables with indexes.

### Q: Can I disable Knowledge Graph features?
**A:** Not directly, but KG features are opt-in (you don't have to use them). Set `kg_enabled=0` in metadata if needed:
```sql
UPDATE metadata SET value='0' WHERE key='kg_enabled';
```

### Q: What if migration fails?
**A:** Migration uses transactions. If it fails, database rolls back to v2.1 state. Check logs for error details.

### Q: Do I need to extract entities from existing bullets?
**A:** No, extraction happens automatically during MAP workflows. Manual backfill is optional (see "Manual KG Extraction" above).

### Q: Will KG slow down my playbook queries?
**A:** No, KG tables have separate indexes. Legacy playbook queries are unaffected.

### Q: Can I query both v2.1 and v3.0 features simultaneously?
**A:** Yes! v3.0 is fully backward compatible. Use `bullets` table queries (v2.1 style) alongside KG queries (v3.0 style).

---

## Troubleshooting

### Error: "table entities already exists"

**Cause**: Migration tried to run twice.

**Solution**: This is safe to ignore. Migration is idempotent (uses `CREATE TABLE IF NOT EXISTS`).

**Verification**:
```bash
sqlite3 .claude/playbook.db "SELECT value FROM metadata WHERE key='schema_version';"
# Should output: 3.0
```

### Error: "FOREIGN KEY constraint failed"

**Cause**: Foreign keys enabled but constraint violated (rare).

**Solution**:
```bash
sqlite3 .claude/playbook.db "PRAGMA foreign_key_check;"
# Lists violations (should be empty)
```

If violations exist, file an issue at https://github.com/azalio/map-framework/issues.

### Error: "disk I/O error"

**Cause**: Database file locked or corrupted.

**Solution**:
1. Close all Claude Code windows
2. Verify file integrity:
   ```bash
   sqlite3 .claude/playbook.db "PRAGMA integrity_check;"
   # Expected: ok
   ```
3. If corrupted, restore from backup

### Performance: Slow queries after migration

**Cause**: Indexes not created or disabled.

**Solution**: Verify indexes exist:
```bash
sqlite3 .claude/playbook.db ".indexes entities"
# Expected: idx_entities_confidence, idx_entities_last_seen, idx_entities_name, idx_entities_type
```

If missing, re-run migration:
```python
from mapify_cli.playbook_manager import PlaybookManager
pm = PlaybookManager(db_path=".claude/playbook.db")
# Migration runs automatically on init
```

---

## Technical Details

### Schema Version Comparison

| Feature                  | v2.1          | v3.0                |
|--------------------------|---------------|---------------------|
| Bullets storage          | ✅ SQLite     | ✅ SQLite (same)    |
| Entity extraction        | ❌ Manual     | ✅ Automatic        |
| Relationship tracking    | ❌ None       | ✅ Typed edges      |
| Provenance tracking      | ❌ None       | ✅ Bullet-level     |
| Full-text search         | ✅ bullets_fts | ✅ bullets_fts + entities_fts |
| Graph queries            | ❌ None       | ✅ BFS, paths, neighbors |
| Contradiction detection  | ❌ None       | ✅ CONTRADICTS rel  |
| Semantic knowledge       | ⚠️ Implicit   | ✅ Explicit graph   |

### Migration SQL

The full migration SQL is in `src/mapify_cli/schemas.py`:

```python
SCHEMA_V3_0_SQL = """
CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL CHECK (type IN (...)),
    name TEXT NOT NULL,
    ...
);

CREATE TABLE IF NOT EXISTS relationships (
    id TEXT PRIMARY KEY,
    source_entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    ...
);

CREATE TABLE IF NOT EXISTS provenance (
    ...
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type);
...
"""
```

**Idempotency**: Uses `IF NOT EXISTS` clauses, safe to run multiple times.

---

## Next Steps

After successful migration:

1. **Read API Documentation**: [`api_reference.md`](./api_reference.md)
2. **Explore ERD**: [`ERD_v3.0.md`](./ERD_v3.0.md)
3. **Learn Best Practices**: [USAGE.md](../USAGE.md#knowledge-graph-features)
4. **Understand Design Rationale**: [`DESIGN_RATIONALE.md`](./DESIGN_RATIONALE.md)

---

## Support & Feedback

- **Issues**: https://github.com/azalio/map-framework/issues
- **Discussions**: https://github.com/azalio/map-framework/discussions
- **Documentation**: [`docs/knowledge_graph/`](.)
