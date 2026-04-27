"""Whisper ASR provider.

Default model: ``large-v3-turbo`` — 809M params, 8× decode speedup over large-v3
while keeping large-v3 quality on well-represented languages (UK + EN both fine).
Released Oct 2024; available via ``faster-whisper`` as ``large-v3-turbo`` (or ``turbo``).

When ``faster-whisper`` is not installed, the provider falls back to Hugging Face
Transformers' ASR implementation. If neither backend can load, the provider
raises and logs the detailed exception instead of returning fake transcripts.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np

from ..models import Utterance

log = logging.getLogger(__name__)


class WhisperASRProvider:
    """Whisper ASR wrapper with lazy model load."""

    def __init__(
        self,
        model_id: str = "large-v3-turbo",
        *,
        model_size: Optional[str] = None,  # legacy alias for model_id
        device: Optional[str] = None,
        compute_type: Optional[str] = None,
        beam_size: int = 1,
        cpu_threads: int = 0,
    ) -> None:
        self.model_id = model_size or model_id
        # legacy alias — existing test/code may read ``model_size``
        self.model_size = self.model_id
        self.device = device
        self.compute_type = compute_type
        self.beam_size = beam_size
        self.cpu_threads = cpu_threads
        self._model: Optional[Any] = None
        self._backend: Optional[str] = None
        self._state = "UNLOADED"
        self._error: Optional[str] = None

    # ---- model lifecycle ----

    def _load_model(self) -> None:
        self._state = "LOADING"
        self._error = None

        try:
            from faster_whisper import WhisperModel  # type: ignore[import-untyped]
        except Exception as exc:
            faster_whisper_error = exc
            log.exception("faster-whisper backend failed to import")
        else:
            device = self.device or self._auto_device()
            compute_type = self.compute_type or (
                "float16" if device == "cuda" else "int8"
            )
            log.info(
                "Loading faster-whisper model=%s device=%s compute_type=%s",
                self.model_id,
                device,
                compute_type,
            )
            self._model = WhisperModel(
                self.model_id,
                device=device,
                compute_type=compute_type,
                cpu_threads=self.cpu_threads,
            )
            self._backend = "faster-whisper"
            self._state = "LOADED"
            return

        if self._load_transformers_model():
            self._error = (
                "faster-whisper not installed; using Transformers ASR fallback "
                f"({faster_whisper_error})"
            )
            log.warning(self._error)
            return

        message = (
            "faster-whisper not installed and Transformers ASR could not be loaded "
            f"({faster_whisper_error})"
        )
        self._error = message
        self._state = "ERROR"
        raise RuntimeError(message)

    def _load_transformers_model(self) -> bool:
        try:
            import torch  # type: ignore[import-untyped]
            from transformers import (  # type: ignore[import-untyped]
                AutoModelForSpeechSeq2Seq,
                AutoProcessor,
            )
        except Exception as exc:
            self._error = f"Transformers ASR import failed: {exc}"
            log.exception("Transformers ASR backend failed to import")
            return False

        device_name = self.device or self._auto_device()
        device = "cuda:0" if device_name == "cuda" and torch.cuda.is_available() else "cpu"
        torch_dtype = torch.float16 if device != "cpu" else torch.float32
        model_id = self._transformers_model_id(self.model_id)

        try:
            log.info(
                "Loading Transformers ASR model=%s device=%s dtype=%s",
                model_id,
                device,
                torch_dtype,
            )
            processor = AutoProcessor.from_pretrained(model_id)
            model = AutoModelForSpeechSeq2Seq.from_pretrained(
                model_id,
                dtype=torch_dtype,
                low_cpu_mem_usage=True,
            ).to(device)
            self._model = {
                "model": model,
                "processor": processor,
                "device": device,
                "dtype": torch_dtype,
            }
        except Exception as exc:
            self._error = f"Transformers ASR load failed: {exc}"
            log.exception("Transformers ASR model load failed")
            return False

        self._backend = "transformers"
        self._state = "LOADED"
        return True

    @staticmethod
    def _transformers_model_id(model_id: str) -> str:
        aliases = {
            "tiny": "openai/whisper-tiny",
            "base": "openai/whisper-base",
            "small": "openai/whisper-small",
            "medium": "openai/whisper-medium",
            "large-v3": "openai/whisper-large-v3",
            "large-v3-turbo": "openai/whisper-large-v3-turbo",
            "turbo": "openai/whisper-large-v3-turbo",
        }
        return aliases.get(model_id, model_id)

    def load(self) -> None:
        """Load the configured model if it is not already loaded."""
        if self._model is None:
            self._load_model()

    def unload(self) -> None:
        """Release the model reference; the next transcription loads lazily."""
        self._model = None
        self._backend = None
        self._state = "UNLOADED"
        self._error = None

    @staticmethod
    def _auto_device() -> str:
        try:
            import torch  # type: ignore[import-untyped]

            return "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            return "cpu"

    # ---- inference ----

    def transcribe(
        self,
        audio: np.ndarray,
        language_hint: Optional[str] = None,
    ) -> Utterance:
        """Transcribe a float32 mono 16 kHz waveform. Returns a fresh Utterance."""
        if audio.size == 0:
            return Utterance(transcript="", language=language_hint, confidence=0.0)

        audio = np.ascontiguousarray(audio, dtype=np.float32)
        if float(np.sqrt(np.mean(np.square(audio)))) < 1e-4:
            return Utterance(transcript="", language=language_hint, confidence=0.0)

        if self._model is None:
            self._load_model()

        assert self._model is not None

        if self._backend == "faster-whisper":
            segments_iter, info = self._model.transcribe(
                audio,
                language=language_hint,
                beam_size=self.beam_size,
                vad_filter=False,  # we run VAD upstream in the pipeline
                condition_on_previous_text=False,
            )
            segments = list(segments_iter)
            text = " ".join(s.text.strip() for s in segments if s.text).strip()
            return Utterance(
                transcript=text,
                language=info.language,
                confidence=float(info.language_probability or 0.0),
            )

        text = self._transcribe_transformers(audio, language_hint)

        return Utterance(
            transcript=text,
            language=language_hint,
            confidence=0.0,
        )

    def _transcribe_transformers(
        self,
        audio: np.ndarray,
        language_hint: Optional[str],
    ) -> str:
        import torch  # type: ignore[import-untyped]

        assert isinstance(self._model, dict)
        model = self._model["model"]
        processor = self._model["processor"]
        device = self._model["device"]
        dtype = self._model["dtype"]

        inputs = processor(
            audio,
            sampling_rate=16000,
            return_tensors="pt",
        )
        input_features = inputs.input_features.to(device=device, dtype=dtype)
        generate_kwargs = self._generate_kwargs(language_hint)

        with torch.no_grad():
            predicted_ids = model.generate(input_features, **generate_kwargs)
        return str(processor.batch_decode(predicted_ids, skip_special_tokens=True)[0]).strip()

    @staticmethod
    def _generate_kwargs(language_hint: Optional[str]) -> dict[str, str]:
        kwargs = {"task": "transcribe"}
        if language_hint:
            kwargs["language"] = language_hint.lower()
        return kwargs
