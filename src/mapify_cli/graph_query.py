"""
Knowledge Graph Query Interface for MAP Framework.

Provides efficient graph traversal and query operations on the Knowledge Graph
stored in playbook.db (entities, relationships, provenance tables).

Performance targets:
- find_paths(): <100ms for depth ≤3
- get_neighbors(): <50ms
- entities_since(): <30ms
- query_entities(): <50ms
- query_relationships(): <50ms
- get_entity_provenance(): <20ms

Based on: src/mapify_cli/schemas.py (SCHEMA_V3_0_SQL)
"""

import sqlite3
import json
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict, Any
from collections import deque

# Import Entity and Relationship data models
from mapify_cli.entity_extractor import Entity, EntityType
from mapify_cli.relationship_detector import Relationship, RelationshipType


@dataclass
class Path:
    """
    Represents a path through the knowledge graph.

    Attributes:
        relationships: List of relationships forming the path
        length: Number of hops (relationship count)
        confidence: Minimum confidence across all relationships in path
    """

    relationships: List[Relationship]
    length: int
    confidence: float

    def entities(self) -> List[str]:
        """
        Extract entity IDs in order along path.

        Returns:
            List of entity IDs: [source, intermediate_1, ..., intermediate_N, target]

        Example:
            Path with relationships: A→B, B→C
            Returns: ['ent-a', 'ent-b', 'ent-c']
        """
        if not self.relationships:
            return []

        # Start with source of first relationship
        entity_ids = [self.relationships[0].source_entity_id]

        # Add target of each relationship
        for rel in self.relationships:
            entity_ids.append(rel.target_entity_id)

        return entity_ids


class KnowledgeGraphQuery:
    """
    Query interface for Knowledge Graph operations.

    Provides efficient graph traversal, temporal queries, and provenance tracking
    using SQLite with optimized indexes.

    Performance optimizations:
    - Uses existing indexes (idx_entities_type, idx_rel_source, idx_rel_target, etc.)
    - Single-query fetches with JOINs (avoids N+1 queries)
    - LIMIT clauses to prevent memory issues
    - Parameterized queries for safety and caching

    Example:
        >>> from mapify_cli.playbook_manager import PlaybookManager
        >>> pm = PlaybookManager()
        >>> paths = pm.kg_query.find_paths('ent-pytest', 'ent-python', max_depth=2)
        >>> neighbors = pm.kg_query.get_neighbors('ent-pytest', direction='outgoing')
    """

    def __init__(self, db_conn: sqlite3.Connection):
        """
        Initialize query interface with existing database connection.

        Args:
            db_conn: SQLite connection from PlaybookManager

        Note:
            Connection must have row_factory set to sqlite3.Row for dict-like access
        """
        self.db_conn = db_conn

        # Ensure row_factory is set (should already be set by PlaybookManager)
        if self.db_conn.row_factory is None:
            self.db_conn.row_factory = sqlite3.Row

    def find_paths(
        self,
        source_id: str,
        target_id: str,
        max_depth: int = 3,
        relationship_types: Optional[List[RelationshipType]] = None,
    ) -> List[Path]:
        """
        Find all paths from source entity to target entity using BFS.

        Uses breadth-first search to return shortest paths first.
        Stops at max_depth to prevent infinite loops in cyclic graphs.

        Args:
            source_id: Source entity ID (must start with 'ent-')
            target_id: Target entity ID (must start with 'ent-')
            max_depth: Maximum number of hops (default: 3)
            relationship_types: Optional filter for relationship types

        Returns:
            List of Path objects sorted by length (shortest first)

        Edge cases:
            - source_id == target_id: returns empty list (no path to self)
            - No path exists: returns empty list
            - Multiple paths: returns all paths up to max_depth
            - Cyclic graph: terminates at max_depth

        Performance: <100ms for depth ≤3 (uses indexed queries)

        Example:
            >>> paths = kg_query.find_paths('ent-pytest', 'ent-python', max_depth=2)
            >>> paths[0].length
            1
            >>> paths[0].entities()
            ['ent-pytest', 'ent-python']
        """
        # Validate inputs
        if not source_id.startswith("ent-"):
            raise ValueError(
                f"Source entity ID must start with 'ent-', got {source_id}"
            )
        if not target_id.startswith("ent-"):
            raise ValueError(
                f"Target entity ID must start with 'ent-', got {target_id}"
            )

        # Edge case: path to self
        if source_id == target_id:
            return []

        # Edge case: invalid depth
        if max_depth < 1:
            return []

        # Build relationship type filter SQL
        type_filter_sql = ""
        type_params = []
        if relationship_types:
            type_placeholders = ",".join(["?" for _ in relationship_types])
            type_filter_sql = f"AND type IN ({type_placeholders})"
            type_params = [rt.value for rt in relationship_types]

        # BFS to find all paths
        # Queue entries: (current_entity_id, path_so_far, visited_entities)
        queue = deque([(source_id, [], {source_id})])
        found_paths = []

        while queue:
            current_id, current_path, visited = queue.popleft()

            # Stop if reached max depth
            if len(current_path) >= max_depth:
                continue

            # Fetch outgoing relationships from current entity
            cursor = self.db_conn.execute(
                f"""
                SELECT
                    id, source_entity_id, target_entity_id, type,
                    created_from_bullet_id, confidence, metadata,
                    created_at, updated_at
                FROM relationships
                WHERE source_entity_id = ?
                {type_filter_sql}
                ORDER BY confidence DESC
            """,
                [current_id] + type_params,
            )

            for row in cursor:
                # Reconstruct Relationship object
                rel = Relationship(
                    id=row["id"],
                    source_entity_id=row["source_entity_id"],
                    target_entity_id=row["target_entity_id"],
                    type=RelationshipType(row["type"]),
                    created_from_bullet_id=row["created_from_bullet_id"],
                    confidence=row["confidence"],
                    metadata=json.loads(row["metadata"]) if row["metadata"] else None,
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )

                next_id = rel.target_entity_id

                # Found target!
                if next_id == target_id:
                    path_relationships = current_path + [rel]
                    path_confidence = min(r.confidence for r in path_relationships)
                    found_paths.append(
                        Path(
                            relationships=path_relationships,
                            length=len(path_relationships),
                            confidence=path_confidence,
                        )
                    )
                    continue  # Don't explore beyond target

                # Avoid cycles: skip if already visited in this path
                if next_id in visited:
                    continue

                # Add to queue for further exploration
                queue.append(
                    (
                        next_id,
                        current_path + [rel],
                        visited | {next_id},  # Create new set with next_id added
                    )
                )

        # Sort paths by length (shortest first), then by confidence (highest first)
        found_paths.sort(key=lambda p: (p.length, -p.confidence))

        # Limit to 100 paths to prevent memory issues
        return found_paths[:100]

    def get_neighbors(
        self,
        entity_id: str,
        direction: str = "both",
        relationship_types: Optional[List[RelationshipType]] = None,
        min_confidence: float = 0.5,
    ) -> List[Tuple[Entity, Relationship]]:
        """
        Get neighboring entities connected to given entity.

        Uses single JOIN query for efficiency (avoids N+1 problem).

        Args:
            entity_id: Entity ID to get neighbors for
            direction: 'outgoing' (entity as source), 'incoming' (entity as target), 'both'
            relationship_types: Optional filter for relationship types
            min_confidence: Minimum confidence threshold (default: 0.5)

        Returns:
            List of (neighbor_entity, connecting_relationship) tuples
            Sorted by relationship confidence descending

        Edge cases:
            - No neighbors: returns empty list
            - Invalid direction: raises ValueError
            - Entity doesn't exist: returns empty list (not an error)

        Performance: <50ms (single JOIN query with indexes)

        Example:
            >>> neighbors = kg_query.get_neighbors('ent-pytest', direction='outgoing',
            ...                                      relationship_types=[RelationshipType.USES])
            >>> neighbor_entity, relationship = neighbors[0]
            >>> neighbor_entity.name
            'Python'
        """
        # Validate inputs
        if not entity_id.startswith("ent-"):
            raise ValueError(f"Entity ID must start with 'ent-', got {entity_id}")

        if direction not in ("outgoing", "incoming", "both"):
            raise ValueError(
                f"Direction must be 'outgoing', 'incoming', or 'both', got {direction}"
            )

        # Build SQL query based on direction
        if direction == "outgoing":
            direction_clause = "r.source_entity_id = ?"
            neighbor_id_column = "r.target_entity_id"
        elif direction == "incoming":
            direction_clause = "r.target_entity_id = ?"
            neighbor_id_column = "r.source_entity_id"
        else:  # both
            direction_clause = "(r.source_entity_id = ? OR r.target_entity_id = ?)"
            neighbor_id_column = "CASE WHEN r.source_entity_id = ? THEN r.target_entity_id ELSE r.source_entity_id END"

        # Build relationship type filter
        type_filter_sql = ""
        type_params = []
        if relationship_types:
            type_placeholders = ",".join(["?" for _ in relationship_types])
            type_filter_sql = f"AND r.type IN ({type_placeholders})"
            type_params = [rt.value for rt in relationship_types]

        # Build query parameters
        if direction == "both":
            query_params = (
                [entity_id, entity_id, entity_id] + type_params + [min_confidence]
            )
        else:
            query_params = [entity_id] + type_params + [min_confidence]

        # Execute JOIN query to fetch neighbors and relationships in one go
        cursor = self.db_conn.execute(
            f"""
            SELECT
                -- Entity columns
                e.id as entity_id,
                e.type as entity_type,
                e.name as entity_name,
                e.first_seen_at as entity_first_seen,
                e.last_seen_at as entity_last_seen,
                e.confidence as entity_confidence,
                e.metadata as entity_metadata,
                -- Relationship columns
                r.id as rel_id,
                r.source_entity_id as rel_source,
                r.target_entity_id as rel_target,
                r.type as rel_type,
                r.created_from_bullet_id as rel_bullet_id,
                r.confidence as rel_confidence,
                r.metadata as rel_metadata,
                r.created_at as rel_created_at,
                r.updated_at as rel_updated_at
            FROM relationships r
            INNER JOIN entities e ON e.id = {neighbor_id_column}
            WHERE {direction_clause}
            {type_filter_sql}
            AND r.confidence >= ?
            ORDER BY r.confidence DESC
            LIMIT 1000
        """,
            query_params,
        )

        # Reconstruct Entity and Relationship objects
        results = []
        for row in cursor:
            entity = Entity(
                id=row["entity_id"],
                type=EntityType(row["entity_type"]),
                name=row["entity_name"],
                confidence=row["entity_confidence"],
                first_seen_at=row["entity_first_seen"],
                last_seen_at=row["entity_last_seen"],
                metadata=(
                    json.loads(row["entity_metadata"])
                    if row["entity_metadata"]
                    else None
                ),
            )

            relationship = Relationship(
                id=row["rel_id"],
                source_entity_id=row["rel_source"],
                target_entity_id=row["rel_target"],
                type=RelationshipType(row["rel_type"]),
                created_from_bullet_id=row["rel_bullet_id"],
                confidence=row["rel_confidence"],
                metadata=(
                    json.loads(row["rel_metadata"]) if row["rel_metadata"] else None
                ),
                created_at=row["rel_created_at"],
                updated_at=row["rel_updated_at"],
            )

            results.append((entity, relationship))

        return results

    def entities_since(
        self,
        timestamp: str,
        entity_types: Optional[List[EntityType]] = None,
        min_confidence: float = 0.5,
    ) -> List[Entity]:
        """
        Get entities first seen after given timestamp.

        Uses indexed first_seen_at column for fast temporal queries.

        Args:
            timestamp: ISO8601 timestamp (e.g., '2024-01-01T00:00:00Z')
            entity_types: Optional filter for entity types
            min_confidence: Minimum confidence threshold (default: 0.5)

        Returns:
            List of Entity objects sorted by first_seen_at DESC (newest first)

        Performance: <30ms (uses idx_entities_last_seen index)

        Example:
            >>> from datetime import datetime, timedelta
            >>> cutoff = (datetime.now() - timedelta(days=1)).isoformat() + 'Z'
            >>> recent = kg_query.entities_since(cutoff)
        """
        # Build entity type filter
        type_filter_sql = ""
        type_params = []
        if entity_types:
            type_placeholders = ",".join(["?" for _ in entity_types])
            type_filter_sql = f"AND type IN ({type_placeholders})"
            type_params = [et.value for et in entity_types]

        # Execute query
        cursor = self.db_conn.execute(
            f"""
            SELECT
                id, type, name, confidence,
                first_seen_at, last_seen_at, metadata
            FROM entities
            WHERE first_seen_at > ?
            {type_filter_sql}
            AND confidence >= ?
            ORDER BY first_seen_at DESC
            LIMIT 1000
        """,
            [timestamp] + type_params + [min_confidence],
        )

        # Reconstruct Entity objects
        entities = []
        for row in cursor:
            entities.append(
                Entity(
                    id=row["id"],
                    type=EntityType(row["type"]),
                    name=row["name"],
                    confidence=row["confidence"],
                    first_seen_at=row["first_seen_at"],
                    last_seen_at=row["last_seen_at"],
                    metadata=json.loads(row["metadata"]) if row["metadata"] else None,
                )
            )

        return entities

    def query_entities(
        self,
        entity_type: Optional[EntityType] = None,
        min_confidence: float = 0.0,
        name_pattern: Optional[str] = None,
    ) -> List[Entity]:
        """
        Generic entity query with filters.

        Args:
            entity_type: Optional filter for entity type
            min_confidence: Minimum confidence threshold (default: 0.0)
            name_pattern: Optional LIKE pattern for name search (e.g., '%pytest%')

        Returns:
            List of Entity objects sorted by confidence DESC

        Performance: <50ms

        Example:
            >>> tools = kg_query.query_entities(entity_type=EntityType.TOOL, min_confidence=0.8)
            >>> pytest_related = kg_query.query_entities(name_pattern='%pytest%')
        """
        # Build filters
        filters = ["confidence >= ?"]
        params = [min_confidence]

        if entity_type:
            filters.append("type = ?")
            params.append(entity_type.value)

        if name_pattern:
            filters.append("name LIKE ?")
            params.append(name_pattern)

        where_clause = " AND ".join(filters)

        # Execute query
        cursor = self.db_conn.execute(
            f"""
            SELECT
                id, type, name, confidence,
                first_seen_at, last_seen_at, metadata
            FROM entities
            WHERE {where_clause}
            ORDER BY confidence DESC
            LIMIT 1000
        """,
            params,
        )

        # Reconstruct Entity objects
        entities = []
        for row in cursor:
            entities.append(
                Entity(
                    id=row["id"],
                    type=EntityType(row["type"]),
                    name=row["name"],
                    confidence=row["confidence"],
                    first_seen_at=row["first_seen_at"],
                    last_seen_at=row["last_seen_at"],
                    metadata=json.loads(row["metadata"]) if row["metadata"] else None,
                )
            )

        return entities

    def query_relationships(
        self,
        relationship_type: Optional[RelationshipType] = None,
        source_id: Optional[str] = None,
        target_id: Optional[str] = None,
        min_confidence: float = 0.0,
    ) -> List[Relationship]:
        """
        Generic relationship query with filters.

        Args:
            relationship_type: Optional filter for relationship type
            source_id: Optional filter for source entity ID
            target_id: Optional filter for target entity ID
            min_confidence: Minimum confidence threshold (default: 0.0)

        Returns:
            List of Relationship objects sorted by confidence DESC

        Performance: <50ms (uses composite indexes)

        Example:
            >>> uses_rels = kg_query.query_relationships(
            ...     relationship_type=RelationshipType.USES,
            ...     source_id='ent-pytest'
            ... )
        """
        # Build filters
        filters = ["confidence >= ?"]
        params = [min_confidence]

        if relationship_type:
            filters.append("type = ?")
            params.append(relationship_type.value)

        if source_id:
            if not source_id.startswith("ent-"):
                raise ValueError(
                    f"Source entity ID must start with 'ent-', got {source_id}"
                )
            filters.append("source_entity_id = ?")
            params.append(source_id)

        if target_id:
            if not target_id.startswith("ent-"):
                raise ValueError(
                    f"Target entity ID must start with 'ent-', got {target_id}"
                )
            filters.append("target_entity_id = ?")
            params.append(target_id)

        where_clause = " AND ".join(filters)

        # Execute query
        cursor = self.db_conn.execute(
            f"""
            SELECT
                id, source_entity_id, target_entity_id, type,
                created_from_bullet_id, confidence, metadata,
                created_at, updated_at
            FROM relationships
            WHERE {where_clause}
            ORDER BY confidence DESC
            LIMIT 1000
        """,
            params,
        )

        # Reconstruct Relationship objects
        relationships = []
        for row in cursor:
            relationships.append(
                Relationship(
                    id=row["id"],
                    source_entity_id=row["source_entity_id"],
                    target_entity_id=row["target_entity_id"],
                    type=RelationshipType(row["type"]),
                    created_from_bullet_id=row["created_from_bullet_id"],
                    confidence=row["confidence"],
                    metadata=json.loads(row["metadata"]) if row["metadata"] else None,
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
            )

        return relationships

    def get_entity_provenance(self, entity_id: str) -> List[Dict[str, Any]]:
        """
        Get all bullets that contributed to this entity.

        Args:
            entity_id: Entity ID to get provenance for

        Returns:
            List of provenance records with keys:
                - bullet_id: Source bullet ID
                - extraction_method: Method used (MANUAL, NLP_REGEX, LLM_GPT4, etc.)
                - confidence: Extraction confidence
                - extracted_at: Extraction timestamp

        Performance: <20ms (uses idx_prov_entity index)

        Example:
            >>> provenance = kg_query.get_entity_provenance('ent-pytest')
            >>> provenance[0]['bullet_id']
            'impl-0042'
        """
        # Validate input
        if not entity_id.startswith("ent-"):
            raise ValueError(f"Entity ID must start with 'ent-', got {entity_id}")

        # Execute query
        cursor = self.db_conn.execute(
            """
            SELECT
                source_bullet_id as bullet_id,
                extraction_method,
                extraction_confidence as confidence,
                extracted_at
            FROM provenance
            WHERE entity_id = ?
            ORDER BY extracted_at DESC
        """,
            [entity_id],
        )

        # Convert to list of dicts
        provenance_records = []
        for row in cursor:
            provenance_records.append(
                {
                    "bullet_id": row["bullet_id"],
                    "extraction_method": row["extraction_method"],
                    "confidence": row["confidence"],
                    "extracted_at": row["extracted_at"],
                }
            )

        return provenance_records


# Convenience functions for module-level API


def find_paths(
    db_conn: sqlite3.Connection,
    source_id: str,
    target_id: str,
    max_depth: int = 3,
    relationship_types: Optional[List[RelationshipType]] = None,
) -> List[Path]:
    """
    Find all paths from source to target entity.

    Convenience wrapper for KnowledgeGraphQuery.find_paths().

    Example:
        >>> from mapify_cli.graph_query import find_paths
        >>> paths = find_paths(db_conn, 'ent-pytest', 'ent-python')
    """
    kg_query = KnowledgeGraphQuery(db_conn)
    return kg_query.find_paths(source_id, target_id, max_depth, relationship_types)


def get_neighbors(
    db_conn: sqlite3.Connection,
    entity_id: str,
    direction: str = "both",
    relationship_types: Optional[List[RelationshipType]] = None,
    min_confidence: float = 0.5,
) -> List[Tuple[Entity, Relationship]]:
    """
    Get neighboring entities.

    Convenience wrapper for KnowledgeGraphQuery.get_neighbors().

    Example:
        >>> from mapify_cli.graph_query import get_neighbors
        >>> neighbors = get_neighbors(db_conn, 'ent-pytest', direction='outgoing')
    """
    kg_query = KnowledgeGraphQuery(db_conn)
    return kg_query.get_neighbors(
        entity_id, direction, relationship_types, min_confidence
    )


def entities_since(
    db_conn: sqlite3.Connection,
    timestamp: str,
    entity_types: Optional[List[EntityType]] = None,
    min_confidence: float = 0.5,
) -> List[Entity]:
    """
    Get entities first seen after given timestamp.

    Convenience wrapper for KnowledgeGraphQuery.entities_since().

    Example:
        >>> from mapify_cli.graph_query import entities_since
        >>> from datetime import datetime, timedelta
        >>> cutoff = (datetime.now() - timedelta(days=1)).isoformat()
        >>> recent = entities_since(db_conn, cutoff)
    """
    kg_query = KnowledgeGraphQuery(db_conn)
    return kg_query.entities_since(timestamp, entity_types, min_confidence)


def query_entities(
    db_conn: sqlite3.Connection,
    entity_type: Optional[EntityType] = None,
    min_confidence: float = 0.0,
    name_pattern: Optional[str] = None,
) -> List[Entity]:
    """
    Generic entity query with filters.

    Convenience wrapper for KnowledgeGraphQuery.query_entities().

    Example:
        >>> from mapify_cli.graph_query import query_entities
        >>> from mapify_cli.entity_extractor import EntityType
        >>> tools = query_entities(db_conn, entity_type=EntityType.TOOL, min_confidence=0.8)
    """
    kg_query = KnowledgeGraphQuery(db_conn)
    return kg_query.query_entities(entity_type, min_confidence, name_pattern)


def query_relationships(
    db_conn: sqlite3.Connection,
    relationship_type: Optional[RelationshipType] = None,
    source_id: Optional[str] = None,
    target_id: Optional[str] = None,
    min_confidence: float = 0.0,
) -> List[Relationship]:
    """
    Generic relationship query with filters.

    Convenience wrapper for KnowledgeGraphQuery.query_relationships().

    Example:
        >>> from mapify_cli.graph_query import query_relationships
        >>> from mapify_cli.relationship_detector import RelationshipType
        >>> uses = query_relationships(db_conn, relationship_type=RelationshipType.USES)
    """
    kg_query = KnowledgeGraphQuery(db_conn)
    return kg_query.query_relationships(
        relationship_type, source_id, target_id, min_confidence
    )


def get_entity_provenance(db_conn: sqlite3.Connection, entity_id: str) -> List[Dict]:
    """
    Get all bullets that contributed to this entity.

    Convenience wrapper for KnowledgeGraphQuery.get_entity_provenance().

    Example:
        >>> from mapify_cli.graph_query import get_entity_provenance
        >>> provenance = get_entity_provenance(db_conn, 'ent-pytest')
        >>> for entry in provenance:
        ...     print(f"From bullet {entry['bullet_id']} via {entry['extraction_method']}")
    """
    kg_query = KnowledgeGraphQuery(db_conn)
    return kg_query.get_entity_provenance(entity_id)
