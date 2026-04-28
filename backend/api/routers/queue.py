"""Unknown-queue REST endpoints.

The list endpoint groups unresolved fragments by voiceprint similarity so the
UI can present one card per likely person. Resolution operates on the whole
cluster and triggers a cascade pass that auto-identifies any other unresolved
segments now matching the freshly added contact.
"""
from __future__ import annotations

import sqlite3

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ...identification.clustering import centroid, cluster_embeddings
from ...identification.resolver import SpeakerResolver, SQLiteResolverStore
from ...models import SpeakerSegment
from ...storage.queue_repo import QueueRepo
from ..deps import get_db
from ..schemas import (
    QueueCandidate,
    QueueClusterOut,
    QueueItemOut,
    QueueResolveRequest,
    QueueResolveResponse,
    QueueSkipRequest,
)

router = APIRouter()


# Slightly tighter than the identification threshold: cluster merges should
# require strong evidence the two fragments are the *same* person.
_CLUSTER_MARGIN = 0.03


def _cluster_threshold(request: Request) -> float:
    cfg = request.app.state.config.pipeline
    return min(0.99, cfg.speaker_identification_threshold + _CLUSTER_MARGIN)


def _decode_embedding(blob) -> np.ndarray:
    if blob is None:
        return np.zeros(0, dtype=np.float32)
    raw = blob.tobytes() if isinstance(blob, memoryview) else bytes(blob)
    return np.frombuffer(raw, dtype=np.float32).copy()


@router.get("", response_model=list[QueueClusterOut])
def list_queue(
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    rows = QueueRepo(conn).list_unresolved_with_extras()
    if not rows:
        return []

    embeddings = [_decode_embedding(r["embedding"]) for r in rows]
    threshold = _cluster_threshold(request)

    # Cluster within each source separately. Mic-track and system-track
    # fragments live in different identification spaces (the resolver scopes
    # voiceprint candidates by source), so merging them in the queue would
    # be misleading: a YouTube anchor and an in-room colleague saying the
    # same words could otherwise share a card.
    groups: list[list[int]] = []
    rows_by_source: dict[str, list[int]] = {}
    for idx, row in enumerate(rows):
        rows_by_source.setdefault(row.get("source") or "mic", []).append(idx)
    for source_indices in rows_by_source.values():
        local_embeddings = [embeddings[i] for i in source_indices]
        local_groups = cluster_embeddings(local_embeddings, threshold=threshold)
        for local_group in local_groups:
            groups.append([source_indices[i] for i in local_group])

    resolver = SpeakerResolver(
        SQLiteResolverStore(conn),
        embedding_model_id=request.app.state.config.providers.embedding_model_id,
    )

    clusters: list[QueueClusterOut] = []
    for group in groups:
        members = [rows[i] for i in group]
        member_embeddings = [embeddings[i] for i in group]
        cluster_id = sorted(m["id"] for m in members)[0]
        queue_ids = [m["id"] for m in members]
        segment_ids = [m["speaker_segment_id"] for m in members]
        session_ids: list[str] = []
        session_titles: list[str] = []
        for m in members:
            sid = m["session_id"]
            if sid not in session_ids:
                session_ids.append(sid)
                session_titles.append(m.get("session_title") or sid)
        created_at = min(m["created_at"] for m in members)
        fragment_count = sum(m["fragment_count"] for m in members) or len(members)
        duration_ms = sum(m["duration_ms"] for m in members)
        # Pick the longest non-empty quote as the representative.
        quote = ""
        for m in members:
            if m["quote"] and len(m["quote"]) > len(quote):
                quote = m["quote"]

        # Cluster source: take the most common source across members. If a
        # cluster mixes mic+system fragments (rare — clustering threshold is
        # tight), fall back to the first member.
        source_counts: dict[str, int] = {}
        for m in members:
            src = m.get("source") or "mic"
            source_counts[src] = source_counts.get(src, 0) + 1
        cluster_source = max(source_counts.items(), key=lambda kv: kv[1])[0]

        cent = centroid(member_embeddings)
        candidates_payload: list[QueueCandidate] = []
        if cent.size > 0:
            probe = SpeakerSegment(embedding=cent, source=cluster_source)
            candidates_payload = [
                QueueCandidate(
                    contact_id=cid,
                    score=score,
                    contact_name=name,
                )
                for cid, score, name in resolver.get_candidates(probe)
            ]

        clusters.append(
            QueueClusterOut(
                id=cluster_id,
                queue_ids=queue_ids,
                segment_ids=segment_ids,
                session_ids=session_ids,
                session_titles=session_titles,
                created_at=created_at,
                fragment_count=fragment_count,
                duration_ms=duration_ms,
                quote=quote,
                source=cluster_source,
                candidates=candidates_payload,
            )
        )

    clusters.sort(key=lambda c: c.created_at, reverse=True)
    return clusters[offset : offset + limit]


@router.get("/count")
def queue_count(conn: sqlite3.Connection = Depends(get_db)):
    return {"count": QueueRepo(conn).count_unresolved()}


def _cascade_identify(
    conn: sqlite3.Connection, threshold: float, embedding_model_id: str
) -> int:
    """Re-run identification across remaining unresolved segments.

    Called right after a user resolution adds a new voice profile. Any
    segment whose embedding now matches the freshly added profile (or any
    existing one above the threshold — the resolver doesn't know which is
    which) gets auto-resolved without recording another voice profile.

    Processes in batches of 100 to bound memory. Returns the total number
    of cascaded resolutions.
    """
    repo = QueueRepo(conn)
    resolver = SpeakerResolver(
        SQLiteResolverStore(conn),
        embedding_model_id=embedding_model_id,
    )
    total_cascaded = 0
    BATCH = 100

    while True:
        rows = repo.list_unresolved_with_extras(limit=BATCH)
        if not rows:
            break
        batch_cascaded = 0
        for row in rows:
            emb = _decode_embedding(row["embedding"])
            if emb.size == 0:
                continue
            segment = SpeakerSegment(
                id=row["speaker_segment_id"],
                session_id=row["session_id"],
                embedding=emb,
                source=row.get("source") or "mic",
            )
            contact_id = resolver.resolve(segment, threshold=threshold)
            if contact_id is None:
                continue
            repo.resolve(row["id"], contact_id, record_voice_profile=False)
            batch_cascaded += 1
        total_cascaded += batch_cascaded
        if batch_cascaded == 0:
            break

    return total_cascaded


def _resolve_batch(
    conn: sqlite3.Connection,
    request: Request,
    queue_ids: list[str],
    contact_id: str,
) -> QueueResolveResponse:
    repo = QueueRepo(conn)
    missing = [qid for qid in queue_ids if not repo.get(qid)]
    if missing:
        raise HTTPException(
            status_code=404, detail=f"queue items not found: {missing}"
        )
    embedding_model_id = request.app.state.config.providers.embedding_model_id
    resolved = repo.resolve_many(
        queue_ids,
        contact_id,
        embedding_model_id=embedding_model_id,
    )
    threshold = request.app.state.config.pipeline.speaker_identification_threshold
    cascaded = _cascade_identify(conn, threshold, embedding_model_id)
    return QueueResolveResponse(resolved_count=resolved, cascaded_count=cascaded)


@router.post("/resolve", response_model=QueueResolveResponse)
def resolve_batch(
    payload: QueueResolveRequest,
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
):
    if not payload.queue_ids:
        raise HTTPException(status_code=400, detail="queue_ids required")
    return _resolve_batch(conn, request, payload.queue_ids, payload.contact_id)


@router.post("/skip", status_code=200)
def skip_batch(
    payload: QueueSkipRequest, conn: sqlite3.Connection = Depends(get_db)
):
    if not payload.queue_ids:
        raise HTTPException(status_code=400, detail="queue_ids required")
    repo = QueueRepo(conn)
    missing = [qid for qid in payload.queue_ids if not repo.get(qid)]
    if missing:
        raise HTTPException(
            status_code=404, detail=f"queue items not found: {missing}"
        )
    skipped = repo.skip_many(payload.queue_ids)
    return {"skipped_count": skipped}


# ---- Per-item routes (kept for backward compatibility / single-row callers) ----


@router.post("/{queue_id}/resolve", response_model=QueueItemOut)
def resolve_queue(
    queue_id: str,
    payload: QueueResolveRequest,
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
):
    repo = QueueRepo(conn)
    if not repo.get(queue_id):
        raise HTTPException(status_code=404, detail="queue item not found")
    embedding_model_id = request.app.state.config.providers.embedding_model_id
    result = repo.resolve(
        queue_id,
        payload.contact_id,
        embedding_model_id=embedding_model_id,
    )
    assert result is not None
    threshold = request.app.state.config.pipeline.speaker_identification_threshold
    _cascade_identify(conn, threshold, embedding_model_id)
    # Fill candidates as the legacy shape expected.
    result["candidates"] = []
    return result


@router.post("/{queue_id}/skip", response_model=QueueItemOut)
def skip_queue(queue_id: str, conn: sqlite3.Connection = Depends(get_db)):
    repo = QueueRepo(conn)
    if not repo.get(queue_id):
        raise HTTPException(status_code=404, detail="queue item not found")
    result = repo.skip(queue_id)
    assert result is not None
    result["candidates"] = []
    return result
