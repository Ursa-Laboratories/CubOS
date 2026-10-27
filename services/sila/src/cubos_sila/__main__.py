"""Start the CubOS SiLA server from a local deployment configuration."""

import argparse
import asyncio
import logging
from pathlib import Path
import signal

from . import __version__
from .config import ConfigurationError, load_settings
from .connector import create_app


async def serve(settings) -> None:
    app = create_app(settings)
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    installed = []
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, stopped.set)
        except NotImplementedError:
            continue
        installed.append(signum)
    try:
        await app.start()
        await stopped.wait()
    finally:
        for signum in installed:
            loop.remove_signal_handler(signum)
        await app.stop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Expose configured CubOS protocols through SiLA 2")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--config", required=True, type=Path, help="Path to local YAML deployment settings")
    parser.add_argument("--allow-hardware", action="store_true", help="Explicitly enable presets with mock_mode: false")
    args = parser.parse_args(argv)
    try:
        settings = load_settings(args.config, allow_hardware=args.allow_hardware)
    except ConfigurationError as error:
        parser.error(str(error))
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(serve(settings))
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
