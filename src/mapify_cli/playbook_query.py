"""
Playbook Query API - Dataclasses and enums for playbook search.

This module defines the query API for efficient playbook searching using
SQLite FTS5 full-text search and optional cipher integration.

Based on: docs/playbook-query-api-spec.md v2.1
"""

from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from enum import Enum


# Valid section names for validation
VALID_SECTIONS = {
    "ARCHITECTURE_PATTERNS",
    "IMPLEMENTATION_PATTERNS",
    "SECURITY_PATTERNS",
    "PERFORMANCE_PATTERNS",
    "TESTING_STRATEGIES",
    "ERROR_PATTERNS",
    "DEBUGGING_TECHNIQUES",
    "CODE_QUALITY_RULES",
    "TOOL_USAGE",
    "CLI_TOOL_PATTERNS",
    "DOCUMENTATION_PATTERNS",
    "DEPLOYMENT_PATTERNS",
    "MONITORING_PATTERNS",
}


class SearchMode(Enum):
    """Search mode for playbook queries."""

    CIPHER_ONLY = "cipher_only"  # Search cipher only
    PLAYBOOK_ONLY = "playbook_only"  # Search local playbook only
    HYBRID = "hybrid"  # Search both (default)


@dataclass
class PlaybookQuery:
    """Query parameters for playbook search."""

    # Primary query
    query: str
    """
    Task description or keywords to search for.
    Examples:
    - "implement JWT authentication"
    - "fix rate limiting memory leak"
    - "optimize database queries"
    """

    # Filtering
    sections: Optional[List[str]] = None
    """
    Filter by section names. If None, searches all sections.
    Examples:
    - ["SECURITY_PATTERNS", "IMPLEMENTATION_PATTERNS"]
    - ["ERROR_PATTERNS", "DEBUGGING_TECHNIQUES"]
    """

    min_quality_score: int = 0
    """
    Minimum (helpful_count - harmful_count) score.
    Default: 0 (include all non-negative bullets)
    Recommended for production: 3 (proven patterns)
    """

    exclude_deprecated: bool = True
    """Whether to exclude deprecated bullets (default: True)"""

    # Result limits
    limit: Optional[int] = None
    """
    Maximum bullets to return.
    Default: None (uses playbook.metadata.top_k, currently 5)
    """

    # Semantic search
    similarity_threshold: float = 0.3
    """
    Minimum semantic similarity for results (0.0-1.0).
    Only used when semantic search is available.
    Default: 0.3 (30% similarity)
    """

    # Search mode
    search_mode: SearchMode = SearchMode.PLAYBOOK_ONLY
    """
    Search mode: CIPHER_ONLY, PLAYBOOK_ONLY, or HYBRID.
    Default: PLAYBOOK_ONLY
    Note: CIPHER_ONLY and HYBRID deferred to future subtasks
    """

    # FTS5 options
    fts_prefix: bool = True
    """
    Enable FTS5 prefix matching (e.g., "JWT*" matches "JWT", "JWTs").
    Default: True
    """

    def __post_init__(self):
        """Validate query parameters."""
        # Query string validation
        if not self.query or len(self.query.strip()) == 0:
            raise ValueError("Query string cannot be empty")
        if len(self.query) > 1000:
            raise ValueError("Query string too long (max 1000 characters)")

        # Sections validation
        if self.sections:
            invalid = set(self.sections) - VALID_SECTIONS
            if invalid:
                raise ValueError(f"Invalid sections: {invalid}")

        # Similarity threshold validation (clamp instead of error)
        if not 0.0 <= self.similarity_threshold <= 1.0:
            self.similarity_threshold = max(0.0, min(1.0, self.similarity_threshold))

        # Limit validation
        if self.limit is not None and self.limit < 1:
            raise ValueError("Limit must be >= 1")


@dataclass
class PlaybookResult:
    """Single playbook search result."""

    # Bullet metadata
    id: str
    section: str
    content: str
    code_example: Optional[str]

    # Quality metrics
    helpful_count: int
    harmful_count: int
    quality_score: int  # helpful - harmful

    # Relevance
    relevance_score: float
    """
    - FTS5: BM25 rank score (0.0-1.0, normalized)
    - Semantic search: cosine similarity (0.0-1.0)
    - Combined: weighted average of FTS + semantic
    """

    source: str  # "playbook" or "cipher"

    # Combined score for sorting
    combined_score: float
    """
    Combined relevance + quality score: relevance * 0.7 + quality * 0.03
    Used for final result ranking
    """

    # Context
    related_bullets: List[str]
    tags: List[str]
    created_at: str
    last_used_at: str


@dataclass
class PlaybookQueryResponse:
    """Response from playbook query."""

    results: List[PlaybookResult]
    """Search results sorted by combined_score (relevance + quality)."""

    metadata: Dict[str, Any]
    """
    Query metadata:
    - total_candidates: int (bullets evaluated)
    - search_time_ms: int
    - search_method: str ("fts5", "semantic", "fts5+semantic")
    - cipher_results: int (how many from cipher)
    - playbook_results: int (how many from local playbook)
    - sections_searched: List[str]
    """
