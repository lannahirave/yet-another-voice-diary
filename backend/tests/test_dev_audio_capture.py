from __future__ import annotations

import wave

import numpy as np

from backend.api.routers.audio_ws import (
    _safe_filename_part,
    _write_dev_audio_wav,
)


def test_safe_filename_part_replaces_unsafe_characters():
    assert _safe_filename_part("session:../abc 123") == "session_abc_123"


def test_write_dev_audio_wav_is_disabled_outside_dev(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("NODE_ENV", raising=False)
    monkeypatch.delenv("VOICE_DIARY_SAVE_DEV_AUDIO", raising=False)

    path = _write_dev_audio_wav("session-1", [np.ones(4, dtype=np.float32)])

    assert path is None
    assert not (tmp_path / ".dev-audio").exists()


def test_write_dev_audio_wav_writes_pcm16_in_dev(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NODE_ENV", "development")

    path = _write_dev_audio_wav(
        "session-1",
        [
            np.array([-1.0, 0.0], dtype=np.float32),
            np.array([0.5, 1.0], dtype=np.float32),
        ],
        sample_rate=16000,
    )

    assert path is not None
    assert path.parent == tmp_path / ".dev-audio"
    with wave.open(str(path), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getframerate() == 16000
        assert wav.getnframes() == 4
