"""Tests for embedding matching."""
import numpy as np

from backend.identification.matching import SimilarityMatcher


def test_cosine_similarity():
    """Test cosine similarity computation."""
    matcher = SimilarityMatcher()

    # Same vectors should have similarity 1.0
    a = np.array([1, 0, 0], dtype=np.float32)
    b = np.array([1, 0, 0], dtype=np.float32)
    assert abs(matcher.cosine_similarity(a, b) - 1.0) < 0.001

    # Orthogonal vectors should have similarity ~0.0
    a = np.array([1, 0, 0], dtype=np.float32)
    b = np.array([0, 1, 0], dtype=np.float32)
    assert abs(matcher.cosine_similarity(a, b)) < 0.001


def test_find_best_match():
    """Test finding best match."""
    matcher = SimilarityMatcher()
    query = np.array([1, 0, 0], dtype=np.float32)
    candidates = [
        ("contact_1", np.array([1, 0, 0], dtype=np.float32)),
        ("contact_2", np.array([0.5, 0.5, 0], dtype=np.float32)),
    ]

    match = matcher.find_best_match(query, candidates, threshold=0.8)
    assert match is not None
    assert match[0] == "contact_1"
    assert match[1] > 0.9


def test_find_best_match_below_threshold():
    """Test that matches below threshold return None."""
    matcher = SimilarityMatcher()
    query = np.array([1, 0, 0], dtype=np.float32)
    candidates = [
        ("contact_1", np.array([0, 1, 0], dtype=np.float32)),
    ]

    match = matcher.find_best_match(query, candidates, threshold=0.8)
    assert match is None


def test_find_candidates():
    """Test finding multiple candidates."""
    matcher = SimilarityMatcher()
    query = np.array([1, 0, 0], dtype=np.float32)
    candidates = [
        ("contact_1", np.array([1, 0, 0], dtype=np.float32)),
        ("contact_2", np.array([0.8, 0.2, 0], dtype=np.float32)),
        ("contact_3", np.array([0.5, 0.5, 0], dtype=np.float32)),
        ("contact_4", np.array([0, 1, 0], dtype=np.float32)),
    ]

    matches = matcher.find_candidates(query, candidates, threshold=0.65, top_k=2)
    assert len(matches) == 2
    assert matches[0][0] == "contact_1"
    assert matches[0][1] > matches[1][1]
