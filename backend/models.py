"""Domain model entities."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import numpy as np


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Person:
    """Known person in the contact book."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    notes: str = ""
    created_at: datetime = field(default_factory=_utc_now)


@dataclass
class VoiceProfile:
    """Stored voiceprint for a person."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    contact_id: str = ""
    embedding: np.ndarray = field(default_factory=lambda: np.array([], dtype=np.float32))
    model_id: str = "ecapa"
    embedding_dim: int = 0
    quality_score: float = 0.0
    recorded_at: datetime = field(default_factory=_utc_now)
    source_session_id: Optional[str] = None
    source: str = "mic"


@dataclass
class RecordingSession:
    """A recording session."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    title: str = ""
    started_at: datetime = field(default_factory=_utc_now)
    ended_at: Optional[datetime] = None
    notes: str = ""
    language_hint: Optional[str] = None


@dataclass
class Utterance:
    """Speech segment with transcript."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    started_ms: int = 0
    ended_ms: int = 0
    transcript: str = ""
    language: Optional[str] = None
    confidence: float = 0.0
    speaker_segment_id: Optional[str] = None
    speaker_contact_id: Optional[str] = None
    source: str = "mic"


@dataclass
class SpeakerSegment:
    """Speaker identification data."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    contact_id: Optional[str] = None
    status: str = "unknown"  # identified, unknown, rejected
    embedding: np.ndarray = field(default_factory=lambda: np.array([], dtype=np.float32))
    diarization_model_id: str = "pyannote"
    sim_score: float = 0.0
    reviewed_at: Optional[datetime] = None
    source: str = "mic"


@dataclass
class UnresolvedSpeaker:
    """Unresolved speaker awaiting manual mapping."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    speaker_segment_id: str = ""
    created_at: datetime = field(default_factory=_utc_now)
    resolved_contact_id: Optional[str] = None
    resolved_at: Optional[datetime] = None
