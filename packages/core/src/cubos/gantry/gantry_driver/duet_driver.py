"""Duet 3 / RepRapFirmware motion-controller driver.

DuetDriver mirrors the Mill (GRBL) driver surface exactly — same method
names, signatures, exception types, and blocking semantics — so the Gantry
facade can hold either driver behind the same seam. On the wire it speaks
RepRapFirmware 3.5+ over USB serial: line-based commands acknowledged with
``ok``, status and position read from the object model via ``M409``.

Status frames crossing the driver boundary are synthesized in the GRBL
shape ``<State|WPos:x,y,z>`` because that shape is a de-facto interchange
format for every layer above the driver (Gantry._extract_status, session
alarm classification, limit_recovery token matching, the operator web UI).
The state word is mapped from the RRF object model:

    idle/simulating          -> Idle
    processing/busy/starting -> Run
    resuming/cancelling      -> Run
    pausing/paused           -> Hold:0
    halted/off               -> Alarm

Semantics that differ from GRBL, by necessity:

* ``stop()``/``feed_hold_realtime()`` issue ``M112`` (emergency stop) —
  RRF has no realtime feed hold for streamed moves over USB. Recovery is
  ``soft_reset_and_unlock()`` (``M999`` + reconnect), the same path limit
  recovery already drives. There is no resumable hold; ``resume()`` sends
  ``M24``, which is benign outside file prints.
* ``soft_reset()``/``unlock()`` both map to ``M999``, which reboots the
  board and drops USB for a few seconds; the driver closes and reopens
  the port transparently. Homed state is lost, exactly as GRBL loses it
  on Ctrl-X with homing lock enabled.
* GRBL ``$`` settings do not exist: ``read_grbl_settings()`` returns an
  empty dict (callers treat missing keys as "unknown"), and
  ``set_grbl_setting()`` raises CommandExecutionError — motion limits,
  homing behavior, and axis directions live in the board's config.g.
"""

# pylint: disable=line-too-long

import json
import math
import os
import re
import time
from pathlib import Path
from typing import Optional, Tuple

import serial
import serial.tools.list_ports

from .driver import DEFAULT_FEED_RATE
from .exceptions import (
    CommandExecutionError,
    LocationNotFound,
    MillConnectionError,
    StatusReturnError,
)
from .logger import set_up_command_logger, set_up_mill_logger
from ..coordinates import Coordinates

HOMING_TIMEOUT = 90
COMMAND_IDLE_TIMEOUT = 5
RESET_RECONNECT_DELAY = 4.0
RESET_RECONNECT_ATTEMPTS = 8
RESET_RECONNECT_RETRY_DELAY = 1.5

_RRF_STATE_TO_GRBL_WORD = {
    "idle": "Idle",
    "simulating": "Idle",
    "processing": "Run",
    "busy": "Run",
    "starting": "Run",
    "resuming": "Run",
    "cancelling": "Run",
    "changingTool": "Run",
    "updating": "Run",
    "pausing": "Hold:0",
    "paused": "Hold:0",
    "halted": "Alarm",
    "off": "Alarm",
}

_JSON_REPLY_RE = re.compile(r"^\{.*\}\s*$")


class DuetDriver:
    """Drive a Duet 3 (RepRapFirmware) motion controller over USB serial.

    Attributes mirror :class:`~cubos.gantry.gantry_driver.driver.Mill`:
    ``config``, ``ser_mill``, ``homed``, ``active_connection``,
    ``last_status``, ``port``.
    """

    def __init__(self, port: Optional[str] = None, log_dir: Path | None = None):
        self.logger_location = log_dir
        self.logger = set_up_mill_logger(log_dir)
        self.port = port
        self.config = {}
        self._init_state()
        self.ser_mill: serial.Serial = None

    def _init_state(self):
        """Initialize state attributes for a fresh, unconnected controller."""
        self.config = {}
        self.homed = False
        self.auto_home = False
        self.active_connection = False
        self.command_logger = set_up_command_logger(self.logger_location)
        self.last_status: str = ""
        self._last_position: Optional[Coordinates] = None

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def _get_available_ports(self):
        """List serial ports that could plausibly be a Duet (USB CDC)."""
        if os.name == "posix":
            return list(serial.tools.list_ports.grep("ttyACM|usbmodem|Duet"))
        if os.name == "nt":
            return list(serial.tools.list_ports.grep("COM"))
        raise OSError("Unsupported OS")

    def _verify_connection(self, ser_mill: serial.Serial) -> bool:
        """Verify the connected device answers M115 as RepRapFirmware."""
        ser_mill.flushInput()
        ser_mill.flushOutput()
        time.sleep(0.1)
        if not ser_mill.is_open:
            ser_mill.open()
            time.sleep(0.5)
        if not ser_mill.is_open:
            return False

        ser_mill.write(b"M115\n")
        time.sleep(0.2)
        lines = ser_mill.readlines()
        self.logger.info("M115 raw response: %s", lines)
        for line in lines:
            decoded = line.decode(errors="ignore")
            if "RepRapFirmware" in decoded or "Duet" in decoded:
                return True
        return False

    def _locate_over_serial(self, port: Optional[str] = None) -> Tuple[serial.Serial, str]:
        """Find a RepRapFirmware controller, preferring the given port."""
        ports = []
        if port:
            ports.append(port)
        for candidate in self._get_available_ports():
            if candidate.device not in ports:
                ports.append(candidate.device)
        if not ports:
            self.logger.error("No serial ports found to connect to.")
            raise MillConnectionError(
                "No serial ports found. Checked ttyACM and usbmodem."
            )

        ser_mill = serial.Serial()
        for candidate in ports:
            if not candidate:
                continue
            try:
                self.logger.info("Attempting Duet connection on %s", candidate)
                ser_mill = serial.Serial(port=candidate, baudrate=115200, timeout=2)
                if self._verify_connection(ser_mill):
                    self.logger.info("RepRapFirmware found on %s", candidate)
                    return ser_mill, candidate
                self.logger.warning("No RepRapFirmware response from %s", candidate)
                ser_mill.close()
            except Exception as exc:  # pylint: disable=broad-except
                self.logger.error("Error checking %s: %s", candidate, exc)
                if ser_mill.is_open:
                    ser_mill.close()
        raise MillConnectionError(
            f"Could not find a RepRapFirmware controller on ports {ports}"
        )

    def connect(
        self,
        port: Optional[str] = None,
        baudrate=115200,
        timeout=3,
    ) -> serial.Serial:
        """Open the serial connection and initialize the controller."""
        self._init_state()
        self.ser_mill = None
        try:
            ser_mill, port_name = self._locate_over_serial(port or self.port)
            self.ser_mill = ser_mill
            self.port = port_name
            if not self.ser_mill.is_open:
                self.ser_mill.open()
                time.sleep(0.5)
            if not self.ser_mill.is_open:
                raise MillConnectionError("Error opening serial connection to Duet")
            self.ser_mill.timeout = timeout
            self.active_connection = True
            self.logger.info("Duet connected on %s", port_name)
        except MillConnectionError:
            raise
        except Exception as exep:
            self.logger.error("Error connecting to the Duet: %s", str(exep))
            raise MillConnectionError("Error connecting to the mill") from exep

        # Mirror the GRBL alarm early-return: when the board is halted
        # (post-M112), skip setup and leave recovery to the caller
        # (prepare_for_protocol_run -> reset_and_unlock).
        state = self._query_state(allow_failure=True)
        self._refresh_homed_from_object_model(allow_failure=True)
        if state == "halted":
            self.last_status = self._synthesize_frame("Alarm")
            self.logger.warning(
                "Duet is halted (emergency stop) — skipping setup. "
                "Reset (M999) to clear."
            )
            return self.ser_mill

        self.read_config()
        self.clear_buffers()
        self.enforce_wpos_mode()
        self.set_feed_rate(DEFAULT_FEED_RATE)
        self.seed_wco()
        return self.ser_mill

    def disconnect(self):
        """Close the serial connection to the controller."""
        self.logger.info("Disconnecting from the Duet")
        if self.ser_mill:
            self.ser_mill.close()
            if self.ser_mill.is_open:
                self.logger.error("Failed to close the serial connection")
                raise MillConnectionError("Error closing serial connection to mill")
            self._init_state()
            self.ser_mill = None
        else:
            self.logger.info("Serial connection was already closed or never opened.")
            self._init_state()

    def connected_port(self) -> str | None:
        """Return the active serial port name, if connected."""
        if self.ser_mill is None:
            return self.port
        port = getattr(self.ser_mill, "port", None)
        return str(port) if port else self.port

    def is_connected(self) -> bool:
        """Check if the serial connection is open."""
        return bool(self.ser_mill and self.ser_mill.is_open)

    def set_read_timeout(self, timeout: float) -> None:
        """Set the serial read timeout when a connection exists."""
        if self.ser_mill is not None:
            self.ser_mill.timeout = timeout

    def get_read_timeout(self) -> float | None:
        """Return the serial read timeout when a connection exists."""
        if self.ser_mill is None:
            return None
        return self.ser_mill.timeout

    def _require_open_serial(self) -> None:
        if self.ser_mill is None or not getattr(self.ser_mill, "is_open", False):
            self.logger.error("Serial connection to Duet is not open")
            raise MillConnectionError("Serial connection to mill is not open")

    # ------------------------------------------------------------------
    # Low-level protocol
    # ------------------------------------------------------------------

    def _write_line(self, command: str) -> None:
        self._require_open_serial()
        self.command_logger.debug("%s", command)
        self.ser_mill.write((command + "\n").encode("ascii"))

    def _read_reply(self, timeout: float = 5.0) -> list[str]:
        """Collect reply lines until ``ok`` (which terminates every reply).

        Error lines are collected, not raised — callers decide severity.
        """
        self._require_open_serial()
        deadline = time.time() + timeout
        lines: list[str] = []
        while time.time() < deadline:
            raw = self.ser_mill.readline()
            if raw in (b"", ""):
                time.sleep(0.01)
                continue
            line = raw.decode("ascii", errors="replace") if isinstance(raw, bytes) else raw
            line = line.strip()
            if not line:
                continue
            if line == "ok" or line.endswith(" ok"):
                return lines
            lines.append(line)
        raise StatusReturnError(
            f"Timed out after {timeout}s waiting for ok; got {lines!r}"
        )

    def _query_object_model(self, key: str, timeout: float = 3.0):
        """Query one object-model key via M409 and return its ``result``.

        The reply stream is scanned for the JSON payload whose ``key``
        matches the request; anything else — stray ``ok`` acknowledgments
        from earlier fire-and-forget commands (G28, M24), stale replies to
        older M409s that were queued behind a blocking command, plain
        messages — is skimmed. This self-heals reply desynchronization,
        which RRF's USB channel makes routine: a blocking G28 queues every
        subsequent command and answers them in a burst on completion.
        """
        self._write_line(f'M409 K"{key}"')
        deadline = time.time() + timeout
        seen: list[str] = []
        while time.time() < deadline:
            raw = self.ser_mill.readline()
            if raw in (b"", ""):
                time.sleep(0.01)
                continue
            line = raw.decode("ascii", errors="replace") if isinstance(raw, bytes) else raw
            line = line.strip()
            if not line:
                continue
            seen.append(line)
            if not _JSON_REPLY_RE.match(line):
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if payload.get("key") == key:
                self._consume_trailing_ok()
                return payload.get("result")
        raise StatusReturnError(
            f"No object-model reply for {key!r} within {timeout}s; got {seen!r}"
        )

    def _consume_trailing_ok(self, timeout: float = 0.5) -> None:
        """Drain the ``ok`` that terminates a reply we returned from early.

        Leaving it queued would make the next command's reply reader treat
        the stale ``ok`` as its terminator — silently swallowing that
        command's real reply (including error lines).
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            raw = self.ser_mill.readline()
            if raw in (b"", ""):
                time.sleep(0.01)
                continue
            line = raw.decode("ascii", errors="replace") if isinstance(raw, bytes) else raw
            line = line.strip()
            if line == "ok" or line.endswith(" ok"):
                return

    def _query_state(self, allow_failure: bool = False) -> str:
        """Return the RRF machine state word (lowercase)."""
        try:
            result = self._query_object_model("state.status")
            return str(result)
        except (StatusReturnError, MillConnectionError):
            if allow_failure:
                return ""
            raise

    def _query_axes(self):
        """Return the object-model ``move.axes`` array."""
        result = self._query_object_model("move.axes")
        if not isinstance(result, list):
            raise StatusReturnError(f"Unexpected move.axes reply: {result!r}")
        return result

    def _refresh_homed_from_object_model(self, allow_failure: bool = False) -> None:
        try:
            axes = self._query_axes()
            self.homed = bool(axes) and all(a.get("homed") for a in axes)
        except (StatusReturnError, MillConnectionError):
            if allow_failure:
                return
            raise

    def _synthesize_frame(
        self, state_word: str, coords: Optional[Coordinates] = None
    ) -> str:
        """Build a GRBL-shaped status frame from RRF state + position."""
        coords = coords or self._last_position or Coordinates(0.0, 0.0, 0.0)
        return (
            f"<{state_word}|WPos:{coords.x:.3f},{coords.y:.3f},{coords.z:.3f}>"
        )

    @staticmethod
    def _grbl_word_for_state(state: str) -> str:
        return _RRF_STATE_TO_GRBL_WORD.get(state, state.capitalize() or "Unknown")

    # ------------------------------------------------------------------
    # Status / position
    # ------------------------------------------------------------------

    def current_status(self) -> str:
        """Return a GRBL-shaped status frame synthesized from the object model."""
        self._require_open_serial()
        state = self._query_state()
        try:
            coords = self._read_position_once()
        except (StatusReturnError, MillConnectionError):
            coords = None
        status = self._synthesize_frame(self._grbl_word_for_state(state), coords)
        self.last_status = status
        return status

    def query_raw_status(self) -> str:
        """Return one raw status frame for diagnostics/recovery.

        Returns an empty string only when the driver is not connected.
        Transport failures raise :class:`MillConnectionError` so safety
        paths cannot mistake a broken port for a healthy controller.
        Content (including Alarm) never raises — callers inspect it.
        """
        if not self.is_connected():
            return ""
        try:
            state = self._query_state()
            try:
                coords = self._read_position_once()
            except StatusReturnError:
                coords = None
            frame = self._synthesize_frame(
                self._grbl_word_for_state(state), coords
            )
            self.last_status = frame
            return frame
        except MillConnectionError:
            raise
        except (serial.SerialException, OSError) as exc:
            self.logger.warning("Raw status query failed: %s", exc)
            raise MillConnectionError(f"Raw status query failed: {exc}") from exc
        except StatusReturnError:
            return self.last_status or ""

    def _read_position_once(self) -> Coordinates:
        axes = self._query_axes()
        by_letter = {str(a.get("letter", "")).upper(): a for a in axes}
        try:
            coords = Coordinates(
                round(float(by_letter["X"]["userPosition"]), 3),
                round(float(by_letter["Y"]["userPosition"]), 3),
                round(float(by_letter["Z"]["userPosition"]), 3),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise StatusReturnError(
                f"Malformed move.axes position reply: {axes!r}"
            ) from exc
        self._last_position = coords
        return coords

    def current_coordinates(self) -> Coordinates:
        """Return the current deck-frame position from the object model.

        Raises:
            LocationNotFound: no parsable position after several queries —
                callers that can proceed safely without a position
                (absolute moves) may catch this and fall back.
        """
        self._require_open_serial()
        max_attempts = 4
        last_error: Optional[Exception] = None
        for attempt in range(max_attempts):
            try:
                coords = self._read_position_once()
                self.last_status = self._synthesize_frame(
                    self._grbl_word_for_state(self._query_state()), coords
                )
                self.logger.info(
                    "Position: X = %s, Y = %s, Z = %s",
                    coords.x, coords.y, coords.z,
                )
                return coords
            except (StatusReturnError, MillConnectionError) as exc:
                last_error = exc
                self.logger.warning(
                    "No position from object model (attempt %d/%d): %s",
                    attempt + 1, max_attempts, exc,
                )
                time.sleep(0.2)
        raise LocationNotFound(
            f"No parsable position after {max_attempts} object-model "
            f"queries; last error: {last_error}"
        )

    # ------------------------------------------------------------------
    # Command execution
    # ------------------------------------------------------------------

    def execute_command(self, command: str, suppress_errors: bool = False):
        """Send one command, wait for ``ok``, then wait for motion to finish.

        Mirrors Mill.execute_command: failures (including RRF ``Error:``
        reply lines) raise :class:`CommandExecutionError`; the RRF error
        text is preserved in the message so upper layers can classify it
        (e.g. "outside machine limits" matches limit-recovery tokens).
        """
        try:
            self._require_open_serial()
            self.logger.debug("Command sent: %s", command)
            if command == "$$":
                # GRBL settings dump has no RRF analogue.
                return {}
            self._write_line(command)
            reply = self._read_reply()
            errors = [line for line in reply if line.lower().startswith("error")]
            if errors:
                raise StatusReturnError(f"Error in status: {'; '.join(errors)}")
            status = self._wait_until_idle(suppress_errors=suppress_errors)
            self.logger.debug("Returned %s", status)
            return status
        except Exception as exep:
            import logging as _logging
            level = _logging.WARNING if suppress_errors else _logging.ERROR
            self.logger.log(
                level, "Error executing command %s: %s", command, str(exep)
            )
            raise CommandExecutionError(
                f"Error executing command {command}: {str(exep)}"
            ) from exep

    def _wait_until_idle(
        self, suppress_errors: bool = False, timeout=COMMAND_IDLE_TIMEOUT
    ):
        """Poll the object model until the machine returns to idle.

        The timeout clock resets while the machine reports active motion,
        so it bounds *stall* time, not total move time — matching the GRBL
        driver's reset-on-Run behavior.
        """
        start_time = time.time()
        while True:
            state = self._query_state()
            word = self._grbl_word_for_state(state)
            frame = self._synthesize_frame(word)
            self.last_status = frame
            if state in ("idle", "simulating"):
                return frame
            if word == "Alarm":
                if not suppress_errors:
                    self.logger.error("Alarm in status: %s", frame)
                raise StatusReturnError(f"Alarm in status: {frame}")
            if word.startswith("Hold"):
                if not suppress_errors:
                    self.logger.error("Hold in status: %s", frame)
                raise StatusReturnError(f"Hold in status: {frame}")
            if word == "Run":
                start_time = time.time()
            if time.time() - start_time > timeout:
                raise StatusReturnError(
                    f"Command execution timed out after {timeout} seconds: {frame}"
                )
            time.sleep(0.05)

    # ------------------------------------------------------------------
    # Setup helpers (GRBL-parity surface)
    # ------------------------------------------------------------------

    def read_config(self):
        """Read controller identity (M115) into ``config``."""
        self._require_open_serial()
        self._write_line("M115")
        lines = self._read_reply()
        info = "; ".join(lines)
        self.config = {"firmware_info": info}
        self.logger.info("Duet firmware: %s", info)
        return self.config

    def clear_buffers(self):
        """Clear input and output buffers."""
        self._require_open_serial()
        self.ser_mill.flush()
        self.ser_mill.read_all()

    def enforce_wpos_mode(self):
        """Ensure absolute positioning (G90). RRF has no $10 concept."""
        self.execute_command("G90")
        self.logger.info("Absolute positioning enforced")

    def set_feed_rate(self, rate):
        """Set the modal feed rate."""
        self.execute_command(f"G1 F{rate}")

    def seed_wco(self):
        """No-op: RRF work offsets are read directly from the object model."""
        return

    def read_soft_limits(self) -> bool:
        """Return whether RRF axis-limit enforcement (M564 S1) is active."""
        return bool(self._query_object_model("move.limitAxes"))

    def set_soft_limits(self, enabled: bool) -> None:
        """Enable/disable RRF axis-limit enforcement (M564).

        Runtime-volatile: the board reverts to config.g's M564 on reboot,
        which ships S1 H1 — so a reboot fails safe (limits back on).
        """
        self.execute_command("M564 S1" if enabled else "M564 S0")

    def read_work_offsets(self) -> dict:
        """Return the effective workplace offsets (machine − user) per axis."""
        axes = self._query_axes()
        offsets = {}
        for axis in axes:
            letter = str(axis.get("letter", "")).lower()
            if letter in ("x", "y", "z"):
                offsets[letter] = round(
                    float(axis["machinePosition"]) - float(axis["userPosition"]),
                    3,
                )
        if set(offsets) != {"x", "y", "z"}:
            raise StatusReturnError(f"Malformed move.axes offsets reply: {axes!r}")
        return offsets

    def apply_work_offsets(self, x: float, y: float, z: float) -> None:
        """Set the G54 origin offsets directly (G10 L2, machine frame).

        RRF does not persist workplace offsets across reboots, so calibrated
        offsets live in the gantry YAML and are re-applied at connect.
        """
        self.execute_command(f"G10 L2 P1 X{x:.3f} Y{y:.3f} Z{z:.3f}")

    def read_axis_extents(self) -> dict:
        """Return machine-frame axis (min, max) tuples from the object model."""
        axes = self._query_axes()
        extents = {}
        for axis in axes:
            letter = str(axis.get("letter", "")).lower()
            if letter in ("x", "y", "z"):
                try:
                    extents[letter] = (float(axis["min"]), float(axis["max"]))
                except (KeyError, TypeError, ValueError) as exc:
                    raise StatusReturnError(
                        f"Malformed move.axes extents reply: {axes!r}"
                    ) from exc
        if set(extents) != {"x", "y", "z"}:
            raise StatusReturnError(f"Malformed move.axes extents reply: {axes!r}")
        return extents

    def read_grbl_settings(self) -> dict:
        """Return an empty dict — RRF has no GRBL ``$`` settings.

        Callers treat missing keys as "unknown/not readable", which is the
        correct answer here: motion limits and homing behavior live in the
        board's config.g, not in runtime-writable settings.
        """
        return {}

    def set_grbl_setting(self, setting: str, value: str):
        """GRBL settings cannot be written on RepRapFirmware."""
        raise CommandExecutionError(
            f"GRBL setting ${setting} is not supported on RepRapFirmware/Duet; "
            "motion configuration lives in the board's config.g"
        )

    # ------------------------------------------------------------------
    # Motion
    # ------------------------------------------------------------------

    def jog(self, x: float = 0, y: float = 0, z: float = 0,
            feed_rate: float = DEFAULT_FEED_RATE) -> None:
        """Jog by a relative offset, emitted as one absolute ``G1``.

        The target is computed from the current object-model position, so
        the controller's modal state is never switched to relative — a jog
        that dies mid-sequence can therefore never leave the parser in G91
        (the real-motion hazard the GRBL driver's enforce_wpos_mode
        docstring warns about). Consequence: overlapping jogs anchor to
        the position read at send time; CubOS jogs are discrete, so this
        matches GRBL ``$J`` behavior in practice.

        When homed, the move is soft-limited. When not homed (e.g. during
        limit recovery after a reset), ``G1 H2`` is used — RRF's unhomed
        individual-motor move; the frame is zeroed after reset, so the
        computed absolute target is the pure displacement. Jogs are
        non-blocking: RRF buffers the move and acknowledges immediately.
        """
        self._require_open_serial()
        if x == 0 and y == 0 and z == 0:
            return
        try:
            current = self._read_position_once()
        except (StatusReturnError, MillConnectionError) as exc:
            raise CommandExecutionError(
                f"Jog failed: could not read current position ({exc})"
            ) from exc
        parts = []
        if x != 0:
            parts.append(f"X{current.x + x:.3f}")
        if y != 0:
            parts.append(f"Y{current.y + y:.3f}")
        if z != 0:
            parts.append(f"Z{current.z + z:.3f}")
        move_flag = "" if self.homed else " H2"
        cmd = f"G1{move_flag} {' '.join(parts)} F{feed_rate}"
        self.logger.debug("Jog command: %s", cmd)
        self._write_line(cmd)
        try:
            reply = self._read_reply(timeout=2.0)
        except StatusReturnError as exc:
            raise CommandExecutionError(f"Jog failed: {exc}") from exc
        errors = [line for line in reply if line.lower().startswith("error")]
        if errors:
            self.logger.error("Jog error: %s", errors)
            raise CommandExecutionError(f"Jog failed: {'; '.join(errors)}")

    def jog_cancel(self) -> None:
        """No-op: RRF has no jog-cancel for buffered moves.

        CubOS jogs are short, finite, and non-repeating, so an uncancelled
        jog completes in well under a second. Emergency interruption is
        ``stop()`` (M112).
        """
        self.logger.debug("jog_cancel is a no-op on RepRapFirmware")

    def move_to(
        self,
        x_coordinate: float = 0.00,
        y_coordinate: float = 0.00,
        z_coordinate: float = 0.00,
        coordinates: Coordinates = None,
        travel_z: Optional[float] = None,
    ) -> None:
        """Move to absolute machine coordinates, axis-by-axis.

        Semantics mirror Mill.move_to exactly: optional ``travel_z``
        transit height, axis-by-axis motion (never diagonal), pruning of
        no-op axes when the current position is readable, and a fallback
        to the full unpruned absolute sequence when it is not.
        """
        goto = (
            Coordinates(x=x_coordinate, y=y_coordinate, z=z_coordinate)
            if not coordinates
            else coordinates
        )
        self._validate_target_coordinates(goto)
        if travel_z is not None:
            self._validate_finite_coordinate(travel_z, "travel Z")
        try:
            current_coordinates = self.current_coordinates()
        except LocationNotFound as exc:
            self.logger.warning(
                "Position read failed before move (%s); emitting full "
                "absolute move sequence without pruning.", exc,
            )
            current_coordinates = None

        if current_coordinates is not None and self._is_already_at_target(
            goto, current_coordinates
        ):
            self.logger.debug(
                "Already at target coordinates [%s, %s, %s]",
                goto.x, goto.y, goto.z,
            )
            return

        if travel_z is None:
            commands = self._build_direct_move(current_coordinates, goto)
        else:
            commands = self._build_transit_move(
                current_coordinates, goto, travel_z
            )
        for cmd in commands:
            self.execute_command(cmd)

    def _is_already_at_target(self, goto: Coordinates, current: Coordinates):
        return (goto.x, goto.y) == (current.x, current.y) and goto.z == current.z

    def _validate_target_coordinates(self, target: Coordinates):
        self._validate_finite_coordinate(target.x, "target X")
        self._validate_finite_coordinate(target.y, "target Y")
        self._validate_finite_coordinate(target.z, "target Z")

    @staticmethod
    def _validate_finite_coordinate(value: float, label: str) -> None:
        try:
            numeric_value = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} must be finite; got {value!r}.") from exc
        if not math.isfinite(numeric_value):
            raise ValueError(f"{label} must be finite; got {value!r}.")

    def _build_direct_move(self, current: Optional[Coordinates], target: Coordinates):
        """Axis-by-axis absolute move, X then Y then Z. See Mill for rationale."""
        f = f" F{DEFAULT_FEED_RATE}"
        commands = []
        if current is None or target.x != current.x:
            commands.append(f"G01 X{target.x}{f}")
        if current is None or target.y != current.y:
            commands.append(f"G01 Y{target.y}{f}")
        if current is None or target.z != current.z:
            commands.append(f"G01 Z{target.z}{f}")
        return commands

    def _build_transit_move(
        self, current: Optional[Coordinates], target: Coordinates, travel_z: float
    ):
        """Transit via ``travel_z``: lift, X, Y, descend. See Mill for rationale."""
        f = f" F{DEFAULT_FEED_RATE}"
        self._validate_finite_coordinate(travel_z, "travel Z")
        commands = []
        if current is None or current.z != travel_z:
            commands.append(f"G01 Z{travel_z}{f}")
        if current is None or target.x != current.x:
            commands.append(f"G01 X{target.x}{f}")
        if current is None or target.y != current.y:
            commands.append(f"G01 Y{target.y}{f}")
        if target.z != travel_z:
            commands.append(f"G01 Z{target.z}{f}")
        return commands

    # ------------------------------------------------------------------
    # Homing
    # ------------------------------------------------------------------

    def home(self, timeout=HOMING_TIMEOUT):
        """Home all axes (G28) and wait for completion.

        A paused state during homing raises rather than auto-resuming
        (design rule carried over from GRBL hold recovery: no automatic
        resume is permitted). A halted state raises as an alarm.
        """
        self._require_open_serial()
        self.logger.info("Homing (G28)")
        self._write_line("G28")
        time.sleep(1)
        start_time = time.time()
        last_status_error = None

        while True:
            if time.time() - start_time > timeout:
                self.logger.warning("Homing timed out")
                if last_status_error is not None:
                    raise StatusReturnError(
                        f"Homing timed out after {timeout} seconds; "
                        f"last status error: {last_status_error}"
                    ) from last_status_error
                raise StatusReturnError(f"Homing timed out after {timeout} seconds")

            try:
                state = self._query_state()
            except (StatusReturnError, MillConnectionError) as exc:
                last_status_error = exc
                self.logger.warning("No valid status during homing; retrying: %s", exc)
                time.sleep(0.5)
                continue

            word = self._grbl_word_for_state(state)
            self.last_status = self._synthesize_frame(word)

            if word.startswith("Hold"):
                raise StatusReturnError(
                    "Homing paused by feed hold "
                    f"({self.last_status}). Resume or reset/unlock before retrying."
                )
            if word == "Alarm":
                raise StatusReturnError(
                    f"Alarm in status during homing: {self.last_status}"
                )
            if state in ("idle", "simulating"):
                self._refresh_homed_from_object_model(allow_failure=True)
                if self.homed:
                    self.logger.info("Homing completed")
                    break
                # Idle but not homed yet: G28 may not have started, or a
                # homing file aborted without an error state. Give it the
                # full timeout before concluding failure.
                time.sleep(0.5)
                if time.time() - start_time > timeout:
                    raise StatusReturnError(
                        "Homing finished without all axes reporting homed"
                    )
                continue
            time.sleep(0.5)

    # ------------------------------------------------------------------
    # Stop / reset / recovery
    # ------------------------------------------------------------------

    def stop(self):
        """Immediately stop all motion via RRF emergency stop (M112).

        RRF has no realtime feed hold for USB-streamed moves, so stop is
        an emergency halt. Recovery is ``soft_reset_and_unlock()``.
        """
        self.feed_hold_realtime()
        self.last_status = self._synthesize_frame("Alarm")

    def feed_hold_realtime(self) -> None:
        """Send M112 without waiting for a reply (the board halts)."""
        self._require_open_serial()
        self.logger.warning("Sending emergency stop (M112)")
        self.ser_mill.write(b"M112\n")
        time.sleep(0.2)
        try:
            self.ser_mill.read_all()
        except (serial.SerialException, OSError):
            pass
        self.homed = False

    def resume(self) -> None:
        """Send M24 (resume). Benign outside paused file prints.

        An M112 halt cannot be resumed — use ``soft_reset_and_unlock()``.
        """
        self._require_open_serial()
        self._write_line("M24")
        try:
            self._read_reply(timeout=2.0)
        except StatusReturnError:
            pass

    def soft_reset(self):
        """Reset the board (M999) and transparently reconnect.

        M999 reboots RepRapFirmware and drops the USB device for a few
        seconds; the driver closes the port, waits, and reopens the same
        port path. Homed state is lost, as with a GRBL soft reset.
        """
        self._require_open_serial()
        port_path = self.connected_port()
        self.logger.info("Sending reset (M999); board will drop USB briefly")
        try:
            self.ser_mill.write(b"M999\n")
        except (serial.SerialException, OSError):
            pass
        try:
            self.ser_mill.close()
        except (serial.SerialException, OSError):
            pass
        time.sleep(RESET_RECONNECT_DELAY)

        last_error: Optional[Exception] = None
        for attempt in range(RESET_RECONNECT_ATTEMPTS):
            try:
                self.ser_mill = serial.Serial(
                    port=port_path, baudrate=115200, timeout=3
                )
                if self._verify_connection(self.ser_mill):
                    self.active_connection = True
                    self.homed = False
                    self.logger.info(
                        "Reconnected to Duet on %s after reset", port_path
                    )
                    return
                self.ser_mill.close()
                last_error = MillConnectionError(
                    "Device did not answer M115 after reset"
                )
            except (serial.SerialException, OSError) as exc:
                last_error = exc
            time.sleep(RESET_RECONNECT_RETRY_DELAY)
        self.active_connection = False
        raise MillConnectionError(
            f"Could not reconnect to Duet on {port_path} after M999 reset: "
            f"{last_error}"
        )

    def unlock(self):
        """Clear a halted (emergency-stopped) state.

        RRF's only unlock is a board reset (M999). When the board is not
        halted this is a no-op, unlike GRBL's $X which is always safe to
        send.
        """
        self._require_open_serial()
        state = self._query_state(allow_failure=True)
        if state != "halted":
            self.logger.info("Unlock requested but Duet is not halted (%s)", state)
            return
        self.soft_reset()
        state = self._query_state(allow_failure=True)
        if state == "halted":
            raise CommandExecutionError(
                "Duet remained halted after M999 reset"
            )

    def soft_reset_and_unlock(self):
        """Reset the board and verify it comes back un-halted."""
        self.soft_reset()
        state = self._query_state(allow_failure=True)
        if state == "halted":
            raise CommandExecutionError("Duet remained halted after M999 reset")
        self.last_status = self._synthesize_frame(
            self._grbl_word_for_state(state or "idle")
        )
