"""Voice Diary MCP server: local, read-only diary retrieval over stdio."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from .mcp.diary_search import DiarySearchService
from .mcp.read_connection import load_database_path

_database_path: Path | None = None

mcp = FastMCP(
    "Voice Diary",
    instructions=(
        "Search the user's local Voice Diary. Results contain sensitive diary text. "
        "Use concise queries and retrieve only information needed for the user's request."
    ),
)


def _service() -> DiarySearchService:
    return DiarySearchService(_database_path or load_database_path())


@mcp.tool()
def search_transcripts(
    query: str,
    session_id: str | None = None,
    contact_id: str | None = None,
    language: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Search diary transcripts and return concise, attributed snippets.

    Filter by session, known contact, or language when the user's request names
    one. The limit is clamped to 1-50. This tool never returns audio or voice
    embeddings.
    """
    return _service().search_transcripts(
        query,
        session_id=session_id,
        contact_id=contact_id,
        language=language,
        limit=limit,
    )


@mcp.tool()
def search_diary(query: str, limit: int = 20) -> dict[str, Any]:
    """Search transcripts, session titles/notes, and known contacts.

    Results are grouped by session and ordered with transcript matches first.
    Use this for broad questions about what, when, or with whom something was
    discussed. The limit is clamped to 1-50.
    """
    return _service().search_diary(query, limit=limit)


def main() -> None:
    parser = argparse.ArgumentParser(description="Voice Diary read-only MCP server")
    parser.add_argument("--config", type=Path, help="Voice Diary config JSON path")
    parser.add_argument("--database", type=Path, help="Explicit diary SQLite path")
    args = parser.parse_args()

    global _database_path
    _database_path = load_database_path(
        config_path=args.config,
        database_path=args.database,
    )
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
