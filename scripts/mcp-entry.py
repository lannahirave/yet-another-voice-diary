"""PyInstaller entry point for the standalone Voice Diary MCP sidecar."""
from __future__ import annotations

from backend.mcp_server import main


if __name__ == "__main__":
    main()
