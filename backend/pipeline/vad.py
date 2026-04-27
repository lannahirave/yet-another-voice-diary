"""Voice Activity Detection.

Streaming wrapper around `silero-vad`. Calling ``get_speech_timestamps`` on
each ~100 ms chunk in isolation is unsafe: Silero is a *temporal* detector
and its defaults (``min_speech_duration_ms=250``) require a longer window than
a single chunk to declare speech, so most true-speech chunks would be
classified as silence. Instead we drive the model through ``VADIterator``,
which keeps its LSTM state across calls and emits ``{'start': …}`` and
``{'end': …}`` events when crossing thresholds. The iterator only accepts
fixed-size frames (512 samples @ 16 kHz, 256 @ 8 kHz), so we maintain a small
internal frame buffer to slice variable-length input from the WebSocket into
those frames.
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Optional

import numpy as np


log = logging.getLogger(__name__)


# Silero requires fixed window sizes — 512 samples for 16 kHz models, 256 for
# 8 kHz. We expose a single supported sampling rate to match the rest of the
# pipeline; if the audio source ever changes we'll add a lookup here.
_SUPPORTED_SAMPLE_RATES = {16_000: 512, 8_000: 256}


@dataclass
class VADSegment:
    """Per-chunk VAD classification.

    ``is_speech`` reflects the iterator's *sustained* state at the end of the
    chunk — i.e. whether the current sample lies inside a Silero-detected
    speech span (after its own silence-debounce and speech-pad logic). Use
    this as the signal driving a coordinator-level endpointing state machine.
    """

    start_ms: int
    end_ms: int
    is_speech: bool


class VADProcessor:
    """Stateful streaming Silero VAD."""

    def __init__(
        self,
        threshold: float = 0.5,
        sample_rate: int = 16_000,
        min_silence_ms: int = 500,
        speech_pad_ms: int = 200,
    ) -> None:
        if sample_rate not in _SUPPORTED_SAMPLE_RATES:
            raise ValueError(
                f"VADProcessor supports {sorted(_SUPPORTED_SAMPLE_RATES)} Hz, "
                f"got {sample_rate}"
            )
        self.threshold = threshold
        self.sample_rate = sample_rate
        self.min_silence_ms = min_silence_ms
        self.speech_pad_ms = speech_pad_ms
        self._frame_samples = _SUPPORTED_SAMPLE_RATES[sample_rate]

        self._model: Optional[Any] = None
        self._iterator: Optional[Any] = None
        self._frame_buffer: np.ndarray = np.zeros(0, dtype=np.float32)
        self._is_voiced: bool = False
        self._elapsed_ms: int = 0
        self._state: str = "UNLOADED"
        self._error: Optional[str] = None

    # ---- lifecycle ----------------------------------------------------

    def reset(self) -> None:
        """Reset between sessions: clear state, frame buffer, and elapsed clock."""
        if self._iterator is not None:
            try:
                self._iterator.reset_states()
            except Exception:
                # Don't let a buggy reset propagate — fall back to a fresh iterator.
                log.exception("VADIterator.reset_states failed; recreating iterator")
                self._iterator = None
                if self._model is not None:
                    self._iterator = self._build_iterator()
        self._frame_buffer = np.zeros(0, dtype=np.float32)
        self._is_voiced = False
        self._elapsed_ms = 0

    def load(self) -> None:
        """Load the Silero model and instantiate the streaming iterator."""
        if self._iterator is not None:
            return
        self._state = "LOADING"
        self._error = None
        try:
            from silero_vad import VADIterator, load_silero_vad  # type: ignore[import-untyped]
        except Exception as exc:
            self._error = f"silero-vad not installed or could not load: {exc}"
            self._state = "ERROR"
            log.exception("Silero VAD import failed")
            raise RuntimeError(self._error) from exc

        try:
            self._model = load_silero_vad()
            self._VADIterator = VADIterator  # retained for reset rebuilds
            self._iterator = self._build_iterator()
        except Exception as exc:
            self._error = f"Silero VAD model load failed: {exc}"
            self._state = "ERROR"
            log.exception("Silero VAD model load failed")
            raise RuntimeError(self._error) from exc

        self._state = "LOADED"

    def _build_iterator(self) -> Any:
        return self._VADIterator(
            self._model,
            threshold=self.threshold,
            sampling_rate=self.sample_rate,
            min_silence_duration_ms=self.min_silence_ms,
            speech_pad_ms=self.speech_pad_ms,
        )

    def unload(self) -> None:
        self._model = None
        self._iterator = None
        self._frame_buffer = np.zeros(0, dtype=np.float32)
        self._is_voiced = False
        self._state = "UNLOADED"
        self._error = None

    # ---- inference ----------------------------------------------------

    def process(self, audio: np.ndarray, sample_rate: int) -> Optional[VADSegment]:
        """Classify a chunk of streaming audio.

        The chunk may be any length; it is appended to the internal frame
        buffer and drained in fixed Silero-sized windows. The returned
        ``is_speech`` reflects the iterator's state after the *last* drained
        frame — partially-buffered samples are kept for the next call.
        """
        if sample_rate <= 0 or audio.size == 0:
            return None
        if sample_rate != self.sample_rate:
            raise ValueError(
                f"VADProcessor configured for {self.sample_rate} Hz, got {sample_rate}"
            )

        audio = np.asarray(audio, dtype=np.float32).reshape(-1)
        duration_ms = max(1, int(round((len(audio) / sample_rate) * 1000)))
        start_ms = self._elapsed_ms
        end_ms = start_ms + duration_ms
        self._elapsed_ms = end_ms

        if self._iterator is None:
            self.load()

        try:
            import torch  # imported lazily — only required when Silero is available
        except Exception as exc:  # pragma: no cover - silero_vad pulls torch already
            self._error = f"torch not available for Silero VAD: {exc}"
            self._state = "ERROR"
            raise RuntimeError(self._error) from exc

        # Append to the frame buffer and drain in fixed-size windows.
        self._frame_buffer = (
            audio if self._frame_buffer.size == 0
            else np.concatenate([self._frame_buffer, audio])
        )

        try:
            while self._frame_buffer.size >= self._frame_samples:
                frame = self._frame_buffer[: self._frame_samples]
                self._frame_buffer = self._frame_buffer[self._frame_samples :]
                event = self._iterator(torch.from_numpy(frame).float())
                if event is None:
                    continue
                if "start" in event:
                    self._is_voiced = True
                elif "end" in event:
                    self._is_voiced = False
        except Exception as exc:
            self._error = f"Silero VAD inference failed: {exc}"
            self._state = "ERROR"
            log.exception("Silero VAD inference failed")
            raise RuntimeError(self._error) from exc

        return VADSegment(start_ms=start_ms, end_ms=end_ms, is_speech=self._is_voiced)
