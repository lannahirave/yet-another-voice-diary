"""FTS5 search over utterances."""
from __future__ import annotations

import re
import sqlite3
from typing import Optional

# Unicode letters/digits plus hyphen, underscore, apostrophe. Covers Ukrainian cyrillic.
_TOKEN_RE = re.compile(r"[\wЀ-ӿ'-]+", re.UNICODE)


def _sanitize_query(raw: str) -> str:
    """Turn user text into a safe FTS5 MATCH expression.

    FTS5 MATCH is a mini-DSL; untrusted input can trip phrase/near operators.
    Extract word tokens and AND them together as quoted phrases.
    """
    tokens = _TOKEN_RE.findall(raw)
    return " ".join(f'"{t}"' for t in tokens)


class SearchRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def search(
        self,
        query: str,
        *,
        session_id: Optional[str] = None,
        speaker_id: Optional[str] = None,
        language: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        match = _sanitize_query(query)
        if not match:
            return []

        extra_filters: list[str] = []
        params: list = [match]
        if session_id:
            extra_filters.append("utterances.session_id = ?")
            params.append(session_id)
        if language:
            extra_filters.append("utterances.language = ?")
            params.append(language)
        if speaker_id:
            extra_filters.append("speaker_segments.contact_id = ?")
            params.append(speaker_id)

        where_tail = (" AND " + " AND ".join(extra_filters)) if extra_filters else ""
        speaker_join = (
            "LEFT JOIN speaker_segments ON speaker_segments.id = utterances.speaker_segment_id"
        )

        sql = f"""
            SELECT utterances.id          AS utterance_id,
                   utterances.session_id  AS session_id,
                   sessions.title         AS session_title,
                   utterances.transcript  AS transcript,
                   utterances.language    AS language,
                   utterances.started_ms  AS started_ms,
                   snippet(utterances_fts, 0, '<mark>', '</mark>', '…', 10) AS snippet
            FROM utterances_fts
            JOIN utterances ON utterances.rowid = utterances_fts.rowid
            JOIN sessions   ON sessions.id = utterances.session_id
            {speaker_join}
            WHERE utterances_fts MATCH ?{where_tail}
            ORDER BY rank
            LIMIT ?
        """
        params.append(limit)
        cur = self.conn.execute(sql, tuple(params))
        return [dict(r) for r in cur.fetchall()]
