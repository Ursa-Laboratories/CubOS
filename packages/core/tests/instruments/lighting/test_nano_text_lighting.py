from unittest.mock import MagicMock, patch

import pytest

from cubos.instruments.lighting.exceptions import (
    LightingCommandError,
    LightingConnectionError,
    LightingTimeoutError,
)
from cubos.instruments.controllers.nano_text import (
    NanoTextCommandError,
    NanoTextTimeoutError,
)
from cubos.instruments.lighting.vendors.nano_text import NanoTextLighting
from cubos.instruments.registry import get_instrument_class


def _serial_with(*responses: str) -> MagicMock:
    link = MagicMock()
    link.is_open = True
    link.readline.side_effect = [f"{response}\n".encode() for response in responses]
    return link


def test_registry_resolves_nano_text_lighting():
    assert get_instrument_class("lighting", "nano_text") is NanoTextLighting


def test_offline_rgbw_channel_composition():
    lights = NanoTextLighting(offline=True)
    lights.set_channel("red", 100)
    lights.set_channel("blue", 50)
    assert lights.status().channels == {
        "red": 100,
        "green": 0,
        "blue": 50,
        "white": 0,
    }


@patch("cubos.instruments.controllers.nano_text.time.sleep")
@patch("cubos.instruments.controllers.nano_text.serial.Serial")
def test_connect_identifies_board_and_forces_off(serial_cls, _sleep):
    serial_link = _serial_with("LIGHT_MODULE", "OK OFF")
    serial_cls.return_value = serial_link
    lights = NanoTextLighting(port="/dev/ttyUSB1")

    lights.connect()

    assert [call.args[0] for call in serial_link.write.call_args_list] == [
        b"ID?\n",
        b"OFF\n",
    ]
    assert lights.health_check() is True


@patch("cubos.instruments.controllers.nano_text.time.sleep")
@patch("cubos.instruments.controllers.nano_text.serial.Serial")
def test_set_channel_sends_composed_rgbw(serial_cls, _sleep):
    serial_link = _serial_with("LIGHT_MODULE", "OK OFF", "OK RGBW", "OK RGBW")
    serial_cls.return_value = serial_link
    lights = NanoTextLighting(port="/dev/ttyUSB1")
    lights.connect()

    lights.set_channel("red", 100)
    lights.set_channel("blue", 50)

    assert [call.args[0] for call in serial_link.write.call_args_list][-2:] == [
        b"RGBW 255 0 0 0\n",
        b"RGBW 255 0 128 0\n",
    ]


@patch("cubos.instruments.controllers.nano_text.time.sleep")
@patch("cubos.instruments.controllers.nano_text.serial.Serial")
def test_wrong_module_is_rejected(serial_cls, _sleep):
    serial_cls.return_value = _serial_with("CAP_MODULE")
    lights = NanoTextLighting(port="/dev/ttyUSB2")

    with pytest.raises(LightingConnectionError, match="Expected LIGHT_MODULE"):
        lights.connect()


def test_hardware_command_requires_connection():
    lights = NanoTextLighting(port="/dev/ttyUSB1")
    with pytest.raises(LightingCommandError, match="Not connected"):
        lights.set_channel("white", 25)


def test_offline_lifecycle_and_channels():
    lights = NanoTextLighting(offline=True)
    lights.connect()
    assert set(lights.channels) == {"red", "green", "blue", "white"}
    assert lights.health_check() is True
    lights.set_channel("white", 100)
    lights.all_off()
    lights.disconnect()
    assert all(level == 0 for level in lights.status().channels.values())


def test_connect_requires_port():
    with pytest.raises(LightingConnectionError, match="non-empty"):
        NanoTextLighting().connect()


@pytest.mark.parametrize("error", [NanoTextCommandError("bad"), NanoTextTimeoutError("late")])
@patch("cubos.instruments.lighting.vendors.nano_text.NanoTextLink")
def test_connect_wraps_safe_off_failure(link_cls, error):
    link_cls.return_value.send.side_effect = error
    with pytest.raises(LightingConnectionError, match="initialize safely"):
        NanoTextLighting(port="/dev/ttyUSB1").connect()
    link_cls.return_value.disconnect.assert_called_once()


def test_disconnect_attempts_off_and_releases_link():
    lights = NanoTextLighting(port="/dev/ttyUSB1")
    lights._link = MagicMock(is_open=True)
    lights._link.send.side_effect = NanoTextCommandError("gone")
    link = lights._link
    lights.disconnect()
    link.disconnect.assert_called_once()
    assert lights._link is None


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (NanoTextTimeoutError("late"), LightingTimeoutError),
        (NanoTextCommandError("bad"), LightingCommandError),
    ],
)
def test_set_channel_maps_transport_errors(error, expected):
    lights = NanoTextLighting(port="/dev/ttyUSB1")
    lights._link = MagicMock()
    lights._link.send.side_effect = error
    with pytest.raises(expected):
        lights.set_channel("white", 25)


def test_all_off_requires_connection_and_maps_errors():
    lights = NanoTextLighting(port="/dev/ttyUSB1")
    with pytest.raises(LightingCommandError, match="Not connected"):
        lights.all_off()
    lights._link = MagicMock()
    lights._link.send.side_effect = NanoTextTimeoutError("late")
    with pytest.raises(LightingTimeoutError):
        lights.all_off()
    lights._link.send.side_effect = NanoTextCommandError("bad")
    with pytest.raises(LightingCommandError):
        lights.all_off()


def test_unexpected_success_response_is_rejected():
    lights = NanoTextLighting(port="/dev/ttyUSB1")
    lights._link = MagicMock()
    lights._link.send.return_value = "OK RED"
    with pytest.raises(LightingCommandError, match="Unexpected response"):
        lights.set_channel("red", 10)
