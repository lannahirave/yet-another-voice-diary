"""Read-only MCP retrieval service tests (no MCP transport required)."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from backend.mcp.diary_search import DiarySearchService
from backend.mcp.read_connection import (
    DiaryDatabaseError,
    load_database_path,
    open_read_connection,
)


@pytest.fixture
def diary_db(tmp_path: Path) -> Path:
    path = tmp_path / "diary.db"
    conn = sqlite3.connect(path)
    schema = (Path(__file__).parents[1] / "storage" / "schema.sql").read_text(
        encoding="utf-8"
    )
    conn.executescript(schema)
    conn.executescript(
        """
        CREATE TRIGGER utterances_ai AFTER INSERT ON utterances BEGIN
          INSERT INTO utterances_fts(rowid, transcript)
          VALUES (new.rowid, new.transcript);
        END;

        INSERT INTO contacts (id, name, notes, created_at)
        VALUES ('contact-1', 'Anna', 'Platform engineering', 1700000000);
        INSERT INTO sessions (id, title, started_at, ended_at, notes, language_hint)
        VALUES
          ('session-1', 'Deployment review', 1700000100, 1700000200,
           'Discussed production rollout and monitoring', 'en'),
          ('session-2', 'Design sync', 1700000300, 1700000400,
           'Accessibility follow-up', 'en');
        INSERT INTO speaker_segments
          (id, session_id, contact_id, status, source)
        VALUES ('segment-1', 'session-1', 'contact-1', 'identified', 'system');
        INSERT INTO utterances
          (id, session_id, started_ms, ended_ms, transcript, language,
           confidence, speaker_segment_id, source)
        VALUES
          ('utterance-1', 'session-1', 1200, 3600,
           'We should deploy the API after the final smoke test.', 'en', 0.95,
           'segment-1', 'system'),
          ('utterance-2', 'session-2', 500, 1800,
           'The interface needs a clearer focus state.', 'en', 0.91,
           NULL, 'mic');
        """
    )
    conn.commit()
    conn.close()
    return path


def test_transcript_search_returns_bounded_attributed_snippets(diary_db: Path) -> None:
    result = DiarySearchService(diary_db).search_transcripts("deploy", limit=1000)

    assert result["total"] == 1
    assert result["results"] == [
        {
            "utterance_id": "utterance-1",
            "session_id": "session-1",
            "session_title": "Deployment review",
            "session_started_at": 1700000100,
            "started_ms": 1200,
            "ended_ms": 3600,
            "snippet": "We should deploy the API after the final smoke test.",
            "language": "en",
            "contact_id": "contact-1",
            "contact_name": "Anna",
            "source": "system",
        }
    ]


def test_transcript_search_filters_by_contact_and_language(diary_db: Path) -> None:
    service = DiarySearchService(diary_db)

    assert service.search_transcripts(
        "deploy", contact_id="contact-1", language="en"
    )["total"] == 1
    assert service.search_transcripts(
        "deploy", contact_id="missing-contact"
    )["total"] == 0
    assert service.search_transcripts("deploy", language="uk")["total"] == 0


@pytest.mark.parametrize("query", ["", "   "])
def test_search_rejects_empty_queries(diary_db: Path, query: str) -> None:
    with pytest.raises(ValueError, match="searchable text"):
        DiarySearchService(diary_db).search_diary(query)


def test_diary_search_groups_transcript_and_metadata_matches(diary_db: Path) -> None:
    service = DiarySearchService(diary_db)

    transcript = service.search_diary("deploy")
    session_note = service.search_diary("monitoring")
    contact = service.search_diary("Anna")

    assert transcript["sessions"][0]["matches"][0]["kind"] == "transcript"
    assert session_note["sessions"][0]["matches"][0]["kind"] == "session_note"
    assert contact["sessions"][0]["matches"][0]["kind"] == "contact"
    assert contact["sessions"][0]["matches"][0]["contact_name"] == "Anna"


def test_diary_metadata_search_is_unicode_case_insensitive(diary_db: Path) -> None:
    conn = sqlite3.connect(diary_db)
    conn.execute(
        "UPDATE sessions SET title = 'Розгортання сервісу' WHERE id = 'session-1'"
    )
    conn.commit()
    conn.close()

    result = DiarySearchService(diary_db).search_diary("РОЗГОРТАННЯ")

    assert result["sessions"][0]["session_id"] == "session-1"
    assert result["sessions"][0]["matches"][0]["kind"] == "session_title"


def test_read_connection_blocks_writes(diary_db: Path) -> None:
    with pytest.raises(DiaryDatabaseError, match="readonly|read-only"):
        with open_read_connection(diary_db) as conn:
            conn.execute(
                "INSERT INTO sessions (id, title, started_at) VALUES ('x', 'x', 1)"
            )

    conn = sqlite3.connect(diary_db)
    assert conn.execute("SELECT COUNT(*) FROM sessions WHERE id = 'x'").fetchone()[0] == 0
    conn.close()


def test_read_connection_rejects_outdated_schema(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY)")
    conn.close()

    with pytest.raises(DiaryDatabaseError, match="Open or update Voice Diary first"):
        with open_read_connection(path):
            pass


def test_database_path_loads_without_backend_ml_config(tmp_path: Path) -> None:
    database = tmp_path / "configured.db"
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"database": {"path": str(database)}}), encoding="utf-8"
    )

    assert load_database_path(config_path=config) == database.resolve()
