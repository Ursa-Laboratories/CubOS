"""`python -m cubos_api` entry point."""

import logging
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn

from cubos_api.config import CubOSSettings

FRONTEND_DIR = Path(
    os.environ.get(
        "CUBOS_WEB_DIR",
        Path(__file__).resolve().parents[4] / "apps" / "operator-web",
    )
)
FRONTEND_DIST = FRONTEND_DIR / "dist"
log = logging.getLogger(__name__)


def main() -> None:
    settings = CubOSSettings()

    if not FRONTEND_DIST.is_dir():
        log.warning(
            "compiled web assets were not found at %s; run `npm run build` in apps/operator-web/",
            FRONTEND_DIST,
        )

    if settings.open_browser:

        def _open() -> None:
            time.sleep(1.5)
            webbrowser.open(f"http://{settings.host}:{settings.port}")

        threading.Thread(target=_open, daemon=True).start()

    uvicorn.run(
        "cubos_api.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
