"""Unknown queue REST — list / resolve / skip, seeded via direct DB writes."""
from __future__ import annotations

import sqlite3
import time
import uuid
from collections.abc import Iterator

import numpy as np
import pytest
from fastapi import FastAPI
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Seed helper
# ---------------------------------------------------------------------------


def _seed_queue_item(
    conn: sqlite3.Connection, session_id: str
) -> tuple[str, str]:
    """Insert one session + speaker_segment + unknown_queue row; return (seg_id, q_id)."""
    seg_id = str(uuid.uuid4())
    q_id = str(uuid.uuid4())
    embedding = np.zeros(192, dtype=np.float32).tobytes()
    conn.execute(
        "INSERT OR IGNORE INTO sessions (id, title, started_at) VALUES (?, ?, ?)",
        (session_id, "e2e-queue-test", int(time.time())),
    )
    conn.execute(
        """
        INSERT INTO speaker_segments (id, session_id, status, embedding, sim_score)
        VALUES (?, ?, 'unknown', ?, 0.0)
        """,
        (seg_id, session_id, embedding),
    )
    conn.execute(
        "INSERT INTO unknown_queue (id, speaker_segment_id, created_at) VALUES (?, ?, ?)",
        (q_id, seg_id, int(time.time())),
    )
    conn.commit()
    return seg_id, q_id


@pytest.fixture()
def queue_seed(
    db_conn: sqlite3.Connection, e2e_app: FastAPI
) -> Iterator[dict]:
    """Seed two independent queue items; yield ids; clean up after test."""
    sess_id = str(uuid.uuid4())
    seg1, q1 = _seed_queue_item(db_conn, sess_id)
    # second item in same session
    seg2_id = str(uuid.uuid4())
    q2_id = str(uuid.uuid4())
    embedding = np.zeros(192, dtype=np.float32).tobytes()
    db_conn.execute(
        """
        INSERT INTO speaker_segments (id, session_id, status, embedding, sim_score)
        VALUES (?, ?, 'unknown', ?, 0.0)
        """,
        (seg2_id, sess_id, embedding),
    )
    db_conn.execute(
        "INSERT INTO unknown_queue (id, speaker_segment_id, created_at) VALUES (?, ?, ?)",
        (q2_id, seg2_id, int(time.time())),
    )
    db_conn.commit()

    yield {"session_id": sess_id, "q1": q1, "q2": q2_id, "seg1": seg1, "seg2": seg2_id}

    # Delete in FK-safe order: queue → voice_profiles → utterances → segments → session
    db_conn.execute("DELETE FROM unknown_queue WHERE id IN (?, ?)", (q1, q2_id))
    db_conn.execute("DELETE FROM voice_profiles WHERE source_session_id = ?", (sess_id,))
    db_conn.execute("DELETE FROM utterances WHERE session_id = ?", (sess_id,))
    db_conn.execute("DELETE FROM speaker_segments WHERE session_id = ?", (sess_id,))
    db_conn.execute("DELETE FROM sessions WHERE id = ?", (sess_id,))
    db_conn.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def _all_queue_ids(clusters: list[dict]) -> list[str]:
    out: list[str] = []
    for c in clusters:
        out.extend(c["queue_ids"])
    return out


async def test_queue_list_returns_seeded_items(
    client: AsyncClient, queue_seed: dict
) -> None:
    r = await client.get("/unknown-queue")
    assert r.status_code == 200
    ids = _all_queue_ids(r.json())
    assert queue_seed["q1"] in ids
    assert queue_seed["q2"] in ids


async def test_queue_resolve(client: AsyncClient, queue_seed: dict) -> None:
    # Create a contact to resolve to
    contact = (await client.post("/contacts", json={"name": "ResolveTarget"})).json()
    cid = contact["id"]

    r = await client.post(
        "/unknown-queue/resolve",
        json={"queue_ids": [queue_seed["q1"]], "contact_id": cid},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["resolved_count"] == 1

    # Resolved item no longer appears in unresolved list
    clusters = (await client.get("/unknown-queue")).json()
    unresolved_ids = _all_queue_ids(clusters)
    assert queue_seed["q1"] not in unresolved_ids
    # Contact intentionally not deleted: speaker_segment.contact_id FK would fail
    # if contact is deleted before the segment. DB is ephemeral (temp dir).


async def test_queue_skip(client: AsyncClient, queue_seed: dict) -> None:
    r = await client.post(
        "/unknown-queue/skip", json={"queue_ids": [queue_seed["q2"]]}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["skipped_count"] == 1
    # Item is still unresolved (skip just re-queues it)
    clusters = (await client.get("/unknown-queue")).json()
    assert queue_seed["q2"] in _all_queue_ids(clusters)


async def test_queue_resolve_nonexistent_returns_404(client: AsyncClient) -> None:
    r = await client.post(
        "/unknown-queue/resolve",
        json={"queue_ids": ["ghost-id"], "contact_id": "x"},
    )
    assert r.status_code == 404


async def test_queue_skip_nonexistent_returns_404(client: AsyncClient) -> None:
    r = await client.post(
        "/unknown-queue/skip", json={"queue_ids": ["ghost-id"]}
    )
    assert r.status_code == 404
