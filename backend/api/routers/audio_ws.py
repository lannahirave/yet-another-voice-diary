"""WebSocket audio streaming endpoint.

Protocol:
    1. Client opens ws://.../ws/audio
    2. Client sends JSON {"type": "start", "session_id": "...", "title?": "..."}
    3. Client sends binary frames of float32 PCM @ 16 kHz (channel count 1)
    4. Server emits JSON {"type": "utterance", "data": {...}}
                        {"type": "speaker_segment", "data": {...}}
                        {"type": "error", "message": "..."}
    5. Client sends {"type": "stop"} or closes the socket
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sqlite3
import wave
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ...identification.resolver import SpeakerResolver, SQLiteResolverStore
from ...models import RecordingSession, SpeakerSegment, Utterance
from ...pipeline.coordinator import PipelineCoordinator
from ..diagnostics import DebugSession, start_debug_session
from ...storage.queue_repo import QueueRepo
from ...storage.session_repo import SessionRepo

log = logging.getLogger(__name__)
router = APIRouter()
SAMPLE_RATE = 16000


def _dev_audio_enabled() -> bool:
    return os.environ.get("VOICE_DIARY_SAVE_DEV_AUDIO") == "1"


def _dev_audio_dir() -> Path:
    configured = os.environ.get("VOICE_DIARY_DEV_AUDIO_DIR")
    return Path(configured) if configured else Path.cwd() / ".dev-audio"


def _safe_filename_part(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_-")
    return safe or "session"


def _write_dev_audio_wav(
    session_id: str,
    chunks: list[np.ndarray],
    sample_rate: int = SAMPLE_RATE,
    track: str = "mic",
) -> Path | None:
    if not _dev_audio_enabled() or not chunks:
        return None

    audio = np.concatenate(chunks).astype(np.float32, copy=False)
    if audio.size == 0:
        return None

    audio = np.nan_to_num(audio, nan=0.0, posinf=1.0, neginf=-1.0)
    pcm16 = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2")

    output_dir = _dev_audio_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    filename = (
        f"{timestamp}-{_safe_filename_part(session_id)}-{_safe_filename_part(track)}.wav"
    )
    output_path = output_dir / filename

    with wave.open(str(output_path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm16.tobytes())

    return output_path


def _utterance_to_dict(u: Utterance) -> dict[str, Any]:
    return {
        "id": u.id,
        "session_id": u.session_id,
        "started_ms": u.started_ms,
        "ended_ms": u.ended_ms,
        "transcript": u.transcript,
        "language": u.language,
        "confidence": u.confidence,
        "speaker_segment_id": u.speaker_segment_id,
        "speaker_contact_id": u.speaker_contact_id,
    }


def _segment_to_dict(s: SpeakerSegment) -> dict[str, Any]:
    return {
        "id": s.id,
        "session_id": s.session_id,
        "contact_id": s.contact_id,
        "status": s.status,
        "sim_score": s.sim_score,
        "source": s.source,
    }


_ALLOWED_TRACKS = {"mic", "system"}


def _build_coordinator(state: Any, source: str) -> PipelineCoordinator:
    """Construct a fresh coordinator per WS connection.

    The coordinator owns per-stream state (VAD session, audio buffer, current
    session).  Sharing one across two parallel tracks would corrupt that state
    instantly.  Provider singletons (ASR / diarization / embedding) are reused
    because they're stateless w.r.t. the call sequence and expensive to load.

    The VAD manager is a singleton (loaded model), but each connection gets
    its own lightweight ``VadSession`` with independent LSTM state.
    """
    cfg = state.config
    providers = state.providers
    vad_session = providers["vad"].create_session()
    return PipelineCoordinator(
        cfg.pipeline,
        providers["asr"],
        providers["diarization"],
        providers["embedding"],
        vad_processor=vad_session,
        source=source,
    )


@router.websocket("/ws/audio")
async def stream(ws: WebSocket) -> None:
    track = ws.query_params.get("track", "mic")
    if track not in _ALLOWED_TRACKS:
        await ws.close(code=1008, reason=f"unknown track: {track}")
        return
    await ws.accept()
    # ``coordinator_factory`` is the test seam: unit tests inject a coordinator
    # with a fake VAD/ASR/diarization stack so they don't have to load real
    # models. Production code path uses ``_build_coordinator``.
    factory = getattr(ws.app.state, "coordinator_factory", None)
    if factory is not None:
        coord = factory(track)
    else:
        coord = _build_coordinator(ws.app.state, source=track)
    queue: asyncio.Queue[dict] = asyncio.Queue()
    db_conn: sqlite3.Connection | None = None
    db_conn = sqlite3.connect(str(ws.app.state.config.database.path))
    db_conn.row_factory = sqlite3.Row
    db_conn.execute("PRAGMA foreign_keys = ON")
    try:
        db_conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError:
        log.warning("WAL mode unavailable; using default journal (concurrent readers may block)")
    session_repo = SessionRepo(db_conn)
    queue_repo = QueueRepo(db_conn)
    resolver = SpeakerResolver(
        SQLiteResolverStore(db_conn),
        embedding_model_id=ws.app.state.config.providers.embedding_model_id,
    )

    def on_utt(u: Utterance) -> None:
        payload = session_repo.create_utterance(u)
        queue.put_nowait({"type": "utterance", "data": payload})

    def on_seg(s: SpeakerSegment) -> None:
        s.diarization_model_id = ws.app.state.config.providers.diarization_model_id
        if not s.contact_id:
            try:
                resolver.resolve(
                    s,
                    threshold=ws.app.state.config.pipeline.speaker_identification_threshold,
                )
            except Exception as exc:
                log.exception("resolver failed; segment remains unknown")
                queue.put_nowait({
                    "type": "error",
                    "code": "RESOLVER_FAILURE",
                    "component": "resolver",
                    "message": str(exc),
                })
        session_repo.create_speaker_segment(s)
        if not s.contact_id:
            queue_repo.enqueue(s.id)
        queue.put_nowait({"type": "speaker_segment", "data": _segment_to_dict(s)})

    coord.on("utterance", on_utt)
    coord.on("speaker_segment", on_seg)
    coord.on(
        "draft_utterance",
        lambda d: queue.put_nowait({"type": "draft_utterance", "data": d}),
    )

    # ---- debug mode callbacks ----

    def _on_debug_audio(data: dict) -> None:
        if debug is None:
            return
        try:
            debug.save_utterance(
                utt_id=data.get("utt_id", data.get("utterance_id", "")),
                audio=data["audio"],
                started_ms=data["started_ms"],
                ended_ms=data["ended_ms"],
                transcript=data["transcript"],
                language=data.get("language"),
                confidence=data.get("confidence", 0.0),
                source=data.get("source", "mic"),
                speaker_segments=data.get("speaker_segments", []),
            )
        except Exception:
            log.exception("failed to persist debug utterance")

    def _on_debug_vad(data: dict) -> None:
        if debug is not None:
            debug.log_vad(data["ms"], data["is_speech"])

    def _on_error_debug(exc: dict) -> None:
        if debug is not None:
            debug.log_error(exc.get("ms", 0), exc.get("message", str(exc)))

    def _on_error_client(err: dict) -> None:
        queue.put_nowait({"type": "error", **err})
        if session is not None and session.id:
            try:
                session_repo.create_error(
                    session_id=session.id,
                    component=err.get("component", "unknown"),
                    error_code=err.get("code", "UNKNOWN"),
                    message=err.get("message", ""),
                    occurred_at_ms=err.get("ms", 0),
                )
            except Exception:
                pass  # DB write failure should not cascade

    coord.on("error", _on_error_client)

    session: RecordingSession | None = None
    sender_task: asyncio.Task | None = None
    debug: DebugSession | None = None
    debug_hooks_attached = False
    dev_audio_chunks: list[np.ndarray] = []
    _dev_audio_total_samples = 0
    _DEV_AUDIO_MAX_SAMPLES = 16000 * 300  # cap at 5 minutes per track

    async def sender() -> None:
        while True:
            msg = await queue.get()
            await ws.send_json(msg)

    try:
        sender_task = asyncio.create_task(sender())
        while True:
            msg = await ws.receive()
            msg_type = msg.get("type")
            if msg_type == "websocket.disconnect":
                break
            if "text" in msg and msg["text"] is not None:
                try:
                    payload = json.loads(msg["text"])
                except json.JSONDecodeError:
                    await ws.send_json({"type": "error", "message": "invalid JSON"})
                    continue
                ptype = payload.get("type")
                if ptype == "start":
                    sid = payload.get("session_id")
                    if not sid:
                        await ws.send_json(
                            {"type": "error", "message": "start requires session_id"}
                        )
                        continue
                    session = RecordingSession(
                        id=sid, title=payload.get("title", "")
                    )
                    existing = session_repo.get_session(sid)
                    if existing is None:
                        session_repo.create_session(session)
                    elif payload.get("title") and existing["title"] != payload["title"]:
                        session_repo.update_session(sid, title=payload["title"])
                    coord.start_session(session)
                    # SUPER DEBUG: capture config snapshot and start diagnostics
                    if debug is None:
                        cfg = ws.app.state.config
                        config_snapshot = {
                            "asr_model_id": cfg.providers.asr_model_id,
                            "diarization_model_id": cfg.providers.diarization_model_id,
                            "embedding_model_id": cfg.providers.embedding_model_id,
                            "vad_model_id": cfg.providers.vad_model_id,
                            "device": cfg.providers.device,
                            "vad_threshold": cfg.pipeline.vad_threshold,
                            "vad_min_silence_ms": cfg.pipeline.vad_min_silence_ms,
                            "vad_speech_pad_ms": cfg.pipeline.vad_speech_pad_ms,
                            "vad_min_utterance_ms": cfg.pipeline.vad_min_utterance_ms,
                            "vad_max_utterance_ms": cfg.pipeline.vad_max_utterance_ms,
                            "speaker_identification_threshold": cfg.pipeline.speaker_identification_threshold,
                            "chunk_duration_ms": cfg.pipeline.chunk_duration_ms,
                        }
                        debug = start_debug_session(sid, config_snapshot)
                        if debug:
                            if not debug_hooks_attached:
                                coord.on("debug:audio", _on_debug_audio)
                                coord.on("debug:vad", _on_debug_vad)
                                coord.on("error", _on_error_debug)
                                debug_hooks_attached = True
                            log.info("SUPER DEBUG: capturing session %s to %s", sid, debug.output_dir)
                    await ws.send_json({"type": "started", "session_id": sid})
                elif ptype == "stop":
                    break
                else:
                    await ws.send_json(
                        {"type": "error", "message": f"unknown message type: {ptype}"}
                    )
            elif "bytes" in msg and msg["bytes"] is not None:
                if session is None:
                    await ws.send_json(
                        {"type": "error", "message": "send 'start' before audio"}
                    )
                    continue
                audio_np = np.frombuffer(msg["bytes"], dtype=np.float32).copy()
                if _dev_audio_enabled() and audio_np.size > 0:
                    _dev_audio_total_samples += audio_np.size
                    if _dev_audio_total_samples <= _DEV_AUDIO_MAX_SAMPLES:
                        dev_audio_chunks.append(audio_np.copy())
                try:
                    await coord.process_chunk(audio_np, SAMPLE_RATE)
                except Exception as exc:
                    log.exception("process_chunk failed")
                    await ws.send_json({"type": "error", "message": str(exc)})
    except WebSocketDisconnect:
        pass
    finally:
        if session is not None:
            try:
                saved_audio = _write_dev_audio_wav(
                    session.id, dev_audio_chunks, track=track
                )
                if saved_audio is not None:
                    log.info("Saved dev audio capture to %s", saved_audio)
            except Exception:
                log.exception("failed to save dev audio capture")
            try:
                coord.end_session()
                session_repo.update_session(session.id, ended_at=datetime.utcnow())
            except Exception:
                log.exception("end_session failed")
            if debug is not None:
                try:
                    html_path = debug.finish(ended_at=datetime.utcnow().isoformat())
                    log.info("SUPER DEBUG: report written to %s", html_path)
                except Exception:
                    log.exception("debug report generation failed")
            try:
                if getattr(
                    ws.app.state.config.pipeline,
                    "unload_models_after_stop",
                    False,
                ):
                    for provider in ws.app.state.providers.values():
                        if hasattr(provider, "unload"):
                            provider.unload()
            except Exception:
                log.exception("provider unload-after-stop failed")
        coord.off("utterance", on_utt)
        coord.off("speaker_segment", on_seg)
        coord.off("error", _on_error_client)
        if debug_hooks_attached:
            coord.off("debug:audio", _on_debug_audio)
            coord.off("debug:vad", _on_debug_vad)
            coord.off("error", _on_error_debug)
        if db_conn is not None:
            db_conn.close()
        if sender_task is not None:
            sender_task.cancel()
            try:
                await sender_task
            except (asyncio.CancelledError, Exception):
                pass
        # Drain any events that end_session() put directly into the queue
        # (on_utt/on_seg now use put_nowait, so items are available immediately).
        while not queue.empty():
            try:
                await ws.send_json(queue.get_nowait())
            except Exception:
                break
        try:
            await ws.close()
        except RuntimeError:
            pass
