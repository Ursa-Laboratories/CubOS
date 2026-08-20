"""Tests for the lighting interface and the Pawduino lighting vendor."""

from unittest.mock import MagicMock

import pytest

from cubos.instruments._shared.pawduino_link import PawduinoLink
from cubos.instruments.base_instrument import BaseInstrument
from cubos.instruments.lighting.exceptions import (
    LightingCommandError,
    LightingConfigError,
)
from cubos.instruments.lighting.interface import LightingInstrument
from cubos.instruments.lighting.vendors.pawduino import PawduinoLighting
from cubos.instruments.registry import get_instrument_class


def _offline_lights(**overrides):
    kwargs = dict(offline=True)
    kwargs.update(overrides)
    return PawduinoLighting(**kwargs)


def _linked_lights(responses=None):
    """Lighting driver with a pre-opened mocked link (bypassing connect)."""
    lights = PawduinoLighting(port="/dev/ttyACM0")
    mock_ser = MagicMock()
    mock_ser.is_open = True
    mock_ser.in_waiting = 0
    if responses is None:
        mock_ser.readline.return_value = b"OK:done\n"
    else:
        mock_ser.readline.side_effect = [r.encode() for r in responses]
    link = PawduinoLink.acquire("/dev/ttyACM0")
    link._serial = mock_ser
    link._holders = 1
    lights._link = link
    return lights, mock_ser


class TestInterface:
    def test_is_base_instrument(self):
        assert issubclass(PawduinoLighting, BaseInstrument)
        assert issubclass(PawduinoLighting, LightingInstrument)

    def test_registry_resolves_vendor(self):
        assert get_instrument_class("lighting", "pawduino") is PawduinoLighting

    def test_declared_channels(self):
        channels = _offline_lights().channels
        assert channels["white"] == (5, 10, 15, 25, 50, 100)
        assert channels["contact"] == (5, 10, 20, 30, 50)

    def test_unknown_channel_rejected(self):
        with pytest.raises(LightingConfigError, match="Unknown lighting channel"):
            _offline_lights().set_channel("uv", 50)

    def test_unsupported_level_rejected_with_valid_set(self):
        with pytest.raises(LightingConfigError, match="5, 10, 20, 30, 50"):
            _offline_lights().set_channel("contact", 60)

    def test_zero_always_allowed(self):
        lights = _offline_lights()
        lights.set_channel("white", 0)
        assert lights.status().channels["white"] == 0


class TestOffline:
    def test_status_shadows_channel_state(self):
        lights = _offline_lights()
        lights.connect()
        lights.set_channel("white", 25)
        assert lights.status().channels == {"white": 25, "contact": 0}
        lights.set_channel("contact", 50)
        assert lights.status().channels == {"white": 25, "contact": 50}
        lights.all_off()
        assert lights.status().channels == {"white": 0, "contact": 0}

    def test_health_check(self):
        assert _offline_lights().health_check() is True

    def test_connect_resets_shadow(self):
        lights = _offline_lights()
        lights.set_channel("white", 25)
        lights.connect()
        assert lights.status().channels["white"] == 0


class TestSerialProtocol:
    @pytest.mark.parametrize(
        ("channel", "level", "expected"),
        [
            ("white", 100, b"17\n"),
            ("white", 50, b"18\n"),
            ("white", 25, b"19\n"),
            ("white", 15, b"20\n"),
            ("white", 10, b"21\n"),
            ("white", 5, b"22\n"),
            ("white", 0, b"2\n"),
            ("contact", 50, b"23\n"),
            ("contact", 30, b"24\n"),
            ("contact", 20, b"25\n"),
            ("contact", 10, b"26\n"),
            ("contact", 5, b"27\n"),
            ("contact", 0, b"4\n"),
        ],
    )
    def test_channel_level_command_ids(self, channel, level, expected):
        lights, mock_ser = _linked_lights()
        lights.set_channel(channel, level)
        assert mock_ser.write.call_args[0][0] == expected

    def test_all_off_sends_both_off_commands(self):
        lights, mock_ser = _linked_lights()
        lights.all_off()
        sent = [call[0][0] for call in mock_ser.write.call_args_list]
        assert set(sent) == {b"2\n", b"4\n"}

    def test_err_response_raises_and_shadow_unchanged(self):
        lights, _ = _linked_lights(["ERR:no lights\n"])
        with pytest.raises(LightingCommandError, match="no lights"):
            lights.set_channel("white", 50)
        assert lights.status().channels["white"] == 0

    def test_not_connected_raises(self):
        lights = PawduinoLighting(port="/dev/ttyACM0")
        with pytest.raises(LightingCommandError, match="Not connected"):
            lights.set_channel("white", 50)
