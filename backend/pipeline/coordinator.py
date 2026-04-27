"""Pipeline coordinator orchestrating all components."""
import asyncio
import logging
from typing import Any, Callable, Optional, Protocol

import numpy as np

from ..config import PipelineConfig
from ..models import RecordingSession, SpeakerSegment
from ..providers.base import ASRProvider, DiarizationProvider, EmbeddingProvider
from ..providers.diarization import DiarizationSegment
from .vad import VADProcessor


log = logging.getLogger(__name__)


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
        self.vad = vad_processor or VADProcessor(
            threshold=config.vad_threshold,
            min_silence_ms=config.vad_min_silence_ms,
            speech_pad_ms=config.vad_speech_pad_ms,
        )
        self.source = source

        self._current_session: Optional[RecordingSession] = None
        self._callbacks: dict[str, list[Callable]] = {
            "utterance": [],
            "speaker_segment": [],
            "error": [],
        }
        self._pending_tasks: set[asyncio.Task] = set()  # type: ignore
        self._session_elapsed_ms = 0
        self._buffered_audio: list[np.ndarray] = []
        self._buffer_started_ms: Optional[int] = None
        self._buffer_ended_ms = 0
        self._buffer_sample_rate: Optional[int] = None
        self._in_speech: bool = False
        self._buffered_speech_ms: int = 0

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

    def _emit(self, event: str, data: Any):
        """Emit event to all registered callbacks."""
        for callback in self._callbacks.get(event, []):
            try:
                if asyncio.iscoroutinefunction(callback):
                    task = asyncio.create_task(callback(data))
                    # Store reference to prevent garbage collection
                    self._pending_tasks.add(task)
                    task.add_done_callback(self._pending_tasks.discard)
                else:
                    callback(data)
            except Exception as e:
                self._emit("error", e)

    def start_session(self, session: RecordingSession):
        """Start a new recording session."""
        self._current_session = session
        self._session_elapsed_ms = 0
        self._in_speech = False
        self._reset_buffer()
        self.vad.reset()

    def end_session(self) -> Optional[RecordingSession]:
        """End the current session.

        Only flushes the buffer when it crosses ``vad_min_utterance_ms`` —
        same floor as the falling-edge path. A 100-300 ms tail at session
        stop is almost always a click, key release or breath, and pushing
        it through diarization + embedding produces a degenerate segment
        that pollutes the unknown queue and the voice-profile gallery.
        """
        session = self._current_session
        if (
            session is not None
            and self._buffered_speech_ms >= self.config.vad_min_utterance_ms
        ):
            self._flush_buffered_utterance()
        self._current_session = None
        self._session_elapsed_ms = 0
        self._in_speech = False
        self._reset_buffer()
        self.vad.reset()
        return session

    @staticmethod
    def _chunk_duration_ms(audio: np.ndarray, sample_rate: int) -> int:
        if sample_rate <= 0:
            return 0
        return max(1, int(round((len(audio) / sample_rate) * 1000)))

    def _reset_buffer(self) -> None:
        self._buffered_audio = []
        self._buffer_started_ms = None
        self._buffer_ended_ms = 0
        self._buffer_sample_rate = None
        self._buffered_speech_ms = 0

    def _buffer_chunk(
        self,
        audio: np.ndarray,
        started_ms: int,
        ended_ms: int,
        sample_rate: int,
    ) -> None:
        if self._buffer_started_ms is None:
            self._buffer_started_ms = started_ms
        if self._buffer_sample_rate is None:
            self._buffer_sample_rate = sample_rate
        self._buffered_audio.append(np.ascontiguousarray(audio, dtype=np.float32))
        self._buffer_ended_ms = ended_ms

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

    def _build_speaker_segments(
        self,
        audio: np.ndarray,
        sample_rate: int,
    ) -> tuple[list[SpeakerSegment], Optional[SpeakerSegment]]:
        diarized_segments: list[DiarizationSegment] = []
        try:
            diarized_segments = self.diarization.segment(audio)
        except Exception as exc:
            log.exception("diarization failed; continuing with full-utterance embedding")
            self._emit("error", exc)
        speaker_groups = self._speaker_groups(audio, sample_rate, diarized_segments)
        session_id = self._current_session.id if self._current_session else ""

        built_segments: list[tuple[SpeakerSegment, int]] = []
        for _speaker, speaker_audio, sample_count in speaker_groups:
            try:
                embedding = self.embedding.embed(speaker_audio)
            except Exception as exc:
                log.exception("embedding failed for speaker group; skipping segment")
                self._emit("error", exc)
                continue
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
            return [], None

        primary_segment = max(built_segments, key=lambda item: item[1])[0]
        return [segment for segment, _ in built_segments], primary_segment

    def _flush_buffered_utterance(self) -> None:
        if not self._current_session or not self._buffered_audio:
            self._reset_buffer()
            return

        audio = np.concatenate(self._buffered_audio)
        utterance = self.asr.transcribe(
            audio,
            language_hint=self._current_session.language_hint,
        )
        if not utterance.transcript.strip():
            self._reset_buffer()
            return

        sample_rate = self._buffer_sample_rate or 16000
        speaker_segments, primary_segment = self._build_speaker_segments(
            audio,
            sample_rate,
        )

        utterance.session_id = self._current_session.id
        utterance.started_ms = self._buffer_started_ms or 0
        utterance.ended_ms = self._buffer_ended_ms
        utterance.source = self.source
        if primary_segment is not None:
            utterance.speaker_segment_id = primary_segment.id
            utterance.speaker_contact_id = primary_segment.contact_id

        for speaker_segment in speaker_segments:
            self._emit("speaker_segment", speaker_segment)
        self._emit("utterance", utterance)
        self._reset_buffer()

    async def process_chunk(self, audio: np.ndarray, sample_rate: int = 16000):
        """Process an audio chunk through the pipeline.

        Endpointing follows the standard streaming-ASR state machine:

        * the VAD (Silero, stateful) provides a *current* speech/silence
          classification per chunk — its own ``min_silence_duration_ms`` and
          ``speech_pad_ms`` already debounce micro-pauses inside speech;
        * the coordinator opens an utterance buffer on the rising edge,
          continues buffering through speech (and the falling-edge chunk so
          Silero's trailing pad is captured), and on the falling edge decides
          whether the buffer is long enough to count as a real utterance
          (``vad_min_utterance_ms``) or should be discarded (cough, click);
        * to bound memory and latency on monologues the buffer is force-flushed
          once it crosses ``vad_max_utterance_ms``, while keeping the speaker
          marked as voiced so the next chunk seamlessly opens the next
          utterance.
        """
        if not self._current_session:
            raise RuntimeError("No active session")
        if audio.size == 0:
            return

        audio = np.ascontiguousarray(audio, dtype=np.float32)
        duration_ms = self._chunk_duration_ms(audio, sample_rate)
        started_ms = self._session_elapsed_ms
        ended_ms = started_ms + duration_ms
        self._session_elapsed_ms = ended_ms

        vad_segment = self.vad.process(audio, sample_rate)
        if vad_segment is None:
            return

        was_in_speech = self._in_speech
        is_speech_now = vad_segment.is_speech

        # Buffer audio that is part of a speech span, including the
        # falling-edge chunk so Silero's trailing speech-pad is preserved.
        if was_in_speech or is_speech_now:
            self._buffer_chunk(audio, started_ms, ended_ms, sample_rate)
            if is_speech_now:
                self._buffered_speech_ms += duration_ms

        # Falling edge: VAD declared end-of-speech. Either emit or discard.
        if was_in_speech and not is_speech_now:
            if self._buffered_speech_ms >= self.config.vad_min_utterance_ms:
                self._flush_buffered_utterance()
            else:
                log.debug(
                    "discarding sub-min utterance: %d ms < %d ms",
                    self._buffered_speech_ms,
                    self.config.vad_min_utterance_ms,
                )
                self._reset_buffer()
            self._in_speech = False
            return

        self._in_speech = is_speech_now

        # Force-flush long monologues to bound memory and ASR latency.
        if (
            self._in_speech
            and self._buffered_speech_ms >= self.config.vad_max_utterance_ms
        ):
            log.info(
                "force-flushing utterance at max length: %d ms",
                self._buffered_speech_ms,
            )
            self._flush_buffered_utterance()
            # Stay voiced — the speaker is still talking.
