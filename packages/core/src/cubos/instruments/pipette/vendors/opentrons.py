import math
import threading
import time
from typing import Optional

import serial

from cubos.instruments.pipette.interface import PipetteInstrument
from cubos.instruments.pipette.exceptions import (
    PipetteCommandError,
    PipetteConfigError,
    PipetteConnectionError,
    PipetteTimeoutError,
)
from cubos.instruments.pipette.liquid_class import build_liquid_classes
from cubos.instruments.pipette.models import (
    AspirateResult,
    MixResult,
    PipetteConfig,
    PipetteStatus,
    PIPETTE_MODELS,
)

_CMD_HOME = 10
_CMD_MOVE_TO = 11
_CMD_ASPIRATE = 12
_CMD_DISPENSE = 13
_CMD_STATUS = 14
_CMD_MIX = 15
_CMD_DRIP_STOP = 28

_ARDUINO_SETTLE_TIME = 2.0

# Homing runs open-loop until a limit switch; firmware allows up to 60 s
# before it gives up, so the serial wait must outlast that.
_HOME_TIMEOUT = 90.0


class OpentronsPipette(PipetteInstrument):
    """Driver for Opentrons pipettes via Arduino serial (Pawduino firmware).

    Pass ``offline=True`` for dry runs — simulates plunger state in memory.
    """

    CONFIG_FIELD_CHOICES = {
        "pipette_model": sorted(PIPETTE_MODELS.keys()),
    }

    def __init__(
        self,
        pipette_model: str = "p300_single_gen2",
        port: str = "",
        baud_rate: int = 115200,
        command_timeout: float = 30.0,
        name: Optional[str] = None,
        offset_x: float = 0.0,
        offset_y: float = 0.0,
        depth: float = 0.0,
        offline: bool = False,
        liquid_classes: Optional[dict] = None,
        **kwargs,
    ):
        super().__init__(
            name=name, offset_x=offset_x, offset_y=offset_y,
            depth=depth,
            offline=offline,
        )
        if pipette_model not in PIPETTE_MODELS:
            raise PipetteConfigError(
                f"Unknown pipette model '{pipette_model}'. "
                f"Available: {', '.join(sorted(PIPETTE_MODELS.keys()))}"
            )
        self._config: PipetteConfig = PIPETTE_MODELS[pipette_model]
        # Per-liquid-class stroke-volume correction (multiplier + offset_ul),
        # keyed by an operator-chosen name; empty/disabled unless configured.
        # See cubos.instruments.pipette.liquid_class for the parametric form.
        self._liquid_classes = build_liquid_classes(liquid_classes)
        self._port = port
        self._baud_rate = baud_rate
        self._command_timeout = command_timeout
        self._serial: Optional[serial.Serial] = None
        self._lock = threading.Lock()
        self._has_tip = False
        self._attached_tip_extension = 0.0
        self._position_mm = 0.0
        self._is_homed = False
        self._is_primed = False

    @property
    def config(self) -> PipetteConfig:
        return self._config

    @property
    def attached_tip_extension(self) -> float:
        return self._attached_tip_extension

    @property
    def effective_depth(self) -> float:
        return self.depth + self._attached_tip_extension

    def set_attached_tip_extension(self, extension_mm: float) -> None:
        if (
            isinstance(extension_mm, bool)
            or not isinstance(extension_mm, (int, float))
            or not math.isfinite(float(extension_mm))
            or float(extension_mm) < 0.0
        ):
            raise PipetteConfigError(
                f"attached tip extension must be a non-negative finite number, "
                f"got {extension_mm!r}."
            )
        self._attached_tip_extension = float(extension_mm)

    def clear_attached_tip_extension(self) -> None:
        self._attached_tip_extension = 0.0

    # ── BaseInstrument interface ──────────────────────────────────────────

    def connect(self) -> None:
        if self._offline:
            self.logger.info("Pipette connected (offline)")
            return
        try:
            self._serial = serial.Serial(
                port=self._port,
                baudrate=self._baud_rate,
                timeout=self._command_timeout,
            )
        except serial.SerialException as exc:
            raise PipetteConnectionError(
                f"Cannot open serial port {self._port}: {exc}"
            ) from exc

        time.sleep(_ARDUINO_SETTLE_TIME)
        # Opening the port resets the Arduino; discard any boot banner so it
        # is not mistaken for the first command's response.
        self._serial.reset_input_buffer()

        try:
            status = self.get_status()
        except (PipetteCommandError, PipetteTimeoutError) as exc:
            self._close_serial()
            raise PipetteConnectionError(
                f"Arduino did not respond after connect: {exc}"
            ) from exc

        # The reset also wipes the firmware's plunger reference: it believes
        # position 0.0 wherever the plunger physically sits, and no motion
        # command guards against that. Re-establish a real reference now.
        if not status.is_homed:
            self.logger.info("Plunger not homed after connect; homing and priming")
            try:
                self.home()
                self.prime()
            except (PipetteCommandError, PipetteTimeoutError) as exc:
                self._close_serial()
                raise PipetteConnectionError(
                    f"Plunger home/prime after connect failed: {exc}"
                ) from exc

        self.logger.info(
            "Connected to %s on %s", self._config.name, self._port
        )

    def disconnect(self) -> None:
        if self._offline:
            self.logger.info("Pipette disconnected (offline)")
            return
        self._close_serial()
        self.logger.info("Disconnected from pipette")

    def health_check(self) -> bool:
        if self._offline:
            return True
        if self._serial is None or not self._serial.is_open:
            return False
        try:
            self.get_status()
            return True
        except (PipetteCommandError, PipetteTimeoutError):
            return False

    def warm_up(self) -> None:
        self.home()
        self.prime()

    # ── Pipette-specific commands ─────────────────────────────────────────

    def home(self) -> None:
        if self._offline:
            self._position_mm = self._config.zero_position
            self._is_homed = True
            return
        self._send_command(_CMD_HOME, timeout=_HOME_TIMEOUT)
        self._position_mm = self._config.zero_position
        self._is_homed = True

    def prime(self, speed: float = 50.0) -> None:
        if self._offline:
            self._position_mm = self._config.prime_position
            self._is_primed = True
            return
        self._send_command(_CMD_MOVE_TO, self._config.prime_position, speed)
        self._position_mm = self._config.prime_position
        self._is_primed = True

    def aspirate(self, volume_ul: float, speed: float = 50.0) -> AspirateResult:
        self._validate_volume(volume_ul)
        mm_travel = volume_ul * self._config.mm_to_ul
        if self._offline:
            self._position_mm += mm_travel
            return AspirateResult(
                success=True, volume_ul=volume_ul, position_mm=self._position_mm
            )
        response = self._send_command(_CMD_ASPIRATE, mm_travel, speed)
        position = self._parse_position(response)
        return AspirateResult(
            success=True, volume_ul=volume_ul, position_mm=position
        )

    def dispense(self, volume_ul: float, speed: float = 50.0) -> AspirateResult:
        self._validate_volume(volume_ul)
        mm_travel = volume_ul * self._config.mm_to_ul
        if self._offline:
            self._position_mm -= mm_travel
            return AspirateResult(
                success=True, volume_ul=volume_ul, position_mm=self._position_mm
            )
        response = self._send_command(_CMD_DISPENSE, mm_travel, speed)
        position = self._parse_position(response)
        return AspirateResult(
            success=True, volume_ul=volume_ul, position_mm=position
        )

    def blowout(self, speed: float = 50.0) -> None:
        if self._offline:
            self._position_mm = self._config.blowout_position
            return
        self._send_command(_CMD_MOVE_TO, self._config.blowout_position, speed)

    def mix(
        self, volume_ul: float, repetitions: int = 3, speed: float = 50.0
    ) -> MixResult:
        self._validate_volume(volume_ul)
        if not self._offline:
            mm_travel = volume_ul * self._config.mm_to_ul
            self._send_command(_CMD_MIX, mm_travel, repetitions, speed)
        return MixResult(
            success=True, volume_ul=volume_ul, repetitions=repetitions
        )

    def pick_up_tip(self, speed: float = 50.0) -> None:
        if not self._offline:
            self._send_command(_CMD_MOVE_TO, self._config.zero_position, speed)
        self._has_tip = True

    def drop_tip(self, speed: float = 50.0) -> None:
        if not self._offline:
            self._send_command(_CMD_MOVE_TO, self._config.drop_tip_position, speed)
        self._has_tip = False
        self.clear_attached_tip_extension()
        self._position_mm = self._config.drop_tip_position

    def get_status(self) -> PipetteStatus:
        if self._offline:
            return PipetteStatus(
                is_homed=self._is_homed,
                position_mm=self._position_mm,
                max_volume=self._config.max_volume,
                has_tip=self._has_tip,
                is_primed=self._is_primed,
            )
        response = self._send_command(_CMD_STATUS)
        parsed = self._parse_key_value(response)
        return PipetteStatus(
            is_homed=parsed.get("homed", 0) == 1,
            position_mm=float(parsed.get("pos", 0.0)),
            max_volume=float(parsed.get("max_vol", self._config.max_volume)),
            has_tip=self._has_tip,
            is_primed=parsed.get("primed", 0) == 1,
        )

    def drip_stop(self, volume_ul: float = 5.0, speed: float = 50.0) -> None:
        self._validate_positive_bounded_volume(volume_ul)
        if self._offline:
            return
        mm_travel = volume_ul * self._config.mm_to_ul
        self._send_command(_CMD_DRIP_STOP, mm_travel, speed)

    # ── Private helpers ───────────────────────────────────────────────────

    def _send_command(
        self, code: int, *args: float, timeout: Optional[float] = None
    ) -> str:
        if self._serial is None or not self._serial.is_open:
            raise PipetteCommandError("Not connected to Arduino")
        wait = self._command_timeout if timeout is None else timeout

        parts = [str(code)] + [str(a) for a in args]
        message = ",".join(parts) + "\n"

        with self._lock:
            try:
                self._serial.write(message.encode())
                self._serial.flush()
            except serial.SerialException as exc:
                raise PipetteCommandError(
                    f"Failed to send command {code}: {exc}"
                ) from exc

            deadline = time.monotonic() + wait
            while time.monotonic() < deadline:
                try:
                    line = self._serial.readline().decode().strip()
                except serial.SerialException as exc:
                    raise PipetteCommandError(
                        f"Serial read error for command {code}: {exc}"
                    ) from exc

                if not line:
                    continue
                if line.startswith("OK:"):
                    return line
                if line.startswith("ERR:"):
                    raise PipetteCommandError(
                        f"Command {code} failed: {line}"
                    )

            raise PipetteTimeoutError(
                f"Timed out ({wait}s) waiting for response to command {code}"
            )

    @staticmethod
    def _parse_key_value(response: str) -> dict[str, float]:
        """Parse ``OK:{...}`` bodies with quoted or bare keys.

        The Pawduino firmware emits JSON-quoted keys
        (``OK:{"homed":1,"pos":0.00,"max_vol":300.00}``); bare keys are
        tolerated for older firmware and tests.
        """
        result: dict[str, float] = {}
        body = response.removeprefix("OK:").strip()
        if body.startswith("{") and body.endswith("}"):
            body = body[1:-1]
        for pair in body.split(","):
            if ":" not in pair:
                continue
            key, _, val = pair.partition(":")
            try:
                result[key.strip().strip('"')] = float(val.strip().strip('"'))
            except ValueError:
                continue
        return result

    @staticmethod
    def _parse_position(response: str) -> float:
        parsed = OpentronsPipette._parse_key_value(response)
        return float(parsed.get("pos", 0.0))

    def _close_serial(self) -> None:
        if self._serial is not None:
            try:
                self._serial.close()
            except serial.SerialException:
                pass
            self._serial = None

    def _validate_volume(self, volume_ul: float) -> None:
        if (
            isinstance(volume_ul, bool)
            or not isinstance(volume_ul, (int, float))
            or not math.isfinite(float(volume_ul))
            or not (self._config.min_volume <= float(volume_ul) <= self._config.max_volume)
        ):
            raise PipetteCommandError(
                f"Volume {volume_ul!r} uL is outside {self._config.name} range "
                f"{self._config.min_volume}-{self._config.max_volume} uL"
            )

    def _validate_positive_bounded_volume(self, volume_ul: float) -> None:
        if (
            isinstance(volume_ul, bool)
            or not isinstance(volume_ul, (int, float))
            or not math.isfinite(float(volume_ul))
            or not (0.0 < float(volume_ul) <= self._config.max_volume)
        ):
            raise PipetteCommandError(
                f"Volume {volume_ul!r} uL is outside {self._config.name} range "
                f"0-{self._config.max_volume} uL"
            )
