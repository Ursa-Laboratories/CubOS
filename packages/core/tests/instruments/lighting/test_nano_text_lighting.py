from unittest.mock import MagicMock, patch

import pytest

from cubos.instruments.lighting.exceptions import (
    LightingCommandError,
    LightingConnectionError,
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
