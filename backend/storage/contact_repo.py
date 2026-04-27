"""Contact + voice-profile repository."""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional

import numpy as np

from ..models import Person, VoiceProfile


def _to_epoch(dt: Optional[datetime]) -> Optional[int]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _from_epoch(ts: Optional[int]) -> Optional[datetime]:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc)


class ContactRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def list_contacts(self) -> list[dict]:
        cur = self.conn.execute(
            """
            SELECT c.id, c.name, c.notes, c.created_at,
                   (SELECT COUNT(*) FROM voice_profiles vp WHERE vp.contact_id = c.id) AS profile_count,
                   (SELECT COUNT(DISTINCT ss.session_id)
                      FROM speaker_segments ss WHERE ss.contact_id = c.id) AS session_count
            FROM contacts c
            ORDER BY c.name COLLATE NOCASE ASC
            """
        )
        return [self._row_to_dict(r, self._compute_confidence(r["id"])) for r in cur.fetchall()]

    def get_contact(self, contact_id: str) -> Optional[dict]:
        cur = self.conn.execute(
            """
            SELECT c.id, c.name, c.notes, c.created_at,
                   (SELECT COUNT(*) FROM voice_profiles vp WHERE vp.contact_id = c.id) AS profile_count,
                   (SELECT COUNT(DISTINCT ss.session_id)
                      FROM speaker_segments ss WHERE ss.contact_id = c.id) AS session_count
            FROM contacts c
            WHERE c.id = ?
            """,
            (contact_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return self._row_to_dict(row, self._compute_confidence(contact_id))

    def _compute_confidence(self, contact_id: str) -> float:
        """Mean pairwise cosine similarity across the contact's voice profiles.

        Quantifies how internally consistent the contact's voiceprint is —
        tightly-clustered profiles → high confidence in future matches;
        scattered profiles → noisy voiceprint, expect rejected true matches.

        Returns 0.0 when there are fewer than two valid profiles, which the
        UI treats as "not yet computed" (mirrors the disabled-update-button
        state when profileCount < 2).
        """
        cur = self.conn.execute(
            """
            SELECT embedding, model_id, embedding_dim
            FROM voice_profiles
            WHERE contact_id = ? AND embedding IS NOT NULL
            """,
            (contact_id,),
        )
        embeddings_by_space: dict[tuple[str, int], list[np.ndarray]] = {}
        for row in cur.fetchall():
            arr = np.frombuffer(row["embedding"], dtype=np.float32)
            norm = float(np.linalg.norm(arr))
            if arr.size == 0 or norm == 0.0 or not np.isfinite(norm):
                continue
            model_id = str(row["model_id"] or "ecapa")
            embedding_dim = int(row["embedding_dim"] or arr.size or 0)
            if embedding_dim != int(arr.size):
                continue
            embeddings_by_space.setdefault((model_id, embedding_dim), []).append(
                arr / norm
            )

        if not embeddings_by_space:
            return 0.0

        embeddings = max(
            embeddings_by_space.values(),
            key=len,
        )

        if len(embeddings) < 2:
            return 0.0

        stacked = np.stack(embeddings)
        # Pairwise cosine = M @ M.T (already unit-norm). Average the upper
        # triangle (n*(n-1)/2 entries).
        sim = stacked @ stacked.T
        n = sim.shape[0]
        upper_sum = float(np.triu(sim, k=1).sum())
        pairs = n * (n - 1) / 2
        mean = upper_sum / pairs
        return float(max(0.0, min(1.0, mean)))

    def create_contact(self, person: Person) -> dict:
        if not person.id:
            person.id = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO contacts (id, name, notes, created_at) VALUES (?, ?, ?, ?)",
            (
                person.id,
                person.name,
                person.notes,
                _to_epoch(person.created_at),
            ),
        )
        self.conn.commit()
        fetched = self.get_contact(person.id)
        assert fetched is not None
        return fetched

    def update_contact(
        self,
        contact_id: str,
        *,
        name: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Optional[dict]:
        fields: list[str] = []
        params: list = []
        if name is not None:
            fields.append("name = ?")
            params.append(name)
        if notes is not None:
            fields.append("notes = ?")
            params.append(notes)
        if not fields:
            return self.get_contact(contact_id)
        params.append(contact_id)
        self.conn.execute(
            f"UPDATE contacts SET {', '.join(fields)} WHERE id = ?", tuple(params)
        )
        self.conn.commit()
        return self.get_contact(contact_id)

    def delete_contact(self, contact_id: str) -> bool:
        self.conn.execute(
            "DELETE FROM voice_profiles WHERE contact_id = ?", (contact_id,)
        )
        self.conn.execute(
            "UPDATE speaker_segments SET contact_id = NULL, status = 'unknown' WHERE contact_id = ?",
            (contact_id,),
        )
        cur = self.conn.execute("DELETE FROM contacts WHERE id = ?", (contact_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def merge(self, target_id: str, source_id: str) -> Optional[dict]:
        """Move source's voice profiles + segments onto target, then drop source."""
        if target_id == source_id:
            return self.get_contact(target_id)
        self.conn.execute(
            "UPDATE voice_profiles SET contact_id = ? WHERE contact_id = ?",
            (target_id, source_id),
        )
        self.conn.execute(
            "UPDATE speaker_segments SET contact_id = ? WHERE contact_id = ?",
            (target_id, source_id),
        )
        self.conn.execute("DELETE FROM contacts WHERE id = ?", (source_id,))
        self.conn.commit()
        return self.get_contact(target_id)

    # ---- voice profiles ----

    def list_voice_profiles(self) -> list[tuple[str, np.ndarray]]:
        cur = self.conn.execute(
            "SELECT contact_id, embedding FROM voice_profiles"
        )
        return [
            (r["contact_id"], np.frombuffer(r["embedding"], dtype=np.float32))
            for r in cur.fetchall()
        ]

    def create_voice_profile(self, profile: VoiceProfile) -> dict:
        if not profile.id:
            profile.id = str(uuid.uuid4())
        embedding = profile.embedding.astype(np.float32)
        emb_bytes = embedding.tobytes()
        embedding_dim = profile.embedding_dim or int(embedding.size)
        self.conn.execute(
            """
            INSERT INTO voice_profiles (
                id, contact_id, embedding, model_id, embedding_dim, quality_score,
                recorded_at, source_session_id, source
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                profile.id,
                profile.contact_id,
                emb_bytes,
                profile.model_id or "ecapa",
                embedding_dim,
                profile.quality_score,
                _to_epoch(profile.recorded_at),
                profile.source_session_id,
                profile.source,
            ),
        )
        self.conn.commit()
        return {"id": profile.id, "contact_id": profile.contact_id}

    # ---- helpers ----

    @staticmethod
    def _row_to_dict(row: sqlite3.Row, confidence: float = 0.0) -> dict:
        return {
            "id": row["id"],
            "name": row["name"],
            "notes": row["notes"] or "",
            "created_at": _from_epoch(row["created_at"]),
            "profile_count": row["profile_count"],
            "session_count": row["session_count"],
            "confidence": confidence,
        }
