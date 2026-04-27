"""Speaker identification resolver."""
from __future__ import annotations

import sqlite3
from typing import Any, Optional

import numpy as np

from ..models import SpeakerSegment
from ..storage.database import Database
from .matching import SimilarityMatcher


class SQLiteResolverStore:
    """Adapter exposing the small DB surface used by ``SpeakerResolver``."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def fetch_all(self, sql: str, params: tuple = ()):
        return self.conn.execute(sql, params).fetchall()

    def fetch_one(self, sql: str, params: tuple = ()):
        return self.conn.execute(sql, params).fetchone()


class SpeakerResolver:
    """Resolves speaker identification using embeddings."""

    def __init__(
        self,
        db: Database | SQLiteResolverStore,
        matcher: Optional[SimilarityMatcher] = None,
        embedding_model_id: str | None = None,
    ):
        self.db = db
        self.matcher = matcher or SimilarityMatcher()
        self.embedding_model_id = embedding_model_id

    def resolve(
        self,
        speaker_segment: SpeakerSegment,
        threshold: float = 0.82,
    ) -> Optional[str]:
        """
        Resolve speaker segment to known contact.
        Returns contact_id or None if unknown.

        Voiceprint candidates are scoped to ``speaker_segment.source`` —
        mic-track segments only match profiles enrolled from the mic, system-
        track segments only against system profiles. Without this scoping, a
        YouTube anchor heard through the speakers can spuriously match an
        in-room colleague.
        """
        source = getattr(speaker_segment, "source", None) or "mic"
        candidates = self._load_voice_profiles(
            source=source,
            model_id=self.embedding_model_id,
            embedding_dim=int(speaker_segment.embedding.size) or None,
        )
        if not candidates:
            return None

        match = self.matcher.find_best_match(
            speaker_segment.embedding,
            candidates,
            threshold=threshold
        )

        if match:
            contact_id, score = match
            speaker_segment.contact_id = contact_id
            speaker_segment.status = "identified"
            speaker_segment.sim_score = score
            return contact_id

        speaker_segment.status = "unknown"
        return None

    def get_candidates(
        self,
        speaker_segment: SpeakerSegment,
        threshold: float = 0.65,
        top_k: int = 3,
    ) -> list[tuple[str, float, str]]:
        """
        Get candidate contacts for a speaker segment.
        Returns list of (contact_id, score, contact_name) tuples, with one
        entry per *contact* — when a contact has several voice profiles, the
        highest-scoring profile represents them so the UI does not show the
        same person twice.
        """
        source = getattr(speaker_segment, "source", None) or "mic"
        embedding_dim = int(speaker_segment.embedding.size) or None
        candidates = self._load_voice_profiles(
            source=source,
            model_id=self.embedding_model_id,
            embedding_dim=embedding_dim,
        )
        # Candidate suggestions are a manual-assistance surface, not an
        # automatic decision boundary. If the current embedding model has no
        # enrolled profiles yet, fall back to same-source profiles from any
        # model with the same dimensionality so the queue can still offer
        # quick-assign hints. `resolve()` stays strict and does not use this.
        if not candidates and self.embedding_model_id:
            candidates = self._load_voice_profiles(
                source=source,
                embedding_dim=embedding_dim,
            )
        if not candidates:
            return []

        # Score against every profile, then collapse by contact keeping the
        # best score per contact, then take top_k contacts.
        matches = self.matcher.find_candidates(
            speaker_segment.embedding,
            candidates,
            threshold=threshold,
            top_k=len(candidates),
        )

        best_per_contact: dict[str, float] = {}
        for contact_id, score in matches:
            if score > best_per_contact.get(contact_id, -1.0):
                best_per_contact[contact_id] = score

        ranked = sorted(best_per_contact.items(), key=lambda x: x[1], reverse=True)[:top_k]
        return [
            (contact_id, score, self._get_contact_name(contact_id))
            for contact_id, score in ranked
        ]

    def _load_voice_profiles(
        self,
        source: str = "mic",
        model_id: str | None = None,
        embedding_dim: int | None = None,
    ) -> list[tuple[str, np.ndarray]]:
        """Load voice profiles whose ``source`` matches the segment's track.

        Cross-track matching is intentionally disallowed: mic-track lookups
        compare only against mic-enrolled profiles, system-track lookups only
        against system-enrolled ones. Profiles are also filtered to the current
        embedding model and dimensionality so galleries from incompatible
        embedding spaces cannot participate in cosine matching.
        """
        rows = self.db.fetch_all(
            """
            SELECT contact_id, embedding, model_id, embedding_dim
            FROM voice_profiles
            WHERE embedding IS NOT NULL
              AND COALESCE(source, 'mic') = ?
            """,
            (source,),
        )
        profiles: list[tuple[str, np.ndarray]] = []
        for row in rows:
            contact_id = self._row_value(row, "contact_id", 0)
            embedding_blob = self._row_value(row, "embedding", 1)
            if embedding_blob is None:
                continue
            row_model_id = self._row_value(row, "model_id", 2)
            row_embedding_dim = self._row_value(row, "embedding_dim", 3)
            decoded = self._decode_embedding(embedding_blob)
            actual_dim = int(decoded.size)

            if model_id and str(row_model_id or "").strip() != model_id:
                continue
            stored_dim = int(row_embedding_dim or 0)
            if stored_dim and stored_dim != actual_dim:
                continue
            if embedding_dim and actual_dim != embedding_dim:
                continue

            profiles.append(
                (
                    contact_id,
                    decoded,
                )
            )

        return profiles

    def load_segment(self, speaker_segment_id: str) -> Optional[SpeakerSegment]:
        """Load a persisted speaker segment and its embedding."""
        row = self.db.fetch_one(
            """
            SELECT id, session_id, contact_id, status, embedding,
                   diarization_model_id, sim_score
            FROM speaker_segments
            WHERE id = ?
            """,
            (speaker_segment_id,),
        )
        if row is None:
            return None

        embedding_blob = self._row_value(row, "embedding", 4)
        embedding = (
            self._decode_embedding(embedding_blob)
            if embedding_blob is not None
            else np.array([], dtype=np.float32)
        )
        return SpeakerSegment(
            id=self._row_value(row, "id", 0),
            session_id=self._row_value(row, "session_id", 1),
            contact_id=self._row_value(row, "contact_id", 2),
            status=self._row_value(row, "status", 3),
            embedding=embedding,
            diarization_model_id=str(
                self._row_value(row, "diarization_model_id", 5) or "pyannote"
            ),
            sim_score=float(self._row_value(row, "sim_score", 6) or 0.0),
        )

    def _get_contact_name(self, contact_id: str) -> str:
        """Get contact name from database."""
        row = self.db.fetch_one(
            "SELECT name FROM contacts WHERE id = ?",
            (contact_id,),
        )
        if row is None:
            return "Unknown"

        name = self._row_value(row, "name", 0)
        return str(name) if name else "Unknown"

    @staticmethod
    def _row_value(row: Any, key: str, index: int) -> Any:
        """Support sqlite rows fetched either as tuples or mapping-like objects."""
        try:
            return row[key]
        except (KeyError, IndexError, TypeError):
            return row[index]

    @staticmethod
    def _decode_embedding(embedding_blob: Any) -> np.ndarray:
        embedding_bytes = (
            embedding_blob.tobytes()
            if isinstance(embedding_blob, memoryview)
            else bytes(embedding_blob)
        )
        return np.frombuffer(embedding_bytes, dtype=np.float32).copy()
