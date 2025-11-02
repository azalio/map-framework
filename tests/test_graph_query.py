"""
Comprehensive tests for Knowledge Graph Query Interface.

Tests cover:
1. Path finding (direct, indirect, no path, cycles, multiple paths)
2. Neighbor queries (outgoing, incoming, both, type filters)
3. Temporal queries (entities_since)
4. Generic queries (query_entities, query_relationships)
5. Provenance queries
6. Performance benchmarks (<100ms target)
7. Integration with PlaybookManager
"""

import pytest
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile

# Import modules under test
from mapify_cli.graph_query import (
    KnowledgeGraphQuery,
    find_paths,
    get_neighbors,
    entities_since,
    query_entities,
    query_relationships,
    get_entity_provenance
)
from mapify_cli.entity_extractor import EntityType
from mapify_cli.relationship_detector import RelationshipType
from mapify_cli.playbook_manager import PlaybookManager
from mapify_cli.schemas import SCHEMA_V3_0_SQL


@pytest.fixture
def temp_db():
    """Create temporary SQLite database with KG schema."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.db', delete=False) as f:
        db_path = f.name

    # Create schema
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")

    # Create bullets table (required for relationships FK)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bullets (
            id TEXT PRIMARY KEY,
            section TEXT NOT NULL,
            content TEXT NOT NULL,
            helpful_count INTEGER DEFAULT 0,
            harmful_count INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            last_used_at TEXT NOT NULL
        )
    """)

    # Create metadata table (required for schema)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # Create KG schema
    conn.executescript(SCHEMA_V3_0_SQL)
    conn.commit()

    yield conn

    # Cleanup
    conn.close()
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def sample_graph(temp_db):
    """
    Create sample knowledge graph for testing.

    Graph structure:
        pytest (TOOL) --USES--> Python (TECHNOLOGY)
        pytest --DEPENDS_ON--> unittest (TOOL)
        MAP-workflow (WORKFLOW) --DEPENDS_ON--> playbook.db (TOOL)
        playbook.db --SUPERSEDES--> playbook.json (TOOL)
        retry-pattern (PATTERN) --PREVENTS--> timeout-error (ERROR_TYPE)
        generic-exception (ANTIPATTERN) --CONTRADICTS--> specific-exceptions (PATTERN)

    Path tests:
        - Direct: pytest -> Python (1 hop)
        - Indirect: pytest -> unittest (1 hop), no 2-hop path
        - No path: pytest -> MAP-workflow (disconnected components)
        - Transitive: playbook.json -> playbook.db -> MAP-workflow (2 hops via SUPERSEDES + DEPENDS_ON)
    """
    conn = temp_db
    now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat().replace('+00:00', 'Z')

    # Insert bullets (for FK constraints)
    bullets = [
        ('impl-0001', 'IMPLEMENTATION_PATTERNS', 'Use pytest for testing'),
        ('impl-0002', 'IMPLEMENTATION_PATTERNS', 'MAP workflow depends on playbook.db'),
        ('impl-0003', 'IMPLEMENTATION_PATTERNS', 'Retry pattern prevents timeouts'),
        ('anti-0001', 'ERROR_PATTERNS', 'Avoid generic exceptions'),
    ]
    for bullet_id, section, content in bullets:
        conn.execute("""
            INSERT INTO bullets (id, section, content, created_at, last_used_at)
            VALUES (?, ?, ?, ?, ?)
        """, (bullet_id, section, content, now, now))

    # Insert entities
    entities = [
        ('ent-pytest', 'TOOL', 'pytest', 0.9, yesterday, now),
        ('ent-python', 'TECHNOLOGY', 'Python', 0.95, yesterday, now),
        ('ent-unittest', 'TOOL', 'unittest', 0.85, yesterday, now),
        ('ent-map-workflow', 'WORKFLOW', 'MAP-workflow', 0.8, now, now),  # Created today
        ('ent-playbook-db', 'TOOL', 'playbook.db', 0.9, now, now),  # Created today
        ('ent-playbook-json', 'TOOL', 'playbook.json', 0.7, yesterday, yesterday),  # Deprecated
        ('ent-retry-pattern', 'PATTERN', 'retry-pattern', 0.85, yesterday, now),
        ('ent-timeout-error', 'ERROR_TYPE', 'timeout-error', 0.8, yesterday, now),
        ('ent-generic-exception', 'ANTIPATTERN', 'generic-exception-catch', 0.9, yesterday, now),
        ('ent-specific-exceptions', 'PATTERN', 'specific-exceptions', 0.9, yesterday, now),
    ]

    for entity_id, entity_type, name, confidence, first_seen, last_seen in entities:
        conn.execute("""
            INSERT INTO entities (id, type, name, confidence, first_seen_at, last_seen_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (entity_id, entity_type, name, confidence, first_seen, last_seen, now, now))

    # Insert relationships
    relationships = [
        ('rel-001', 'ent-pytest', 'ent-python', 'USES', 'impl-0001', 0.9),
        ('rel-002', 'ent-pytest', 'ent-unittest', 'DEPENDS_ON', 'impl-0001', 0.8),
        ('rel-003', 'ent-map-workflow', 'ent-playbook-db', 'DEPENDS_ON', 'impl-0002', 0.85),
        ('rel-004', 'ent-playbook-db', 'ent-playbook-json', 'SUPERSEDES', 'impl-0002', 0.9),
        ('rel-005', 'ent-retry-pattern', 'ent-timeout-error', 'PREVENTS', 'impl-0003', 0.8),
        ('rel-006', 'ent-generic-exception', 'ent-specific-exceptions', 'CONTRADICTS', 'anti-0001', 0.85),
    ]

    for rel_id, source, target, rel_type, bullet_id, confidence in relationships:
        conn.execute("""
            INSERT INTO relationships (id, source_entity_id, target_entity_id, type, created_from_bullet_id, confidence, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (rel_id, source, target, rel_type, bullet_id, confidence, now, now))

    # Insert provenance
    provenance_records = [
        ('prov-001', 'ent-pytest', None, 'impl-0001', 'RULE_BASED', 0.9, now),
        ('prov-002', 'ent-python', None, 'impl-0001', 'RULE_BASED', 0.95, now),
        ('prov-003', None, 'rel-001', 'impl-0001', 'RULE_BASED', 0.9, now),
    ]

    for prov_id, entity_id, rel_id, bullet_id, method, confidence, extracted_at in provenance_records:
        conn.execute("""
            INSERT INTO provenance (id, entity_id, relationship_id, source_bullet_id, extraction_method, extraction_confidence, extracted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (prov_id, entity_id, rel_id, bullet_id, method, confidence, extracted_at))

    conn.commit()
    return conn


# ==============================================================================
# PATH FINDING TESTS
# ==============================================================================

def test_find_paths_direct_path(sample_graph):
    """Test finding direct path (1 hop): pytest -> Python."""
    kg_query = KnowledgeGraphQuery(sample_graph)

    paths = kg_query.find_paths('ent-pytest', 'ent-python', max_depth=3)

    assert len(paths) == 1
    assert paths[0].length == 1
    assert paths[0].confidence == 0.9
    assert paths[0].relationships[0].type == RelationshipType.USES
    assert paths[0].entities() == ['ent-pytest', 'ent-python']


def test_find_paths_indirect_path(sample_graph):
    """Test finding indirect path (2 hops): playbook.json -> playbook.db -> MAP-workflow."""
    kg_query = KnowledgeGraphQuery(sample_graph)

    # Note: Path is reversed because relationships are directional
    # playbook.db SUPERSEDES playbook.json (playbook.db is source)
    # MAP-workflow DEPENDS_ON playbook.db (MAP-workflow is source)
    # So there's no path from playbook.json -> MAP-workflow following relationship directions

    # But there IS a path from MAP-workflow -> playbook.json (2 hops)
    paths = kg_query.find_paths('ent-map-workflow', 'ent-playbook-json', max_depth=3)

    assert len(paths) == 1
    assert paths[0].length == 2
    # Path: MAP-workflow --DEPENDS_ON--> playbook.db --SUPERSEDES--> playbook.json
    assert paths[0].relationships[0].type == RelationshipType.DEPENDS_ON
    assert paths[0].relationships[1].type == RelationshipType.SUPERSEDES
    assert paths[0].entities() == ['ent-map-workflow', 'ent-playbook-db', 'ent-playbook-json']


def test_find_paths_no_path(sample_graph):
    """Test no path exists between disconnected components."""
    kg_query = KnowledgeGraphQuery(sample_graph)

    # pytest and retry-pattern are in different graph components
    paths = kg_query.find_paths('ent-pytest', 'ent-retry-pattern', max_depth=3)

    assert len(paths) == 0


def test_find_paths_self_path(sample_graph):
    """Test path to self returns empty list."""
    kg_query = KnowledgeGraphQuery(sample_graph)

    paths = kg_query.find_paths('ent-pytest', 'ent-pytest', max_depth=3)

    assert len(paths) == 0


def test_find_paths_with_cycle_termination(sample_graph):
    """Test cycle handling with max_depth termination."""
    # Add a cycle: Python -> pytest (creates cycle with existing pytest -> Python)
    now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    sample_graph.execute("""
        INSERT INTO relationships (id, source_entity_id, target_entity_id, type, created_from_bullet_id, confidence, created_at, updated_at)
        VALUES ('rel-cycle', 'ent-python', 'ent-pytest', 'USES', 'impl-0001', 0.7, ?, ?)
    """, (now, now))
    sample_graph.commit()

    kg_query = KnowledgeGraphQuery(sample_graph)

    # Should still find direct path without getting stuck in cycle
    paths = kg_query.find_paths('ent-pytest', 'ent-python', max_depth=3)

    assert len(paths) >= 1
    # Should find direct path (1 hop) first
    assert paths[0].length == 1


def test_find_paths_with_type_filter(sample_graph):
    """Test filtering paths by relationship type."""
    kg_query = KnowledgeGraphQuery(sample_graph)

    # pytest has both USES and DEPENDS_ON relationships
    # Filter to only USES
    paths = kg_query.find_paths(
        'ent-pytest',
        'ent-python',
        max_depth=2,
        relationship_types=[RelationshipType.USES]
    )

    assert len(paths) == 1
    assert paths[0].relationships[0].type == RelationshipType.USES

    # Filter to only DEPENDS_ON (should not find Python path)
    paths = kg_query.find_paths(
        'ent-pytest',
        'ent-python',
        max_depth=2,
        relationship_types=[RelationshipType.DEPENDS_ON]
    )

    assert len(paths) == 0


def test_find_paths_validation(sample_graph):
    """Test input validation for find_paths."""
    kg_query = KnowledgeGraphQuery(sample_graph)

    # Invalid source ID (doesn't start with 'ent-')
    with pytest.raises(ValueError, match="must start with 'ent-'"):
        kg_query.find_paths('pytest', 'ent-python')

    # Invalid target ID
    with pytest.raises(ValueError, match="must start with 'ent-'"):
        kg_query.find_paths('ent-pytest', 'python')


# ==============================================================================
# NEIGHBOR QUERIES
# ==============================================================================

def test_get_neighbors_outgoing(sample_graph):
    """Test getting outgoing neighbors (entity as source)."""
    kg_query = KnowledgeGraphQuery(sample_graph)

    neighbors = kg_query.get_neighbors('ent-pytest', direction='outgoing')

    # pytest has 2 outgoing relationships: USES Python, DEPENDS_ON unittest
    assert len(neighbors) == 2

    # Should be sorted by confidence descending
    entity1, rel1 = neighbors[0]
    assert entity1.name in ('Python', 'unittest')
    assert rel1.confidence >= neighbors[1][1].confidence


def test_get_neighbors_incoming(sample_graph):
    """Test getting incoming neighbors (entity as target)."""
    kg_query = KnowledgeGraphQuery(sample_graph)

    neighbors = kg_query.get_neighbors('ent-python', direction='incoming')

    # Python is target of: pytest USES Python
    assert len(neighbors) == 1
    entity, rel = neighbors[0]
    assert entity.id == 'ent-pytest'
    assert rel.type == RelationshipType.USES


def test_get_neighbors_both_directions(sample_graph):
    """Test getting neighbors in both directions."""
    kg_query = KnowledgeGraphQuery(sample_graph)

    neighbors = kg_query.get_neighbors('ent-playbook-db', direction='both')

    # playbook.db has:
    # - Incoming: MAP-workflow DEPENDS_ON playbook.db
    # - Outgoing: playbook.db SUPERSEDES playbook.json
    assert len(neighbors) == 2

    entity_ids = {entity.id for entity, _ in neighbors}
    assert 'ent-map-workflow' in entity_ids
    assert 'ent-playbook-json' in entity_ids


def test_get_neighbors_with_type_filter(sample_graph):
    """Test filtering neighbors by relationship type."""
    kg_query = KnowledgeGraphQuery(sample_graph)

    # Filter pytest neighbors to only USES relationships
    neighbors = kg_query.get_neighbors(
        'ent-pytest',
        direction='outgoing',
        relationship_types=[RelationshipType.USES]
    )

    assert len(neighbors) == 1
    entity, rel = neighbors[0]
    assert entity.name == 'Python'
    assert rel.type == RelationshipType.USES


def test_get_neighbors_with_confidence_threshold(sample_graph):
    """Test filtering neighbors by confidence threshold."""
    kg_query = KnowledgeGraphQuery(sample_graph)

    # Get pytest neighbors with high confidence (>= 0.85)
    neighbors = kg_query.get_neighbors(
        'ent-pytest',
        direction='outgoing',
        min_confidence=0.85
    )

    # Only USES Python (0.9) should pass, not DEPENDS_ON unittest (0.8)
    assert len(neighbors) == 1
    entity, rel = neighbors[0]
    assert entity.name == 'Python'
    assert rel.confidence >= 0.85


def test_get_neighbors_validation(sample_graph):
    """Test input validation for get_neighbors."""
    kg_query = KnowledgeGraphQuery(sample_graph)

    # Invalid entity ID
    with pytest.raises(ValueError, match="must start with 'ent-'"):
        kg_query.get_neighbors('pytest')

    # Invalid direction
    with pytest.raises(ValueError, match="Direction must be"):
        kg_query.get_neighbors('ent-pytest', direction='invalid')


# ==============================================================================
# TEMPORAL QUERIES
# ==============================================================================

def test_entities_since(sample_graph):
    """Test getting entities created after timestamp."""
    kg_query = KnowledgeGraphQuery(sample_graph)

    # Get entities created today (MAP-workflow, playbook.db)
    cutoff = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat().replace('+00:00', 'Z')
    recent = kg_query.entities_since(cutoff)

    assert len(recent) == 2
    entity_names = {e.name for e in recent}
    assert 'MAP-workflow' in entity_names
    assert 'playbook.db' in entity_names

    # Should be sorted by first_seen_at DESC (newest first)
    assert recent[0].first_seen_at >= recent[1].first_seen_at


def test_entities_since_with_type_filter(sample_graph):
    """Test temporal query with entity type filter."""
    kg_query = KnowledgeGraphQuery(sample_graph)

    cutoff = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat().replace('+00:00', 'Z')

    # Filter to only WORKFLOW entities created today
    recent = kg_query.entities_since(
        cutoff,
        entity_types=[EntityType.WORKFLOW]
    )

    assert len(recent) == 1
    assert recent[0].name == 'MAP-workflow'
    assert recent[0].type == EntityType.WORKFLOW


def test_entities_since_with_confidence_threshold(sample_graph):
    """Test temporal query with confidence filter."""
    kg_query = KnowledgeGraphQuery(sample_graph)

    cutoff = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat().replace('+00:00', 'Z')

    # Get recent entities with high confidence (>= 0.85)
    recent = kg_query.entities_since(cutoff, min_confidence=0.85)

    # MAP-workflow (0.8) should be filtered out
    assert len(recent) == 1
    assert recent[0].name == 'playbook.db'
    assert recent[0].confidence >= 0.85


# ==============================================================================
# GENERIC QUERIES
# ==============================================================================

def test_query_entities_by_type(sample_graph):
    """Test querying entities by type."""
    kg_query = KnowledgeGraphQuery(sample_graph)

    tools = kg_query.query_entities(entity_type=EntityType.TOOL)

    # Should find: pytest, unittest, playbook.db, playbook.json
    assert len(tools) == 4
    tool_names = {e.name for e in tools}
    assert 'pytest' in tool_names
    assert 'unittest' in tool_names


def test_query_entities_by_confidence(sample_graph):
    """Test querying entities by confidence threshold."""
    kg_query = KnowledgeGraphQuery(sample_graph)

    high_confidence = kg_query.query_entities(min_confidence=0.9)

    # Should find: pytest (0.9), Python (0.95), playbook.db (0.9), generic-exception (0.9), specific-exceptions (0.9)
    assert len(high_confidence) == 5
    for entity in high_confidence:
        assert entity.confidence >= 0.9


def test_query_entities_by_name_pattern(sample_graph):
    """Test querying entities by name pattern."""
    kg_query = KnowledgeGraphQuery(sample_graph)

    # Find entities with 'playbook' in name
    playbook_entities = kg_query.query_entities(name_pattern='%playbook%')

    assert len(playbook_entities) == 2
    names = {e.name for e in playbook_entities}
    assert 'playbook.db' in names
    assert 'playbook.json' in names


def test_query_relationships_by_type(sample_graph):
    """Test querying relationships by type."""
    kg_query = KnowledgeGraphQuery(sample_graph)

    depends_on = kg_query.query_relationships(relationship_type=RelationshipType.DEPENDS_ON)

    # Should find 2 DEPENDS_ON relationships
    assert len(depends_on) == 2
    for rel in depends_on:
        assert rel.type == RelationshipType.DEPENDS_ON


def test_query_relationships_by_source(sample_graph):
    """Test querying relationships by source entity."""
    kg_query = KnowledgeGraphQuery(sample_graph)

    pytest_rels = kg_query.query_relationships(source_id='ent-pytest')

    # pytest has 2 outgoing relationships
    assert len(pytest_rels) == 2
    for rel in pytest_rels:
        assert rel.source_entity_id == 'ent-pytest'


def test_query_relationships_by_target(sample_graph):
    """Test querying relationships by target entity."""
    kg_query = KnowledgeGraphQuery(sample_graph)

    python_rels = kg_query.query_relationships(target_id='ent-python')

    # Python has 1 incoming relationship (pytest USES Python)
    assert len(python_rels) == 1
    assert python_rels[0].target_entity_id == 'ent-python'


def test_query_relationships_validation(sample_graph):
    """Test input validation for query_relationships."""
    kg_query = KnowledgeGraphQuery(sample_graph)

    # Invalid source ID
    with pytest.raises(ValueError, match="must start with 'ent-'"):
        kg_query.query_relationships(source_id='pytest')

    # Invalid target ID
    with pytest.raises(ValueError, match="must start with 'ent-'"):
        kg_query.query_relationships(target_id='python')


# ==============================================================================
# PROVENANCE QUERIES
# ==============================================================================

def test_get_entity_provenance(sample_graph):
    """Test getting entity provenance records."""
    kg_query = KnowledgeGraphQuery(sample_graph)

    provenance = kg_query.get_entity_provenance('ent-pytest')

    assert len(provenance) == 1
    record = provenance[0]
    assert record['bullet_id'] == 'impl-0001'
    assert record['extraction_method'] == 'RULE_BASED'
    assert record['confidence'] == 0.9
    assert 'extracted_at' in record


def test_get_entity_provenance_validation(sample_graph):
    """Test input validation for get_entity_provenance."""
    kg_query = KnowledgeGraphQuery(sample_graph)

    # Invalid entity ID
    with pytest.raises(ValueError, match="must start with 'ent-'"):
        kg_query.get_entity_provenance('pytest')


def test_get_entity_provenance_no_records(sample_graph):
    """Test provenance query for entity with no records."""
    kg_query = KnowledgeGraphQuery(sample_graph)

    # unittest entity has no provenance records
    provenance = kg_query.get_entity_provenance('ent-unittest')

    assert len(provenance) == 0


# ==============================================================================
# PERFORMANCE TESTS
# ==============================================================================

def test_find_paths_performance(sample_graph):
    """Test find_paths performance (<100ms)."""
    kg_query = KnowledgeGraphQuery(sample_graph)

    start = time.perf_counter()
    paths = kg_query.find_paths('ent-pytest', 'ent-python', max_depth=3)
    elapsed = (time.perf_counter() - start) * 1000  # Convert to ms

    assert isinstance(paths, list), "find_paths should return a list"
    assert elapsed < 100, f"find_paths took {elapsed:.2f}ms (target: <100ms)"


def test_get_neighbors_performance(sample_graph):
    """Test get_neighbors performance (<50ms)."""
    kg_query = KnowledgeGraphQuery(sample_graph)

    start = time.perf_counter()
    neighbors = kg_query.get_neighbors('ent-pytest', direction='both')
    elapsed = (time.perf_counter() - start) * 1000

    assert isinstance(neighbors, list), "get_neighbors should return a list"
    assert elapsed < 50, f"get_neighbors took {elapsed:.2f}ms (target: <50ms)"


def test_entities_since_performance(sample_graph):
    """Test entities_since performance (<30ms)."""
    kg_query = KnowledgeGraphQuery(sample_graph)

    cutoff = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat().replace('+00:00', 'Z')

    start = time.perf_counter()
    entities = kg_query.entities_since(cutoff)
    elapsed = (time.perf_counter() - start) * 1000

    assert isinstance(entities, list)
    assert elapsed < 30, f"entities_since took {elapsed:.2f}ms (target: <30ms)"


def test_query_entities_performance(sample_graph):
    """Test query_entities performance (<50ms)."""
    kg_query = KnowledgeGraphQuery(sample_graph)

    start = time.perf_counter()
    entities = kg_query.query_entities(entity_type=EntityType.TOOL)
    elapsed = (time.perf_counter() - start) * 1000

    assert isinstance(entities, list)
    assert elapsed < 50, f"query_entities took {elapsed:.2f}ms (target: <50ms)"


def test_get_provenance_performance(sample_graph):
    """Test get_entity_provenance performance (<20ms)."""
    kg_query = KnowledgeGraphQuery(sample_graph)

    start = time.perf_counter()
    provenance = kg_query.get_entity_provenance('ent-pytest')
    elapsed = (time.perf_counter() - start) * 1000

    assert provenance, "Provenance data should not be empty or None"
    assert elapsed < 20, f"get_entity_provenance took {elapsed:.2f}ms (target: <20ms)"


# ==============================================================================
# INTEGRATION TESTS
# ==============================================================================

def test_playbook_manager_kg_query_property():
    """Test PlaybookManager.kg_query property integration."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_playbook.db"

        # Create PlaybookManager (will auto-initialize database)
        pm = PlaybookManager(db_path=str(db_path))

        # Access kg_query property (should lazy-initialize)
        assert pm.kg_query is not None
        assert isinstance(pm.kg_query, KnowledgeGraphQuery)

        # Second access should return same instance
        kg_query_1 = pm.kg_query
        kg_query_2 = pm.kg_query
        assert kg_query_1 is kg_query_2


def test_end_to_end_graph_workflow():
    """
    End-to-end test: extract entities → detect relationships → query graph.

    This simulates the complete workflow:
    1. Extract entities from text
    2. Detect relationships between entities
    3. Insert into database
    4. Query graph
    """
    from mapify_cli.entity_extractor import EntityExtractor
    from mapify_cli.relationship_detector import RelationshipDetector

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_playbook.db"

        # Initialize PlaybookManager
        pm = PlaybookManager(db_path=str(db_path))

        # Step 1: Extract entities
        text = "Use pytest for testing Python applications. pytest uses Python and depends on unittest."
        extractor = EntityExtractor()
        entities = extractor.extract_entities(text)

        # Step 2: Detect relationships
        detector = RelationshipDetector()
        bullet_id = 'test-001'

        # Insert bullet first (FK requirement)
        now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        pm.db_conn.execute("""
            INSERT INTO bullets (id, section, content, created_at, last_used_at)
            VALUES (?, 'TEST', ?, ?, ?)
        """, (bullet_id, text, now, now))
        pm.db_conn.commit()

        relationships = detector.detect_relationships(text, entities, bullet_id)

        # Step 3: Insert entities into database
        for entity in entities:
            pm.db_conn.execute("""
                INSERT OR IGNORE INTO entities (id, type, name, confidence, first_seen_at, last_seen_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (entity.id, entity.type.value, entity.name, entity.confidence,
                  entity.first_seen_at, entity.last_seen_at, now, now))

        # Step 4: Insert relationships
        for rel in relationships:
            try:
                pm.db_conn.execute("""
                    INSERT OR IGNORE INTO relationships (id, source_entity_id, target_entity_id, type, created_from_bullet_id, confidence, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (rel.id, rel.source_entity_id, rel.target_entity_id, rel.type.value,
                      rel.created_from_bullet_id, rel.confidence, rel.created_at, rel.updated_at))
            except Exception as e:
                # Skip if relationship insertion fails (e.g., duplicate)
                pass

        pm.db_conn.commit()

        # Step 5: Query graph
        # Find path from pytest to Python
        paths = pm.kg_query.find_paths('ent-pytest', 'ent-python', max_depth=2)

        # Should find at least one path (pytest USES Python)
        assert len(paths) >= 1
        assert paths[0].length <= 2

        # Get pytest neighbors
        neighbors = pm.kg_query.get_neighbors('ent-pytest', direction='outgoing')
        assert len(neighbors) >= 1

        # Query all tools
        tools = pm.kg_query.query_entities(entity_type=EntityType.TOOL)
        tool_names = {e.name for e in tools}
        assert 'pytest' in tool_names


def test_module_level_convenience_functions(sample_graph):
    """Test module-level convenience functions."""
    from datetime import datetime, timezone, timedelta

    # Test find_paths convenience function
    paths = find_paths(sample_graph, 'ent-pytest', 'ent-python')
    assert len(paths) == 1

    # Test get_neighbors convenience function
    neighbors = get_neighbors(sample_graph, 'ent-pytest', direction='outgoing')
    assert len(neighbors) == 2

    # Test entities_since convenience function
    cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    recent_entities = entities_since(sample_graph, cutoff)
    assert len(recent_entities) > 0  # Should have entities from today

    # Test query_entities convenience function
    tools = query_entities(sample_graph, entity_type=EntityType.TOOL, min_confidence=0.7)
    assert len(tools) >= 1  # At least pytest

    # Test query_relationships convenience function
    uses_rels = query_relationships(sample_graph, relationship_type=RelationshipType.USES)
    assert len(uses_rels) >= 1  # pytest USES Python

    # Test get_entity_provenance convenience function
    provenance = get_entity_provenance(sample_graph, 'ent-pytest')
    assert len(provenance) >= 1  # At least one source bullet
