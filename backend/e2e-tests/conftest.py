"""Shared fixtures for e2e tests — real providers, real ML models, real DB."""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import numpy as np
import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

# Ensure web_app/ is on sys.path so `backend.*` imports resolve when pytest's
# rootdir is set to e2e-tests/ itself.
_web_app = Path(__file__).parents[2]
if str(_web_app) not in sys.path:
    sys.path.insert(0, str(_web_app))

from backend.api.app import create_app
from backend.config import BackendConfig, DatabaseConfig, PipelineConfig


@pytest.fixture(scope="session")
def e2e_app(monkeypatch_session: pytest.MonkeyPatch) -> Iterator[FastAPI]:
    with tempfile.TemporaryDirectory() as tmpdir:
        # Redirect BackendConfig.save() target into the tmpdir so endpoints
        # like POST /config/threshold and /config/provider/{kind} — which call
        # config.save() — don't overwrite the user's real ~/.voice-diary/config.json
        # with the test's temp DB path.
        config_path = Path(tmpdir) / "config.json"
        monkeypatch_session.setattr(
            BackendConfig, "default_path", staticmethod(lambda: config_path)
        )
        cfg = BackendConfig(
            database=DatabaseConfig(path=Path(tmpdir) / "e2e.db"),
            pipeline=PipelineConfig(),
        )
        yield create_app(cfg)


@pytest.fixture(scope="session")
def monkeypatch_session() -> Iterator[pytest.MonkeyPatch]:
    """Session-scoped MonkeyPatch — built-in fixture is function-scoped."""
    mp = pytest.MonkeyPatch()
    yield mp
    mp.undo()


@pytest_asyncio.fixture(scope="session")
async def client(e2e_app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=e2e_app), base_url="http://test"
    ) as c:
        yield c


@pytest.fixture(scope="session")
def sync_client(e2e_app: FastAPI) -> TestClient:
    """Synchronous TestClient — required for WebSocket tests."""
    return TestClient(e2e_app, raise_server_exceptions=True)


@pytest.fixture(scope="session")
def wav_f32() -> np.ndarray:
    """Load docs/record_out.wav as mono float32 at 16 kHz."""
    import soundfile as sf

    wav_path = _web_app / "docs" / "record_out.wav"
    data, sr = sf.read(str(wav_path), dtype="float32", always_2d=False)
    if data.ndim > 1:
        data = data[:, 0]
    if sr != 16000:
        from scipy.signal import resample_poly

        data = resample_poly(data, 16000, sr).astype(np.float32)
    return data


@pytest.fixture(scope="session")
def db_conn(e2e_app: FastAPI) -> Iterator[sqlite3.Connection]:
    """Direct SQLite connection for seeding data in API tests."""
    conn = sqlite3.connect(str(e2e_app.state.config.database.path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    yield conn
    conn.close()
