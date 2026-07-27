"""Desktop-owned CubOS API process with stdin-driven graceful shutdown."""

from __future__ import annotations

import sys
import threading
from typing import BinaryIO

import uvicorn

from cubos_api.config import CubOSSettings


def _watch_for_shutdown(server: uvicorn.Server, stream: BinaryIO) -> None:
    """Request shutdown when the desktop parent closes its stdin pipe."""
    try:
        stream.read()
    finally:
        server.should_exit = True


def main() -> None:
    settings = CubOSSettings()
    config = uvicorn.Config(
        "cubos_api.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        reload=False,
    )
    server = uvicorn.Server(config)
    threading.Thread(
        target=_watch_for_shutdown,
        args=(server, sys.stdin.buffer),
        name="cubos-desktop-shutdown",
        daemon=True,
    ).start()
    server.run()


if __name__ == "__main__":
    main()
