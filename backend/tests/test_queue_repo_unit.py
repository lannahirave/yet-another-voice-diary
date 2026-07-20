"""Focused unit coverage for unknown-speaker queue persistence."""
from __future__ import annotations

import sqlite3
import time

import numpy as np

from backend.storage.queue_repo import QueueRepo


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(open("backend/storage/schema.sql", encoding="utf-8").read())
    return conn


def _seed(conn: sqlite3.Connection, segment_id: str, queue_id: str, embedding: np.ndarray) -> None:
    conn.execute(
        "INSERT INTO sessions (id, title, started_at, ended_at, notes, language_hint) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("s1", "Meeting", 100, None, None, None),
    )
    conn.execute(
        "INSERT INTO contacts (id, name, notes, created_at) VALUES (?, ?, ?, ?)",
        ("c1", "Alice", None, 100),
    )
    conn.execute(
        "INSERT INTO speaker_segments (id, session_id, embedding, source) VALUES (?, ?, ?, ?)",
        (segment_id, "s1", embedding.astype("float32").tobytes(), "mic"),
    )
    conn.execute(
        "INSERT INTO unknown_queue (id, speaker_segment_id, created_at) VALUES (?, ?, ?)",
        (queue_id, segment_id, int(time.time())),
    )
    conn.execute(
        """INSERT INTO utterances (
            id, session_id, started_ms, ended_ms, transcript, language,
            confidence, speaker_segment_id, source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("u1", "s1", 10, 210, "longer quote", None, 1.0, segment_id, "mic"),
    )
    conn.commit()


def test_queue_repo_lists_extras_and_resolves_with_profile() -> None:
    conn = _db()
    _seed(conn, "seg1", "q1", np.array([1.0, 0.0]))
    repo = QueueRepo(conn)

    rows = repo.list_unresolved_with_extras(q="quote", session_id="s1")
    assert rows[0]["quote"] == "longer quote"
    assert rows[0]["duration_ms"] == 200
    assert rows[0]["fragment_count"] == 1
    assert repo.count_unresolved() == 1

    resolved = repo.resolve("q1", "c1", embedding_model_id="test-model")
    assert resolved and resolved["resolved_contact_id"] == "c1"
    assert repo.count_unresolved() == 0
    profile = conn.execute("SELECT contact_id, model_id, embedding_dim FROM voice_profiles").fetchone()
    assert tuple(profile) == ("c1", "test-model", 2)


def test_queue_repo_resolve_many_records_one_profile_and_delete_cleans_children() -> None:
    conn = _db()
    _seed(conn, "seg1", "q1", np.array([1.0, 0.0]))
    conn.execute("INSERT INTO speaker_segments (id, session_id, embedding) VALUES (?, ?, ?)", ("seg2", "s1", np.array([0.0, 1.0], dtype="float32").tobytes()))
    conn.execute(
        """INSERT INTO unknown_queue (
            id, speaker_segment_id, created_at, resolved_contact_id,
            resolved_at, source
        ) VALUES (?, ?, ?, ?, ?, ?)""",
        ("q2", "seg2", int(time.time()), None, None, "mic"),
    )
    conn.commit()
    repo = QueueRepo(conn)

    assert repo.resolve_many(["q1", "q2"], "c1") == 2
    assert conn.execute("SELECT COUNT(*) FROM voice_profiles").fetchone()[0] == 1
    queue_rows = conn.execute(
        "SELECT id, resolved_contact_id, resolved_at FROM unknown_queue "
        "WHERE id IN (?, ?) ORDER BY id",
        ("q1", "q2"),
    ).fetchall()
    assert [tuple(row)[:2] for row in queue_rows] == [("q1", "c1"), ("q2", "c1")]
    assert all(row[2] is not None for row in queue_rows)
    segment_rows = conn.execute(
        "SELECT id, contact_id, status FROM speaker_segments "
        "WHERE id IN (?, ?) ORDER BY id",
        ("seg1", "seg2"),
    ).fetchall()
    assert [tuple(row) for row in segment_rows] == [
        ("seg1", "c1", "identified"),
        ("seg2", "c1", "identified"),
    ]
    assert repo.delete_many(["q1"]) == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM unknown_queue WHERE id = ?", ("q1",)
    ).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM speaker_segments WHERE id = 'seg1'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM utterances WHERE speaker_segment_id = 'seg1'").fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM unknown_queue WHERE id = ?", ("q2",)
    ).fetchone()[0] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM speaker_segments WHERE id = ?", ("seg2",)
    ).fetchone()[0] == 1
