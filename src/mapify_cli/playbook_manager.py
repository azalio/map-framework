"""
ACE-style Playbook Manager for MAP Framework.

Handles deterministic merging of delta operations, deduplication of bullets,
and retrieval of relevant knowledge bullets for Agent context.

Based on research: Agentic Context Engineering (ACE) - arXiv:2510.04618v1
"""

import json
import hashlib
import sys
from datetime import datetime
from typing import List, Dict, Any, Optional
from pathlib import Path
import re

# Optional: Semantic search with sentence-transformers
try:
    from mapify_cli.semantic_search import SemanticSearchEngine
    SEMANTIC_SEARCH_AVAILABLE = True
except (ImportError, ValueError) as e:
    # Handle both ImportError and ValueError (e.g., Keras compatibility issues)
    SEMANTIC_SEARCH_AVAILABLE = False
    SemanticSearchEngine = None  # Define placeholder
    # Debug: Print error if verbose mode
    import os
    if os.environ.get('DEBUG_SEMANTIC_SEARCH'):
        print(f"Semantic search unavailable: {type(e).__name__}: {e}")


class PlaybookManager:
    """Manages ACE-style playbook with incremental delta updates."""

    def __init__(
        self,
        playbook_path: str = ".claude/playbook.json",
        use_semantic_search: bool = True
    ):
        self.playbook_path = Path(playbook_path)
        self.playbook = self._load_playbook()

        # Initialize semantic search engine if available
        self.semantic_engine = None
        if use_semantic_search and SEMANTIC_SEARCH_AVAILABLE:
            try:
                self.semantic_engine = SemanticSearchEngine()
                print("✓ Semantic search enabled", file=sys.stderr)
            except Exception as e:
                print(f"Warning: Could not initialize semantic search: {e}", file=sys.stderr)
                print("  Falling back to keyword matching", file=sys.stderr)

    def _load_playbook(self) -> Dict:
        """Load playbook from disk or create empty one."""
        if not self.playbook_path.exists():
            self.playbook_path.parent.mkdir(parents=True, exist_ok=True)
            playbook = self._create_empty_playbook()
            self._save_playbook(playbook)
            return playbook

        with open(self.playbook_path, 'r', encoding='utf-8') as f:
            playbook = json.load(f)

        # Ensure top_k exists with default value for backward compatibility
        if "top_k" not in playbook.get("metadata", {}):
            playbook.setdefault("metadata", {})["top_k"] = 5

        return playbook

    def _create_empty_playbook(self) -> Dict:
        """Create empty playbook structure."""
        return {
            "version": "1.0",
            "metadata": {
                "project": "map-framework",
                "created_at": datetime.utcnow().isoformat() + "Z",
                "last_updated": datetime.utcnow().isoformat() + "Z",
                "total_bullets": 0,
                "sections_count": 9,
                # Phase 1.3: Limit playbook patterns to reduce context distraction and save ~15% tokens
                "top_k": 5
            },
            "sections": {
                "ARCHITECTURE_PATTERNS": {
                    "description": "Proven architectural decisions",
                    "bullets": []
                },
                "IMPLEMENTATION_PATTERNS": {
                    "description": "Code patterns for common tasks",
                    "bullets": []
                },
                "SECURITY_PATTERNS": {
                    "description": "Security best practices",
                    "bullets": []
                },
                "PERFORMANCE_PATTERNS": {
                    "description": "Optimization techniques",
                    "bullets": []
                },
                "ERROR_PATTERNS": {
                    "description": "Common errors and solutions",
                    "bullets": []
                },
                "TESTING_STRATEGIES": {
                    "description": "Test patterns and coverage",
                    "bullets": []
                },
                "CODE_QUALITY_RULES": {
                    "description": "Style guides and maintainability",
                    "bullets": []
                },
                "TOOL_USAGE": {
                    "description": "Library and framework usage",
                    "bullets": []
                },
                "DEBUGGING_TECHNIQUES": {
                    "description": "Troubleshooting workflows",
                    "bullets": []
                }
            }
        }

    def apply_delta(self, operations: List[Dict]) -> Dict:
        """
        Apply incremental delta updates (ACE-style).

        Args:
            operations: List of delta operations from Curator

        Returns:
            Summary of applied operations

        Example:
            operations = [
                {"type": "ADD", "section": "SECURITY_PATTERNS", "content": "..."},
                {"type": "UPDATE", "bullet_id": "sec-0012", "increment_helpful": 1}
            ]
        """
        summary = {
            "added": 0,
            "updated": 0,
            "deprecated": 0,
            "errors": []
        }

        for op in operations:
            try:
                op_type = op.get("type")

                if op_type == "ADD":
                    self._add_bullet(
                        section=op["section"],
                        content=op["content"],
                        code_example=op.get("code_example"),
                        related_to=op.get("related_to", []),
                        tags=op.get("tags", [])
                    )
                    summary["added"] += 1

                elif op_type == "UPDATE":
                    self._update_bullet(
                        bullet_id=op["bullet_id"],
                        increment_helpful=op.get("increment_helpful", 0),
                        increment_harmful=op.get("increment_harmful", 0)
                    )
                    summary["updated"] += 1

                elif op_type == "DEPRECATE":
                    self._deprecate_bullet(
                        bullet_id=op["bullet_id"],
                        reason=op.get("reason", "Marked as harmful")
                    )
                    summary["deprecated"] += 1

                else:
                    summary["errors"].append(f"Unknown operation type: {op_type}")

            except Exception as e:
                summary["errors"].append(f"Error applying {op}: {str(e)}")

        # Run deduplication after applying all operations
        if summary["added"] > 0:
            dedup_summary = self._deduplicate()
            summary["deduplicated"] = dedup_summary.get("removed", 0)

        self._save_playbook(self.playbook)
        return summary

    def _add_bullet(
        self,
        section: str,
        content: str,
        code_example: Optional[str] = None,
        related_to: List[str] = None,
        tags: List[str] = None
    ) -> str:
        """Add new bullet to section."""
        if section not in self.playbook["sections"]:
            raise ValueError(f"Unknown section: {section}")

        bullet_id = self._generate_id(section)
        now = datetime.utcnow().isoformat() + "Z"

        bullet = {
            "id": bullet_id,
            "content": content,
            "code_example": code_example,
            "helpful_count": 0,
            "harmful_count": 0,
            "created_at": now,
            "last_used_at": now,
            "related_bullets": related_to or [],
            "tags": tags or [],
            "deprecated": False,
            "deprecation_reason": None
        }

        self.playbook["sections"][section]["bullets"].append(bullet)
        self.playbook["metadata"]["total_bullets"] += 1

        return bullet_id

    def _update_bullet(
        self,
        bullet_id: str,
        increment_helpful: int = 0,
        increment_harmful: int = 0
    ) -> bool:
        """Update bullet counters."""
        bullet = self._find_bullet(bullet_id)
        if not bullet:
            return False

        bullet["helpful_count"] += increment_helpful
        bullet["harmful_count"] += increment_harmful
        bullet["last_used_at"] = datetime.utcnow().isoformat() + "Z"

        # Auto-deprecate if harmful_count >= 3
        if bullet["harmful_count"] >= 3 and not bullet["deprecated"]:
            bullet["deprecated"] = True
            bullet["deprecation_reason"] = f"High harmful count ({bullet['harmful_count']})"

        return True

    def _deprecate_bullet(self, bullet_id: str, reason: str) -> bool:
        """Mark bullet as deprecated."""
        bullet = self._find_bullet(bullet_id)
        if not bullet:
            return False

        bullet["deprecated"] = True
        bullet["deprecation_reason"] = reason
        return True

    def _find_bullet(self, bullet_id: str) -> Optional[Dict]:
        """Find bullet by ID across all sections."""
        for section in self.playbook["sections"].values():
            for bullet in section["bullets"]:
                if bullet["id"] == bullet_id:
                    return bullet
        return None

    def _generate_id(self, section: str) -> str:
        """Generate unique bullet ID."""
        # Extract prefix from section name (first 4 chars, lowercase)
        prefix = re.sub(r'[^a-z]', '', section.lower())[:4]

        # Count existing bullets in section
        count = len(self.playbook["sections"][section]["bullets"])

        return f"{prefix}-{count:04d}"

    def _deduplicate(self, threshold: float = 0.9) -> Dict:
        """
        Remove semantic duplicates using semantic similarity or content comparison.

        Uses semantic search if available, otherwise falls back to exact matching.

        Args:
            threshold: Similarity threshold for duplicates (0.9 = 90% similar)

        Returns:
            Summary dict with removed/merged counts
        """
        summary = {"removed": 0, "merged": 0}

        for section_name, section in self.playbook["sections"].items():
            bullets = section["bullets"]

            if not bullets:
                continue

            # Use semantic deduplication if available
            if self.semantic_engine:
                unique_bullets, duplicates = self.semantic_engine.deduplicate_bullets(
                    bullets, threshold=threshold
                )

                # Merge counters from duplicates into originals
                for idx1, idx2, similarity in duplicates:
                    bullets[idx1]["helpful_count"] += bullets[idx2]["helpful_count"]
                    bullets[idx1]["harmful_count"] += bullets[idx2]["harmful_count"]
                    summary["merged"] += 1

                # Replace section bullets with unique ones
                section["bullets"] = unique_bullets
                summary["removed"] += len(bullets) - len(unique_bullets)
                self.playbook["metadata"]["total_bullets"] -= (len(bullets) - len(unique_bullets))

            else:
                # Fallback: exact content hash matching
                seen_content = {}
                to_remove = []

                for i, bullet in enumerate(bullets):
                    content_hash = hashlib.md5(
                        bullet["content"].encode()
                    ).hexdigest()

                    if content_hash in seen_content:
                        # Duplicate found - merge counters
                        orig_idx = seen_content[content_hash]
                        bullets[orig_idx]["helpful_count"] += bullet["helpful_count"]
                        bullets[orig_idx]["harmful_count"] += bullet["harmful_count"]
                        to_remove.append(i)
                        summary["merged"] += 1
                    else:
                        seen_content[content_hash] = i

                # Remove duplicates (reverse order to preserve indices)
                for idx in reversed(to_remove):
                    bullets.pop(idx)
                    summary["removed"] += 1
                    self.playbook["metadata"]["total_bullets"] -= 1

        return summary

    def get_relevant_bullets(
        self,
        query: str,
        limit: Optional[int] = None,
        min_quality_score: int = 0,
        similarity_threshold: float = 0.3
    ) -> List[Dict]:
        """
        Retrieve relevant bullets for Actor context.

        Uses semantic search if available, otherwise falls back to keyword matching.

        Args:
            query: Task description or keywords
            limit: Maximum bullets to return (defaults to playbook metadata top_k)
            min_quality_score: Minimum (helpful - harmful) score
            similarity_threshold: Minimum semantic similarity (0-1, only for semantic search)

        Returns:
            List of bullets sorted by relevance and quality score
        """
        # Use playbook top_k as default if limit not specified
        if limit is None:
            limit = self.playbook["metadata"]["top_k"]

        # Collect non-deprecated bullets with quality filtering
        all_bullets = []
        for section in self.playbook["sections"].values():
            for bullet in section["bullets"]:
                if bullet.get("deprecated", False):
                    continue

                quality_score = bullet.get("helpful_count", 0) - bullet.get("harmful_count", 0)

                if quality_score < min_quality_score:
                    continue

                all_bullets.append({
                    **bullet,
                    "quality_score": quality_score
                })

        if not all_bullets:
            return []

        # Use semantic search if available
        if self.semantic_engine:
            # Find semantically similar bullets
            results = self.semantic_engine.find_similar(
                query=query,
                bullets=all_bullets,
                top_k=limit,
                threshold=similarity_threshold
            )

            # Add quality_score to results (already in bullet dict)
            return [bullet for bullet, similarity in results]

        else:
            # Fallback: keyword matching
            for bullet in all_bullets:
                bullet["relevance_score"] = self._calculate_relevance(query, bullet)

            # Sort by combined score: relevance + quality
            sorted_bullets = sorted(
                all_bullets,
                key=lambda b: (b["relevance_score"], b["quality_score"]),
                reverse=True
            )

            return sorted_bullets[:limit]

    def _calculate_relevance(self, query: str, bullet: Dict) -> float:
        """
        Calculate relevance score (placeholder).

        TODO: Replace with semantic similarity using embeddings.
        """
        query_lower = query.lower()
        content_lower = bullet["content"].lower()

        # Count keyword matches
        query_words = set(re.findall(r'\w+', query_lower))
        content_words = set(re.findall(r'\w+', content_lower))

        if not query_words:
            return 0.0

        matches = query_words & content_words
        return len(matches) / len(query_words)

    def get_bullets_for_sync(self, threshold: int = 5) -> List[Dict]:
        """Get high-quality bullets for syncing to cipher."""
        sync_bullets = []

        for section_name, section in self.playbook["sections"].items():
            for bullet in section["bullets"]:
                if bullet.get("deprecated", False):
                    continue

                quality_score = bullet.get("helpful_count", 0) - bullet.get("harmful_count", 0)

                if quality_score >= threshold:
                    sync_bullets.append({
                        "section": section_name,
                        **bullet
                    })

        return sync_bullets

    def _save_playbook(self, playbook: Optional[Dict] = None) -> None:
        """Save playbook to disk."""
        if playbook is None:
            playbook = self.playbook

        playbook["metadata"]["last_updated"] = datetime.utcnow().isoformat() + "Z"

        with open(self.playbook_path, 'w', encoding='utf-8') as f:
            json.dump(playbook, f, indent=2, ensure_ascii=False)

    def export_for_actor(self, bullets: List[Dict]) -> str:
        """
        Format bullets for Actor context.

        Returns markdown-formatted playbook excerpt.
        """
        if not bullets:
            return "No relevant patterns found in playbook."

        output = "# PLAYBOOK CONTEXT\n\n"
        output += "Relevant patterns from past successful implementations:\n\n"

        for bullet in bullets:
            output += f"## [{bullet['id']}] Quality: {bullet['quality_score']}\n\n"
            output += f"{bullet['content']}\n\n"

            if bullet.get('code_example'):
                output += f"{bullet['code_example']}\n\n"

            if bullet.get('related_bullets'):
                output += f"*Related: {', '.join(bullet['related_bullets'])}*\n\n"

            output += "---\n\n"

        return output


# CLI interface for testing
if __name__ == "__main__":
    import sys

    manager = PlaybookManager()

    if len(sys.argv) > 1:
        command = sys.argv[1]

        if command == "stats":
            print(json.dumps(manager.playbook["metadata"], indent=2))

        elif command == "search":
            if len(sys.argv) < 3:
                print("Usage: playbook_manager.py search <query>")
                sys.exit(1)

            query = " ".join(sys.argv[2:])
            bullets = manager.get_relevant_bullets(query, limit=5)
            print(manager.export_for_actor(bullets))

        elif command == "sync":
            bullets = manager.get_bullets_for_sync(threshold=5)
            print(f"Found {len(bullets)} bullets ready for cipher sync:")
            for b in bullets:
                print(f"  - [{b['id']}] {b['content'][:80]}...")

    else:
        print("Usage: playbook_manager.py {stats|search|sync}")
