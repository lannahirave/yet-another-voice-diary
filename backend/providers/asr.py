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
import re
from pathlib import Path
from typing import Any, Optional

import numpy as np

from ..models import Utterance
from .compat import suppress_known_ml_warnings

log = logging.getLogger(__name__)

# Language codes supported by OpenAI Whisper's multilingual tokenizer.
WHISPER_LANGUAGE_CODES = frozenset({
    "af", "am", "ar", "as", "az", "ba", "be", "bg", "bn", "bo", "br",
    "bs", "ca", "cs", "cy", "da", "de", "el", "en", "es", "et", "eu",
    "fa", "fi", "fo", "fr", "fy", "ga", "gd", "gl", "gu", "ha", "haw",
    "he", "hi", "hr", "ht", "hu", "hy", "id", "is", "it", "ja", "jw",
    "ka", "kk", "km", "kn", "ko", "la", "lb", "ln", "lo", "lt", "lv",
    "mg", "mi", "mk", "ml", "mn", "mr", "ms", "mt", "my", "ne", "nl",
    "nn", "no", "oc", "pa", "pl", "ps", "pt", "ro", "ru", "sa", "sd",
    "si", "sk", "sl", "sn", "so", "sq", "sr", "su", "sv", "sw", "ta",
    "te", "th", "tk", "tl", "tr", "tt", "uk", "ur", "uz", "vi", "yi",
    "yo", "zh",
})


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
        no_speech_threshold: float = 0.6,
        compression_ratio_threshold: float = 2.4,
        repetition_penalty: float = 1.1,
        no_repeat_ngram_size: int = 3,
    ) -> None:
        self.model_id = model_size or model_id
        # legacy alias — existing test/code may read ``model_size``
        self.model_size = self.model_id
        self.device = device
        self.compute_type = compute_type
        self.beam_size = beam_size
        self.cpu_threads = cpu_threads
        self.no_speech_threshold = no_speech_threshold
        self.compression_ratio_threshold = compression_ratio_threshold
        self.repetition_penalty = repetition_penalty
        self.no_repeat_ngram_size = no_repeat_ngram_size
        self._model: Optional[Any] = None
        self._backend: Optional[str] = None
        self._state = "UNLOADED"
        self._error: Optional[str] = None

        # Blocklist fields (set by pipeline coordinator before transcribe)
        self.blocklist_enabled: bool = False
        self._blocklists: dict[str, set[str]] = {}
        self._blocklists_loaded: bool = False

    # ---- blocklist ----

    _BLOCKLIST_DIR = Path(__file__).resolve().parent / "blocklists"
    _NON_WORD_RE = re.compile(r"[^\w\s]")
    _WHITESPACE_RE = re.compile(r"\s+")

    @classmethod
    def _normalize_for_blocklist(cls, text: str) -> str:
        text = text.lower().strip()
        text = cls._NON_WORD_RE.sub("", text)
        text = cls._WHITESPACE_RE.sub(" ", text).strip()
        return text

    def _load_blocklists(self) -> None:
        """Lazy-load per-language blocklist files from disk."""
        if self._blocklists_loaded:
            return
        self._blocklists = {}
        if not self._BLOCKLIST_DIR.is_dir():
            log.warning("blocklist directory not found: %s", self._BLOCKLIST_DIR)
            self._blocklists_loaded = True
            return
        for filepath in self._BLOCKLIST_DIR.glob("*.txt"):
            lang = filepath.stem.lower()
            phrases = {
                line.strip()
                for line in filepath.read_text(encoding="utf-8").splitlines()
                if line.strip()
            }
            if phrases:
                self._blocklists[lang] = phrases
        self._blocklists_loaded = True
        total = sum(len(v) for v in self._blocklists.values())
        log.info(
            "blocklist loaded phrases=%d languages=%d",
            total, len(self._blocklists),
        )

    def _is_blocked(self, text: str, lang: str | None) -> bool:
        """Return True when the transcript matches a blocklist entry."""
        if not self._blocklists_loaded:
            self._load_blocklists()
        lang_code = (lang or "en").lower()
        blocklist = self._blocklists.get(lang_code)
        if blocklist is None:
            blocklist = self._blocklists.get("en", set())
            if not blocklist:
                return False
        normal = self._normalize_for_blocklist(text)
        return normal in blocklist

    # ---- model lifecycle ----

    def _load_model(self) -> None:
        self._state = "LOADING"
        self._error = None

        configured_device = None if self.device == "auto" else self.device
        device = configured_device or self._auto_device()
        use_faster_whisper = device != "mps"
        faster_whisper_error: Exception | None = None

        if use_faster_whisper:
            try:
                with suppress_known_ml_warnings():
                    from faster_whisper import WhisperModel  # type: ignore[import-untyped]
            except Exception as exc:
                faster_whisper_error = exc
                log.exception("faster-whisper backend failed to import")
                use_faster_whisper = False
            else:
                compute_type = self.compute_type or (
                    "float16" if device == "cuda" else "int8"
                )
                log.info(
                    "Loading faster-whisper model=%s device=%s compute_type=%s",
                    self.model_id,
                    device,
                    compute_type,
                )
                try:
                    with suppress_known_ml_warnings():
                        self._model = WhisperModel(
                            self.model_id,
                            device=device,
                            compute_type=compute_type,
                            cpu_threads=self.cpu_threads,
                        )
                except Exception as exc:
                    faster_whisper_error = exc
                    if device == "cuda" and self._is_cuda_runtime_load_error(exc):
                        cpu_compute_type = (
                            self.compute_type
                            if self.compute_type and self.compute_type != "float16"
                            else "int8"
                        )
                        self._error = (
                            "CUDA ASR runtime unavailable; using CPU "
                            f"faster-whisper fallback: {exc}"
                        )
                        log.warning(self._error)
                        try:
                            with suppress_known_ml_warnings():
                                self._model = WhisperModel(
                                    self.model_id,
                                    device="cpu",
                                    compute_type=cpu_compute_type,
                                    cpu_threads=self.cpu_threads,
                                )
                            self._backend = "faster-whisper"
                            self._state = "LOADED"
                            return
                        except Exception as cpu_exc:
                            faster_whisper_error = cpu_exc
                            log.exception("CPU faster-whisper fallback failed")
                            use_faster_whisper = False
                    else:
                        log.exception("faster-whisper model load failed")
                        use_faster_whisper = False
                else:
                    self._backend = "faster-whisper"
                    self._state = "LOADED"
                    return

        if self._load_transformers_model():
            if device == "mps":
                reason = "MPS device selected"
            elif faster_whisper_error is not None:
                reason = f"faster-whisper failed to load: {faster_whisper_error}"
            else:
                reason = "faster-whisper not installed"
            self._error = f"{reason}; using Transformers ASR fallback"
            log.warning(self._error)
            return

        message = (
            "faster-whisper not installed and Transformers ASR could not be loaded"
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
        if device_name == "cuda" and torch.cuda.is_available():
            device = "cuda:0"
        elif device_name == "mps" and torch.backends.mps.is_available():
            device = "mps"
        else:
            device = "cpu"
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
    def _is_cuda_runtime_load_error(exc: Exception) -> bool:
        message = str(exc).lower()
        return any(
            marker in message
            for marker in (
                "cublas",
                "cudnn",
                "cuda",
                "nvrtc",
                "cufft",
                "curand",
                "cannot be loaded",
                "not found",
            )
        )

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
        model = self._model
        self._model = None
        self._backend = None
        self._state = "UNLOADED"
        self._error = None
        # Drop the local reference after state is clean so any C-extension
        # __del__ crash (CTranslate2 known issue) doesn't leave stale state.
        del model

    @staticmethod
    def _auto_device() -> str:
        try:
            import torch  # type: ignore[import-untyped]
            if torch.cuda.is_available():
                return "cuda"
            if torch.backends.mps.is_available():
                return "mps"
            return "cpu"
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
                no_speech_threshold=self.no_speech_threshold,
                compression_ratio_threshold=self.compression_ratio_threshold,
                repetition_penalty=self.repetition_penalty,
                no_repeat_ngram_size=self.no_repeat_ngram_size,
            )
            segments = list(segments_iter)
            text = " ".join(s.text.strip() for s in segments if s.text).strip()
            detected_lang: Optional[str] = info.language
            confidence = float(info.language_probability or 0.0)

            # Post-inference quality gate — discard silent / repetitive output
            # (Vexa pattern: no_speech_prob ≤ 0.5, compression_ratio ≤ 2.4)
            if not text:
                return Utterance(
                    transcript="", language=detected_lang, confidence=0.0,
                )
            no_speech_prob = float(getattr(info, "no_speech_prob", 0.0) or 0.0)
            avg_logprob = float(getattr(info, "avg_log_prob", 0.0) or 0.0)
            if no_speech_prob > 0.5 and avg_logprob < -0.7:
                log.info(
                    "ASR quality gate: silence detected no_speech_prob=%.3f avg_logprob=%.3f",
                    no_speech_prob, avg_logprob,
                )
                return Utterance(
                    transcript="", language=detected_lang, confidence=0.0,
                )
            max_cr = max(
                (float(getattr(s, "compression_ratio", 0.0)) for s in segments),
                default=0.0,
            )
            if max_cr > self.compression_ratio_threshold:
                log.info(
                    "ASR quality gate: repetitive output compression_ratio=%.3f threshold=%.3f",
                    max_cr, self.compression_ratio_threshold,
                )
                return Utterance(
                    transcript="", language=detected_lang, confidence=0.0,
                )

            if self.blocklist_enabled and text:
                if self._is_blocked(text, detected_lang):
                    log.info(
                        "whisper blocklist dropped language=%s text=%r",
                        detected_lang, text,
                    )
                    return Utterance(
                        transcript="", language=detected_lang, confidence=0.0,
                    )

            return Utterance(
                transcript=text,
                language=detected_lang,
                confidence=confidence,
            )

        text = self._transcribe_transformers(audio, language_hint)

        if self.blocklist_enabled and text.strip():
            if self._is_blocked(text.strip(), language_hint):
                log.info(
                    "whisper blocklist dropped language=%s text=%r",
                    language_hint, text.strip(),
                )
                return Utterance(
                    transcript="", language=language_hint, confidence=0.0,
                )

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
