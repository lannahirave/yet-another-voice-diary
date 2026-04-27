"""FTS5 sync triggers — keeps utterances_fts in sync with utterances."""
from __future__ import annotations

from .database import Database
from .migrations import Migration, MigrationRunner

_FTS_TRIGGERS_SQL = """
CREATE TRIGGER IF NOT EXISTS utterances_ai AFTER INSERT ON utterances BEGIN
  INSERT INTO utterances_fts(rowid, transcript) VALUES (new.rowid, new.transcript);
END;

CREATE TRIGGER IF NOT EXISTS utterances_ad AFTER DELETE ON utterances BEGIN
  INSERT INTO utterances_fts(utterances_fts, rowid, transcript)
    VALUES('delete', old.rowid, old.transcript);
END;

CREATE TRIGGER IF NOT EXISTS utterances_au AFTER UPDATE ON utterances BEGIN
  INSERT INTO utterances_fts(utterances_fts, rowid, transcript)
    VALUES('delete', old.rowid, old.transcript);
  INSERT INTO utterances_fts(rowid, transcript) VALUES (new.rowid, new.transcript);
END;
"""

_DROP_SQL = """
DROP TRIGGER IF EXISTS utterances_ai;
DROP TRIGGER IF EXISTS utterances_ad;
DROP TRIGGER IF EXISTS utterances_au;
"""


def _up(db: Database) -> None:
    conn = db.connect()
    conn.executescript(_FTS_TRIGGERS_SQL)
    conn.commit()


def _down(db: Database) -> None:
    conn = db.connect()
    conn.executescript(_DROP_SQL)
    conn.commit()


def register_fts_migration(runner: MigrationRunner) -> None:
    runner.register(Migration(name="002_fts_triggers", up=_up, down=_down))
