"""Wipe all user data from the voice_diary SQLite DB while preserving schema.

Deletes every row from every user table (sessions, utterances, speaker_segments,
voice_profiles, contacts, unknown_queue) and the FTS shadow, then VACUUMs.
Schema, indexes, and migrations stay untouched. Pass ``--yes`` to skip the
confirmation prompt.

Usage:
    python -m backend.scripts.clear_db [path/to/voice_diary.db] [--yes]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


# Order matters: child tables first to avoid foreign-key violations even when
# foreign_keys pragma is on.
_TABLES_IN_ORDER = (
    "unknown_queue",
    "utterances",
    "speaker_segments",
    "voice_profiles",
    "contacts",
    "sessions",
)


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def clear(db_path: str, *, confirm: bool = True) -> int:
    path = Path(db_path)
    if not path.exists():
        print(f"db not found: {path}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(path))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        counts: dict[str, int] = {}
        for table in _TABLES_IN_ORDER:
            if not _table_exists(conn, table):
                continue
            counts[table] = conn.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]

        total = sum(counts.values())
        if total == 0:
            print(f"db already empty: {path}")
            return 0

        print(f"db: {path}")
        for table, n in counts.items():
            print(f"  {table}: {n} rows")
        print(f"total: {total} rows")

        if confirm:
            answer = input("delete all rows? [y/N] ").strip().lower()
            if answer not in {"y", "yes"}:
                print("aborted")
                return 2

        for table in _TABLES_IN_ORDER:
            if _table_exists(conn, table):
                conn.execute(f"DELETE FROM {table}")
        if _table_exists(conn, "utterances_fts"):
            try:
                conn.execute("DELETE FROM utterances_fts")
            except sqlite3.DatabaseError as exc:
                print(f"warning: failed to clear utterances_fts: {exc}")

        conn.commit()
        conn.execute("VACUUM")

        print("cleared.")
        for table in _TABLES_IN_ORDER:
            if _table_exists(conn, table):
                n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                print(f"  {table}: {n}")
        return 0
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "db",
        nargs="?",
        default="backend/voice_diary.db",
        help="path to voice_diary.db (default: backend/voice_diary.db)",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="skip the confirmation prompt",
    )
    args = parser.parse_args(argv)
    return clear(args.db, confirm=not args.yes)


if __name__ == "__main__":
    raise SystemExit(main())
