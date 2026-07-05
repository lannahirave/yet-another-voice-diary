"""Contact endpoints."""
from __future__ import annotations

import pytest

pytest_plugins = ("backend.tests.api_fixtures",)


@pytest.mark.asyncio
async def test_contact_crud(client):
    r = await client.get("/contacts")
    assert r.status_code == 200
    assert r.json() == []

    r = await client.post("/contacts", json={"name": "Аліса", "notes": "PM"})
    assert r.status_code == 201
    contact_id = r.json()["id"]
    assert r.json()["name"] == "Аліса"

    r = await client.patch(f"/contacts/{contact_id}", json={"notes": "Lead PM"})
    assert r.status_code == 200
    assert r.json()["notes"] == "Lead PM"

    r = await client.delete(f"/contacts/{contact_id}")
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_list_contact_utterances(client, app):
    """Contact page must show every utterance attributed to the contact —
    across all sessions, newest first."""
    import sqlite3

    contact = (await client.post("/contacts", json={"name": "Bob"})).json()
    contact_id = contact["id"]

    # Seed two sessions, each with one utterance attributed to Bob, and one
    # utterance attributed to nobody (must NOT appear in the contact list).
    db_path = app.state.config.database.path
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(
        f"""
        INSERT INTO sessions (id, title, started_at) VALUES
            ('sess-old', 'old', 1000),
            ('sess-new', 'new', 2000);
        INSERT INTO speaker_segments (id, session_id, contact_id, status) VALUES
            ('seg-1', 'sess-old', '{contact_id}', 'identified'),
            ('seg-2', 'sess-new', '{contact_id}', 'identified'),
            ('seg-3', 'sess-new', NULL, 'unknown');
        INSERT INTO utterances (id, session_id, started_ms, ended_ms,
                                 transcript, speaker_segment_id) VALUES
            ('u-old', 'sess-old', 0, 1000, 'hello from old', 'seg-1'),
            ('u-new', 'sess-new', 0, 1000, 'hello from new', 'seg-2'),
            ('u-other', 'sess-new', 1000, 2000, 'someone else', 'seg-3');
        """
    )
    conn.commit()
    conn.close()

    r = await client.get(f"/contacts/{contact_id}/utterances")
    assert r.status_code == 200
    body = r.json()
    transcripts = [u["transcript"] for u in body]
    assert transcripts == ["hello from new", "hello from old"], (
        "expected newest session first, then chronological inside; "
        "and 'someone else' must be excluded"
    )


@pytest.mark.asyncio
async def test_list_utterances_for_unknown_contact_returns_404(client):
    r = await client.get("/contacts/does-not-exist/utterances")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_contact_merge(client):
    a = (await client.post("/contacts", json={"name": "A"})).json()
    b = (await client.post("/contacts", json={"name": "B"})).json()

    r = await client.post(
        f"/contacts/{a['id']}/merge", json={"source_id": b["id"]}
    )
    assert r.status_code == 200
    assert r.json()["id"] == a["id"]

    # B should be gone
    r = await client.get(f"/contacts/{b['id']}")
    assert r.status_code == 404
