"""Session + utterance endpoints."""
from __future__ import annotations

import pytest

pytest_plugins = ("backend.tests.api_fixtures",)


@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_sessions_crud(client):
    # empty list
    r = await client.get("/sessions")
    assert r.status_code == 200
    assert r.json() == []

    # create
    r = await client.post(
        "/sessions",
        json={"title": "Daily standup", "language_hint": "uk", "notes": "kickoff"},
    )
    assert r.status_code == 201
    created = r.json()
    assert created["title"] == "Daily standup"
    assert created["language_hint"] == "uk"
    assert created["utterance_count"] == 0
    session_id = created["id"]

    # list
    r = await client.get("/sessions")
    assert r.status_code == 200
    assert len(r.json()) == 1

    # get
    r = await client.get(f"/sessions/{session_id}")
    assert r.status_code == 200
    assert r.json()["id"] == session_id

    # patch
    r = await client.patch(
        f"/sessions/{session_id}", json={"notes": "updated"}
    )
    assert r.status_code == 200
    assert r.json()["notes"] == "updated"

    # delete
    r = await client.delete(f"/sessions/{session_id}")
    assert r.status_code == 204
    r = await client.get(f"/sessions/{session_id}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_session_utterances(client):
    r = await client.post("/sessions", json={"title": "test"})
    session_id = r.json()["id"]

    r = await client.post(
        f"/sessions/{session_id}/utterances",
        json={
            "session_id": session_id,
            "started_ms": 0,
            "ended_ms": 1500,
            "transcript": "привіт world",
            "language": "uk",
            "confidence": 0.9,
        },
    )
    assert r.status_code == 201
    u = r.json()
    assert u["transcript"] == "привіт world"

    r = await client.get(f"/sessions/{session_id}/utterances")
    assert r.status_code == 200
    assert len(r.json()) == 1

    # session summary now reflects the utterance
    r = await client.get(f"/sessions/{session_id}")
    assert r.json()["utterance_count"] == 1


@pytest.mark.asyncio
async def test_session_not_found(client):
    r = await client.get("/sessions/does-not-exist")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_session_rename_title(client):
    # Create
    r = await client.post("/sessions", json={"title": "original"})
    assert r.status_code == 201
    sid = r.json()["id"]

    # Rename
    r = await client.patch(f"/sessions/{sid}", json={"title": "renamed"})
    assert r.status_code == 200
    assert r.json()["title"] == "renamed"

    # Verify persistence
    r = await client.get(f"/sessions/{sid}")
    assert r.status_code == 200
    assert r.json()["title"] == "renamed"

    # Rename to empty
    r = await client.patch(f"/sessions/{sid}", json={"title": ""})
    assert r.status_code == 200
    assert r.json()["title"] == ""

    # Cleanup
    await client.delete(f"/sessions/{sid}")


@pytest.mark.asyncio
async def test_session_rename_not_found(client):
    r = await client.patch("/sessions/does-not-exist", json={"title": "nope"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_session_rename_from_empty(client):
    # Create untitled session (simulates "Без назви" default)
    r = await client.post("/sessions", json={"title": ""})
    assert r.status_code == 201
    sid = r.json()["id"]
    assert r.json()["title"] == ""

    # Rename via inline edit (simulating transcript panel click → type → blur)
    r = await client.patch(f"/sessions/{sid}", json={"title": "Morning standup"})
    assert r.status_code == 200
    assert r.json()["title"] == "Morning standup"

    # Verify list reflects the change
    sessions = (await client.get("/sessions")).json()
    titles = [s["title"] for s in sessions if s["id"] == sid]
    assert titles == ["Morning standup"]

    await client.delete(f"/sessions/{sid}")


@pytest.mark.asyncio
async def test_session_rename_preserves_other_fields(client):
    r = await client.post(
        "/sessions",
        json={"title": "original", "language_hint": "uk", "notes": "my notes"},
    )
    assert r.status_code == 201
    sid = r.json()["id"]

    r = await client.patch(f"/sessions/{sid}", json={"title": "renamed"})
    assert r.status_code == 200
    data = r.json()
    assert data["title"] == "renamed"
    assert data["language_hint"] == "uk"
    assert data["notes"] == "my notes"

    await client.delete(f"/sessions/{sid}")
