"""FastAPI application factory."""
from __future__ import annotations

import threading
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..config import BackendConfig
from ..pipeline.coordinator import PipelineCoordinator
from ..providers.diarization import create_diarization_provider
from ..providers.embedding import ECAPATDNNEmbeddingProvider
from ..providers.vad import create_vad_provider
from ..storage.database import Database
from ..storage.fts_migration import register_fts_migration
from ..storage.migrations import MigrationRunner
from ..storage.pipeline_errors_migration import register_pipeline_errors_migration
from ..storage.speaker_segment_diarization_model_migration import (
    register_speaker_segment_diarization_model_migration,
)
from ..storage.source_migration import register_source_migration
from ..storage.voice_profile_metadata_migration import (
    register_voice_profile_metadata_migration,
)
from .routers import audio_ws, config_rt, contacts, models, queue, search, sessions


@asynccontextmanager
async def _lifespan(app: FastAPI):
    yield


def _startup_preload(app: FastAPI) -> None:
    """Spawn background threads to preload configured providers."""
    import logging

    _log = logging.getLogger(__name__)
    from .routers.models import _LoadState, _run_load

    if not hasattr(app.state, "load_states"):
        app.state.load_states = {
            kind: _LoadState() for kind in app.state.providers
        }

    for kind, provider in app.state.providers.items():
        state = getattr(provider, "_state", "UNLOADED")
        if state not in ("UNLOADED", "ERROR"):
            continue
        load = app.state.load_states[kind]
        try:
            provider._state = "LOADING"  # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            provider._error = None  # type: ignore[attr-defined]
        except Exception:
            pass
        load.progress = 0.05
        load.started_at = time.monotonic()
        load.event.clear()
        thread = threading.Thread(
            target=_run_load,
            args=(kind, provider, load),
            name=f"preload-{kind}",
            daemon=True,
        )
        thread.start()
        _log.info("preloading %s model %s", kind, getattr(provider, "model_id", "?"))


def create_app(config: Optional[BackendConfig] = None) -> FastAPI:
    config = config or BackendConfig.load()

    db = Database(config.database)
    db.init_schema()
    runner = MigrationRunner(db)
    register_fts_migration(runner)
    register_source_migration(runner)
    register_voice_profile_metadata_migration(runner)
    register_speaker_segment_diarization_model_migration(runner)
    register_pipeline_errors_migration(runner)
    runner.apply_pending()
    db.close()

    asr = config_rt._asr_provider_factory(config)
    diarization = create_diarization_provider(
        config.providers.diarization_model_id,
        device=config.providers.device,
    )
    embedding = ECAPATDNNEmbeddingProvider(
        model_id=config.providers.embedding_model_id,
        device=config.providers.device,
    )
    vad = create_vad_provider(
        model_id=config.providers.vad_model_id,
        threshold=config.pipeline.vad_threshold,
        negative_threshold=config.pipeline.vad_negative_threshold,
        min_silence_ms=config.pipeline.vad_min_silence_ms,
        speech_pad_pre_ms=config.pipeline.vad_speech_pad_pre_ms,
        speech_pad_post_ms=config.pipeline.vad_speech_pad_post_ms,
        min_utterance_ms=config.pipeline.vad_min_utterance_ms,
        max_utterance_ms=config.pipeline.vad_max_utterance_ms,
    )
    coordinator = PipelineCoordinator(config.pipeline, asr, diarization, embedding)

    app = FastAPI(title="Voice Diary API", version="0.1.0", lifespan=_lifespan)
    app.state.config = config
    app.state.coordinator = coordinator
    app.state.providers = {
        "asr": asr,
        "diarization": diarization,
        "embedding": embedding,
        "vad": vad,
    }

    if config.providers.preload_on_start:
        _startup_preload(app)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(sessions.router, prefix="/sessions", tags=["sessions"])
    app.include_router(contacts.router, prefix="/contacts", tags=["contacts"])
    app.include_router(queue.router, prefix="/unknown-queue", tags=["queue"])
    app.include_router(search.router, prefix="/search", tags=["search"])
    app.include_router(config_rt.router, prefix="/config", tags=["config"])
    app.include_router(models.router, prefix="/models", tags=["models"])
    app.include_router(audio_ws.router)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "version": app.version}

    return app
