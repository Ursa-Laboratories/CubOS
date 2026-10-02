"""RGBW ring lighting driven by the dedicated LIGHT_MODULE Nano firmware."""

from __future__ import annotations

from typing import Mapping, Optional, Tuple

from cubos.instruments.controllers.nano_text import (
    NanoTextCommandError,
    NanoTextConfigError,
    NanoTextConnectionError,
    NanoTextLink,
    NanoTextTimeoutError,
)
from cubos.instruments.lighting.exceptions import (
    LightingCommandError,
    LightingConnectionError,
    LightingTimeoutError,
)
from cubos.instruments.lighting.interface import LightingInstrument
from cubos.instruments.lighting.models import LightingStatus


_CHANNELS = ("red", "green", "blue", "white")
_LEVELS = tuple(range(1, 101))


class NanoTextLighting(LightingInstrument):
    """Four-channel RGBW lighting over newline-delimited Nano commands."""

    def __init__(
        self,
        *,
        port: str = "",
        baud_rate: int = 115200,
        command_timeout: float = 3.0,
        name: Optional[str] = None,
        offset_x: float = 0.0,
        offset_y: float = 0.0,
        depth: float = 0.0,
        offline: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(
            name=name,
            offset_x=offset_x,
            offset_y=offset_y,
            depth=depth,
            offline=offline,
        )
        self._port = port
        self._baud_rate = baud_rate
        self._command_timeout = command_timeout
        self._link: NanoTextLink | None = None
        self._active = {channel: 0 for channel in _CHANNELS}

    @property
    def channels(self) -> Mapping[str, Tuple[int, ...]]:
        return {channel: _LEVELS for channel in _CHANNELS}

    def connect(self) -> None:
        self._active = {channel: 0 for channel in _CHANNELS}
        if self._offline:
            return
        try:
            self._link = NanoTextLink(
                self._port, self._baud_rate, self._command_timeout
            )
            self._link.connect("LIGHT_MODULE")
            self._expect_ok(self._link.send("OFF"), "OFF")
        except (NanoTextConfigError, NanoTextConnectionError) as exc:
            self._release_link()
            raise LightingConnectionError(str(exc)) from exc
        except (NanoTextCommandError, NanoTextTimeoutError) as exc:
            self._release_link()
            raise LightingConnectionError(
                f"Light module did not initialize safely: {exc}"
            ) from exc

    def disconnect(self) -> None:
        if self._offline:
            self._active = {channel: 0 for channel in _CHANNELS}
            return
        if self._link is not None and self._link.is_open:
            try:
                self._expect_ok(self._link.send("OFF"), "OFF")
            except (NanoTextCommandError, NanoTextTimeoutError):
                self.logger.warning("Light-module OFF failed during disconnect")
        self._active = {channel: 0 for channel in _CHANNELS}
        self._release_link()

    def health_check(self) -> bool:
        return self._offline or (self._link is not None and self._link.is_open)

    def set_channel(self, channel: str, brightness_pct: int) -> None:
        self.validate_channel_level(channel, brightness_pct)
        proposed = dict(self._active)
        proposed[channel] = brightness_pct
        command = self._rgbw_command(proposed)
        if not self._offline:
            if self._link is None:
                raise LightingCommandError("Not connected to Nano light module")
            try:
                self._expect_ok(self._link.send(command), "RGBW")
            except NanoTextTimeoutError as exc:
                raise LightingTimeoutError(str(exc)) from exc
            except NanoTextCommandError as exc:
                raise LightingCommandError(str(exc)) from exc
        self._active = proposed

    def all_off(self) -> None:
        if not self._offline:
            if self._link is None:
                raise LightingCommandError("Not connected to Nano light module")
            try:
                self._expect_ok(self._link.send("OFF"), "OFF")
            except NanoTextTimeoutError as exc:
                raise LightingTimeoutError(str(exc)) from exc
            except NanoTextCommandError as exc:
                raise LightingCommandError(str(exc)) from exc
        self._active = {channel: 0 for channel in _CHANNELS}

    def status(self) -> LightingStatus:
        return LightingStatus(channels=dict(self._active))

    @staticmethod
    def _rgbw_command(levels: Mapping[str, int]) -> str:
        values = [round(levels[channel] * 255 / 100) for channel in _CHANNELS]
        return "RGBW " + " ".join(str(value) for value in values)

    @staticmethod
    def _expect_ok(response: str, command: str) -> None:
        if response != f"OK {command}":
            raise NanoTextCommandError(
                f"Unexpected response to {command}: {response!r}"
            )

    def _release_link(self) -> None:
        if self._link is not None:
            self._link.disconnect()
            self._link = None
