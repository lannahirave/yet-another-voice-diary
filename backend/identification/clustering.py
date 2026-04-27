"""Greedy embedding clustering for the unknown-speaker queue.

Groups unresolved speaker segments whose voiceprints are mutually close, so
the UI can present one card per likely person instead of one per fragment.
The grouping is intentionally simple — single-pass greedy linkage against an
incrementally maintained centroid — because the queue is small (tens of items)
and the cost of an incorrect merge (one mis-tag affecting many segments) is
mitigated by the cascade-resolve step that re-checks identifications after
every user decision.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import numpy as np

from .matching import SimilarityMatcher


@dataclass
class _MutableCluster:
    members: list[int] = field(default_factory=list)
    centroid: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float32))

    def add(self, idx: int, embedding: np.ndarray) -> None:
        if not self.members:
            self.centroid = embedding.astype(np.float32, copy=True)
        else:
            n = len(self.members)
            self.centroid = ((self.centroid * n) + embedding) / (n + 1)
        self.members.append(idx)


def cluster_embeddings(
    embeddings: list[np.ndarray],
    *,
    threshold: float,
    matcher: SimilarityMatcher | None = None,
) -> list[list[int]]:
    """Return a list of clusters as lists of indices into ``embeddings``.

    Items whose embedding has zero length or zero norm get their own
    singleton cluster — they can't be compared meaningfully against others.
    """
    matcher = matcher or SimilarityMatcher()
    clusters: list[_MutableCluster] = []

    for idx, emb in enumerate(embeddings):
        if emb.size == 0 or float(np.linalg.norm(emb)) == 0.0:
            cluster = _MutableCluster()
            cluster.add(idx, emb)
            clusters.append(cluster)
            continue

        best_cluster: _MutableCluster | None = None
        best_score = 0.0
        for cluster in clusters:
            score = matcher.cosine_similarity(emb, cluster.centroid)
            if score >= threshold and score > best_score:
                best_score = score
                best_cluster = cluster

        if best_cluster is None:
            best_cluster = _MutableCluster()
            clusters.append(best_cluster)
        best_cluster.add(idx, emb)

    return [c.members for c in clusters]


def centroid(embeddings: Iterable[np.ndarray]) -> np.ndarray:
    """Mean of valid embeddings; returns an empty array if none qualify."""
    valid = [e for e in embeddings if e.size > 0 and float(np.linalg.norm(e)) > 0.0]
    if not valid:
        return np.zeros(0, dtype=np.float32)
    stacked = np.stack(valid).astype(np.float32, copy=False)
    return stacked.mean(axis=0)
