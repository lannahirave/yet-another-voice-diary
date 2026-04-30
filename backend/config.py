"""Backend configuration."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import torch


def _resolve_device(device: str) -> str:
    """Normalize the user-visible device name, falling back to auto-detection.
    
    ``"auto"`` probes CUDA → MPS → CPU in that order.  Explicit strings
    ``"cuda"``, ``"mps"``, ``"cpu"`` are passed through unchanged.
    """
    if device != "auto":
        return device
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"

SUPPORTED_DIARIZATION_MODEL_IDS = frozenset(
    {"pyannote", "pyannote-3.1", "sortformer-v2.1"}
)


def normalize_diarization_model_id(model_id: str) -> str:
    return model_id if model_id in SUPPORTED_DIARIZATION_MODEL_IDS else "pyannote"


@dataclass
class DatabaseConfig:
    path: Path = Path("backend/voice_diary.db")
    echo: bool = False


@dataclass
class PipelineConfig:
    """Pipeline + endpointing configuration.

    The VAD knobs are exposed at the application layer because end-of-utterance
    behaviour is a perceived-quality property, not an internal model detail.
    Defaults follow common conversational-AI practice (e.g. Silero/Picovoice
    streaming guides, OpenAI Realtime defaults): around half a second of
    trailing silence before closing an utterance, a sub-second floor for the
    minimum useful utterance, and a hard cap to prevent runaway buffers.
    """

    vad_threshold: float = 0.5
    """Silero VAD speech-probability threshold (0..1)."""

    vad_min_silence_ms: int = 500
    """Trailing silence required to declare end-of-utterance.

    Forwarded to Silero's ``VADIterator`` as ``min_silence_duration_ms``. Too
    low → utterances split on intra-sentence breaths. Too high → user perceives
    lag before transcripts appear.
    """

    vad_speech_pad_ms: int = 200
    """Padding added to each side of detected speech windows.

    Forwarded to Silero. Captures co-articulation around the speech boundary
    so Whisper does not lose the leading/trailing phoneme.
    """

    vad_min_utterance_ms: int = 300
    """Minimum buffered speech to accept as a real utterance.

    Coordinator drops anything shorter than this on end-of-speech, suppressing
    spurious activations (cough, click, mic bump). The same floor applies to
    explicit end-of-session flushes so a 100-300 ms stop-tail does not pollute
    the unknown queue or the voice-profile gallery.
    """

    vad_max_utterance_ms: int = 30_000
    """Hard cap on continuous speech before forcing a flush.

    Safeguards memory/latency on monologues. The speaker remains voiced after
    a forced flush; the next chunk continues buffering a fresh utterance.
    """

    speaker_identification_threshold: float = 0.5
    chunk_duration_ms: int = 100

    unload_models_after_stop: bool = False
    """If true, unload all loaded providers when a recording session ends.

    Frees RAM but introduces a 3-10 s warm-up on the next session.
    """


@dataclass
class ProviderConfig:
    asr_model_id: str = "large-v3-turbo"
    diarization_model_id: str = "pyannote"
    embedding_model_id: str = "ecapa"
    device: str = "auto"
    preload_on_start: bool = False

    def __post_init__(self) -> None:
        self.diarization_model_id = normalize_diarization_model_id(
            self.diarization_model_id
        )


@dataclass
class BackendConfig:
    database: DatabaseConfig
    pipeline: PipelineConfig
    providers: ProviderConfig = field(default_factory=ProviderConfig)

    @classmethod
    def default(cls) -> "BackendConfig":
        return cls(
            database=DatabaseConfig(),
            pipeline=PipelineConfig(),
        )

    @staticmethod
    def default_path() -> Path:
        return Path.home() / ".voice-diary" / "config.json"

    def save(self, path: Path | None = None) -> Path:
        target = path or self.default_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "database": {
                "path": str(self.database.path) if self.database.path is not None else None,
                "echo": self.database.echo,
            },
            "pipeline": asdict(self.pipeline),
            "providers": asdict(self.providers),
        }
        target.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )
        return target

    @classmethod
    def load(cls, path: Path | None = None) -> "BackendConfig":
        source = path or cls.default_path()
        if not source.exists():
            return cls.default()

        raw = json.loads(source.read_text(encoding="utf-8"))
        config = cls(
            database=cls._load_database(raw.get("database", {})),
            pipeline=PipelineConfig(**raw.get("pipeline", {})),
            providers=ProviderConfig(**raw.get("providers", {})),
        )
        raw_diarization_model_id = (
            raw.get("providers", {}).get("diarization_model_id")
            if isinstance(raw.get("providers", {}), dict)
            else None
        )
        if raw_diarization_model_id != config.providers.diarization_model_id:
            config.save(source)
        return config

    @staticmethod
    def _load_database(raw: dict[str, Any]) -> DatabaseConfig:
        raw_path = raw.get("path")
        return DatabaseConfig(
            path=Path(raw_path) if raw_path is not None else None,
            echo=bool(raw.get("echo", False)),
        )
