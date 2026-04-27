"""Database migrations."""
from typing import Callable

from .database import Database


class Migration:
    """Base migration class."""

    def __init__(self, name: str, up: Callable, down: Callable):
        self.name = name
        self.up = up
        self.down = down


class MigrationRunner:
    """Manages database migrations."""

    def __init__(self, db: Database):
        self.db = db
        self.migrations: list[Migration] = []
        self._ensure_migrations_table()

    def _ensure_migrations_table(self):
        """Create migrations tracking table."""
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                name TEXT PRIMARY KEY,
                applied_at INTEGER NOT NULL
            )
            """
        )

    def register(self, migration: Migration):
        """Register a migration."""
        self.migrations.append(migration)

    def apply_pending(self):
        """Apply all pending migrations."""
        for migration in self.migrations:
            row = self.db.fetch_one(
                "SELECT name FROM schema_migrations WHERE name = ?",
                (migration.name,)
            )
            if not row:
                migration.up(self.db)
                import time
                self.db.execute(
                    "INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)",
                    (migration.name, int(time.time()))
                )
