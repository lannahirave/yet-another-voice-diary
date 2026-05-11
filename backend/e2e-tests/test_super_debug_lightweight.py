"""E2E tests for lightweight SUPER DEBUG mode."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse, unquote

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.config import BackendConfig, DatabaseConfig, PipelineConfig
from backend.models import Utterance
from backend.pipeline.coordinator import PipelineCoordinator
from backend.providers.vad import SpeechSegment


class FakeASRProvider:
    model_id = "test-asr"
    _state = "LOADED"
    _error = None

    def transcribe(
        self,
        audio: np.ndarray,
        language_hint: str | None = None,
    ) -> Utterance:
        return Utterance(
            transcript=f"samples:{len(audio)}",
            language=language_hint,
            confidence=1.0,
        )


class FakeDiarizationProvider:
    model_id = "test-diarization"
    _state = "LOADED"
    _error = None

    def segment(self, audio: np.ndarray) -> list[object]:
        return []


class FakeEmbeddingProvider:
    model_id = "test-embedding"
    _state = "LOADED"
    _error = None

    def embed(self, audio: np.ndarray) -> np.ndarray:
        return np.zeros(192, dtype=np.float32)


class FakeVADProcessor:
    def __init__(self) -> None:
        self._buffer: list[np.ndarray] = []
        self._ended = 0
        self._sr: int | None = None

    def reset(self) -> None:
        self._buffer = []
        self._ended = 0
        self._sr = None

    def process(
        self, audio: np.ndarray, sample_rate: int
    ) -> SpeechSegment | None:
        dur = max(1, int(round((len(audio) / sample_rate) * 1000)))
        self._ended += dur
        if bool(np.any(audio)):
            self._buffer.append(audio.copy())
            if self._sr is None:
                self._sr = sample_rate
            return None
        if not self._buffer:
            return None
        concat = np.concatenate(self._buffer)
        duration = self._ended
        seg = SpeechSegment(
            audio=np.ascontiguousarray(concat, dtype=np.float32),
            sample_rate=self._sr or sample_rate,
            started_ms=0,
            ended_ms=self._ended,
            duration_ms=duration,
        )
        self._buffer = []
        self._ended = 0
        return seg

    def finalize(self) -> SpeechSegment | None:
        if not self._buffer:
            return None
        concat = np.concatenate(self._buffer)
        seg = SpeechSegment(
            audio=np.ascontiguousarray(concat, dtype=np.float32),
            sample_rate=self._sr or 16000,
            started_ms=0,
            ended_ms=self._ended,
            duration_ms=self._ended,
        )
        self._buffer = []
        self._ended = 0
        self._sr = None
        return seg

    def snapshot(self) -> SpeechSegment | None:
        if not self._buffer:
            return None
        concat = np.concatenate(self._buffer)
        return SpeechSegment(
            audio=np.ascontiguousarray(concat, dtype=np.float32),
            sample_rate=self._sr or 16000,
            started_ms=0,
            ended_ms=self._ended,
            duration_ms=self._ended,
        )


@pytest.fixture()
def debug_client(tmp_path: Path) -> TestClient:
    cfg = BackendConfig(
        database=DatabaseConfig(path=tmp_path / "debug-e2e.db"),
        pipeline=PipelineConfig(vad_min_utterance_ms=50),
    )
    app = create_app(cfg)

    def _fake_coordinator(track: str) -> PipelineCoordinator:
        return PipelineCoordinator(
            cfg.pipeline,
            FakeASRProvider(),
            FakeDiarizationProvider(),
            FakeEmbeddingProvider(),
            vad_processor=FakeVADProcessor(),
            source=track,
        )

    app.state.coordinator_factory = _fake_coordinator

    with TestClient(app) as client:
        yield client


def _run_one_ws_session(client: TestClient, session_id: str = "debug-sess") -> None:
    with client.websocket_connect("/ws/audio") as ws:
        ws.send_json({"type": "start", "session_id": session_id})
        started = ws.receive_json()
        assert started["type"] == "started"

        speech = np.ones(1600, dtype=np.float32)
        silence = np.zeros(1600, dtype=np.float32)
        ws.send_bytes(speech.tobytes())
        ws.send_bytes(silence.tobytes())

        _ = ws.receive_json()  # speaker_segment
        _ = ws.receive_json()  # utterance
        ws.send_json({"type": "stop"})


def test_super_debug_writes_compact_artifacts(
    debug_client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    debug_dir = tmp_path / "super-debug"
    monkeypatch.setenv("VOICE_DIARY_DEBUG", "1")
    monkeypatch.setenv("VOICE_DIARY_DEBUG_DIR", str(debug_dir))
    monkeypatch.setenv("NODE_ENV", "production")

    _run_one_ws_session(debug_client)

    session_dirs = [p for p in debug_dir.iterdir() if p.is_dir()]
    assert len(session_dirs) == 1
    session_dir = session_dirs[0]

    report = session_dir / "debug-report.html"
    utterances_json = session_dir / "utterances.json"
    vad_timeline = session_dir / "vad-timeline.json"
    debug_meta = session_dir / "debug-meta.json"

    assert report.exists()
    assert utterances_json.exists()
    assert vad_timeline.exists()
    assert debug_meta.exists()

    utterances = json.loads(utterances_json.read_text(encoding="utf-8"))
    assert len(utterances) == 1
    utt = utterances[0]

    # Compact manifest: no giant inline base64 payload.
    assert "waveform_base64" not in utt
    assert isinstance(utt["speaker_segments"], list)
    if utt["speaker_segments"]:
        assert "embedding" not in utt["speaker_segments"][0]

    waveform_uri = utt["waveform_file"]
    parsed = urlparse(waveform_uri)
    assert parsed.scheme == "file"
    wav_path = Path(unquote(parsed.path.lstrip("/")))
    assert wav_path.exists()
    assert wav_path.stat().st_size > 44

    # With one short utterance, the report should stay small.
    assert report.stat().st_size < 400_000

    vad = json.loads(vad_timeline.read_text(encoding="utf-8"))
    # Transition-only VAD logging: speech -> silence.
    assert len(vad) <= 2


def test_super_debug_disabled_writes_nothing(
    debug_client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    debug_dir = tmp_path / "super-debug-disabled"
    monkeypatch.setenv("VOICE_DIARY_DEBUG_DIR", str(debug_dir))
    monkeypatch.setenv("NODE_ENV", "production")
    monkeypatch.delenv("VOICE_DIARY_DEBUG", raising=False)

    _run_one_ws_session(debug_client, session_id="no-debug")

    if debug_dir.exists():
        session_dirs = [p for p in debug_dir.iterdir() if p.is_dir()]
        assert session_dirs == []
