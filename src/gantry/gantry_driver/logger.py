"""Logger helpers for the low-level GRBL driver."""

import logging
from pathlib import Path


def set_up_mill_logger(
    path_to_logs: Path | None = None,
) -> logging.Logger:
    """Set up the mill logger.

    File logging is opt-in. The driver is often constructed in tests and setup
    helpers, so the default must not create package-local log files.
    """
    logger = logging.getLogger("grbl_cnc_mill")
    logger.setLevel(logging.DEBUG)
    if path_to_logs is None:
        if not logger.handlers:
            logger.addHandler(logging.NullHandler())
        return logger

    path_to_logs = Path(path_to_logs)
    path_to_logs.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(
        "%(asctime)s&%(name)s&%(levelname)s&%(module)s&%(funcName)s&%(lineno)d&%(message)s"
    )
    log_file = path_to_logs / "mill_control.log"
    if not any(
        isinstance(handler, logging.FileHandler)
        and Path(handler.baseFilename) == log_file
        for handler in logger.handlers
    ):
        system_handler = logging.FileHandler(log_file)
        system_handler.setFormatter(formatter)
        logger.addHandler(system_handler)

    return logger


def set_up_command_logger(
    path_to_logs: Path | None = None,
) -> logging.Logger:
    """Set up the command logger.

    File logging is opt-in for the same reason as ``set_up_mill_logger``.
    """
    logger = logging.getLogger("grbl_cnc_mill_cmds")
    logger.setLevel(logging.DEBUG)
    if path_to_logs is None:
        if not logger.handlers:
            logger.addHandler(logging.NullHandler())
        return logger

    path_to_logs = Path(path_to_logs)
    path_to_logs.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(message)s")
    log_file = path_to_logs / "command.log"
    if not any(
        isinstance(handler, logging.FileHandler)
        and Path(handler.baseFilename) == log_file
        for handler in logger.handlers
    ):
        system_handler = logging.FileHandler(log_file)
        system_handler.setFormatter(formatter)
        logger.addHandler(system_handler)

    return logger
