"""FastAPI application factory."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..config import BackendConfig
from ..pipeline.coordinator import PipelineCoordinator
from ..providers.asr import WhisperASRProvider
from ..providers.diarization import create_diarization_provider
from ..providers.embedding import ECAPATDNNEmbeddingProvider
from ..storage.database import Database
from ..storage.fts_migration import register_fts_migration
from ..storage.migrations import MigrationRunner
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


def create_app(config: Optional[BackendConfig] = None) -> FastAPI:
    config = config or BackendConfig.load()

    db = Database(config.database)
    db.init_schema()
    runner = MigrationRunner(db)
    register_fts_migration(runner)
    register_source_migration(runner)
    register_voice_profile_metadata_migration(runner)
    register_speaker_segment_diarization_model_migration(runner)
    runner.apply_pending()
    db.close()

    asr = WhisperASRProvider(model_id=config.providers.asr_model_id)
    diarization = create_diarization_provider(config.providers.diarization_model_id)
    embedding = ECAPATDNNEmbeddingProvider(
        model_id=config.providers.embedding_model_id
    )
    coordinator = PipelineCoordinator(config.pipeline, asr, diarization, embedding)

    app = FastAPI(title="Voice Diary API", version="0.1.0", lifespan=_lifespan)
    app.state.config = config
    app.state.coordinator = coordinator
    app.state.providers = {
        "asr": asr,
        "diarization": diarization,
        "embedding": embedding,
    }

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
