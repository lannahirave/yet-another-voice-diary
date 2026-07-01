from __future__ import annotations


async def test_pipeline_config_roundtrips_itn_enabled(client):
    response = await client.get("/config")

    assert response.status_code == 200
    assert response.json()["itn_enabled"] is True

    response = await client.post("/config/pipeline", json={"itn_enabled": False})

    assert response.status_code == 200
    assert response.json()["itn_enabled"] is False
