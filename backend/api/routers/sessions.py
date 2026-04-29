"""Session + utterance REST endpoints."""
from __future__ import annotations

import sqlite3
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request

from ...identification.resolver import SpeakerResolver, SQLiteResolverStore
from ...models import RecordingSession, SpeakerSegment, Utterance, VoiceProfile
from ...storage.session_repo import SessionRepo
from ..deps import get_db
from ..schemas import (
    SessionCreate,
    SessionOut,
    SessionUpdate,
    UtteranceCandidateOut,
    UtteranceCandidatesOut,
    UtteranceCreate,
    UtteranceIdentifyRequest,
    UtteranceIdentifyResponse,
    UtteranceOut,
)

router = APIRouter()


@router.get("", response_model=list[SessionOut])
def list_sessions(conn: sqlite3.Connection = Depends(get_db)):
    return SessionRepo(conn).list_sessions()


@router.post("", response_model=SessionOut, status_code=201)
def create_session(payload: SessionCreate, conn: sqlite3.Connection = Depends(get_db)):
    session = RecordingSession(
        title=payload.title,
        language_hint=payload.language_hint,
        notes=payload.notes,
    )
    return SessionRepo(conn).create_session(session)


@router.get("/{session_id}", response_model=SessionOut)
def get_session(session_id: str, conn: sqlite3.Connection = Depends(get_db)):
    session = SessionRepo(conn).get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    return session


@router.patch("/{session_id}", response_model=SessionOut)
def update_session(
    session_id: str,
    payload: SessionUpdate,
    conn: sqlite3.Connection = Depends(get_db),
):
    updated = SessionRepo(conn).update_session(
        session_id,
        title=payload.title,
        ended_at=payload.ended_at,
        notes=payload.notes,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="session not found")
    return updated


@router.delete("/{session_id}", status_code=204)
def delete_session(session_id: str, conn: sqlite3.Connection = Depends(get_db)):
    ok = SessionRepo(conn).delete_session(session_id)
    if not ok:
        raise HTTPException(status_code=404, detail="session not found")
    return None


@router.get("/{session_id}/utterances", response_model=list[UtteranceOut])
def list_utterances(session_id: str, conn: sqlite3.Connection = Depends(get_db)):
    repo = SessionRepo(conn)
    if not repo.get_session(session_id):
        raise HTTPException(status_code=404, detail="session not found")
    return repo.list_utterances(session_id)


@router.post(
    "/{session_id}/utterances", response_model=UtteranceOut, status_code=201
)
def create_utterance(
    session_id: str,
    payload: UtteranceCreate,
    conn: sqlite3.Connection = Depends(get_db),
):
    if payload.session_id != session_id:
        raise HTTPException(status_code=400, detail="session_id mismatch")
    repo = SessionRepo(conn)
    if not repo.get_session(session_id):
        raise HTTPException(status_code=404, detail="session not found")
    utt = Utterance(
        session_id=session_id,
        started_ms=payload.started_ms,
        ended_ms=payload.ended_ms,
        transcript=payload.transcript,
        language=payload.language,
        confidence=payload.confidence,
        speaker_segment_id=payload.speaker_segment_id,
    )
    return repo.create_utterance(utt)


# ---- Inline utterance identification ----


@router.get("/utterances/{utterance_id}/candidates", response_model=UtteranceCandidatesOut)
def get_utterance_candidates(
    utterance_id: str,
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
):
    repo = SessionRepo(conn)
    utt = repo.get_utterance(utterance_id)
    if utt is None:
        raise HTTPException(status_code=404, detail="utterance not found")
    segment_id = utt.get("speaker_segment_id")
    if not segment_id:
        return UtteranceCandidatesOut(
            candidates=[], source=utt.get("source") or "mic", has_embedding=False
        )

    resolver = SpeakerResolver(
        SQLiteResolverStore(conn),
        embedding_model_id=request.app.state.config.providers.embedding_model_id,
    )
    segment = resolver.load_segment(segment_id)
    if segment is None or segment.embedding.size == 0:
        return UtteranceCandidatesOut(
            candidates=[], source=segment.source if segment else "mic", has_embedding=False
        )

    candidates = resolver.get_candidates(segment)
    return UtteranceCandidatesOut(
        candidates=[
            UtteranceCandidateOut(contact_id=cid, contact_name=name, score=score)
            for cid, score, name in candidates
        ],
        source=segment.source,
        has_embedding=True,
    )


@router.post("/utterances/{utterance_id}/identify", response_model=UtteranceIdentifyResponse)
def identify_utterance(
    utterance_id: str,
    payload: UtteranceIdentifyRequest,
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
):
    repo = SessionRepo(conn)
    utt = repo.get_utterance(utterance_id)
    if utt is None:
        raise HTTPException(status_code=404, detail="utterance not found")

    segment_id = utt.get("speaker_segment_id")
    session_id = utt["session_id"]
    if not segment_id:
        return UtteranceIdentifyResponse(updated_count=0)

    resolver = SpeakerResolver(
        SQLiteResolverStore(conn),
        embedding_model_id=request.app.state.config.providers.embedding_model_id,
    )
    segment = resolver.load_segment(segment_id)
    if segment is None:
        return UtteranceIdentifyResponse(updated_count=0)

    # Idempotency: already assigned
    if segment.status == "identified":
        if segment.contact_id == payload.contact_id:
            return UtteranceIdentifyResponse(updated_count=1)
        raise HTTPException(
            status_code=409, detail="utterance already assigned to a different contact"
        )

    # Assign contact to segment
    conn.execute(
        "UPDATE speaker_segments SET contact_id = ?, status = 'identified' "
        "WHERE id = ?",
        (payload.contact_id, segment_id),
    )

    # Create voice profile from embedding if available
    embedding_model_id = request.app.state.config.providers.embedding_model_id
    if segment.embedding.size > 0:
        profile = VoiceProfile(
            contact_id=payload.contact_id,
            embedding=segment.embedding,
            model_id=embedding_model_id or "ecapa",
            embedding_dim=int(segment.embedding.size),
            source=segment.source,
            source_session_id=session_id,
        )
        conn.execute(
            "INSERT INTO voice_profiles "
            "(id, contact_id, embedding, model_id, embedding_dim, "
            "quality_score, recorded_at, source_session_id, source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                profile.contact_id,
                profile.embedding.astype("float32").tobytes(),
                profile.model_id,
                profile.embedding_dim,
                profile.quality_score or 0.0,
                int(profile.recorded_at.timestamp()),
                profile.source_session_id,
                profile.source,
            ),
        )

    conn.commit()

    # Session-scoped cascade: re-resolve other unknown segments in this session
    threshold = request.app.state.config.pipeline.speaker_identification_threshold
    cascaded = 0
    for row in repo.list_unknown_segments(session_id):
        if row["id"] == segment_id:
            continue
        emb = row["embedding"]
        if emb is None:
            continue
        import numpy as np

        emb_arr = np.frombuffer(emb if isinstance(emb, bytes) else bytes(emb), dtype=np.float32)
        if emb_arr.size == 0:
            continue
        probe = SpeakerSegment(
            id=row["id"],
            session_id=row["session_id"],
            embedding=emb_arr,
            source=row.get("source") or "mic",
        )
        match = resolver.resolve(probe, threshold=threshold)
        if match is None:
            continue
        conn.execute(
            "UPDATE speaker_segments SET contact_id = ?, status = 'identified' "
            "WHERE id = ?",
            (match, row["id"]),
        )
        cascaded += 1

    if cascaded:
        conn.commit()

    return UtteranceIdentifyResponse(updated_count=1, cascaded_count=cascaded)
