from unittest.mock import MagicMock

import pytest
import serial

from cubos.instruments.controllers.nano_text import (
    NanoTextCommandError,
    NanoTextConfigError,
    NanoTextConnectionError,
    NanoTextLink,
    NanoTextTimeoutError,
)


def test_empty_port_is_rejected():
    with pytest.raises(NanoTextConfigError, match="non-empty"):
        NanoTextLink("")


def test_serial_open_failure_is_wrapped(monkeypatch):
    def fail_open(**_kwargs):
        raise serial.SerialException("busy")

    monkeypatch.setattr("cubos.instruments.controllers.nano_text.serial.Serial", fail_open)
    with pytest.raises(NanoTextConnectionError, match="busy"):
        NanoTextLink("/dev/ttyUSB0").connect("LIGHT_MODULE")


def test_disconnect_handles_closed_and_failing_ports():
    link = NanoTextLink("/dev/ttyUSB0")
    link.disconnect()
    serial_link = MagicMock(is_open=True)
    serial_link.close.side_effect = serial.SerialException("gone")
    link._serial = serial_link
    link.disconnect()
    assert link._serial is None


def test_send_requires_open_port():
    with pytest.raises(NanoTextCommandError, match="not connected"):
        NanoTextLink("/dev/ttyUSB0").send("ID?")


def test_send_wraps_write_and_read_failures():
    link = NanoTextLink("/dev/ttyUSB0")
    serial_link = MagicMock(is_open=True)
    serial_link.write.side_effect = serial.SerialException("write failed")
    link._serial = serial_link
    with pytest.raises(NanoTextCommandError, match="Failed to send"):
        link.send("OFF")

    serial_link.write.side_effect = None
    serial_link.readline.side_effect = serial.SerialException("read failed")
    with pytest.raises(NanoTextCommandError, match="Serial read failed"):
        link.send("OFF")


def test_send_ignores_banner_and_reports_module_errors():
    link = NanoTextLink("/dev/ttyUSB0")
    serial_link = MagicMock(is_open=True)
    serial_link.readline.side_effect = [b"LIGHT_MODULE_READY\n", b"\n", b"OK OFF\n"]
    link._serial = serial_link
    assert link.send("OFF") == "OK OFF"

    serial_link.readline.side_effect = [b"ERROR UNKNOWN_COMMAND\n"]
    with pytest.raises(NanoTextCommandError, match="UNKNOWN_COMMAND"):
        link.send("NOPE")


def test_send_times_out():
    link = NanoTextLink("/dev/ttyUSB0", command_timeout=0.0)
    link._serial = MagicMock(is_open=True)
    with pytest.raises(NanoTextTimeoutError, match="Timed out"):
        link.send("ID?")
