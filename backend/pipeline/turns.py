from __future__ import annotations

"""Helpers for converting diarization output into non-overlapping speaker turns."""

from dataclasses import dataclass

import numpy as np

from ..providers.diarization import DiarizationSegment


@dataclass
class TurnSlice:
    """A non-overlapping diarized speaker turn ready for per-turn ASR."""

    speaker_label: str
    start_s: float
    end_s: float
    started_ms: int
    ended_ms: int
    audio: np.ndarray


def slice_audio(
    audio: np.ndarray,
    start_s: float,
    end_s: float,
    sample_rate: int,
) -> np.ndarray:
    start_idx = max(0, min(len(audio), int(round(start_s * sample_rate))))
    end_idx = max(start_idx, min(len(audio), int(round(end_s * sample_rate))))
    return np.ascontiguousarray(audio[start_idx:end_idx], dtype=np.float32)


def _clip_diarized_segments(
    diarized_segments: list[DiarizationSegment],
    total_duration_s: float,
) -> list[tuple[int, float, float, str, float]]:
    clipped: list[tuple[int, float, float, str, float]] = []
    for idx, diarized in enumerate(diarized_segments):
        start_s = max(0.0, min(total_duration_s, float(diarized.start)))
        end_s = max(0.0, min(total_duration_s, float(diarized.end)))
        if end_s <= start_s:
            continue
        speaker_label = diarized.speaker or f"speaker-{idx}"
        clipped.append((idx, start_s, end_s, speaker_label, end_s - start_s))
    return clipped


def _make_turn_slice(
    audio: np.ndarray,
    sample_rate: int,
    base_started_ms: int,
    speaker_label: str,
    start_s: float,
    end_s: float,
) -> TurnSlice | None:
    turn_audio = slice_audio(audio, start_s, end_s, sample_rate)
    if turn_audio.size == 0:
        return None
    started_ms = base_started_ms + int(round(start_s * 1000.0))
    ended_ms = base_started_ms + int(round(end_s * 1000.0))
    if ended_ms <= started_ms:
        ended_ms = started_ms + max(
            1,
            int(round((turn_audio.size / sample_rate) * 1000.0)) if sample_rate > 0 else 1,
        )
    return TurnSlice(
        speaker_label=speaker_label,
        start_s=float(start_s),
        end_s=float(end_s),
        started_ms=int(started_ms),
        ended_ms=int(ended_ms),
        audio=turn_audio,
    )


def build_turn_slices(
    audio: np.ndarray,
    sample_rate: int,
    started_ms: int,
    diarized_segments: list[DiarizationSegment],
) -> list[TurnSlice]:
    """Normalize diarization output into non-overlapping speaker turns."""
    total_duration_s = (len(audio) / sample_rate) if sample_rate > 0 else 0.0
    if total_duration_s <= 0.0:
        return []

    clipped = _clip_diarized_segments(diarized_segments, total_duration_s)
    if not clipped:
        fallback = _make_turn_slice(
            audio, sample_rate, started_ms, "speaker-0", 0.0, total_duration_s
        )
        return [fallback] if fallback is not None else []

    boundaries = sorted(
        {
            0.0,
            total_duration_s,
            *[start_s for _, start_s, _, _, _ in clipped],
            *[end_s for _, _, end_s, _, _ in clipped],
        }
    )
    atomic: list[tuple[str, float, float]] = []
    for left, right in zip(boundaries, boundaries[1:]):
        if right <= left:
            continue
        active = [
            segment
            for segment in clipped
            if segment[1] < right and segment[2] > left
        ]
        if not active:
            continue
        chosen = min(
            active,
            key=lambda item: (
                -item[4],
                item[1],
                item[0],
            ),
        )
        atomic.append((chosen[3], left, right))

    if not atomic:
        fallback = _make_turn_slice(
            audio, sample_rate, started_ms, "speaker-0", 0.0, total_duration_s
        )
        return [fallback] if fallback is not None else []

    merged: list[tuple[str, float, float]] = []
    eps = 1e-6
    for speaker_label, left, right in atomic:
        if merged and merged[-1][0] == speaker_label and abs(merged[-1][2] - left) <= eps:
            merged[-1] = (speaker_label, merged[-1][1], right)
        else:
            merged.append((speaker_label, left, right))

    turns: list[TurnSlice] = []
    for speaker_label, left, right in merged:
        turn = _make_turn_slice(
            audio,
            sample_rate,
            started_ms,
            speaker_label,
            left,
            right,
        )
        if turn is not None:
            turns.append(turn)
    if turns:
        return turns

    fallback = _make_turn_slice(
        audio, sample_rate, started_ms, "speaker-0", 0.0, total_duration_s
    )
    return [fallback] if fallback is not None else []


def speaker_groups(turns: list[TurnSlice]) -> list[tuple[str, np.ndarray, int]]:
    """Group turn audio by speaker label and concatenate per speaker."""
    if not turns:
        return []

    chunks_by_speaker: dict[str, list[np.ndarray]] = {}
    lengths_by_speaker: dict[str, int] = {}
    speaker_order: list[str] = []
    for idx, turn in enumerate(turns):
        speaker_label = turn.speaker_label or f"speaker-{idx}"
        if turn.audio.size == 0:
            continue
        if speaker_label not in chunks_by_speaker:
            chunks_by_speaker[speaker_label] = []
            lengths_by_speaker[speaker_label] = 0
            speaker_order.append(speaker_label)
        chunks_by_speaker[speaker_label].append(turn.audio)
        lengths_by_speaker[speaker_label] += int(turn.audio.size)

    return [
        (
            speaker_label,
            np.ascontiguousarray(np.concatenate(chunks_by_speaker[speaker_label]), dtype=np.float32),
            lengths_by_speaker[speaker_label],
        )
        for speaker_label in speaker_order
    ]
