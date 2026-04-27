"""Contacts REST — CRUD + merge."""
from __future__ import annotations

from httpx import AsyncClient


async def test_contacts_crud(client: AsyncClient) -> None:
    # create
    r = await client.post("/contacts", json={"name": "Alice", "notes": "test"})
    assert r.status_code == 201
    alice = r.json()
    assert alice["name"] == "Alice"
    assert alice["profile_count"] == 0
    cid = alice["id"]

    # list contains new contact
    r = await client.get("/contacts")
    assert r.status_code == 200
    ids = [c["id"] for c in r.json()]
    assert cid in ids

    # get by id
    r = await client.get(f"/contacts/{cid}")
    assert r.status_code == 200
    assert r.json()["name"] == "Alice"

    # patch name
    r = await client.patch(f"/contacts/{cid}", json={"name": "Alice Updated"})
    assert r.status_code == 200
    assert r.json()["name"] == "Alice Updated"

    # delete
    r = await client.delete(f"/contacts/{cid}")
    assert r.status_code == 204
    r = await client.get(f"/contacts/{cid}")
    assert r.status_code == 404


async def test_contact_merge(client: AsyncClient) -> None:
    r_a = await client.post("/contacts", json={"name": "Target"})
    r_b = await client.post("/contacts", json={"name": "Source"})
    target_id = r_a.json()["id"]
    source_id = r_b.json()["id"]

    # merge source INTO target
    r = await client.post(
        f"/contacts/{target_id}/merge", json={"source_id": source_id}
    )
    assert r.status_code == 200
    assert r.json()["id"] == target_id

    # source no longer exists
    r = await client.get(f"/contacts/{source_id}")
    assert r.status_code == 404

    # target still exists
    r = await client.get(f"/contacts/{target_id}")
    assert r.status_code == 200

    # cleanup
    await client.delete(f"/contacts/{target_id}")


async def test_contact_not_found(client: AsyncClient) -> None:
    r = await client.get("/contacts/does-not-exist")
    assert r.status_code == 404


async def test_merge_source_not_found(client: AsyncClient) -> None:
    r_a = await client.post("/contacts", json={"name": "OnlyContact"})
    cid = r_a.json()["id"]
    r = await client.post(f"/contacts/{cid}/merge", json={"source_id": "ghost"})
    assert r.status_code == 404
    await client.delete(f"/contacts/{cid}")
