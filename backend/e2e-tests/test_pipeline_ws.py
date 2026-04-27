"""Full WebSocket audio pipeline — real audio, real models, real DB persistence.

Models are loaded once for the entire module via the autouse fixture and
unloaded in teardown.  All three assertions (transcript, persistence, queue)
run against the same WS session to avoid redundant 60-second model loads.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterator

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Module-scoped fixture: load models once, unload in teardown
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", autouse=True)
def models_loaded(sync_client: TestClient) -> Iterator[None]:
    for kind in ("asr", "embedding", "diarization"):
        r = sync_client.post(f"/models/{kind}/load")
        assert r.json()["state"] == "LOADED", (
            f"Failed to load {kind} for pipeline tests: {r.json()}"
        )
    yield
    for kind in ("asr", "embedding", "diarization"):
        sync_client.post(f"/models/{kind}/unload")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stream_session(
    app: FastAPI, wav: np.ndarray, session_id: str, track: str = "mic"
) -> list[dict]:
    """Open a WS session, stream wav in 500 ms chunks, send stop, collect events.

    SileroVAD's get_speech_timestamps needs at least ~500 ms of audio to reliably
    detect speech in a single chunk; 100 ms chunks return no timestamps at all.
    """
    events: list[dict] = []
    tc = TestClient(app)
    chunk_size = 8000  # 500 ms @ 16 kHz

    url = f"/ws/audio?track={track}" if track else "/ws/audio"
    with tc.websocket_connect(url) as ws:
        ws.send_json({"type": "start", "session_id": session_id})
        started = ws.receive_json()
        assert started["type"] == "started", f"Unexpected first message: {started}"

        for i in range(0, len(wav), chunk_size):
            ws.send_bytes(wav[i : i + chunk_size].tobytes())

        ws.send_json({"type": "stop"})

        while True:
            try:
                events.append(ws.receive_json())
            except Exception:
                break

    return events


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_full_pipeline(e2e_app: FastAPI, wav_f32: np.ndarray) -> None:
    """Single comprehensive test: transcript + DB persistence + queue population."""
    session_id = str(uuid.uuid4())
    events = _stream_session(e2e_app, wav_f32, session_id)

    # --- transcript ---
    utterance_events = [e for e in events if e.get("type") == "utterance"]
    assert len(utterance_events) >= 1, (
        f"No utterance events received. All events: {[e.get('type') for e in events]}"
    )
    full_transcript = " ".join(
        e["data"]["transcript"] for e in utterance_events
    ).lower()
    assert "hello" in full_transcript, (
        f"Expected 'hello' in transcript, got: {full_transcript!r}"
    )

    tc = TestClient(e2e_app)

    # --- DB persistence ---
    sess_r = tc.get(f"/sessions/{session_id}")
    assert sess_r.status_code == 200
    assert sess_r.json()["ended_at"] is not None, "Session should have ended_at set"

    utts_r = tc.get(f"/sessions/{session_id}/utterances")
    assert utts_r.status_code == 200
    db_utterances = utts_r.json()
    assert len(db_utterances) >= 1, "Utterances not persisted to DB"
    assert db_utterances[0]["transcript"].strip() != ""

    # --- unknown queue populated ---
    queue_r = tc.get("/unknown-queue")
    assert queue_r.status_code == 200
    our_items = [q for q in queue_r.json() if session_id in q["session_ids"]]
    assert len(our_items) >= 1, (
        "Expected at least one unknown-queue cluster for this session"
    )


def test_ws_audio_before_start_returns_error(e2e_app: FastAPI) -> None:
    tc = TestClient(e2e_app)
    with tc.websocket_connect("/ws/audio") as ws:
        ws.send_bytes(b"\x00" * 64)
        msg = ws.receive_json()
        assert msg["type"] == "error"


def test_ws_stop_flushes_buffered_speech(
    e2e_app: FastAPI, wav_f32: np.ndarray
) -> None:
    """Sending stop before silence boundary should still flush an utterance."""
    session_id = str(uuid.uuid4())
    tc = TestClient(e2e_app)

    events: list[dict] = []
    with tc.websocket_connect("/ws/audio") as ws:
        ws.send_json({"type": "start", "session_id": session_id})
        ws.receive_json()  # "started"

        # Send only the first 3 s of audio then stop immediately (no silence chunk)
        speech = wav_f32[: 16000 * 3]
        for i in range(0, len(speech), 8000):
            ws.send_bytes(speech[i : i + 8000].tobytes())

        ws.send_json({"type": "stop"})
        while True:
            try:
                events.append(ws.receive_json())
            except Exception:
                break

    utterances = [e for e in events if e.get("type") == "utterance"]
    assert len(utterances) >= 1, "stop should flush remaining buffered speech"


def test_unknown_track_rejected(e2e_app: FastAPI) -> None:
    """Unrecognised ``?track=`` values must be refused — clients shouldn't
    invent new track names because doing so would silently bypass the
    coordinator-per-track wiring."""
    tc = TestClient(e2e_app)
    with pytest.raises(Exception):  # WebSocketDisconnect from rejection close
        with tc.websocket_connect("/ws/audio?track=bogus") as ws:
            ws.receive_json()


def test_dual_track_keeps_sources_separate(
    e2e_app: FastAPI, wav_f32: np.ndarray
) -> None:
    """Two parallel WS sessions on the same session_id with different tracks
    must persist utterances tagged with the correct ``source`` and not blend
    state between the two coordinators.

    We feed identical audio into both tracks. The mic track should produce
    only ``source='mic'`` utterances and unknown-queue clusters; the system
    track only ``source='system'`` ones. If the coordinator state were
    shared, the two flushes would interfere and we'd see mixed-source
    artifacts.
    """
    session_id = str(uuid.uuid4())

    mic_events = _stream_session(e2e_app, wav_f32, session_id, track="mic")
    sys_events = _stream_session(e2e_app, wav_f32, session_id, track="system")

    mic_utts = [e for e in mic_events if e.get("type") == "utterance"]
    sys_utts = [e for e in sys_events if e.get("type") == "utterance"]
    assert mic_utts, "mic track produced no utterances"
    assert sys_utts, "system track produced no utterances"

    for u in mic_utts:
        assert u["data"].get("source") in ("mic", None), (
            f"mic-track utterance carried unexpected source: {u['data']}"
        )
    for u in sys_utts:
        assert u["data"].get("source") == "system", (
            f"system-track utterance must carry source='system', got {u['data']}"
        )

    tc = TestClient(e2e_app)

    # --- DB row source columns are persisted correctly ---
    utts_r = tc.get(f"/sessions/{session_id}/utterances")
    assert utts_r.status_code == 200
    db_utts = utts_r.json()
    sources = {u["source"] for u in db_utts}
    assert sources == {"mic", "system"}, (
        f"Expected both 'mic' and 'system' utterances persisted, got {sources}"
    )

    # --- queue clusters retain their source ---
    queue_r = tc.get("/unknown-queue")
    assert queue_r.status_code == 200
    clusters = [c for c in queue_r.json() if session_id in c["session_ids"]]
    cluster_sources = {c["source"] for c in clusters}
    # Both tracks created speakers, so both source values should appear.
    assert "mic" in cluster_sources, (
        f"mic-track cluster missing from queue (sources={cluster_sources})"
    )
    assert "system" in cluster_sources, (
        f"system-track cluster missing from queue (sources={cluster_sources})"
    )
