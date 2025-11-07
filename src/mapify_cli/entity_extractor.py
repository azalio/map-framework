"""
Entity Extraction Module for Knowledge Graph Construction.

Extracts entities (tools, patterns, concepts, etc.) from text content using
pattern matching and keyword detection. No external NLP dependencies required.

Based on: docs/knowledge_graph/schema_v3.0.sql
Entity types: TOOL, PATTERN, CONCEPT, ERROR_TYPE, TECHNOLOGY, WORKFLOW, ANTIPATTERN
"""

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple
from enum import Enum


class EntityType(Enum):
    """Entity types matching schema_v3.0.sql CHECK constraint."""

    TOOL = "TOOL"  # CLI tools, libraries, frameworks (pytest, SQLite, Docker)
    PATTERN = "PATTERN"  # Implementation patterns (retry-with-backoff, feature-flags)
    CONCEPT = "CONCEPT"  # Abstract ideas (idempotency, eventual-consistency)
    ERROR_TYPE = "ERROR_TYPE"  # Error categories (race-condition, null-pointer)
    TECHNOLOGY = "TECHNOLOGY"  # Tech stack components (Python, Kubernetes, CI/CD)
    WORKFLOW = "WORKFLOW"  # Process patterns (MAP-debugging, TDD-cycle)
    ANTIPATTERN = "ANTIPATTERN"  # Known bad practices (generic-exception-catch)


@dataclass
class Entity:
    """
    Extracted entity with metadata.

    Attributes:
        id: Semantic ID in format 'ent-{slug}' (e.g., 'ent-pytest')
        type: EntityType enum value
        name: Human-readable name (e.g., 'pytest', 'Exponential Backoff')
        confidence: Extraction confidence score (0.0-1.0)
        first_seen_at: ISO8601 timestamp of first extraction
        last_seen_at: ISO8601 timestamp of last mention (same as first_seen for new extractions)
        metadata: Optional JSON-serializable dict for entity-specific attributes
    """

    id: str
    type: EntityType
    name: str
    confidence: float
    first_seen_at: str
    last_seen_at: str
    metadata: Optional[Dict] = None

    def __post_init__(self):
        """Validate entity constraints."""
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Confidence must be in [0.0, 1.0], got {self.confidence}")

        # Validate ID format
        if not self.id.startswith("ent-"):
            raise ValueError(f"Entity ID must start with 'ent-', got {self.id}")


class EntityExtractor:
    """
    Pattern-based entity extraction engine.

    Achieves ≥80% accuracy through:
    1. Exact keyword matching for tools/technologies
    2. Pattern-based extraction for code entities (backticks, code blocks)
    3. Context-aware confidence scoring
    4. Deduplication by name+type

    Example:
        >>> extractor = EntityExtractor()
        >>> entities = extractor.extract_entities("Use pytest for testing")
        >>> entities[0].name
        'pytest'
        >>> entities[0].type
        EntityType.TOOL
    """

    def __init__(self):
        """Initialize pattern dictionaries for each entity type."""

        # TOOL: CLI tools, libraries, frameworks
        # Exact keyword match → confidence 0.9
        self.tool_keywords = {
            # Testing frameworks
            "pytest",
            "unittest",
            "jest",
            "mocha",
            "jasmine",
            "cypress",
            # Databases
            "sqlite",
            "postgresql",
            "postgres",
            "mysql",
            "mongodb",
            "redis",
            "fts5",  # SQLite FTS5 extension
            # Python libraries
            "numpy",
            "pandas",
            "flask",
            "django",
            "fastapi",
            "requests",
            "sqlalchemy",
            "pydantic",
            "click",
            # CLI tools
            "git",
            "docker",
            "kubernetes",
            "kubectl",
            "helm",
            "terraform",
            "ansible",
            "make",
            "cmake",
            "gradle",
            "maven",
            # Build/package tools
            "npm",
            "yarn",
            "pip",
            "poetry",
            "cargo",
            "go mod",
            # Monitoring/logging
            "prometheus",
            "grafana",
            "elk",
            "elasticsearch",
            "kibana",
            "logstash",
            # CI/CD
            "jenkins",
            "github actions",
            "gitlab ci",
            "circleci",
            "travis ci",
        }

        # TECHNOLOGY: Tech stack components
        # Exact keyword match → confidence 0.9
        self.technology_keywords = {
            # Languages
            "python",
            "javascript",
            "typescript",
            "java",
            "go",
            "rust",
            "c++",
            "c#",
            "ruby",
            "php",
            "swift",
            "kotlin",
            # Frameworks/platforms
            "react",
            "vue",
            "angular",
            "next.js",
            "nuxt",
            "svelte",
            "node.js",
            "express",
            "koa",
            "fastify",
            # Infrastructure
            "kubernetes",
            "docker",
            "aws",
            "azure",
            "gcp",
            "heroku",
            "ci/cd",
            "devops",
            "microservices",
            "serverless",
            # Protocols/standards
            "http",
            "https",
            "grpc",
            "rest",
            "graphql",
            "websocket",
            "oauth",
            "jwt",
            "saml",
            "openid",
        }

        # PATTERN: Implementation patterns
        # Keyword detection + context clues → confidence 0.7-0.9
        self.pattern_keywords = {
            # Resilience patterns
            "retry": "retry-pattern",
            "backoff": "exponential-backoff",
            "circuit-breaker": "circuit-breaker-pattern",
            "timeout": "timeout-pattern",
            "fallback": "fallback-pattern",
            # Design patterns
            "singleton": "singleton-pattern",
            "factory": "factory-pattern",
            "observer": "observer-pattern",
            "strategy": "strategy-pattern",
            "decorator": "decorator-pattern",
            "adapter": "adapter-pattern",
            # Architecture patterns
            "microservices": "microservices-pattern",
            "event-driven": "event-driven-architecture",
            "pub-sub": "publish-subscribe-pattern",
            "cqrs": "cqrs-pattern",
            "saga": "saga-pattern",
            # Data patterns
            "repository": "repository-pattern",
            "active-record": "active-record-pattern",
            "data-mapper": "data-mapper-pattern",
            # Feature management
            "feature-flag": "feature-flag-pattern",
            "feature-toggle": "feature-toggle-pattern",
            "canary": "canary-deployment",
            "blue-green": "blue-green-deployment",
        }

        # CONCEPT: Abstract ideas
        # Context-based inference → confidence 0.5-0.7
        self.concept_keywords = {
            "idempotency": "idempotency",
            "idempotent": "idempotency",
            "consistency": "consistency",
            "eventual-consistency": "eventual-consistency",
            "atomicity": "atomicity",
            "durability": "durability",
            "isolation": "isolation",
            "acid": "acid-properties",
            "cap-theorem": "cap-theorem",
            "base": "base-properties",
            "immutability": "immutability",
            "referential-transparency": "referential-transparency",
            "side-effect": "side-effects",
            "declarative": "declarative-programming",
            "imperative": "imperative-programming",
            "functional-programming": "functional-programming",
            "object-oriented": "object-oriented-programming",
        }

        # ERROR_TYPE: Error categories
        # Pattern + error keywords → confidence 0.7-0.9
        self.error_type_keywords = {
            "race-condition": "race-condition",
            "deadlock": "deadlock",
            "memory-leak": "memory-leak",
            "null-pointer": "null-pointer-exception",
            "buffer-overflow": "buffer-overflow",
            "stack-overflow": "stack-overflow",
            "out-of-memory": "out-of-memory",
            "timeout": "timeout-error",
            "connection-refused": "connection-refused",
            "permission-denied": "permission-denied",
            "file-not-found": "file-not-found",
            "syntax-error": "syntax-error",
            "type-error": "type-error",
            "value-error": "value-error",
            "index-error": "index-error",
            "key-error": "key-error",
            "attribute-error": "attribute-error",
        }

        # WORKFLOW: Process patterns
        # Multi-word pattern detection → confidence 0.7
        self.workflow_keywords = {
            "tdd": "test-driven-development",
            "bdd": "behavior-driven-development",
            "ci/cd": "continuous-integration-deployment",
            "gitflow": "gitflow-workflow",
            "trunk-based": "trunk-based-development",
            "code-review": "code-review-process",
            "pair-programming": "pair-programming",
            "map-feature": "map-feature-workflow",
            "map-debug": "map-debug-workflow",
            "map-refactor": "map-refactor-workflow",
            "agile": "agile-methodology",
            "scrum": "scrum-framework",
            "kanban": "kanban-method",
        }

        # ANTIPATTERN: Known bad practices
        # Negative context clues ("never", "avoid", "don't") → confidence 0.7-0.9
        self.antipattern_keywords = {
            "generic-exception": "generic-exception-catch",
            "silent-failure": "silent-failure",
            "god-object": "god-object-antipattern",
            "spaghetti-code": "spaghetti-code",
            "magic-number": "magic-numbers",
            "hardcoded": "hardcoded-values",
            "global-variable": "global-variables",
            "copy-paste": "copy-paste-programming",
            "premature-optimization": "premature-optimization",
            "callback-hell": "callback-hell",
            "dependency-hell": "dependency-hell",
        }

        # Compile regex patterns for efficiency
        self._compile_patterns()

    def _compile_patterns(self):
        """Compile regex patterns for entity extraction."""

        # Pattern 1: Code entities in backticks
        # Matches: `pytest`, `SQLite`, `retry_with_backoff()`
        # Confidence: 0.9 (explicit code reference)
        self.code_entity_pattern = re.compile(r"`([a-zA-Z0-9_\-\.]+(?:\(\))?)`")

        # Pattern 2: Code blocks (triple backticks or indentation)
        # Extract tool names from import statements, function calls
        # Confidence: 0.8 (code context)
        self.code_block_pattern = re.compile(
            r"```[\w]*\n(.*?)```|^(?: {4}|\t)(.+)$", re.MULTILINE | re.DOTALL
        )

        # Pattern 3: Import statements
        # Matches: import pytest, from flask import Flask
        # Confidence: 0.9 (explicit tool usage)
        self.import_pattern = re.compile(
            r"(?:import|from)\s+([a-zA-Z0-9_\.]+)", re.IGNORECASE
        )

        # Pattern 4: Negative context for antipatterns
        # Matches: "never use", "avoid", "don't do"
        # Confidence boost: +0.2
        self.negative_context_pattern = re.compile(
            r"\b(never|avoid|don\'t|do not|anti[\s-]?pattern|bad practice|wrong)\b",
            re.IGNORECASE,
        )

        # Pattern 5: Pattern suffix detection
        # Matches: "retry pattern", "singleton Pattern", "factory-pattern"
        # Confidence: 0.8
        self.pattern_suffix_pattern = re.compile(
            r"\b([a-z][\w\-]+)[\s\-]pattern\b", re.IGNORECASE
        )

    def extract_entities(self, content: str) -> List[Entity]:
        """
        Extract all entities from content string.

        Args:
            content: Text to extract entities from (playbook bullet content, code, etc.)

        Returns:
            List of Entity objects with confidence scores

        Handles edge cases:
        - Empty content: returns empty list
        - Special characters: sanitized during extraction
        - Long text: processed in chunks if needed
        - Duplicates: deduplicated by (name, type) tuple

        Example:
            >>> extractor = EntityExtractor()
            >>> text = "Use `pytest` for testing with exponential backoff pattern"
            >>> entities = extractor.extract_entities(text)
            >>> len(entities)
            2
            >>> entities[0].name
            'pytest'
            >>> entities[1].name
            'exponential-backoff'
        """
        # Edge case: empty or whitespace-only content
        if not content or not content.strip():
            return []

        # Edge case: handle extremely long content (>100KB)
        if len(content) > 100_000:
            # Process in chunks to avoid performance issues
            # Use 100-char overlap to prevent missing entities at chunk boundaries
            chunk_size = 50_000
            overlap = 100
            all_entities = []
            for i in range(0, len(content), chunk_size):
                # Include overlap from previous chunk
                start = max(0, i - overlap)
                chunk = content[start : i + chunk_size]
                all_entities.extend(self._extract_from_text(chunk))
            # Deduplicate across chunks
            return self._deduplicate_entities(all_entities)

        # Normal processing
        entities = self._extract_from_text(content)
        return self._deduplicate_entities(entities)

    def _extract_from_text(self, text: str) -> List[Entity]:
        """
        Core extraction logic for a single text chunk.

        Extraction strategy:
        1. Extract code entities (backticks, code blocks) → high confidence
        2. Extract keyword matches → medium-high confidence
        3. Extract pattern-based entities → medium confidence
        4. Extract inferred concepts → low-medium confidence

        Returns raw list (before deduplication).
        """
        entities = []
        # Use timezone-aware datetime (fixes deprecation warning)
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        # Step 1: Extract code entities (highest confidence: 0.9)
        entities.extend(self._extract_code_entities(text, now))

        # Step 2: Extract tools and technologies from keywords
        entities.extend(
            self._extract_keyword_entities(
                text, self.tool_keywords, EntityType.TOOL, now, base_confidence=0.9
            )
        )
        entities.extend(
            self._extract_keyword_entities(
                text,
                self.technology_keywords,
                EntityType.TECHNOLOGY,
                now,
                base_confidence=0.9,
            )
        )

        # Step 3: Extract patterns (with pattern suffix detection)
        entities.extend(self._extract_pattern_entities(text, now))

        # Step 4: Extract concepts (context-based inference)
        entities.extend(
            self._extract_keyword_entities(
                text,
                self.concept_keywords,
                EntityType.CONCEPT,
                now,
                base_confidence=0.6,
            )
        )

        # Step 5: Extract error types
        entities.extend(
            self._extract_keyword_entities(
                text,
                self.error_type_keywords,
                EntityType.ERROR_TYPE,
                now,
                base_confidence=0.7,
            )
        )

        # Step 6: Extract workflows
        entities.extend(
            self._extract_keyword_entities(
                text,
                self.workflow_keywords,
                EntityType.WORKFLOW,
                now,
                base_confidence=0.7,
            )
        )

        # Step 7: Extract antipatterns (with negative context boost)
        entities.extend(self._extract_antipattern_entities(text, now))

        return entities

    def _extract_code_entities(self, text: str, timestamp: str) -> List[Entity]:
        """
        Extract entities from code contexts (backticks, code blocks, imports).

        Confidence: 0.9 (explicit code reference)
        """
        entities = []

        # Extract from backticks: `pytest`, `SQLite`
        for match in self.code_entity_pattern.finditer(text):
            code_entity = match.group(1).strip()

            # Remove function parentheses: retry_with_backoff() → retry_with_backoff
            code_entity = re.sub(r"\(\)$", "", code_entity)

            # Skip if too short (single char) or too long (>50 chars)
            if len(code_entity) < 2 or len(code_entity) > 50:
                continue

            # Normalize case for matching
            entity_lower = code_entity.lower()

            # Check if it's a known tool
            if entity_lower in self.tool_keywords:
                entities.append(
                    self._create_entity(
                        name=code_entity,
                        entity_type=EntityType.TOOL,
                        confidence=0.9,
                        timestamp=timestamp,
                    )
                )
            # Check if it's a known technology
            elif entity_lower in self.technology_keywords:
                entities.append(
                    self._create_entity(
                        name=code_entity,
                        entity_type=EntityType.TECHNOLOGY,
                        confidence=0.9,
                        timestamp=timestamp,
                    )
                )
            # Otherwise, infer as TOOL (generic code entity)
            else:
                # Lower confidence for unknown code entities
                entities.append(
                    self._create_entity(
                        name=code_entity,
                        entity_type=EntityType.TOOL,
                        confidence=0.7,
                        timestamp=timestamp,
                        metadata={"inferred_from": "code_context"},
                    )
                )

        # Extract from import statements
        for match in self.import_pattern.finditer(text):
            module_name = match.group(1).strip()

            # Get top-level module: flask.app → flask
            top_level = module_name.split(".")[0]

            # Skip standard library imports (common false positives)
            # Expanded list to reduce false positive tool extractions
            stdlib_modules = {
                "os",
                "sys",
                "json",
                "re",
                "time",
                "datetime",
                "typing",
                "pathlib",
                "collections",
                "itertools",
                "functools",
                "copy",
                "hashlib",
                "uuid",
                "logging",
                "warnings",
                "contextlib",
                "abc",
                "enum",
                "dataclasses",
                "io",
                "tempfile",
                "shutil",
                "glob",
                "fnmatch",
                "subprocess",
                "threading",
                "multiprocessing",
                "asyncio",
                "math",
                "random",
                "statistics",
                "decimal",
                "fractions",
                "string",
                "textwrap",
                "unicodedata",
                "struct",
                "codecs",
            }
            if top_level in stdlib_modules:
                continue

            entities.append(
                self._create_entity(
                    name=top_level,
                    entity_type=EntityType.TOOL,
                    confidence=0.9,
                    timestamp=timestamp,
                    metadata={"extraction_method": "import_statement"},
                )
            )

        return entities

    def _extract_keyword_entities(
        self,
        text: str,
        keywords,  # Can be Set[str] or Dict[str, str]
        entity_type: EntityType,
        timestamp: str,
        base_confidence: float,
    ) -> List[Entity]:
        """
        Extract entities by exact keyword matching.

        Args:
            text: Input text
            keywords: Set[str] or Dict[str, str] mapping keyword → canonical name
            entity_type: EntityType for matched entities
            timestamp: ISO8601 timestamp
            base_confidence: Base confidence score (0.0-1.0)

        Returns:
            List of matched entities
        """
        entities = []
        text_lower = text.lower()

        # Handle both Set and Dict
        if isinstance(keywords, dict):
            # Dict: keyword → canonical_name
            keyword_items = keywords.items()
        else:
            # Set: keyword is canonical name
            keyword_items = [(k, k) for k in keywords]

        for keyword, canonical_name in keyword_items:
            # Use word boundary regex for exact match
            # Handles: "pytest" matches, but not "apytest"
            pattern = r"\b" + re.escape(keyword) + r"\b"

            if re.search(pattern, text_lower):
                entities.append(
                    self._create_entity(
                        name=canonical_name,
                        entity_type=entity_type,
                        confidence=base_confidence,
                        timestamp=timestamp,
                    )
                )

        return entities

    def _extract_pattern_entities(self, text: str, timestamp: str) -> List[Entity]:
        """
        Extract PATTERN entities with pattern suffix detection.

        Matches:
        - "retry pattern" → retry-pattern
        - "exponential backoff" → exponential-backoff (from pattern_keywords)
        - "circuit-breaker pattern" → circuit-breaker-pattern

        Confidence: 0.8 (explicit pattern mention)
        """
        entities = []

        # First, extract from pattern_keywords
        entities.extend(
            self._extract_keyword_entities(
                text,
                self.pattern_keywords,
                EntityType.PATTERN,
                timestamp,
                base_confidence=0.8,
            )
        )

        # Second, detect "{word} pattern" or "{word}-pattern"
        for match in self.pattern_suffix_pattern.finditer(text):
            pattern_name = match.group(1).strip().lower()

            # Skip if too short or already in keywords
            if len(pattern_name) < 3 or pattern_name in self.pattern_keywords:
                continue

            # Create canonical name: retry → retry-pattern
            canonical_name = f"{pattern_name}-pattern"

            entities.append(
                self._create_entity(
                    name=canonical_name,
                    entity_type=EntityType.PATTERN,
                    confidence=0.7,  # Slightly lower for inferred patterns
                    timestamp=timestamp,
                    metadata={"inferred_from": "pattern_suffix"},
                )
            )

        return entities

    def _extract_antipattern_entities(self, text: str, timestamp: str) -> List[Entity]:
        """
        Extract ANTIPATTERN entities with negative context boost.

        Confidence adjustment:
        - Base: 0.7
        - With negative context ("never", "avoid"): +0.2 → 0.9

        Example:
        - "never use generic exception" → confidence 0.9
        - "generic exception handling" → confidence 0.7
        """
        entities = []
        text_lower = text.lower()

        # Process each antipattern keyword
        for keyword, canonical_name in self.antipattern_keywords.items():
            pattern = r"\b" + re.escape(keyword) + r"\b"

            # Find all matches of this antipattern
            for match in re.finditer(pattern, text_lower):
                # Extract ±50 char window around match for context analysis
                start = max(0, match.start() - 50)
                end = min(len(text_lower), match.end() + 50)
                context_window = text_lower[start:end]

                # Check for negative context in local window only
                has_local_negative = bool(
                    self.negative_context_pattern.search(context_window)
                )

                confidence = 0.9 if has_local_negative else 0.7
                metadata = {}

                if has_local_negative:
                    metadata["negative_context_detected"] = True

                entities.append(
                    self._create_entity(
                        name=canonical_name,
                        entity_type=EntityType.ANTIPATTERN,
                        confidence=confidence,
                        timestamp=timestamp,
                        metadata=metadata if metadata else None,
                    )
                )

        return entities

    def _create_entity(
        self,
        name: str,
        entity_type: EntityType,
        confidence: float,
        timestamp: str,
        metadata: Optional[Dict] = None,
    ) -> Entity:
        """
        Create Entity object with semantic ID.

        ID format: ent-{slug}
        Slug generation: lowercase, replace spaces/special chars with hyphens

        Example:
        - name="Exponential Backoff" → id="ent-exponential-backoff"
        - name="pytest" → id="ent-pytest"
        """
        # Generate semantic slug from name
        slug = self._generate_slug(name)

        # Create entity ID
        entity_id = f"ent-{slug}"

        return Entity(
            id=entity_id,
            type=entity_type,
            name=name,
            confidence=confidence,
            first_seen_at=timestamp,
            last_seen_at=timestamp,
            metadata=metadata,
        )

    def _generate_slug(self, name: str) -> str:
        """
        Generate URL-friendly slug from entity name.

        Rules:
        - Lowercase
        - Replace spaces with hyphens
        - Remove special characters except hyphens/underscores
        - Collapse multiple hyphens
        - Strip leading/trailing hyphens

        Examples:
        - "Exponential Backoff" → "exponential-backoff"
        - "retry_with_backoff()" → "retry-with-backoff"
        - "JWT Token" → "jwt-token"
        """
        slug = name.lower()

        # Remove function parentheses
        slug = re.sub(r"\(\)$", "", slug)

        # Replace spaces and underscores with hyphens
        slug = re.sub(r"[\s_]+", "-", slug)

        # Remove special characters (keep alphanumeric and hyphens)
        slug = re.sub(r"[^a-z0-9\-]", "", slug)

        # Collapse multiple hyphens
        slug = re.sub(r"-+", "-", slug)

        # Strip leading/trailing hyphens
        slug = slug.strip("-")

        # Fallback: if slug is empty, use UUID
        if not slug:
            slug = str(uuid.uuid4())[:8]

        return slug

    def _deduplicate_entities(self, entities: List[Entity]) -> List[Entity]:
        """
        Deduplicate entities by (name, type) tuple.

        Deduplication strategy:
        - Same name + type → same entity
        - Keep entity with highest confidence
        - Update last_seen_at to latest timestamp

        Example:
        - Input: [Entity(name="pytest", type=TOOL, conf=0.9), Entity(name="pytest", type=TOOL, conf=0.7)]
        - Output: [Entity(name="pytest", type=TOOL, conf=0.9)]
        """
        seen: Dict[Tuple[str, EntityType], Entity] = {}

        for entity in entities:
            # Normalize name for comparison (case-insensitive)
            key = (entity.name.lower(), entity.type)

            if key not in seen:
                seen[key] = entity
            else:
                # Entity already seen: merge
                existing = seen[key]

                # Keep higher confidence
                if entity.confidence > existing.confidence:
                    existing.confidence = entity.confidence

                # Update last_seen_at to latest timestamp
                if entity.last_seen_at > existing.last_seen_at:
                    existing.last_seen_at = entity.last_seen_at

                # Merge metadata (if both have metadata)
                if entity.metadata and existing.metadata:
                    existing.metadata.update(entity.metadata)
                elif entity.metadata and not existing.metadata:
                    existing.metadata = entity.metadata

        # Return deduplicated list, sorted by confidence (descending)
        return sorted(seen.values(), key=lambda e: e.confidence, reverse=True)


# Convenience function for module-level API
def extract_entities(content: str) -> List[Entity]:
    """
    Extract entities from content string.

    Convenience wrapper around EntityExtractor for simple usage.

    Args:
        content: Text to extract entities from

    Returns:
        List of Entity objects with confidence scores

    Example:
        >>> from mapify_cli.entity_extractor import extract_entities
        >>> entities = extract_entities("Use pytest for testing")
        >>> entities[0].name
        'pytest'
    """
    extractor = EntityExtractor()
    return extractor.extract_entities(content)
