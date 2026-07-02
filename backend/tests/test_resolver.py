"""Tests for speaker resolver database loading."""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import numpy as np
import pytest

from backend.config import DatabaseConfig
from backend.identification.resolver import SpeakerResolver
from backend.models import SpeakerSegment
from backend.storage.database import Database


@pytest.fixture()
def db() -> Database:
    tmpdir = tempfile.TemporaryDirectory()
    db = Database(DatabaseConfig(path=Path(tmpdir.name) / "test.db"))
    db.init_schema()
    try:
        yield db
    finally:
        db.close()
        tmpdir.cleanup()


def test_load_voice_profiles_decodes_sqlite_blob_to_float32_arrays(db: Database):
    resolver = SpeakerResolver(db)

    emb_a = np.array([0.1, 0.2, 0.3], dtype=np.float32)
    emb_b = np.array([0.4, 0.5, 0.6], dtype=np.float32)

    db.execute(
        "INSERT INTO contacts (id, name, created_at) VALUES (?, ?, ?)",
        ("contact_a", "Alice", 1),
    )
    db.execute(
        "INSERT INTO contacts (id, name, created_at) VALUES (?, ?, ?)",
        ("contact_b", "Bob", 1),
    )
    db.execute(
        """
        INSERT INTO voice_profiles (id, contact_id, embedding, quality_score, recorded_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("profile_a", "contact_a", emb_a.tobytes(), 0.9, 1),
    )
    db.execute(
        """
        INSERT INTO voice_profiles (id, contact_id, embedding, quality_score, recorded_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("profile_b", "contact_b", emb_b.tobytes(), 0.8, 1),
    )

    profiles = resolver._load_voice_profiles()

    assert [contact_id for contact_id, _ in profiles] == ["contact_a", "contact_b"]
    assert all(embedding.dtype == np.float32 for _, embedding in profiles)
    np.testing.assert_array_equal(profiles[0][1], emb_a)
    np.testing.assert_array_equal(profiles[1][1], emb_b)


def test_get_contact_name_reads_sqlite_and_falls_back_to_unknown(db: Database):
    resolver = SpeakerResolver(db)

    db.execute(
        "INSERT INTO contacts (id, name, created_at) VALUES (?, ?, ?)",
        ("contact_a", "Alice", 1),
    )

    assert resolver._get_contact_name("contact_a") == "Alice"
    assert resolver._get_contact_name("missing") == "Unknown"


def test_load_segment_reads_diarization_model_id(db: Database):
    resolver = SpeakerResolver(db)
    emb = np.array([0.1, 0.2, 0.3], dtype=np.float32)

    db.execute(
        """
        INSERT INTO speaker_segments
            (id, session_id, status, embedding, diarization_model_id, sim_score, source)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("seg_a", "sess_a", "unknown", emb.tobytes(), "pyannote", 0.42, "mic"),
    )

    segment = resolver.load_segment("seg_a")

    assert segment is not None
    assert segment.diarization_model_id == "pyannote"
    assert segment.sim_score == pytest.approx(0.42)
    np.testing.assert_array_equal(segment.embedding, emb)


def test_get_candidates_uses_loaded_profiles_and_contact_names(db: Database):
    conn = db.connect()
    conn.row_factory = sqlite3.Row
    resolver = SpeakerResolver(db)

    emb_a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    emb_b = np.array([0.8, 0.2, 0.0], dtype=np.float32)

    db.execute(
        "INSERT INTO contacts (id, name, created_at) VALUES (?, ?, ?)",
        ("contact_a", "Alice", 1),
    )
    db.execute(
        "INSERT INTO contacts (id, name, created_at) VALUES (?, ?, ?)",
        ("contact_b", "Bob", 1),
    )
    db.execute(
        """
        INSERT INTO voice_profiles (id, contact_id, embedding, quality_score, recorded_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("profile_a", "contact_a", emb_a.tobytes(), 0.9, 1),
    )
    db.execute(
        """
        INSERT INTO voice_profiles (id, contact_id, embedding, quality_score, recorded_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("profile_b", "contact_b", emb_b.tobytes(), 0.8, 1),
    )

    segment = SpeakerSegment(embedding=np.array([0.95, 0.05, 0.0], dtype=np.float32))

    candidates = resolver.get_candidates(segment, threshold=0.7, top_k=2)

    assert candidates[0][0] == "contact_a"
    assert candidates[0][2] == "Alice"
    assert candidates[1][0] == "contact_b"
    assert candidates[1][2] == "Bob"


def test_get_candidates_dedupes_multiple_profiles_per_contact(db: Database):
    """When a contact has several voice profiles, the candidate list must
    contain that contact at most once — represented by their best-scoring
    profile. Otherwise the queue UI shows the same person twice with two
    different match percentages."""
    resolver = SpeakerResolver(db)

    db.execute(
        "INSERT INTO contacts (id, name, created_at) VALUES (?, ?, ?)",
        ("contact_a", "Alice", 1),
    )
    db.execute(
        "INSERT INTO contacts (id, name, created_at) VALUES (?, ?, ?)",
        ("contact_b", "Bob", 1),
    )
    # Two profiles for Alice with different similarity to the probe.
    near = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    far = np.array([0.9, 0.4, 0.0], dtype=np.float32)
    db.execute(
        "INSERT INTO voice_profiles (id, contact_id, embedding, quality_score, recorded_at)"
        " VALUES (?, ?, ?, ?, ?)",
        ("profile_a1", "contact_a", near.tobytes(), 0.9, 1),
    )
    db.execute(
        "INSERT INTO voice_profiles (id, contact_id, embedding, quality_score, recorded_at)"
        " VALUES (?, ?, ?, ?, ?)",
        ("profile_a2", "contact_a", far.tobytes(), 0.8, 1),
    )
    bob_emb = np.array([0.0, 1.0, 0.0], dtype=np.float32)
    db.execute(
        "INSERT INTO voice_profiles (id, contact_id, embedding, quality_score, recorded_at)"
        " VALUES (?, ?, ?, ?, ?)",
        ("profile_b", "contact_b", bob_emb.tobytes(), 0.9, 1),
    )

    segment = SpeakerSegment(embedding=np.array([1.0, 0.0, 0.0], dtype=np.float32))
    candidates = resolver.get_candidates(segment, threshold=0.5, top_k=3)

    contact_ids = [c[0] for c in candidates]
    assert contact_ids.count("contact_a") == 1, (
        f"contact_a should appear once, got {contact_ids}"
    )
    # And it should be represented by the higher-scoring profile.
    alice = next(c for c in candidates if c[0] == "contact_a")
    assert alice[1] == pytest.approx(1.0, abs=1e-5)


def test_resolve_scopes_voice_profiles_by_source(db: Database):
    """A profile enrolled from the mic must not match a system-track segment
    even when the embeddings are identical. Without source scoping, a YouTube
    anchor played through the speakers can spuriously match an in-room
    colleague enrolled via the mic."""
    resolver = SpeakerResolver(db)

    emb = np.array([1.0, 0.0, 0.0], dtype=np.float32)

    db.execute(
        "INSERT INTO contacts (id, name, created_at) VALUES (?, ?, ?)",
        ("mic_contact", "Mike", 1),
    )
    db.execute(
        """
        INSERT INTO voice_profiles
            (id, contact_id, embedding, quality_score, recorded_at, source)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("mic_profile", "mic_contact", emb.tobytes(), 0.9, 1, "mic"),
    )

    # Mic-track segment: should match.
    mic_segment = SpeakerSegment(embedding=emb.copy(), source="mic")
    assert resolver.resolve(mic_segment, threshold=0.5) == "mic_contact"

    # System-track segment with the same embedding: must NOT match — the
    # only enrolled profile is mic-scoped.
    system_segment = SpeakerSegment(embedding=emb.copy(), source="system")
    assert resolver.resolve(system_segment, threshold=0.5) is None
    assert system_segment.status == "unknown"


def test_get_candidates_respects_source_scope(db: Database):
    """``get_candidates`` must only surface contacts whose voice_profiles
    were enrolled under the same source. Cross-track candidates are not
    legitimate suggestions."""
    resolver = SpeakerResolver(db)

    emb = np.array([1.0, 0.0, 0.0], dtype=np.float32)

    db.execute(
        "INSERT INTO contacts (id, name, created_at) VALUES (?, ?, ?)",
        ("mike", "Mike", 1),
    )
    db.execute(
        "INSERT INTO contacts (id, name, created_at) VALUES (?, ?, ?)",
        ("anchor", "Anchor", 1),
    )
    db.execute(
        """
        INSERT INTO voice_profiles
            (id, contact_id, embedding, quality_score, recorded_at, source)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("p_mike", "mike", emb.tobytes(), 0.9, 1, "mic"),
    )
    db.execute(
        """
        INSERT INTO voice_profiles
            (id, contact_id, embedding, quality_score, recorded_at, source)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("p_anchor", "anchor", emb.tobytes(), 0.9, 1, "system"),
    )

    mic_probe = SpeakerSegment(embedding=emb.copy(), source="mic")
    candidates = resolver.get_candidates(mic_probe, threshold=0.5, top_k=5)
    assert [c[0] for c in candidates] == ["mike"]

    sys_probe = SpeakerSegment(embedding=emb.copy(), source="system")
    candidates = resolver.get_candidates(sys_probe, threshold=0.5, top_k=5)
    assert [c[0] for c in candidates] == ["anchor"]


def test_resolve_filters_profiles_by_embedding_model_id(db: Database):
    resolver = SpeakerResolver(db, embedding_model_id="ecapa")

    emb = np.array([1.0, 0.0, 0.0], dtype=np.float32)

    db.execute(
        "INSERT INTO contacts (id, name, created_at) VALUES (?, ?, ?)",
        ("ecapa_contact", "ECAPA", 1),
    )
    db.execute(
        "INSERT INTO contacts (id, name, created_at) VALUES (?, ?, ?)",
        ("other_embedding_contact", "Other Embedding", 1),
    )
    db.execute(
        """
        INSERT INTO voice_profiles
            (id, contact_id, embedding, model_id, embedding_dim, quality_score, recorded_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("ecapa_profile", "ecapa_contact", emb.tobytes(), "ecapa", 3, 0.9, 1),
    )
    db.execute(
        """
        INSERT INTO voice_profiles
            (id, contact_id, embedding, model_id, embedding_dim, quality_score, recorded_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "other_embedding_profile",
            "other_embedding_contact",
            emb.tobytes(),
            "other-embedding",
            3,
            0.9,
            1,
        ),
    )

    segment = SpeakerSegment(embedding=emb.copy(), source="mic")
    assert resolver.resolve(segment, threshold=0.5) == "ecapa_contact"


def test_resolve_filters_profiles_by_embedding_dimension(db: Database):
    resolver = SpeakerResolver(db, embedding_model_id="ecapa")

    db.execute(
        "INSERT INTO contacts (id, name, created_at) VALUES (?, ?, ?)",
        ("matching_contact", "Match", 1),
    )
    db.execute(
        "INSERT INTO contacts (id, name, created_at) VALUES (?, ?, ?)",
        ("mismatch_contact", "Mismatch", 1),
    )

    matching = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    mismatched = np.array([1.0, 0.0], dtype=np.float32)
    db.execute(
        """
        INSERT INTO voice_profiles
            (id, contact_id, embedding, model_id, embedding_dim, quality_score, recorded_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("matching_profile", "matching_contact", matching.tobytes(), "ecapa", 3, 0.9, 1),
    )
    db.execute(
        """
        INSERT INTO voice_profiles
            (id, contact_id, embedding, model_id, embedding_dim, quality_score, recorded_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("mismatch_profile", "mismatch_contact", mismatched.tobytes(), "ecapa", 2, 0.9, 1),
    )

    segment = SpeakerSegment(embedding=matching.copy(), source="mic")
    assert resolver.resolve(segment, threshold=0.5) == "matching_contact"


def test_get_candidates_falls_back_to_same_dim_profiles_from_other_models(db: Database):
    resolver = SpeakerResolver(db, embedding_model_id="other-embedding")

    emb = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    db.execute(
        "INSERT INTO contacts (id, name, created_at) VALUES (?, ?, ?)",
        ("legacy_contact", "Legacy", 1),
    )
    db.execute(
        """
        INSERT INTO voice_profiles
            (id, contact_id, embedding, model_id, embedding_dim, quality_score, recorded_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("legacy_profile", "legacy_contact", emb.tobytes(), "ecapa", 3, 0.9, 1),
    )

    probe = SpeakerSegment(embedding=emb.copy(), source="mic")

    # Auto-resolve remains strict to the currently selected embedding model.
    assert resolver.resolve(probe, threshold=0.5) is None

    # Candidate suggestions fall back so the queue still offers quick-assign hints.
    candidates = resolver.get_candidates(probe, threshold=0.5, top_k=3)
    assert [c[0] for c in candidates] == ["legacy_contact"]
