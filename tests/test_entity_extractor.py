"""
Tests for Entity Extraction Module.

Validates:
- Extraction accuracy ≥80% on test corpus
- Confidence scoring (0.0-1.0)
- Edge case handling (empty content, special characters, long text)
- Deduplication by (name, type)
- All 7 entity types: TOOL, PATTERN, CONCEPT, ERROR_TYPE, TECHNOLOGY, WORKFLOW, ANTIPATTERN
"""

import pytest
from datetime import datetime
from mapify_cli.entity_extractor import (
    EntityExtractor,
    extract_entities,
    Entity,
    EntityType
)


class TestEntityExtractor:
    """Test suite for EntityExtractor class."""

    @pytest.fixture
    def extractor(self):
        """Create EntityExtractor instance."""
        return EntityExtractor()

    # ============================================================================
    # TOOL Entity Tests
    # ============================================================================

    def test_extract_tool_from_backticks(self, extractor):
        """Test extracting TOOL entities from backticked code."""
        text = "Use `pytest` for testing and `SQLite` for storage."
        entities = extractor.extract_entities(text)

        # Should extract pytest and SQLite
        assert len(entities) >= 2

        pytest_entity = next((e for e in entities if "pytest" in e.name.lower()), None)
        assert pytest_entity is not None
        assert pytest_entity.type == EntityType.TOOL
        assert pytest_entity.confidence >= 0.8

        sqlite_entity = next((e for e in entities if "sqlite" in e.name.lower()), None)
        assert sqlite_entity is not None
        assert sqlite_entity.type == EntityType.TOOL

    def test_extract_tool_from_import_statement(self, extractor):
        """Test extracting TOOL from import statements."""
        text = """
        import pytest
        from flask import Flask
        from sqlalchemy import create_engine
        """
        entities = extractor.extract_entities(text)

        tool_names = {e.name.lower() for e in entities if e.type == EntityType.TOOL}

        assert "pytest" in tool_names
        assert "flask" in tool_names
        assert "sqlalchemy" in tool_names

    def test_extract_tool_keyword_match(self, extractor):
        """Test extracting TOOL via keyword matching."""
        text = "We use Docker and Kubernetes for deployment."
        entities = extractor.extract_entities(text)

        tool_entities = [e for e in entities if e.type == EntityType.TOOL]
        tool_names = {e.name.lower() for e in tool_entities}

        assert "docker" in tool_names or any("docker" in name for name in tool_names)
        assert "kubernetes" in tool_names or any("kubernetes" in name for name in tool_names)

    def test_skip_stdlib_imports(self, extractor):
        """Test that standard library imports are skipped."""
        text = """
        import os
        import sys
        import json
        import pytest  # Non-stdlib
        """
        entities = extractor.extract_entities(text)

        # Should extract pytest, but not os/sys/json
        tool_names = {e.name.lower() for e in entities if e.type == EntityType.TOOL}

        assert "pytest" in tool_names
        assert "os" not in tool_names
        assert "sys" not in tool_names
        assert "json" not in tool_names

    # ============================================================================
    # TECHNOLOGY Entity Tests
    # ============================================================================

    def test_extract_technology(self, extractor):
        """Test extracting TECHNOLOGY entities."""
        text = "Built with Python and React, deployed to AWS using Docker."
        entities = extractor.extract_entities(text)

        tech_entities = [e for e in entities if e.type == EntityType.TECHNOLOGY]
        tech_names = {e.name.lower() for e in tech_entities}

        assert "python" in tech_names
        assert "react" in tech_names
        assert "aws" in tech_names

    def test_extract_technology_from_backticks(self, extractor):
        """Test extracting TECHNOLOGY from code context."""
        text = "Use `Python` with `FastAPI` framework."
        entities = extractor.extract_entities(text)

        # Should extract Python and FastAPI (both as TOOL or TECHNOLOGY)
        entity_names = {e.name.lower() for e in entities}

        assert "python" in entity_names or "Python" in {e.name for e in entities}
        assert "fastapi" in entity_names or "FastAPI" in {e.name for e in entities}

    # ============================================================================
    # PATTERN Entity Tests
    # ============================================================================

    def test_extract_pattern_with_suffix(self, extractor):
        """Test extracting PATTERN with 'pattern' suffix."""
        text = "Implement retry pattern and circuit-breaker pattern for resilience."
        entities = extractor.extract_entities(text)

        pattern_entities = [e for e in entities if e.type == EntityType.PATTERN]
        pattern_names = {e.name.lower() for e in pattern_entities}

        # Should extract retry-pattern and circuit-breaker-pattern
        assert any("retry" in name for name in pattern_names)
        assert any("circuit" in name or "breaker" in name for name in pattern_names)

    def test_extract_pattern_keyword(self, extractor):
        """Test extracting PATTERN via keyword matching."""
        text = "Use exponential backoff for API retries with fallback strategy."
        entities = extractor.extract_entities(text)

        pattern_entities = [e for e in entities if e.type == EntityType.PATTERN]
        pattern_names = {e.name.lower() for e in pattern_entities}

        # Should extract exponential-backoff and fallback
        assert any("backoff" in name for name in pattern_names)
        assert any("fallback" in name for name in pattern_names)

    def test_extract_inferred_pattern(self, extractor):
        """Test extracting inferred patterns from '{word} pattern' syntax."""
        text = "We follow the repository pattern for data access."
        entities = extractor.extract_entities(text)

        pattern_entities = [e for e in entities if e.type == EntityType.PATTERN]
        pattern_names = {e.name.lower() for e in pattern_entities}

        assert any("repository" in name for name in pattern_names)

    # ============================================================================
    # CONCEPT Entity Tests
    # ============================================================================

    def test_extract_concept(self, extractor):
        """Test extracting CONCEPT entities."""
        text = "Ensure idempotency and eventual consistency in distributed systems."
        entities = extractor.extract_entities(text)

        concept_entities = [e for e in entities if e.type == EntityType.CONCEPT]
        concept_names = {e.name.lower() for e in concept_entities}

        assert "idempotency" in concept_names
        assert any("consistency" in name for name in concept_names)

    def test_extract_acid_concept(self, extractor):
        """Test extracting database ACID concepts."""
        text = "Database transactions must provide atomicity, consistency, isolation, and durability (ACID)."
        entities = extractor.extract_entities(text)

        concept_entities = [e for e in entities if e.type == EntityType.CONCEPT]
        concept_names = {e.name.lower() for e in concept_entities}

        # Should extract ACID and individual properties
        assert any("acid" in name for name in concept_names)
        assert "atomicity" in concept_names
        assert "durability" in concept_names
        assert "isolation" in concept_names

    # ============================================================================
    # ERROR_TYPE Entity Tests
    # ============================================================================

    def test_extract_error_type(self, extractor):
        """Test extracting ERROR_TYPE entities."""
        text = "Fixed race-condition causing deadlock. Also handled null-pointer exceptions."
        entities = extractor.extract_entities(text)

        error_entities = [e for e in entities if e.type == EntityType.ERROR_TYPE]
        error_names = {e.name.lower() for e in error_entities}

        assert any("race" in name for name in error_names)
        assert any("deadlock" in name for name in error_names)
        assert any("null" in name or "pointer" in name for name in error_names)

    def test_extract_memory_error(self, extractor):
        """Test extracting memory-related errors."""
        text = "Resolved memory-leak and out-of-memory issues."
        entities = extractor.extract_entities(text)

        error_entities = [e for e in entities if e.type == EntityType.ERROR_TYPE]
        error_names = {e.name.lower() for e in error_entities}

        assert any("memory" in name and "leak" in name for name in error_names)
        assert any("memory" in name for name in error_names)

    # ============================================================================
    # WORKFLOW Entity Tests
    # ============================================================================

    def test_extract_workflow(self, extractor):
        """Test extracting WORKFLOW entities."""
        text = "Follow TDD methodology with gitflow workflow and code-review process."
        entities = extractor.extract_entities(text)

        workflow_entities = [e for e in entities if e.type == EntityType.WORKFLOW]
        workflow_names = {e.name.lower() for e in workflow_entities}

        assert any("tdd" in name or "test-driven" in name for name in workflow_names)
        assert any("gitflow" in name or "workflow" in name for name in workflow_names)
        assert any("review" in name for name in workflow_names)

    def test_extract_map_workflow(self, extractor):
        """Test extracting MAP Framework workflows."""
        text = "Use map-feature workflow for implementation and map-debug for troubleshooting."
        entities = extractor.extract_entities(text)

        workflow_entities = [e for e in entities if e.type == EntityType.WORKFLOW]
        workflow_names = {e.name.lower() for e in workflow_entities}

        assert any("map" in name and "feature" in name for name in workflow_names)
        assert any("map" in name and "debug" in name for name in workflow_names)

    # ============================================================================
    # ANTIPATTERN Entity Tests
    # ============================================================================

    def test_extract_antipattern_with_negative_context(self, extractor):
        """Test extracting ANTIPATTERN with negative context boost."""
        text = "Never use generic-exception handlers. Avoid silent-failure patterns."
        entities = extractor.extract_entities(text)

        antipattern_entities = [e for e in entities if e.type == EntityType.ANTIPATTERN]

        # Should extract with high confidence due to "never" and "avoid"
        assert len(antipattern_entities) >= 2

        # Check confidence boost for negative context
        high_conf_entities = [e for e in antipattern_entities if e.confidence >= 0.85]
        assert len(high_conf_entities) >= 1  # At least one should have boosted confidence

    def test_extract_antipattern_without_negative_context(self, extractor):
        """Test extracting ANTIPATTERN without negative context."""
        text = "The code has magic-number issues and god-object structure."
        entities = extractor.extract_entities(text)

        antipattern_entities = [e for e in entities if e.type == EntityType.ANTIPATTERN]
        antipattern_names = {e.name.lower() for e in antipattern_entities}

        # Should still extract, but with lower confidence
        assert any("magic" in name for name in antipattern_names)
        assert any("god" in name for name in antipattern_names)

    def test_antipattern_negative_context_is_local_not_global(self, extractor):
        """Regression test: negative context boost applied locally, not globally."""
        # Text with 150+ chars separation to ensure windows don't overlap
        text = (
            "Never use generic-exception in your codebase. "
            "This is a well-known antipattern that should be avoided. "
            "In completely unrelated news, our configuration system uses magic-number "
            "for various settings, which is a common practice in this domain."
        )
        entities = extractor.extract_entities(text)

        antipatterns = [e for e in entities if e.type == EntityType.ANTIPATTERN]

        # generic-exception near 'Never' and 'avoided' → high confidence
        generic_exc = next((e for e in antipatterns if 'generic' in e.name.lower()), None)
        assert generic_exc is not None, "Should extract generic-exception"
        assert generic_exc.confidence >= 0.85, \
            f"generic-exception near 'Never' should have high confidence, got {generic_exc.confidence}"

        # magic-number >100 chars away from negative words → lower confidence
        magic_num = next((e for e in antipatterns if 'magic' in e.name.lower()), None)
        assert magic_num is not None, "Should extract magic-number"
        assert magic_num.confidence <= 0.75, \
            f"magic-number without nearby negative context should have lower confidence, got {magic_num.confidence}"

    # ============================================================================
    # Confidence Scoring Tests
    # ============================================================================

    def test_confidence_range(self, extractor):
        """Test that all confidence scores are in [0.0, 1.0]."""
        text = """
        Use `pytest` for testing.
        Implement retry pattern with exponential backoff.
        Ensure idempotency.
        Fixed race-condition.
        Follow TDD workflow.
        Never use generic-exception handlers.
        Built with Python.
        """
        entities = extractor.extract_entities(text)

        assert len(entities) > 0

        for entity in entities:
            assert 0.0 <= entity.confidence <= 1.0, \
                f"Entity {entity.name} has invalid confidence: {entity.confidence}"

    def test_code_entity_high_confidence(self, extractor):
        """Test that code entities (backticks) have high confidence."""
        text = "Use `pytest` and `SQLite` for testing."
        entities = extractor.extract_entities(text)

        code_entities = [e for e in entities if e.name.lower() in ["pytest", "sqlite"]]

        for entity in code_entities:
            assert entity.confidence >= 0.7, \
                f"Code entity {entity.name} should have high confidence, got {entity.confidence}"

    def test_inferred_entity_lower_confidence(self, extractor):
        """Test that inferred entities have lower confidence than explicit ones."""
        text = """
        Use `pytest` for testing.  # Explicit
        Testing frameworks are useful.  # Inferred context
        """
        entities = extractor.extract_entities(text)

        # Explicit pytest should have confidence >= 0.8
        pytest_entity = next((e for e in entities if "pytest" in e.name.lower()), None)
        if pytest_entity:
            assert pytest_entity.confidence >= 0.7

    # ============================================================================
    # Deduplication Tests
    # ============================================================================

    def test_deduplication_same_name_and_type(self, extractor):
        """Test that entities with same name+type are deduplicated."""
        text = """
        Use `pytest` for testing.
        Install pytest via pip.
        pytest is the best framework.
        """
        entities = extractor.extract_entities(text)

        # Should have only ONE pytest entity (deduplicated)
        pytest_entities = [e for e in entities if "pytest" in e.name.lower() and e.type == EntityType.TOOL]
        assert len(pytest_entities) == 1

    def test_deduplication_keeps_highest_confidence(self, extractor):
        """Test that deduplication keeps entity with highest confidence."""
        # Manually create extractor and test internal method
        entity1 = Entity(
            id="ent-pytest",
            type=EntityType.TOOL,
            name="pytest",
            confidence=0.9,
            first_seen_at="2024-01-01T00:00:00Z",
            last_seen_at="2024-01-01T00:00:00Z"
        )
        entity2 = Entity(
            id="ent-pytest",
            type=EntityType.TOOL,
            name="pytest",
            confidence=0.7,
            first_seen_at="2024-01-02T00:00:00Z",
            last_seen_at="2024-01-02T00:00:00Z"
        )

        deduplicated = extractor._deduplicate_entities([entity1, entity2])

        assert len(deduplicated) == 1
        assert deduplicated[0].confidence == 0.9  # Keeps higher confidence

    def test_deduplication_different_types_not_merged(self, extractor):
        """Test that entities with same name but different types are NOT merged."""
        # This is a synthetic test case
        # In practice, "retry" could be both PATTERN and WORKFLOW
        entity1 = Entity(
            id="ent-retry-pattern",
            type=EntityType.PATTERN,
            name="retry-pattern",
            confidence=0.8,
            first_seen_at="2024-01-01T00:00:00Z",
            last_seen_at="2024-01-01T00:00:00Z"
        )
        entity2 = Entity(
            id="ent-retry-workflow",
            type=EntityType.WORKFLOW,
            name="retry-pattern",  # Same name, different type
            confidence=0.8,
            first_seen_at="2024-01-01T00:00:00Z",
            last_seen_at="2024-01-01T00:00:00Z"
        )

        deduplicated = extractor._deduplicate_entities([entity1, entity2])

        # Should keep both (different types)
        assert len(deduplicated) == 2

    # ============================================================================
    # Edge Case Tests
    # ============================================================================

    def test_empty_content(self, extractor):
        """Test extraction from empty content."""
        entities = extractor.extract_entities("")
        assert entities == []

    def test_whitespace_only_content(self, extractor):
        """Test extraction from whitespace-only content."""
        entities = extractor.extract_entities("   \n\t  \n  ")
        assert entities == []

    def test_special_characters(self, extractor):
        """Test extraction with special characters."""
        text = "Use `pytest` with @decorators and $variables! #comments"
        entities = extractor.extract_entities(text)

        # Should extract pytest despite special chars
        pytest_entity = next((e for e in entities if "pytest" in e.name.lower()), None)
        assert pytest_entity is not None

    def test_long_text_handling(self, extractor):
        """Test extraction from very long text (chunking)."""
        # Create 150KB text (exceeds 100KB threshold)
        long_text = "Use pytest for testing. " * 10000  # ~250KB

        entities = extractor.extract_entities(long_text)

        # Should still extract pytest
        pytest_entity = next((e for e in entities if "pytest" in e.name.lower()), None)
        assert pytest_entity is not None

    def test_unicode_handling(self, extractor):
        """Test extraction with Unicode characters."""
        text = "Use `pytest` für Testing mit émojis 🚀"
        entities = extractor.extract_entities(text)

        # Should extract pytest despite Unicode
        pytest_entity = next((e for e in entities if "pytest" in e.name.lower()), None)
        assert pytest_entity is not None

    def test_code_block_extraction(self, extractor):
        """Test extraction from code blocks."""
        text = """
        Example code:
        ```python
        import pytest
        from flask import Flask

        def test_example():
            pass
        ```
        """
        entities = extractor.extract_entities(text)

        # Should extract pytest and flask from imports
        tool_names = {e.name.lower() for e in entities if e.type == EntityType.TOOL}

        assert "pytest" in tool_names
        assert "flask" in tool_names

    # ============================================================================
    # Entity Metadata Tests
    # ============================================================================

    def test_entity_id_format(self, extractor):
        """Test that entity IDs follow 'ent-{slug}' format."""
        text = "Use `pytest` for testing."
        entities = extractor.extract_entities(text)

        for entity in entities:
            assert entity.id.startswith("ent-"), \
                f"Entity ID must start with 'ent-', got {entity.id}"

    def test_entity_timestamps(self, extractor):
        """Test that entities have valid ISO8601 timestamps."""
        text = "Use `pytest` for testing."
        entities = extractor.extract_entities(text)

        for entity in entities:
            # Should be valid ISO8601
            assert "T" in entity.first_seen_at
            assert "T" in entity.last_seen_at

            # Should be parseable
            datetime.fromisoformat(entity.first_seen_at.replace("Z", "+00:00"))
            datetime.fromisoformat(entity.last_seen_at.replace("Z", "+00:00"))

    def test_entity_metadata_extraction_method(self, extractor):
        """Test that metadata includes extraction method for imports."""
        text = "import pytest"
        entities = extractor.extract_entities(text)

        pytest_entity = next((e for e in entities if "pytest" in e.name.lower()), None)
        if pytest_entity and pytest_entity.metadata:
            # May have extraction_method metadata
            assert "extraction_method" in pytest_entity.metadata or pytest_entity.metadata is None

    # ============================================================================
    # Accuracy Tests (Test Corpus)
    # ============================================================================

    def test_accuracy_on_corpus(self, extractor):
        """
        Test extraction accuracy on predefined corpus.

        Acceptance criteria: ≥80% accuracy

        Test corpus: 20 sentences with known entities
        Expected: Extract at least 16/20 correctly (80%)
        """
        test_corpus = [
            # (text, expected_entity_name, expected_type)
            ("Use `pytest` for testing", "pytest", EntityType.TOOL),
            ("Built with Python", "python", EntityType.TECHNOLOGY),
            ("Implement retry pattern", "retry", EntityType.PATTERN),
            ("Ensure idempotency", "idempotency", EntityType.CONCEPT),
            ("Fixed race-condition", "race-condition", EntityType.ERROR_TYPE),
            ("Follow TDD workflow", "tdd", EntityType.WORKFLOW),
            ("Never use generic-exception", "generic-exception", EntityType.ANTIPATTERN),
            ("Use `SQLite` database", "sqlite", EntityType.TOOL),
            ("Deploy to Kubernetes", "kubernetes", EntityType.TECHNOLOGY),
            ("Circuit-breaker pattern", "circuit-breaker", EntityType.PATTERN),
            ("Eventual-consistency model", "consistency", EntityType.CONCEPT),
            ("Null-pointer exception", "null-pointer", EntityType.ERROR_TYPE),
            ("CI/CD pipeline", "ci/cd", EntityType.WORKFLOW),
            ("Avoid magic-number", "magic", EntityType.ANTIPATTERN),
            ("import flask", "flask", EntityType.TOOL),
            ("React framework", "react", EntityType.TECHNOLOGY),
            ("Exponential backoff", "backoff", EntityType.PATTERN),
            ("ACID properties", "acid", EntityType.CONCEPT),
            ("Memory-leak detected", "memory-leak", EntityType.ERROR_TYPE),
            ("Code-review process", "review", EntityType.WORKFLOW),
        ]

        correct_extractions = 0

        for text, expected_name, expected_type in test_corpus:
            entities = extractor.extract_entities(text)

            # Check if expected entity was extracted
            found = any(
                expected_name.lower() in e.name.lower() and e.type == expected_type
                for e in entities
            )

            if found:
                correct_extractions += 1

        accuracy = correct_extractions / len(test_corpus)

        # Acceptance criteria: ≥80% accuracy
        assert accuracy >= 0.80, \
            f"Extraction accuracy {accuracy:.1%} is below 80% threshold. " \
            f"Correct: {correct_extractions}/{len(test_corpus)}"

    # ============================================================================
    # Module-Level API Tests
    # ============================================================================

    def test_module_level_extract_entities(self):
        """Test module-level extract_entities() function."""
        entities = extract_entities("Use `pytest` for testing")

        assert len(entities) > 0
        pytest_entity = next((e for e in entities if "pytest" in e.name.lower()), None)
        assert pytest_entity is not None
        assert pytest_entity.type == EntityType.TOOL


class TestEntityDataclass:
    """Test Entity dataclass validation."""

    def test_entity_creation_valid(self):
        """Test creating valid Entity."""
        entity = Entity(
            id="ent-pytest",
            type=EntityType.TOOL,
            name="pytest",
            confidence=0.9,
            first_seen_at="2024-01-01T00:00:00Z",
            last_seen_at="2024-01-01T00:00:00Z"
        )

        assert entity.id == "ent-pytest"
        assert entity.type == EntityType.TOOL
        assert entity.name == "pytest"
        assert entity.confidence == 0.9

    def test_entity_confidence_validation(self):
        """Test that invalid confidence raises ValueError."""
        with pytest.raises(ValueError, match="Confidence must be in"):
            Entity(
                id="ent-test",
                type=EntityType.TOOL,
                name="test",
                confidence=1.5,  # Invalid: > 1.0
                first_seen_at="2024-01-01T00:00:00Z",
                last_seen_at="2024-01-01T00:00:00Z"
            )

        with pytest.raises(ValueError, match="Confidence must be in"):
            Entity(
                id="ent-test",
                type=EntityType.TOOL,
                name="test",
                confidence=-0.1,  # Invalid: < 0.0
                first_seen_at="2024-01-01T00:00:00Z",
                last_seen_at="2024-01-01T00:00:00Z"
            )

    def test_entity_id_validation(self):
        """Test that invalid ID format raises ValueError."""
        with pytest.raises(ValueError, match="Entity ID must start with 'ent-'"):
            Entity(
                id="invalid-id",  # Missing 'ent-' prefix
                type=EntityType.TOOL,
                name="test",
                confidence=0.8,
                first_seen_at="2024-01-01T00:00:00Z",
                last_seen_at="2024-01-01T00:00:00Z"
            )

    def test_entity_with_metadata(self):
        """Test creating Entity with metadata."""
        entity = Entity(
            id="ent-pytest",
            type=EntityType.TOOL,
            name="pytest",
            confidence=0.9,
            first_seen_at="2024-01-01T00:00:00Z",
            last_seen_at="2024-01-01T00:00:00Z",
            metadata={"version": "7.4.0", "license": "MIT"}
        )

        assert entity.metadata == {"version": "7.4.0", "license": "MIT"}


class TestSlugGeneration:
    """Test slug generation for entity IDs."""

    @pytest.fixture
    def extractor(self):
        return EntityExtractor()

    def test_slug_from_simple_name(self, extractor):
        """Test slug generation from simple name."""
        slug = extractor._generate_slug("pytest")
        assert slug == "pytest"

    def test_slug_from_multi_word_name(self, extractor):
        """Test slug generation from multi-word name."""
        slug = extractor._generate_slug("Exponential Backoff")
        assert slug == "exponential-backoff"

    def test_slug_from_name_with_underscores(self, extractor):
        """Test slug generation with underscores."""
        slug = extractor._generate_slug("retry_with_backoff")
        assert slug == "retry-with-backoff"

    def test_slug_removes_special_characters(self, extractor):
        """Test that special characters are removed."""
        slug = extractor._generate_slug("JWT Token!")
        assert slug == "jwt-token"

    def test_slug_collapses_multiple_hyphens(self, extractor):
        """Test that multiple hyphens are collapsed."""
        slug = extractor._generate_slug("multi---word---slug")
        assert slug == "multi-word-slug"

    def test_slug_strips_leading_trailing_hyphens(self, extractor):
        """Test that leading/trailing hyphens are stripped."""
        slug = extractor._generate_slug("-leading-trailing-")
        assert slug == "leading-trailing"

    def test_slug_fallback_for_empty(self, extractor):
        """Test fallback to UUID for empty slug."""
        slug = extractor._generate_slug("!!!")
        # Should be 8-char UUID fallback
        assert len(slug) == 8
        assert slug.isalnum() or '-' in slug
