from unittest.mock import MagicMock, patch

import pytest

from cubos.instruments.capper.exceptions import (
    CapperCommandError,
    CapperConnectionError,
    CapperSensorFault,
    CapperTimeoutError,
)
from cubos.instruments.controllers.nano_text import (
    NanoTextCommandError,
    NanoTextTimeoutError,
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


def test_offline_health_and_disconnect():
    capper = _capper(offline=True)
    capper.connect()
    assert capper.health_check() is True
    capper.disconnect()


def test_health_check_handles_connection_and_sensor_failures():
    capper = _capper()
    assert capper.health_check() is False
    capper._link = MagicMock(is_open=True)
    capper._link.send.return_value = "CAP DETECTED"
    assert capper.health_check() is True
    capper._link.send.side_effect = NanoTextCommandError("gone")
    assert capper.health_check() is False


@patch("cubos.instruments.capper.vendors.nano_text.NanoTextLink")
def test_connect_wraps_sensor_probe_failure(link_cls):
    link_cls.return_value.send.side_effect = NanoTextTimeoutError("late")
    with pytest.raises(CapperConnectionError, match="sensor probe"):
        _capper().connect()
    link_cls.return_value.disconnect.assert_called_once()


def test_unexpected_magnet_responses_are_rejected():
    capper = _capper()
    capper._link = MagicMock()
    capper._link.send.side_effect = ["OK MAYBE", "OK MAYBE"]
    with pytest.raises(CapperCommandError, match="MAGNET ON"):
        capper.capture_cap()
    with pytest.raises(CapperCommandError, match="MAGNET OFF"):
        capper.release_cap()


def test_sensor_detected_updates_status():
    capper = _capper()
    capper._link = MagicMock()
    capper._link.send.return_value = "CAP DETECTED"
    assert capper.read_cap_present() is True


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (NanoTextTimeoutError("late"), CapperTimeoutError),
        (NanoTextCommandError("bad"), CapperCommandError),
    ],
)
def test_transport_errors_are_mapped(error, expected):
    capper = _capper()
    capper._link = MagicMock()
    capper._link.send.side_effect = error
    with pytest.raises(expected):
        capper.read_cap_present()


def test_disconnect_releases_link():
    capper = _capper()
    capper._link = MagicMock()
    link = capper._link
    capper.disconnect()
    link.disconnect.assert_called_once()
    assert capper._link is None
