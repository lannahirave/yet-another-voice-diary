"""Pipeline errors table — persists processing errors per session."""
from __future__ import annotations

from .database import Database
from .migrations import Migration, MigrationRunner


_MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS pipeline_errors (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    utterance_id TEXT,
    component TEXT NOT NULL,
    error_code TEXT NOT NULL,
    message TEXT NOT NULL,
    occurred_at_ms INTEGER NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);
"""


def _up(db: Database) -> None:
    db.execute(_MIGRATION_SQL)


def _down(db: Database) -> None:
    db.execute("DROP TABLE IF EXISTS pipeline_errors")


def register_pipeline_errors_migration(runner: MigrationRunner) -> None:
    runner.register(Migration("005_pipeline_errors", _up, _down))
