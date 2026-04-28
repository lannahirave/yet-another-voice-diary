"""Pydantic request/response schemas — server-side domain, shaped for the REST surface."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

# ---------- Sessions ----------

class SessionCreate(BaseModel):
    title: str = ""
    language_hint: Optional[str] = None
    notes: str = ""


class SessionUpdate(BaseModel):
    title: Optional[str] = None
    ended_at: Optional[datetime] = None
    notes: Optional[str] = None


class SessionOut(BaseModel):
    id: str
    title: str
    started_at: datetime
    ended_at: Optional[datetime] = None
    notes: str = ""
    language_hint: Optional[str] = None
    utterance_count: int = 0
    speakers: list[str] = Field(default_factory=list)


class UtteranceOut(BaseModel):
    id: str
    session_id: str
    started_ms: int
    ended_ms: int
    transcript: str
    language: Optional[str] = None
    confidence: float = 0.0
    speaker_segment_id: Optional[str] = None
    speaker_contact_id: Optional[str] = None
    source: str = "mic"
    session_started_at: Optional[datetime] = None


class UtteranceCreate(BaseModel):
    session_id: str
    started_ms: int
    ended_ms: int
    transcript: str
    language: Optional[str] = None
    confidence: float = 0.0
    speaker_segment_id: Optional[str] = None


# ---------- Contacts ----------

class ContactCreate(BaseModel):
    name: str
    notes: str = ""


class ContactUpdate(BaseModel):
    name: Optional[str] = None
    notes: Optional[str] = None


class ContactOut(BaseModel):
    id: str
    name: str
    notes: str = ""
    created_at: datetime
    profile_count: int = 0
    session_count: int = 0
    confidence: float = 0.0
    """Mean pairwise cosine across this contact's voice profiles, in [0,1].

    Higher = the enrolled profiles are mutually consistent → reliable
    identification. 0 when fewer than two profiles exist (the UI treats this
    as "voiceprint not yet computed").
    """


class ContactMergeRequest(BaseModel):
    source_id: str  # contact to merge INTO the path-id target


# ---------- Unknown Queue ----------

class QueueCandidate(BaseModel):
    contact_id: str
    contact_name: str
    score: float


class QueueItemOut(BaseModel):
    id: str
    speaker_segment_id: str
    session_id: str
    created_at: datetime
    resolved_contact_id: Optional[str] = None
    resolved_at: Optional[datetime] = None
    candidates: list[QueueCandidate] = Field(default_factory=list)


class QueueClusterOut(BaseModel):
    """A group of queue rows whose voiceprints are mutually close.

    Frontend renders one card per cluster. ``queue_ids`` carries the items the
    cluster represents; resolve/skip operate on this list so a single user
    decision applies to every fragment of the same speaker.
    """

    id: str
    queue_ids: list[str]
    segment_ids: list[str]
    session_ids: list[str]
    session_titles: list[str] = Field(default_factory=list)
    created_at: datetime
    fragment_count: int
    duration_ms: int
    quote: str = ""
    source: str = "mic"
    candidates: list[QueueCandidate] = Field(default_factory=list)


class QueueResolveRequest(BaseModel):
    contact_id: str
    queue_ids: Optional[list[str]] = None  # batch path; if None, route uses path id


class QueueSkipRequest(BaseModel):
    queue_ids: list[str]


class QueueResolveResponse(BaseModel):
    resolved_count: int
    cascaded_count: int = 0


# ---------- Search ----------

class SearchHit(BaseModel):
    utterance_id: str
    session_id: str
    session_title: str
    transcript: str
    language: Optional[str] = None
    started_ms: int
    snippet: str


class SearchResponse(BaseModel):
    query: str
    total: int
    hits: list[SearchHit]


# ---------- Config ----------

class ProviderStatus(BaseModel):
    kind: str  # "asr" | "embedding" | "diarization" | "vad"
    model_id: str
    state: str  # "UNLOADED" | "LOADING" | "LOADED" | "ERROR"
    error: Optional[str] = None


class ConfigOut(BaseModel):
    vad_threshold: float
    vad_min_silence_ms: int
    vad_speech_pad_ms: int
    vad_min_utterance_ms: int
    vad_max_utterance_ms: int
    speaker_identification_threshold: float
    chunk_duration_ms: int
    unload_models_after_stop: bool = False
    preload_on_start: bool = False
    providers: list[ProviderStatus]


class ThresholdUpdate(BaseModel):
    value: float


class UnloadAfterStopUpdate(BaseModel):
    value: bool


class PreloadOnStartUpdate(BaseModel):
    value: bool


class StorageInfoOut(BaseModel):
    db_path: str
    db_size_bytes: int
    exists: bool


class ProviderSelect(BaseModel):
    model_id: str


class ModelDownloadEvent(BaseModel):
    kind: str
    model_id: str
    progress: float
    state: str
    message: str = ""
