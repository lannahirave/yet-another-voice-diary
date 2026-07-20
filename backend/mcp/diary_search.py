"""Agent-friendly, bounded retrieval over Voice Diary data."""
from __future__ import annotations

import re
import sqlite3
from collections import OrderedDict
from pathlib import Path
from typing import Any

from ..storage.search_repo import SearchRepo
from .read_connection import open_read_connection

MAX_QUERY_LENGTH = 500
MAX_RESULTS = 50
MAX_SNIPPET_LENGTH = 320
_MARK_RE = re.compile(r"</?mark>", re.IGNORECASE)


def _validated_query(query: str) -> str:
    normalized = " ".join(query.split())
    if not normalized:
        raise ValueError("query must contain searchable text")
    if len(normalized) > MAX_QUERY_LENGTH:
        raise ValueError(f"query must be at most {MAX_QUERY_LENGTH} characters")
    return normalized


def _validated_limit(limit: int) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError("limit must be an integer")
    return max(1, min(limit, MAX_RESULTS))


def _compact(value: str | None, *, limit: int = MAX_SNIPPET_LENGTH) -> str:
    text = " ".join((value or "").split())
    text = _MARK_RE.sub("", text)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _like_pattern(query: str) -> str:
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


class DiarySearchService:
    """Read-only search service shared by MCP tools and future adapters."""

    def __init__(self, database_path: Path):
        self.database_path = database_path

    def search_transcripts(
        self,
        query: str,
        *,
        session_id: str | None = None,
        contact_id: str | None = None,
        language: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        normalized = _validated_query(query)
        bounded_limit = _validated_limit(limit)
        with open_read_connection(self.database_path) as conn:
            raw_hits = SearchRepo(conn).search(
                normalized,
                session_id=session_id,
                speaker_id=contact_id,
                language=language,
                limit=bounded_limit,
            )
            enrichment = self._utterance_enrichment(
                conn, [str(hit["utterance_id"]) for hit in raw_hits]
            )

        results = []
        for hit in raw_hits:
            extra = enrichment.get(str(hit["utterance_id"]), {})
            results.append(
                {
                    "utterance_id": hit["utterance_id"],
                    "session_id": hit["session_id"],
                    "session_title": hit["session_title"],
                    "session_started_at": extra.get("session_started_at"),
                    "started_ms": hit["started_ms"],
                    "ended_ms": extra.get("ended_ms"),
                    "snippet": _compact(hit["snippet"] or hit["transcript"]),
                    "language": hit["language"],
                    "contact_id": extra.get("contact_id"),
                    "contact_name": extra.get("contact_name"),
                    "source": extra.get("source") or "mic",
                }
            )
        return {"query": normalized, "total": len(results), "results": results}

    def search_diary(self, query: str, *, limit: int = 20) -> dict[str, Any]:
        normalized = _validated_query(query)
        bounded_limit = _validated_limit(limit)
        transcript_result = self.search_transcripts(
            normalized, limit=bounded_limit
        )

        with open_read_connection(self.database_path) as conn:
            metadata = self._metadata_matches(conn, normalized, bounded_limit)

        ordered_matches = [
            {
                **hit,
                "kind": "transcript",
            }
            for hit in transcript_result["results"]
        ]
        ordered_matches.extend(metadata)
        ordered_matches = ordered_matches[:bounded_limit]

        sessions: OrderedDict[str, dict[str, Any]] = OrderedDict()
        for match in ordered_matches:
            session_id = str(match["session_id"])
            group = sessions.setdefault(
                session_id,
                {
                    "session_id": session_id,
                    "session_title": match["session_title"],
                    "session_started_at": match.get("session_started_at"),
                    "matches": [],
                },
            )
            group["matches"].append(
                {
                    key: value
                    for key, value in match.items()
                    if key
                    not in {"session_id", "session_title", "session_started_at"}
                }
            )

        return {
            "query": normalized,
            "total_matches": len(ordered_matches),
            "sessions": list(sessions.values()),
        }

    @staticmethod
    def _utterance_enrichment(
        conn: sqlite3.Connection, utterance_ids: list[str]
    ) -> dict[str, dict[str, Any]]:
        if not utterance_ids:
            return {}
        placeholders = ",".join("?" for _ in utterance_ids)
        rows = conn.execute(
            f"""
            SELECT u.id, u.ended_ms, u.source,
                   s.started_at AS session_started_at,
                   c.id AS contact_id, c.name AS contact_name
            FROM utterances u
            JOIN sessions s ON s.id = u.session_id
            LEFT JOIN speaker_segments ss ON ss.id = u.speaker_segment_id
            LEFT JOIN contacts c ON c.id = ss.contact_id
            WHERE u.id IN ({placeholders})
            """,
            tuple(utterance_ids),
        ).fetchall()
        return {str(row["id"]): dict(row) for row in rows}

    @staticmethod
    def _metadata_matches(
        conn: sqlite3.Connection, query: str, limit: int
    ) -> list[dict[str, Any]]:
        pattern = _like_pattern(query)
        rows = conn.execute(
            """
            SELECT * FROM (
                SELECT 1 AS priority, 'session_title' AS kind,
                       s.id AS session_id, s.title AS session_title,
                       s.started_at AS session_started_at,
                       s.title AS snippet, NULL AS contact_id, NULL AS contact_name
                FROM sessions s
                WHERE CASEFOLD(s.title) LIKE CASEFOLD(?) ESCAPE '\\'
                UNION ALL
                SELECT 2, 'session_note', s.id, s.title, s.started_at,
                       s.notes, NULL, NULL
                FROM sessions s
                WHERE CASEFOLD(COALESCE(s.notes, '')) LIKE CASEFOLD(?) ESCAPE '\\'
                UNION ALL
                SELECT DISTINCT 3, 'contact', s.id, s.title, s.started_at,
                       c.name || CASE WHEN COALESCE(c.notes, '') = ''
                           THEN '' ELSE ': ' || c.notes END,
                       c.id, c.name
                FROM contacts c
                JOIN speaker_segments ss ON ss.contact_id = c.id
                JOIN sessions s ON s.id = ss.session_id
                WHERE (CASEFOLD(c.name) LIKE CASEFOLD(?) ESCAPE '\\'
                    OR CASEFOLD(COALESCE(c.notes, '')) LIKE CASEFOLD(?) ESCAPE '\\')
            )
            ORDER BY priority ASC, session_started_at DESC
            LIMIT ?
            """,
            (pattern, pattern, pattern, pattern, limit),
        ).fetchall()
        return [
            {
                "kind": row["kind"],
                "session_id": row["session_id"],
                "session_title": row["session_title"],
                "session_started_at": row["session_started_at"],
                "snippet": _compact(row["snippet"]),
                "contact_id": row["contact_id"],
                "contact_name": row["contact_name"],
            }
            for row in rows
        ]
