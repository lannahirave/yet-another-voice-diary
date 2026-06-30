"""ASR provider backend selection helpers."""
from __future__ import annotations

import sys
import types

import numpy as np

from backend.providers.asr import WhisperASRProvider


def test_transformers_model_aliases_match_whisper_hub_ids():
    assert WhisperASRProvider._transformers_model_id("tiny") == "openai/whisper-tiny"
    assert (
        WhisperASRProvider._transformers_model_id("large-v3-turbo")
        == "openai/whisper-large-v3-turbo"
    )
    assert (
        WhisperASRProvider._transformers_model_id("distil-whisper/distil-large-v3")
        == "distil-whisper/distil-large-v3"
    )


def test_generate_kwargs_preserve_transcribe_task_and_language_hint():
    assert WhisperASRProvider._generate_kwargs(None) == {"task": "transcribe"}
    assert WhisperASRProvider._generate_kwargs("UK") == {
        "task": "transcribe",
        "language": "uk",
    }


def test_silent_audio_returns_empty_without_loading_model():
    provider = WhisperASRProvider(model_id="tiny")

    utterance = provider.transcribe(np.zeros(16000, dtype=np.float32), language_hint="uk")

    assert utterance.transcript == ""
    assert utterance.language == "uk"
    assert provider._state == "UNLOADED"


def test_cuda_runtime_load_error_falls_back_to_cpu(monkeypatch):
    calls: list[tuple[str, str]] = []

    class FakeWhisperModel:
        def __init__(self, model_id, *, device, compute_type, cpu_threads):
            calls.append((device, compute_type))
            if device == "cuda":
                raise RuntimeError(
                    "Library cublas64_12.dll is not found or cannot be loaded"
                )

    fake_module = types.ModuleType("faster_whisper")
    fake_module.WhisperModel = FakeWhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)

    provider = WhisperASRProvider(model_id="tiny", device="cuda")

    provider.load()

    assert calls == [("cuda", "float16"), ("cpu", "int8")]
    assert provider._backend == "faster-whisper"
    assert provider._state == "LOADED"
    assert provider._error is not None
    assert "CUDA ASR runtime unavailable" in provider._error


def test_auto_device_is_resolved_before_loading_faster_whisper(monkeypatch):
    calls: list[tuple[str, str]] = []

    class FakeWhisperModel:
        def __init__(self, model_id, *, device, compute_type, cpu_threads):
            calls.append((device, compute_type))

    fake_module = types.ModuleType("faster_whisper")
    fake_module.WhisperModel = FakeWhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)
    monkeypatch.setattr(WhisperASRProvider, "_auto_device", staticmethod(lambda: "cpu"))

    provider = WhisperASRProvider(model_id="tiny", device="auto")

    provider.load()

    assert calls == [("cpu", "int8")]
    assert provider._backend == "faster-whisper"
    assert provider._state == "LOADED"
