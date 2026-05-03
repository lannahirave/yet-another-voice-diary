"""SUPER DEBUG mode - per-session diagnostic capture and HTML report generation.

Triggered when ``NODE_ENV=development`` (or ``VOICE_DIARY_DEBUG=1``).
Captures compact per-utterance metadata, VAD transitions, pipeline events,
and on-disk WAV artifacts, then produces an HTML report plus sidecar JSON files.
"""
from __future__ import annotations

import json
import os
import wave
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from .debug_report import generate_debug_html


# ---- helpers -----------------------------------------------------------


def _debug_enabled() -> bool:
    return (
        os.environ.get("NODE_ENV") == "development"
        or os.environ.get("VOICE_DIARY_DEBUG") == "1"
    )


def _debug_dir() -> Path:
    configured = os.environ.get("VOICE_DIARY_DEBUG_DIR")
    return Path(configured) if configured else Path.cwd() / ".dev-audio"


def _wav_to_disk(audio: np.ndarray, path: Path, sample_rate: int = 16000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        scaled = np.clip(audio * 32767, -32768, 32767).astype(np.int16)
        wf.writeframes(scaled.tobytes())


# ---- DebugSession ------------------------------------------------------


def _now_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")


@dataclass
class DebugSession:
    """Per-session debug state.

    Create one instance per WebSocket connection when debug mode is active.
    """

    session_id: str
    output_dir: Path
    config_snapshot: dict[str, Any]
    started_at: str = field(default_factory=_now_iso)

    # ---- accumulated data ----
    utterances: list[dict[str, Any]] = field(default_factory=list)
    vad_events: list[dict[str, Any]] = field(default_factory=list)
    pipeline_events: list[dict[str, Any]] = field(default_factory=list)
    queue_items: list[dict[str, Any]] = field(default_factory=list)

    dropped_utterances: int = 0
    dropped_vad_events: int = 0
    _last_vad_is_speech: bool | None = None
    _max_utterances: int = field(
        default_factory=lambda: int(
            os.environ.get("VOICE_DIARY_DEBUG_MAX_UTTERANCES", "2000")
        )
    )
    _max_vad_events: int = field(
        default_factory=lambda: int(
            os.environ.get("VOICE_DIARY_DEBUG_MAX_VAD_EVENTS", "10000")
        )
    )

    def save_utterance(
        self,
        utt_id: str,
        audio: np.ndarray,
        *,
        started_ms: int,
        ended_ms: int,
        transcript: str,
        language: str | None,
        confidence: float,
        source: str,
        speaker_segments: list[dict[str, Any]],
    ) -> None:
        """Save a single utterance WAV + compact metadata."""
        if len(self.utterances) >= self._max_utterances:
            self.dropped_utterances += 1
            return

        idx = len(self.utterances) + 1
        utt_dir_name = f"{idx:03d}-{started_ms}ms-{ended_ms}ms"
        utt_dir = self.output_dir / "utterances" / utt_dir_name
        utt_dir.mkdir(parents=True, exist_ok=True)

        wav_rel = Path("utterances") / utt_dir_name / "audio.wav"
        _wav_to_disk(audio, self.output_dir / wav_rel)

        serializable_segments: list[dict[str, Any]] = []
        for seg in speaker_segments:
            segment_id = seg.get("id", "")
            serializable_segments.append(
                {
                    "id": segment_id,
                    "segment_id": segment_id,
                    "speaker": seg.get("speaker", ""),
                    "contact_id": seg.get("contact_id"),
                    "diarization_model_id": seg.get("diarization_model_id", ""),
                }
            )

        meta = {
            "utt_id": utt_id,
            "index": idx,
            "started_ms": started_ms,
            "ended_ms": ended_ms,
            "duration_ms": ended_ms - started_ms,
            "transcript": transcript,
            "language": language,
            "confidence": confidence,
            "source": source,
            "speaker_segments": serializable_segments,
            "waveform_file": wav_rel.as_posix(),
        }

        self.utterances.append(meta)

    def log_vad(self, ms: int, is_speech: bool) -> None:
        # Persist only transitions instead of every chunk-level sample.
        if self._last_vad_is_speech is not None and self._last_vad_is_speech == is_speech:
            return
        self._last_vad_is_speech = is_speech
        if len(self.vad_events) >= self._max_vad_events:
            self.dropped_vad_events += 1
            return
        self.vad_events.append({"ms": ms, "is_speech": is_speech})

    def log_event(self, ms: int, kind: str, message: str) -> None:
        self.pipeline_events.append({"ms": ms, "kind": kind, "message": message})

    def log_error(self, ms: int, error: str) -> None:
        self.pipeline_events.append({"ms": ms, "kind": "ERROR", "message": error})

    def finish(self, ended_at: str = "") -> Path:
        """Generate the debug HTML report and write all logs to disk."""
        self.output_dir.mkdir(parents=True, exist_ok=True)

        with open(self.output_dir / "config-snapshot.json", "w", encoding="utf-8") as f:
            json.dump(self.config_snapshot, f, indent=2)

        with open(self.output_dir / "vad-timeline.json", "w", encoding="utf-8") as f:
            json.dump(self.vad_events, f, indent=2)

        with open(self.output_dir / "pipeline-events.json", "w", encoding="utf-8") as f:
            json.dump(self.pipeline_events, f, indent=2)

        with open(self.output_dir / "debug-meta.json", "w", encoding="utf-8") as f:
            json.dump(
                {
                    "dropped_utterances": self.dropped_utterances,
                    "dropped_vad_events": self.dropped_vad_events,
                },
                f,
                indent=2,
            )

        with open(self.output_dir / "utterances.json", "w", encoding="utf-8") as f:
            json.dump(self.utterances, f, indent=2)

        html = generate_debug_html(
            session_id=self.session_id,
            started_at=self.started_at,
            ended_at=ended_at,
            config_snapshot=self.config_snapshot,
            utterances=self.utterances,
            vad_events=self.vad_events,
            pipeline_events=self.pipeline_events,
            queue_items=self.queue_items,
        )
        html_path = self.output_dir / "debug-report.html"
        html_path.write_text(html, encoding="utf-8")
        return html_path


def start_debug_session(
    session_id: str,
    config_snapshot: dict[str, Any],
) -> DebugSession | None:
    if not _debug_enabled():
        return None
    output_dir = _debug_dir() / f"{_now_iso()}-{session_id}"
    return DebugSession(
        session_id=session_id,
        output_dir=output_dir,
        config_snapshot=config_snapshot,
    )
