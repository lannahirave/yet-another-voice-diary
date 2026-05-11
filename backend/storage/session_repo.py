"""Session + utterance repository."""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional

import numpy as np

from ..models import RecordingSession, SpeakerSegment, Utterance


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


class SessionRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # ---- sessions ----

    def list_sessions(self) -> list[dict]:
        cur = self.conn.execute(
            """
            SELECT s.id, s.title, s.started_at, s.ended_at, s.notes, s.language_hint,
                   (SELECT COUNT(*) FROM utterances u WHERE u.session_id = s.id) AS utterance_count,
                   (SELECT GROUP_CONCAT(DISTINCT ss.contact_id)
                      FROM speaker_segments ss WHERE ss.session_id = s.id) AS speaker_ids
            FROM sessions s
            ORDER BY s.started_at DESC
            """
        )
        return [self._row_to_dict(r) for r in cur.fetchall()]

    def get_session(self, session_id: str) -> Optional[dict]:
        cur = self.conn.execute(
            """
            SELECT s.id, s.title, s.started_at, s.ended_at, s.notes, s.language_hint,
                   (SELECT COUNT(*) FROM utterances u WHERE u.session_id = s.id) AS utterance_count,
                   (SELECT GROUP_CONCAT(DISTINCT ss.contact_id)
                      FROM speaker_segments ss WHERE ss.session_id = s.id) AS speaker_ids
            FROM sessions s
            WHERE s.id = ?
            """,
            (session_id,),
        )
        row = cur.fetchone()
        return self._row_to_dict(row) if row else None

    def create_session(self, session: RecordingSession) -> dict:
        if not session.id:
            session.id = str(uuid.uuid4())
        self.conn.execute(
            """
            INSERT INTO sessions (id, title, started_at, ended_at, notes, language_hint)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                session.id,
                session.title,
                _to_epoch(session.started_at),
                _to_epoch(session.ended_at),
                session.notes,
                session.language_hint,
            ),
        )
        self.conn.commit()
        fetched = self.get_session(session.id)
        assert fetched is not None
        return fetched

    def update_session(
        self,
        session_id: str,
        *,
        title: Optional[str] = None,
        ended_at: Optional[datetime] = None,
        notes: Optional[str] = None,
    ) -> Optional[dict]:
        fields: list[str] = []
        params: list = []
        if title is not None:
            fields.append("title = ?")
            params.append(title)
        if ended_at is not None:
            fields.append("ended_at = ?")
            params.append(_to_epoch(ended_at))
        if notes is not None:
            fields.append("notes = ?")
            params.append(notes)
        if not fields:
            return self.get_session(session_id)
        params.append(session_id)
        self.conn.execute(
            f"UPDATE sessions SET {', '.join(fields)} WHERE id = ?", tuple(params)
        )
        self.conn.commit()
        return self.get_session(session_id)

    def delete_session(self, session_id: str) -> bool:
        self.conn.execute("DELETE FROM utterances WHERE session_id = ?", (session_id,))
        self.conn.execute(
            "DELETE FROM speaker_segments WHERE session_id = ?", (session_id,)
        )
        cur = self.conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        self.conn.commit()
        return cur.rowcount > 0

    # ---- utterances ----

    def list_utterances(self, session_id: str) -> list[dict]:
        cur = self.conn.execute(
            """
            SELECT u.id, u.session_id, u.started_ms, u.ended_ms, u.transcript,
                   u.language, u.confidence, u.speaker_segment_id, u.source,
                   ss.contact_id AS speaker_contact_id
            FROM utterances u
            LEFT JOIN speaker_segments ss ON ss.id = u.speaker_segment_id
            WHERE u.session_id = ?
            ORDER BY u.started_ms ASC
            """,
            (session_id,),
        )
        return [self._utterance_row_to_dict(r) for r in cur.fetchall()]

    def list_utterances_for_contact(self, contact_id: str) -> list[dict]:
        """Every utterance attributed to this contact, newest session first.

        Joins utterances → speaker_segments to filter by ``contact_id``. The
        order — newest session, then most recent utterance first — keeps the
        contact page readable when there are many sessions.
        """
        cur = self.conn.execute(
            """
            SELECT u.id, u.session_id, u.started_ms, u.ended_ms, u.transcript,
                   u.language, u.confidence, u.speaker_segment_id, u.source,
                   ss.contact_id AS speaker_contact_id,
                   s.started_at AS session_started_at
            FROM utterances u
            JOIN speaker_segments ss ON ss.id = u.speaker_segment_id
            JOIN sessions s ON s.id = u.session_id
            WHERE ss.contact_id = ?
            ORDER BY s.started_at DESC, u.started_ms DESC
            """,
            (contact_id,),
        )
        return [self._utterance_row_to_dict(r) for r in cur.fetchall()]

    def create_utterance(self, utt: Utterance) -> dict:
        if not utt.id:
            utt.id = str(uuid.uuid4())
        self.conn.execute(
            """
            INSERT INTO utterances (id, session_id, started_ms, ended_ms, transcript,
                                    language, confidence, speaker_segment_id, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                utt.id,
                utt.session_id,
                utt.started_ms,
                utt.ended_ms,
                utt.transcript,
                utt.language,
                utt.confidence,
                utt.speaker_segment_id,
                utt.source,
            ),
        )
        self.conn.commit()
        row = self.conn.execute(
            """
            SELECT u.id, u.session_id, u.started_ms, u.ended_ms, u.transcript,
                   u.language, u.confidence, u.speaker_segment_id, u.source,
                   ss.contact_id AS speaker_contact_id
            FROM utterances u
            LEFT JOIN speaker_segments ss ON ss.id = u.speaker_segment_id
            WHERE u.id = ?
            """,
            (utt.id,),
        ).fetchone()
        assert row is not None
        return self._utterance_row_to_dict(row)

    def create_speaker_segment(self, segment: SpeakerSegment) -> dict:
        if not segment.id:
            segment.id = str(uuid.uuid4())
        embedding_blob = None
        if segment.embedding.size:
            embedding_blob = np.asarray(segment.embedding, dtype=np.float32).tobytes()
        self.conn.execute(
            """
            INSERT INTO speaker_segments (
                id, session_id, contact_id, status, embedding, diarization_model_id,
                sim_score, reviewed_at, source
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                segment.id,
                segment.session_id,
                segment.contact_id,
                segment.status,
                embedding_blob,
                segment.diarization_model_id,
                segment.sim_score,
                _to_epoch(segment.reviewed_at),
                segment.source,
            ),
        )
        self.conn.commit()
        row = self.conn.execute(
            """
            SELECT id, session_id, contact_id, status, diarization_model_id,
                   sim_score, reviewed_at
            FROM speaker_segments
            WHERE id = ?
            """,
            (segment.id,),
        ).fetchone()
        assert row is not None
        return dict(row)

    # ---- inline identify helpers ----

    def get_utterance(self, utterance_id: str) -> Optional[dict]:
        cur = self.conn.execute(
            "SELECT id, session_id, speaker_segment_id, source "
            "FROM utterances WHERE id = ?",
            (utterance_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def delete_utterance(self, utterance_id: str) -> bool:
        utt = self.get_utterance(utterance_id)
        if utt is None:
            return False
        segment_id = utt.get("speaker_segment_id")
        # Delete the utterance (FTS5 trigger auto-cleans utterances_fts)
        cur = self.conn.execute(
            "DELETE FROM utterances WHERE id = ?", (utterance_id,)
        )
        if cur.rowcount == 0:
            return False
        # Cascade: if no other utterance references this speaker_segment, clean it up
        if segment_id:
            ref = self.conn.execute(
                "SELECT COUNT(*) FROM utterances WHERE speaker_segment_id = ?",
                (segment_id,),
            ).fetchone()
            if ref is not None and ref[0] == 0:
                self.conn.execute(
                    "DELETE FROM unknown_queue WHERE speaker_segment_id = ?",
                    (segment_id,),
                )
                self.conn.execute(
                    "DELETE FROM speaker_segments WHERE id = ?",
                    (segment_id,),
                )
        self.conn.commit()
        return True

    def list_unknown_segments(self, session_id: str) -> list[dict]:
        cur = self.conn.execute(
            "SELECT id, session_id, contact_id, status, embedding, "
            "diarization_model_id, sim_score, source "
            "FROM speaker_segments "
            "WHERE session_id = ? AND status = 'unknown' "
            "AND embedding IS NOT NULL",
            (session_id,),
        )
        return [dict(r) for r in cur.fetchall()]

    # ---- helpers ----

    def create_error(
        self,
        session_id: str,
        component: str,
        error_code: str,
        message: str,
        occurred_at_ms: int,
        utterance_id: str | None = None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO pipeline_errors
                (id, session_id, utterance_id, component, error_code, message, occurred_at_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                session_id,
                utterance_id,
                component,
                error_code,
                message,
                occurred_at_ms,
            ),
        )
        self.conn.commit()

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        speaker_ids_raw = row["speaker_ids"]
        speakers = (
            [s for s in speaker_ids_raw.split(",") if s]
            if speaker_ids_raw
            else []
        )
        return {
            "id": row["id"],
            "title": row["title"],
            "started_at": _from_epoch(row["started_at"]),
            "ended_at": _from_epoch(row["ended_at"]),
            "notes": row["notes"] or "",
            "language_hint": row["language_hint"],
            "utterance_count": row["utterance_count"],
            "speakers": speakers,
        }

    @staticmethod
    def _utterance_row_to_dict(row: sqlite3.Row) -> dict:
        keys = row.keys() if hasattr(row, "keys") else ()
        source_val = row["source"] if "source" in keys else "mic"
        session_started_at = (
            _from_epoch(row["session_started_at"])
            if "session_started_at" in keys and row["session_started_at"] is not None
            else None
        )
        return {
            "id": row["id"],
            "session_id": row["session_id"],
            "started_ms": row["started_ms"],
            "ended_ms": row["ended_ms"],
            "transcript": row["transcript"],
            "language": row["language"],
            "confidence": row["confidence"] if row["confidence"] is not None else 0.0,
            "speaker_segment_id": row["speaker_segment_id"],
            "speaker_contact_id": row["speaker_contact_id"],
            "source": source_val or "mic",
            "session_started_at": session_started_at,
        }
