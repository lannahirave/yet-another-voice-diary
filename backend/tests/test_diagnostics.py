"""Tests for the opt-in session diagnostics artifact."""
from __future__ import annotations

import json
import wave

import numpy as np

from backend.api.diagnostics import start_debug_session


def test_debug_session_writes_audio_metadata_and_report(tmp_path, monkeypatch):
    monkeypatch.setenv("VOICE_DIARY_DEBUG", "1")
    monkeypatch.setenv("VOICE_DIARY_DEBUG_DIR", str(tmp_path))

    session = start_debug_session("session-1", {"pipeline": {"chunk_ms": 100}})

    assert session is not None
    session.save_utterance(
        "utt-1",
        np.array([0.0, 0.5, -0.5], dtype=np.float32),
        started_ms=100,
        ended_ms=250,
        transcript="hello world",
        language="en",
        confidence=0.9,
        source="mic",
        speaker_segments=[
            {
                "id": "segment-1",
                "speaker": "SPEAKER_00",
                "contact_id": "contact-1",
                "diarization_model_id": "pyannote",
            }
        ],
    )
    session.log_vad(0, False)
    session.log_vad(100, False)
    session.log_vad(200, True)
    session.log_event(250, "ASR", "transcribed")
    session.log_error(300, "embedding unavailable")

    report_path = session.finish(ended_at="2026-07-12T12:00:00+00:00")

    assert report_path == session.output_dir / "debug-report.html"
    assert report_path.exists()
    assert "session-1" in report_path.read_text(encoding="utf-8")

    with wave.open(str(session.output_dir / "utterances/001-100ms-250ms/audio.wav")) as wav:
        assert wav.getframerate() == 16000
        assert wav.getnframes() == 3

    metadata = json.loads((session.output_dir / "utterances.json").read_text())
    assert metadata[0]["transcript"] == "hello world"
    assert metadata[0]["speaker_segments"][0]["contact_id"] == "contact-1"

    vad_events = json.loads((session.output_dir / "vad-timeline.json").read_text())
    assert vad_events == [
        {"ms": 0, "is_speech": False},
        {"ms": 200, "is_speech": True},
    ]


def test_debug_session_enforces_utterance_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("VOICE_DIARY_DEBUG", "1")
    monkeypatch.setenv("VOICE_DIARY_DEBUG_DIR", str(tmp_path))
    monkeypatch.setenv("VOICE_DIARY_DEBUG_MAX_UTTERANCES", "1")

    session = start_debug_session("session-2", {})
    assert session is not None

    kwargs = {
        "started_ms": 0,
        "ended_ms": 100,
        "transcript": "one",
        "language": None,
        "confidence": 0.0,
        "source": "system",
        "speaker_segments": [],
    }
    audio = np.zeros(2, dtype=np.float32)
    session.save_utterance("utt-1", audio, **kwargs)
    session.save_utterance("utt-2", audio, **kwargs)

    assert len(session.utterances) == 1
    assert session.dropped_utterances == 1


def test_start_debug_session_is_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("VOICE_DIARY_DEBUG", raising=False)
    monkeypatch.delenv("NODE_ENV", raising=False)
    monkeypatch.setenv("VOICE_DIARY_DEBUG_DIR", str(tmp_path))

    assert start_debug_session("session-3", {}) is None
