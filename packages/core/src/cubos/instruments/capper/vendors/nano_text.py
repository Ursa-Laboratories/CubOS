"""Cap sensor and electromagnet driven by dedicated CAP_MODULE Nano firmware."""

from __future__ import annotations

from typing import Optional

from cubos.instruments.capper.exceptions import (
    CapperCommandError,
    CapperConnectionError,
    CapperSensorFault,
    CapperTimeoutError,
)
from cubos.instruments.capper.interface import CapperInstrument
from cubos.instruments.capper.models import CapperStatus
from cubos.instruments.controllers.nano_text import (
    NanoTextCommandError,
    NanoTextConfigError,
    NanoTextConnectionError,
    NanoTextLink,
    NanoTextTimeoutError,
)


class NanoTextCapper(CapperInstrument):
    """Dedicated Nano capper using CAP?, MAGNET ON, and MAGNET OFF."""

    def __init__(
        self,
        *,
        engage_depth_mm: float,
        capture_retries: int = 2,
        capture_settle_s: float = 1.0,
        release_overtravel_mm: float = 0.0,
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
            engage_depth_mm=engage_depth_mm,
            capture_retries=capture_retries,
            capture_settle_s=capture_settle_s,
            release_overtravel_mm=release_overtravel_mm,
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
        self._cap_present = False

    def connect(self) -> None:
        if self._offline:
            return
        try:
            self._link = NanoTextLink(
                self._port, self._baud_rate, self._command_timeout
            )
            self._link.connect("CAP_MODULE")
            self._cap_present = self.read_cap_present()
        except (NanoTextConfigError, NanoTextConnectionError) as exc:
            self._release_link()
            raise CapperConnectionError(str(exc)) from exc
        except (CapperCommandError, CapperTimeoutError, CapperSensorFault) as exc:
            self._release_link()
            raise CapperConnectionError(
                f"Cap module did not answer its sensor probe: {exc}"
            ) from exc

    def disconnect(self) -> None:
        self._release_link()

    def health_check(self) -> bool:
        if self._offline:
            return True
        if self._link is None or not self._link.is_open:
            return False
        try:
            self.read_cap_present()
            return True
        except (CapperCommandError, CapperTimeoutError, CapperSensorFault):
            return False

    def capture_cap(self) -> None:
        if self._offline:
            self._cap_present = True
            return
        response = self._send("MAGNET ON")
        if response != "OK MAGNET ON":
            raise CapperCommandError(
                f"Unexpected response to MAGNET ON: {response!r}"
            )

    def release_cap(self) -> None:
        if self._offline:
            self._cap_present = False
            return
        response = self._send("MAGNET OFF")
        if response != "OK MAGNET OFF":
            raise CapperCommandError(
                f"Unexpected response to MAGNET OFF: {response!r}"
            )

    def read_cap_present(self) -> bool:
        if self._offline:
            return self._cap_present
        response = self._send("CAP?")
        if response == "CAP DETECTED":
            self._cap_present = True
        elif response == "CAP NOT_DETECTED":
            self._cap_present = False
        else:
            raise CapperSensorFault(
                f"Unexpected CAP? response: {response!r}"
            )
        return self._cap_present

    def get_status(self) -> CapperStatus:
        return CapperStatus(cap_present=self.read_cap_present())

    def _send(self, command: str) -> str:
        if self._link is None:
            raise CapperCommandError("Not connected to Nano cap module")
        try:
            return self._link.send(command)
        except NanoTextTimeoutError as exc:
            raise CapperTimeoutError(str(exc)) from exc
        except NanoTextCommandError as exc:
            raise CapperCommandError(str(exc)) from exc

    def _release_link(self) -> None:
        if self._link is not None:
            self._link.disconnect()
            self._link = None
