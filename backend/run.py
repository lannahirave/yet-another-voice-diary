"""Uvicorn entry point — binds 127.0.0.1:8765 (loopback only)."""
from __future__ import annotations


def main() -> None:
    import uvicorn

    uvicorn.run(
        "backend.api.app:create_app",
        factory=True,
        host="127.0.0.1",
        port=8765,
        log_level="info",
        reload=False,
    )


if __name__ == "__main__":
    main()
