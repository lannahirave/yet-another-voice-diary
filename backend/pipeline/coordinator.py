"""Pipeline coordinator orchestrating all components."""
import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Optional, Protocol

import numpy as np

from ..config import PipelineConfig
from ..models import RecordingSession, SpeakerSegment, Utterance
from ..providers.base import ASRProvider, DiarizationProvider, EmbeddingProvider
from ..providers.diarization import DiarizationSegment
from ..providers.vad import SpeechSegment

# Dedicated thread pool for ML inference — keeps heavy model calls (ASR,
# diarization, embedding) from competing with HTTP handler threads in
# FastAPI's default pool, and keeps the event loop responsive during
# transcription.
#
# max_workers=1 serialises all inference across connections, which also
# avoids thread-safety issues with shared provider singletons (CTranslate2,
# SpeechBrain, PyAnnote are not designed for concurrent calls).
_inference_pool = ThreadPoolExecutor(max_workers=1)
_draft_pool = ThreadPoolExecutor(max_workers=1)


log = logging.getLogger(__name__)
uvicorn_log = logging.getLogger("uvicorn.error")


class VADLike(Protocol):
    def reset(self) -> None: ...

    def process(self, audio: np.ndarray, sample_rate: int) -> Any: ...


class PipelineCoordinator:
    """Orchestrates the full processing pipeline."""

    def __init__(
        self,
        config: PipelineConfig,
        asr_provider: ASRProvider,
        diarization_provider: DiarizationProvider,
        embedding_provider: EmbeddingProvider,
        vad_processor: VADLike | None = None,
        source: str = "mic",
    ):
        self.config = config
        self.asr = asr_provider
        self.diarization = diarization_provider
        self.embedding = embedding_provider
        self.vad = vad_processor
        if self.vad is None:
            from ..providers.vad import create_vad_provider
            _vad = create_vad_provider(
                threshold=config.vad_threshold,
                negative_threshold=config.vad_negative_threshold,
                min_silence_ms=config.vad_min_silence_ms,
                speech_pad_pre_ms=config.vad_speech_pad_pre_ms,
                speech_pad_post_ms=config.vad_speech_pad_post_ms,
            )
            self.vad = _vad.create_session()
        if hasattr(self.vad, "max_utterance_ms"):
            self.vad.max_utterance_ms = config.vad_max_utterance_ms
        self.source = source

        self._current_session: Optional[RecordingSession] = None
        self._callbacks: dict[str, list[Callable]] = {
            "utterance": [],
            "speaker_segment": [],
            "error": [],
            "debug:audio": [],
            "debug:vad": [],
        }
        self._pending_tasks: set[asyncio.Task] = set()  # type: ignore
        self._session_elapsed_ms = 0
        self._draft_asr: Any = None  # lightweight ASR for draft streaming
        self._last_draft_ms: int = 0

    def on(self, event: str, callback: Callable):
        """Register event callback."""
        if event not in self._callbacks:
            self._callbacks[event] = []
        self._callbacks[event].append(callback)

    def off(self, event: str, callback: Callable) -> bool:
        """Unregister a previously-registered callback. Returns True if removed."""
        handlers = self._callbacks.get(event)
        if not handlers:
            return False
        try:
            handlers.remove(callback)
            return True
        except ValueError:
            return False

    def has_listeners(self, event: str) -> bool:
        """Return True when at least one callback is attached for ``event``."""
        return bool(self._callbacks.get(event))

    def _emit(self, event: str, data: Any):
        """Emit event to all registered callbacks."""
        for callback in self._callbacks.get(event, []):
            try:
                if asyncio.iscoroutinefunction(callback):
                    task = asyncio.create_task(callback(data))
                    self._pending_tasks.add(task)
                    task.add_done_callback(self._pending_tasks.discard)
                else:
                    callback(data)
            except Exception as e:
                if event != "error":
                    self._emit("error", {"code": "CALLBACK_FAILURE", "message": str(e)})

    @staticmethod
    def _cuda_memory_snapshot() -> dict[str, Any]:
        """Return current CUDA memory metrics in MiB when available."""
        try:
            import torch  # type: ignore[import-untyped]
        except Exception:
            return {"available": False}

        if not torch.cuda.is_available():
            return {"available": False}

        try:
            device_idx = torch.cuda.current_device()
            return {
                "available": True,
                "device_idx": int(device_idx),
                "allocated_mib": round(torch.cuda.memory_allocated(device_idx) / (1024 ** 2), 2),
                "reserved_mib": round(torch.cuda.memory_reserved(device_idx) / (1024 ** 2), 2),
                "max_allocated_mib": round(torch.cuda.max_memory_allocated(device_idx) / (1024 ** 2), 2),
                "max_reserved_mib": round(torch.cuda.max_memory_reserved(device_idx) / (1024 ** 2), 2),
            }
        except Exception as exc:
            return {"available": True, "error": str(exc)}

    def start_session(self, session: RecordingSession):
        """Start a new recording session."""
        self._current_session = session
        self._session_elapsed_ms = 0
        self._last_draft_ms = 0
        self.vad.reset()

    def end_session(self) -> Optional[RecordingSession]:
        """End the current session.

        Delegates final buffer flush to the VAD layer which gates on
        its internal ``_speech_duration_ms``.  Inference runs synchronously —
        the recording is already stopped, so briefly blocking the event loop
        is acceptable.
        """
        session = self._current_session
        if session is not None:
            seg = self.vad.finalize()
            if seg is not None and seg.duration_ms >= self.config.vad_min_utterance_ms:
                self._flush_speech_segment_sync(seg)
        self._current_session = None
        self._session_elapsed_ms = 0
        self.vad.reset()
        return session

    @staticmethod
    def _slice_audio(
        audio: np.ndarray,
        start_s: float,
        end_s: float,
        sample_rate: int,
    ) -> np.ndarray:
        start_idx = max(0, min(len(audio), int(round(start_s * sample_rate))))
        end_idx = max(start_idx, min(len(audio), int(round(end_s * sample_rate))))
        return np.ascontiguousarray(audio[start_idx:end_idx], dtype=np.float32)

    def _speaker_groups(
        self,
        audio: np.ndarray,
        sample_rate: int,
        diarized_segments: list[DiarizationSegment],
    ) -> list[tuple[str, np.ndarray, int]]:
        """Group diarized slices by speaker label and concatenate their audio."""
        if not diarized_segments:
            return [("speaker-0", np.ascontiguousarray(audio, dtype=np.float32), len(audio))]

        chunks_by_speaker: dict[str, list[np.ndarray]] = {}
        lengths_by_speaker: dict[str, int] = {}
        speaker_order: list[str] = []

        for idx, diarized in enumerate(diarized_segments):
            speaker = diarized.speaker or f"speaker-{idx}"
            chunk = self._slice_audio(audio, diarized.start, diarized.end, sample_rate)
            if chunk.size == 0:
                continue
            if speaker not in chunks_by_speaker:
                chunks_by_speaker[speaker] = []
                lengths_by_speaker[speaker] = 0
                speaker_order.append(speaker)
            chunks_by_speaker[speaker].append(chunk)
            lengths_by_speaker[speaker] += int(chunk.size)

        if not speaker_order:
            return [("speaker-0", np.ascontiguousarray(audio, dtype=np.float32), len(audio))]

        return [
            (
                speaker,
                np.ascontiguousarray(np.concatenate(chunks_by_speaker[speaker]), dtype=np.float32),
                lengths_by_speaker[speaker],
            )
            for speaker in speaker_order
        ]

    # ---- inference (thread-safe, no callbacks) -------------------------

    def _infer_utterance(
        self,
        audio: np.ndarray,
        language_hint: str | None,
        sample_rate: int,
        session_id: str,
        started_ms: int,
        ended_ms: int,
    ) -> tuple[
        tuple[Utterance, list[SpeakerSegment], Optional[SpeakerSegment]],
        list[dict[str, Any]],
    ]:
        """Run ASR + diarization + embedding synchronously.  Thread-safe — no
        callbacks are emitted from this method; errors are collected and
        returned so callers can emit them on the event loop afterwards.

        ``session_id`` is snapshot by the caller on the event loop so
        we never read ``self._current_session`` from a worker thread."""
        errors: list[dict[str, Any]] = []
        processing_key = f"{session_id}:{self.source}:{started_ms}-{ended_ms}"
        duration_ms = max(0, ended_ms - started_ms)
        duration_s = (len(audio) / sample_rate) if sample_rate > 0 else 0.0

        def _info(message: str, *args: Any) -> None:
            log.info(message, *args)
            uvicorn_log.info(message, *args)

        def _error(message: str, *args: Any) -> None:
            log.error(message, *args)
            uvicorn_log.error(message, *args)

        cuda_before = self._cuda_memory_snapshot()
        _info(
            "whisper transcription started key=%s model=%s samples=%d duration_ms=%d duration_s=%.3f sample_rate=%d cuda=%s",
            processing_key,
            getattr(self.asr, "model_id", "?"),
            int(len(audio)),
            int(duration_ms),
            float(duration_s),
            int(sample_rate),
            cuda_before,
        )
        asr_t0 = time.perf_counter()
        try:
            if hasattr(self.asr, "blocklist_enabled"):
                self.asr.blocklist_enabled = self.config.blocklist_enabled
            if hasattr(self.asr, "no_speech_threshold"):
                self.asr.no_speech_threshold = self.config.asr_no_speech_threshold
                self.asr.compression_ratio_threshold = (
                    self.config.asr_compression_ratio_threshold
                )
                self.asr.repetition_penalty = self.config.asr_repetition_penalty
                self.asr.no_repeat_ngram_size = self.config.asr_no_repeat_ngram_size
            utterance = self.asr.transcribe(audio, language_hint)
        except Exception as exc:
            cuda_after_error = self._cuda_memory_snapshot()
            log.exception(
                "whisper transcription failed key=%s cuda=%s",
                processing_key,
                cuda_after_error,
            )
            _error(
                "whisper transcription failed key=%s cuda=%s error=%s",
                processing_key,
                cuda_after_error,
                exc,
            )
            errors.append({"code": "ASR_FAILURE", "component": "asr", "message": str(exc)})
            utterance = Utterance(transcript="", language=language_hint, confidence=0.0)
        asr_ms = (time.perf_counter() - asr_t0) * 1000.0
        cuda_after = self._cuda_memory_snapshot()
        _info(
            "whisper transcription finished key=%s model=%s utterance_id=%s transcript_chars=%d language=%s confidence=%.3f asr_ms=%.2f cuda=%s",
            processing_key,
            getattr(self.asr, "model_id", "?"),
            utterance.id,
            len(utterance.transcript or ""),
            utterance.language,
            float(utterance.confidence or 0.0),
            float(asr_ms),
            cuda_after,
        )
        if not utterance.transcript.strip():
            return (utterance, [], None), errors

        diarized_segments: list[DiarizationSegment] = []
        _info(
            "diarization started key=%s samples=%d duration_ms=%d cuda=%s",
            processing_key,
            int(len(audio)),
            int(duration_ms),
            self._cuda_memory_snapshot(),
        )
        diar_t0 = time.perf_counter()
        try:
            diarized_segments = self.diarization.segment(audio)
            diar_ms = (time.perf_counter() - diar_t0) * 1000.0
            _info(
                "diarization finished key=%s segments=%d diarization_ms=%.2f cuda=%s",
                processing_key,
                len(diarized_segments),
                float(diar_ms),
                self._cuda_memory_snapshot(),
            )
        except Exception as exc:
            diar_ms = (time.perf_counter() - diar_t0) * 1000.0
            log.exception("diarization failed; continuing with full-utterance embedding")
            _error(
                "diarization failed key=%s diarization_ms=%.2f cuda=%s error=%s",
                processing_key,
                float(diar_ms),
                self._cuda_memory_snapshot(),
                exc,
            )
            errors.append({"code": "DIARIZATION_FAILURE", "component": "diarization", "message": str(exc)})

        group_t0 = time.perf_counter()
        speaker_groups = self._speaker_groups(audio, sample_rate, diarized_segments)
        group_ms = (time.perf_counter() - group_t0) * 1000.0
        _info(
            "speaker grouping finished key=%s groups=%d grouping_ms=%.2f",
            processing_key,
            len(speaker_groups),
            float(group_ms),
        )

        built_segments: list[tuple[SpeakerSegment, int]] = []
        for group_idx, (_speaker, speaker_audio, sample_count) in enumerate(speaker_groups):
            emb_duration_s = (sample_count / sample_rate) if sample_rate > 0 else 0.0
            _info(
                "embedding started key=%s group_idx=%d speaker=%s samples=%d duration_s=%.3f cuda=%s",
                processing_key,
                int(group_idx),
                _speaker,
                int(sample_count),
                float(emb_duration_s),
                self._cuda_memory_snapshot(),
            )
            emb_t0 = time.perf_counter()
            try:
                embedding = self.embedding.embed(speaker_audio)
            except Exception as exc:
                emb_ms = (time.perf_counter() - emb_t0) * 1000.0
                log.exception("embedding failed for speaker group; skipping segment")
                _error(
                    "embedding failed key=%s group_idx=%d speaker=%s samples=%d embedding_ms=%.2f cuda=%s error=%s",
                    processing_key,
                    int(group_idx),
                    _speaker,
                    int(sample_count),
                    float(emb_ms),
                    self._cuda_memory_snapshot(),
                    exc,
                )
                errors.append({"code": "EMBEDDING_FAILURE", "component": "embedding", "message": str(exc)})
                continue
            emb_ms = (time.perf_counter() - emb_t0) * 1000.0
            emb_dim = int(getattr(embedding, "shape", [0])[-1]) if getattr(embedding, "shape", None) else 0
            _info(
                "embedding finished key=%s group_idx=%d speaker=%s samples=%d embedding_dim=%d embedding_ms=%.2f cuda=%s",
                processing_key,
                int(group_idx),
                _speaker,
                int(sample_count),
                int(emb_dim),
                float(emb_ms),
                self._cuda_memory_snapshot(),
            )
            built_segments.append(
                (
                    SpeakerSegment(
                        session_id=session_id,
                        embedding=embedding,
                        source=self.source,
                    ),
                    sample_count,
                )
            )

        if not built_segments:
            primary = None
            speakers: list[SpeakerSegment] = []
        else:
            primary = max(built_segments, key=lambda item: item[1])[0]
            speakers = [seg for seg, _ in built_segments]

        return (utterance, speakers, primary), errors

    # ---- flush helpers -------------------------------------------------

    def _attach_and_emit(
        self,
        utterance: Utterance,
        speaker_segments: list[SpeakerSegment],
        primary_segment: Optional[SpeakerSegment],
        audio: np.ndarray,
        started_ms: int,
        ended_ms: int,
        sample_rate: int,
    ) -> None:
        """Attach session metadata to the utterance and emit callbacks."""
        utterance.session_id = self._current_session.id
        utterance.started_ms = started_ms
        utterance.ended_ms = ended_ms
        utterance.source = self.source
        if primary_segment is not None:
            utterance.speaker_segment_id = primary_segment.id
            utterance.speaker_contact_id = primary_segment.contact_id
        for speaker_segment in speaker_segments:
            self._emit("speaker_segment", speaker_segment)
        self._emit("utterance", utterance)

        if self.has_listeners("debug:audio"):
            self._emit(
                "debug:audio",
                {
                    "audio": audio,
                    "started_ms": started_ms,
                    "ended_ms": ended_ms,
                    "sample_rate": sample_rate,
                    "transcript": utterance.transcript,
                    "language": utterance.language,
                    "confidence": utterance.confidence,
                    "source": self.source,
                    "speaker_segments": [
                        {
                            "id": seg.id,
                            "speaker": getattr(seg, "speaker", ""),
                            "contact_id": seg.contact_id,
                            "diarization_model_id": getattr(seg, "diarization_model_id", ""),
                        }
                        for seg in speaker_segments
                    ],
                },
            )

    async def _flush_speech_segment(self, seg: SpeechSegment) -> None:
        """Async flush — inference offloaded to thread pool."""
        if not self._current_session:
            return

        loop = asyncio.get_running_loop()
        (utterance, speaker_segments, primary_segment), errors = (
            await loop.run_in_executor(
                _inference_pool,
                self._infer_utterance,
                seg.audio,
                self._current_session.language_hint,
                seg.sample_rate,
                self._current_session.id,
                seg.started_ms,
                seg.ended_ms,
            )
        )
        for err_data in errors:
            err_data["ms"] = seg.started_ms
            self._emit("error", err_data)
        if not utterance.transcript.strip():
            return
        self._attach_and_emit(
            utterance, speaker_segments, primary_segment,
            seg.audio, seg.started_ms, seg.ended_ms, seg.sample_rate,
        )

    def _flush_speech_segment_sync(self, seg: SpeechSegment) -> None:
        """Synchronous flush — runs on the calling thread for end_session."""
        if not self._current_session:
            return

        (utterance, speaker_segments, primary_segment), errors = (
            self._infer_utterance(
                seg.audio,
                self._current_session.language_hint,
                seg.sample_rate,
                self._current_session.id,
                seg.started_ms,
                seg.ended_ms,
            )
        )
        for err_data in errors:
            err_data["ms"] = seg.started_ms
            self._emit("error", err_data)
        if not utterance.transcript.strip():
            return
        self._attach_and_emit(
            utterance, speaker_segments, primary_segment,
            seg.audio, seg.started_ms, seg.ended_ms, seg.sample_rate,
        )

    # ---- session lifecycle & streaming ---------------------------------

    async def process_chunk(self, audio: np.ndarray, sample_rate: int = 16000):
        """Process an audio chunk through the pipeline.

        The VAD layer owns all audio buffering, hysteresis, and padding.
        When a speech span ends (or ``max_utterance_ms`` is exceeded) it
        returns a complete ``SpeechSegment`` ready for inference.  The
        coordinator only gates by ``vad_min_utterance_ms`` and dispatches
        to ASR / diarization / embedding.
        """
        if not self._current_session:
            raise RuntimeError("No active session")
        if audio.size == 0:
            return

        audio = np.ascontiguousarray(audio, dtype=np.float32)
        duration_ms = self._chunk_duration(audio, sample_rate)
        started_ms = self._session_elapsed_ms
        ended_ms = started_ms + duration_ms
        self._session_elapsed_ms = ended_ms

        result = self.vad.process(audio, sample_rate)
        if result is None:
            self._maybe_submit_draft(sample_rate)
            return

        # VAD returned a complete utterance.
        if result.duration_ms < self.config.vad_min_utterance_ms:
            log.debug(
                "discarding sub-min utterance: %d ms < %d ms",
                result.duration_ms,
                self.config.vad_min_utterance_ms,
            )
            return

        await self._flush_speech_segment(result)

    @staticmethod
    def _chunk_duration(audio: np.ndarray, sample_rate: int) -> int:
        if sample_rate <= 0:
            return 0
        return max(1, int(round((len(audio) / sample_rate) * 1000)))

    def _maybe_submit_draft(self, sample_rate: int) -> None:
        """Submit current speech buffer for draft ASR if interval elapsed."""
        if not self.config.draft_enabled:
            return
        if self._session_elapsed_ms - self._last_draft_ms < self.config.draft_interval_ms:
            return
        snap = self.vad.snapshot()
        if snap is None or snap.audio.size == 0:
            return

        self._last_draft_ms = self._session_elapsed_ms

        if self._draft_asr is None:
            self._draft_asr = self._build_draft_provider()

        session_id = self._current_session.id
        started_ms = snap.started_ms

        def _run_draft() -> None:
            try:
                utterance = self._draft_asr.transcribe(snap.audio, None)
                if not utterance.transcript.strip():
                    return
                self._emit(
                    "draft_utterance",
                    {
                        "session_id": session_id,
                        "started_ms": started_ms,
                        "transcript": utterance.transcript,
                        "language": utterance.language,
                        "confidence": utterance.confidence,
                    },
                )
            except Exception:
                log.exception("draft ASR failed")

        loop = asyncio.get_running_loop()
        loop.run_in_executor(_draft_pool, _run_draft)

    def _build_draft_provider(self) -> Any:
        """Lazy-create a lightweight ASR provider for draft streaming."""
        from ..providers.asr import WhisperASRProvider
        return WhisperASRProvider(
            model_id="small",
            beam_size=1,
            # Inherit quality gates from config.
            no_speech_threshold=self.config.asr_no_speech_threshold,
            compression_ratio_threshold=self.config.asr_compression_ratio_threshold,
            repetition_penalty=self.config.asr_repetition_penalty,
            no_repeat_ngram_size=self.config.asr_no_repeat_ngram_size,
        )
