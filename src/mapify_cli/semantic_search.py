"""
Semantic Search for ACE Playbook using sentence-transformers.

Provides embedding generation and similarity search for finding relevant
knowledge bullets based on semantic meaning, not just keyword matching.

Installation:
    pip install -r requirements-semantic.txt

Usage:
    from mapify_cli.semantic_search import SemanticSearchEngine

    engine = SemanticSearchEngine()
    results = engine.find_similar(query="JWT authentication", bullets=playbook_bullets, top_k=5)
"""

# Set environment variables before importing transformers/sentence-transformers
import os

os.environ["TRANSFORMERS_NO_TF"] = "1"
os.environ["TF_USE_LEGACY_KERAS"] = (
    "1"  # Force TensorFlow to use Keras 2 instead of Keras 3
)
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
# Clear HuggingFace tokens to avoid 401 errors
if "HF_TOKEN" in os.environ:
    del os.environ["HF_TOKEN"]
if "HUGGING_FACE_HUB_TOKEN" in os.environ:
    del os.environ["HUGGING_FACE_HUB_TOKEN"]

import hashlib
import pickle
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Optional
import numpy as np

try:
    from sentence_transformers import SentenceTransformer
    from sklearn.metrics.pairwise import cosine_similarity

    SEMANTIC_SEARCH_AVAILABLE = True
except ImportError:
    SEMANTIC_SEARCH_AVAILABLE = False
    print(
        "Warning: sentence-transformers not installed. Run: pip install -r requirements-semantic.txt",
        file=sys.stderr,
    )


class SemanticSearchEngine:
    """
    Semantic search engine for ACE playbook bullets.

    Uses sentence-transformers 'all-MiniLM-L6-v2' model:
    - Size: ~80MB (much smaller than alternatives)
    - Speed: ~3000 sentences/second on CPU
    - Quality: Good balance for code/documentation
    - Dimensions: 384
    """

    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
        cache_dir: str = ".claude/embeddings_cache",
    ):
        """
        Initialize semantic search engine.

        Args:
            model_name: SentenceTransformer model name
            cache_dir: Directory for caching embeddings
        """
        if not SEMANTIC_SEARCH_AVAILABLE:
            raise ImportError(
                "sentence-transformers not installed. "
                "Run: pip install -r requirements-semantic.txt"
            )

        self.model_name = model_name
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Load model (downloads ~80MB on first use)
        print(f"Loading sentence-transformers model: {model_name}...", file=sys.stderr)
        self.model = SentenceTransformer(model_name)
        print("✓ Model loaded successfully", file=sys.stderr)

        # Cache for embeddings
        self._embedding_cache: Dict[str, np.ndarray] = {}
        self._load_cache()

    def _load_cache(self) -> None:
        """Load embedding cache from disk."""
        cache_file = self.cache_dir / "embeddings.pkl"
        if cache_file.exists():
            try:
                with open(cache_file, "rb") as f:
                    self._embedding_cache = pickle.load(f)
                print(
                    f"✓ Loaded {len(self._embedding_cache)} cached embeddings",
                    file=sys.stderr,
                )
            except Exception as e:
                print(f"Warning: Could not load cache: {e}", file=sys.stderr)
                self._embedding_cache = {}

    def _save_cache(self) -> None:
        """Save embedding cache to disk."""
        cache_file = self.cache_dir / "embeddings.pkl"
        try:
            with open(cache_file, "wb") as f:
                pickle.dump(self._embedding_cache, f)
        except Exception as e:
            print(f"Warning: Could not save cache: {e}", file=sys.stderr)

    def _get_cache_key(self, text: str) -> str:
        """Generate cache key for text."""
        return hashlib.md5(text.encode()).hexdigest()

    def encode(self, text: str, use_cache: bool = True) -> np.ndarray:
        """
        Encode text to embedding vector.

        Args:
            text: Text to encode
            use_cache: Whether to use/update cache

        Returns:
            Embedding vector (384 dimensions)
        """
        if use_cache:
            cache_key = self._get_cache_key(text)
            if cache_key in self._embedding_cache:
                return self._embedding_cache[cache_key]

        # Generate embedding
        embedding = self.model.encode(text, convert_to_numpy=True)

        if use_cache:
            self._embedding_cache[cache_key] = embedding
            # Save cache every 10 new embeddings
            if len(self._embedding_cache) % 10 == 0:
                self._save_cache()

        return embedding

    def encode_batch(self, texts: List[str], batch_size: int = 32) -> np.ndarray:
        """
        Encode multiple texts efficiently.

        Args:
            texts: List of texts to encode
            batch_size: Batch size for encoding

        Returns:
            Array of embeddings (N x 384)
        """
        embeddings = []

        for text in texts:
            cache_key = self._get_cache_key(text)
            if cache_key in self._embedding_cache:
                embeddings.append(self._embedding_cache[cache_key])
            else:
                # Will be encoded in batch below
                embeddings.append(None)

        # Find texts that need encoding
        texts_to_encode = [t for t, e in zip(texts, embeddings) if e is None]
        indices_to_encode = [i for i, e in enumerate(embeddings) if e is None]

        if texts_to_encode:
            # Batch encode
            new_embeddings = self.model.encode(
                texts_to_encode,
                batch_size=batch_size,
                convert_to_numpy=True,
                show_progress_bar=len(texts_to_encode) > 50,
            )

            # Update cache and results
            for idx, text, embedding in zip(
                indices_to_encode, texts_to_encode, new_embeddings
            ):
                embeddings[idx] = embedding
                cache_key = self._get_cache_key(text)
                self._embedding_cache[cache_key] = embedding

            self._save_cache()

        return np.array(embeddings)

    def find_similar(
        self, query: str, bullets: List[Dict], top_k: int = 10, threshold: float = 0.3
    ) -> List[Tuple[Dict, float]]:
        """
        Find semantically similar bullets to query.

        Args:
            query: Search query
            bullets: List of bullet dicts with 'content' field
            top_k: Number of results to return
            threshold: Minimum similarity score (0-1)

        Returns:
            List of (bullet, similarity_score) tuples, sorted by similarity

        Example:
            >>> bullets = [
            ...     {"id": "sec-0001", "content": "Always verify JWT signatures"},
            ...     {"id": "impl-0002", "content": "Use bcrypt for password hashing"}
            ... ]
            >>> results = engine.find_similar("token authentication", bullets, top_k=5)
            >>> for bullet, score in results:
            ...     print(f"{bullet['id']}: {score:.3f}")
        """
        if not bullets:
            return []

        # Encode query
        query_embedding = self.encode(query)

        # Encode all bullets (with caching)
        bullet_texts = [b.get("content", "") for b in bullets]
        bullet_embeddings = self.encode_batch(bullet_texts)

        # Calculate cosine similarity
        similarities = cosine_similarity([query_embedding], bullet_embeddings)[0]

        # Filter by threshold and sort
        results = []
        for bullet, similarity in zip(bullets, similarities):
            if similarity >= threshold:
                results.append((bullet, float(similarity)))

        results.sort(key=lambda x: x[1], reverse=True)

        return results[:top_k]

    def deduplicate_bullets(
        self, bullets: List[Dict], threshold: float = 0.9
    ) -> Tuple[List[Dict], List[Tuple[int, int, float]]]:
        """
        Find duplicate bullets based on semantic similarity.

        Args:
            bullets: List of bullet dicts
            threshold: Similarity threshold for duplicates (default: 0.9)

        Returns:
            Tuple of (unique_bullets, duplicates)
            duplicates: List of (idx1, idx2, similarity) for duplicate pairs

        Example:
            >>> unique, dupes = engine.deduplicate_bullets(bullets, threshold=0.9)
            >>> print(f"Found {len(dupes)} duplicate pairs")
            >>> for idx1, idx2, sim in dupes:
            ...     print(f"Bullets {idx1} and {idx2} are {sim:.1%} similar")
        """
        if len(bullets) <= 1:
            return bullets, []

        # Encode all bullets
        bullet_texts = [b.get("content", "") for b in bullets]
        embeddings = self.encode_batch(bullet_texts)

        # Calculate pairwise similarities
        similarities = cosine_similarity(embeddings)

        # Find duplicates (upper triangle of similarity matrix)
        duplicates = []
        seen_indices = set()

        for i in range(len(bullets)):
            if i in seen_indices:
                continue

            for j in range(i + 1, len(bullets)):
                if j in seen_indices:
                    continue

                similarity = similarities[i][j]
                if similarity >= threshold:
                    duplicates.append((i, j, float(similarity)))
                    seen_indices.add(j)  # Mark j as duplicate

        # Keep unique bullets
        unique_bullets = [b for i, b in enumerate(bullets) if i not in seen_indices]

        return unique_bullets, duplicates

    def cluster_bullets(
        self, bullets: List[Dict], n_clusters: Optional[int] = None
    ) -> Dict[int, List[Dict]]:
        """
        Cluster bullets by semantic similarity (optional feature).

        Useful for organizing playbook into semantic groups.

        Args:
            bullets: List of bullet dicts
            n_clusters: Number of clusters (auto if None)

        Returns:
            Dict mapping cluster_id -> list of bullets
        """
        from sklearn.cluster import KMeans

        if len(bullets) < 2:
            return {0: bullets}

        # Encode bullets
        bullet_texts = [b.get("content", "") for b in bullets]
        embeddings = self.encode_batch(bullet_texts)

        # Auto-determine clusters (rule of thumb: sqrt(n/2))
        if n_clusters is None:
            n_clusters = max(2, int(np.sqrt(len(bullets) / 2)))

        # K-means clustering
        kmeans = KMeans(n_clusters=n_clusters, random_state=42)
        labels = kmeans.fit_predict(embeddings)

        # Group bullets by cluster
        clusters = {}
        for bullet, label in zip(bullets, labels):
            if label not in clusters:
                clusters[label] = []
            clusters[label].append(bullet)

        return clusters


# Singleton instance for easy import
_engine_instance: Optional[SemanticSearchEngine] = None


def get_search_engine() -> SemanticSearchEngine:
    """Get singleton instance of SemanticSearchEngine."""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = SemanticSearchEngine()
    return _engine_instance


# CLI for testing
if __name__ == "__main__":
    import sys

    if not SEMANTIC_SEARCH_AVAILABLE:
        print("Error: sentence-transformers not installed")
        print("Install with: pip install -r requirements-semantic.txt")
        sys.exit(1)

    # Demo
    engine = SemanticSearchEngine()

    # Test bullets
    bullets = [
        {
            "id": "sec-0001",
            "content": "Always verify JWT token signatures to prevent forgery",
        },
        {
            "id": "sec-0002",
            "content": "Use bcrypt with cost factor 12 for password hashing",
        },
        {"id": "impl-0003", "content": "Implement authentication with bearer tokens"},
        {
            "id": "perf-0004",
            "content": "Use Redis caching to speed up database queries",
        },
        {"id": "perf-0005", "content": "Add indexes to frequently queried columns"},
    ]

    # Test queries
    queries = [
        "token authentication security",
        "password hashing",
        "improve query performance",
    ]

    print("\n" + "=" * 60)
    print("SEMANTIC SEARCH DEMO")
    print("=" * 60)

    for query in queries:
        print(f"\nQuery: '{query}'")
        print("-" * 60)

        results = engine.find_similar(query, bullets, top_k=3)

        for bullet, score in results:
            print(f"  [{bullet['id']}] {score:.3f} - {bullet['content'][:60]}...")

    # Test deduplication
    print("\n" + "=" * 60)
    print("DEDUPLICATION TEST")
    print("=" * 60)

    dupes_bullets = bullets + [
        {
            "id": "sec-0006",
            "content": "JWT signature verification prevents token tampering",
        }  # Similar to sec-0001
    ]

    unique, duplicates = engine.deduplicate_bullets(dupes_bullets, threshold=0.85)

    print(f"\nOriginal bullets: {len(dupes_bullets)}")
    print(f"Unique bullets: {len(unique)}")
    print(f"Duplicate pairs found: {len(duplicates)}")

    for idx1, idx2, sim in duplicates:
        print(
            f"\n  {dupes_bullets[idx1]['id']} ≈ {dupes_bullets[idx2]['id']} ({sim:.1%} similar)"
        )
        print(f"    1: {dupes_bullets[idx1]['content'][:50]}...")
        print(f"    2: {dupes_bullets[idx2]['content'][:50]}...")
