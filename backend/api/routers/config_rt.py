"""Runtime config + provider status endpoints."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from ...config import SUPPORTED_DIARIZATION_MODEL_IDS, normalize_diarization_model_id
from ...providers.diarization import create_diarization_provider
from ..schemas import (
    ConfigOut,
    ProviderSelect,
    ProviderStatus,
    StorageInfoOut,
    ThresholdUpdate,
    UnloadAfterStopUpdate,
)

router = APIRouter()


def _provider_status(kind: str, provider: object) -> ProviderStatus:
    model_id = getattr(provider, "model_id", None) or getattr(provider, "model_size", "") or ""
    state = getattr(provider, "_state", None)
    if state is None:
        state = "LOADED" if getattr(provider, "_model", None) is not None else "UNLOADED"
    return ProviderStatus(
        kind=kind,
        model_id=str(model_id),
        state=str(state),
        error=getattr(provider, "_error", None),
    )


@router.get("", response_model=ConfigOut)
def get_config_rt(request: Request):
    cfg = request.app.state.config
    providers = request.app.state.providers
    return ConfigOut(
        vad_threshold=cfg.pipeline.vad_threshold,
        vad_min_silence_ms=cfg.pipeline.vad_min_silence_ms,
        vad_speech_pad_ms=cfg.pipeline.vad_speech_pad_ms,
        vad_min_utterance_ms=cfg.pipeline.vad_min_utterance_ms,
        vad_max_utterance_ms=cfg.pipeline.vad_max_utterance_ms,
        speaker_identification_threshold=cfg.pipeline.speaker_identification_threshold,
        chunk_duration_ms=cfg.pipeline.chunk_duration_ms,
        unload_models_after_stop=cfg.pipeline.unload_models_after_stop,
        providers=[
            _provider_status(kind, provider) for kind, provider in providers.items()
        ],
    )


@router.post("/threshold", response_model=ConfigOut)
def set_threshold(payload: ThresholdUpdate, request: Request):
    if not 0.0 <= payload.value <= 1.0:
        raise HTTPException(status_code=400, detail="threshold must be 0..1")
    request.app.state.config.pipeline.speaker_identification_threshold = payload.value
    request.app.state.config.save()
    return get_config_rt(request)


@router.post("/unload-after-stop", response_model=ConfigOut)
def set_unload_after_stop(payload: UnloadAfterStopUpdate, request: Request):
    request.app.state.config.pipeline.unload_models_after_stop = bool(payload.value)
    request.app.state.config.save()
    return get_config_rt(request)


@router.get("/storage", response_model=StorageInfoOut)
def get_storage_info(request: Request):
    cfg = request.app.state.config
    db_path = Path(cfg.database.path) if cfg.database.path is not None else None
    if db_path is None:
        return StorageInfoOut(db_path="", db_size_bytes=0, exists=False)
    resolved = db_path.resolve() if db_path.exists() else db_path
    size = resolved.stat().st_size if db_path.exists() else 0
    return StorageInfoOut(
        db_path=str(resolved),
        db_size_bytes=int(size),
        exists=db_path.exists(),
    )


@router.post("/provider/{kind}", response_model=ConfigOut)
def select_provider(kind: str, payload: ProviderSelect, request: Request):
    providers = request.app.state.providers
    config = request.app.state.config
    if kind not in providers:
        raise HTTPException(status_code=404, detail=f"unknown provider kind: {kind}")
    if kind == "diarization":
        normalized = normalize_diarization_model_id(payload.model_id)
        if normalized != payload.model_id:
            allowed = ", ".join(sorted(SUPPORTED_DIARIZATION_MODEL_IDS))
            raise HTTPException(
                status_code=400,
                detail=(
                    f"unsupported diarization model_id: {payload.model_id}. "
                    f"Supported: {allowed}"
                ),
            )
    provider = providers[kind]
    if kind == "diarization":
        if hasattr(provider, "unload"):
            provider.unload()
        provider = create_diarization_provider(payload.model_id)
        providers[kind] = provider
        coordinator = getattr(request.app.state, "coordinator", None)
        if coordinator is not None:
            coordinator.diarization = provider
    elif hasattr(provider, "model_id"):
        provider.model_id = payload.model_id
    elif hasattr(provider, "model_size"):
        provider.model_size = payload.model_id
    if kind == "asr":
        config.providers.asr_model_id = payload.model_id
    elif kind == "embedding":
        config.providers.embedding_model_id = payload.model_id
    elif kind == "diarization":
        config.providers.diarization_model_id = payload.model_id
    if hasattr(provider, "unload"):
        provider.unload()
    else:
        provider._model = None
    # reset load progress on switch
    states = getattr(request.app.state, "load_states", None)
    if states and kind in states:
        states[kind].progress = 0.0
        states[kind].started_at = 0.0
    config.save()
    return get_config_rt(request)
