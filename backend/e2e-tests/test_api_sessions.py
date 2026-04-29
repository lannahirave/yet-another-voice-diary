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


async def test_session_rename(client: AsyncClient) -> None:
    """Inline session renaming: PATCH title, verify persistence, handle empty/trim."""
    # Create a session with an initial title
    r = await client.post("/sessions", json={"title": "old name"})
    assert r.status_code == 201
    sid = r.json()["id"]
    assert r.json()["title"] == "old name"

    # Rename via PATCH
    r = await client.patch(f"/sessions/{sid}", json={"title": "new name"})
    assert r.status_code == 200
    assert r.json()["title"] == "new name"

    # Verify persistence via GET
    r = await client.get(f"/sessions/{sid}")
    assert r.status_code == 200
    assert r.json()["title"] == "new name"

    # Rename to empty string (trim → empty, the API accepts it)
    r = await client.patch(f"/sessions/{sid}", json={"title": ""})
    assert r.status_code == 200
    assert r.json()["title"] == ""

    # Rename back
    r = await client.patch(f"/sessions/{sid}", json={"title": "final name"})
    assert r.status_code == 200
    assert r.json()["title"] == "final name"

    # Cleanup
    await client.delete(f"/sessions/{sid}")


async def test_session_rename_nonexistent(client: AsyncClient) -> None:
    """PATCH on non-existent session returns 404."""
    r = await client.patch("/sessions/does-not-exist", json={"title": "nope"})
    assert r.status_code == 404


async def test_utterance_candidates_not_found(client: AsyncClient) -> None:
    """GET candidates for non-existent utterance returns 404."""
    r = await client.get("/sessions/utterances/does-not-exist/candidates")
    assert r.status_code == 404


async def test_utterance_identify_not_found(client: AsyncClient) -> None:
    """POST identify for non-existent utterance returns 404."""
    r = await client.post(
        "/sessions/utterances/does-not-exist/identify",
        json={"contact_id": "fake"},
    )
    assert r.status_code == 404
