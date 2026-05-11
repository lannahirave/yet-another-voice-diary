from __future__ import annotations

"""Pipeline coordinator orchestrating all components."""

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Protocol

import numpy as np

from ..config import PipelineConfig
from ..models import RecordingSession, SpeakerSegment, Utterance
from ..providers.base import ASRProvider, DiarizationProvider, EmbeddingProvider
from ..providers.diarization import DiarizationSegment
from ..providers.vad import SpeechSegment

# Dedicated thread pool for ML inference keeps heavy model calls (ASR,
# diarization, embedding) from competing with HTTP handler threads in FastAPI's
# default pool, and keeps the event loop responsive during transcription.
#
# max_workers=1 serialises all inference across connections, which also avoids
# thread-safety issues with shared provider singletons (CTranslate2,
# SpeechBrain, PyAnnote are not designed for concurrent calls).
_inference_pool = ThreadPoolExecutor(max_workers=1)
_draft_pool = ThreadPoolExecutor(max_workers=1)


log = logging.getLogger(__name__)
uvicorn_log = logging.getLogger("uvicorn.error")


class VADLike(Protocol):
    def reset(self) -> None: ...

    def process(self, audio: np.ndarray, sample_rate: int) -> Any: ...

    def snapshot(self) -> SpeechSegment | None: ...

    def finalize(self) -> SpeechSegment | None: ...


@dataclass
class TurnSlice:
    """A non-overlapping diarized speaker turn ready for per-turn ASR."""

    speaker_label: str
    start_s: float
    end_s: float
    started_ms: int
    ended_ms: int
    audio: np.ndarray


@dataclass
class EmittedUtterance:
    """A final utterance plus the audio used to produce it."""

    utterance: Utterance
    audio: np.ndarray
    speaker_label: str


@dataclass
class InferenceBatch:
    """Inference result for a single VAD flush."""

    utterances: list[EmittedUtterance]
    speaker_segments: list[SpeakerSegment]


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

        self._current_session: RecordingSession | None = None
        self._callbacks: dict[str, list[Callable]] = {
            "utterance": [],
            "speaker_segment": [],
            "error": [],
            "debug:audio": [],
            "debug:vad": [],
        }
        self._pending_tasks: set[asyncio.Task] = set()  # type: ignore[type-arg]
        self._session_elapsed_ms = 0
        self._draft_asr: Any = None  # lightweight ASR for draft streaming
        self._last_draft_ms: int = 0
        self._chunk_count: int = 0  # for periodic GC

    def on(self, event: str, callback: Callable) -> None:
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

    def _emit(self, event: str, data: Any) -> None:
        """Emit event to all registered callbacks."""
        for callback in self._callbacks.get(event, []):
            try:
                if asyncio.iscoroutinefunction(callback):
                    task = asyncio.create_task(callback(data))
                    self._pending_tasks.add(task)
                    task.add_done_callback(self._pending_tasks.discard)
                else:
                    callback(data)
            except Exception as exc:
                if event != "error":
                    self._emit("error", {"code": "CALLBACK_FAILURE", "message": str(exc)})

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

    def start_session(self, session: RecordingSession) -> None:
        """Start a new recording session."""
        self._current_session = session
        self._session_elapsed_ms = 0
        self._last_draft_ms = 0
        self._chunk_count = 0
        self.vad.reset()

    def end_session(self) -> RecordingSession | None:
        """End the current session.

        Delegates final buffer flush to the VAD layer which gates on its internal
        ``_speech_duration_ms``. Inference runs synchronously because the recording
        is already stopped, so briefly blocking the event loop is acceptable.
        """
        session = self._current_session
        if session is not None:
            seg = self.vad.finalize()
            if seg is not None and seg.duration_ms >= self.config.vad_min_utterance_ms:
                self._flush_speech_segment_sync(seg)
        self._current_session = None
        self._session_elapsed_ms = 0
        self._chunk_count = 0
        if self._draft_asr is not None:
            try:
                if hasattr(self._draft_asr, "unload"):
                    self._draft_asr.unload()
            except Exception:
                log.exception("failed to unload draft ASR")
            self._draft_asr = None
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

    @staticmethod
    def _clip_diarized_segments(
        diarized_segments: list[DiarizationSegment],
        total_duration_s: float,
    ) -> list[tuple[int, float, float, str, float]]:
        clipped: list[tuple[int, float, float, str, float]] = []
        for idx, diarized in enumerate(diarized_segments):
            start_s = max(0.0, min(total_duration_s, float(diarized.start)))
            end_s = max(0.0, min(total_duration_s, float(diarized.end)))
            if end_s <= start_s:
                continue
            speaker_label = diarized.speaker or f"speaker-{idx}"
            clipped.append((idx, start_s, end_s, speaker_label, end_s - start_s))
        return clipped

    def _make_turn_slice(
        self,
        audio: np.ndarray,
        sample_rate: int,
        base_started_ms: int,
        speaker_label: str,
        start_s: float,
        end_s: float,
    ) -> TurnSlice | None:
        turn_audio = self._slice_audio(audio, start_s, end_s, sample_rate)
        if turn_audio.size == 0:
            return None
        started_ms = base_started_ms + int(round(start_s * 1000.0))
        ended_ms = base_started_ms + int(round(end_s * 1000.0))
        if ended_ms <= started_ms:
            ended_ms = started_ms + max(
                1,
                int(round((turn_audio.size / sample_rate) * 1000.0)) if sample_rate > 0 else 1,
            )
        return TurnSlice(
            speaker_label=speaker_label,
            start_s=float(start_s),
            end_s=float(end_s),
            started_ms=int(started_ms),
            ended_ms=int(ended_ms),
            audio=turn_audio,
        )

    def _build_turn_slices(
        self,
        audio: np.ndarray,
        sample_rate: int,
        started_ms: int,
        diarized_segments: list[DiarizationSegment],
    ) -> list[TurnSlice]:
        """Normalize diarization output into non-overlapping speaker turns."""
        total_duration_s = (len(audio) / sample_rate) if sample_rate > 0 else 0.0
        if total_duration_s <= 0.0:
            return []

        clipped = self._clip_diarized_segments(diarized_segments, total_duration_s)
        if not clipped:
            fallback = self._make_turn_slice(
                audio, sample_rate, started_ms, "speaker-0", 0.0, total_duration_s
            )
            return [fallback] if fallback is not None else []

        boundaries = sorted(
            {
                0.0,
                total_duration_s,
                *[start_s for _, start_s, _, _, _ in clipped],
                *[end_s for _, _, end_s, _, _ in clipped],
            }
        )
        atomic: list[tuple[str, float, float]] = []
        for left, right in zip(boundaries, boundaries[1:]):
            if right <= left:
                continue
            active = [
                segment
                for segment in clipped
                if segment[1] < right and segment[2] > left
            ]
            if not active:
                continue
            chosen = min(
                active,
                key=lambda item: (
                    -item[4],
                    item[1],
                    item[0],
                ),
            )
            atomic.append((chosen[3], left, right))

        if not atomic:
            fallback = self._make_turn_slice(
                audio, sample_rate, started_ms, "speaker-0", 0.0, total_duration_s
            )
            return [fallback] if fallback is not None else []

        merged: list[tuple[str, float, float]] = []
        eps = 1e-6
        for speaker_label, left, right in atomic:
            if merged and merged[-1][0] == speaker_label and abs(merged[-1][2] - left) <= eps:
                merged[-1] = (speaker_label, merged[-1][1], right)
            else:
                merged.append((speaker_label, left, right))

        turns: list[TurnSlice] = []
        for speaker_label, left, right in merged:
            turn = self._make_turn_slice(
                audio,
                sample_rate,
                started_ms,
                speaker_label,
                left,
                right,
            )
            if turn is not None:
                turns.append(turn)
        if turns:
            return turns

        fallback = self._make_turn_slice(
            audio, sample_rate, started_ms, "speaker-0", 0.0, total_duration_s
        )
        return [fallback] if fallback is not None else []

    @staticmethod
    def _speaker_groups(turns: list[TurnSlice]) -> list[tuple[str, np.ndarray, int]]:
        """Group turn audio by speaker label and concatenate per speaker."""
        if not turns:
            return []

        chunks_by_speaker: dict[str, list[np.ndarray]] = {}
        lengths_by_speaker: dict[str, int] = {}
        speaker_order: list[str] = []
        for idx, turn in enumerate(turns):
            speaker_label = turn.speaker_label or f"speaker-{idx}"
            if turn.audio.size == 0:
                continue
            if speaker_label not in chunks_by_speaker:
                chunks_by_speaker[speaker_label] = []
                lengths_by_speaker[speaker_label] = 0
                speaker_order.append(speaker_label)
            chunks_by_speaker[speaker_label].append(turn.audio)
            lengths_by_speaker[speaker_label] += int(turn.audio.size)

        return [
            (
                speaker_label,
                np.ascontiguousarray(np.concatenate(chunks_by_speaker[speaker_label]), dtype=np.float32),
                lengths_by_speaker[speaker_label],
            )
            for speaker_label in speaker_order
        ]

    # ---- inference (thread-safe, no callbacks) -------------------------

    def _apply_language_policy(self, audio: np.ndarray, utterance: Utterance) -> Utterance:
        """Apply language allowlist policy. May re-transcribe with forced languages."""
        if not self.config.language_allowlist_enabled:
            return utterance
        allowed = [x.strip() for x in self.config.language_allowlist.split(",") if x.strip()]
        if not allowed:
            return utterance
        threshold = self.config.language_confidence_threshold

        if (
            utterance.confidence < threshold
            or (utterance.language and utterance.language not in allowed)
        ):
            candidates = [utterance]
            for lang in allowed:
                try:
                    cand = self.asr.transcribe(audio, lang)
                    candidates.append(cand)
                except Exception:
                    log.exception("language retry failed for lang=%s", lang)
            utterance = max(candidates, key=lambda item: item.confidence)
        return utterance

    def _infer_utterance(
        self,
        audio: np.ndarray,
        language_hint: str | None,
        sample_rate: int,
        session_id: str,
        started_ms: int,
        ended_ms: int,
    ) -> tuple[InferenceBatch, list[dict[str, Any]]]:
        """Run diarization + grouped embedding + per-turn ASR synchronously.

        Thread-safe: callbacks are not emitted from this method; errors are
        collected and returned so callers can emit them on the event loop later.
        ``session_id`` is snapped by the caller so we never read
        ``self._current_session`` from a worker thread.
        """
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

        diarized_segments: list[DiarizationSegment] = []
        if self.source == "mic" and self.config.mic_self_contact_id:
            if duration_s > 0.0:
                diarized_segments = [
                    DiarizationSegment(start=0.0, end=duration_s, speaker="speaker-self")
                ]
        else:
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
                log.exception("diarization failed; continuing with pseudo-turn fallback")
                _error(
                    "diarization failed key=%s diarization_ms=%.2f cuda=%s error=%s",
                    processing_key,
                    float(diar_ms),
                    self._cuda_memory_snapshot(),
                    exc,
                )
                errors.append(
                    {"code": "DIARIZATION_FAILURE", "component": "diarization", "message": str(exc)}
                )

        turn_t0 = time.perf_counter()
        turns = self._build_turn_slices(audio, sample_rate, started_ms, diarized_segments)
        turn_ms = (time.perf_counter() - turn_t0) * 1000.0
        _info(
            "turn normalization finished key=%s turns=%d turn_ms=%.2f",
            processing_key,
            len(turns),
            float(turn_ms),
        )

        group_t0 = time.perf_counter()
        speaker_groups = self._speaker_groups(turns)
        group_ms = (time.perf_counter() - group_t0) * 1000.0
        _info(
            "speaker grouping finished key=%s groups=%d grouping_ms=%.2f",
            processing_key,
            len(speaker_groups),
            float(group_ms),
        )

        if hasattr(self.asr, "blocklist_enabled"):
            self.asr.blocklist_enabled = self.config.blocklist_enabled
        if hasattr(self.asr, "no_speech_threshold"):
            self.asr.no_speech_threshold = self.config.asr_no_speech_threshold
            self.asr.compression_ratio_threshold = self.config.asr_compression_ratio_threshold
            self.asr.repetition_penalty = self.config.asr_repetition_penalty
            self.asr.no_repeat_ngram_size = self.config.asr_no_repeat_ngram_size

        built_segments: dict[str, SpeakerSegment] = {}
        for group_idx, (speaker_label, speaker_audio, sample_count) in enumerate(speaker_groups):
            emb_duration_s = (sample_count / sample_rate) if sample_rate > 0 else 0.0
            _info(
                "embedding started key=%s group_idx=%d speaker=%s samples=%d duration_s=%.3f cuda=%s",
                processing_key,
                int(group_idx),
                speaker_label,
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
                    speaker_label,
                    int(sample_count),
                    float(emb_ms),
                    self._cuda_memory_snapshot(),
                    exc,
                )
                errors.append(
                    {"code": "EMBEDDING_FAILURE", "component": "embedding", "message": str(exc)}
                )
                continue
            emb_ms = (time.perf_counter() - emb_t0) * 1000.0
            emb_dim = int(getattr(embedding, "shape", [0])[-1]) if getattr(embedding, "shape", None) else 0
            _info(
                "embedding finished key=%s group_idx=%d speaker=%s samples=%d embedding_dim=%d embedding_ms=%.2f cuda=%s",
                processing_key,
                int(group_idx),
                speaker_label,
                int(sample_count),
                int(emb_dim),
                float(emb_ms),
                self._cuda_memory_snapshot(),
            )
            speaker_segment = SpeakerSegment(
                session_id=session_id,
                embedding=embedding,
                source=self.source,
                contact_id=self.config.mic_self_contact_id if self.source == "mic" and self.config.mic_self_contact_id else None,
                status="identified" if self.source == "mic" and self.config.mic_self_contact_id else "unknown",
            )
            setattr(speaker_segment, "speaker", speaker_label)
            built_segments[speaker_label] = speaker_segment

        emitted: list[EmittedUtterance] = []
        for turn_idx, turn in enumerate(turns):
            cuda_before = self._cuda_memory_snapshot()
            _info(
                "whisper transcription started key=%s turn_idx=%d speaker=%s model=%s samples=%d duration_ms=%d duration_s=%.3f sample_rate=%d cuda=%s",
                processing_key,
                int(turn_idx),
                turn.speaker_label,
                getattr(self.asr, "model_id", "?"),
                int(len(turn.audio)),
                int(turn.ended_ms - turn.started_ms),
                float((len(turn.audio) / sample_rate) if sample_rate > 0 else 0.0),
                int(sample_rate),
                cuda_before,
            )
            asr_t0 = time.perf_counter()
            try:
                utterance = self.asr.transcribe(turn.audio, language_hint)
            except Exception as exc:
                cuda_after_error = self._cuda_memory_snapshot()
                log.exception(
                    "whisper transcription failed key=%s turn_idx=%d speaker=%s cuda=%s",
                    processing_key,
                    int(turn_idx),
                    turn.speaker_label,
                    cuda_after_error,
                )
                _error(
                    "whisper transcription failed key=%s turn_idx=%d speaker=%s cuda=%s error=%s",
                    processing_key,
                    int(turn_idx),
                    turn.speaker_label,
                    cuda_after_error,
                    exc,
                )
                errors.append({"code": "ASR_FAILURE", "component": "asr", "message": str(exc)})
                continue

            asr_ms = (time.perf_counter() - asr_t0) * 1000.0
            utterance = self._apply_language_policy(turn.audio, utterance)
            _info(
                "whisper transcription finished key=%s turn_idx=%d speaker=%s model=%s utterance_id=%s transcript_chars=%d language=%s confidence=%.3f asr_ms=%.2f cuda=%s",
                processing_key,
                int(turn_idx),
                turn.speaker_label,
                getattr(self.asr, "model_id", "?"),
                utterance.id,
                len(utterance.transcript or ""),
                utterance.language,
                float(utterance.confidence or 0.0),
                float(asr_ms),
                self._cuda_memory_snapshot(),
            )
            if not utterance.transcript.strip():
                continue

            utterance.session_id = session_id
            utterance.started_ms = turn.started_ms
            utterance.ended_ms = turn.ended_ms
            utterance.source = self.source
            speaker_segment = built_segments.get(turn.speaker_label)
            if speaker_segment is not None:
                utterance.speaker_segment_id = speaker_segment.id
                utterance.speaker_contact_id = speaker_segment.contact_id
            emitted.append(
                EmittedUtterance(
                    utterance=utterance,
                    audio=turn.audio,
                    speaker_label=turn.speaker_label,
                )
            )

        emitted.sort(
            key=lambda item: (
                item.utterance.started_ms,
                item.utterance.ended_ms,
                item.utterance.id,
            )
        )
        used_labels: list[str] = []
        for item in emitted:
            if item.speaker_label in built_segments and item.speaker_label not in used_labels:
                used_labels.append(item.speaker_label)

        return (
            InferenceBatch(
                utterances=emitted,
                speaker_segments=[built_segments[label] for label in used_labels],
            ),
            errors,
        )

    # ---- flush helpers -------------------------------------------------

    def _attach_and_emit(
        self,
        batch: InferenceBatch,
        sample_rate: int,
    ) -> None:
        """Emit speaker segments first, then the utterances that reference them."""
        segment_by_id = {segment.id: segment for segment in batch.speaker_segments}
        for speaker_segment in batch.speaker_segments:
            self._emit("speaker_segment", speaker_segment)

        for item in batch.utterances:
            utterance = item.utterance
            self._emit("utterance", utterance)
            if not self.has_listeners("debug:audio"):
                continue
            debug_segments: list[SpeakerSegment] = []
            if utterance.speaker_segment_id and utterance.speaker_segment_id in segment_by_id:
                debug_segments = [segment_by_id[utterance.speaker_segment_id]]
            self._emit(
                "debug:audio",
                {
                    "utt_id": utterance.id,
                    "audio": item.audio,
                    "started_ms": utterance.started_ms,
                    "ended_ms": utterance.ended_ms,
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
                        for seg in debug_segments
                    ],
                },
            )

    async def _flush_speech_segment(self, seg: SpeechSegment) -> None:
        """Async flush: inference is offloaded to the shared thread pool."""
        if not self._current_session:
            return

        loop = asyncio.get_running_loop()
        batch, errors = await loop.run_in_executor(
            _inference_pool,
            self._infer_utterance,
            seg.audio,
            self._current_session.language_hint,
            seg.sample_rate,
            self._current_session.id,
            seg.started_ms,
            seg.ended_ms,
        )
        for err_data in errors:
            err_data["ms"] = seg.started_ms
            self._emit("error", err_data)
        if not batch.utterances:
            return
        self._attach_and_emit(batch, seg.sample_rate)

    def _flush_speech_segment_sync(self, seg: SpeechSegment) -> None:
        """Synchronous flush: runs on the calling thread for end_session."""
        if not self._current_session:
            return

        batch, errors = self._infer_utterance(
            seg.audio,
            self._current_session.language_hint,
            seg.sample_rate,
            self._current_session.id,
            seg.started_ms,
            seg.ended_ms,
        )
        for err_data in errors:
            err_data["ms"] = seg.started_ms
            self._emit("error", err_data)
        if not batch.utterances:
            return
        self._attach_and_emit(batch, seg.sample_rate)

    # ---- session lifecycle & streaming ---------------------------------

    async def process_chunk(self, audio: np.ndarray, sample_rate: int = 16000) -> None:
        """Process an audio chunk through the pipeline.

        The VAD layer owns all audio buffering, hysteresis, and padding. When a
        speech span ends (or ``max_utterance_ms`` is exceeded) it returns a
        complete ``SpeechSegment`` ready for inference. The coordinator only
        gates by ``vad_min_utterance_ms`` and dispatches to diarization / ASR /
        embedding.
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

        # Periodic GC returns freed numpy memory to the OS every ~5 s.
        self._chunk_count += 1
        if self._chunk_count % 50 == 0:
            import gc

            gc.collect()

        if result is None:
            self._maybe_submit_draft(sample_rate)
            return

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
            no_speech_threshold=self.config.asr_no_speech_threshold,
            compression_ratio_threshold=self.config.asr_compression_ratio_threshold,
            repetition_penalty=self.config.asr_repetition_penalty,
            no_repeat_ngram_size=self.config.asr_no_repeat_ngram_size,
        )
