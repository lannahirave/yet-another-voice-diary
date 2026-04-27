"""Shared pytest fixtures for backend tests."""
from __future__ import annotations

import tempfile
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.api.app import create_app
from backend.config import BackendConfig, DatabaseConfig, PipelineConfig


@pytest.fixture()
def app() -> Iterator[FastAPI]:
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = BackendConfig(
            database=DatabaseConfig(path=Path(tmpdir) / "test.db"),
            pipeline=PipelineConfig(),
        )
        yield create_app(cfg)


@pytest_asyncio.fixture()
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
