"""Lightweight, read-only access to the configured Voice Diary database."""
from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

DEFAULT_DATABASE_PATH = Path("backend/voice_diary.db")
CONFIG_ENV_VAR = "VOICE_DIARY_CONFIG"
REQUIRED_TABLES = frozenset(
    {"sessions", "utterances", "speaker_segments", "contacts", "utterances_fts"}
)


class DiaryDatabaseError(RuntimeError):
    """The configured diary database cannot safely serve MCP searches."""


def default_config_path() -> Path:
    return Path.home() / ".voice-diary" / "config.json"


def load_database_path(
    *,
    config_path: Path | None = None,
    database_path: Path | None = None,
) -> Path:
    """Resolve the DB without importing the ML-aware backend configuration."""
    if database_path is not None:
        return database_path.expanduser().resolve()

    selected_config = config_path
    if selected_config is None:
        configured = os.environ.get(CONFIG_ENV_VAR)
        selected_config = Path(configured) if configured else default_config_path()

    raw: dict[str, Any] = {}
    if selected_config.exists():
        try:
            loaded = json.loads(selected_config.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DiaryDatabaseError(
                f"Cannot read Voice Diary config at {selected_config}: {exc}"
            ) from exc
        if not isinstance(loaded, dict):
            raise DiaryDatabaseError(
                f"Voice Diary config at {selected_config} must contain a JSON object"
            )
        raw = loaded

    database_config = raw.get("database", {})
    if not isinstance(database_config, dict):
        raise DiaryDatabaseError(
            f"Voice Diary config at {selected_config} has an invalid database section"
        )
    configured_path = database_config.get("path", DEFAULT_DATABASE_PATH)
    if not isinstance(configured_path, str) or not configured_path.strip():
        raise DiaryDatabaseError("Voice Diary config has no valid database path")
    return Path(configured_path).expanduser().resolve()


def _validate_schema(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
    ).fetchall()
    existing = {str(row[0]) for row in rows}
    missing = sorted(REQUIRED_TABLES - existing)
    if missing:
        raise DiaryDatabaseError(
            "Voice Diary database is not ready for MCP search; missing "
            f"{', '.join(missing)}. Open or update Voice Diary first."
        )

    utterance_columns = {
        str(row[1]) for row in conn.execute("PRAGMA table_info(utterances)").fetchall()
    }
    required_columns = {"source", "speaker_segment_id", "started_ms", "ended_ms"}
    missing_columns = sorted(required_columns - utterance_columns)
    if missing_columns:
        raise DiaryDatabaseError(
            "Voice Diary database schema is outdated; missing utterance columns "
            f"{', '.join(missing_columns)}. Open or update Voice Diary first."
        )


@contextmanager
def open_read_connection(path: Path) -> Iterator[sqlite3.Connection]:
    """Open one short-lived SQLite connection that cannot perform writes."""
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise DiaryDatabaseError(f"Voice Diary database does not exist: {resolved}")

    try:
        conn = sqlite3.connect(
            f"{resolved.as_uri()}?mode=ro",
            uri=True,
            timeout=2.0,
            check_same_thread=False,
        )
    except sqlite3.Error as exc:
        raise DiaryDatabaseError(f"Cannot open Voice Diary database: {exc}") from exc

    conn.row_factory = sqlite3.Row
    conn.create_function(
        "CASEFOLD", 1, lambda value: str(value).casefold() if value is not None else ""
    )
    try:
        conn.execute("PRAGMA query_only = ON")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 2000")
        _validate_schema(conn)
        yield conn
    except sqlite3.Error as exc:
        raise DiaryDatabaseError(f"Voice Diary database search failed: {exc}") from exc
    finally:
        conn.close()
