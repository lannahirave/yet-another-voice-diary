"""Whole-session recording and refinement regression tests."""
from __future__ import annotations

import sqlite3
import time
import wave
from pathlib import Path

import numpy as np

from backend.api.app import create_app
from backend.config import BackendConfig, DatabaseConfig, PipelineConfig, ProviderConfig
from backend.models import RecordingSession, Utterance
from backend.providers.diarization import DiarizationSegment
from backend.providers.vad import SpeechSegment
from backend.refinement.recording import SessionAudioRecorder
from backend.storage.session_repo import SessionRepo


class _VadSession:
    def __init__(self) -> None:
        self.samples = 0
        self.max_utterance_ms = 0

    def reset(self) -> None:
        self.samples = 0

    def process(self, audio: np.ndarray, sample_rate: int):
        self.samples += len(audio)
        return None

    def finalize(self):
        if not self.samples:
            return None
        return SpeechSegment(
            audio=np.zeros(self.samples, dtype=np.float32),
            sample_rate=16000,
            started_ms=0,
            ended_ms=int(self.samples * 1000 / 16000),
            duration_ms=int(self.samples * 1000 / 16000),
        )


class _Vad:
    def create_session(self):
        return _VadSession()


class _Diarization:
    def segment(self, audio: np.ndarray, sample_rate: int = 16000):
        return [DiarizationSegment(0, len(audio) / sample_rate, "local")]


class _Embedding:
    def embed(self, _audio: np.ndarray):
        return np.array([1.0, 0.0], dtype=np.float32)


class _Asr:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    def transcribe(self, _audio: np.ndarray, _language_hint: str | None = None):
        if self.fail:
            raise RuntimeError("asr failed")
        return Utterance(transcript="refined transcript", language="en", confidence=0.9)


def _write_wav(path: Path, seconds: float = 1.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    audio = (np.ones(int(16000 * seconds), dtype=np.float32) * 0.1 * 32767).astype("<i2")
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(audio.tobytes())


def _app_with_recording(tmp_path: Path, *, fail_asr: bool = False):
    config = BackendConfig(
        database=DatabaseConfig(path=tmp_path / "test.db"),
        pipeline=PipelineConfig(recording_retention="keep", vad_max_utterance_ms=8000),
        providers=ProviderConfig(preload_on_start=False),
    )
    app = create_app(config)
    app.state.providers.update(
        {"vad": _Vad(), "diarization": _Diarization(), "embedding": _Embedding(), "asr": _Asr(fail_asr)}
    )
    conn = sqlite3.connect(config.database.path)
    conn.row_factory = sqlite3.Row
    repo = SessionRepo(conn)
    session = RecordingSession(title="meeting")
    repo.create_session(session)
    repo.update_session(session.id, ended_at=session.started_at)
    repo.create_utterance(
        Utterance(session_id=session.id, started_ms=0, ended_ms=500, transcript="live transcript")
    )
    wav_path = tmp_path / "mic.wav"
    _write_wav(wav_path)
    conn.execute(
        """
        INSERT INTO session_recordings
            (session_id, source, path, duration_ms, size_bytes, status, created_at)
        VALUES (?, 'mic', ?, 1000, ?, 'ready', ?)
        """,
        (session.id, str(wav_path), wav_path.stat().st_size, int(time.time())),
    )
    conn.commit()
    conn.close()
    return app, session.id


def _wait_for_job(app, session_id: str) -> dict:
    deadline = time.time() + 5
    while time.time() < deadline:
        job = app.state.refinement_manager.latest(session_id)
        if job and job["status"] not in {"queued", "running"}:
            return job
        time.sleep(0.02)
    raise AssertionError("refinement job did not finish")


def test_session_audio_recorder_streams_pcm16(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.refinement.recording.recordings_root", lambda: tmp_path
    )
    recorder = SessionAudioRecorder("session", "mic")
    assert recorder.write(np.array([-2.0, 0.0, 2.0], dtype=np.float32))
    result = recorder.finish()
    assert result is not None
    path, duration_ms, size_bytes = result
    assert path.exists()
    assert duration_ms >= 0
    assert size_bytes == 50


def test_refinement_atomically_replaces_live_result(tmp_path: Path) -> None:
    app, session_id = _app_with_recording(tmp_path)
    app.state.refinement_manager.submit(session_id)
    job = _wait_for_job(app, session_id)
    assert job["status"] == "completed"
    assert job["metrics"]["audio_seconds"] == 1.0
    assert job["metrics"]["wall_time_seconds"] >= 0
    conn = sqlite3.connect(app.state.config.database.path)
    rows = conn.execute(
        "SELECT transcript FROM utterances WHERE session_id = ?", (session_id,)
    ).fetchall()
    assert rows == [("refined transcript",)]
    assert conn.execute(
        "SELECT COUNT(*) FROM unknown_queue"
    ).fetchone()[0] == 1
    conn.close()


def test_refinement_failure_preserves_live_result(tmp_path: Path) -> None:
    app, session_id = _app_with_recording(tmp_path, fail_asr=True)
    app.state.refinement_manager.submit(session_id)
    job = _wait_for_job(app, session_id)
    assert job["status"] == "failed"
    conn = sqlite3.connect(app.state.config.database.path)
    rows = conn.execute(
        "SELECT transcript FROM utterances WHERE session_id = ?", (session_id,)
    ).fetchall()
    assert rows == [("live transcript",)]
    assert conn.execute(
        "SELECT COUNT(*) FROM refinement_utterances"
    ).fetchone()[0] == 0
    conn.close()


def test_refinement_can_be_cancelled_while_queued(tmp_path: Path) -> None:
    app, session_id = _app_with_recording(tmp_path)
    with app.state.active_recordings_lock:
        app.state.active_recordings["another-session"] = 1
    app.state.refinement_manager.submit(session_id)
    app.state.refinement_manager.cancel(session_id)
    with app.state.active_recordings_lock:
        app.state.active_recordings.clear()
    job = _wait_for_job(app, session_id)
    assert job["status"] == "cancelled"
    conn = sqlite3.connect(app.state.config.database.path)
    assert conn.execute(
        "SELECT transcript FROM utterances WHERE session_id = ?", (session_id,)
    ).fetchone()[0] == "live transcript"
    conn.close()
