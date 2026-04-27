"""Adds embedding-space metadata to ``voice_profiles``.

``model_id`` and ``embedding_dim`` let the resolver reject profiles enrolled
under a different speaker-embedding model or dimensionality. Without this,
switching from one embedding model to another silently mixes incompatible
vector spaces inside the same cosine lookup table.

Legacy rows are conservatively backfilled as ``ecapa`` because that was the
historical bundled/default embedding provider when the gallery schema had no
model metadata.
"""
from __future__ import annotations

from .database import Database
from .migrations import Migration, MigrationRunner


def _has_column(db: Database, table: str, column: str) -> bool:
    rows = db.fetch_all(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in rows)


def _up(db: Database) -> None:
    conn = db.connect()
    if not _has_column(db, "voice_profiles", "model_id"):
        conn.execute(
            "ALTER TABLE voice_profiles ADD COLUMN model_id TEXT NOT NULL DEFAULT 'ecapa'"
        )
    if not _has_column(db, "voice_profiles", "embedding_dim"):
        conn.execute(
            "ALTER TABLE voice_profiles ADD COLUMN embedding_dim INTEGER NOT NULL DEFAULT 0"
        )
    conn.executescript(
        """
        UPDATE voice_profiles
        SET model_id = 'ecapa'
        WHERE model_id IS NULL OR TRIM(model_id) = '';

        UPDATE voice_profiles
        SET embedding_dim = LENGTH(embedding) / 4
        WHERE embedding IS NOT NULL
          AND (embedding_dim IS NULL OR embedding_dim <= 0);

        CREATE INDEX IF NOT EXISTS idx_voice_profiles_space
            ON voice_profiles(source, model_id, embedding_dim);
        """
    )
    conn.commit()


def _down(db: Database) -> None:
    # Best-effort no-op for SQLite deployments that may not support DROP COLUMN.
    pass


def register_voice_profile_metadata_migration(runner: MigrationRunner) -> None:
    runner.register(Migration(name="004_voice_profile_metadata", up=_up, down=_down))
