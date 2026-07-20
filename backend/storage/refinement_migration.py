"""Durable recording and full-session refinement storage."""
from __future__ import annotations

from .database import Database
from .migrations import Migration, MigrationRunner


def _up(db: Database) -> None:
    conn = db.connect()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS session_recordings (
            session_id TEXT NOT NULL,
            source TEXT NOT NULL,
            path TEXT NOT NULL,
            duration_ms INTEGER NOT NULL DEFAULT 0,
            size_bytes INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'ready',
            created_at INTEGER NOT NULL,
            PRIMARY KEY (session_id, source),
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        );

        CREATE TABLE IF NOT EXISTS refinement_jobs (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            status TEXT NOT NULL,
            stage TEXT NOT NULL,
            progress REAL NOT NULL DEFAULT 0,
            current_source TEXT,
            processed_items INTEGER NOT NULL DEFAULT 0,
            total_items INTEGER NOT NULL DEFAULT 0,
            error TEXT,
            cancel_requested INTEGER NOT NULL DEFAULT 0,
            config_snapshot TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            started_at INTEGER,
            completed_at INTEGER,
            metrics_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_refinement_active_session
        ON refinement_jobs(session_id)
        WHERE status IN ('queued', 'running');

        CREATE TABLE IF NOT EXISTS refinement_speaker_segments (
            job_id TEXT NOT NULL,
            id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            contact_id TEXT,
            status TEXT NOT NULL,
            embedding BLOB,
            diarization_model_id TEXT NOT NULL,
            sim_score REAL,
            source TEXT NOT NULL,
            PRIMARY KEY (job_id, id),
            FOREIGN KEY (job_id) REFERENCES refinement_jobs(id)
        );

        CREATE TABLE IF NOT EXISTS refinement_utterances (
            job_id TEXT NOT NULL,
            id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            started_ms INTEGER NOT NULL,
            ended_ms INTEGER NOT NULL,
            transcript TEXT NOT NULL,
            language TEXT,
            confidence REAL,
            speaker_segment_id TEXT,
            source TEXT NOT NULL,
            PRIMARY KEY (job_id, id),
            FOREIGN KEY (job_id) REFERENCES refinement_jobs(id)
        );

        CREATE INDEX IF NOT EXISTS idx_recordings_session
            ON session_recordings(session_id);
        CREATE INDEX IF NOT EXISTS idx_refinement_jobs_session
            ON refinement_jobs(session_id, created_at DESC);
        """
    )
    conn.execute(
        """
        UPDATE refinement_jobs
        SET status = 'failed', stage = 'failed',
            error = COALESCE(error, 'application stopped during refinement'),
            completed_at = CAST(strftime('%s','now') AS INTEGER)
        WHERE status IN ('queued', 'running')
        """
    )
    conn.commit()


def _down(_db: Database) -> None:
    return


def register_refinement_migration(runner: MigrationRunner) -> None:
    runner.register(Migration("006_full_session_refinement", _up, _down))
    runner.register(Migration("007_refinement_metrics", _up_metrics, _down))


def _up_metrics(db: Database) -> None:
    conn = db.connect()
    columns = {row[1] for row in conn.execute("PRAGMA table_info(refinement_jobs)")}
    if "metrics_json" not in columns:
        conn.execute(
            "ALTER TABLE refinement_jobs ADD COLUMN metrics_json TEXT NOT NULL DEFAULT '{}'"
        )
        conn.commit()
