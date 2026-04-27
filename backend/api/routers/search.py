"""FTS5 search REST endpoint."""
from __future__ import annotations

import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, Query

from ...storage.search_repo import SearchRepo
from ..deps import get_db
from ..schemas import SearchResponse

router = APIRouter()


@router.get("", response_model=SearchResponse)
def search(
    q: str = Query(..., min_length=1),
    session_id: Optional[str] = None,
    speaker_id: Optional[str] = None,
    language: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    conn: sqlite3.Connection = Depends(get_db),
):
    hits = SearchRepo(conn).search(
        q,
        session_id=session_id,
        speaker_id=speaker_id,
        language=language,
        limit=limit,
    )
    return SearchResponse(query=q, total=len(hits), hits=hits)
