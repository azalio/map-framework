# Knowledge Graph Schema v3.0 - Design Rationale

## Overview

This document explains the **why** behind design decisions in the Knowledge Graph schema extension for MAP Framework playbook.

---

## Why Three Tables Instead of One?

### Design Decision

Separate tables for **entities**, **relationships**, and **provenance** instead of single denormalized table.

### Rationale

1. **Normalization**: Prevents data duplication. Entity mentioned in 10 bullets stored once in `entities`, with 10 `provenance` records.
2. **Query Performance**: Graph traversal queries benefit from focused indexes on relationships table.
3. **Schema Evolution**: Easy to add entity-specific fields without affecting other tables.
4. **Referential Integrity**: Foreign key constraints enforce graph consistency.

### Alternative Considered: Single Table

Rejected because NULL columns for half the rows, index bloat, complex queries requiring `WHERE type = 'entity'` everywhere.

---

## Entity Type Taxonomy

### 7 Entity Types

1. **TOOL**: CLI tools, libraries, frameworks (pytest, SQLite, Docker)
2. **PATTERN**: Implementation patterns (retry-with-backoff, feature-flags)
3. **CONCEPT**: Abstract ideas (idempotency, eventual-consistency)
4. **ERROR_TYPE**: Error categories (race-condition, null-pointer)
5. **TECHNOLOGY**: Tech stack components (Python, Kubernetes, CI/CD)
6. **WORKFLOW**: Process patterns (MAP-debugging, TDD-cycle)
7. **ANTIPATTERN**: Known bad practices (generic-exception-catch)

### Why These 7?

Derived from analyzing 100+ playbook bullets:
- Tools mentioned in `code_example` fields → TOOL
- "Pattern:" bullets → PATTERN
- Abstract concepts in explanations → CONCEPT
- Error handling bullets → ERROR_TYPE
- Stack mentions → TECHNOLOGY
- Process descriptions → WORKFLOW
- "Never do X" bullets → ANTIPATTERN

**Extensibility**: Can add new types by modifying CHECK constraint in future migrations.

---

## Relationship Type Taxonomy

### 9 Relationship Types

1. **USES**: A uses B (pytest USES Python)
2. **DEPENDS_ON**: A depends on B (MAP-workflow DEPENDS_ON playbook.db)
3. **CONTRADICTS**: A contradicts B (generic-exception CONTRADICTS specific-exceptions)
4. **SUPERSEDES**: A replaces B (playbook.db SUPERSEDES playbook.json)
5. **RELATED_TO**: Generic relationship (fallback)
6. **IMPLEMENTS**: A implements pattern B (retry-logic IMPLEMENTS resilience-pattern)
7. **CAUSES**: A causes B (race-condition CAUSES data-corruption)
8. **PREVENTS**: A prevents B (mutex-lock PREVENTS race-condition)
9. **ALTERNATIVE_TO**: A is alternative to B (JSON-storage ALTERNATIVE_TO SQLite-storage)

### Why These 9?

**Inspired by CORE framework** and ontology design:
- **Directional**: All relationships have clear source → target semantics
- **Semantic clarity**: Each type has unambiguous meaning
- **Covers common patterns**: Derived from analyzing how playbook bullets relate concepts

---

## Foreign Key Cascade vs Restrict

### Design Decision

All foreign keys use `ON DELETE CASCADE` instead of `ON DELETE RESTRICT`.

### Rationale

1. **Simplifies cleanup**: Deleting deprecated bullet automatically removes derived entities/relationships
2. **Referential integrity**: No orphaned foreign keys
3. **Aligns with playbook lifecycle**: When bullet removed, derived knowledge should be re-evaluated

### Trade-off: Accidental Deletion Risk

If user accidentally deletes bullet, graph knowledge is lost.

**Mitigation (future work)**:
- Add `deleted_at` soft-delete column to bullets
- Add `playbook.db.backup` pre-delete hook
- Add "Undo delete" command

**Decision**: Accept risk for v3.0 (playbook operations are infrequent, users review before delete).

---

## Confidence Score Calculation

### Entity Confidence

Calculated as **average of provenance extraction confidences**:

```python
entity.confidence = AVG(provenance.extraction_confidence WHERE entity_id = entity.id)
```

**Factors increasing extraction confidence:**
- Explicit mention in `content`: +0.3
- Mentioned in `code_example`: +0.2
- High `helpful_count` of source bullet: +0.1 (if helpful_count > 5)
- Multiple bullets mention same entity: +0.1 per additional bullet (max +0.3)

**Example:**
```
Bullet impl-0042: "Use pytest for testing" (helpful_count = 8, has code_example)
  → extraction_confidence = 0.5 + 0.3 + 0.2 + 0.1 = 1.0

Bullet impl-0087: "Testing frameworks like pytest..." (helpful_count = 2, no code)
  → extraction_confidence = 0.5 + 0.3 = 0.8

entity.confidence = AVG(1.0, 0.8) = 0.9
```

---

## Why TEXT PRIMARY KEY?

### Design Decision

Use TEXT (semantic IDs) instead of INTEGER (auto-increment) for primary keys.

### Rationale

1. **Debuggability**: `ent-pytest` is more readable than `1234` in logs/queries
2. **Compatibility**: Existing bullets table uses TEXT IDs (`impl-0042`, `sec-0015`)
3. **Mergeability**: Can merge knowledge graphs from different sources without ID conflicts
4. **Semantic meaning**: ID conveys entity type (`ent-` prefix) and identity (`pytest`)

### ID Format

- Entities: `ent-{slug}` (e.g., `ent-pytest`, `ent-map-framework`)
- Relationships: `rel-{uuid}` (e.g., `rel-a1b2c3d4`)
- Provenance: `prov-{uuid}` (e.g., `prov-e5f6g7h8`)

**Performance Impact**: TEXT keys ~10% slower than INTEGER for lookups.

**Decision**: Acceptable trade-off for debuggability.

---

## Why JSON Metadata Instead of Columns?

### Design Decision

Use `metadata TEXT` (JSON) instead of adding entity-specific columns.

### Rationale

1. **Schema flexibility**: Can add new entity attributes without migration
2. **Entity-specific fields**: TOOL entities need `version`, PATTERN entities need `aliases`, ERROR_TYPE entities need `severity` → different schemas per type
3. **Sparse data**: Most entities don't use most metadata fields → NULL columns waste space

### Example Usage

```json
// Entity: pytest (type=TOOL)
{
  "version": "7.4.0",
  "documentation_url": "https://docs.pytest.org",
  "license": "MIT"
}

// Entity: exponential-backoff (type=PATTERN)
{
  "aliases": ["retry logic", "resilient requests"],
  "complexity": "medium",
  "use_cases": ["API calls", "database retries"]
}
```

---

## Trade-offs Summary

### 8 Key Trade-offs

1. **TEXT PRIMARY KEYs** prioritize debuggability over performance (~10% slower than INTEGER)

2. **CASCADE delete** prioritizes data consistency over accidental deletion protection

3. **JSON metadata fields** prioritize schema flexibility over query performance

4. **15 indexes** prioritize read performance over write speed (~2.5x disk space)

5. **Single provenance table** prioritizes schema simplicity over type safety

6. **SQLite instead of graph database** prioritizes operational simplicity over query expressiveness

7. **Stored confidence scores** prioritize query performance over storage

8. **7 entity types + 9 relationship types (CHECK constraints)** prioritize data quality over flexibility

---

## Alternatives Considered

### 1. Graph Database vs SQLite

**Alternative**: Use Neo4j, ArangoDB

**Rejected**: Adds infrastructure dependency, overkill for <10K entities, SQLite handles graph queries efficiently at this scale

### 2. Denormalized Schema

**Alternative**: Store relationships as JSON in entities table

**Rejected**: Query complexity (`json_extract` is slow), can't index JSON array elements efficiently

### 3. Confidence as Computed Column

**Alternative**: Make `entity.confidence` VIRTUAL column

**Rejected**: SQLite GENERATED columns can't use subqueries, performance issues

### 4. Temporal Validity

**Alternative**: Add `valid_from`/`valid_to` to track when entity/relationship was true

**Deferred to future**: Adds complexity, unclear how to determine validity period, current `first_seen_at`/`last_seen_at` provides simpler temporal tracking

---

## References

- **Cipher knowledge**: "SQLITE AUTO-MIGRATION WITH NULL SAFETY" pattern
- **CORE framework**: Inspiration for entity/relationship types
- **Playbook analysis**: 100+ bullets analyzed to derive entity types
- **SQLite best practices**: https://www.sqlite.org/foreignkeys.html, https://www.sqlite.org/fts5.html
