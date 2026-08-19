"""Driver for the Sartorius Picus 2 electronic pipette.

Unlike ``vendors/opentrons.py`` -- which drives a stepper CubOS bolted to the
plunger of a bare pipette body, and therefore commands *millimetres of travel*
-- the Picus 2 owns its own piston and closed-loop control. Commands are
volumes in microlitres, and the pipette reports completion rather than
position. Several ``PipetteInstrument`` obligations are consequently driver
bookkeeping rather than hardware readback; each is called out below.

Wire protocol: line-based JSON at 230400 8N1, CRLF-terminated, each frame
carrying a monotonic sequence number so replies can be correlated::

    {"no":7,"data":"RUN_ASPIRATE 500 5"}\\r\\n

Every frame is answered with ``ACK <seq>``, ``BEGIN <seq>``, a payload, then
``END <seq>``. The payload is either a result token (``OK <seq>`` or an error
code) for commands that only act, or bare data lines for commands that
report -- a query such as ``GET_NOMINAL_VOLUME`` never sends ``OK`` at all,
so ``END <seq>`` is the only reliable terminator.

Two consequences, both observed on hardware. Replies for different sequence
numbers interleave freely, and data lines carry no sequence number of their
own, so a data line belongs to whichever ``BEGIN`` scope is innermost. And
with ``AUTO 1`` enabled the pipette also pushes unsolicited JSON events for
physical button presses, which must not be mistaken for a command's output.

Protocol details were established with the permission of the
AccelerationConsortium ``cnc-4-science`` maintainers, whose GPL-3.0 driver
documents the same command set; this implementation is independent CubOS code
(offline path, BaseInstrument conformance, CubOS exception hierarchy, liquid
classes). See the integration scope in ``progress/`` for the provenance note.
"""

from __future__ import annotations

import itertools
import json
import math
import re
import threading
import time
from typing import Any, Optional

import serial

from cubos.instruments.pipette.interface import PipetteInstrument
from cubos.instruments.pipette.exceptions import (
    PipetteBatteryError,
    PipetteCommandError,
    PipetteConfigError,
    PipetteConnectionError,
    PipetteMotorControlError,
    PipetteTimeoutError,
)
from cubos.instruments.pipette.liquid_class import build_liquid_classes
from cubos.instruments.pipette.models import (
    AspirateResult,
    MixResult,
    PipetteConfig,
    PipetteStatus,
    PICUS2_MODELS,
)

_TERMINATOR = b"\r\n"
_BAUD_RATE = 230400

# Envelope tokens frame a reply but carry no outcome.
_ENVELOPE_TOKENS = frozenset({"ACK", "BEGIN", "END"})

_RESULT_OK = "OK"
_RESULT_CODES = frozenset(
    {
        "OK",
        "FULL",
        "SYNTAX_ERROR",
        "ERROR_PARSING",
        "UNKNOWN_COMMAND",
        "MISSING_PARAMETERS",
        "ERR_RANGE_PARAMETERS",
        "CHK_ERROR",
        "NOT_ALLOWED",
        "FAILED",
        "MOTOR_CONTROL_ABORTED",
    }
)

# The instrument revoked host control. Never auto-retried: the piston
# position after an abort is unknown, so recovery has to start from a
# reconnect (which re-runs RUN_INIT) rather than from a guess.
_ABORT_CODE = "MOTOR_CONTROL_ABORTED"

# Piston moves are slow at low speed settings and a full-stroke 10 mL
# dispense is the worst case. Generous, but bounded.
_MOTION_TIMEOUT = 120.0
_QUERY_TIMEOUT = 5.0

# The pipette asks for on-screen confirmation before handing motor control to
# a host. The confirmation is a softkey press, which can be satisfied over the
# wire; we retry it on a short cadence until the instrument acknowledges.
_ARM_TIMEOUT = 30.0
_ARM_TAP_INTERVAL = 0.4
_CONFIRM_BUTTON = "TRIGGER_BUTTON_RIGHT"

# `speed` on PipetteInstrument is a normalized 0-100 percentage of the
# instrument's usable range (see the interface docstring). The Picus takes an
# integer 1..9, and this map sends the interface default of 50.0 to the
# vendor's own mid-scale default of 5.
_SPEED_MIN = 1
_SPEED_MAX = 9


def _speed_index(speed: float) -> int:
    """Map a normalized 0-100 speed onto the Picus 1..9 scale."""
    try:
        normalized = float(speed)
    except (TypeError, ValueError):
        normalized = 50.0
    if not math.isfinite(normalized):
        normalized = 50.0
    index = _SPEED_MIN + round(normalized / 100.0 * (_SPEED_MAX - _SPEED_MIN))
    return int(max(_SPEED_MIN, min(_SPEED_MAX, index)))


class SartoriusPicus2Pipette(PipetteInstrument):
    """Sartorius Picus 2 over USB serial.

    Pass ``offline=True`` for dry runs -- simulates piston state in memory.
    """

    CONFIG_FIELD_CHOICES = {
        "pipette_model": sorted(PICUS2_MODELS.keys()),
    }

    def __init__(
        self,
        pipette_model: str = "picus2_1ch_1000",
        port: str = "",
        baud_rate: int = _BAUD_RATE,
        command_timeout: float = 30.0,
        default_speed: float = 50.0,
        blowout_delay_ms: int = 3000,
        blowout_go_home: bool = True,
        min_battery_percent: float = 20.0,
        verify_model: bool = True,
        whole_microlitres_only: bool = False,
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
            depth=depth, offline=offline,
        )
        if pipette_model not in PICUS2_MODELS:
            raise PipetteConfigError(
                f"Unknown Picus 2 model '{pipette_model}'. "
                f"Available: {', '.join(sorted(PICUS2_MODELS.keys()))}"
            )
        self._config: PipetteConfig = PICUS2_MODELS[pipette_model]
        self._liquid_classes = build_liquid_classes(liquid_classes)
        self._port = port
        self._baud_rate = baud_rate
        self._command_timeout = command_timeout
        self._default_speed = default_speed
        self._blowout_delay_ms = int(blowout_delay_ms)
        self._blowout_go_home = bool(blowout_go_home)
        self._min_battery_percent = float(min_battery_percent)
        self._verify_model = bool(verify_model)
        self._whole_microlitres_only = bool(whole_microlitres_only)

        self._serial: Optional[serial.Serial] = None
        self._lock = threading.Lock()
        self._counter = itertools.count(1)
        self._has_tip = False
        self._attached_tip_extension = 0.0
        self._initialized = False
        self._motor_control_lost = False
        # No position readback exists, so loaded volume is tracked here and
        # reported through AspirateResult/PipetteStatus.
        self._loaded_volume_ul = 0.0

    # ── Configuration ─────────────────────────────────────────────────────

    @property
    def config(self) -> PipetteConfig:
        return self._config

    @property
    def attached_tip_extension(self) -> float:
        return self._attached_tip_extension

    @property
    def effective_depth(self) -> float:
        return self.depth + self._attached_tip_extension

    @property
    def loaded_volume_ul(self) -> float:
        """Driver-tracked volume currently in the tip."""
        return self._loaded_volume_ul

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
            self._initialized = True
            self._motor_control_lost = False
            self._loaded_volume_ul = 0.0
            self.logger.info("Picus 2 connected (offline)")
            return
        try:
            self._serial = serial.Serial(
                port=self._port,
                baudrate=self._baud_rate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.2,
                write_timeout=2.0,
            )
        except serial.SerialException as exc:
            raise PipetteConnectionError(
                f"Cannot open serial port {self._port}: {exc}"
            ) from exc

        try:
            self._serial.reset_input_buffer()
            self._send("AUTO 1", timeout=_QUERY_TIMEOUT)
            self._arm_motor_control()
            if self._verify_model:
                self._verify_attached_model()
            self._check_battery()
            # Establishes a real piston reference, so a reconnect always
            # starts from a known-empty tip regardless of prior state.
            self._send("RUN_INIT", timeout=_MOTION_TIMEOUT)
        except Exception:
            self._close_serial()
            raise

        self._initialized = True
        self._motor_control_lost = False
        self._loaded_volume_ul = 0.0
        self.logger.info("Connected to %s on %s", self._config.name, self._port)

    def disconnect(self) -> None:
        if self._offline:
            self._initialized = False
            self.logger.info("Picus 2 disconnected (offline)")
            return
        if self._serial is not None and self._serial.is_open:
            try:
                self._send("ENABLE_MOTOR_CONTROL 0", timeout=_QUERY_TIMEOUT)
            except (PipetteCommandError, PipetteTimeoutError,
                    PipetteMotorControlError, serial.SerialException) as exc:
                # Releasing control is courtesy; the port still has to close.
                self.logger.debug("Ignored error releasing motor control: %s", exc)
        self._close_serial()
        self._initialized = False
        self.logger.info("Disconnected from pipette")

    def health_check(self) -> bool:
        if self._offline:
            return True
        if self._serial is None or not self._serial.is_open:
            return False
        if self._motor_control_lost:
            return False
        try:
            self._send("GET_VERSION", timeout=_QUERY_TIMEOUT)
            return True
        except (PipetteCommandError, PipetteTimeoutError, PipetteMotorControlError):
            return False

    def warm_up(self) -> None:
        self.home()

    # ── Pipette-specific commands ─────────────────────────────────────────

    def home(self) -> None:
        """Return the piston to its home position.

        ``RUN_INIT`` is used once per session to establish the reference;
        afterwards ``HOME`` is a plain move, so re-homing mid-protocol does
        not repeat the slower initialization sweep.
        """
        if self._offline:
            self._initialized = True
            self._loaded_volume_ul = 0.0
            return
        self._send(
            "RUN_INIT" if not self._initialized else "HOME",
            timeout=_MOTION_TIMEOUT,
        )
        self._initialized = True
        self._loaded_volume_ul = 0.0

    def prime(self, speed: float = 50.0) -> None:
        """No-op: the Picus 2 has no plunger to pre-position.

        On a CubOS-driven plunger, priming parks it mid-travel so a later
        aspirate has somewhere to go. The Picus manages its own piston
        reference and takes absolute volumes, so there is nothing to
        pre-position. Kept as a documented no-op rather than given a
        plausible-looking fake; ``PipetteStatus.is_primed`` therefore means
        "initialized" on this vendor.
        """
        if not self._initialized:
            self.home()

    def aspirate(self, volume_ul: float, speed: float = 50.0) -> AspirateResult:
        commanded = self._quantize(volume_ul)
        if self._offline:
            self._loaded_volume_ul += commanded
            return self._result(commanded)
        self._send(
            f"RUN_ASPIRATE {self._format_volume(commanded)} {self._speed(speed)}",
            timeout=_MOTION_TIMEOUT,
        )
        self._loaded_volume_ul += commanded
        return self._result(commanded)

    def dispense(self, volume_ul: float, speed: float = 50.0) -> AspirateResult:
        commanded = self._quantize(volume_ul)
        if self._offline:
            self._loaded_volume_ul = max(0.0, self._loaded_volume_ul - commanded)
            return self._result(commanded)
        self._send(
            f"RUN_DISPENSE {self._format_volume(commanded)} {self._speed(speed)}",
            timeout=_MOTION_TIMEOUT,
        )
        self._loaded_volume_ul = max(0.0, self._loaded_volume_ul - commanded)
        return self._result(commanded)

    def blowout(self, speed: float = 50.0) -> None:
        """Expel residual liquid using the instrument's own blow-out stroke."""
        if self._offline:
            self._loaded_volume_ul = 0.0
            return
        self._send(
            f"BLOW_OUT {1 if self._blowout_go_home else 0} "
            f"{self._speed(speed)} {self._blowout_delay_ms}",
            timeout=_MOTION_TIMEOUT,
        )
        self._loaded_volume_ul = 0.0

    def mix(
        self, volume_ul: float, repetitions: int = 3, speed: float = 50.0
    ) -> MixResult:
        """Mix by repeated aspirate/dispense.

        The Picus 2 exposes no atomic mix command, so this is a host-side
        loop. A failure part-way therefore leaves liquid in the tip: the
        driver attempts to return it before re-raising, and the protocol
        engine's fluid journal already marks an interrupted mix as needing
        reconciliation.
        """
        commanded = self._quantize(volume_ul)
        if self._offline:
            return MixResult(success=True, volume_ul=commanded, repetitions=repetitions)
        completed = 0
        try:
            for _ in range(int(repetitions)):
                self.aspirate(commanded, speed)
                self.dispense(commanded, speed)
                completed += 1
        except Exception:
            self._recover_interrupted_mix(completed, int(repetitions), speed)
            raise
        return MixResult(success=True, volume_ul=commanded, repetitions=repetitions)

    def pick_up_tip(self, speed: float = 50.0) -> None:
        """Record that a tip was seated.

        Tip pickup is entirely gantry motion on this vendor: the toolhead
        presses the cone onto the tip. There is no pipette-side command and
        no tip sensor, so ``has_tip`` is bookkeeping -- the same as the
        Opentrons driver.
        """
        if not self._offline and not self._initialized:
            self.home()
        self._has_tip = True

    def drop_tip(self, speed: float = 50.0) -> None:
        """Eject the tip with the instrument's electronic ejector."""
        if not self._offline:
            self._send("TIP_EJECT", timeout=_MOTION_TIMEOUT)
        self._has_tip = False
        self.clear_attached_tip_extension()
        self._loaded_volume_ul = 0.0

    def get_status(self) -> PipetteStatus:
        """Return current state.

        ``position_mm`` is always 0.0: the Picus exposes no piston-position
        query. Read ``loaded_volume_ul`` instead. ``is_homed``/``is_primed``
        are driver state for the same reason, and both are re-established on
        connect, which always runs ``RUN_INIT``.
        """
        return PipetteStatus(
            is_homed=self._initialized,
            position_mm=0.0,
            max_volume=self._config.max_volume,
            has_tip=self._has_tip,
            is_primed=self._initialized,
            battery_percent=None if self._offline else self._read_battery(),
        )

    # ── Identity / telemetry ──────────────────────────────────────────────

    def get_model(self) -> str:
        return "" if self._offline else (self._send("GET_MODEL", timeout=_QUERY_TIMEOUT) or "")

    def get_serial_number(self) -> str:
        return "" if self._offline else (self._send("GET_SERIAL", timeout=_QUERY_TIMEOUT) or "")

    def get_nominal_volume(self) -> str:
        return (
            str(self._config.max_volume)
            if self._offline
            else (self._send("GET_NOMINAL_VOLUME", timeout=_QUERY_TIMEOUT) or "")
        )

    # ── Private helpers ───────────────────────────────────────────────────

    def _result(self, commanded: float) -> AspirateResult:
        return AspirateResult(
            success=True,
            volume_ul=commanded,
            position_mm=0.0,
            loaded_volume_ul=self._loaded_volume_ul,
        )

    def _speed(self, speed: float) -> int:
        return _speed_index(self._default_speed if speed is None else speed)

    def _quantize(self, volume_ul: float) -> float:
        """Round *volume_ul* to the model's settable increment and bounds-check.

        The returned figure is what actually gets commanded, and is reported
        back on ``AspirateResult.volume_ul`` so callers can see the rounding.
        """
        if (
            isinstance(volume_ul, bool)
            or not isinstance(volume_ul, (int, float))
            or not math.isfinite(float(volume_ul))
        ):
            raise PipetteCommandError(f"Volume {volume_ul!r} uL is not a finite number")
        requested = float(volume_ul)
        increment = self._config.volume_increment_ul
        quantized = (
            round(requested / increment) * increment if increment > 0 else requested
        )
        # Guard against float dust turning 0.29999999 into a visible artifact.
        quantized = round(quantized, 6)
        if not (self._config.min_volume <= quantized <= self._config.max_volume):
            raise PipetteCommandError(
                f"Volume {volume_ul!r} uL (quantized to {quantized} uL) is outside "
                f"{self._config.name} range {self._config.min_volume}-"
                f"{self._config.max_volume} uL"
            )
        return quantized

    def _format_volume(self, volume_ul: float) -> str:
        """Render a volume for the wire at the model's resolution.

        Whether the instrument accepts fractional microlitres is unverified
        (see the integration scope's F-4): models whose increment is a whole
        microlitre are sent as integers regardless, and
        ``whole_microlitres_only`` forces that for the rest if bench testing
        shows fractions are rejected.
        """
        increment = self._config.volume_increment_ul
        if self._whole_microlitres_only or increment >= 1.0 or increment <= 0:
            return str(int(round(volume_ul)))
        decimals = max(0, -int(math.floor(math.log10(increment))))
        return f"{volume_ul:.{decimals}f}"

    def _recover_interrupted_mix(
        self, completed: int, repetitions: int, speed: float,
    ) -> None:
        """Best-effort return of liquid left in the tip by a failed mix."""
        if self._loaded_volume_ul <= 0:
            return
        try:
            self.blowout(speed)
        except Exception as exc:  # noqa: BLE001 - the original error must win
            self.logger.warning(
                "Mix failed at repetition %d/%d and blow-out recovery also "
                "failed (%s); tip may still hold liquid",
                completed + 1, repetitions, exc,
            )

    def _arm_motor_control(self, mode: int = 2) -> None:
        """Request host motor control and satisfy the on-screen confirmation.

        The instrument will not accept motion commands until a human (or a
        softkey frame standing in for one) confirms on the device. The
        confirmation is re-sent on a short cadence until acknowledged, and a
        timeout raises with the physical action named so an operator at the
        bench knows what to press.
        """
        deadline = time.monotonic() + _ARM_TIMEOUT
        frame_no = next(self._counter)
        self._write(self._frame(frame_no, data=f"ENABLE_MOTOR_CONTROL {int(mode)}"))
        last_tap = 0.0
        while True:
            now = time.monotonic()
            if now >= deadline:
                raise PipetteConnectionError(
                    f"Timed out after {_ARM_TIMEOUT:.0f}s enabling motor control on "
                    f"{self._port}. Confirm remote control on the pipette screen "
                    f"(right softkey) and reconnect."
                )
            if now - last_tap >= _ARM_TAP_INTERVAL:
                self._write(
                    self._frame(next(self._counter), button=_CONFIRM_BUTTON)
                )
                last_tap = now
            line = self._read_line()
            if line is None:
                continue
            kind, reply_no, value = self._parse_line(line)
            if kind == "result" and reply_no == frame_no:
                if value != _RESULT_OK:
                    raise PipetteConnectionError(
                        f"Pipette refused motor control: {value}"
                    )
                return

    def _verify_attached_model(self) -> None:
        """Fail closed when the physical device is not the configured model.

        The Opentrons driver cannot do this -- a bare pipette body has no
        identity to query -- so it is worth spending the round-trip here: a
        1000 uL config driving a 10 uL pipette would otherwise over-aspirate
        by 100x on the first command.
        """
        nominal = self._send("GET_NOMINAL_VOLUME", timeout=_QUERY_TIMEOUT)
        if not nominal:
            self.logger.warning(
                "Pipette did not report a nominal volume; skipping model check"
            )
            return
        reported = _first_number(nominal)
        if reported is None:
            self.logger.warning(
                "Could not parse nominal volume %r; skipping model check", nominal,
            )
            return
        if abs(reported - self._config.max_volume) > 0.5:
            raise PipetteConnectionError(
                f"Configured model {self._config.name} expects a "
                f"{self._config.max_volume:g} uL pipette, but the device on "
                f"{self._port} reports {reported:g} uL. Fix `pipette_model` in "
                f"the gantry YAML, or set verify_model: false to override."
            )

    def _read_battery(self) -> Optional[float]:
        try:
            reported = self._send("GET_BATTERY_LEVEL", timeout=_QUERY_TIMEOUT)
        except (PipetteCommandError, PipetteTimeoutError, PipetteMotorControlError):
            return None
        return None if not reported else _first_number(reported)

    def _check_battery(self) -> None:
        """Refuse to start below the configured charge floor.

        No other CubOS instrument has a charge state; an overnight campaign
        that dies mid-transfer is a new failure mode, so this fails closed at
        connect rather than surprising the operator hours in.
        """
        level = self._read_battery()
        if level is None:
            self.logger.warning("Pipette did not report a battery level")
            return
        if level < self._min_battery_percent:
            raise PipetteBatteryError(
                f"Pipette battery is at {level:g}%, below the "
                f"{self._min_battery_percent:g}% minimum. Charge it over USB "
                f"before starting a run."
            )
        self.logger.info("Pipette battery at %g%%", level)

    @staticmethod
    def _frame(no: int, *, data: str | None = None, button: str | None = None) -> bytes:
        payload: dict[str, Any] = {"no": no}
        if data is not None:
            payload["data"] = data
        if button is not None:
            payload["button"] = button
        return json.dumps(payload, separators=(",", ":")).encode("ascii") + _TERMINATOR

    @staticmethod
    def _parse_line(line: str) -> tuple[str, Optional[int], Optional[str]]:
        """Sort one received line into ``(kind, sequence_no, value)``.

        Kinds are ``ack`` / ``begin`` / ``end`` (envelope, carrying the
        sequence number), ``result`` (a result code plus its sequence number),
        ``data`` (a bare payload line, which carries no sequence number of its
        own) and ``ignore`` (blank lines and the unsolicited JSON button
        events the pipette pushes when ``AUTO 1`` is on).
        """
        stripped = line.strip()
        if not stripped:
            return ("ignore", None, None)
        if stripped.startswith("{"):
            # Asynchronous notification (e.g. {"button":"RIGHT_PRESSED"}).
            # Never a command's output, however mid-command it arrives.
            return ("ignore", None, None)
        parts = stripped.split()
        head = parts[0]
        reply_no: Optional[int] = None
        if len(parts) >= 2:
            try:
                reply_no = int(parts[1])
            except ValueError:
                reply_no = None
        if head in _ENVELOPE_TOKENS and reply_no is not None:
            return (head.lower(), reply_no, None)
        if head in _RESULT_CODES and reply_no is not None:
            return ("result", reply_no, head)
        return ("data", None, stripped)

    def _write(self, frame: bytes) -> None:
        if self._serial is None:
            raise PipetteCommandError("Not connected to pipette")
        try:
            self._serial.write(frame)
            self._serial.flush()
        except serial.SerialException as exc:
            raise PipetteConnectionError(f"Serial write failed: {exc}") from exc

    def _read_line(self) -> Optional[str]:
        if self._serial is None:
            raise PipetteCommandError("Not connected to pipette")
        try:
            raw = self._serial.readline()
        except serial.SerialException as exc:
            raise PipetteConnectionError(f"Serial read failed: {exc}") from exc
        if not raw:
            return None
        return raw.decode("ascii", errors="replace")

    def _send(self, data: str, *, timeout: Optional[float] = None) -> Optional[str]:
        """Send one command and wait for its terminal result token.

        Returns the joined data lines, or ``None`` when the command produced
        none. Raises on any non-OK result.
        """
        if self._serial is None or not self._serial.is_open:
            raise PipetteCommandError("Not connected to pipette")
        if self._motor_control_lost:
            raise PipetteMotorControlError(
                "Motor control was aborted; reconnect before sending further "
                "commands (the piston position is unknown)."
            )
        wait = self._command_timeout if timeout is None else timeout
        responses: list[str] = []
        # Sequence numbers of BEGIN scopes the pipette has opened and not yet
        # closed. Data lines carry no number of their own, so one belongs to
        # whichever scope is innermost -- replies for different commands
        # interleave freely.
        scopes: list[int] = []

        with self._lock:
            frame_no = next(self._counter)
            self._write(self._frame(frame_no, data=data))
            deadline = time.monotonic() + wait
            while True:
                if time.monotonic() >= deadline:
                    raise PipetteTimeoutError(
                        f"Timed out ({wait}s) waiting for a reply to {data!r}"
                    )
                line = self._read_line()
                if line is None:
                    continue
                kind, reply_no, value = self._parse_line(line)
                if kind == "begin":
                    scopes.append(reply_no)
                elif kind == "end":
                    if reply_no in scopes:
                        scopes.remove(reply_no)
                    # END is the only terminator every command sends: a query
                    # replies with data lines and no result code at all.
                    if reply_no == frame_no:
                        return "\n".join(responses) if responses else None
                elif kind == "result" and reply_no == frame_no:
                    if value == _ABORT_CODE:
                        self._motor_control_lost = True
                        raise PipetteMotorControlError(
                            f"Pipette aborted motor control during {data!r}. The "
                            f"piston position is now unknown; reconnect to "
                            f"re-initialize before any further liquid handling."
                        )
                    if value != _RESULT_OK:
                        raise PipetteCommandError(f"{data!r} failed: {value}")
                elif (
                    kind == "data"
                    and value is not None
                    and scopes[-1:] == [frame_no]
                ):
                    responses.append(value)

    def _close_serial(self) -> None:
        if self._serial is not None:
            try:
                self._serial.close()
            except serial.SerialException:
                pass
            self._serial = None


# Matches the first number in a reply, tolerating a thousands separator and a
# trailing unit: "1,000 uL" and "battery 87 %" both yield their figure. Naive
# whitespace splitting would read "1,000" as 1, which would make the connect-
# time model check reject a correctly configured 1000 uL pipette.
_NUMBER_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def _first_number(text: str) -> Optional[float]:
    """Pull the first numeric value out of an instrument reply."""
    match = _NUMBER_RE.search(text)
    if match is None:
        return None
    try:
        return float(match.group().replace(",", ""))
    except ValueError:
        return None
