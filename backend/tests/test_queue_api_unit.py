"""Focused queue API behavior, using the lightweight app fixture."""
from __future__ import annotations

import sqlite3

import numpy as np
import pytest

pytest_plugins = ("backend.tests.api_fixtures",)


def _conn(app) -> sqlite3.Connection:
    conn = sqlite3.connect(str(app.state.config.database.path))
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _seed(app) -> None:
    conn = _conn(app)
    conn.execute(
        "INSERT INTO contacts (id, name, notes, created_at) VALUES (?, ?, ?, ?)",
        ("c1", "Alice", None, 1),
    )
    conn.execute(
        "INSERT INTO sessions (id, title, started_at, ended_at, notes, language_hint) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("s1", "Test", 1, None, None, None),
    )
    conn.execute(
        "INSERT INTO speaker_segments (id, session_id, embedding) VALUES (?, ?, ?)",
        ("seg1", "s1", np.array([1, 0], dtype="float32").tobytes()),
    )
    conn.execute(
        "INSERT INTO unknown_queue (id, speaker_segment_id, created_at) "
        "VALUES (?, ?, ?)",
        ("q1", "seg1", 1),
    )
    conn.execute(
        """INSERT INTO utterances (
            id, session_id, started_ms, ended_ms, transcript, language,
            confidence, speaker_segment_id, source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("u1", "s1", 10, 210, "longer quote", None, 1.0, "seg1", "mic"),
    )
    conn.commit()
    conn.close()


@pytest.mark.asyncio
async def test_queue_count_resolve_and_skip_validation(app, client) -> None:
    _seed(app)
    assert (await client.get("/unknown-queue/count")).json() == {"count": 1}
    assert (await client.post("/unknown-queue/skip", json={"queue_ids": []})).status_code == 400
    response = await client.post("/unknown-queue/resolve", json={"queue_ids": ["q1"], "contact_id": "c1"})
    assert response.status_code == 200
    assert response.json() == {"resolved_count": 1, "cascaded_count": 0}
    assert (await client.get("/unknown-queue/count")).json() == {"count": 0}

    conn = _conn(app)
    queue_row = conn.execute(
        "SELECT resolved_contact_id, resolved_at FROM unknown_queue WHERE id = ?",
        ("q1",),
    ).fetchone()
    assert queue_row[0] == "c1"
    assert queue_row[1] is not None
    segment_row = conn.execute(
        "SELECT contact_id, status FROM speaker_segments WHERE id = ?", ("seg1",)
    ).fetchone()
    assert tuple(segment_row) == ("c1", "identified")
    profile_row = conn.execute(
        "SELECT contact_id, model_id, embedding_dim, source_session_id, source "
        "FROM voice_profiles"
    ).fetchone()
    assert tuple(profile_row) == ("c1", "ecapa", 2, "s1", "mic")
    conn.close()


@pytest.mark.asyncio
async def test_queue_list_returns_complete_cluster_response(app, client) -> None:
    _seed(app)

    response = await client.get("/unknown-queue")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": "q1",
            "queue_ids": ["q1"],
            "segment_ids": ["seg1"],
            "session_ids": ["s1"],
            "session_titles": ["Test"],
            "created_at": "1970-01-01T00:00:01Z",
            "fragment_count": 1,
            "duration_ms": 200,
            "quote": "longer quote",
            "source": "mic",
            "candidates": [],
        }
    ]


@pytest.mark.asyncio
async def test_queue_skip_returns_complete_response_and_updates_database(app, client) -> None:
    _seed(app)

    response = await client.post("/unknown-queue/skip", json={"queue_ids": ["q1"]})

    assert response.status_code == 200
    assert response.json() == {"skipped_count": 1}
    conn = _conn(app)
    row = conn.execute(
        "SELECT created_at, resolved_contact_id, resolved_at "
        "FROM unknown_queue WHERE id = ?",
        ("q1",),
    ).fetchone()
    assert row[0] >= 1
    assert row[1:] == (None, None)
    conn.close()


@pytest.mark.asyncio
async def test_queue_item_and_batch_missing_ids_are_404(app, client) -> None:
    assert (await client.post("/unknown-queue/resolve", json={"queue_ids": ["missing"], "contact_id": "c1"})).status_code == 404
    assert (await client.post("/unknown-queue/skip", json={"queue_ids": ["missing"]})).status_code == 404


@pytest.mark.asyncio
async def test_mixed_valid_and_missing_batches_are_atomic(app, client) -> None:
    _seed(app)

    resolve_response = await client.post(
        "/unknown-queue/resolve",
        json={"queue_ids": ["q1", "missing"], "contact_id": "c1"},
    )
    skip_response = await client.post(
        "/unknown-queue/skip", json={"queue_ids": ["q1", "missing"]}
    )

    assert resolve_response.status_code == 404
    assert resolve_response.json() == {
        "detail": "queue items not found: ['missing']"
    }
    assert skip_response.status_code == 404
    assert skip_response.json() == {"detail": "queue items not found: ['missing']"}

    conn = _conn(app)
    queue_row = conn.execute(
        "SELECT resolved_contact_id, resolved_at, created_at "
        "FROM unknown_queue WHERE id = ?",
        ("q1",),
    ).fetchone()
    assert tuple(queue_row) == (None, None, 1)
    assert conn.execute("SELECT COUNT(*) FROM voice_profiles").fetchone()[0] == 0
    assert conn.execute(
        "SELECT contact_id, status FROM speaker_segments WHERE id = ?", ("seg1",)
    ).fetchone() == (None, "unknown")
    conn.close()


@pytest.mark.asyncio
async def test_queue_delete_returns_count_and_deletes_queue_database_rows(app, client) -> None:
    _seed(app)

    response = await client.post("/unknown-queue/delete", json={"queue_ids": ["q1"]})

    assert response.status_code == 200
    assert response.json() == {"deleted_count": 1}
    conn = _conn(app)
    assert conn.execute(
        "SELECT COUNT(*) FROM unknown_queue WHERE id = ?", ("q1",)
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM speaker_segments WHERE id = ?", ("seg1",)
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM utterances WHERE speaker_segment_id = ?", ("seg1",)
    ).fetchone()[0] == 0
    conn.close()
