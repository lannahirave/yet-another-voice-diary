from __future__ import annotations

pytest_plugins = ("backend.tests.api_fixtures",)


async def test_pipeline_config_roundtrips_itn_enabled(client):
    response = await client.get("/config")

    assert response.status_code == 200
    assert response.json()["itn_enabled"] is True

    response = await client.post("/config/pipeline", json={"itn_enabled": False})

    assert response.status_code == 200
    assert response.json()["itn_enabled"] is False


async def test_config_includes_itn_maps_and_selected_defaults(client):
    response = await client.get("/config")

    assert response.status_code == 200
    payload = response.json()
    assert "itn_maps" in payload
    assert "itn_selected_maps" in payload
    valid_maps = [item["filename"] for item in payload["itn_maps"] if item["valid"]]
    assert valid_maps
    assert payload["itn_selected_maps"] == valid_maps


async def test_pipeline_config_roundtrips_itn_selected_maps(client):
    response = await client.get("/config")
    payload = response.json()
    selected = payload["itn_selected_maps"][:1]

    response = await client.post(
        "/config/pipeline",
        json={"itn_selected_maps": selected},
    )

    assert response.status_code == 200
    assert response.json()["itn_selected_maps"] == selected


async def test_pipeline_config_rejects_invalid_itn_selected_maps(client):
    response = await client.post(
        "/config/pipeline",
        json={"itn_selected_maps": ["../bad.json"]},
    )

    assert response.status_code == 400
    assert "invalid ITN map selection" in response.json()["detail"]


async def test_pipeline_config_roundtrips_min_utterance_filter(client):
    response = await client.get("/config")

    assert response.status_code == 200
    assert response.json()["vad_min_utterance_ms"] == 100

    response = await client.post(
        "/config/pipeline",
        json={"vad_min_utterance_ms": 75},
    )

    assert response.status_code == 200
    assert response.json()["vad_min_utterance_ms"] == 75


async def test_pipeline_config_rejects_non_positive_min_utterance_filter(client):
    response = await client.post(
        "/config/pipeline",
        json={"vad_min_utterance_ms": 0},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "vad_min_utterance_ms must be a positive integer"


async def test_pipeline_config_rejects_negative_min_utterance_filter(client):
    response = await client.post(
        "/config/pipeline",
        json={"vad_min_utterance_ms": -25},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "vad_min_utterance_ms must be a positive integer"


async def test_provider_select_rejects_unsupported_embedding_model(client):
    response = await client.post(
        "/config/provider/embedding",
        json={"model_id": "unsupported-embedding"},
    )

    assert response.status_code == 400
    assert "unsupported embedding model_id: unsupported-embedding" in response.json()["detail"]


async def test_provider_select_rejects_unsupported_vad_model(client):
    response = await client.post(
        "/config/provider/vad",
        json={"model_id": "unsupported-vad"},
    )

    assert response.status_code == 400
    assert "unsupported vad model_id: unsupported-vad" in response.json()["detail"]


async def test_provider_select_reconstructs_and_persists_firered_vad(
    client, app, monkeypatch, tmp_path
):
    from backend.config import BackendConfig
    from backend.providers.vad import FireRedVADProvider

    monkeypatch.setattr(
        BackendConfig,
        "default_path",
        staticmethod(lambda: tmp_path / "config.json"),
    )
    previous = app.state.providers["vad"]

    response = await client.post(
        "/config/provider/vad",
        json={"model_id": "firered-stream-vad"},
    )

    assert response.status_code == 200
    assert response.json()["vad_model_id"] == "firered-stream-vad"
    assert isinstance(app.state.providers["vad"], FireRedVADProvider)
    assert app.state.providers["vad"] is not previous
    assert app.state.providers["vad"]._state == "UNLOADED"
    assert BackendConfig.load(tmp_path / "config.json").providers.vad_model_id == (
        "firered-stream-vad"
    )
