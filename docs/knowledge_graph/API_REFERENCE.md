# Knowledge Graph API Reference

Complete API documentation for MAP Framework Knowledge Graph Layer modules.

## Table of Contents

- [Entity Extractor](#entity-extractor)
  - [EntityExtractor](#entityextractor-class)
  - [Entity Dataclass](#entity-dataclass)
  - [EntityType Enum](#entitytype-enum)
  - [Module Functions](#entity-extractor-module-functions)
- [Relationship Detector](#relationship-detector)
  - [RelationshipDetector](#relationshipdetector-class)
  - [Relationship Dataclass](#relationship-dataclass)
  - [RelationshipType Enum](#relationshiptype-enum)
  - [Module Functions](#relationship-detector-module-functions)
- [Knowledge Graph Query](#knowledge-graph-query)
  - [KnowledgeGraphQuery](#knowledgegraphquery-class)
  - [Path Dataclass](#path-dataclass)
  - [Module Functions](#knowledge-graph-query-module-functions)
- [Contradiction Detector](#contradiction-detector)
  - [ContradictionDetector](#contradictiondetector-class)
  - [Contradiction Dataclass](#contradiction-dataclass)
  - [Module Functions](#contradiction-detector-module-functions)
- [Confidence Scoring System](#confidence-scoring-system)
- [Performance Characteristics](#performance-characteristics)

---

## Entity Extractor

Module: `mapify_cli.entity_extractor`

### EntityExtractor Class

Pattern-based entity extraction engine that identifies and extracts semantic entities from text.

#### Methods

##### `extract_entities(text: str) -> List[Entity]`

Extract entities from text content.

**Parameters:**
- `text` (str): Content to extract entities from

**Returns:**
- `List[Entity]`: List of extracted entities with confidence scores

**Example:**
```python
from mapify_cli.entity_extractor import EntityExtractor

extractor = EntityExtractor()
entities = extractor.extract_entities("Use pytest for testing Python applications")

for entity in entities:
    print(f"{entity.name} ({entity.type.value}): {entity.confidence:.2f}")
# Output:
# pytest (TOOL): 0.85
# Python (TECHNOLOGY): 0.90
```

**Extraction Patterns:**
- **Code entities** (backticks): Confidence 0.7-0.9
- **Import statements**: Confidence 0.8-0.9
- **Keyword matching**: Confidence 0.6-0.8
- **Pattern suffixes** ("pattern", "antipattern"): Confidence 0.7-0.85

**Edge Cases:**
- Empty text → returns `[]`
- Whitespace-only → returns `[]`
- Long text (>100KB) → automatic chunking
- Unicode characters → handled correctly

**Performance:**
- Typical text (1KB): <10ms
- Long text (100KB): <100ms
- Accuracy on test corpus: ≥80%

---

### Entity Dataclass

Represents an extracted entity with metadata and provenance.

#### Fields

- **`id`** (str): Unique entity ID in format `ent-{slug}`
  - Example: `'ent-pytest'`, `'ent-retry-pattern'`
  - Automatically generated from entity name

- **`type`** (EntityType): Entity classification
  - Valid values: TOOL, PATTERN, CONCEPT, ERROR_TYPE, TECHNOLOGY, WORKFLOW, ANTIPATTERN

- **`name`** (str): Human-readable entity name
  - Example: `'pytest'`, `'Exponential Backoff'`, `'race-condition'`

- **`confidence`** (float): Extraction quality score (0.0-1.0)
  - 0.9-1.0: High confidence (explicit mentions, code blocks)
  - 0.7-0.9: Medium confidence (keyword matching)
  - 0.5-0.7: Low confidence (inferred from context)

- **`first_seen_at`** (str): ISO8601 timestamp of first extraction
  - Example: `'2025-01-15T14:30:00Z'`

- **`last_seen_at`** (str): ISO8601 timestamp of last mention
  - Updated when entity re-appears in new content

- **`metadata`** (Optional[Dict]): Additional entity-specific data
  - Example: `{"version": "7.4.0", "license": "MIT"}`

#### Validation

Entities are validated on creation:
- `confidence` must be in range [0.0, 1.0]
- `id` must start with `'ent-'`
- Raises `ValueError` if constraints violated

#### Example

```python
from mapify_cli.entity_extractor import Entity, EntityType
from datetime import datetime, timezone

now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

entity = Entity(
    id='ent-pytest',
    type=EntityType.TOOL,
    name='pytest',
    confidence=0.9,
    first_seen_at=now,
    last_seen_at=now,
    metadata={"version": "7.4.0"}
)
```

---

### EntityType Enum

Entity classification taxonomy aligned with schema CHECK constraint.

#### Values

```python
class EntityType(Enum):
    TOOL = "TOOL"                    # CLI tools, libraries (pytest, Docker, SQLite)
    PATTERN = "PATTERN"              # Implementation patterns (retry-with-backoff)
    CONCEPT = "CONCEPT"              # Abstract ideas (idempotency, ACID)
    ERROR_TYPE = "ERROR_TYPE"        # Error categories (race-condition, deadlock)
    TECHNOLOGY = "TECHNOLOGY"        # Tech stack (Python, Kubernetes, React)
    WORKFLOW = "WORKFLOW"            # Process patterns (TDD, CI/CD, MAP-workflow)
    ANTIPATTERN = "ANTIPATTERN"      # Bad practices (generic-exception, magic-number)
```

#### Usage

```python
from mapify_cli.entity_extractor import EntityType

# Create entity with specific type
entity.type = EntityType.TOOL

# Compare types
if entity.type == EntityType.TOOL:
    print(f"{entity.name} is a tool")

# Get string value
print(entity.type.value)  # "TOOL"
```

---

### Entity Extractor Module Functions

#### `extract_entities(text: str) -> List[Entity]`

Convenience function for one-off entity extraction.

**Parameters:**
- `text` (str): Content to extract entities from

**Returns:**
- `List[Entity]`: Extracted entities

**Example:**
```python
from mapify_cli.entity_extractor import extract_entities

entities = extract_entities("Use pytest for testing")
print(len(entities))  # 1-2 entities
```

---

## Relationship Detector

Module: `mapify_cli.relationship_detector`

### RelationshipDetector Class

Pattern-matching relationship detector that identifies typed relationships between entities.

#### Methods

##### `detect_relationships(text: str, entities: List[Entity], bullet_id: str) -> List[Relationship]`

Detect relationships between entities in text.

**Parameters:**
- `text` (str): Content containing relationship patterns
- `entities` (List[Entity]): Entities to find relationships between
- `bullet_id` (str): Source bullet ID for provenance tracking

**Returns:**
- `List[Relationship]`: Detected relationships with confidence scores

**Example:**
```python
from mapify_cli.relationship_detector import RelationshipDetector
from mapify_cli.entity_extractor import extract_entities

text = "pytest uses Python for unit testing"
entities = extract_entities(text)

detector = RelationshipDetector()
relationships = detector.detect_relationships(text, entities, 'bullet-001')

for rel in relationships:
    source = next(e for e in entities if e.id == rel.source_entity_id)
    target = next(e for e in entities if e.id == rel.target_entity_id)
    print(f"{source.name} {rel.type.value} {target.name} (conf: {rel.confidence:.2f})")
# Output:
# pytest USES Python (conf: 0.85)
```

**Relationship Patterns:**

| Type          | Pattern Examples                                 | Confidence |
|---------------|--------------------------------------------------|------------|
| USES          | "X uses Y", "X built on Y", "X with Y"           | 0.7-0.9    |
| DEPENDS_ON    | "X depends on Y", "X requires Y", "X needs Y"    | 0.7-0.9    |
| CONTRADICTS   | "X contradicts Y", "use Y instead of X"          | 0.8-0.95   |
| SUPERSEDES    | "X supersedes Y", "migrated from Y to X"         | 0.8-0.9    |
| IMPLEMENTS    | "X implements Y", "X follows Y"                  | 0.6-0.8    |
| CAUSES        | "X causes Y", "X leads to Y"                     | 0.6-0.8    |
| PREVENTS      | "X prevents Y", "X avoids Y"                     | 0.6-0.8    |
| ALTERNATIVE_TO| "X is alternative to Y"                          | 0.5-0.7    |
| RELATED_TO    | Proximity-based (entities close together)       | 0.4-0.6    |

**Edge Cases:**
- No entities → returns `[]`
- Empty text → returns `[]`
- Self-relationships filtered (e.g., "pytest USES pytest")
- Duplicate relationships deduplicated

**Performance:**
- Small text (1KB, 5 entities): <20ms
- Medium text (10KB, 20 entities): <100ms
- Accuracy on test corpus: ≥70%

---

### Relationship Dataclass

Represents a typed relationship between two entities.

#### Fields

- **`id`** (str): Unique relationship ID in format `rel-{uuid}`
  - Example: `'rel-001'`, `'rel-abc123'`

- **`source_entity_id`** (str): Source entity ID (must start with `'ent-'`)
  - Example: `'ent-pytest'`

- **`target_entity_id`** (str): Target entity ID (must start with `'ent-'`)
  - Example: `'ent-python'`

- **`type`** (RelationshipType): Relationship classification
  - Valid values: USES, DEPENDS_ON, CONTRADICTS, SUPERSEDES, RELATED_TO, IMPLEMENTS, CAUSES, PREVENTS, ALTERNATIVE_TO

- **`created_from_bullet_id`** (str): Provenance tracking (which bullet mentioned this)
  - Example: `'impl-0001'`

- **`confidence`** (float): Relationship strength (0.0-1.0)
  - 0.8-1.0: Explicit patterns ("X uses Y")
  - 0.6-0.8: Implicit patterns ("X with Y")
  - 0.4-0.6: Proximity-based

- **`metadata`** (Optional[Dict]): Extraction context
  - Example: `{"extraction_method": "pattern_matching", "pattern_matched": "uses"}`

- **`created_at`** (str): ISO8601 timestamp of creation

- **`updated_at`** (str): ISO8601 timestamp of last update

#### Validation

Relationships are validated on creation:
- `confidence` must be in range [0.0, 1.0]
- `id` must start with `'rel-'`
- `source_entity_id` and `target_entity_id` must start with `'ent-'`
- Raises `ValueError` if constraints violated

#### Example

```python
from mapify_cli.relationship_detector import Relationship, RelationshipType
from datetime import datetime, timezone

now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

relationship = Relationship(
    id='rel-001',
    source_entity_id='ent-pytest',
    target_entity_id='ent-python',
    type=RelationshipType.USES,
    created_from_bullet_id='impl-0001',
    confidence=0.85,
    metadata={"pattern_matched": "uses"},
    created_at=now,
    updated_at=now
)
```

---

### RelationshipType Enum

Relationship classification taxonomy aligned with schema CHECK constraint.

#### Values

```python
class RelationshipType(Enum):
    USES = "USES"                      # X uses Y as dependency
    DEPENDS_ON = "DEPENDS_ON"          # X requires Y to function
    CONTRADICTS = "CONTRADICTS"        # X conflicts with Y
    SUPERSEDES = "SUPERSEDES"          # X replaces Y
    RELATED_TO = "RELATED_TO"          # X and Y are semantically related
    IMPLEMENTS = "IMPLEMENTS"          # X implements pattern Y
    CAUSES = "CAUSES"                  # X causes problem Y
    PREVENTS = "PREVENTS"              # X prevents problem Y
    ALTERNATIVE_TO = "ALTERNATIVE_TO"  # X is alternative to Y
```

#### Semantics

**Directional relationships** (order matters):
- `pytest USES Python` (✓ correct)
- `Python USES pytest` (✗ incorrect)

**Symmetric relationships** (order doesn't matter):
- `RELATED_TO`: Proximity-based, bidirectional
- `ALTERNATIVE_TO`: Both options are valid alternatives

---

### Relationship Detector Module Functions

#### `detect_relationships(text: str, entities: List[Entity], bullet_id: str) -> List[Relationship]`

Convenience function for one-off relationship detection.

**Parameters:**
- `text` (str): Content containing relationships
- `entities` (List[Entity]): Entities to find relationships between
- `bullet_id` (str): Source bullet ID for provenance

**Returns:**
- `List[Relationship]`: Detected relationships

**Example:**
```python
from mapify_cli.relationship_detector import detect_relationships
from mapify_cli.entity_extractor import extract_entities

text = "pytest depends on unittest for testing"
entities = extract_entities(text)
relationships = detect_relationships(text, entities, 'bullet-001')

print(len(relationships))  # 1-2 relationships
```

---

## Knowledge Graph Query

Module: `mapify_cli.graph_query`

### KnowledgeGraphQuery Class

High-performance graph query interface with BFS path finding and neighbor traversal.

#### Constructor

```python
KnowledgeGraphQuery(db_conn: sqlite3.Connection)
```

**Parameters:**
- `db_conn`: SQLite database connection with schema v3.0

#### Methods

##### `find_paths(source_id: str, target_id: str, max_depth: int = 3, relationship_types: Optional[List[RelationshipType]] = None) -> List[Path]`

Find all paths from source to target entity using BFS traversal.

**Parameters:**
- `source_id` (str): Source entity ID (must start with `'ent-'`)
- `target_id` (str): Target entity ID (must start with `'ent-'`)
- `max_depth` (int, default=3): Maximum path length to explore
- `relationship_types` (Optional[List[RelationshipType]]): Filter paths by relationship types

**Returns:**
- `List[Path]`: Paths sorted by length (shortest first), then confidence (highest first)

**Example:**
```python
from mapify_cli.graph_query import KnowledgeGraphQuery
from mapify_cli.relationship_detector import RelationshipType

kg_query = KnowledgeGraphQuery(db_conn)

# Find all paths
paths = kg_query.find_paths('ent-pytest', 'ent-python', max_depth=3)

for path in paths:
    print(f"Path length: {path.length}, confidence: {path.confidence:.2f}")
    print(" -> ".join(path.entities()))

# Filter by relationship type
paths = kg_query.find_paths(
    'ent-pytest',
    'ent-python',
    relationship_types=[RelationshipType.USES, RelationshipType.DEPENDS_ON]
)
```

**Performance:**
- Direct path (1 hop): <10ms
- Indirect path (2-3 hops): <50ms
- Target: <100ms for most queries

**Edge Cases:**
- Source == target → returns `[]`
- No path exists → returns `[]`
- Cycle detection: Prevents infinite loops

---

##### `get_neighbors(entity_id: str, direction: str = 'both', relationship_types: Optional[List[RelationshipType]] = None, min_confidence: float = 0.0) -> List[Tuple[Entity, Relationship]]`

Get neighboring entities connected by relationships.

**Parameters:**
- `entity_id` (str): Entity ID to find neighbors for
- `direction` (str): `'outgoing'`, `'incoming'`, or `'both'` (default)
- `relationship_types` (Optional[List[RelationshipType]]): Filter by relationship type
- `min_confidence` (float, default=0.0): Minimum relationship confidence

**Returns:**
- `List[Tuple[Entity, Relationship]]`: Neighbor entities with connecting relationships, sorted by confidence (descending)

**Example:**
```python
neighbors = kg_query.get_neighbors('ent-pytest', direction='outgoing')

for entity, relationship in neighbors:
    print(f"pytest {relationship.type.value} {entity.name} (conf: {relationship.confidence:.2f})")
# Output:
# pytest USES Python (conf: 0.90)
# pytest DEPENDS_ON unittest (conf: 0.80)
```

**Performance:**
- Typical case (5-10 neighbors): <20ms
- Target: <50ms

---

##### `entities_since(cutoff_timestamp: str, entity_types: Optional[List[EntityType]] = None, min_confidence: float = 0.0) -> List[Entity]`

Query entities created after specified timestamp (temporal query).

**Parameters:**
- `cutoff_timestamp` (str): ISO8601 timestamp (e.g., `'2025-01-15T00:00:00Z'`)
- `entity_types` (Optional[List[EntityType]]): Filter by entity type
- `min_confidence` (float, default=0.0): Minimum confidence threshold

**Returns:**
- `List[Entity]`: Entities sorted by `first_seen_at` (descending, newest first)

**Example:**
```python
from datetime import datetime, timedelta, timezone

# Get entities from last 24 hours
cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
recent_entities = kg_query.entities_since(cutoff, min_confidence=0.7)

print(f"Found {len(recent_entities)} recent entities")
```

**Performance:**
- Target: <30ms

---

##### `query_entities(entity_type: Optional[EntityType] = None, name_pattern: Optional[str] = None, min_confidence: float = 0.0) -> List[Entity]`

Generic entity query with filtering.

**Parameters:**
- `entity_type` (Optional[EntityType]): Filter by type
- `name_pattern` (Optional[str]): SQL LIKE pattern (e.g., `'%pytest%'`)
- `min_confidence` (float, default=0.0): Minimum confidence threshold

**Returns:**
- `List[Entity]`: Matching entities sorted by confidence (descending)

**Example:**
```python
from mapify_cli.entity_extractor import EntityType

# Find all tools
tools = kg_query.query_entities(entity_type=EntityType.TOOL)

# Find entities with "test" in name
test_entities = kg_query.query_entities(name_pattern='%test%')

# Combine filters
high_conf_tools = kg_query.query_entities(
    entity_type=EntityType.TOOL,
    min_confidence=0.8
)
```

**Performance:**
- Target: <50ms

---

##### `query_relationships(relationship_type: Optional[RelationshipType] = None, source_id: Optional[str] = None, target_id: Optional[str] = None, min_confidence: float = 0.0) -> List[Relationship]`

Generic relationship query with filtering.

**Parameters:**
- `relationship_type` (Optional[RelationshipType]): Filter by type
- `source_id` (Optional[str]): Filter by source entity
- `target_id` (Optional[str]): Filter by target entity
- `min_confidence` (float, default=0.0): Minimum confidence threshold

**Returns:**
- `List[Relationship]`: Matching relationships sorted by confidence (descending)

**Example:**
```python
from mapify_cli.relationship_detector import RelationshipType

# Find all USES relationships
uses_rels = kg_query.query_relationships(relationship_type=RelationshipType.USES)

# Find all relationships from pytest
pytest_rels = kg_query.query_relationships(source_id='ent-pytest')

# Find all relationships to Python
python_rels = kg_query.query_relationships(target_id='ent-python')
```

**Performance:**
- Target: <50ms

---

##### `get_entity_provenance(entity_id: str) -> List[Dict]`

Get provenance records showing which bullets mentioned this entity.

**Parameters:**
- `entity_id` (str): Entity ID to get provenance for

**Returns:**
- `List[Dict]`: Provenance records with keys: `bullet_id`, `extraction_method`, `confidence`, `extracted_at`, `metadata`

**Example:**
```python
provenance = kg_query.get_entity_provenance('ent-pytest')

for record in provenance:
    print(f"Extracted from bullet {record['bullet_id']} "
          f"via {record['extraction_method']} "
          f"(conf: {record['confidence']:.2f})")
```

**Performance:**
- Target: <20ms

---

### Path Dataclass

Represents a path through the knowledge graph.

#### Fields

- **`length`** (int): Number of hops in path
- **`confidence`** (float): Minimum confidence of all relationships in path
- **`relationships`** (List[Relationship]): Edges in path (ordered)

#### Methods

##### `entities() -> List[str]`

Get entity IDs in path (ordered from source to target).

**Returns:**
- `List[str]`: Entity IDs

**Example:**
```python
path = paths[0]
print(path.entities())
# ['ent-pytest', 'ent-python', 'ent-unittest']
```

---

### Knowledge Graph Query Module Functions

#### `find_paths(db_conn, source_id, target_id, **kwargs) -> List[Path]`

Convenience function for one-off path finding.

#### `get_neighbors(db_conn, entity_id, **kwargs) -> List[Tuple[Entity, Relationship]]`

Convenience function for neighbor queries.

#### `entities_since(db_conn, cutoff_timestamp, **kwargs) -> List[Entity]`

Convenience function for temporal queries.

#### `query_entities(db_conn, **kwargs) -> List[Entity]`

Convenience function for entity queries.

#### `query_relationships(db_conn, **kwargs) -> List[Relationship]`

Convenience function for relationship queries.

#### `get_entity_provenance(db_conn, entity_id) -> List[Dict]`

Convenience function for provenance queries.

---

## Contradiction Detector

Module: `mapify_cli.contradiction_detector`

### ContradictionDetector Class

Contradiction detection and resolution suggestion engine.

#### Methods

##### `detect_contradictions(db_conn: sqlite3.Connection, min_confidence: float = 0.7) -> List[Contradiction]`

Detect all CONTRADICTS relationships in knowledge graph.

**Parameters:**
- `db_conn`: SQLite database connection
- `min_confidence` (float, default=0.7): Minimum relationship confidence threshold

**Returns:**
- `List[Contradiction]`: Contradictions with severity and resolution suggestions

**Example:**
```python
from mapify_cli.contradiction_detector import ContradictionDetector

detector = ContradictionDetector()
contradictions = detector.detect_contradictions(db_conn, min_confidence=0.7)

for contra in contradictions:
    print(f"[{contra.severity.upper()}] {contra.entity_a.name} vs {contra.entity_b.name}")
    print(f"  {contra.description}")
    print(f"  → {contra.resolution_suggestion}\n")
```

**Severity Levels:**
- **High** (0.8+): High confidence relationship AND high confidence entities
- **Medium** (0.7-0.8): Medium confidence OR one entity is medium confidence
- **Low** (<0.7): Low confidence relationship OR both entities low confidence

**Performance:**
- Target: <50ms for typical playbooks

---

##### `find_entity_contradictions(db_conn: sqlite3.Connection, entity_id: str, min_confidence: float = 0.7) -> List[Contradiction]`

Find contradictions involving specific entity.

**Parameters:**
- `db_conn`: SQLite database connection
- `entity_id` (str): Entity ID to check for conflicts
- `min_confidence` (float, default=0.7): Minimum confidence threshold

**Returns:**
- `List[Contradiction]`: Contradictions involving this entity

**Example:**
```python
# Check if new pattern conflicts with existing knowledge
conflicts = detector.find_entity_contradictions(db_conn, 'ent-generic-exception')

if conflicts:
    print(f"Warning: {len(conflicts)} conflicts found!")
    for conflict in conflicts:
        print(f"  - Conflicts with: {conflict.entity_b.name}")
```

**Performance:**
- Target: <30ms

---

##### `check_new_pattern_conflicts(db_conn: sqlite3.Connection, pattern_text: str, entities: List[Entity], min_confidence: float = 0.7) -> List[Contradiction]`

Check if new pattern conflicts with existing knowledge (Curator integration).

**Parameters:**
- `db_conn`: SQLite database connection
- `pattern_text` (str): New pattern content
- `entities` (List[Entity]): Entities extracted from pattern
- `min_confidence` (float, default=0.7): Minimum confidence threshold

**Returns:**
- `List[Contradiction]`: Conflicts with existing patterns

**Example:**
```python
from mapify_cli.entity_extractor import extract_entities

new_pattern = "Always use generic exception handling for simplicity"
entities = extract_entities(new_pattern)

conflicts = detector.check_new_pattern_conflicts(db_conn, new_pattern, entities)

if conflicts:
    print("⚠️  New pattern conflicts with existing best practices:")
    for conflict in conflicts:
        print(f"  - {conflict.description}")
        print(f"    Resolution: {conflict.resolution_suggestion}")
```

**Performance:**
- Target: <100ms

---

##### `get_contradiction_report(db_conn: sqlite3.Connection, min_confidence: float = 0.7, group_by: str = 'severity') -> Dict`

Generate contradiction report with grouping.

**Parameters:**
- `db_conn`: SQLite database connection
- `min_confidence` (float, default=0.7): Minimum confidence threshold
- `group_by` (str): Grouping strategy: `'severity'`, `'entity_type'`, or `'none'`

**Returns:**
- `Dict`: Report with keys: `total_count`, `groups`, `summary`

**Example:**
```python
report = detector.get_contradiction_report(db_conn, group_by='severity')

print(report['summary'])
# "Found 5 contradictions: 2 high severity, 2 medium severity, 1 low severity"

for severity, contradictions in report['groups'].items():
    print(f"\n{severity.upper()} Severity ({len(contradictions)}):")
    for contra in contradictions:
        print(f"  - {contra.entity_a.name} vs {contra.entity_b.name}")
```

**Performance:**
- Target: <100ms

---

### Contradiction Dataclass

Represents a detected contradiction with resolution guidance.

#### Fields

- **`id`** (str): Unique contradiction ID in format `contra-{uuid}`
- **`entity_a`** (Entity): First conflicting entity
- **`entity_b`** (Entity): Second conflicting entity
- **`relationship`** (Relationship): CONTRADICTS relationship
- **`severity`** (str): `'high'`, `'medium'`, or `'low'`
- **`description`** (str): Human-readable description
- **`resolution_suggestion`** (str): Actionable resolution guidance

#### Example

```python
# Contradiction automatically includes resolution suggestion
print(contradiction.description)
# "Entity 'generic-exception' contradicts 'specific-exceptions'"

print(contradiction.resolution_suggestion)
# "Consider deprecating older entity 'generic-exception' in favor of newer higher-confidence entity 'specific-exceptions'"
```

---

### Contradiction Detector Module Functions

#### `detect_contradictions(db_conn, **kwargs) -> List[Contradiction]`

Convenience function for detecting all contradictions.

#### `find_entity_contradictions(db_conn, entity_id, **kwargs) -> List[Contradiction]`

Convenience function for entity-specific conflict checking.

#### `check_new_pattern_conflicts(db_conn, pattern_text, entities, **kwargs) -> List[Contradiction]`

Convenience function for new pattern validation.

#### `get_contradiction_report(db_conn, **kwargs) -> Dict`

Convenience function for generating reports.

---

## Confidence Scoring System

Confidence scores represent extraction/relationship quality on a 0.0-1.0 scale.

### Entity Confidence

| Score Range | Quality     | Examples                                      |
|-------------|-------------|-----------------------------------------------|
| 0.9-1.0     | Very High   | Code blocks, explicit imports, backticks      |
| 0.7-0.9     | High        | Keyword matches, pattern suffixes             |
| 0.5-0.7     | Medium      | Inferred from context, proximity-based        |
| 0.3-0.5     | Low         | Ambiguous mentions, weak context              |

**Confidence Factors:**
- **Extraction method**: Code blocks (0.9), imports (0.8), keywords (0.7)
- **Context strength**: Negative context for antipatterns (+0.1), technical terms (+0.05)
- **Frequency**: Multiple mentions (+0.05 per mention, capped at +0.15)

### Relationship Confidence

| Score Range | Quality     | Examples                                      |
|-------------|-------------|-----------------------------------------------|
| 0.8-1.0     | Very High   | Explicit patterns ("X uses Y", "X depends on Y") |
| 0.6-0.8     | High        | Implicit patterns ("X with Y", "X needs Y")   |
| 0.4-0.6     | Medium      | Proximity-based, weak verbs                   |

**Confidence Factors:**
- **Pattern explicitness**: Direct verbs (0.8-0.9), prepositions (0.6-0.7)
- **Entity confidence**: Relationship confidence ≤ min(entity_a.conf, entity_b.conf)
- **Context clarity**: Clear sentence structure (+0.1), ambiguous phrasing (-0.1)

### Contradiction Severity

| Severity | Criteria                                      | Action                |
|----------|-----------------------------------------------|-----------------------|
| High     | Relationship ≥0.8 AND both entities >0.8      | Immediate review      |
| Medium   | Relationship 0.7-0.8 OR one entity 0.6-0.8    | Review when convenient|
| Low      | Relationship <0.7 OR both entities <0.6       | Low priority          |

---

## Performance Characteristics

All performance targets are based on typical playbook sizes (<1000 bullets, <10K entities).

### Entity Extraction

- **Small text** (1KB): <10ms
- **Medium text** (10KB): <50ms
- **Large text** (100KB): <100ms
- **Accuracy**: ≥80% on test corpus

### Relationship Detection

- **Small text** (5 entities): <20ms
- **Medium text** (20 entities): <100ms
- **Accuracy**: ≥70% on test corpus

### Graph Queries

- **`find_paths`**: <100ms (typical case: 1-3 hops)
- **`get_neighbors`**: <50ms
- **`entities_since`**: <30ms
- **`query_entities`**: <50ms
- **`query_relationships`**: <50ms
- **`get_entity_provenance`**: <20ms

### Contradiction Detection

- **`detect_contradictions`**: <50ms (100 contradictions)
- **`find_entity_contradictions`**: <30ms
- **`check_new_pattern_conflicts`**: <100ms
- **`get_contradiction_report`**: <100ms

### Scalability

| Dataset Size           | Query Performance | Notes                              |
|------------------------|-------------------|------------------------------------|
| 1K entities            | <50ms             | Typical personal playbook          |
| 10K entities           | <100ms            | Large team playbook                |
| 50K entities           | <500ms            | Enterprise-scale (requires tuning) |

**Optimization strategies for large datasets:**
- Use `min_confidence` filters to reduce result sets
- Filter by `entity_type` or `relationship_type` for targeted queries
- Implement pagination for UI displays
- Use FTS5 for full-text search (optimized for large corpora)

---

## Migration & Compatibility

All modules are compatible with schema v3.0. For schema v2.1 databases, automatic migration occurs via `PlaybookManager`.

See:
- [Migration Guide](./MIGRATION_V2.1_TO_V3.0.md)
- [Schema ERD](./ERD_v3.0.md)
- [Rollback Guide](./MIGRATION_ROLLBACK.md)

---

## Support & Resources

- **GitHub Issues**: https://github.com/azalio/map-framework/issues
- **Usage Examples**: [USAGE.md](../USAGE.md)
- **Architecture Documentation**: [ARCHITECTURE.md](../ARCHITECTURE.md)
- **Test Suite**: `tests/test_entity_extractor.py`, `tests/test_relationship_detector.py`, etc.

---

*Last updated: 2025-01-15 (schema v3.0)*
