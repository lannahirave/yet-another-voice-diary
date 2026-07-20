"""Serialized, durable full-session refinement jobs."""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
import uuid
import wave
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from ..identification.matching import SimilarityMatcher
from ..models import SpeakerSegment
from ..providers.diarization import DiarizationSegment
from ..providers.itn import normalize_transcript

log = logging.getLogger(__name__)
SAMPLE_RATE = 16000
WINDOW_SAMPLES = 120 * SAMPLE_RATE
OVERLAP_SAMPLES = 10 * SAMPLE_RATE
READ_CHUNK_SAMPLES = 1600


class RefinementCancelled(RuntimeError):
    pass


@dataclass
class TimelineTurn:
    start_sample: int
    end_sample: int
    speaker: str


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _process_rss_bytes() -> int:
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            class Counters(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
                    ("PrivateUsage", ctypes.c_size_t),
                ]
            counters = Counters()
            counters.cb = ctypes.sizeof(counters)
            ctypes.windll.psapi.GetProcessMemoryInfo(
                ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
            )
            return int(counters.WorkingSetSize)
        statm = Path("/proc/self/statm")
        if statm.exists():
            resident_pages = int(statm.read_text(encoding="ascii").split()[1])
            return resident_pages * int(os.sysconf("SC_PAGE_SIZE"))
    except Exception:
        return 0
    return 0


def _wav_info(path: Path) -> tuple[int, int]:
    with wave.open(str(path), "rb") as wav:
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
            raise ValueError(f"unsupported recording format: {path}")
        return wav.getframerate(), wav.getnframes()


def _read_wav(path: Path, start: int, count: int) -> np.ndarray:
    with wave.open(str(path), "rb") as wav:
        wav.setpos(max(0, min(start, wav.getnframes())))
        raw = wav.readframes(max(0, count))
    if not raw:
        return np.array([], dtype=np.float32)
    return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0


def _iter_wav_chunks(path: Path, chunk_samples: int) -> Iterable[np.ndarray]:
    with wave.open(str(path), "rb") as wav:
        while True:
            raw = wav.readframes(chunk_samples)
            if not raw:
                return
            yield np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0


def _cosine(left: np.ndarray, right: np.ndarray) -> float:
    denom = float(np.linalg.norm(left) * np.linalg.norm(right))
    return float(np.dot(left, right) / denom) if denom > 0 else -1.0


def _merge_turns(turns: list[TimelineTurn]) -> list[TimelineTurn]:
    merged: list[TimelineTurn] = []
    for turn in sorted(turns, key=lambda item: (item.start_sample, item.end_sample)):
        if turn.end_sample <= turn.start_sample:
            continue
        if (
            merged
            and merged[-1].speaker == turn.speaker
            and turn.start_sample <= merged[-1].end_sample + int(0.15 * SAMPLE_RATE)
        ):
            merged[-1].end_sample = max(merged[-1].end_sample, turn.end_sample)
        else:
            merged.append(turn)
    return merged


def _normalize_turns(turns: list[TimelineTurn]) -> list[TimelineTurn]:
    """Collapse overlapping model output into deterministic speaker turns."""
    if not turns:
        return []
    boundaries = sorted({value for turn in turns for value in (turn.start_sample, turn.end_sample)})
    atomic: list[TimelineTurn] = []
    for left, right in zip(boundaries, boundaries[1:]):
        active = [turn for turn in turns if turn.start_sample < right and turn.end_sample > left]
        if not active:
            continue
        chosen = min(
            active,
            key=lambda turn: (-(turn.end_sample - turn.start_sample), turn.start_sample, turn.speaker),
        )
        atomic.append(TimelineTurn(left, right, chosen.speaker))
    return _merge_turns(atomic)


def _merge_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for left, right in sorted(intervals):
        if right <= left:
            continue
        if merged and left <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], right))
        else:
            merged.append((left, right))
    return merged


def _intersections(
    start: int, end: int, speech: list[tuple[int, int]]
) -> Iterable[tuple[int, int]]:
    for left, right in speech:
        if right <= start:
            continue
        if left >= end:
            break
        clipped_left, clipped_right = max(start, left), min(end, right)
        if clipped_right > clipped_left:
            yield clipped_left, clipped_right


class RefinementManager:
    """Runs one refinement job at a time against shared ML providers."""

    def __init__(self, app: Any):
        self.app = app
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="refinement")
        self._lock = threading.Lock()
        self._active_job_id: str | None = None
        self._job_started_perf = 0.0
        self._job_peak_rss = 0
        self._metric_stage: str | None = None
        self._metric_stage_started = 0.0
        self._stage_timings: dict[str, float] = {}

    def latest(self, session_id: str) -> dict[str, Any] | None:
        with closing(_connect(Path(self.app.state.config.database.path))) as conn:
            row = conn.execute(
                "SELECT * FROM refinement_jobs WHERE session_id = ? ORDER BY created_at DESC LIMIT 1",
                (session_id,),
            ).fetchone()
            if row is None:
                return None
            result = dict(row)
            result["metrics"] = json.loads(result.get("metrics_json") or "{}")
            return result

    def submit(self, session_id: str) -> dict[str, Any]:
        cfg = self.app.state.config
        snapshot = json.dumps(
            {"pipeline": asdict(cfg.pipeline), "providers": asdict(cfg.providers)},
            ensure_ascii=True,
        )
        job_id = str(uuid.uuid4())
        now = int(time.time())
        with closing(_connect(Path(cfg.database.path))) as conn:
            recordings = conn.execute(
                "SELECT source, path FROM session_recordings WHERE session_id = ? AND status = 'ready'",
                (session_id,),
            ).fetchall()
            if not recordings:
                raise ValueError("no retained recording is available")
            try:
                conn.execute(
                    """
                    INSERT INTO refinement_jobs
                        (id, session_id, status, stage, progress, config_snapshot, created_at)
                    VALUES (?, ?, 'queued', 'queued', 0, ?, ?)
                    """,
                    (job_id, session_id, snapshot, now),
                )
                conn.commit()
            except sqlite3.IntegrityError as exc:
                raise RuntimeError("a refinement job is already active for this session") from exc
        self._executor.submit(self._run, job_id)
        result = self.latest(session_id)
        assert result is not None
        return result

    def cancel(self, session_id: str) -> dict[str, Any] | None:
        with closing(_connect(Path(self.app.state.config.database.path))) as conn:
            cursor = conn.execute(
                """
                UPDATE refinement_jobs SET cancel_requested = 1
                WHERE id = (
                    SELECT id FROM refinement_jobs
                    WHERE session_id = ? AND status IN ('queued', 'running')
                    ORDER BY created_at DESC LIMIT 1
                )
                """,
                (session_id,),
            )
            conn.commit()
            if cursor.rowcount == 0:
                return None
        return self.latest(session_id)

    def has_active_job(self) -> bool:
        with closing(_connect(Path(self.app.state.config.database.path))) as conn:
            row = conn.execute(
                "SELECT 1 FROM refinement_jobs WHERE status IN ('queued', 'running') LIMIT 1"
            ).fetchone()
            return row is not None

    def _check_cancelled(self, conn: sqlite3.Connection, job_id: str) -> None:
        row = conn.execute(
            "SELECT cancel_requested FROM refinement_jobs WHERE id = ?", (job_id,)
        ).fetchone()
        if row and row[0]:
            raise RefinementCancelled()

    def _progress(
        self,
        conn: sqlite3.Connection,
        job_id: str,
        stage: str,
        progress: float,
        *,
        source: str | None = None,
        processed: int = 0,
        total: int = 0,
    ) -> None:
        now_perf = time.perf_counter()
        if self._metric_stage != stage:
            if self._metric_stage is not None:
                elapsed = now_perf - self._metric_stage_started
                self._stage_timings[self._metric_stage] = self._stage_timings.get(self._metric_stage, 0.0) + elapsed
            self._metric_stage = stage
            self._metric_stage_started = now_perf
        self._job_peak_rss = max(self._job_peak_rss, _process_rss_bytes())
        conn.execute(
            """
            UPDATE refinement_jobs
            SET stage = ?, progress = ?, current_source = ?,
                processed_items = ?, total_items = ?
            WHERE id = ?
            """,
            (stage, max(0.0, min(1.0, progress)), source, processed, total, job_id),
        )
        conn.commit()

    def _wait_for_idle_recording(self, conn: sqlite3.Connection, job_id: str) -> None:
        while True:
            self._check_cancelled(conn, job_id)
            with self.app.state.active_recordings_lock:
                active = bool(self.app.state.active_recordings)
            if not active:
                return
            time.sleep(0.25)

    def _run(self, job_id: str) -> None:
        db_path = Path(self.app.state.config.database.path)
        conn = _connect(db_path)
        with self._lock:
            self._active_job_id = job_id
        self._job_started_perf = 0.0
        self._job_peak_rss = 0
        self._metric_stage = None
        self._metric_stage_started = 0.0
        self._stage_timings = {}
        try:
            self._wait_for_idle_recording(conn, job_id)
            row = conn.execute("SELECT * FROM refinement_jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                return
            session_id = str(row["session_id"])
            snapshot = json.loads(row["config_snapshot"])
            conn.execute(
                "UPDATE refinement_jobs SET status = 'running', stage = 'vad', started_at = ? WHERE id = ?",
                (int(time.time()), job_id),
            )
            conn.commit()
            self._job_started_perf = time.perf_counter()
            self._job_peak_rss = _process_rss_bytes()
            self._metric_stage = "vad"
            self._metric_stage_started = self._job_started_perf
            self._stage_timings = {}
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.reset_peak_memory_stats()
            except Exception:
                pass
            recordings = conn.execute(
                "SELECT source, path FROM session_recordings WHERE session_id = ? ORDER BY source",
                (session_id,),
            ).fetchall()
            source_results: list[tuple[str, list[TimelineTurn], dict[str, np.ndarray]]] = []
            for source_index, recording in enumerate(recordings):
                source = str(recording["source"])
                path = Path(recording["path"])
                turns, embeddings = self._process_source(
                    conn, job_id, source, path, snapshot, source_index, len(recordings)
                )
                source_results.append((source, turns, embeddings))
            self._stage_results(conn, job_id, session_id, source_results, snapshot)
            self._promote(conn, job_id, session_id, snapshot)
            metrics = self._finish_metrics(conn, session_id)
            if snapshot["pipeline"].get("recording_retention") == "until_refined":
                self._delete_recordings(conn, session_id)
            conn.execute(
                """
                UPDATE refinement_jobs SET status = 'completed', stage = 'completed',
                    progress = 1, completed_at = ?, metrics_json = ? WHERE id = ?
                """,
                (int(time.time()), json.dumps(metrics), job_id),
            )
            conn.commit()
        except RefinementCancelled:
            self._finish_failed(conn, job_id, "cancelled", None)
        except Exception as exc:
            log.exception("full-session refinement failed job=%s", job_id)
            self._finish_failed(conn, job_id, "failed", str(exc))
        finally:
            with self._lock:
                self._active_job_id = None
            conn.close()

    def _process_source(
        self,
        conn: sqlite3.Connection,
        job_id: str,
        source: str,
        path: Path,
        snapshot: dict[str, Any],
        source_index: int,
        source_count: int,
    ) -> tuple[list[TimelineTurn], dict[str, np.ndarray]]:
        sample_rate, frame_count = _wav_info(path)
        if sample_rate != SAMPLE_RATE:
            raise ValueError(f"recording sample rate must be {SAMPLE_RATE} Hz")
        speech = self._run_vad(
            conn, job_id, source, path, frame_count, snapshot, source_index, source_count
        )
        turns, embeddings = self._run_diarization(
            conn, job_id, source, path, frame_count, speech, snapshot, source_index, source_count
        )
        return turns, embeddings

    def _run_vad(
        self,
        conn: sqlite3.Connection,
        job_id: str,
        source: str,
        path: Path,
        frame_count: int,
        snapshot: dict[str, Any],
        source_index: int,
        source_count: int,
    ) -> list[tuple[int, int]]:
        provider = self.app.state.providers["vad"]
        pipeline = snapshot["pipeline"]
        for name, value in (
            ("threshold", pipeline["vad_threshold"]),
            ("negative_threshold", pipeline["vad_negative_threshold"]),
            ("min_silence_ms", pipeline["vad_min_silence_ms"]),
            ("speech_pad_pre_ms", pipeline["vad_speech_pad_pre_ms"]),
            ("speech_pad_post_ms", pipeline["vad_speech_pad_post_ms"]),
            ("min_utterance_ms", pipeline["vad_min_utterance_ms"]),
            ("max_utterance_ms", pipeline["vad_max_utterance_ms"]),
        ):
            if hasattr(provider, name):
                setattr(provider, name, value)
        session = provider.create_session()
        session.max_utterance_ms = int(pipeline["vad_max_utterance_ms"])
        session.reset()
        speech: list[tuple[int, int]] = []
        processed = 0
        next_status_sample = 0
        for chunk in _iter_wav_chunks(path, READ_CHUNK_SAMPLES):
            segment = session.process(chunk, SAMPLE_RATE)
            processed += int(chunk.size)
            if segment is not None:
                speech.append((int(segment.started_ms * 16), int(segment.ended_ms * 16)))
            if processed >= next_status_sample or processed >= frame_count:
                self._check_cancelled(conn, job_id)
                overall = (source_index + processed / max(1, frame_count)) / source_count
                self._progress(conn, job_id, "vad", overall * 0.15, source=source, processed=processed, total=frame_count)
                next_status_sample = processed + 2 * SAMPLE_RATE
        final = session.finalize()
        if final is not None:
            speech.append((int(final.started_ms * 16), int(final.ended_ms * 16)))
        return _merge_intervals(speech)

    def _run_diarization(
        self,
        conn: sqlite3.Connection,
        job_id: str,
        source: str,
        path: Path,
        frame_count: int,
        speech: list[tuple[int, int]],
        snapshot: dict[str, Any],
        source_index: int,
        source_count: int,
    ) -> tuple[list[TimelineTurn], dict[str, np.ndarray]]:
        if not speech:
            return [], {}
        starts = list(range(0, frame_count, WINDOW_SAMPLES - OVERLAP_SAMPLES))
        global_turns: list[TimelineTurn] = []
        centroids: dict[str, np.ndarray] = {}
        counts: dict[str, int] = {}
        next_speaker = 0
        threshold = float(snapshot["pipeline"]["speaker_identification_threshold"])
        for index, start in enumerate(starts):
            self._check_cancelled(conn, job_id)
            audio = _read_wav(path, start, min(WINDOW_SAMPLES, frame_count - start))
            if audio.size == 0:
                continue
            diarized: list[DiarizationSegment] = self.app.state.providers["diarization"].segment(
                audio, SAMPLE_RATE
            )
            if not diarized:
                diarized = [DiarizationSegment(0.0, len(audio) / SAMPLE_RATE, "speaker-0")]
            local: dict[str, list[tuple[int, int]]] = {}
            for segment in diarized:
                left = start + max(0, int(segment.start * SAMPLE_RATE))
                right = start + min(len(audio), int(segment.end * SAMPLE_RATE))
                for masked_left, masked_right in _intersections(left, right, speech):
                    local.setdefault(segment.speaker, []).append((masked_left, masked_right))
            mappings: dict[str, str] = {}
            for local_name, intervals in local.items():
                samples = [
                    _read_wav(path, left, min(right - left, 6 * SAMPLE_RATE))
                    for left, right in intervals[:10]
                ]
                samples = [item for item in samples if item.size]
                if not samples:
                    continue
                embedding = self.app.state.providers["embedding"].embed(np.concatenate(samples))
                overlap_scores: dict[str, int] = {}
                for prior in global_turns:
                    for left, right in intervals:
                        overlap = max(0, min(prior.end_sample, right) - max(prior.start_sample, left))
                        if overlap:
                            overlap_scores[prior.speaker] = overlap_scores.get(prior.speaker, 0) + overlap
                chosen = max(overlap_scores, key=overlap_scores.get) if overlap_scores else None
                if chosen is None and centroids:
                    candidate, score = max(
                        ((name, _cosine(embedding, centroid)) for name, centroid in centroids.items()),
                        key=lambda item: item[1],
                    )
                    if score >= threshold:
                        chosen = candidate
                if chosen is None:
                    chosen = f"speaker-{next_speaker}"
                    next_speaker += 1
                mappings[local_name] = chosen
                count = counts.get(chosen, 0)
                centroids[chosen] = (
                    embedding if count == 0 else (centroids[chosen] * count + embedding) / (count + 1)
                )
                counts[chosen] = count + 1
            core_left = start if index == 0 else start + OVERLAP_SAMPLES // 2
            core_right = (
                start + len(audio)
                if index == len(starts) - 1
                else start + len(audio) - OVERLAP_SAMPLES // 2
            )
            for local_name, intervals in local.items():
                chosen = mappings.get(local_name)
                if chosen is None:
                    continue
                for left, right in intervals:
                    left, right = max(left, core_left), min(right, core_right)
                    if right > left:
                        global_turns.append(TimelineTurn(left, right, chosen))
            overall_source = (index + 1) / max(1, len(starts))
            progress = 0.15 + 0.40 * ((source_index + overall_source) / source_count)
            self._progress(conn, job_id, "diarization", progress, source=source, processed=index + 1, total=len(starts))
        return _normalize_turns(global_turns), centroids

    def _stage_results(
        self,
        conn: sqlite3.Connection,
        job_id: str,
        session_id: str,
        source_results: list[tuple[str, list[TimelineTurn], dict[str, np.ndarray]]],
        snapshot: dict[str, Any],
    ) -> None:
        total_turns = sum(len(turns) for _, turns, _ in source_results)
        asr = self.app.state.providers["asr"]
        pipeline_snapshot = snapshot["pipeline"]
        for name, value in (
            ("blocklist_enabled", pipeline_snapshot.get("blocklist_enabled", True)),
            ("no_speech_threshold", pipeline_snapshot.get("asr_no_speech_threshold", 0.6)),
            ("compression_ratio_threshold", pipeline_snapshot.get("asr_compression_ratio_threshold", 2.4)),
            ("repetition_penalty", pipeline_snapshot.get("asr_repetition_penalty", 1.1)),
            ("no_repeat_ngram_size", pipeline_snapshot.get("asr_no_repeat_ngram_size", 3)),
        ):
            if hasattr(asr, name):
                setattr(asr, name, value)
        completed = 0
        segment_ids: dict[tuple[str, str], str] = {}
        for source, turns, embeddings in source_results:
            used_speakers = {turn.speaker for turn in turns}
            for speaker, embedding in embeddings.items():
                if speaker not in used_speakers:
                    continue
                self._check_cancelled(conn, job_id)
                segment_id = str(uuid.uuid4())
                segment_ids[(source, speaker)] = segment_id
                contact_id, score = self._resolve_contact(
                    conn, session_id, source, embedding, snapshot["providers"]["embedding_model_id"],
                    float(snapshot["pipeline"]["speaker_identification_threshold"]),
                )
                conn.execute(
                    """
                    INSERT INTO refinement_speaker_segments
                        (job_id, id, session_id, contact_id, status, embedding,
                         diarization_model_id, sim_score, source)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job_id, segment_id, session_id, contact_id,
                        "identified" if contact_id else "unknown",
                        np.asarray(embedding, dtype=np.float32).tobytes(),
                        snapshot["providers"]["diarization_model_id"], score, source,
                    ),
                )
        conn.commit()
        self._progress(conn, job_id, "embedding", 0.65)
        max_samples = max(1, int(snapshot["pipeline"]["vad_max_utterance_ms"] * SAMPLE_RATE / 1000))
        min_samples = max(1, int(snapshot["pipeline"]["vad_min_utterance_ms"] * SAMPLE_RATE / 1000))
        for source, turns, _ in source_results:
            recording = conn.execute(
                "SELECT path FROM session_recordings WHERE session_id = ? AND source = ?",
                (session_id, source),
            ).fetchone()
            if recording is None:
                continue
            path = Path(recording["path"])
            for turn in turns:
                cursor = turn.start_sample
                while cursor < turn.end_sample:
                    self._check_cancelled(conn, job_id)
                    end = min(turn.end_sample, cursor + max_samples)
                    if end - cursor < min_samples:
                        break
                    audio = _read_wav(path, cursor, end - cursor)
                    utterance = asr.transcribe(audio, None)
                    utterance = self._apply_language_policy(audio, utterance, snapshot)
                    transcript = utterance.transcript
                    if snapshot["pipeline"].get("itn_enabled", True):
                        transcript = normalize_transcript(
                            transcript,
                            selected_maps=snapshot["pipeline"].get("itn_selected_maps"),
                        )
                    if transcript.strip():
                        conn.execute(
                            """
                            INSERT INTO refinement_utterances
                                (job_id, id, session_id, started_ms, ended_ms, transcript,
                                 language, confidence, speaker_segment_id, source)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                job_id, str(uuid.uuid4()), session_id,
                                int(cursor * 1000 / SAMPLE_RATE), int(end * 1000 / SAMPLE_RATE),
                                transcript, utterance.language, utterance.confidence,
                                segment_ids.get((source, turn.speaker)), source,
                            ),
                        )
                    cursor = end
                completed += 1
                progress = 0.65 + 0.30 * completed / max(1, total_turns)
                self._progress(conn, job_id, "transcription", progress, source=source, processed=completed, total=total_turns)
        conn.commit()

    def _apply_language_policy(self, audio: np.ndarray, utterance: Any, snapshot: dict[str, Any]) -> Any:
        pipeline = snapshot["pipeline"]
        if not pipeline.get("language_allowlist_enabled"):
            return utterance
        allowed = [item.strip() for item in pipeline.get("language_allowlist", "").split(",") if item.strip()]
        threshold = float(pipeline.get("language_confidence_threshold", 0.5))
        if not allowed or (
            utterance.confidence >= threshold and (not utterance.language or utterance.language in allowed)
        ):
            return utterance
        candidates = [utterance]
        for language in allowed:
            candidates.append(self.app.state.providers["asr"].transcribe(audio, language))
        return max(candidates, key=lambda item: item.confidence)

    def _resolve_contact(
        self,
        conn: sqlite3.Connection,
        session_id: str,
        source: str,
        embedding: np.ndarray,
        model_id: str,
        threshold: float,
    ) -> tuple[str | None, float | None]:
        rows = conn.execute(
            """
            SELECT contact_id, embedding FROM voice_profiles
            WHERE COALESCE(source, 'mic') = ? AND model_id = ?
              AND COALESCE(source_session_id, '') != ? AND embedding_dim = ?
            """,
            (source, model_id, session_id, int(embedding.size)),
        ).fetchall()
        candidates = [(row["contact_id"], np.frombuffer(row["embedding"], dtype=np.float32)) for row in rows]
        match = SimilarityMatcher().find_best_match(embedding, candidates, threshold=threshold)
        return (match[0], float(match[1])) if match else (None, None)

    def _promote(
        self,
        conn: sqlite3.Connection,
        job_id: str,
        session_id: str,
        snapshot: dict[str, Any],
    ) -> None:
        self._check_cancelled(conn, job_id)
        old_count = conn.execute(
            "SELECT COUNT(*) FROM utterances WHERE session_id = ?", (session_id,)
        ).fetchone()[0]
        staged_count = conn.execute(
            "SELECT COUNT(*) FROM refinement_utterances WHERE job_id = ?", (job_id,)
        ).fetchone()[0]
        if old_count and not staged_count:
            raise RuntimeError("refinement produced no utterances; live result was preserved")
        self._progress(conn, job_id, "committing", 0.96)
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                "DELETE FROM unknown_queue WHERE speaker_segment_id IN (SELECT id FROM speaker_segments WHERE session_id = ?)",
                (session_id,),
            )
            conn.execute("DELETE FROM voice_profiles WHERE source_session_id = ?", (session_id,))
            conn.execute("DELETE FROM utterances WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM speaker_segments WHERE session_id = ?", (session_id,))
            conn.execute(
                """
                INSERT INTO speaker_segments
                    (id, session_id, contact_id, status, embedding, diarization_model_id,
                     sim_score, source)
                SELECT id, session_id, contact_id, status, embedding, diarization_model_id,
                       sim_score, source
                FROM refinement_speaker_segments WHERE job_id = ?
                """,
                (job_id,),
            )
            conn.execute(
                """
                INSERT INTO utterances
                    (id, session_id, started_ms, ended_ms, transcript, language,
                     confidence, speaker_segment_id, source)
                SELECT id, session_id, started_ms, ended_ms, transcript, language,
                       confidence, speaker_segment_id, source
                FROM refinement_utterances WHERE job_id = ?
                """,
                (job_id,),
            )
            unknown_rows = conn.execute(
                "SELECT id, source FROM speaker_segments WHERE session_id = ? AND contact_id IS NULL",
                (session_id,),
            ).fetchall()
            now = int(time.time())
            conn.executemany(
                "INSERT INTO unknown_queue (id, speaker_segment_id, created_at, source) VALUES (?, ?, ?, ?)",
                [(str(uuid.uuid4()), row["id"], now, row["source"]) for row in unknown_rows],
            )
            conn.execute("DELETE FROM refinement_utterances WHERE job_id = ?", (job_id,))
            conn.execute("DELETE FROM refinement_speaker_segments WHERE job_id = ?", (job_id,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def _finish_failed(
        self, conn: sqlite3.Connection, job_id: str, status: str, error: str | None
    ) -> None:
        conn.execute("DELETE FROM refinement_utterances WHERE job_id = ?", (job_id,))
        conn.execute("DELETE FROM refinement_speaker_segments WHERE job_id = ?", (job_id,))
        metrics: dict[str, float] = {}
        row = conn.execute("SELECT session_id FROM refinement_jobs WHERE id = ?", (job_id,)).fetchone()
        if row is not None and self._job_started_perf:
            metrics = self._finish_metrics(conn, str(row["session_id"]))
        conn.execute(
            """
            UPDATE refinement_jobs SET status = ?, stage = ?, error = ?, completed_at = ?, metrics_json = ?
            WHERE id = ?
            """,
            (status, status, error, int(time.time()), json.dumps(metrics), job_id),
        )
        conn.commit()

    def _finish_metrics(self, conn: sqlite3.Connection, session_id: str) -> dict[str, float]:
        now_perf = time.perf_counter()
        if self._metric_stage is not None:
            elapsed = now_perf - self._metric_stage_started
            self._stage_timings[self._metric_stage] = self._stage_timings.get(self._metric_stage, 0.0) + elapsed
        wall = max(0.0, now_perf - self._job_started_perf)
        audio_ms = conn.execute(
            "SELECT COALESCE(SUM(duration_ms), 0) FROM session_recordings WHERE session_id = ?",
            (session_id,),
        ).fetchone()[0]
        audio_seconds = float(audio_ms) / 1000.0
        peak_vram = 0.0
        try:
            import torch
            if torch.cuda.is_available():
                peak_vram = float(torch.cuda.max_memory_allocated())
        except Exception:
            pass
        metrics: dict[str, float] = {
            "wall_time_seconds": wall,
            "audio_seconds": audio_seconds,
            "real_time_factor": wall / audio_seconds if audio_seconds > 0 else 0.0,
            "peak_ram_bytes": float(self._job_peak_rss),
            "peak_vram_bytes": peak_vram,
        }
        metrics.update({f"stage_{name}_seconds": value for name, value in self._stage_timings.items()})
        self._metric_stage = None
        return metrics

    def shutdown(self) -> None:
        with closing(_connect(Path(self.app.state.config.database.path))) as conn:
            conn.execute(
                "UPDATE refinement_jobs SET cancel_requested = 1 WHERE status = 'running'"
            )
            conn.execute(
                "UPDATE refinement_jobs SET status = 'cancelled', stage = 'cancelled', completed_at = ? WHERE status = 'queued'",
                (int(time.time()),),
            )
            conn.commit()
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _delete_recordings(self, conn: sqlite3.Connection, session_id: str) -> None:
        rows = conn.execute(
            "SELECT path FROM session_recordings WHERE session_id = ?", (session_id,)
        ).fetchall()
        for row in rows:
            try:
                Path(row["path"]).unlink(missing_ok=True)
            except OSError:
                log.exception("failed to delete retained recording %s", row["path"])
                return
        conn.execute("DELETE FROM session_recordings WHERE session_id = ?", (session_id,))
        conn.commit()

    def delete_recordings(self, session_id: str) -> bool:
        latest = self.latest(session_id)
        if latest and latest["status"] in {"queued", "running"}:
            raise RuntimeError("cannot delete recording while refinement is active")
        with closing(_connect(Path(self.app.state.config.database.path))) as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM session_recordings WHERE session_id = ?", (session_id,)
            ).fetchone()[0]
            self._delete_recordings(conn, session_id)
            return bool(count)
