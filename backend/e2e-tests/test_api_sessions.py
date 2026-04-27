"""Sessions + utterances REST — full CRUD cycle against a real DB."""
from __future__ import annotations

from httpx import AsyncClient


async def test_health(client: AsyncClient) -> None:
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


async def test_sessions_list_initially_empty_or_grows(client: AsyncClient) -> None:
    before = (await client.get("/sessions")).json()
    r = await client.post("/sessions", json={"title": "standup"})
    assert r.status_code == 201
    after = (await client.get("/sessions")).json()
    assert len(after) == len(before) + 1


async def test_sessions_crud(client: AsyncClient) -> None:
    # create
    r = await client.post(
        "/sessions",
        json={"title": "Daily standup", "language_hint": "uk", "notes": "kickoff"},
    )
    assert r.status_code == 201
    s = r.json()
    assert s["title"] == "Daily standup"
    assert s["language_hint"] == "uk"
    assert s["utterance_count"] == 0
    sid = s["id"]

    # get
    r = await client.get(f"/sessions/{sid}")
    assert r.status_code == 200
    assert r.json()["id"] == sid

    # patch
    r = await client.patch(f"/sessions/{sid}", json={"notes": "updated notes"})
    assert r.status_code == 200
    assert r.json()["notes"] == "updated notes"

    # delete
    r = await client.delete(f"/sessions/{sid}")
    assert r.status_code == 204
    r = await client.get(f"/sessions/{sid}")
    assert r.status_code == 404


async def test_session_utterances_via_api(client: AsyncClient) -> None:
    r = await client.post("/sessions", json={"title": "utterance test"})
    sid = r.json()["id"]

    r = await client.post(
        f"/sessions/{sid}/utterances",
        json={
            "session_id": sid,
            "started_ms": 0,
            "ended_ms": 2000,
            "transcript": "привіт як справи",
            "language": "uk",
            "confidence": 0.95,
        },
    )
    assert r.status_code == 201
    assert r.json()["transcript"] == "привіт як справи"

    r = await client.get(f"/sessions/{sid}/utterances")
    assert r.status_code == 200
    assert len(r.json()) == 1

    r = await client.get(f"/sessions/{sid}")
    assert r.json()["utterance_count"] == 1

    # cleanup
    await client.delete(f"/sessions/{sid}")


async def test_session_not_found(client: AsyncClient) -> None:
    r = await client.get("/sessions/does-not-exist")
    assert r.status_code == 404
