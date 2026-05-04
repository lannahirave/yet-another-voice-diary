"""Model lifecycle API tests."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest

from backend.config import BackendConfig


class FakeLoadProvider:
    def __init__(self) -> None:
        self.model_id = "fake-model"
        self._state = "UNLOADED"
        self._error = None
        self._model = None

    def load(self) -> None:
        self._model = object()
        self._state = "LOADED"


async def _wait_for_state(client, kind: str, target: str | tuple[str, ...], timeout: float = 5.0):
    targets = {target} if isinstance(target, str) else set(target)
    deadline = asyncio.get_event_loop().time() + timeout
    last: dict = {}
    while asyncio.get_event_loop().time() < deadline:
        response = await client.get("/models/status")
        assert response.status_code == 200
        last = response.json()[kind]
        if last["state"] in targets:
            return last
        await asyncio.sleep(0.05)
    raise AssertionError(f"{kind} did not reach {targets}; last={last}")


@pytest.mark.asyncio
async def test_model_status_lists_configured_providers(client):
    response = await client.get("/models/status")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"asr", "diarization", "embedding", "vad"}
    assert body["asr"]["model_id"] == "large-v3-turbo"
    assert body["asr"]["state"] == "UNLOADED"


@pytest.mark.asyncio
async def test_model_unload_is_idempotent(client):
    response = await client.post("/models/asr/unload")

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "asr"
    assert body["state"] == "UNLOADED"


@pytest.mark.asyncio
async def test_unknown_model_kind_returns_404(client):
    response = await client.post("/models/missing/unload")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_model_load_logs_success(client, app, caplog):
    app.state.providers["asr"] = FakeLoadProvider()
    caplog.set_level(logging.INFO, logger="backend.api.routers.models")

    response = await client.post("/models/asr/load")

    assert response.status_code == 200
    final = await _wait_for_state(client, "asr", "LOADED")
    assert final["model_id"] == "fake-model"
    assert "model loaded kind=asr model_id=fake-model provider=FakeLoadProvider" in caplog.text


@pytest.mark.asyncio
async def test_model_load_logs_already_loaded(client, app, caplog):
    provider = FakeLoadProvider()
    provider.load()
    app.state.providers["asr"] = provider
    caplog.set_level(logging.INFO, logger="backend.api.routers.models")

    response = await client.post("/models/asr/load")

    assert response.status_code == 200
    assert response.json()["state"] == "LOADED"
    assert "model load skipped kind=asr model_id=fake-model provider=FakeLoadProvider" in caplog.text


@pytest.mark.asyncio
async def test_sortformer_load_surfaces_controlled_error_without_nemo(
    client, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        BackendConfig,
        "default_path",
        staticmethod(lambda: Path(tmp_path) / "config.json"),
    )
    original_cfg = await client.get("/config")
    original_model_id = next(
        p["model_id"]
        for p in original_cfg.json()["providers"]
        if p["kind"] == "diarization"
    )
    try:
        response = await client.post(
            "/config/provider/diarization", json={"model_id": "sortformer-v2.1"}
        )
        assert response.status_code == 200

        response = await client.post("/models/diarization/load")
        assert response.status_code == 200
        assert response.json()["state"] in {"LOADING", "ERROR"}

        final = await _wait_for_state(client, "diarization", ("ERROR", "LOADED"), timeout=30.0)
        if final["state"] == "ERROR":
            assert ".[ml-nemo]" in (final["error"] or "")
        else:
            assert final["state"] == "LOADED"
    finally:
        await client.post(
            "/config/provider/diarization", json={"model_id": original_model_id}
        )
