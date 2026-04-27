"""Session + utterance REST endpoints."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from ...models import RecordingSession, Utterance
from ...storage.session_repo import SessionRepo
from ..deps import get_db
from ..schemas import (
    SessionCreate,
    SessionOut,
    SessionUpdate,
    UtteranceCreate,
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
