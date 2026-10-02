from unittest.mock import MagicMock, patch

import pytest

from cubos.instruments.capper.exceptions import (
    CapperCommandError,
    CapperConnectionError,
    CapperSensorFault,
)
from cubos.instruments.capper.vendors.nano_text import NanoTextCapper
from cubos.instruments.registry import get_instrument_class


def _serial_with(*responses: str) -> MagicMock:
    link = MagicMock()
    link.is_open = True
    link.readline.side_effect = [f"{response}\n".encode() for response in responses]
    return link


def _capper(**overrides) -> NanoTextCapper:
    kwargs = {"engage_depth_mm": -10.0, "port": "/dev/ttyUSB2"}
    kwargs.update(overrides)
    return NanoTextCapper(**kwargs)


def test_registry_resolves_nano_text_capper():
    assert get_instrument_class("capper", "nano_text") is NanoTextCapper


def test_offline_capture_release():
    capper = _capper(offline=True)
    capper.capture_cap()
    assert capper.read_cap_present() is True
    capper.release_cap()
    assert capper.read_cap_present() is False


@patch("cubos.instruments.controllers.nano_text.time.sleep")
@patch("cubos.instruments.controllers.nano_text.serial.Serial")
def test_connect_identifies_board_and_reads_sensor(serial_cls, _sleep):
    serial_link = _serial_with(
        "CAP_MODULE", "CAP NOT_DETECTED", "CAP NOT_DETECTED"
    )
    serial_cls.return_value = serial_link
    capper = _capper()

    capper.connect()

    assert [call.args[0] for call in serial_link.write.call_args_list] == [
        b"ID?\n",
        b"CAP?\n",
    ]
    assert capper.get_status().cap_present is False


@patch("cubos.instruments.controllers.nano_text.time.sleep")
@patch("cubos.instruments.controllers.nano_text.serial.Serial")
def test_capture_and_release_commands(serial_cls, _sleep):
    serial_link = _serial_with(
        "CAP_MODULE",
        "CAP NOT_DETECTED",
        "OK MAGNET ON",
        "OK MAGNET OFF",
    )
    serial_cls.return_value = serial_link
    capper = _capper()
    capper.connect()

    capper.capture_cap()
    capper.release_cap()

    assert [call.args[0] for call in serial_link.write.call_args_list][-2:] == [
        b"MAGNET ON\n",
        b"MAGNET OFF\n",
    ]


@patch("cubos.instruments.controllers.nano_text.time.sleep")
@patch("cubos.instruments.controllers.nano_text.serial.Serial")
def test_wrong_module_is_rejected(serial_cls, _sleep):
    serial_cls.return_value = _serial_with("LIGHT_MODULE")
    with pytest.raises(CapperConnectionError, match="Expected CAP_MODULE"):
        _capper().connect()


def test_unknown_sensor_response_fails_closed():
    capper = _capper()
    capper._link = MagicMock()
    capper._link.send.return_value = "CAP MAYBE"
    with pytest.raises(CapperSensorFault, match="Unexpected CAP"):
        capper.read_cap_present()


def test_hardware_command_requires_connection():
    with pytest.raises(CapperCommandError, match="Not connected"):
        _capper().capture_cap()
