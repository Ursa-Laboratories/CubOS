"""`python -m zoo` entry point."""

import logging
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn

from zoo.config import ZooSettings

FRONTEND_DIR = Path(
    os.environ.get("CUB_WEB_DIR", Path(__file__).resolve().parents[2] / "web")
)
FRONTEND_DIST = FRONTEND_DIR / "dist"
log = logging.getLogger(__name__)


def main() -> None:
    settings = ZooSettings()

    if not FRONTEND_DIST.is_dir():
        log.warning(
            "compiled web assets were not found at %s; run `npm run build` in web/",
            FRONTEND_DIST,
        )

    if settings.open_browser:

        def _open() -> None:
            time.sleep(1.5)
            webbrowser.open(f"http://{settings.host}:{settings.port}")

        threading.Thread(target=_open, daemon=True).start()

    uvicorn.run(
        "zoo.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
