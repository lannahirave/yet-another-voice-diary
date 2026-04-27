"""FTS search REST — seeded via direct DB writes so we control the transcript text."""
from __future__ import annotations

import sqlite3
import time
import uuid
from collections.abc import Iterator

import pytest
from httpx import AsyncClient


@pytest.fixture()
def search_seed(db_conn: sqlite3.Connection) -> Iterator[dict]:
    """Insert a session + utterance with a known term; clean up after test."""
    sess_id = str(uuid.uuid4())
    utt_id = str(uuid.uuid4())

    db_conn.execute(
        "INSERT INTO sessions (id, title, started_at) VALUES (?, ?, ?)",
        (sess_id, "e2e-search-test", int(time.time())),
    )
    db_conn.execute(
        """
        INSERT INTO utterances (id, session_id, started_ms, ended_ms, transcript, language)
        VALUES (?, ?, 0, 3000, 'kubernetes cluster deployment', 'en')
        """,
        (utt_id, sess_id),
    )
    db_conn.commit()
    # The utterances_ai trigger fires automatically on INSERT, populating utterances_fts.

    yield {"session_id": sess_id, "utterance_id": utt_id}

    db_conn.execute("DELETE FROM utterances WHERE id = ?", (utt_id,))
    db_conn.execute("DELETE FROM sessions WHERE id = ?", (sess_id,))
    db_conn.commit()


async def test_search_returns_matching_utterance(
    client: AsyncClient, search_seed: dict
) -> None:
    r = await client.get("/search", params={"q": "kubernetes"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    hit_ids = [h["utterance_id"] for h in body["hits"]]
    assert search_seed["utterance_id"] in hit_ids


async def test_search_returns_correct_session(
    client: AsyncClient, search_seed: dict
) -> None:
    r = await client.get("/search", params={"q": "kubernetes"})
    hits = r.json()["hits"]
    matching = [h for h in hits if h["utterance_id"] == search_seed["utterance_id"]]
    assert matching[0]["session_id"] == search_seed["session_id"]


async def test_search_empty_for_nonexistent_term(client: AsyncClient) -> None:
    r = await client.get("/search", params={"q": "xyznonexistent99"})
    assert r.status_code == 200
    assert r.json()["total"] == 0
    assert r.json()["hits"] == []


async def test_search_requires_query(client: AsyncClient) -> None:
    r = await client.get("/search")
    # Missing q param should return 422 (validation error)
    assert r.status_code == 422
