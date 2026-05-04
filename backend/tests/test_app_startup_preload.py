"""Application startup preload tests."""
from __future__ import annotations

import threading
from pathlib import Path

from backend.api.app import create_app
from backend.config import BackendConfig, DatabaseConfig, PipelineConfig, ProviderConfig


def test_startup_preload_passes_kind_provider_and_load(monkeypatch, tmp_path):
    calls: list[tuple[str, object, object]] = []
    threads: list[threading.Thread] = []

    def fake_run_load(kind: str, provider: object, load: object) -> None:
        calls.append((kind, provider, load))

    original_start = threading.Thread.start

    def tracking_start(self: threading.Thread) -> None:
        threads.append(self)
        original_start(self)

    monkeypatch.setattr("backend.api.routers.models._run_load", fake_run_load)
    monkeypatch.setattr(threading.Thread, "start", tracking_start)

    cfg = BackendConfig(
        database=DatabaseConfig(path=Path(tmp_path) / "test.db"),
        pipeline=PipelineConfig(),
        providers=ProviderConfig(preload_on_start=True),
    )

    app = create_app(cfg)

    for thread in threads:
        thread.join(timeout=2.0)

    assert [kind for kind, _, _ in calls] == ["asr", "diarization", "embedding", "vad"]
    assert all(load is app.state.load_states[kind] for kind, _, load in calls)
