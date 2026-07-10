"""Voice Activity Detection provider.

Implements pluggable VAD via a provider pattern matching the existing
ASR / diarization / embedding providers.  The module-level factory
``create_vad_provider`` returns a *manager* (singleton — holds the
loaded model and configuration).  Per-WebSocket-connection state is
obtained via ``manager.create_session()``, which returns a lightweight
``VadSession`` carrying its own LSTM state, frame buffer, hysteresis
counters, preroll ring buffer, and speech audio buffer.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import logging
import math
from pathlib import Path
from typing import Any, Optional

import numpy as np

log = logging.getLogger(__name__)

# Silero requires fixed window sizes — 512 samples for 16 kHz models.
_FRAME_SAMPLES = 512

FIRERED_REPO_ID = "FireRedTeam/FireRedVAD"
FIRERED_REVISION = "7990aaccc6b7aec1e527743bd30201f2c4a03b8c"
FIRERED_ALLOW_PATTERNS = (
    "Stream-VAD/model.pth.tar",
    "Stream-VAD/cmvn.ark",
)
_FIRERED_FRAME_SAMPLES = 400
_FIRERED_HOP_SAMPLES = 160
_FIRERED_FRAME_MS = 10


@dataclass
class VADSegment:
    """Per-chunk VAD classification (debug / degraded-mode only).

    ``is_speech`` reflects the sustained speech/silence state at the end
    of the chunk.  Normal operation returns ``SpeechSegment`` instead —
    this type is emitted only in degraded mode or for debug listeners.
    """

    start_ms: int
    end_ms: int
    is_speech: bool
    preroll_audio: np.ndarray | None = None


@dataclass
class SpeechSegment:
    """A complete utterance ready for inference.

    The VAD layer owns audio buffering end-to-end: when speech ends
    (after hysteresis, post-padding, and internal force-flushing) the
    concatenated padded audio is returned as a ``SpeechSegment``.
    The coordinator gates by min/max duration and dispatches to ASR.
    """

    audio: np.ndarray
    sample_rate: int
    started_ms: int   # session-relative
    ended_ms: int     # session-relative
    duration_ms: int  # total speech time inside the segment


class VADProvider:
    """Abstract VAD provider — holds the loaded model and global config.

    Subclass and override ``_create_session_instance()`` to provide a
    different VAD backend (WebRTC, Picovoice, etc.).
    """

    def __init__(self, model_id: str) -> None:
        self.model_id = model_id
        self._state: str = "UNLOADED"
        self._error: Optional[str] = None

    def load(self) -> None:
        """Load the underlying model into memory."""
        raise NotImplementedError

    def unload(self) -> None:
        """Release the underlying model."""
        raise NotImplementedError

    def create_session(self) -> "VadSession":
        """Return a fresh per-connection session with independent LSTM state."""
        raise NotImplementedError


class SileroVADProvider(VADProvider):
    """Silero VAD with Vexa-style dual-threshold hysteresis.

    Bypasses ``silero_vad.VADIterator`` (which only supports a single
    threshold) and drives the raw model directly to obtain per-frame
    speech probabilities.  A custom state machine applies:

    * **onset**   (default 0.60) — speech starts when prob ≥ onset
    * **offset**  (default 0.45) — speech ends after min_silence_ms of
      sustained sub-offset probability
    * **pre-pad** (default 300 ms) — audio before the onset crossing is
      included via a rolling ring buffer
    * **post-pad** (default 400 ms) — the falling-edge ``is_speech``
      signal is delayed so the coordinator captures trailing audio
    """

    def __init__(
        self,
        model_id: str = "silero",
        *,
        threshold: float = 0.60,
        negative_threshold: float = 0.45,
        min_silence_ms: int = 300,
        speech_pad_pre_ms: int = 300,
        speech_pad_post_ms: int = 400,
        sample_rate: int = 16_000,
    ) -> None:
        super().__init__(model_id)
        self.threshold = threshold
        self.negative_threshold = negative_threshold
        self.min_silence_ms = min_silence_ms
        self.speech_pad_pre_ms = speech_pad_pre_ms
        self.speech_pad_post_ms = speech_pad_post_ms
        self.sample_rate = sample_rate

        self._frame_ms = int(_FRAME_SAMPLES / sample_rate * 1000)  # 32ms
        self._min_silence_frames = max(1, min_silence_ms // self._frame_ms)
        self._post_pad_frames = max(0, speech_pad_post_ms // self._frame_ms)

        self._model: Any = None  # raw Silero ONNX/JIT model

    # -- lifecycle ----------------------------------------------------------

    def load(self) -> None:
        if self._model is not None:
            return
        self._state = "LOADING"
        self._error = None
        try:
            from silero_vad import load_silero_vad  # type: ignore[import-untyped]
        except Exception as exc:
            self._error = f"silero-vad not installed: {exc}"
            self._state = "ERROR"
            log.exception("Silero VAD import failed")
            raise RuntimeError(self._error) from exc

        try:
            self._model = load_silero_vad()
        except Exception as exc:
            self._error = f"Silero VAD model load failed: {exc}"
            self._state = "ERROR"
            log.exception("Silero VAD model load failed")
            raise RuntimeError(self._error) from exc

        self._state = "LOADED"

    def unload(self) -> None:
        self._model = None
        self._state = "UNLOADED"
        self._error = None

    def create_session(self) -> "VadSession":
        """Return a fresh per-connection session."""
        return _SileroVadSession(self)


class VadSession:
    """Per-connection VAD state — compatible with ``VADLike`` protocol.

    Each WebSocket connection gets its own session so the LSTM state,
    frame buffer, hysteresis counters, preroll ring buffer, and speech
    audio buffer are isolated per audio stream.
    """

    max_utterance_ms: int = 0  # set by coordinator after creation

    def reset(self) -> None:
        """Reset between recording sessions (clear LSTM and buffers)."""
        raise NotImplementedError

    def process(
        self, audio: np.ndarray, sample_rate: int
    ) -> Optional[SpeechSegment]:
        """Classify a chunk of streaming audio.

        Returns a complete ``SpeechSegment`` when an utterance boundary
        is detected (or ``max_utterance_ms`` is exceeded).  Returns
        ``None`` when audio is still accumulating or no speech detected.
        """
        raise NotImplementedError

    def finalize(self) -> Optional[SpeechSegment]:
        """Flush any remaining buffered speech (used at end-of-session).

        Returns ``None`` when the remaining buffer is too short.
        """
        raise NotImplementedError

    def snapshot(self) -> Optional[SpeechSegment]:
        """Return a copy of the current buffered speech without clearing.

        Used for draft ASR submissions while speech is still in progress.
        Returns ``None`` when no speech is currently buffered.
        """
        raise NotImplementedError

    def pop_error(self) -> str | None:
        """Return and consume the next recoverable VAD failure, if any."""
        return None


class _SileroVadSession(VadSession):
    """Per-connection Silero VAD session owning the full audio buffer."""

    def __init__(self, provider: SileroVADProvider) -> None:
        self._p = provider

        if self._p._model is None:
            self._p.load()

        self.max_utterance_ms: int = 0

        self._frame_chunks: list[np.ndarray] = []  # list-of-chunks avoids np.concatenate churn
        self._frame_offset: int = 0  # samples already consumed in first chunk
        self._is_voiced: bool = False
        self._degraded: bool = False
        self._elapsed_ms: int = 0

        # Hysteresis / padding counters
        self._silence_frames: int = 0
        self._post_pad_counter: int = 0

        # Preroll ring buffer
        self._preroll_samples = int(
            self._p.speech_pad_pre_ms / 1000 * self._p.sample_rate
        )
        self._recent_chunks: deque[np.ndarray] = deque()
        self._recent_total: int = 0
        self._max_recent = self._preroll_samples + _FRAME_SAMPLES * 4

        # Speech audio buffer — accumulated per utterance
        self._speech_chunks: list[np.ndarray] = []
        self._speech_started_ms: int = 0
        self._speech_duration_ms: int = 0
        self._speech_ended_ms: int = 0
        self._speech_sample_rate: int | None = None

    # -- VADLike protocol ---------------------------------------------------

    def reset(self) -> None:
        self._frame_chunks = []
        self._frame_offset = 0
        self._is_voiced = False
        self._degraded = False
        self._elapsed_ms = 0
        self._silence_frames = 0
        self._post_pad_counter = 0
        self._recent_chunks.clear()
        self._recent_total = 0
        self._reset_speech_buffer()

    def process(
        self, audio: np.ndarray, sample_rate: int
    ) -> Optional[SpeechSegment]:
        """Feed a chunk through the hysteresis state machine.

        Returns a ``SpeechSegment`` when speech ends or ``max_utterance_ms``
        is exceeded, ``None`` otherwise.
        """
        if sample_rate <= 0 or audio.size == 0:
            return None
        if sample_rate != self._p.sample_rate:
            raise ValueError(
                f"VAD configured for {self._p.sample_rate} Hz, got {sample_rate}"
            )

        audio = np.asarray(audio, dtype=np.float32).reshape(-1)
        duration_ms = max(1, int(round((len(audio) / sample_rate) * 1000)))
        chunk_start_ms = self._elapsed_ms
        chunk_end_ms = chunk_start_ms + duration_ms
        self._elapsed_ms = chunk_end_ms

        # Feed the preroll ring buffer.
        self._recent_chunks.append(audio.copy())
        self._recent_total += len(audio)
        while self._recent_total > self._max_recent:
            old = self._recent_chunks.popleft()
            self._recent_total -= len(old)

        # Degraded mode — treat everything as speech, force-flush at max.
        if self._degraded:
            self._speech_chunks.append(audio.copy())
            self._speech_duration_ms += duration_ms
            if self._speech_started_ms == 0:
                self._speech_started_ms = chunk_start_ms
            self._speech_ended_ms = chunk_end_ms
            if self._speech_sample_rate is None:
                self._speech_sample_rate = sample_rate
            if self.max_utterance_ms > 0 and self._speech_duration_ms >= self.max_utterance_ms:
                return self._flush_speech()
            return None

        # Accumulate into the frame chunk list (avoids np.concatenate churn).
        self._frame_chunks.append(audio)

        try:
            import torch
        except Exception:
            self._enter_degraded("torch not available")
            return self._step_degraded(audio, chunk_start_ms, chunk_end_ms, duration_ms, sample_rate)

        segment: Optional[SpeechSegment] = None
        try:
            while True:
                # Drain 512-sample frames from the chunk list.
                frame = self._drain_frame()
                if frame is None:
                    break

                prob = self._get_probability(frame)
                transition = self._step_hysteresis(prob)

                if transition == "start":
                    preroll = self._extract_preroll()
                    self._speech_chunks.append(preroll)
                    self._speech_sample_rate = sample_rate
                elif transition == "end":
                    # _step_hysteresis already managed post-pad internally;
                    # "end" here means truly finished → flush the buffer.
                    segment = self._flush_speech()
        except Exception as exc:
            log.exception("Silero VAD inference failed; entering degraded mode")
            self._enter_degraded(str(exc))
            return self._step_degraded(audio, chunk_start_ms, chunk_end_ms, duration_ms, sample_rate)

        # Buffer the current chunk if in a speech span.
        if self._is_voiced:
            self._speech_chunks.append(audio.copy())
            self._speech_duration_ms += duration_ms
            if self._speech_started_ms == 0:
                self._speech_started_ms = chunk_start_ms
            self._speech_ended_ms = chunk_end_ms
            if self._speech_sample_rate is None:
                self._speech_sample_rate = sample_rate

        # Force-flush when max utterance duration is exceeded.
        if (
            self._is_voiced
            and self.max_utterance_ms > 0
            and self._speech_duration_ms >= self.max_utterance_ms
        ):
            segment = self._flush_speech()

        return segment

    def finalize(self) -> Optional[SpeechSegment]:
        """Flush any remaining speech buffer at end-of-session."""
        if self._speech_duration_ms <= 0 or not self._speech_chunks:
            return None
        return self._flush_speech()

    def snapshot(self) -> Optional[SpeechSegment]:
        """Return a copy of the current speech buffer without clearing."""
        if self._speech_duration_ms <= 0 or not self._speech_chunks:
            return None
        audio = np.concatenate(self._speech_chunks)
        return SpeechSegment(
            audio=np.ascontiguousarray(audio, dtype=np.float32),
            sample_rate=self._speech_sample_rate or self._p.sample_rate,
            started_ms=self._speech_started_ms,
            ended_ms=self._speech_ended_ms,
            duration_ms=self._speech_duration_ms,
        )

    # -- internal -----------------------------------------------------------

    def _drain_frame(self) -> Optional[np.ndarray]:
        """Extract one 512-sample frame from the chunk list.

        Returns ``None`` when fewer than 512 samples remain (partial frame
        is left in the chunk list for the next call).
        """
        avail = sum(len(c) for c in self._frame_chunks) - self._frame_offset
        if avail < _FRAME_SAMPLES:
            return None

        needed = _FRAME_SAMPLES
        parts: list[np.ndarray] = []
        while needed > 0 and self._frame_chunks:
            chunk = self._frame_chunks[0]
            chunk_avail = len(chunk) - self._frame_offset
            take = min(needed, chunk_avail)
            parts.append(chunk[self._frame_offset:self._frame_offset + take])
            self._frame_offset += take
            needed -= take
            if self._frame_offset >= len(chunk):
                self._frame_chunks.pop(0)
                self._frame_offset = 0

        if len(parts) == 1:
            return parts[0].copy()
        return np.concatenate(parts)

    def _frame_total(self) -> int:
        return sum(len(c) for c in self._frame_chunks) - self._frame_offset

    def _reset_speech_buffer(self) -> None:
        self._speech_chunks = []
        self._speech_started_ms = 0
        self._speech_duration_ms = 0
        self._speech_ended_ms = 0
        self._speech_sample_rate = None

    def _flush_speech(self) -> SpeechSegment:
        """Concatenate and return buffered speech, then reset."""
        if not self._speech_chunks:
            segment = SpeechSegment(
                audio=np.zeros(0, dtype=np.float32),
                sample_rate=self._p.sample_rate,
                started_ms=0,
                ended_ms=0,
                duration_ms=0,
            )
        else:
            audio = np.concatenate(self._speech_chunks)
            segment = SpeechSegment(
                audio=np.ascontiguousarray(audio, dtype=np.float32),
                sample_rate=self._speech_sample_rate or self._p.sample_rate,
                started_ms=self._speech_started_ms,
                ended_ms=self._speech_ended_ms,
                duration_ms=self._speech_duration_ms,
            )
        self._reset_speech_buffer()
        return segment

    def _step_degraded(
        self,
        audio: np.ndarray,
        chunk_start_ms: int,
        chunk_end_ms: int,
        duration_ms: int,
        sample_rate: int,
    ) -> Optional[SpeechSegment]:
        self._speech_chunks.append(audio.copy())
        self._speech_duration_ms += duration_ms
        if self._speech_started_ms == 0:
            self._speech_started_ms = chunk_start_ms
        self._speech_ended_ms = chunk_end_ms
        if self._speech_sample_rate is None:
            self._speech_sample_rate = sample_rate
        if self.max_utterance_ms > 0 and self._speech_duration_ms >= self.max_utterance_ms:
            return self._flush_speech()
        return None

    def _get_probability(self, frame: np.ndarray) -> float:
        """Raw Silero speech probability for a single frame."""
        import torch
        tensor = torch.from_numpy(frame.copy()).float()
        with torch.no_grad():
            prob = self._p._model(tensor, self._p.sample_rate)
        if hasattr(prob, "item"):
            return float(prob.item())
        return float(prob)

    def _step_hysteresis(self, prob: float) -> Optional[str]:
        """Advance the hysteresis state machine one frame.

        Returns ``"start"``, ``"end"``, or ``None``.
        """
        if not self._is_voiced:
            if prob >= self._p.threshold:
                self._is_voiced = True
                self._silence_frames = 0
                self._post_pad_counter = 0
                return "start"
            return None

        if self._post_pad_counter > 0:
            self._post_pad_counter -= 1
            if self._post_pad_counter == 0:
                self._is_voiced = False
                self._silence_frames = 0
                return "end"
            if prob >= self._p.threshold:
                self._post_pad_counter = 0
                self._silence_frames = 0
                return None
            return None

        if prob >= self._p.negative_threshold:
            self._silence_frames = 0
            return None

        self._silence_frames += 1
        if self._silence_frames >= self._p._min_silence_frames:
            if self._p._post_pad_frames > 0:
                self._post_pad_counter = self._p._post_pad_frames - 1
                return None
            self._is_voiced = False
            self._silence_frames = 0
            return "end"

        return None

    def _extract_preroll(self) -> np.ndarray:
        if self._preroll_samples <= 0 or not self._recent_chunks:
            return np.zeros(0, dtype=np.float32)

        chunks = list(self._recent_chunks)
        if len(chunks) >= 1:
            chunks = chunks[:-1]

        if not chunks:
            return np.zeros(0, dtype=np.float32)

        merged = np.concatenate(chunks)
        if len(merged) <= self._preroll_samples:
            return np.ascontiguousarray(merged, dtype=np.float32)
        return np.ascontiguousarray(
            merged[-self._preroll_samples:], dtype=np.float32
        )

    def _enter_degraded(self, reason: str) -> None:
        self._degraded = True
        self._frame_chunks = []
        self._frame_offset = 0
        self._is_voiced = True
        self._silence_frames = 0
        log.warning("VAD entering degraded mode: %s", reason)


class FireRedVADProvider(VADProvider):
    """CPU-only FireRedVAD manager with one shared immutable model."""

    def __init__(
        self,
        model_id: str = "firered-stream-vad",
        *,
        threshold: float = 0.60,
        min_silence_ms: int = 300,
        speech_pad_pre_ms: int = 300,
        speech_pad_post_ms: int = 400,
        min_utterance_ms: int = 100,
        max_utterance_ms: int = 8_000,
        sample_rate: int = 16_000,
    ) -> None:
        super().__init__(model_id)
        if sample_rate != 16_000:
            raise ValueError("FireRedVAD supports 16000 Hz audio only")
        self.threshold = threshold
        self.min_silence_ms = min_silence_ms
        self.speech_pad_pre_ms = speech_pad_pre_ms
        self.speech_pad_post_ms = speech_pad_post_ms
        self.min_utterance_ms = min_utterance_ms
        self.max_utterance_ms = max_utterance_ms
        self.sample_rate = sample_rate
        self.device = "cpu"
        self._model: Any = None
        self._model_dir: Path | None = None

    def load(self) -> None:
        if self._model is not None:
            return
        self._state = "LOADING"
        self._error = None
        try:
            from huggingface_hub import snapshot_download
            from fireredvad.core.detect_model import DetectModel

            snapshot_path = snapshot_download(
                repo_id=FIRERED_REPO_ID,
                revision=FIRERED_REVISION,
                allow_patterns=list(FIRERED_ALLOW_PATTERNS),
            )
            model_dir = Path(snapshot_path) / "Stream-VAD"
            model = DetectModel.from_pretrained(str(model_dir))
            model.cpu()
            model.eval()
            self._model_dir = model_dir
            self._model = model
            self._state = "LOADED"
        except Exception as exc:
            self._model = None
            self._model_dir = None
            self._error = f"FireRedVAD model load failed: {exc}"
            self._state = "ERROR"
            log.exception("FireRedVAD model load failed")
            raise RuntimeError(self._error) from exc

    def unload(self) -> None:
        self._model = None
        self._model_dir = None
        self._state = "UNLOADED"
        self._error = None

    def create_session(self) -> "VadSession":
        try:
            if self._model is None:
                self.load()
            engine = self._create_engine()
            return FireRedVadSession(self, engine)
        except Exception as exc:
            message = self._error or f"FireRedVAD session creation failed: {exc}"
            log.warning("FireRedVAD unavailable; using pass-through VAD: %s", message)
            return FireRedVadSession(self, None, initial_error=message)

    def _create_engine(self) -> Any:
        if self._model is None or self._model_dir is None:
            raise RuntimeError("FireRedVAD model is not loaded")

        from fireredvad.core.audio_feat import AudioFeat
        from fireredvad.core.stream_vad_postprocessor import StreamVadPostprocessor
        from fireredvad.stream_vad import FireRedStreamVad, FireRedStreamVadConfig

        config = FireRedStreamVadConfig(
            use_gpu=False,
            speech_threshold=self.threshold,
            pad_start_frame=_frames_for_ms(self.speech_pad_pre_ms),
            min_speech_frame=max(1, _frames_for_ms(self.min_utterance_ms)),
            max_speech_frame=max(1, _frames_for_ms(self.max_utterance_ms)),
            min_silence_frame=max(1, _frames_for_ms(self.min_silence_ms)),
        )
        audio_feat = AudioFeat(str(self._model_dir / "cmvn.ark"))
        postprocessor = StreamVadPostprocessor(
            config.smooth_window_size,
            config.speech_threshold,
            config.pad_start_frame,
            config.min_speech_frame,
            config.max_speech_frame,
            config.min_silence_frame,
        )
        return FireRedStreamVad(audio_feat, self._model, postprocessor, config)


def _frames_for_ms(milliseconds: int) -> int:
    return int(math.ceil(max(0, milliseconds) / _FIRERED_FRAME_MS))


class FireRedVadSession(VadSession):
    """Independent FireRed streaming state and exact sample timeline."""

    def __init__(
        self,
        provider: FireRedVADProvider,
        engine: Any | None,
        *,
        initial_error: str | None = None,
    ) -> None:
        self._p = provider
        self._engine = engine
        self._errors: deque[str] = deque()
        self._max_utterance_ms = provider.max_utterance_ms
        self._degraded = engine is None
        if initial_error:
            self._errors.append(initial_error)
        self.reset()

    @property
    def max_utterance_ms(self) -> int:
        return self._max_utterance_ms

    @max_utterance_ms.setter
    def max_utterance_ms(self, value: int) -> None:
        self._max_utterance_ms = max(0, int(value))
        postprocessor = getattr(self._engine, "postprocessor", None)
        if postprocessor is not None and self._max_utterance_ms > 0:
            postprocessor.max_speech_frame = max(
                1, _frames_for_ms(self._max_utterance_ms)
            )
        config = getattr(self._engine, "config", None)
        if config is not None and self._max_utterance_ms > 0:
            config.max_speech_frame = max(1, _frames_for_ms(self._max_utterance_ms))

    def reset(self) -> None:
        if self._engine is not None:
            self._engine.reset()
        self._timeline = np.zeros(0, dtype=np.float32)
        self._timeline_start = 0
        self._audio_end = 0
        self._frame_cursor = 0
        self._active_start: int | None = None
        self._pending_end: int | None = None
        self._degraded_start: int | None = 0 if self._degraded else None
        self._completed: deque[SpeechSegment] = deque()

    def process(
        self, audio: np.ndarray, sample_rate: int
    ) -> Optional[SpeechSegment]:
        if sample_rate <= 0 or audio.size == 0:
            return self._completed.popleft() if self._completed else None
        if sample_rate != self._p.sample_rate:
            raise ValueError(
                f"VAD configured for {self._p.sample_rate} Hz, got {sample_rate}"
            )

        chunk = np.ascontiguousarray(audio, dtype=np.float32).reshape(-1)
        self._append_timeline(chunk)

        if self._degraded:
            self._force_split_degraded()
            self._trim_timeline()
            return self._completed.popleft() if self._completed else None

        try:
            while self._audio_end - self._frame_cursor >= _FIRERED_FRAME_SAMPLES:
                frame_start = self._frame_cursor
                frame = self._slice_audio(
                    frame_start, frame_start + _FIRERED_FRAME_SAMPLES
                )
                pcm_frame = np.ascontiguousarray(
                    np.clip(frame, -1.0, 1.0) * 32767.0,
                    dtype=np.float32,
                )
                result = self._engine.detect_frame(pcm_frame)
                self._handle_frame_result(result, frame_start)
                self._frame_cursor += _FIRERED_HOP_SAMPLES
        except Exception as exc:
            message = f"FireRedVAD inference failed: {exc}"
            log.exception("%s; switching session to pass-through VAD", message)
            self._errors.append(message)
            self._degraded = True
            self._degraded_start = (
                self._active_start
                if self._active_start is not None
                else self._timeline_start
            )
            self._active_start = None
            self._pending_end = None
            self._force_split_degraded()

        if self._pending_end is not None and self._audio_end >= self._pending_end:
            self._queue_active_segment(self._pending_end)
        self._trim_timeline()
        return self._completed.popleft() if self._completed else None

    def snapshot(self) -> Optional[SpeechSegment]:
        if self._degraded:
            start = self._degraded_start
        else:
            start = self._active_start
        if start is None or self._audio_end <= start:
            return None
        end = min(self._audio_end, self._pending_end or self._audio_end)
        return self._make_segment(start, end)

    def finalize(self) -> Optional[SpeechSegment]:
        if self._completed:
            return self._completed.popleft()
        snapshot = self.snapshot()
        self._active_start = None
        self._pending_end = None
        self._degraded_start = self._audio_end if self._degraded else None
        return snapshot

    def pop_error(self) -> str | None:
        return self._errors.popleft() if self._errors else None

    def _handle_frame_result(self, result: Any, frame_start: int) -> None:
        if result.is_speech_start:
            start = max(
                0,
                (int(result.speech_start_frame) - 1) * _FIRERED_HOP_SAMPLES,
            )
            if self._pending_end is not None:
                if start <= self._pending_end:
                    self._pending_end = None
                else:
                    self._queue_active_segment(self._pending_end)
            if self._active_start is None:
                self._active_start = start

        if result.is_speech_end and self._active_start is not None:
            frame_end = min(
                self._audio_end,
                frame_start + _FIRERED_FRAME_SAMPLES,
            )
            forced = bool(result.is_speech)
            if forced:
                self._queue_active_segment(frame_end)
            else:
                post_samples = int(
                    round(self._p.speech_pad_post_ms * self._p.sample_rate / 1000)
                )
                self._pending_end = frame_end + post_samples

    def _append_timeline(self, audio: np.ndarray) -> None:
        if self._timeline.size == 0:
            self._timeline = audio.copy()
        else:
            self._timeline = np.concatenate((self._timeline, audio))
        self._audio_end += len(audio)

    def _slice_audio(self, start: int, end: int) -> np.ndarray:
        bounded_start = max(start, self._timeline_start)
        bounded_end = min(end, self._audio_end)
        left = bounded_start - self._timeline_start
        right = bounded_end - self._timeline_start
        return self._timeline[left:right]

    def _make_segment(self, start: int, end: int) -> SpeechSegment:
        bounded_start = max(start, self._timeline_start)
        bounded_end = min(end, self._audio_end)
        audio = np.ascontiguousarray(
            self._slice_audio(bounded_start, bounded_end), dtype=np.float32
        )
        return SpeechSegment(
            audio=audio,
            sample_rate=self._p.sample_rate,
            started_ms=int(round(bounded_start * 1000 / self._p.sample_rate)),
            ended_ms=int(round(bounded_end * 1000 / self._p.sample_rate)),
            duration_ms=int(round(len(audio) * 1000 / self._p.sample_rate)),
        )

    def _queue_active_segment(self, end: int) -> None:
        if self._active_start is None:
            return
        if end > self._active_start:
            self._completed.append(self._make_segment(self._active_start, end))
        self._active_start = None
        self._pending_end = None

    def _force_split_degraded(self) -> None:
        if self._degraded_start is None:
            self._degraded_start = self._timeline_start
        if self._max_utterance_ms <= 0:
            return
        cap_samples = int(
            round(self._max_utterance_ms * self._p.sample_rate / 1000)
        )
        if self._audio_end - self._degraded_start >= cap_samples:
            end = self._degraded_start + cap_samples
            self._completed.append(self._make_segment(self._degraded_start, end))
            self._degraded_start = end

    def _trim_timeline(self) -> None:
        pre_samples = int(
            round(self._p.speech_pad_pre_ms * self._p.sample_rate / 1000)
        )
        anchors = [max(0, self._frame_cursor - pre_samples - _FIRERED_FRAME_SAMPLES)]
        if self._active_start is not None:
            anchors.append(self._active_start)
        if self._degraded_start is not None:
            anchors.append(self._degraded_start)
        keep_from = max(self._timeline_start, min(anchors))
        if keep_from <= self._timeline_start:
            return
        drop = keep_from - self._timeline_start
        self._timeline = self._timeline[drop:].copy()
        self._timeline_start = keep_from


# -- factory ----------------------------------------------------------------


def create_vad_provider(
    model_id: str = "silero",
    *,
    threshold: float = 0.60,
    negative_threshold: float = 0.45,
    min_silence_ms: int = 300,
    speech_pad_pre_ms: int = 300,
    speech_pad_post_ms: int = 400,
    min_utterance_ms: int = 100,
    max_utterance_ms: int = 8_000,
    sample_rate: int = 16_000,
) -> VADProvider:
    if model_id == "silero":
        return SileroVADProvider(
            model_id=model_id,
            threshold=threshold,
            negative_threshold=negative_threshold,
            min_silence_ms=min_silence_ms,
            speech_pad_pre_ms=speech_pad_pre_ms,
            speech_pad_post_ms=speech_pad_post_ms,
            sample_rate=sample_rate,
        )
    if model_id == "firered-stream-vad":
        return FireRedVADProvider(
            model_id=model_id,
            threshold=threshold,
            min_silence_ms=min_silence_ms,
            speech_pad_pre_ms=speech_pad_pre_ms,
            speech_pad_post_ms=speech_pad_post_ms,
            min_utterance_ms=min_utterance_ms,
            max_utterance_ms=max_utterance_ms,
            sample_rate=sample_rate,
        )
    raise ValueError(f"unsupported vad model_id: {model_id}")
