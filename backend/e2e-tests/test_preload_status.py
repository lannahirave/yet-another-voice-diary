"""End-to-end coverage for startup model preloading and status exposure."""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.api import app as app_module
from backend.api.app import create_app
from backend.config import BackendConfig, DatabaseConfig, PipelineConfig, ProviderConfig


class _FakeProvider:
    def __init__(self, model_id: str, device: str = "cpu") -> None:
        self.model_id = model_id
        self.device = device
        self._state = "UNLOADED"
        self._error = None
        self._model = None

    def load(self) -> None:
        self._model = object()
        self._state = "LOADED"

    def unload(self) -> None:
        self._model = None
        self._state = "UNLOADED"


@pytest_asyncio.fixture
async def preload_client(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        monkeypatch.setattr(
            app_module.config_rt,
            "_asr_provider_factory",
            lambda config: _FakeProvider("large-v3-turbo"),
        )
        monkeypatch.setattr(
            app_module,
            "create_diarization_provider",
            lambda model_id, device: _FakeProvider(model_id, device),
        )
        monkeypatch.setattr(
            app_module,
            "ECAPATDNNEmbeddingProvider",
            lambda model_id, device: _FakeProvider(model_id, device),
        )
        monkeypatch.setattr(
            app_module,
            "create_vad_provider",
            lambda model_id, **kwargs: _FakeProvider(model_id),
        )
        config = BackendConfig(
            database=DatabaseConfig(path=root / "preload.db"),
            pipeline=PipelineConfig(),
            providers=ProviderConfig(preload_on_start=True),
        )
        application = create_app(config)
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://test"
        ) as client:
            yield client


async def _wait_for_loaded(client: AsyncClient) -> dict:
    for _ in range(50):
        response = await client.get("/models/status")
        assert response.status_code == 200
        status = response.json()
        if all(provider["state"] == "LOADED" for provider in status.values()):
            return status
        await asyncio.sleep(0.01)
    raise AssertionError(f"startup preload did not finish: {status}")


async def test_preloaded_models_are_reported_loaded_to_settings(
    preload_client: AsyncClient,
) -> None:
    status = await _wait_for_loaded(preload_client)
    config_response = await preload_client.get("/config")

    assert config_response.status_code == 200
    config_providers = {
        provider["kind"]: provider for provider in config_response.json()["providers"]
    }
    assert config_response.json()["preload_on_start"] is True
    assert set(config_providers) == set(status)
    assert all(provider["state"] == "LOADED" for provider in config_providers.values())
