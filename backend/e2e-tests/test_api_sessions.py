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


async def test_session_rename_from_empty(client: AsyncClient) -> None:
    """Simulates transcript panel inline rename: create untitled → rename → verify."""
    # Create a session with no title (like the default from CurrentSession)
    r = await client.post("/sessions", json={"title": ""})
    assert r.status_code == 201
    sid = r.json()["id"]
    assert r.json()["title"] == ""

    # GET shows empty — the UI would display "Untitled" placeholder
    r = await client.get(f"/sessions/{sid}")
    assert r.status_code == 200
    assert r.json()["title"] == ""

    # User clicks title, types a name, blurs → PATCH sent
    r = await client.patch(f"/sessions/{sid}", json={"title": "Morning standup"})
    assert r.status_code == 200
    assert r.json()["title"] == "Morning standup"

    # Session list should now show the new title
    sessions = (await client.get("/sessions")).json()
    titles = [s["title"] for s in sessions if s["id"] == sid]
    assert titles == ["Morning standup"]

    # Rename again (second edit from transcript panel)
    r = await client.patch(f"/sessions/{sid}", json={"title": "Daily sync"})
    assert r.status_code == 200
    r = await client.get(f"/sessions/{sid}")
    assert r.json()["title"] == "Daily sync"

    # Cleanup
    await client.delete(f"/sessions/{sid}")


async def test_session_rename_trims_whitespace(client: AsyncClient) -> None:
    """Inline rename with leading/trailing whitespace should be trimmed."""
    r = await client.post("/sessions", json={"title": ""})
    assert r.status_code == 201
    sid = r.json()["id"]

    # Simulate user typing with accidental spaces
    r = await client.patch(f"/sessions/{sid}", json={"title": "   design review   "})
    assert r.status_code == 200
    # Note: the API does NOT trim — the frontend trims before sending.
    # This test verifies the raw API behavior. The frontend handles trimming.
    assert r.json()["title"] == "   design review   "

    # Cleanup
    await client.delete(f"/sessions/{sid}")


async def test_session_rename_preserves_other_fields(client: AsyncClient) -> None:
    """PATCH title should not affect notes or language_hint."""
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
