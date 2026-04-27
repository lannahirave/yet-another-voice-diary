"""Adds a ``source`` column to audio-derived tables.

A recording session may now multiplex several audio sources at once — the
local microphone (``mic``) and the system-audio loopback (``system``). The
column is wide-open ``TEXT`` so future per-app values like ``app:zoom`` can
slot in without another migration. The resolver scopes voiceprint candidates
by source, so a YouTube anchor heard through the speakers can't auto-match
the in-room colleague enrolled from the mic.
"""
from __future__ import annotations

from .database import Database
from .migrations import Migration, MigrationRunner

_UP_SQL = """
ALTER TABLE utterances        ADD COLUMN source TEXT NOT NULL DEFAULT 'mic';
ALTER TABLE speaker_segments  ADD COLUMN source TEXT NOT NULL DEFAULT 'mic';
ALTER TABLE voice_profiles    ADD COLUMN source TEXT NOT NULL DEFAULT 'mic';
ALTER TABLE unknown_queue     ADD COLUMN source TEXT NOT NULL DEFAULT 'mic';

CREATE INDEX IF NOT EXISTS idx_voice_profiles_source ON voice_profiles(source);
CREATE INDEX IF NOT EXISTS idx_speaker_segments_source ON speaker_segments(source);
"""


def _has_column(db: Database, table: str, column: str) -> bool:
    # PRAGMA table_info returns: (cid, name, type, notnull, dflt_value, pk)
    rows = db.fetch_all(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in rows)


def _up(db: Database) -> None:
    # Idempotent: SQLite has no `IF NOT EXISTS` for ALTER TABLE ADD COLUMN, and
    # users may have run an earlier dev build with the column already present.
    conn = db.connect()
    if not _has_column(db, "utterances", "source"):
        conn.execute("ALTER TABLE utterances ADD COLUMN source TEXT NOT NULL DEFAULT 'mic'")
    if not _has_column(db, "speaker_segments", "source"):
        conn.execute("ALTER TABLE speaker_segments ADD COLUMN source TEXT NOT NULL DEFAULT 'mic'")
    if not _has_column(db, "voice_profiles", "source"):
        conn.execute("ALTER TABLE voice_profiles ADD COLUMN source TEXT NOT NULL DEFAULT 'mic'")
    if not _has_column(db, "unknown_queue", "source"):
        conn.execute("ALTER TABLE unknown_queue ADD COLUMN source TEXT NOT NULL DEFAULT 'mic'")
    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_voice_profiles_source ON voice_profiles(source);
        CREATE INDEX IF NOT EXISTS idx_speaker_segments_source ON speaker_segments(source);
        """
    )
    conn.commit()


def _down(db: Database) -> None:
    # SQLite < 3.35 cannot drop columns; modern SQLite can. Best-effort no-op.
    pass


def register_source_migration(runner: MigrationRunner) -> None:
    runner.register(Migration(name="003_audio_source", up=_up, down=_down))
