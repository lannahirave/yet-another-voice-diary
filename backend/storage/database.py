"""Database connection and operations."""
import sqlite3
from pathlib import Path
from typing import Optional

from ..config import DatabaseConfig


class Database:
    """SQLite database connection wrapper."""

    def __init__(self, config: DatabaseConfig):
        self.config = config
        self.config.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection: Optional[sqlite3.Connection] = None

    def connect(self) -> sqlite3.Connection:
        """Get or create database connection."""
        if self._connection is None:
            self._connection = sqlite3.connect(
                str(self.config.path),
                check_same_thread=False,
            )
            if self.config.echo:
                self._connection.set_trace_callback(print)
        return self._connection

    def init_schema(self):
        """Initialize database schema from schema.sql."""
        conn = self.connect()
        schema_path = Path(__file__).parent / "schema.sql"
        with open(schema_path) as f:
            schema = f.read()
        conn.executescript(schema)
        conn.commit()

    def execute(self, sql: str, params: tuple = ()):
        """Execute a single statement."""
        conn = self.connect()
        conn.execute(sql, params)
        conn.commit()

    def fetch_one(self, sql: str, params: tuple = ()):
        """Fetch a single row."""
        conn = self.connect()
        cursor = conn.execute(sql, params)
        return cursor.fetchone()

    def fetch_all(self, sql: str, params: tuple = ()):
        """Fetch all rows."""
        conn = self.connect()
        cursor = conn.execute(sql, params)
        return cursor.fetchall()

    def close(self):
        """Close connection."""
        if self._connection:
            self._connection.close()
            self._connection = None
