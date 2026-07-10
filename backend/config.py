"""Backend configuration."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

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
SUPPORTED_EMBEDDING_MODEL_IDS = frozenset({"ecapa", "ecapa-tdnn"})
SUPPORTED_VAD_MODEL_IDS = frozenset({"silero", "firered-stream-vad"})


def normalize_diarization_model_id(model_id: str) -> str:
    return model_id if model_id in SUPPORTED_DIARIZATION_MODEL_IDS else "pyannote"


def normalize_embedding_model_id(model_id: str) -> str:
    return model_id if model_id in SUPPORTED_EMBEDDING_MODEL_IDS else "ecapa"


def normalize_vad_model_id(model_id: str) -> str:
    return model_id if model_id in SUPPORTED_VAD_MODEL_IDS else "silero"


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

    vad_threshold: float = 0.60
    """VAD speech-probability **onset** threshold (0..1).

    Speech starts when the per-frame probability meets or exceeds this value.
    Follows Vexa's conservative onset for noisy real-world audio.
    """

    vad_negative_threshold: float = 0.45
    """VAD speech-probability **offset** threshold (0..1).

    Once speech has started it continues until the probability drops below
    this value for ``vad_min_silence_ms``.  The gap between onset and offset
    is the hysteresis band — it absorbs wavering borderline speech and
    prevents rapid toggling.
    """

    vad_min_silence_ms: int = 300
    """Trailing sub-offset silence required to declare end-of-speech.

    Lower than the prior 500 ms default to tighten utterance boundaries for
    better diarization. Too low → utterances split on intra-sentence breaths.
    Too high → multi-sentence paragraphs merge into one utterance.
    """

    vad_speech_pad_pre_ms: int = 300
    """Audio padding **before** detected speech (preroll).

    Prepended to the utterance buffer so Whisper has enough co-articulation
    context for the first phoneme.
    """

    vad_speech_pad_post_ms: int = 400
    """Audio padding **after** detected speech (trailing).

    The VAD delays the ``is_speech=False`` signal by this duration so the
    coordinator captures trailing audio around the final phoneme.
    """

    vad_speech_pad_ms: int = 200
    """*Deprecated* — kept for backward compat with existing config files.

    When loading an old config that only has this field (and lacks
    ``vad_speech_pad_pre_ms`` / ``vad_speech_pad_post_ms``) the load path
    seeds the new fields from this value.
    """

    vad_min_utterance_ms: int = 100
    """Minimum buffered speech to accept as a real utterance.

    Coordinator drops anything shorter than this on end-of-speech, suppressing
    spurious activations (cough, click, mic bump). The same floor applies to
    explicit end-of-session flushes so a 100-300 ms stop-tail does not pollute
    the unknown queue or the voice-profile gallery.
    """

    vad_max_utterance_ms: int = 8_000
    """Hard cap on continuous speech before forcing a flush.

    Defaults to 8 s to bound memory and ASR latency while keeping diarization
    segments comfortably below the range where PyAnnote accuracy degrades.
    The speaker remains voiced after a forced flush; the next chunk continues
    buffering a fresh utterance.
    """

    speaker_identification_threshold: float = 0.5
    chunk_duration_ms: int = 100

    unload_models_after_stop: bool = False
    """If true, unload all loaded providers when a recording session ends.

    Frees RAM but introduces a 3-10 s warm-up on the next session.
    """

    blocklist_enabled: bool = True
    """If true, drop known Whisper hallucination transcripts (on by default)."""

    itn_enabled: bool = True
    """If true, normalize mapped ASR transliterations into display terms."""

    itn_selected_maps: Optional[list[str]] = None
    """Selected ITN map filenames. None preserves legacy all-valid-map behavior."""

    asr_no_speech_threshold: float = 0.6  # Vexa default, keep
    asr_compression_ratio_threshold: float = 2.4  # Vexa default, keep
    asr_repetition_penalty: float = 1.1  # Vexa default, keep
    asr_no_repeat_ngram_size: int = 3  # Vexa default, keep
    """N-gram size for hard repeat blocking.

    Forwarded to faster-whisper's ``no_repeat_ngram_size``.  Prevents any
    n-word phrase from appearing twice in the same output.  0 = disabled.
    Vexa default: 3.
    """

    draft_enabled: bool = False
    """If true, emit draft transcripts mid-speech via WebSocket.

    A lightweight ASR model periodically transcribes the current speech
    buffer before the VAD closes the utterance.  Drafts are never persisted
    to the database and carry no speaker / diarization info.
    """

    draft_interval_ms: int = 5000
    """Minimum interval between draft ASR submissions during active speech."""

    mic_self_contact_id: Optional[str] = None
    """When set, mic audio skips diarization and is directly attributed to this contact.

    Embedding still runs to build the voice profile for future system-audio
    matching.  When None, mic audio goes through full diarization + resolver
    same as system audio.
    """

    language_allowlist_enabled: bool = False
    """When true, restrict transcription to allowed languages.

    If the auto-detected language is not in the allowlist, or the
    language confidence is below the threshold, the coordinator
    re-transcribes with every allowed language and picks the best.
    """

    language_allowlist: str = "en,uk"
    """Comma-separated ISO language codes for the allowlist (e.g. ``"en,uk"``)."""

    language_confidence_threshold: float = 0.5
    """Language detection confidence floor (0..1).

    When the auto-detected language probability is below this value the
    multi-pass re-transcription is triggered regardless of whether the
    language is in the allowlist.
    """


@dataclass
class ProviderConfig:
    asr_model_id: str = "large-v3-turbo"
    diarization_model_id: str = "pyannote"
    embedding_model_id: str = "ecapa"
    vad_model_id: str = "silero"
    elevenlabs_api_token: str = ""
    device: str = "auto"
    preload_on_start: bool = True

    def __post_init__(self) -> None:
        self.diarization_model_id = normalize_diarization_model_id(
            self.diarization_model_id
        )
        self.embedding_model_id = normalize_embedding_model_id(
            self.embedding_model_id
        )
        self.vad_model_id = normalize_vad_model_id(self.vad_model_id)


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
        pipeline_raw = raw.get("pipeline", {})
        cls._migrate_vad_padding(pipeline_raw)
        cls._migrate_mic_self_contact(pipeline_raw)
        config = cls(
            database=cls._load_database(raw.get("database", {})),
            pipeline=PipelineConfig(**pipeline_raw),
            providers=ProviderConfig(**raw.get("providers", {})),
        )
        raw_diarization_model_id = (
            raw.get("providers", {}).get("diarization_model_id")
            if isinstance(raw.get("providers", {}), dict)
            else None
        )
        raw_embedding_model_id = (
            raw.get("providers", {}).get("embedding_model_id")
            if isinstance(raw.get("providers", {}), dict)
            else None
        )
        raw_vad_model_id = (
            raw.get("providers", {}).get("vad_model_id")
            if isinstance(raw.get("providers", {}), dict)
            else None
        )
        if (
            raw_diarization_model_id != config.providers.diarization_model_id
            or raw_embedding_model_id != config.providers.embedding_model_id
            or raw_vad_model_id != config.providers.vad_model_id
        ):
            config.save(source)
        return config

    @staticmethod
    def _load_database(raw: dict[str, Any]) -> DatabaseConfig:
        raw_path = raw.get("path")
        return DatabaseConfig(
            path=Path(raw_path) if raw_path is not None else None,
            echo=bool(raw.get("echo", False)),
        )

    @staticmethod
    def _migrate_mic_self_contact(pipeline_raw: dict[str, Any]) -> None:
        """Drop legacy ``mic_is_self`` field — replaced by ``mic_self_contact_id``.

        Old configs that had ``mic_is_self: true`` now default to ``None``
        (diarization active).  The user must select a contact in Settings.
        """
        pipeline_raw.pop("mic_is_self", None)

    @staticmethod
    def _migrate_vad_padding(pipeline_raw: dict[str, Any]) -> None:
        """Seed new pre/post padding fields from legacy ``vad_speech_pad_ms``.

        When a config file created before the asymmetric-padding change
        contains ``vad_speech_pad_ms`` but is missing the new
        ``vad_speech_pad_pre_ms`` / ``vad_speech_pad_post_ms`` keys,
        populate both from the old value.
        """
        if "vad_speech_pad_ms" not in pipeline_raw:
            return
        if "vad_speech_pad_pre_ms" not in pipeline_raw:
            pipeline_raw["vad_speech_pad_pre_ms"] = pipeline_raw["vad_speech_pad_ms"]
        if "vad_speech_pad_post_ms" not in pipeline_raw:
            pipeline_raw["vad_speech_pad_post_ms"] = pipeline_raw["vad_speech_pad_ms"]
