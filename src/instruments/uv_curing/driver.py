"""Driver for the Excelitas OmniCure S1500 PRO UV curing system.

Controls the OmniCure via RS-232 serial (19200 baud, 8N1).
Protocol: text commands with CRC8 suffix (currently XX placeholder).

Commands used:
    CONN    — handshake, expects READY response
    SIL{n}  — set iris intensity 1-100%
    STM{n}  — set exposure time in 0.1s units
    RUN     — execute timed shutter cycle (device manages shutter internally)

Reference: Excelitas OmniCure S1500 PRO/S2000 PRO/ELITE User's Guide

The gantry handles Z positioning to the well. This driver controls
only the UV light (intensity + timed exposure).
"""

import time
from typing import Optional

import serial

from instruments.base_instrument import BaseInstrument
from instruments.uv_curing.exceptions import (
    UVCuringCommandError,
    UVCuringConnectionError,
    UVCuringTimeoutError,
)
from instruments.uv_curing.models import CureResult, UVCuringStatus


class UVCuring(BaseInstrument):
    """Driver for the Excelitas OmniCure S1500 PRO.

    Pass ``offline=True`` for dry runs — no serial connection, cure()
    returns immediately with synthetic results.

    Board YAML fields:
        port: Serial port (default /dev/ttyACM0).
        baud_rate: Baud rate (default 19200).
        default_intensity: Default UV intensity % (default 100).
        default_exposure_time: Default exposure time in seconds (default 1.0).
    """

    def __init__(
        self,
        port: str = "/dev/ttyACM0",
        baud_rate: int = 19200,
        default_intensity: float = 100.0,
        default_exposure_time: float = 1.0,
        name: Optional[str] = None,
        offset_x: float = 0.0,
        offset_y: float = 0.0,
        depth: float = 0.0,
        offline: bool = False,
        **kwargs,
    ):
        super().__init__(
            name=name, offset_x=offset_x, offset_y=offset_y,
            depth=depth,
            offline=offline,
        )
        self._port = port
        self._baud_rate = baud_rate
        self._default_intensity = default_intensity
        self._default_exposure_time = default_exposure_time
        self._serial: Optional[serial.Serial] = None

    # ── BaseInstrument interface ──────────────────────────────────────────

    def connect(self) -> None:
        if self._offline:
            self.logger.info("UVCuring connected (offline)")
            return
        try:
            self._serial = serial.Serial(
                port=self._port,
                baudrate=self._baud_rate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=2,
                xonxoff=False,
                rtscts=False,
                dsrdtr=False,
            )
        except serial.SerialException as exc:
            raise UVCuringConnectionError(
                f"Cannot open OmniCure serial port {self._port}: {exc}"
            ) from exc

        self._handshake()
        self.logger.info("Connected to OmniCure on %s", self._port)

    def disconnect(self) -> None:
        if self._offline:
            self.logger.info("UVCuring disconnected (offline)")
            return
        if self._serial is not None:
            try:
                self._serial.close()
            except serial.SerialException:
                pass
            self._serial = None
        self.logger.info("OmniCure disconnected")

    def health_check(self) -> bool:
        if self._offline:
            return True
        return self._serial is not None and self._serial.is_open

    # ── UV-specific commands ──────────────────────────────────────────────

    def cure(
        self,
        intensity: Optional[float] = None,
        exposure_time: Optional[float] = None,
    ) -> CureResult:
        """Execute a timed UV cure cycle.

        Sets iris intensity, sets exposure time, sends RUN command.
        The OmniCure handles the shutter internally — RUN opens the
        shutter for the programmed duration then closes it.

        Args:
            intensity: Iris intensity 1-100% (uses default if None).
            exposure_time: Exposure duration in seconds (uses default if None).

        Returns:
            CureResult with the parameters used.
        """
        intensity = intensity if intensity is not None else self._default_intensity
        exposure_time = exposure_time if exposure_time is not None else self._default_exposure_time

        if not (1 <= intensity <= 100):
            raise UVCuringCommandError("Intensity must be between 1 and 100%")
        if exposure_time <= 0:
            raise UVCuringCommandError("Exposure time must be > 0 seconds")

        if self._offline:
            self.logger.info(
                "Cure (offline): %.0f%% for %.2fs", intensity, exposure_time,
            )
            return CureResult(
                intensity_percent=intensity,
                exposure_time_s=exposure_time,
                timestamp=time.time(),
            )

        self._send_command(f"SIL{int(intensity)}")
        self._send_command(f"STM{int(exposure_time * 10)}")
        self._send_command("RUN")
        time.sleep(exposure_time + 0.05)

        self.logger.info("Cured: %d%% for %.2fs", intensity, exposure_time)

        return CureResult(
            intensity_percent=intensity,
            exposure_time_s=exposure_time,
            timestamp=time.time(),
        )

    def measure(self, **kwargs) -> CureResult:
        """Protocol-compatible alias for cure(). Called by the scan command."""
        return self.cure(**kwargs)

    def get_status(self) -> UVCuringStatus:
        return UVCuringStatus(is_connected=self.health_check())

    # ── Private helpers ───────────────────────────────────────────────────

    def _handshake(self) -> None:
        """Send CONN until the OmniCure responds with READY."""
        for _ in range(10):
            response = self._send_command("CONN")
            if response.startswith("READY"):
                return
            time.sleep(0.5)
        raise UVCuringConnectionError(
            "OmniCure did not respond READY after CONN"
        )

    def _send_command(self, command: str) -> str:
        """Send a command with CRC8 suffix and return the response."""
        if self._serial is None or not self._serial.is_open:
            raise UVCuringCommandError("Not connected to OmniCure")
        full_cmd = f"{command}XX\r"
        try:
            self._serial.write(full_cmd.encode())
            response = self._serial.readline().decode(errors="ignore").strip()
        except serial.SerialException as exc:
            raise UVCuringCommandError(
                f"Serial error sending '{command}': {exc}"
            ) from exc
        if not response:
            raise UVCuringTimeoutError(
                f"No response to '{command}'"
            )
        self.logger.debug(">> %s  << %s", command, response)
        return response
