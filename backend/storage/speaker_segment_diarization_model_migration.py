"""Adds diarization-model provenance to ``speaker_segments``.

Legacy rows are backfilled as ``pyannote`` because that was the only diarization
provider actually used before the UI briefly exposed the broken ``nemo`` option.
"""
from __future__ import annotations

from .database import Database
from .migrations import Migration, MigrationRunner


def _has_column(db: Database, table: str, column: str) -> bool:
    rows = db.fetch_all(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in rows)


def _up(db: Database) -> None:
    conn = db.connect()
    if not _has_column(db, "speaker_segments", "diarization_model_id"):
        conn.execute(
            "ALTER TABLE speaker_segments ADD COLUMN diarization_model_id TEXT NOT NULL DEFAULT 'pyannote'"
        )
    conn.executescript(
        """
        UPDATE speaker_segments
        SET diarization_model_id = 'pyannote'
        WHERE diarization_model_id IS NULL OR TRIM(diarization_model_id) = '';

        CREATE INDEX IF NOT EXISTS idx_speaker_segments_diarization_model
            ON speaker_segments(diarization_model_id);
        """
    )
    conn.commit()


def _down(db: Database) -> None:
    # Best-effort no-op for SQLite deployments that may not support DROP COLUMN.
    pass


def register_speaker_segment_diarization_model_migration(
    runner: MigrationRunner,
) -> None:
    runner.register(
        Migration(
            name="005_speaker_segment_diarization_model",
            up=_up,
            down=_down,
        )
    )
