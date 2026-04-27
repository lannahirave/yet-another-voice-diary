"""Tests for database."""
import tempfile
from pathlib import Path

from backend.config import DatabaseConfig
from backend.storage.database import Database
from backend.storage.migrations import MigrationRunner
from backend.storage.speaker_segment_diarization_model_migration import (
    register_speaker_segment_diarization_model_migration,
)
from backend.storage.voice_profile_metadata_migration import (
    register_voice_profile_metadata_migration,
)


def test_database_init():
    """Test database initialization."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config = DatabaseConfig(path=Path(tmpdir) / "test.db")
        db = Database(config)

        # Should create connection
        conn = db.connect()
        assert conn is not None

        db.close()


def test_schema_initialization():
    """Test schema creation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config = DatabaseConfig(path=Path(tmpdir) / "test.db")
        db = Database(config)
        db.init_schema()

        # Verify tables exist
        result = db.fetch_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'"
        )
        assert result is not None

        db.close()


def test_execute_and_fetch():
    """Test basic execute and fetch."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config = DatabaseConfig(path=Path(tmpdir) / "test.db")
        db = Database(config)
        db.init_schema()

        # Insert a session
        session_id = "test-session-1"
        db.execute(
            "INSERT INTO sessions (id, title, started_at) VALUES (?, ?, ?)",
            (session_id, "Test Session", 1234567890)
        )

        # Fetch it back
        result = db.fetch_one(
            "SELECT title FROM sessions WHERE id = ?",
            (session_id,)
        )
        assert result is not None
        assert result[0] == "Test Session"

        db.close()


def test_voice_profile_metadata_migration_backfills_legacy_rows():
    with tempfile.TemporaryDirectory() as tmpdir:
        config = DatabaseConfig(path=Path(tmpdir) / "test.db")
        db = Database(config)
        conn = db.connect()
        conn.executescript(
            """
            CREATE TABLE voice_profiles (
                id TEXT PRIMARY KEY,
                contact_id TEXT NOT NULL,
                embedding BLOB NOT NULL,
                quality_score REAL,
                recorded_at INTEGER NOT NULL,
                source_session_id TEXT,
                source TEXT NOT NULL DEFAULT 'mic'
            );
            """
        )
        conn.execute(
            """
            INSERT INTO voice_profiles
                (id, contact_id, embedding, quality_score, recorded_at, source)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("p1", "c1", bytes(192 * 4), 1.0, 1, "mic"),
        )
        conn.commit()

        runner = MigrationRunner(db)
        register_voice_profile_metadata_migration(runner)
        runner.apply_pending()

        row = db.fetch_one(
            "SELECT model_id, embedding_dim FROM voice_profiles WHERE id = ?",
            ("p1",),
        )
        assert row is not None
        assert row[0] == "ecapa"
        assert row[1] == 192

        db.close()


def test_speaker_segment_diarization_model_migration_backfills_legacy_rows():
    with tempfile.TemporaryDirectory() as tmpdir:
        config = DatabaseConfig(path=Path(tmpdir) / "test.db")
        db = Database(config)
        conn = db.connect()
        conn.executescript(
            """
            CREATE TABLE speaker_segments (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                contact_id TEXT,
                status TEXT NOT NULL DEFAULT 'unknown',
                embedding BLOB,
                sim_score REAL,
                reviewed_at INTEGER,
                source TEXT NOT NULL DEFAULT 'mic'
            );
            """
        )
        conn.execute(
            """
            INSERT INTO speaker_segments
                (id, session_id, status, embedding, sim_score, source)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("seg1", "sess1", "unknown", bytes(4), 0.0, "mic"),
        )
        conn.commit()

        runner = MigrationRunner(db)
        register_speaker_segment_diarization_model_migration(runner)
        runner.apply_pending()

        row = db.fetch_one(
            "SELECT diarization_model_id FROM speaker_segments WHERE id = ?",
            ("seg1",),
        )
        assert row is not None
        assert row[0] == "pyannote"

        db.close()
