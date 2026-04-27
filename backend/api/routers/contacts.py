"""Contact REST endpoints."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from ...models import Person
from ...storage.contact_repo import ContactRepo
from ...storage.session_repo import SessionRepo
from ..deps import get_db
from ..schemas import (
    ContactCreate,
    ContactMergeRequest,
    ContactOut,
    ContactUpdate,
    UtteranceOut,
)

router = APIRouter()


@router.get("", response_model=list[ContactOut])
def list_contacts(conn: sqlite3.Connection = Depends(get_db)):
    return ContactRepo(conn).list_contacts()


@router.post("", response_model=ContactOut, status_code=201)
def create_contact(payload: ContactCreate, conn: sqlite3.Connection = Depends(get_db)):
    person = Person(name=payload.name, notes=payload.notes)
    return ContactRepo(conn).create_contact(person)


@router.get("/{contact_id}", response_model=ContactOut)
def get_contact(contact_id: str, conn: sqlite3.Connection = Depends(get_db)):
    c = ContactRepo(conn).get_contact(contact_id)
    if not c:
        raise HTTPException(status_code=404, detail="contact not found")
    return c


@router.patch("/{contact_id}", response_model=ContactOut)
def update_contact(
    contact_id: str,
    payload: ContactUpdate,
    conn: sqlite3.Connection = Depends(get_db),
):
    updated = ContactRepo(conn).update_contact(
        contact_id, name=payload.name, notes=payload.notes
    )
    if not updated:
        raise HTTPException(status_code=404, detail="contact not found")
    return updated


@router.delete("/{contact_id}", status_code=204)
def delete_contact(contact_id: str, conn: sqlite3.Connection = Depends(get_db)):
    ok = ContactRepo(conn).delete_contact(contact_id)
    if not ok:
        raise HTTPException(status_code=404, detail="contact not found")
    return None


@router.get("/{contact_id}/utterances", response_model=list[UtteranceOut])
def list_contact_utterances(
    contact_id: str, conn: sqlite3.Connection = Depends(get_db)
):
    if not ContactRepo(conn).get_contact(contact_id):
        raise HTTPException(status_code=404, detail="contact not found")
    return SessionRepo(conn).list_utterances_for_contact(contact_id)


@router.post("/{contact_id}/merge", response_model=ContactOut)
def merge_contact(
    contact_id: str,
    payload: ContactMergeRequest,
    conn: sqlite3.Connection = Depends(get_db),
):
    repo = ContactRepo(conn)
    if not repo.get_contact(contact_id):
        raise HTTPException(status_code=404, detail="target contact not found")
    if not repo.get_contact(payload.source_id):
        raise HTTPException(status_code=404, detail="source contact not found")
    result = repo.merge(contact_id, payload.source_id)
    assert result is not None
    return result
