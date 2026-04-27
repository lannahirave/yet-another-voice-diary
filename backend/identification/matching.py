"""Embedding similarity matching."""
from typing import Optional

import numpy as np


class SimilarityMatcher:
    """Matches speaker embeddings using cosine similarity."""

    @staticmethod
    def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        """Compute cosine similarity between two vectors."""
        if len(a) == 0 or len(b) == 0:
            return 0.0

        norm_a = float(np.linalg.norm(a))
        norm_b = float(np.linalg.norm(b))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0

        a_norm = a / norm_a
        b_norm = b / norm_b
        return float(np.dot(a_norm, b_norm))

    def find_best_match(
        self,
        query_embedding: np.ndarray,
        candidates: list[tuple[str, np.ndarray]],
        threshold: float = 0.82,
    ) -> Optional[tuple[str, float]]:
        """
        Find best matching candidate above threshold.
        Returns (candidate_id, similarity_score) or None.
        """
        best_id: Optional[str] = None
        best_score = 0.0

        for candidate_id, candidate_emb in candidates:
            score = self.cosine_similarity(query_embedding, candidate_emb)
            if score > best_score:
                best_score = score
                best_id = candidate_id

        if best_score >= threshold and best_id is not None:
            return best_id, best_score
        return None

    def find_candidates(
        self,
        query_embedding: np.ndarray,
        candidates: list[tuple[str, np.ndarray]],
        threshold: float = 0.65,
        top_k: int = 3,
    ) -> list[tuple[str, float]]:
        """
        Find all matching candidates above threshold, sorted by score.
        Returns list of (candidate_id, score) pairs, limited to top_k.
        """
        scores = []
        for candidate_id, candidate_emb in candidates:
            score = self.cosine_similarity(query_embedding, candidate_emb)
            if score >= threshold:
                scores.append((candidate_id, score))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]
