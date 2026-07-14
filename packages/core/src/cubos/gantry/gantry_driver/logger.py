"""Logger helpers for the low-level GRBL driver.

This subsystem drives real hardware, so driver errors and serial commands
must never be silently discarded. Both helpers:

- attach a file handler under ``path_to_logs`` (defaulting to
  ``$CUBOS_GANTRY_LOG_DIR`` if set, otherwise ``~/.cubos/logs/gantry/``) so
  ``mill_control.log`` and ``command.log`` always exist for post-incident
  forensics, and
- attach a console handler at ``ERROR`` (mill logger only) so GRBL
  alarms/errors surface even without anyone tailing the file.

The log directory is resolved when the driver connects. If the resolved
directory cannot be created (e.g. a read-only ``$HOME`` in a hardened
container), we fall back to a per-user temp directory and warn, rather
than crashing the gantry connect — forensic logging degrades but the
mill still comes online. Set ``$CUBOS_GANTRY_LOG_DIR`` to a writable path
(the appliance image points it at the persistent ``/var/lib/cub`` volume)
to keep logs where you want them.
"""

import logging
import os
import tempfile
from pathlib import Path

#: Environment variable overriding where gantry logs are written.
GANTRY_LOG_DIR_ENV = "CUBOS_GANTRY_LOG_DIR"

#: Fallback default when ``$CUBOS_GANTRY_LOG_DIR`` is unset.
DEFAULT_LOG_DIR = Path.home() / ".cubos" / "logs" / "gantry"

logger = logging.getLogger(__name__)

_MILL_FORMAT = (
    "%(asctime)s&%(name)s&%(levelname)s&%(module)s&%(funcName)s&%(lineno)d&%(message)s"
)
_COMMAND_FORMAT = "%(message)s"


def default_log_dir() -> Path:
    """Return the configured gantry log directory (env override wins)."""
    override = os.environ.get(GANTRY_LOG_DIR_ENV)
    if override:
        return Path(override).expanduser()
    return DEFAULT_LOG_DIR


def _resolve_log_dir(path_to_logs: Path | None) -> Path:
    candidate = Path(path_to_logs) if path_to_logs is not None else default_log_dir()
    try:
        candidate.mkdir(parents=True, exist_ok=True)
        return candidate
    except OSError as exc:
        fallback = Path(tempfile.gettempdir()) / "cubos" / "logs" / "gantry"
        # If even the temp fallback can't be created, let the OSError propagate:
        # something is badly wrong and silently discarding logs would be worse.
        fallback.mkdir(parents=True, exist_ok=True)
        logger.warning(
            "Gantry log dir %s is not writable (%s); falling back to %s. "
            "Set %s to a writable path to control log placement.",
            candidate,
            exc,
            fallback,
            GANTRY_LOG_DIR_ENV,
        )
        return fallback


def _has_file_handler_for(logger: logging.Logger, log_file: Path) -> bool:
    return any(
        isinstance(handler, logging.FileHandler)
        and Path(handler.baseFilename) == log_file
        for handler in logger.handlers
    )


def _has_console_error_handler(logger: logging.Logger) -> bool:
    return any(
        isinstance(handler, logging.StreamHandler)
        and not isinstance(handler, logging.FileHandler)
        and handler.level <= logging.ERROR
        for handler in logger.handlers
    )


def set_up_mill_logger(
    path_to_logs: Path | None = None,
) -> logging.Logger:
    """Configure the GRBL mill logger.

    Always attaches a file handler (default ``~/.cubos/logs/gantry/mill_control.log``)
    and a console ERROR handler. Idempotent — safe to call repeatedly.
    """
    logger = logging.getLogger("grbl_cnc_mill")
    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter(_MILL_FORMAT)

    log_file = _resolve_log_dir(path_to_logs) / "mill_control.log"
    if not _has_file_handler_for(logger, log_file):
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    if not _has_console_error_handler(logger):
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.ERROR)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger


def set_up_command_logger(
    path_to_logs: Path | None = None,
) -> logging.Logger:
    """Configure the serial-command forensic logger.

    Always attaches a file handler (default ``~/.cubos/logs/gantry/command.log``)
    so every command sent to GRBL is recorded. Idempotent.
    """
    logger = logging.getLogger("grbl_cnc_mill_cmds")
    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter(_COMMAND_FORMAT)

    log_file = _resolve_log_dir(path_to_logs) / "command.log"
    if not _has_file_handler_for(logger, log_file):
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger
