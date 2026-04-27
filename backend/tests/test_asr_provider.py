"""ASR provider backend selection helpers."""
from __future__ import annotations

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
