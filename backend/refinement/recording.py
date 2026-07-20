"""Disk-backed whole-session recording capture."""
from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
import shutil
import time
import wave
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)
_MIN_FREE_BYTES = 32 * 1024 * 1024
_SPACE_CHECK_INTERVAL_BYTES = 16 * 1024 * 1024


def recordings_root() -> Path:
    return Path.home() / ".voice-diary" / "recordings"


def _safe_part(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    if cleaned == value and cleaned:
        return cleaned
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]
    return f"{cleaned or 'session'}-{digest}"


class SessionAudioRecorder:
    """Incrementally writes normalized float audio to an atomic PCM16 WAV."""

    def __init__(self, session_id: str, source: str, sample_rate: int = 16000):
        directory = recordings_root() / _safe_part(session_id)
        directory.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(directory).free < _MIN_FREE_BYTES:
            raise OSError("not enough free disk space to retain session audio")
        self.session_id = session_id
        self.source = source
        self.sample_rate = sample_rate
        self.final_path = directory / f"{_safe_part(source)}.wav"
        self.partial_path = directory / f"{_safe_part(source)}.wav.part"
        self._samples = 0
        self._failed = False
        self._bytes_since_space_check = 0
        self._wav = wave.open(str(self.partial_path), "wb")
        self._wav.setnchannels(1)
        self._wav.setsampwidth(2)
        self._wav.setframerate(sample_rate)

    @property
    def failed(self) -> bool:
        return self._failed

    def write(self, audio: np.ndarray) -> bool:
        if self._failed or audio.size == 0:
            return not self._failed
        try:
            normalized = np.nan_to_num(
                np.asarray(audio, dtype=np.float32), nan=0.0, posinf=1.0, neginf=-1.0
            )
            pcm = (np.clip(normalized, -1.0, 1.0) * 32767.0).astype("<i2")
            self._bytes_since_space_check += int(pcm.nbytes)
            if self._bytes_since_space_check >= _SPACE_CHECK_INTERVAL_BYTES:
                if shutil.disk_usage(self.partial_path.parent).free < _MIN_FREE_BYTES:
                    raise OSError("not enough free disk space to continue retaining audio")
                self._bytes_since_space_check = 0
            self._wav.writeframesraw(pcm.tobytes())
            self._samples += int(pcm.size)
            return True
        except (OSError, wave.Error):
            self._failed = True
            log.exception("session recording write failed for %s/%s", self.session_id, self.source)
            return False

    def finish(self) -> tuple[Path, int, int] | None:
        try:
            self._wav.close()
            if self._failed or self._samples <= 0:
                self.partial_path.unlink(missing_ok=True)
                return None
            self.partial_path.replace(self.final_path)
            duration_ms = int(round(self._samples * 1000 / self.sample_rate))
            return self.final_path, duration_ms, self.final_path.stat().st_size
        except (OSError, wave.Error):
            self._failed = True
            log.exception("session recording finalize failed for %s/%s", self.session_id, self.source)
            return None

    def abort(self) -> None:
        try:
            self._wav.close()
        finally:
            self.partial_path.unlink(missing_ok=True)


def save_recording_metadata(
    conn: sqlite3.Connection,
    session_id: str,
    source: str,
    path: Path,
    duration_ms: int,
    size_bytes: int,
) -> None:
    conn.execute(
        """
        INSERT INTO session_recordings
            (session_id, source, path, duration_ms, size_bytes, status, created_at)
        VALUES (?, ?, ?, ?, ?, 'ready', ?)
        ON CONFLICT(session_id, source) DO UPDATE SET
            path = excluded.path,
            duration_ms = excluded.duration_ms,
            size_bytes = excluded.size_bytes,
            status = 'ready',
            created_at = excluded.created_at
        """,
        (session_id, source, str(path), duration_ms, size_bytes, int(time.time())),
    )
    conn.commit()


def cleanup_partial_recordings() -> None:
    root = recordings_root()
    if not root.exists():
        return
    for partial in root.glob("*/*.wav.part"):
        try:
            partial.unlink()
        except OSError:
            log.warning("could not remove interrupted recording %s", partial)
