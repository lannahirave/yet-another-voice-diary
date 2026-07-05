"""FTS5 search endpoint."""
from __future__ import annotations

import pytest

pytest_plugins = ("backend.tests.api_fixtures",)


@pytest.mark.asyncio
async def test_fts_returns_seeded_rows(client):
    session = (
        await client.post("/sessions", json={"title": "meeting", "language_hint": "uk"})
    ).json()
    sid = session["id"]

    rows = [
        ("Треба запушити фічу", "uk"),
        ("Let's ship the feature", "en"),
        ("Code review після обіду", "uk"),
    ]
    for i, (text, lang) in enumerate(rows):
        r = await client.post(
            f"/sessions/{sid}/utterances",
            json={
                "session_id": sid,
                "started_ms": i * 1000,
                "ended_ms": i * 1000 + 500,
                "transcript": text,
                "language": lang,
                "confidence": 0.9,
            },
        )
        assert r.status_code == 201

    r = await client.get("/search", params={"q": "ship"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert "ship" in body["hits"][0]["transcript"].lower()

    # Filter by language
    r = await client.get("/search", params={"q": "фічу", "language": "uk"})
    assert r.status_code == 200
    assert r.json()["total"] == 1


@pytest.mark.asyncio
async def test_fts_empty_query_rejected(client):
    r = await client.get("/search", params={"q": ""})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_fts_sanitizes_operators(client):
    """MATCH syntax characters should not blow up the query."""
    session = (await client.post("/sessions", json={"title": "t"})).json()
    await client.post(
        f"/sessions/{session['id']}/utterances",
        json={
            "session_id": session["id"],
            "started_ms": 0,
            "ended_ms": 100,
            "transcript": "hello world",
            "confidence": 1.0,
        },
    )
    # Raw query contains an FTS5 phrase-operator char
    r = await client.get("/search", params={"q": "hello*"})
    assert r.status_code == 200
    assert r.json()["total"] == 1
