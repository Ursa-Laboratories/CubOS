"""Tests for the GRBL driver logger setup.

Regression guard: the driver subsystem must never silently discard errors.
Both helpers must attach a real file handler and, for the mill logger, a
console ERROR handler — even when no explicit ``path_to_logs`` is provided.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from gantry.gantry_driver import logger as logger_module
from gantry.gantry_driver.logger import (
    set_up_command_logger,
    set_up_mill_logger,
)


@pytest.fixture(autouse=True)
def _isolate_loggers(tmp_path, monkeypatch):
    """Each test gets a clean logger state and tmp default log dir."""
    monkeypatch.setattr(logger_module, "DEFAULT_LOG_DIR", tmp_path / "default")
    for name in ("grbl_cnc_mill", "grbl_cnc_mill_cmds"):
        existing = logging.getLogger(name)
        for handler in list(existing.handlers):
            existing.removeHandler(handler)
            handler.close()
    yield
    for name in ("grbl_cnc_mill", "grbl_cnc_mill_cmds"):
        existing = logging.getLogger(name)
        for handler in list(existing.handlers):
            existing.removeHandler(handler)
            handler.close()


def _file_handlers(logger: logging.Logger) -> list[logging.FileHandler]:
    return [h for h in logger.handlers if isinstance(h, logging.FileHandler)]


def _console_handlers(logger: logging.Logger) -> list[logging.StreamHandler]:
    return [
        h
        for h in logger.handlers
        if isinstance(h, logging.StreamHandler)
        and not isinstance(h, logging.FileHandler)
    ]


def test_mill_logger_attaches_file_and_console_when_no_path(tmp_path, monkeypatch):
    monkeypatch.setattr(logger_module, "DEFAULT_LOG_DIR", tmp_path / "default")
    logger = set_up_mill_logger()
    file_handlers = _file_handlers(logger)
    assert len(file_handlers) == 1
    assert Path(file_handlers[0].baseFilename).name == "mill_control.log"
    console = _console_handlers(logger)
    assert len(console) == 1
    assert console[0].level <= logging.ERROR


def test_mill_logger_uses_explicit_path(tmp_path):
    logger = set_up_mill_logger(tmp_path / "explicit")
    file_handlers = _file_handlers(logger)
    assert any(
        Path(h.baseFilename).parent == tmp_path / "explicit" for h in file_handlers
    )


def test_mill_logger_is_idempotent(tmp_path):
    set_up_mill_logger(tmp_path)
    set_up_mill_logger(tmp_path)
    logger = logging.getLogger("grbl_cnc_mill")
    assert len(_file_handlers(logger)) == 1
    assert len(_console_handlers(logger)) == 1


def test_command_logger_attaches_file_when_no_path(tmp_path, monkeypatch):
    monkeypatch.setattr(logger_module, "DEFAULT_LOG_DIR", tmp_path / "default")
    logger = set_up_command_logger()
    file_handlers = _file_handlers(logger)
    assert len(file_handlers) == 1
    assert Path(file_handlers[0].baseFilename).name == "command.log"


def test_command_logger_is_idempotent(tmp_path):
    set_up_command_logger(tmp_path)
    set_up_command_logger(tmp_path)
    logger = logging.getLogger("grbl_cnc_mill_cmds")
    assert len(_file_handlers(logger)) == 1


def test_mill_logger_writes_error_to_file(tmp_path):
    logger = set_up_mill_logger(tmp_path)
    logger.error("alarm:1 hard limit")
    for handler in _file_handlers(logger):
        handler.flush()
    contents = (tmp_path / "mill_control.log").read_text()
    assert "alarm:1 hard limit" in contents


def test_command_logger_writes_command_to_file(tmp_path):
    logger = set_up_command_logger(tmp_path)
    logger.debug("G01 X10 F2000")
    for handler in _file_handlers(logger):
        handler.flush()
    contents = (tmp_path / "command.log").read_text()
    assert "G01 X10 F2000" in contents
