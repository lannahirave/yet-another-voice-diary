"""ContactRepo confidence computation."""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import numpy as np
import pytest

from backend.config import DatabaseConfig
from backend.storage.contact_repo import ContactRepo
from backend.storage.database import Database


@pytest.fixture()
def db():
    tmpdir = tempfile.TemporaryDirectory()
    d = Database(DatabaseConfig(path=Path(tmpdir.name) / "test.db"))
    d.init_schema()
    try:
        yield d
    finally:
        d.close()
        tmpdir.cleanup()


def _conn(db: Database) -> sqlite3.Connection:
    c = db.connect()
    c.row_factory = sqlite3.Row
    return c


def _insert_contact(db: Database, contact_id: str, name: str = "X") -> None:
    db.execute(
        "INSERT INTO contacts (id, name, created_at) VALUES (?, ?, ?)",
        (contact_id, name, 1),
    )


def _insert_profile(db: Database, contact_id: str, profile_id: str, emb: np.ndarray) -> None:
    db.execute(
        "INSERT INTO voice_profiles (id, contact_id, embedding, quality_score, recorded_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (profile_id, contact_id, emb.astype(np.float32).tobytes(), 0.9, 1),
    )


def test_confidence_zero_when_no_profiles(db: Database):
    _insert_contact(db, "c1")
    repo = ContactRepo(_conn(db))
    contact = repo.get_contact("c1")
    assert contact["confidence"] == 0.0
    assert contact["profile_count"] == 0


def test_confidence_zero_when_single_profile(db: Database):
    """One profile is meaningless for measuring internal consistency — UI
    treats 0 as 'not yet computed' and matches the 'Update profile' gate."""
    _insert_contact(db, "c1")
    _insert_profile(db, "c1", "p1", np.array([1.0, 0.0, 0.0]))
    repo = ContactRepo(_conn(db))
    contact = repo.get_contact("c1")
    assert contact["confidence"] == 0.0
    assert contact["profile_count"] == 1


def test_confidence_is_mean_pairwise_cosine_for_multiple_profiles(db: Database):
    _insert_contact(db, "c1")
    # Three profiles. Pairwise cosines: (a,b)=0.6, (a,c)=0.8, (b,c)=0.96
    # (after L2 norm). Mean ≈ 0.78.
    a = np.array([1.0, 0.0, 0.0])
    b = np.array([0.6, 0.8, 0.0])
    c = np.array([0.8, 0.6, 0.0])
    _insert_profile(db, "c1", "p1", a)
    _insert_profile(db, "c1", "p2", b)
    _insert_profile(db, "c1", "p3", c)

    repo = ContactRepo(_conn(db))
    contact = repo.get_contact("c1")

    # Verify against direct numpy computation.
    mat = np.stack([v / np.linalg.norm(v) for v in (a, b, c)])
    expected = np.triu(mat @ mat.T, k=1).sum() / 3.0
    assert contact["confidence"] == pytest.approx(float(expected), abs=1e-5)
    assert 0.0 <= contact["confidence"] <= 1.0


def test_confidence_perfect_for_identical_profiles(db: Database):
    _insert_contact(db, "c1")
    emb = np.array([0.1, 0.2, 0.3])
    _insert_profile(db, "c1", "p1", emb)
    _insert_profile(db, "c1", "p2", emb)

    repo = ContactRepo(_conn(db))
    contact = repo.get_contact("c1")
    assert contact["confidence"] == pytest.approx(1.0, abs=1e-5)


def test_confidence_skips_zero_norm_embeddings(db: Database):
    """Garbage embeddings (e.g. from end-of-session 256ms flushes) must not
    drag the contact's confidence to 0."""
    _insert_contact(db, "c1")
    good = np.array([1.0, 0.0, 0.0])
    zero = np.zeros(3, dtype=np.float32)
    _insert_profile(db, "c1", "p1", good)
    _insert_profile(db, "c1", "p2", good)
    _insert_profile(db, "c1", "p3", zero)

    repo = ContactRepo(_conn(db))
    contact = repo.get_contact("c1")
    # Two valid identical profiles → confidence 1.0; zero-norm one ignored.
    assert contact["confidence"] == pytest.approx(1.0, abs=1e-5)


def test_list_contacts_includes_confidence_per_contact(db: Database):
    _insert_contact(db, "c1", "A")
    _insert_contact(db, "c2", "B")
    _insert_profile(db, "c1", "p1", np.array([1.0, 0.0]))
    _insert_profile(db, "c1", "p2", np.array([1.0, 0.0]))

    repo = ContactRepo(_conn(db))
    contacts = {c["id"]: c for c in repo.list_contacts()}
    assert contacts["c1"]["confidence"] == pytest.approx(1.0, abs=1e-5)
    assert contacts["c2"]["confidence"] == 0.0


def test_confidence_ignores_profiles_from_incompatible_embedding_spaces(db: Database):
    _insert_contact(db, "c1")
    conn = _conn(db)
    conn.execute(
        """
        INSERT INTO voice_profiles
            (id, contact_id, embedding, model_id, embedding_dim, quality_score, recorded_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("p1", "c1", np.array([1.0, 0.0, 0.0], dtype=np.float32).tobytes(), "ecapa", 3, 0.9, 1),
    )
    conn.execute(
        """
        INSERT INTO voice_profiles
            (id, contact_id, embedding, model_id, embedding_dim, quality_score, recorded_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("p2", "c1", np.array([1.0, 0.0], dtype=np.float32).tobytes(), "other-embedding", 2, 0.9, 1),
    )
    conn.execute(
        """
        INSERT INTO voice_profiles
            (id, contact_id, embedding, model_id, embedding_dim, quality_score, recorded_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("p3", "c1", np.array([1.0, 0.0, 0.0], dtype=np.float32).tobytes(), "ecapa", 3, 0.9, 1),
    )
    conn.commit()

    repo = ContactRepo(conn)
    contact = repo.get_contact("c1")
    assert contact["confidence"] == pytest.approx(1.0, abs=1e-5)
