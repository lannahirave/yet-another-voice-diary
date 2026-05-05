"""WebSocket audio endpoint — handshake + fake-audio → utterance event."""
from __future__ import annotations

import numpy as np
import pytest
import sqlite3
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
        duration = self._ended
        seg = SpeechSegment(
            audio=np.ascontiguousarray(concat, dtype=np.float32),
            sample_rate=self._sr or 16000,
            started_ms=0,
            ended_ms=self._ended,
            duration_ms=duration,
        )
        self._buffer = []
        self._ended = 0
        return seg


@pytest.fixture()
def sync_client(tmp_path):
    cfg = BackendConfig(
        database=DatabaseConfig(path=tmp_path / "ws.db"),
        pipeline=PipelineConfig(vad_min_utterance_ms=50),
    )
    app = create_app(cfg)
    app.state.coordinator = PipelineCoordinator(
        cfg.pipeline,
        FakeASRProvider(),
        FakeDiarizationProvider(),
        FakeEmbeddingProvider(),
        vad_processor=FakeVADProcessor(),
    )
    app.state.providers = {
        "asr": app.state.coordinator.asr,
        "diarization": app.state.coordinator.diarization,
        "embedding": app.state.coordinator.embedding,
    }

    # Override the per-WS coordinator factory so the WS path uses our fakes
    # instead of constructing a real VAD + provider stack.
    def _fake_coordinator(track: str) -> PipelineCoordinator:
        coord = PipelineCoordinator(
            cfg.pipeline,
            FakeASRProvider(),
            FakeDiarizationProvider(),
            FakeEmbeddingProvider(),
            vad_processor=FakeVADProcessor(),
            source=track,
        )
        return coord

    app.state.coordinator_factory = _fake_coordinator
    with TestClient(app) as client:
        yield client


def test_ws_start_then_audio_yields_utterance(sync_client):
    """WS audio persists a buffered utterance once VAD sees a silence boundary."""
    with sync_client.websocket_connect("/ws/audio") as ws:
        ws.send_json({"type": "start", "session_id": "sess-1", "title": "T"})

        started = ws.receive_json()
        assert started["type"] == "started"
        assert started["session_id"] == "sess-1"

        # 0.1 s of speech followed by 0.1 s of silence, float32 @ 16 kHz
        speech = np.ones(1600, dtype=np.float32)
        silence = np.zeros(1600, dtype=np.float32)
        ws.send_bytes(speech.tobytes())
        ws.send_bytes(silence.tobytes())

        seg_msg = ws.receive_json()
        assert seg_msg["type"] == "speaker_segment"
        assert seg_msg["data"]["session_id"] == "sess-1"

        utt_msg = ws.receive_json()
        assert utt_msg["type"] == "utterance"
        assert utt_msg["data"]["session_id"] == "sess-1"
        assert utt_msg["data"]["started_ms"] == 0
        # Trailing silence chunk is buffered to preserve Silero's speech pad.
        assert utt_msg["data"]["ended_ms"] == 200
        assert utt_msg["data"]["speaker_segment_id"] == seg_msg["data"]["id"]
        assert utt_msg["data"]["speaker_contact_id"] is None

        ws.send_json({"type": "stop"})

    session = sync_client.get("/sessions/sess-1")
    assert session.status_code == 200
    assert session.json()["utterance_count"] == 1
    assert session.json()["ended_at"] is not None

    utterances = sync_client.get("/sessions/sess-1/utterances")
    assert utterances.status_code == 200
    assert len(utterances.json()) == 1
    assert utterances.json()[0]["speaker_segment_id"] == seg_msg["data"]["id"]

    queue = sync_client.get("/unknown-queue")
    assert queue.status_code == 200
    clusters = queue.json()
    assert len(clusters) == 1
    assert seg_msg["data"]["id"] in clusters[0]["segment_ids"]


def test_ws_audio_before_start_errors(sync_client):
    with sync_client.websocket_connect("/ws/audio") as ws:
        ws.send_bytes(b"\x00" * 64)
        msg = ws.receive_json()
        assert msg["type"] == "error"


def test_ws_stop_flushes_buffered_utterance(sync_client):
    with sync_client.websocket_connect("/ws/audio") as ws:
        ws.send_json({"type": "start", "session_id": "sess-stop"})
        started = ws.receive_json()
        assert started["type"] == "started"

        speech = np.ones(1600, dtype=np.float32)
        ws.send_bytes(speech.tobytes())
        ws.send_json({"type": "stop"})

    session = sync_client.get("/sessions/sess-stop")
    assert session.status_code == 200
    assert session.json()["utterance_count"] == 1

    utterances = sync_client.get("/sessions/sess-stop/utterances")
    assert utterances.status_code == 200
    assert len(utterances.json()) == 1
    assert utterances.json()[0]["started_ms"] == 0
    assert utterances.json()[0]["ended_ms"] == 100


def test_ws_invalid_json_errors(sync_client):
    with sync_client.websocket_connect("/ws/audio") as ws:
        ws.send_text("not json")
        msg = ws.receive_json()
        assert msg["type"] == "error"


def test_queue_resolve_creates_voice_profile(sync_client):
    contact = sync_client.post("/contacts", json={"name": "Alice"}).json()
    conn = sqlite3.connect(str(sync_client.app.state.config.database.path))
    conn.row_factory = sqlite3.Row
    embedding = np.ones(192, dtype=np.float32).tobytes()
    conn.execute(
        "INSERT INTO sessions (id, title, started_at) VALUES (?, ?, ?)",
        ("sess-profile", "Profile", 1),
    )
    conn.execute(
        """
        INSERT INTO speaker_segments (id, session_id, status, embedding, sim_score)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("seg-profile", "sess-profile", "unknown", embedding, 0.0),
    )
    conn.execute(
        """
        INSERT INTO unknown_queue (id, speaker_segment_id, created_at)
        VALUES (?, ?, ?)
        """,
        ("queue-profile", "seg-profile", 1),
    )
    conn.commit()
    conn.close()

    clusters = sync_client.get("/unknown-queue").json()
    assert len(clusters) == 1

    resolved = sync_client.post(
        "/unknown-queue/resolve",
        json={"queue_ids": clusters[0]["queue_ids"], "contact_id": contact["id"]},
    )

    assert resolved.status_code == 200
    contacts = sync_client.get("/contacts").json()
    assert contacts[0]["profile_count"] == 1
