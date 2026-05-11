"""Config + provider selection REST."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from backend.config import BackendConfig


async def test_get_config_shape(client: AsyncClient) -> None:
    r = await client.get("/config")
    assert r.status_code == 200
    body = r.json()
    assert "vad_threshold" in body
    assert "speaker_identification_threshold" in body
    assert "chunk_duration_ms" in body
    assert "providers" in body
    kinds = {p["kind"] for p in body["providers"]}
    assert kinds == {"asr", "embedding", "diarization", "vad"}


async def test_get_config_default_values(client: AsyncClient) -> None:
    r = await client.get("/config")
    body = r.json()
    assert 0.0 < body["vad_threshold"] < 1.0
    assert 0.0 < body["speaker_identification_threshold"] < 1.0
    assert body["chunk_duration_ms"] > 0


async def test_update_speaker_identification_threshold(client: AsyncClient) -> None:
    original = (await client.get("/config")).json()["speaker_identification_threshold"]
    try:
        r = await client.post("/config/threshold", json={"value": 0.75})
        assert r.status_code == 200
        assert r.json()["speaker_identification_threshold"] == pytest.approx(0.75)

        r = await client.get("/config")
        assert r.json()["speaker_identification_threshold"] == pytest.approx(0.75)
    finally:
        # Restore — important: model_lifecycle tests must use the original threshold
        await client.post("/config/threshold", json={"value": original})


async def test_threshold_out_of_range_returns_400(client: AsyncClient) -> None:
    r = await client.post("/config/threshold", json={"value": 1.5})
    assert r.status_code == 400


async def test_update_provider_model_id(client: AsyncClient) -> None:
    original_cfg = await client.get("/config")
    original_asr_id = next(
        p["model_id"] for p in original_cfg.json()["providers"] if p["kind"] == "asr"
    )
    try:
        r = await client.post("/config/provider/asr", json={"model_id": "medium"})
        assert r.status_code == 200
        asr = next(p for p in r.json()["providers"] if p["kind"] == "asr")
        assert asr["model_id"] == "medium"
        # Changing model_id auto-unloads the provider
        assert asr["state"] == "UNLOADED"
    finally:
        # Restore original model_id so model_lifecycle tests load the right model
        await client.post(
            "/config/provider/asr", json={"model_id": original_asr_id}
        )


async def test_update_diarization_provider_to_sortformer(client: AsyncClient) -> None:
    original_cfg = await client.get("/config")
    original_model_id = next(
        p["model_id"]
        for p in original_cfg.json()["providers"]
        if p["kind"] == "diarization"
    )
    try:
        r = await client.post(
            "/config/provider/diarization", json={"model_id": "sortformer-v2.1"}
        )
        assert r.status_code == 200
        diar = next(p for p in r.json()["providers"] if p["kind"] == "diarization")
        assert diar["model_id"] == "sortformer-v2.1"
        assert diar["state"] == "UNLOADED"
    finally:
        await client.post(
            "/config/provider/diarization", json={"model_id": original_model_id}
        )


async def test_update_unknown_provider_returns_404(client: AsyncClient) -> None:
    r = await client.post("/config/provider/not-a-provider", json={"model_id": "something"})
    assert r.status_code == 404


async def test_update_unsupported_diarization_model_returns_400(
    client: AsyncClient,
) -> None:
    r = await client.post("/config/provider/diarization", json={"model_id": "nemo"})
    assert r.status_code == 400
    assert "unsupported diarization model_id" in r.json()["detail"]


async def test_config_save_does_not_touch_user_home(
    client: AsyncClient, e2e_app: FastAPI
) -> None:
    """Regression: tests must never write to ~/.voice-diary/config.json.

    Previously, POST /config/threshold and /config/provider called
    config.save() which serialised to BackendConfig.default_path() — i.e.
    ~/.voice-diary/config.json — leaving the temp DB path in the user's
    real config and breaking subsequent app launches.
    """
    user_config = Path.home() / ".voice-diary" / "config.json"
    before = user_config.read_text(encoding="utf-8") if user_config.exists() else None

    # Both endpoints that call config.save():
    original = (await client.get("/config")).json()["speaker_identification_threshold"]
    await client.post("/config/threshold", json={"value": 0.71})
    await client.post("/config/threshold", json={"value": original})

    after = user_config.read_text(encoding="utf-8") if user_config.exists() else None
    assert after == before, (
        "config.save() leaked into ~/.voice-diary/config.json — conftest "
        "must monkeypatch BackendConfig.default_path()"
    )

    # And it should have written into the test's tmpdir instead.
    test_config_path = BackendConfig.default_path()
    assert test_config_path.exists(), (
        f"expected config saved into test tmpdir at {test_config_path}"
    )
    import json
    saved = json.loads(test_config_path.read_text(encoding="utf-8"))
    assert Path(saved["database"]["path"]) == e2e_app.state.config.database.path
