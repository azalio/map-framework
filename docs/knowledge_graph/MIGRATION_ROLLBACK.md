# Schema Migration Rollback Guide (v3.0 → v2.1)

## Overview

This document explains how to rollback the Knowledge Graph schema migration from v3.0 to v2.1 if needed.

**IMPORTANT**: Schema migrations in MAP Framework are **forward-only** by design. There is no automated downgrade path because dropping tables results in data loss.

## Rollback Strategy

### Option 1: Restore from Backup (RECOMMENDED)

If you have a backup of your `playbook.db` file from before the v3.0 migration:

```bash
# Stop any processes using playbook.db
# Replace with your backup file
cp .claude/playbook.db.backup .claude/playbook.db

# Verify schema version
sqlite3 .claude/playbook.db "SELECT value FROM metadata WHERE key='schema_version';"
# Should output: 2.1
```

### Option 2: Manual Table Deletion (DATA LOSS)

If you don't have a backup and want to revert to v2.1 schema:

```bash
sqlite3 .claude/playbook.db <<'EOF'
-- Disable foreign key constraints temporarily
PRAGMA foreign_keys=OFF;

-- Drop Knowledge Graph tables
DROP TABLE IF EXISTS provenance;
DROP TABLE IF EXISTS relationships;
DROP TABLE IF EXISTS entities;

-- Drop FTS5 table for entities
DROP TABLE IF EXISTS entities_fts;

-- Drop triggers (automatically dropped with FTS table, but explicit for clarity)
DROP TRIGGER IF EXISTS entities_ai;
DROP TRIGGER IF EXISTS entities_ad;
DROP TRIGGER IF EXISTS entities_au;

-- Update schema version back to 2.1
UPDATE metadata SET value = '2.1' WHERE key = 'schema_version';

-- Remove KG-specific metadata
DELETE FROM metadata WHERE key = 'kg_enabled';
DELETE FROM metadata WHERE key = 'last_kg_extraction';

-- Re-enable foreign key constraints
PRAGMA foreign_keys=ON;
EOF
```

**WARNING**: This will permanently delete all Knowledge Graph data (entities, relationships, provenance). The `bullets` table and existing playbook data will be preserved.

### Option 3: Prevent Migration (Before Running v3.0 Code)

If you want to prevent the migration from running in the first place:

1. **Backup your database**:
   ```bash
   cp .claude/playbook.db .claude/playbook.db.backup
   ```

2. **Pin to v1.2.x or earlier** version of MAP Framework (before KG feature):
   ```bash
   pip install 'mapify-cli<1.3.0'
   ```

3. **Use the backup**:
   If migration already ran, restore from backup (see Option 1).

## Verification After Rollback

After performing rollback, verify the database is in v2.1 state:

```bash
# Check schema version
sqlite3 .claude/playbook.db "SELECT key, value FROM metadata WHERE key='schema_version';"
# Expected output: schema_version|2.1

# Verify KG tables don't exist
sqlite3 .claude/playbook.db ".tables" | grep -E '(entities|relationships|provenance)'
# Expected output: (empty - no matches)

# Verify bullets table still exists
sqlite3 .claude/playbook.db "SELECT COUNT(*) FROM bullets;"
# Expected output: (number of bullets in your playbook)

# Check foreign_keys pragma (should still work)
sqlite3 .claude/playbook.db "PRAGMA foreign_keys;"
# Expected output: 1 (foreign keys enabled)
```

## When to Rollback

Consider rollback if:
- **Schema migration fails** with errors during v3.0 deployment
- **Application errors** occur after migration that you can't quickly fix
- **Performance degradation** observed (unlikely, but possible with large datasets)
- **You need to revert to pre-KG version** of MAP Framework temporarily

## When NOT to Rollback

Avoid rollback if:
- **KG data already extracted**: Rolling back loses all entity/relationship data
- **Multiple developers using KG features**: Rollback creates schema version conflicts
- **Production deployment completed**: Rollback disrupts users
- **Migration succeeded**: No issues observed (rollback is unnecessary)

## Post-Rollback Actions

After rollback:

1. **Notify team** if working in shared environment
2. **Document reason** for rollback in project changelog
3. **Create issue** to track root cause if migration failed
4. **Plan re-migration** after fixing underlying issues

## Prevention: Backup Strategy

To avoid needing rollback, **always backup before migration**:

```bash
# Before upgrading to v3.0, run:
cp .claude/playbook.db .claude/playbook.db.pre-v3.0-backup

# Verify backup:
ls -lh .claude/playbook.db*
```

## Contact & Support

If you encounter issues with migration or rollback:
- **GitHub Issues**: https://github.com/azalio/map-framework/issues
- **Schema Design Docs**: `docs/knowledge_graph/SCHEMA_DESIGN.md`
- **Migration SQL**: `docs/knowledge_graph/schema_v3.0.sql`

## Technical Details

### Why No Automated Downgrade?

Schema migrations in MAP Framework follow the **forward-only** pattern because:

1. **Data loss**: Downgrade requires dropping tables (loses KG data)
2. **Complexity**: Maintaining bidirectional migrations doubles maintenance burden
3. **Rare need**: Most schema issues are fixed forward (add missing field), not backward
4. **Backup strategy**: Database backups are more reliable than automated downgrades

### Migration Safety Features

The v3.0 migration is designed to be safe:
- **Idempotent**: Uses `CREATE TABLE IF NOT EXISTS`, safe to run multiple times
- **Non-destructive**: Only adds tables, never modifies/deletes existing data
- **Atomic**: Uses transactions, rolls back on error
- **Verification**: Checks table creation and schema_version update
- **Error handling**: Specific exceptions with actionable error messages

### Schema Version Tracking

Schema versions track major structural changes:
- **v2.0**: Initial SQLite schema (migrated from JSON)
- **v2.1**: Added `executable_scripts` field to bullets table
- **v3.0**: Added Knowledge Graph tables (entities, relationships, provenance)
