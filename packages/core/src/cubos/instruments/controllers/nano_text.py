"""Serial transport for independent Arduino Nano text-command modules."""

from __future__ import annotations

import time
from typing import Optional

import serial


class NanoTextError(Exception):
    """Base error for Nano text-module communication."""


class NanoTextConfigError(NanoTextError):
    """The serial configuration is incomplete or invalid."""


class NanoTextConnectionError(NanoTextError):
    """The serial port could not be opened or identified."""


class NanoTextCommandError(NanoTextError):
    """The module rejected a command or the serial link failed."""


class NanoTextTimeoutError(NanoTextError):
    """The module did not answer before the timeout."""


class NanoTextLink:
    """One newline-delimited serial link to a dedicated Nano module."""

    def __init__(
        self,
        port: str,
        baud_rate: int = 115200,
        command_timeout: float = 3.0,
    ) -> None:
        if not port:
            raise NanoTextConfigError("Nano module requires a non-empty serial port.")
        self._port = port
        self._baud_rate = baud_rate
        self._command_timeout = command_timeout
        self._serial: Optional[serial.Serial] = None

    @property
    def is_open(self) -> bool:
        return self._serial is not None and self._serial.is_open

    def connect(self, expected_id: str) -> None:
        try:
            self._serial = serial.Serial(
                port=self._port,
                baudrate=self._baud_rate,
                timeout=min(self._command_timeout, 0.5),
            )
        except serial.SerialException as exc:
            self._serial = None
            raise NanoTextConnectionError(
                f"Cannot open serial port {self._port}: {exc}"
            ) from exc

        try:
            # Opening a Nano normally toggles DTR and reboots it. Wait for
            # setup(), then discard the boot banner before the ID round-trip.
            time.sleep(2.0)
            self._serial.reset_input_buffer()
            identity = self.send("ID?")
            if identity != expected_id:
                raise NanoTextConnectionError(
                    f"Expected {expected_id} on {self._port}, got {identity!r}."
                )
        except NanoTextError:
            self.disconnect()
            raise

    def disconnect(self) -> None:
        if self._serial is None:
            return
        try:
            self._serial.close()
        except serial.SerialException:
            pass
        self._serial = None

    def send(self, command: str) -> str:
        if not self.is_open:
            raise NanoTextCommandError(
                f"Nano module on {self._port} is not connected."
            )
        assert self._serial is not None
        try:
            self._serial.write(f"{command}\n".encode())
            self._serial.flush()
        except serial.SerialException as exc:
            raise NanoTextCommandError(
                f"Failed to send {command!r}: {exc}"
            ) from exc

        deadline = time.monotonic() + self._command_timeout
        while time.monotonic() < deadline:
            try:
                line = self._serial.readline().decode(errors="replace").strip()
            except serial.SerialException as exc:
                raise NanoTextCommandError(
                    f"Serial read failed for {command!r}: {exc}"
                ) from exc
            if not line or line.endswith("_READY"):
                continue
            if line.startswith("ERROR"):
                raise NanoTextCommandError(
                    f"Command {command!r} failed: {line}"
                )
            return line
        raise NanoTextTimeoutError(
            f"Timed out ({self._command_timeout}s) waiting for {command!r}."
        )
