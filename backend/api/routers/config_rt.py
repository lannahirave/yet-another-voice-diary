"""Runtime config + provider status endpoints."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from ...config import SUPPORTED_DIARIZATION_MODEL_IDS, normalize_diarization_model_id
from ...providers.asr import WhisperASRProvider
from ...providers.diarization import create_diarization_provider
from ...providers.elevenlabs import ElevenLabsASRProvider
from ...providers.embedding import ECAPATDNNEmbeddingProvider
from ...providers.itn import (
    discover_itn_maps,
    resolve_selected_itn_maps,
    validate_selected_itn_maps,
)
from ..schemas import (
    BlocklistUpdate,
    ConfigOut,
    DeviceUpdate,
    ElevenLabsTokenUpdate,
    ITNMapOut,
    PipelineUpdate,
    PreloadOnStartUpdate,
    ProviderSelect,
    ProviderStatus,
    StorageInfoOut,
    ThresholdUpdate,
    UnloadAfterStopUpdate,
)

router = APIRouter()


def _mask_token(token: str) -> str:
    if not token:
        return "not set"
    return f"...{token[-4:]}"


def _asr_provider_factory(config, device: str | None = None) -> object:
    """Create the ASR provider based on the configured model_id."""
    if config.providers.asr_model_id == "elevenlabs-scribe":
        return ElevenLabsASRProvider(api_token=config.providers.elevenlabs_api_token)
    return WhisperASRProvider(
        model_id=config.providers.asr_model_id,
        device=device or config.providers.device,
    )


def _provider_status(kind: str, provider: object) -> ProviderStatus:
    model_id = getattr(provider, "model_id", None) or getattr(provider, "model_size", "") or ""
    state = getattr(provider, "_state", None)
    if state is None:
        state = "LOADED" if getattr(provider, "_model", None) is not None else "UNLOADED"
    device = getattr(provider, "device", "auto")
    return ProviderStatus(
        kind=kind,
        model_id=str(model_id),
        state=str(state),
        device=device,
        error=getattr(provider, "_error", None),
    )


def _itn_maps_out() -> list[ITNMapOut]:
    return [
        ITNMapOut(
            filename=info.filename,
            label=info.label,
            valid=info.valid,
            variant_count=info.variant_count,
            error=info.error,
        )
        for info in discover_itn_maps()
    ]


@router.get("", response_model=ConfigOut)
def get_config_rt(request: Request):
    cfg = request.app.state.config
    providers = request.app.state.providers
    return ConfigOut(
        vad_threshold=cfg.pipeline.vad_threshold,
        vad_negative_threshold=cfg.pipeline.vad_negative_threshold,
        vad_min_silence_ms=cfg.pipeline.vad_min_silence_ms,
        vad_speech_pad_pre_ms=cfg.pipeline.vad_speech_pad_pre_ms,
        vad_speech_pad_post_ms=cfg.pipeline.vad_speech_pad_post_ms,
        vad_speech_pad_ms=cfg.pipeline.vad_speech_pad_ms,
        vad_min_utterance_ms=cfg.pipeline.vad_min_utterance_ms,
        vad_max_utterance_ms=cfg.pipeline.vad_max_utterance_ms,
        vad_model_id=cfg.providers.vad_model_id,
        speaker_identification_threshold=cfg.pipeline.speaker_identification_threshold,
        chunk_duration_ms=cfg.pipeline.chunk_duration_ms,
        unload_models_after_stop=cfg.pipeline.unload_models_after_stop,
        preload_on_start=cfg.providers.preload_on_start,
        device=cfg.providers.device,
        blocklist_enabled=cfg.pipeline.blocklist_enabled,
        itn_enabled=cfg.pipeline.itn_enabled,
        itn_maps=_itn_maps_out(),
        itn_selected_maps=resolve_selected_itn_maps(cfg.pipeline.itn_selected_maps),
        elevenlabs_api_token_masked=_mask_token(cfg.providers.elevenlabs_api_token),
        asr_no_speech_threshold=cfg.pipeline.asr_no_speech_threshold,
        asr_compression_ratio_threshold=cfg.pipeline.asr_compression_ratio_threshold,
        asr_repetition_penalty=cfg.pipeline.asr_repetition_penalty,
        asr_no_repeat_ngram_size=cfg.pipeline.asr_no_repeat_ngram_size,
        draft_enabled=cfg.pipeline.draft_enabled,
        draft_interval_ms=cfg.pipeline.draft_interval_ms,
        mic_self_contact_id=cfg.pipeline.mic_self_contact_id,
        language_allowlist_enabled=cfg.pipeline.language_allowlist_enabled,
        language_allowlist=cfg.pipeline.language_allowlist,
        language_confidence_threshold=cfg.pipeline.language_confidence_threshold,
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


@router.post("/pipeline", response_model=ConfigOut)
def set_pipeline(payload: PipelineUpdate, request: Request):
    """Update pipeline VAD / endpointing parameters in bulk.

    Only supplied fields are applied; omitted keys keep their current values.
    """
    pipeline = request.app.state.config.pipeline
    updates = payload.model_dump(exclude_unset=True)
    selected_maps = updates.get("itn_selected_maps", None)
    invalid_maps = validate_selected_itn_maps(selected_maps) if "itn_selected_maps" in updates else []
    if invalid_maps:
        raise HTTPException(
            status_code=400,
            detail=f"invalid ITN map selection: {', '.join(invalid_maps)}",
        )
    min_utterance_ms = updates.get("vad_min_utterance_ms", 1)
    if (
        "vad_min_utterance_ms" in updates
        and (
            not isinstance(min_utterance_ms, int)
            or isinstance(min_utterance_ms, bool)
            or min_utterance_ms < 1
        )
    ):
        raise HTTPException(
            status_code=400,
            detail="vad_min_utterance_ms must be a positive integer",
        )
    for field, value in updates.items():
        if hasattr(pipeline, field):
            setattr(pipeline, field, value)
    request.app.state.config.save()
    return get_config_rt(request)


@router.post("/unload-after-stop", response_model=ConfigOut)
def set_unload_after_stop(payload: UnloadAfterStopUpdate, request: Request):
    request.app.state.config.pipeline.unload_models_after_stop = bool(payload.value)
    request.app.state.config.save()
    return get_config_rt(request)


@router.post("/preload-on-start", response_model=ConfigOut)
def set_preload_on_start(payload: PreloadOnStartUpdate, request: Request):
    request.app.state.config.providers.preload_on_start = bool(payload.value)
    request.app.state.config.save()
    return get_config_rt(request)


@router.post("/blocklist", response_model=ConfigOut)
def set_blocklist(payload: BlocklistUpdate, request: Request):
    request.app.state.config.pipeline.blocklist_enabled = bool(payload.value)
    request.app.state.config.save()
    return get_config_rt(request)


@router.post("/device", response_model=ConfigOut)
def set_device(payload: DeviceUpdate, request: Request):
    allowed = {"auto", "cpu", "cuda", "mps"}
    if payload.value not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"invalid device: {payload.value}. Allowed: {', '.join(sorted(allowed))}",
        )
    config = request.app.state.config
    if config.providers.device == payload.value:
        return get_config_rt(request)

    config.providers.device = payload.value
    providers = request.app.state.providers

    for kind, provider in providers.items():
        if hasattr(provider, "unload"):
            provider.unload()
    # Re-create providers with the new device
    providers["asr"] = _asr_provider_factory(config, device=payload.value)
    providers["diarization"] = create_diarization_provider(
        config.providers.diarization_model_id,
        device=payload.value,
    )
    providers["embedding"] = ECAPATDNNEmbeddingProvider(
        model_id=config.providers.embedding_model_id,
        device=payload.value,
    )

    coordinator = getattr(request.app.state, "coordinator", None)
    if coordinator is not None:
        coordinator.asr = providers["asr"]
        coordinator.diarization = providers["diarization"]
        coordinator.embedding = providers["embedding"]

    config.save()
    if config.providers.preload_on_start:
        from ..app import _startup_preload
        _startup_preload(request.app)
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
        provider = create_diarization_provider(
            payload.model_id, device=config.providers.device
        )
        providers[kind] = provider
        coordinator = getattr(request.app.state, "coordinator", None)
        if coordinator is not None:
            coordinator.diarization = provider
    elif kind == "asr" and (
        payload.model_id == "elevenlabs-scribe"
        or config.providers.asr_model_id == "elevenlabs-scribe"
    ):
        if hasattr(provider, "unload"):
            provider.unload()
        config.providers.asr_model_id = payload.model_id
        provider = _asr_provider_factory(config, device=None)
        providers[kind] = provider
        coordinator = getattr(request.app.state, "coordinator", None)
        if coordinator is not None:
            coordinator.asr = provider
    elif hasattr(provider, "model_id"):
        provider.model_id = payload.model_id
    elif hasattr(provider, "model_size"):
        provider.model_size = payload.model_id
    if kind == "asr":
        # Set by elevenlabs branch above, or fall through
        if config.providers.asr_model_id != payload.model_id:
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


@router.post("/elevenlabs-token", response_model=ConfigOut)
def set_elevenlabs_token(payload: ElevenLabsTokenUpdate, request: Request):
    config = request.app.state.config
    config.providers.elevenlabs_api_token = payload.token
    config.save()

    # If the ASR provider is currently ElevenLabs, update its token in-place
    providers = request.app.state.providers
    asr = providers.get("asr")
    if isinstance(asr, ElevenLabsASRProvider):
        asr.api_token = payload.token
        asr.load()

    # Also update the coordinator reference if needed
    coordinator = getattr(request.app.state, "coordinator", None)
    if coordinator is not None and isinstance(
        getattr(coordinator, "asr", None), ElevenLabsASRProvider
    ):
        coordinator.asr.api_token = payload.token
        coordinator.asr.load()

    return get_config_rt(request)
