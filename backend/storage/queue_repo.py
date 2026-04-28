"""Unknown-speaker queue repository."""
from __future__ import annotations

import sqlite3
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import numpy as np


def _from_epoch(ts: Optional[int]) -> Optional[datetime]:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc)


class QueueRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def list_unresolved(self) -> list[dict]:
        cur = self.conn.execute(
            """
            SELECT q.id, q.speaker_segment_id, q.created_at, q.resolved_contact_id,
                   q.resolved_at, ss.session_id
            FROM unknown_queue q
            JOIN speaker_segments ss ON ss.id = q.speaker_segment_id
            WHERE q.resolved_contact_id IS NULL
            ORDER BY q.created_at DESC
            """
        )
        return [self._row_to_dict(r) for r in cur.fetchall()]

    def list_unresolved_with_extras(self, limit: int | None = None) -> list[dict]:
        """Return unresolved rows joined with embedding bytes + best utterance.

        Adds, per row:
          - ``embedding`` (raw bytes or ``None``)
          - ``quote`` (longest utterance transcript for the segment, ``""`` if none)
          - ``duration_ms`` (sum of ``ended_ms - started_ms`` across utterances)
          - ``fragment_count`` (number of utterances bound to the segment)

        Designed for the cluster builder — a single query per page load instead
        of N+1 lookups. When *limit* is given, only the first N rows are returned.
        """
        sql = """
            SELECT q.id, q.speaker_segment_id, q.created_at, ss.session_id,
                   COALESCE(s.title, '')             AS session_title,
                   ss.embedding, ss.source AS segment_source,
                   COALESCE(agg.duration_ms, 0)        AS duration_ms,
                   COALESCE(agg.fragment_count, 0)     AS fragment_count,
                   COALESCE(longest.transcript, '')    AS quote
            FROM unknown_queue q
            JOIN speaker_segments ss ON ss.id = q.speaker_segment_id
            LEFT JOIN sessions s ON s.id = ss.session_id
            LEFT JOIN (
                SELECT speaker_segment_id,
                       SUM(MAX(ended_ms - started_ms, 0)) AS duration_ms,
                       COUNT(*)                           AS fragment_count
                FROM utterances
                WHERE speaker_segment_id IS NOT NULL
                GROUP BY speaker_segment_id
            ) agg ON agg.speaker_segment_id = ss.id
            LEFT JOIN (
                SELECT u1.speaker_segment_id, u1.transcript
                FROM utterances u1
                WHERE u1.speaker_segment_id IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM utterances u2
                      WHERE u2.speaker_segment_id = u1.speaker_segment_id
                        AND LENGTH(u2.transcript) > LENGTH(u1.transcript)
                  )
                GROUP BY u1.speaker_segment_id
            ) longest ON longest.speaker_segment_id = ss.id
            WHERE q.resolved_contact_id IS NULL
            ORDER BY q.created_at DESC
        """
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        cur = self.conn.execute(sql)
        out: list[dict] = []
        for row in cur.fetchall():
            out.append(
                {
                    "id": row["id"],
                    "speaker_segment_id": row["speaker_segment_id"],
                    "session_id": row["session_id"],
                    "session_title": row["session_title"] or "",
                    "created_at": _from_epoch(row["created_at"]),
                    "embedding": _row_value(row, "embedding"),
                    "duration_ms": int(row["duration_ms"] or 0),
                    "fragment_count": int(row["fragment_count"] or 0),
                    "quote": row["quote"] or "",
                    "source": (_row_value(row, "segment_source") or "mic"),
                }
            )
        return out

    def count_unresolved(self) -> int:
        """Return total unresolved items (lightweight, no BLOBs)."""
        cur = self.conn.execute(
            "SELECT COUNT(*) FROM unknown_queue WHERE resolved_contact_id IS NULL"
        )
        return int(cur.fetchone()[0])

    def get(self, queue_id: str) -> Optional[dict]:
        cur = self.conn.execute(
            """
            SELECT q.id, q.speaker_segment_id, q.created_at, q.resolved_contact_id,
                   q.resolved_at, ss.session_id
            FROM unknown_queue q
            JOIN speaker_segments ss ON ss.id = q.speaker_segment_id
            WHERE q.id = ?
            """,
            (queue_id,),
        )
        row = cur.fetchone()
        return self._row_to_dict(row) if row else None

    def enqueue(self, speaker_segment_id: str) -> dict:
        queue_id = str(uuid.uuid4())
        self.conn.execute(
            """
            INSERT INTO unknown_queue (id, speaker_segment_id, created_at)
            VALUES (?, ?, ?)
            """,
            (queue_id, speaker_segment_id, int(time.time())),
        )
        self.conn.commit()
        fetched = self.get(queue_id)
        assert fetched is not None
        return fetched

    def resolve(
        self,
        queue_id: str,
        contact_id: str,
        *,
        record_voice_profile: bool = True,
        embedding_model_id: str | None = None,
        auto_commit: bool = True,
    ) -> Optional[dict]:
        """Resolve a single queue row.

        ``record_voice_profile`` is ``True`` when the resolution comes from a
        deliberate user action (we want to enrich the profile gallery), and
        ``False`` for cascaded automatic re-identifications (avoids piling up
        many near-duplicate profiles for a single contact).

        ``auto_commit`` is ``False`` inside ``resolve_many`` so the entire
        cluster is committed atomically.
        """
        self.conn.execute(
            """
            UPDATE unknown_queue
            SET resolved_contact_id = ?, resolved_at = ?
            WHERE id = ?
            """,
            (contact_id, int(time.time()), queue_id),
        )
        row = self.conn.execute(
            "SELECT speaker_segment_id FROM unknown_queue WHERE id = ?", (queue_id,)
        ).fetchone()
        if row:
            segment = self.conn.execute(
                "SELECT embedding, session_id, source FROM speaker_segments WHERE id = ?",
                (row["speaker_segment_id"],),
            ).fetchone()
            self.conn.execute(
                """
                UPDATE speaker_segments
                SET contact_id = ?, status = 'identified'
                WHERE id = ?
                """,
                (contact_id, row["speaker_segment_id"]),
            )
            if (
                record_voice_profile
                and segment
                and segment["embedding"] is not None
            ):
                segment_source = (
                    segment["source"] if "source" in segment.keys() else "mic"
                ) or "mic"
                self.conn.execute(
                    """
                    INSERT INTO voice_profiles (
                        id, contact_id, embedding, model_id, embedding_dim,
                        quality_score, recorded_at, source_session_id, source
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        contact_id,
                        segment["embedding"],
                        embedding_model_id or "ecapa",
                        _embedding_dim(segment["embedding"]),
                        1.0,
                        int(time.time()),
                        segment["session_id"],
                        segment_source,
                    ),
                )
        if auto_commit:
            self.conn.commit()
        return self.get(queue_id)

    def resolve_many(
        self,
        queue_ids: list[str],
        contact_id: str,
        *,
        embedding_model_id: str | None = None,
    ) -> int:
        """Resolve multiple rows as one user action.

        Records a voice profile for the *first* row only — the rest are treated
        as additional segments of the same speaker and don't need a new
        profile entry. Commits once after all items are processed so the
        entire cluster is resolved atomically.
        """
        updated = 0
        for idx, qid in enumerate(queue_ids):
            result = self.resolve(
                qid,
                contact_id,
                record_voice_profile=(idx == 0),
                embedding_model_id=embedding_model_id,
                auto_commit=False,
            )
            if result is not None:
                updated += 1
        if updated:
            self.conn.commit()
        return updated

    def skip(self, queue_id: str) -> Optional[dict]:
        """Push to tail of queue by rewriting created_at."""
        self.conn.execute(
            "UPDATE unknown_queue SET created_at = ? WHERE id = ?",
            (int(time.time()), queue_id),
        )
        self.conn.commit()
        return self.get(queue_id)

    def skip_many(self, queue_ids: list[str]) -> int:
        if not queue_ids:
            return 0
        ts = int(time.time())
        placeholders = ",".join("?" * len(queue_ids))
        cur = self.conn.execute(
            f"UPDATE unknown_queue SET created_at = ? WHERE id IN ({placeholders})",
            (ts, *queue_ids),
        )
        self.conn.commit()
        return cur.rowcount or 0

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "speaker_segment_id": row["speaker_segment_id"],
            "session_id": row["session_id"],
            "created_at": _from_epoch(row["created_at"]),
            "resolved_contact_id": row["resolved_contact_id"],
            "resolved_at": _from_epoch(row["resolved_at"]),
        }


def _row_value(row: Any, key: str) -> Any:
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return None


def _embedding_dim(blob: Any) -> int:
    if blob is None:
        return 0
    raw = blob.tobytes() if isinstance(blob, memoryview) else bytes(blob)
    if not raw:
        return 0
    return int(np.frombuffer(raw, dtype=np.float32).size)
