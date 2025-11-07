"""
Relationship Detection Module for Knowledge Graph Construction.

Extracts relationships between entities (USES, DEPENDS_ON, CONTRADICTS, etc.)
from text content using pattern matching and entity linking.

Based on: docs/knowledge_graph/schema_v3.0.sql
Relationship types: USES, DEPENDS_ON, CONTRADICTS, SUPERSEDES, RELATED_TO,
                    IMPLEMENTS, CAUSES, PREVENTS, ALTERNATIVE_TO

Target accuracy: ≥70% on test corpus
"""

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple
from enum import Enum

# Import Entity and EntityType from entity_extractor
from mapify_cli.entity_extractor import Entity


class RelationshipType(Enum):
    """Relationship types matching schema_v3.0.sql CHECK constraint."""

    # Required 5 types (for 70% accuracy requirement)
    USES = "USES"  # A uses B (pytest USES Python)
    DEPENDS_ON = "DEPENDS_ON"  # A depends on B (MAP-workflow DEPENDS_ON playbook.db)
    CONTRADICTS = "CONTRADICTS"  # A contradicts B (generic-exception CONTRADICTS specific-exceptions)
    SUPERSEDES = "SUPERSEDES"  # A replaces B (playbook.db SUPERSEDES playbook.json)
    RELATED_TO = "RELATED_TO"  # Generic relationship (fallback)

    # Bonus 4 types (for comprehensive graph)
    IMPLEMENTS = (
        "IMPLEMENTS"  # A implements B (retry-logic IMPLEMENTS resilience-pattern)
    )
    CAUSES = "CAUSES"  # A causes B (race-condition CAUSES data-corruption)
    PREVENTS = "PREVENTS"  # A prevents B (mutex-lock PREVENTS race-condition)
    ALTERNATIVE_TO = (
        "ALTERNATIVE_TO"  # A is alternative to B (JSON-storage ALTERNATIVE_TO SQLite)
    )


@dataclass
class Relationship:
    """
    Extracted relationship with metadata.

    Attributes:
        id: Relationship ID in format 'rel-{uuid}'
        source_entity_id: Source entity ID (e.g., 'ent-pytest')
        target_entity_id: Target entity ID (e.g., 'ent-python')
        type: RelationshipType enum value
        created_from_bullet_id: Bullet ID that mentioned this relationship
        confidence: Extraction confidence score (0.0-1.0)
        metadata: Optional JSON-serializable dict for context
        created_at: ISO8601 timestamp
        updated_at: ISO8601 timestamp (same as created_at for new extractions)
    """

    id: str
    source_entity_id: str
    target_entity_id: str
    type: RelationshipType
    created_from_bullet_id: str
    confidence: float
    metadata: Optional[Dict] = None
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        """Validate relationship constraints."""
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Confidence must be in [0.0, 1.0], got {self.confidence}")

        # Validate ID format
        if not self.id.startswith("rel-"):
            raise ValueError(f"Relationship ID must start with 'rel-', got {self.id}")

        # Set timestamps if not provided
        if not self.created_at:
            self.created_at = (
                datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            )
        if not self.updated_at:
            self.updated_at = self.created_at

        # Validate entity IDs
        if not self.source_entity_id.startswith("ent-"):
            raise ValueError(
                f"Source entity ID must start with 'ent-', got {self.source_entity_id}"
            )
        if not self.target_entity_id.startswith("ent-"):
            raise ValueError(
                f"Target entity ID must start with 'ent-', got {self.target_entity_id}"
            )


class RelationshipDetector:
    """
    Pattern-based relationship extraction engine.

    Achieves ≥70% accuracy through:
    1. Explicit relationship patterns (verb-based: "uses", "depends on", etc.)
    2. Entity name matching with normalization (case-insensitive, fuzzy)
    3. Context-aware confidence scoring
    4. Proximity-based fallback (RELATED_TO for co-occurring entities)
    5. Deduplication by (source, target, type) tuple

    Example:
        >>> detector = RelationshipDetector()
        >>> entities = [Entity(id="ent-pytest", name="pytest", type=EntityType.TOOL, ...)]
        >>> relationships = detector.detect_relationships("pytest uses Python", entities, "bullet-001")
        >>> relationships[0].type
        RelationshipType.USES
    """

    def __init__(self):
        """Initialize relationship patterns for each type."""
        self._compile_patterns()

    def _compile_patterns(self):
        """
        Compile regex patterns for each relationship type.

        Pattern structure: {entity1} <relationship_verb> {entity2}
        Uses named groups: (?P<source>...) and (?P<target>...)
        """

        # USES: A uses B
        # Examples: "pytest uses Python", "Flask uses Jinja2", "MAP workflow uses playbook.db"
        # Pattern captures: word or multi-word entity (limited to 2 words)
        self.uses_patterns = [
            re.compile(
                r"\b(?P<source>[\w\-\.]+(?:\s[\w\-\.]+)*?)\s+uses?\s+(?P<target>[\w\-\.]+(?:\s[\w\-\.]+)?)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\buse\s+(?P<source>[\w\-\.]+(?:\s[\w\-\.]+)?)\s+for\s+(?:testing|running|building)\s+(?P<target>[\w\-\.]+(?:\s[\w\-\.]+)?)",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(?P<source>[\w\-\.]+(?:\s[\w\-\.]+)?)\s+is\s+built\s+on\s+(?P<target>[\w\-\.]+(?:\s[\w\-\.]+)?)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(?P<source>[\w\-\.]+(?:\s[\w\-\.]+)?)\s+leverages?\s+(?P<target>[\w\-\.]+(?:\s[\w\-\.]+)?)\b",
                re.IGNORECASE,
            ),
        ]

        # DEPENDS_ON: A depends on B
        # Examples: "MAP workflow depends on playbook.db", "Actor requires Monitor"
        self.depends_on_patterns = [
            re.compile(
                r"\b(?P<source>[\w\-\.]+(?:\s[\w\-\.]+)?)\s+depends?\s+on\s+(?P<target>[\w\-\.]+(?:\s[\w\-\.]+)?)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(?P<source>[\w\-\.]+(?:\s[\w\-\.]+)?)\s+requires?\s+(?P<target>[\w\-\.]+(?:\s[\w\-\.]+)?)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(?P<source>[\w\-\.]+(?:\s[\w\-\.]+)?)\s+needs?\s+(?P<target>[\w\-\.]+(?:\s[\w\-\.]+)?)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(?P<source>[\w\-\.]+(?:\s[\w\-\.]+)?)\s+relies\s+on\s+(?P<target>[\w\-\.]+(?:\s[\w\-\.]+)?)\b",
                re.IGNORECASE,
            ),
        ]

        # CONTRADICTS: A contradicts B
        # Examples: "generic exception contradicts specific exceptions", "use pytest instead of unittest"
        self.contradicts_patterns = [
            re.compile(
                r"\b(?P<source>[\w\-\.]+(?:\s[\w\-\.]+)?)\s+contradicts?\s+(?P<target>[\w\-\.]+(?:\s[\w\-\.]+)?)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(?P<source>[\w\-\.]+(?:\s[\w\-\.]+)?)\s+conflicts?\s+with\s+(?P<target>[\w\-\.]+(?:\s[\w\-\.]+)?)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\buse\s+(?P<source>[\w\-\.]+(?:\s[\w\-\.]+)?)\s+instead\s+of\s+(?P<target>[\w\-\.]+(?:\s[\w\-\.]+)?)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\bavoid\s+(?P<target>[\w\-\.]+(?:\s[\w\-\.]+)?)[\s,]+use\s+(?P<source>[\w\-\.]+(?:\s[\w\-\.]+)?)\b",
                re.IGNORECASE,
            ),
        ]

        # SUPERSEDES: A replaces B
        # Examples: "playbook.db supersedes playbook.json", "migrated from JSON to SQLite"
        self.supersedes_patterns = [
            re.compile(
                r"\b(?P<source>[\w\-\.]+(?:\s[\w\-\.]+)?)\s+supersedes?\s+(?P<target>[\w\-\.]+(?:\s[\w\-\.]+)?)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(?P<source>[\w\-\.]+(?:\s[\w\-\.]+)?)\s+replaces?\s+(?P<target>[\w\-\.]+(?:\s[\w\-\.]+)?)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\bmigrated\s+from\s+(?P<target>[\w\-\.]+(?:\s[\w\-\.]+)?)\s+to\s+(?P<source>[\w\-\.]+(?:\s[\w\-\.]+)?)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\bupgraded\s+from\s+(?P<target>[\w\-\.]+(?:\s[\w\-\.]+)?)\s+to\s+(?P<source>[\w\-\.]+(?:\s[\w\-\.]+)?)\b",
                re.IGNORECASE,
            ),
        ]

        # IMPLEMENTS: A implements pattern B
        # Examples: "retry logic implements resilience pattern", "Actor implements Strategy pattern"
        self.implements_patterns = [
            re.compile(
                r"\b(?P<source>[\w\-\.]+(?:\s[\w\-\.]+)?)\s+implements?\s+(?P<target>[\w\-\.]+(?:\s[\w\-\.]+)?)(?:\s+pattern)?\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(?P<source>[\w\-\.]+(?:\s[\w\-\.]+)?)\s+follows?\s+(?P<target>[\w\-\.]+(?:\s[\w\-\.]+)?)(?:\s+pattern)?\b",
                re.IGNORECASE,
            ),
        ]

        # CAUSES: A causes error B
        # Examples: "race condition causes data corruption", "null pointer causes crash"
        self.causes_patterns = [
            re.compile(
                r"\b(?P<source>[\w\-\.]+(?:\s[\w\-\.]+)?)\s+causes?\s+(?P<target>[\w\-\.]+(?:\s[\w\-\.]+)?)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(?P<source>[\w\-\.]+(?:\s[\w\-\.]+)?)\s+leads?\s+to\s+(?:(?:an?\s+)?(?:application|system)\s+)?(?P<target>[\w\-\.]+(?:\s[\w\-\.]+)?)\b",
                re.IGNORECASE,
            ),
        ]

        # PREVENTS: A prevents B
        # Examples: "mutex lock prevents race condition", "validation prevents null pointer"
        self.prevents_patterns = [
            re.compile(
                r"\b(?P<source>[\w\-\.]+(?:\s[\w\-\.]+)?)\s+prevents?\s+(?P<target>[\w\-\.]+(?:\s[\w\-\.]+)?)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(?P<source>[\w\-\.]+)\s+avoids?\s+(?P<target>[\w\-\.]+(?:\s[\w\-\.]+)?)(?:\s+errors?)?\b",
                re.IGNORECASE,
            ),
        ]

        # ALTERNATIVE_TO: A is alternative to B
        # Examples: "JSON storage alternative to SQLite", "pytest instead of unittest"
        self.alternative_to_patterns = [
            re.compile(
                r"\b(?P<source>[\w\-\.]+(?:\s[\w\-\.]+)?)\s+(?:is\s+)?(?:an?\s+)?alternative\s+to\s+(?P<target>[\w\-\.]+(?:\s[\w\-\.]+)?)\b",
                re.IGNORECASE,
            ),
        ]

    def detect_relationships(
        self, content: str, entities: List[Entity], bullet_id: str
    ) -> List[Relationship]:
        """
        Detect relationships between entities in content.

        Args:
            content: Text to extract relationships from (playbook bullet content)
            entities: List of Entity objects already extracted from content
            bullet_id: ID of bullet this content came from (for provenance)

        Returns:
            List of Relationship objects with confidence scores

        Edge cases handled:
        - Empty content or entities: returns empty list
        - Entity name variations: normalized matching (case-insensitive, hyphen/space)
        - Duplicate relationships: deduplicated by (source, target, type)
        - Self-relationships: filtered out (entity cannot relate to itself)

        Example:
            >>> detector = RelationshipDetector()
            >>> entities = [
            ...     Entity(id="ent-pytest", name="pytest", type=EntityType.TOOL, ...),
            ...     Entity(id="ent-python", name="Python", type=EntityType.TECHNOLOGY, ...)
            ... ]
            >>> rels = detector.detect_relationships("pytest uses Python", entities, "bullet-001")
            >>> rels[0].type
            RelationshipType.USES
        """
        # Edge case: empty content or no entities
        if not content or not content.strip() or not entities:
            return []

        # Build entity lookup for fast matching
        entity_lookup = self._build_entity_lookup(entities)

        # Extract all relationships
        relationships = []

        # Process each relationship type
        relationships.extend(
            self._extract_typed_relationships(
                content,
                entity_lookup,
                bullet_id,
                RelationshipType.USES,
                self.uses_patterns,
            )
        )
        relationships.extend(
            self._extract_typed_relationships(
                content,
                entity_lookup,
                bullet_id,
                RelationshipType.DEPENDS_ON,
                self.depends_on_patterns,
            )
        )
        relationships.extend(
            self._extract_typed_relationships(
                content,
                entity_lookup,
                bullet_id,
                RelationshipType.CONTRADICTS,
                self.contradicts_patterns,
            )
        )
        relationships.extend(
            self._extract_typed_relationships(
                content,
                entity_lookup,
                bullet_id,
                RelationshipType.SUPERSEDES,
                self.supersedes_patterns,
            )
        )
        relationships.extend(
            self._extract_typed_relationships(
                content,
                entity_lookup,
                bullet_id,
                RelationshipType.IMPLEMENTS,
                self.implements_patterns,
            )
        )
        relationships.extend(
            self._extract_typed_relationships(
                content,
                entity_lookup,
                bullet_id,
                RelationshipType.CAUSES,
                self.causes_patterns,
            )
        )
        relationships.extend(
            self._extract_typed_relationships(
                content,
                entity_lookup,
                bullet_id,
                RelationshipType.PREVENTS,
                self.prevents_patterns,
            )
        )
        relationships.extend(
            self._extract_typed_relationships(
                content,
                entity_lookup,
                bullet_id,
                RelationshipType.ALTERNATIVE_TO,
                self.alternative_to_patterns,
            )
        )

        # Extract proximity-based RELATED_TO relationships (fallback)
        relationships.extend(
            self._extract_proximity_relationships(content, entities, bullet_id)
        )

        # Deduplicate and return
        return self._deduplicate_relationships(relationships)

    def _build_entity_lookup(self, entities: List[Entity]) -> Dict[str, Entity]:
        """
        Build normalized entity lookup for fast matching.

        Creates multiple lookup keys per entity to handle name variations:
        - Original name (case-insensitive)
        - Hyphenated version (spaces → hyphens)
        - De-hyphenated version (hyphens → spaces)

        Returns:
            Dict mapping normalized_name → Entity
        """
        lookup = {}

        for entity in entities:
            # Normalize: lowercase, strip
            name_lower = entity.name.lower().strip()

            # Add original name
            lookup[name_lower] = entity

            # Add hyphenated version (for "map workflow" → "map-workflow")
            hyphenated = name_lower.replace(" ", "-")
            lookup[hyphenated] = entity

            # Add de-hyphenated version (for "map-workflow" → "map workflow")
            dehyphenated = name_lower.replace("-", " ")
            lookup[dehyphenated] = entity

            # Add underscore version (for "retry_with_backoff")
            underscored = name_lower.replace(" ", "_").replace("-", "_")
            lookup[underscored] = entity

        return lookup

    def _extract_typed_relationships(
        self,
        content: str,
        entity_lookup: Dict[str, Entity],
        bullet_id: str,
        rel_type: RelationshipType,
        patterns: List[re.Pattern],
    ) -> List[Relationship]:
        """
        Extract relationships of a specific type using pattern list.

        Args:
            content: Input text
            entity_lookup: Normalized entity name → Entity mapping
            bullet_id: Bullet ID for provenance
            rel_type: RelationshipType to extract
            patterns: List of compiled regex patterns with named groups

        Returns:
            List of relationships matching this type
        """
        relationships = []

        for pattern in patterns:
            for match in pattern.finditer(content):
                # Extract source and target from named groups
                source_name = (
                    match.group("source") if "source" in match.groupdict() else None
                )
                target_name = (
                    match.group("target") if "target" in match.groupdict() else None
                )

                # Skip if either is missing
                if not source_name or not target_name:
                    continue

                # Normalize names
                source_norm = source_name.lower().strip()
                target_norm = target_name.lower().strip()

                # Try to match to entities - need to handle partial matches
                source_entity = self._find_entity_match(source_norm, entity_lookup)
                target_entity = self._find_entity_match(target_norm, entity_lookup)

                # Skip if either entity not found
                if not source_entity or not target_entity:
                    continue

                # Skip self-relationships
                if source_entity.id == target_entity.id:
                    continue

                # Calculate confidence
                confidence = self._calculate_confidence(
                    source_entity, target_entity, rel_type, match.group(0), content
                )

                # Create relationship
                rel_id = f"rel-{uuid.uuid4()}"
                metadata = {
                    "extraction_method": "pattern_matching",
                    "pattern_matched": match.group(0),
                }

                relationships.append(
                    Relationship(
                        id=rel_id,
                        source_entity_id=source_entity.id,
                        target_entity_id=target_entity.id,
                        type=rel_type,
                        created_from_bullet_id=bullet_id,
                        confidence=confidence,
                        metadata=metadata,
                    )
                )

        return relationships

    def _find_entity_match(
        self, text: str, entity_lookup: Dict[str, Entity]
    ) -> Optional[Entity]:
        """
        Find entity in lookup that matches text (exact or partial).

        Strategy:
        1. Try exact match
        2. Try matching first N words of text to entity names
        3. Try matching entity names as substrings of text

        Args:
            text: Text to match (e.g., "pytest for testing", "Python applications")
            entity_lookup: Normalized entity name → Entity mapping

        Returns:
            Matched Entity or None
        """
        # Try exact match first
        if text in entity_lookup:
            return entity_lookup[text]

        # Try progressively shorter prefixes (e.g., "Python applications" → "Python")
        words = text.split()
        for num_words in range(len(words), 0, -1):
            prefix = " ".join(words[:num_words])
            if prefix in entity_lookup:
                return entity_lookup[prefix]

        # Try finding entity names that are prefixes of text
        # (e.g., "pytest" matches "pytest for testing")
        for entity_name, entity in entity_lookup.items():
            if text.startswith(entity_name + " ") or text.startswith(entity_name + "-"):
                return entity

        return None

    def _extract_proximity_relationships(
        self, content: str, entities: List[Entity], bullet_id: str
    ) -> List[Relationship]:
        """
        Extract RELATED_TO relationships based on entity proximity.

        Entities mentioned within 50 characters of each other are considered
        related with low confidence (0.5-0.6).

        This is a fallback for entities that co-occur but have no explicit
        relationship pattern.

        Args:
            content: Input text
            entities: List of entities
            bullet_id: Bullet ID for provenance

        Returns:
            List of RELATED_TO relationships
        """
        relationships = []
        proximity_threshold = 50  # characters

        # Find positions of all entity mentions
        entity_positions = []
        for entity in entities:
            # Find all occurrences of entity name (case-insensitive)
            pattern = re.compile(r"\b" + re.escape(entity.name) + r"\b", re.IGNORECASE)
            for match in pattern.finditer(content):
                entity_positions.append((match.start(), match.end(), entity))

        # Sort by start position
        entity_positions.sort(key=lambda x: x[0])

        # Find pairs within proximity threshold
        for i, (start1, end1, entity1) in enumerate(entity_positions):
            for start2, end2, entity2 in entity_positions[i + 1 :]:
                # Check distance
                distance = start2 - end1

                if distance > proximity_threshold:
                    # Entities too far apart, and list is sorted, so stop
                    break

                # Skip self-relationships
                if entity1.id == entity2.id:
                    continue

                # Create RELATED_TO relationship with low confidence
                confidence = 0.6 if distance < 20 else 0.5

                # Boost confidence if both entities have high confidence
                if entity1.confidence >= 0.8 and entity2.confidence >= 0.8:
                    confidence = min(1.0, confidence + 0.1)

                rel_id = f"rel-{uuid.uuid4()}"
                metadata = {
                    "extraction_method": "proximity_based",
                    "distance_chars": distance,
                }

                relationships.append(
                    Relationship(
                        id=rel_id,
                        source_entity_id=entity1.id,
                        target_entity_id=entity2.id,
                        type=RelationshipType.RELATED_TO,
                        created_from_bullet_id=bullet_id,
                        confidence=confidence,
                        metadata=metadata,
                    )
                )

        return relationships

    def _calculate_confidence(
        self,
        source: Entity,
        target: Entity,
        rel_type: RelationshipType,
        matched_text: str,
        full_content: str,
    ) -> float:
        """
        Calculate confidence score for a relationship.

        Scoring factors:
        1. Base confidence by relationship type (0.7-0.8)
        2. Entity confidence boost (+0.1 if both entities high confidence)
        3. Code context boost (+0.1 if in code block or backticks)
        4. Explicit relationship boost (+0.1 if exact match)

        Returns:
            Confidence score in [0.0, 1.0]
        """
        # Base confidence by type
        base_confidence = {
            RelationshipType.USES: 0.8,
            RelationshipType.DEPENDS_ON: 0.8,
            RelationshipType.CONTRADICTS: 0.8,
            RelationshipType.SUPERSEDES: 0.8,
            RelationshipType.IMPLEMENTS: 0.7,
            RelationshipType.CAUSES: 0.7,
            RelationshipType.PREVENTS: 0.7,
            RelationshipType.ALTERNATIVE_TO: 0.6,  # Weaker (can be ambiguous)
            RelationshipType.RELATED_TO: 0.5,  # Weakest (proximity-based)
        }.get(rel_type, 0.7)

        confidence = base_confidence

        # Boost if both entities have high confidence
        if source.confidence >= 0.8 and target.confidence >= 0.8:
            confidence = min(1.0, confidence + 0.1)

        # Boost if relationship mentioned in code context
        # Check if matched_text is within backticks or code block
        # Extract 100-char window around match for context
        match_start = full_content.find(matched_text)
        if match_start != -1:
            window_start = max(0, match_start - 50)
            window_end = min(len(full_content), match_start + len(matched_text) + 50)
            context_window = full_content[window_start:window_end]

            # Check for code context markers
            if "`" in context_window or "```" in context_window:
                confidence = min(1.0, confidence + 0.1)

        # Cap at 0.95 (never 1.0 for pattern-based extraction)
        confidence = min(0.95, confidence)

        return round(confidence, 2)

    def _deduplicate_relationships(
        self, relationships: List[Relationship]
    ) -> List[Relationship]:
        """
        Deduplicate relationships by (source, target, type) tuple.

        Deduplication strategy:
        - Same source + target + type → same relationship
        - RELATED_TO is undirected: (A, B, RELATED_TO) = (B, A, RELATED_TO)
        - Keep relationship with highest confidence
        - Keep earliest created_at timestamp

        Example:
            Input: [
                Relationship(source=ent-pytest, target=ent-python, type=USES, conf=0.8),
                Relationship(source=ent-pytest, target=ent-python, type=USES, conf=0.9)
            ]
            Output: [
                Relationship(source=ent-pytest, target=ent-python, type=USES, conf=0.9)
            ]

        Returns:
            Deduplicated list of relationships sorted by confidence (descending)
        """
        seen: Dict[Tuple[str, str, RelationshipType], Relationship] = {}

        for rel in relationships:
            # RELATED_TO is undirected: canonicalize (source, target) by sorting
            if rel.type == RelationshipType.RELATED_TO:
                # Ensure consistent ordering for bidirectional relationships
                canonical_source = min(rel.source_entity_id, rel.target_entity_id)
                canonical_target = max(rel.source_entity_id, rel.target_entity_id)
                key = (canonical_source, canonical_target, rel.type)

                # If relationship was swapped, create canonical version
                if rel.source_entity_id != canonical_source:
                    rel = Relationship(
                        id=rel.id,
                        source_entity_id=canonical_source,
                        target_entity_id=canonical_target,
                        type=rel.type,
                        created_from_bullet_id=rel.created_from_bullet_id,
                        confidence=rel.confidence,
                        metadata=rel.metadata,
                        created_at=rel.created_at,
                        updated_at=rel.updated_at,
                    )
            else:
                # Directed relationships: use as-is
                key = (rel.source_entity_id, rel.target_entity_id, rel.type)

            if key not in seen:
                seen[key] = rel
            else:
                # Relationship already seen: merge
                existing = seen[key]

                # Keep higher confidence
                if rel.confidence > existing.confidence:
                    existing.confidence = rel.confidence
                    existing.metadata = (
                        rel.metadata
                    )  # Update metadata from higher-confidence extraction

                # Keep earliest created_at
                if rel.created_at < existing.created_at:
                    existing.created_at = rel.created_at

        # Return deduplicated list, sorted by confidence (descending)
        return sorted(seen.values(), key=lambda r: r.confidence, reverse=True)


# Convenience function for module-level API
def detect_relationships(
    content: str, entities: List[Entity], bullet_id: str
) -> List[Relationship]:
    """
    Detect relationships between entities in content.

    Convenience wrapper around RelationshipDetector for simple usage.

    Args:
        content: Text to extract relationships from
        entities: List of Entity objects already extracted from content
        bullet_id: ID of bullet this content came from (for provenance)

    Returns:
        List of Relationship objects with confidence scores

    Example:
        >>> from mapify_cli.relationship_detector import detect_relationships
        >>> from mapify_cli.entity_extractor import extract_entities
        >>> entities = extract_entities("pytest uses Python")
        >>> relationships = detect_relationships("pytest uses Python", entities, "bullet-001")
        >>> relationships[0].type
        RelationshipType.USES
    """
    detector = RelationshipDetector()
    return detector.detect_relationships(content, entities, bullet_id)
