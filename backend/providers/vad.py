"""Voice Activity Detection provider.

Implements pluggable VAD via a provider pattern matching the existing
ASR / diarization / embedding providers.  The module-level factory
``create_vad_provider`` returns a *manager* (singleton — holds the
loaded model and configuration).  Per-WebSocket-connection state is
obtained via ``manager.create_session()``, which returns a lightweight
``VadSession`` carrying its own LSTM state, frame buffer, hysteresis
counters, and preroll ring buffer.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import logging
from typing import Any, Optional

import numpy as np

log = logging.getLogger(__name__)

# Silero requires fixed window sizes — 512 samples for 16 kHz models.
_FRAME_SAMPLES = 512


@dataclass
class VADSegment:
    """Per-chunk VAD classification.

    ``is_speech`` reflects the sustained speech/silence state at the end
    of the chunk, after hysteresis and post-speech padding.  On a rising
    edge (silence → speech) the segment may carry ``preroll_audio`` —
    audio from the preceding silence window that should be prepended to
    the utterance buffer so Whisper has enough context for the first
    phoneme.
    """

    start_ms: int
    end_ms: int
    is_speech: bool
    preroll_audio: np.ndarray | None = None


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
    frame buffer, hysteresis counters, and preroll ring buffer are
    isolated per audio stream.
    """

    def reset(self) -> None:
        """Reset between recording sessions (clear LSTM and buffers)."""
        raise NotImplementedError

    def process(
        self, audio: np.ndarray, sample_rate: int
    ) -> Optional[VADSegment]:
        """Classify a chunk of streaming audio."""
        raise NotImplementedError


class _SileroVadSession(VadSession):
    """Per-connection Silero VAD session with hysteresis state machine."""

    def __init__(self, provider: SileroVADProvider) -> None:
        self._p = provider

        # Ensure model is loaded (lazy, called once per provider).
        if self._p._model is None:
            self._p.load()

        self._frame_buffer: np.ndarray = np.zeros(0, dtype=np.float32)
        self._is_voiced: bool = False
        self._degraded: bool = False
        self._elapsed_ms: int = 0

        # Hysteresis / padding counters
        self._silence_frames: int = 0
        self._post_pad_counter: int = 0

        # Preroll ring buffer — holds the last pre_pad_ms of raw audio
        self._preroll_samples = int(
            self._p.speech_pad_pre_ms / 1000 * self._p.sample_rate
        )
        self._recent_chunks: deque[np.ndarray] = deque()
        self._recent_total: int = 0
        self._max_recent = self._preroll_samples + _FRAME_SAMPLES * 4

    # -- VADLike protocol ---------------------------------------------------

    def reset(self) -> None:
        self._frame_buffer = np.zeros(0, dtype=np.float32)
        self._is_voiced = False
        self._degraded = False
        self._elapsed_ms = 0
        self._silence_frames = 0
        self._post_pad_counter = 0
        self._recent_chunks.clear()
        self._recent_total = 0

    def process(
        self, audio: np.ndarray, sample_rate: int
    ) -> Optional[VADSegment]:
        if sample_rate <= 0 or audio.size == 0:
            return None
        if sample_rate != self._p.sample_rate:
            raise ValueError(
                f"VAD configured for {self._p.sample_rate} Hz, got {sample_rate}"
            )

        audio = np.asarray(audio, dtype=np.float32).reshape(-1)
        duration_ms = max(1, int(round((len(audio) / sample_rate) * 1000)))
        start_ms = self._elapsed_ms
        end_ms = start_ms + duration_ms
        self._elapsed_ms = end_ms

        # Feed the preroll ring buffer.
        self._recent_chunks.append(audio.copy())
        self._recent_total += len(audio)
        while self._recent_total > self._max_recent:
            old = self._recent_chunks.popleft()
            self._recent_total -= len(old)

        # Degraded mode — VAD errored earlier, treat everything as speech.
        if self._degraded:
            return VADSegment(
                start_ms=start_ms, end_ms=end_ms, is_speech=True
            )

        # Accumulate into the fixed-frame buffer and drain.
        self._frame_buffer = (
            audio
            if self._frame_buffer.size == 0
            else np.concatenate([self._frame_buffer, audio])
        )

        preroll: np.ndarray | None = None
        try:
            import torch
        except Exception:
            self._enter_degraded("torch not available")
            return self._degraded_segment(start_ms, end_ms)

        try:
            while self._frame_buffer.size >= _FRAME_SAMPLES:
                frame = self._frame_buffer[:_FRAME_SAMPLES]
                self._frame_buffer = self._frame_buffer[_FRAME_SAMPLES:]

                prob = self._get_probability(frame)
                transition = self._step_hysteresis(prob)

                if transition == "start":
                    preroll = self._extract_preroll()
                elif transition == "end" and self._post_pad_counter == 0:
                    # Post-pad starts now — keep is_voiced True for
                    # post_pad_frames more frames.
                    self._post_pad_counter = self._p._post_pad_frames
        except Exception as exc:
            log.exception("Silero VAD inference failed; entering degraded mode")
            self._enter_degraded(str(exc))
            return self._degraded_segment(start_ms, end_ms)

        return VADSegment(
            start_ms=start_ms,
            end_ms=end_ms,
            is_speech=self._is_voiced,
            preroll_audio=preroll,
        )

    # -- internal -----------------------------------------------------------

    def _get_probability(self, frame: np.ndarray) -> float:
        """Raw Silero speech probability for a single frame."""
        import torch
        tensor = torch.from_numpy(frame.copy()).float()
        prob = self._p._model(tensor, self._p.sample_rate)
        if hasattr(prob, "item"):
            return float(prob.item())
        return float(prob)

    def _step_hysteresis(self, prob: float) -> Optional[str]:
        """Advance the hysteresis state machine one frame.

        Returns ``"start"``, ``"end"``, or ``None``.
        """
        if not self._is_voiced:
            # Silence → speech (rising edge)
            if prob >= self._p.threshold:
                self._is_voiced = True
                self._silence_frames = 0
                self._post_pad_counter = 0
                return "start"
            return None

        # Already in speech — check for falling edge or post-pad.

        if self._post_pad_counter > 0:
            # We are in the post-speech padding window.
            self._post_pad_counter -= 1
            if self._post_pad_counter == 0:
                # Post-pad exhausted → truly end speech.
                self._is_voiced = False
                self._silence_frames = 0
                return "end"
            # Still in post-pad — if probability recovers, cancel the end.
            if prob >= self._p.threshold:
                self._post_pad_counter = 0
                self._silence_frames = 0
                return None  # speech resumes, no event
            return None

        # Normal speech — apply offset hysteresis.
        if prob >= self._p.negative_threshold:
            self._silence_frames = 0
            return None  # still speaking

        self._silence_frames += 1
        if self._silence_frames >= self._p._min_silence_frames:
            # min_silence exhausted — begin post-pad (delayed end).
            if self._p._post_pad_frames > 0:
                self._post_pad_counter = self._p._post_pad_frames - 1
                # Stay voiced through post-pad window.
                return None
            # No post-pad configured — end immediately.
            self._is_voiced = False
            self._silence_frames = 0
            return "end"

        return None

    def _extract_preroll(self) -> np.ndarray:
        """Extract up to ``preroll_samples`` of audio preceding speech onset.

        Returns an empty array when no recent audio is available.
        """
        if self._preroll_samples <= 0 or not self._recent_chunks:
            return np.zeros(0, dtype=np.float32)

        # The most recent chunk may contain the onset frame itself;
        # exclude it from the preroll by dropping the last chunk.
        chunks = list(self._recent_chunks)
        if len(chunks) >= 1:
            # Remove the chunk that triggered the onset — it will be
            # included by the coordinator's own buffering.
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
        self._frame_buffer = np.zeros(0, dtype=np.float32)
        self._is_voiced = True  # treat everything as speech
        self._silence_frames = 0
        log.warning("VAD entering degraded mode: %s", reason)

    def _degraded_segment(self, start_ms: int, end_ms: int) -> VADSegment:
        return VADSegment(start_ms=start_ms, end_ms=end_ms, is_speech=True)


# -- factory ----------------------------------------------------------------


def create_vad_provider(
    model_id: str = "silero",
    *,
    threshold: float = 0.60,
    negative_threshold: float = 0.45,
    min_silence_ms: int = 300,
    speech_pad_pre_ms: int = 300,
    speech_pad_post_ms: int = 400,
    sample_rate: int = 16_000,
) -> SileroVADProvider:
    if model_id not in ("silero",):
        raise ValueError(f"unsupported vad model_id: {model_id}")
    return SileroVADProvider(
        model_id=model_id,
        threshold=threshold,
        negative_threshold=negative_threshold,
        min_silence_ms=min_silence_ms,
        speech_pad_pre_ms=speech_pad_pre_ms,
        speech_pad_post_ms=speech_pad_post_ms,
        sample_rate=sample_rate,
    )
