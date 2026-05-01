"""FastAPI dependency injection — per-request DB connections and shared singletons."""
from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from typing import TYPE_CHECKING

from fastapi import Depends, Request, WebSocket

if TYPE_CHECKING:
    from ..config import BackendConfig
    from ..pipeline.coordinator import PipelineCoordinator

log = logging.getLogger(__name__)


def _app_state(request: Request = None, websocket: WebSocket = None):
    # FastAPI injects whichever parameter matches the scope (HTTP vs WS).
    if request is not None:
        return request.app.state
    assert websocket is not None
    return websocket.app.state


def get_config(request: Request = None, websocket: WebSocket = None) -> BackendConfig:
    return _app_state(request, websocket).config


def get_db(
    config: BackendConfig = Depends(get_config),
) -> Iterator[sqlite3.Connection]:
    """Open a fresh SQLite connection per request; close it when the request ends.

    Why: FastAPI serves requests concurrently; a single shared connection
    races on writes. SQLite supports many short-lived connections against the
    same file safely.

    ``check_same_thread=False`` is required because FastAPI runs sync
    generator dependencies via ``contextmanager_in_threadpool``: the setup
    half (before ``yield``) and the teardown half (``conn.close()``) can run
    on different threads, and SQLite's default thread-affinity check would
    raise ``ProgrammingError`` on close. The connection itself is still used
    by exactly one request, so disabling the check is safe — there is no
    concurrent access to a single connection.
    """
    conn = sqlite3.connect(str(config.database.path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError:
        log.warning("WAL mode unavailable; using default journal (concurrent readers may block)")
    try:
        yield conn
    finally:
        conn.close()


def get_coordinator(
    request: Request = None, websocket: WebSocket = None
) -> PipelineCoordinator:
    return _app_state(request, websocket).coordinator
