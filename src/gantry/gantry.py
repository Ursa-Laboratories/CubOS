from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

from .coordinate_translator import (
    to_machine_coordinates,
    to_user_coordinates,
    translate_status_string,
)
from .grbl_settings import format_setting_value, normalize_expected_grbl_settings
from .gantry_driver.driver import DEFAULT_FEED_RATE, Mill
from .gantry_driver.exceptions import (
    CommandExecutionError,
    LocationNotFound,
    MillConnectionError,
    StatusReturnError,
)
from .origin import format_set_work_position_command

_STATUS_RE = re.compile(r"<([^|>]+)")

logger = logging.getLogger(__name__)


class Gantry:
    """High-level gantry wrapper around the low-level Mill driver.

    CubOS coordinates use the deck-origin frame at this boundary:
    front-left-bottom origin, +X operator-right, +Y back, +Z up.
    Controller GRBL settings are expected to make WPos match that frame.
    """

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        offline: bool = False,
    ) -> None:
        self.config = config or {}
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self._offline = offline
        self._offline_coords = {"x": 0.0, "y": 0.0, "z": 0.0}
        self._mill: Mill | None = None if offline else Mill()
        self._expected_grbl_settings_override: Dict[str, float] | None = None
        self._expected_grbl_settings_source: str | None = None

    @property
    def total_z_range(self) -> Optional[float]:
        """Return configured total Z range in user space, if available."""
        if isinstance(self.config, dict):
            cnc = self.config.get("cnc", {})
            if isinstance(cnc, dict) and "total_z_range" in cnc:
                return float(cnc["total_z_range"])
            working_volume = self.config.get("working_volume", {})
            if isinstance(working_volume, dict) and "z_max" in working_volume:
                return float(working_volume["z_max"])
            return None

        if hasattr(self.config, "total_z_range"):
            return float(getattr(self.config, "total_z_range"))
        return None

    def connect(self) -> None:
        """Connect to the CNC mill by auto-scanning serial ports."""
        if self._offline:
            return
        assert self._mill is not None
        try:
            self.logger.info("Connecting to gantry via auto-scan")
            self._mill.connect_to_mill(port=None)
            self._validate_grbl_settings()
            self._check_alarm_state()
        except MillConnectionError as exc:
            self.logger.error("Error connecting to gantry: %s", exc)
            raise

    def disconnect(self) -> None:
        if self._offline:
            return
        assert self._mill is not None
        try:
            self._mill.disconnect()
        except MillConnectionError as exc:
            self.logger.error("Error disconnecting gantry: %s", exc)

    def is_healthy(self) -> bool:
        """Check if the gantry is connected and healthy."""
        if self._offline:
            return True
        assert self._mill is not None
        if not self._mill.active_connection:
            self.logger.debug("Health check: no active connection")
            return False

        try:
            if not self._mill.ser_mill or not self._mill.ser_mill.is_open:
                self.logger.debug("Health check: serial port not open")
                return False

            status = self._mill.current_status()
            if "Alarm" in status or "Error" in status:
                self.logger.debug("Health check: unhealthy status: %s", status)
                return False

            return True
        except (MillConnectionError, StatusReturnError) as exc:
            self.logger.debug("Health check failed: %s", exc)
            return False

    def home(self) -> None:
        """Home the gantry using the configured homing strategy."""
        if self._offline:
            return
        assert self._mill is not None
        strategy = self._homing_strategy()
        try:
            if strategy == "standard":
                self._mill.home()
            else:
                raise ValueError(f"Unknown homing strategy: {strategy!r}")
        except (MillConnectionError, StatusReturnError) as exc:
            self.logger.error("Error homing gantry: %s", exc)
            raise

    def prepare_for_protocol_run(self) -> None:
        """Clear any startup alarm and restore controller state."""
        if self._offline:
            return
        assert self._mill is not None

        raw_status = self._mill.query_raw_status()
        if not raw_status or "alarm" not in raw_status.lower():
            return

        self.logger.warning(
            "GRBL alarm detected before protocol run; unlocking controller. "
            "Status: %s",
            raw_status,
        )
        self.reset_and_unlock()
        self._restore_controller_state()

        final_status = self._mill.query_raw_status()
        if final_status and "alarm" in final_status.lower():
            raise MillConnectionError(
                f"Gantry remained in alarm after unlock. Status: {final_status}"
            )

    def _restore_controller_state(self) -> None:
        """Re-run controller initialization skipped when connect saw Alarm."""
        if self._offline:
            return
        assert self._mill is not None

        self._mill.read_mill_config()
        self._mill.read_working_volume()
        self._mill.clear_buffers()
        status = self._mill.query_raw_status()
        if status:
            self._mill._enforce_wpos_mode()
        self._mill.set_feed_rate(DEFAULT_FEED_RATE)
        if status:
            self._mill._seed_wco()
        self._validate_grbl_settings()

    def move_to(
        self,
        x: float,
        y: float,
        z: float,
        travel_z: Optional[float] = None,
    ) -> None:
        """Move to absolute gantry coordinates.

        ``travel_z``, if given, becomes the Z during XY travel: the gantry
        lifts/lowers to it at the current XY before moving XY, then
        descends/ascends to the target Z. This is how higher layers (Board,
        protocol commands) express "travel above this labware" without the
        mill baking in a machine-wide retract.
        """
        if self._offline:
            if travel_z is not None:
                # Dry runs only record the final tip pose. Log the transit
                # height so offline protocol validation can still reason
                # about approach path (e.g. assert it stays above labware).
                self.logger.debug(
                    "Offline move to (%s, %s, %s) via travel_z=%s", x, y, z, travel_z,
                )
            self._offline_coords = {"x": x, "y": y, "z": z}
            return
        assert self._mill is not None
        try:
            machine_x, machine_y, machine_z = to_machine_coordinates(x, y, z)
            machine_travel_z = (
                to_machine_coordinates(0.0, 0.0, travel_z)[2]
                if travel_z is not None
                else None
            )
            self._mill.move_to_position(
                x_coordinate=machine_x,
                y_coordinate=machine_y,
                z_coordinate=machine_z,
                travel_z=machine_travel_z,
            )
        except (
            MillConnectionError,
            StatusReturnError,
            CommandExecutionError,
            ValueError,
        ) as exc:
            self.logger.error(
                "Error moving gantry to (%s, %s, %s): %s", x, y, z, exc
            )
            raise

    def jog(
        self,
        x: float = 0,
        y: float = 0,
        z: float = 0,
        feed_rate: float = 2000,
    ) -> None:
        """Jog by a relative gantry offset."""
        if self._offline:
            self._offline_coords = {
                "x": self._offline_coords["x"] + x,
                "y": self._offline_coords["y"] + y,
                "z": self._offline_coords["z"] + z,
            }
            return
        assert self._mill is not None
        try:
            self._mill.jog(x=x, y=y, z=z, feed_rate=feed_rate)
        except (MillConnectionError, CommandExecutionError) as exc:
            self.logger.error("Jog error: %s", exc)
            raise

    def jog_cancel(self) -> None:
        """Cancel any in-progress jog motion immediately."""
        if self._offline:
            return
        assert self._mill is not None
        try:
            self._mill.jog_cancel()
        except (MillConnectionError, CommandExecutionError) as exc:
            self.logger.error("Jog cancel error: %s", exc)
            raise

    def soft_reset(self) -> None:
        """Send a GRBL soft reset (Ctrl-X) to the controller."""
        if self._offline:
            return
        assert self._mill is not None
        try:
            self._mill.soft_reset()
        except Exception as exc:
            self.logger.error("Soft reset error: %s", exc)
            raise

    def unlock(self) -> None:
        """Send GRBL unlock command ($X) to clear alarm state."""
        if self._offline:
            return
        assert self._mill is not None
        try:
            self._mill.reset()
        except (MillConnectionError, CommandExecutionError) as exc:
            self.logger.error("Unlock error: %s", exc)
            raise

    def reset_and_unlock(self) -> None:
        """Soft reset + unlock in a single serial sequence."""
        if self._offline:
            return
        assert self._mill is not None
        try:
            self._mill.soft_reset_and_unlock()
        except (MillConnectionError, CommandExecutionError) as exc:
            self.logger.error("Reset and unlock error: %s", exc)
            raise

    def get_status(self) -> str:
        """Return the current status string with normalized coordinates."""
        if self._offline:
            return "Idle"
        assert self._mill is not None
        try:
            return translate_status_string(self._mill.current_status())
        except (MillConnectionError, StatusReturnError) as exc:
            self.logger.error("Error getting status: %s", exc)
            return "StatusQueryFailed"

    def stop(self) -> None:
        """Immediately stop all gantry motion (GRBL feed hold)."""
        if self._offline:
            return
        assert self._mill is not None
        try:
            self._mill.stop()
        except (MillConnectionError, CommandExecutionError) as exc:
            self.logger.error("Error stopping gantry: %s", exc)
            raise

    def get_coordinates(self) -> Dict[str, float]:
        """Return current gantry coordinates as a dict."""
        if self._offline:
            return dict(self._offline_coords)
        assert self._mill is not None
        coords = self._mill.current_coordinates()
        x_user, y_user, z_user = to_user_coordinates(coords.x, coords.y, coords.z)
        return {"x": x_user, "y": y_user, "z": z_user}

    def get_position_info(self) -> Dict[str, Any]:
        """Return coordinates, work position, and last-known status."""
        if self._offline:
            coords = dict(self._offline_coords)
            return {"coords": coords, "work_pos": coords, "status": "Idle"}

        assert self._mill is not None
        coords = self._mill.current_coordinates()
        x_user, y_user, z_user = to_user_coordinates(coords.x, coords.y, coords.z)
        user_coords = {"x": x_user, "y": y_user, "z": z_user}
        status = self._extract_status()
        return {
            "coords": user_coords,
            "work_pos": user_coords,
            "status": status,
        }

    def set_serial_timeout(self, timeout: float) -> None:
        """Set the serial read timeout on the active mill connection."""
        if self._offline:
            return
        assert self._mill is not None
        if self._mill.ser_mill is not None:
            self._mill.ser_mill.timeout = timeout

    def clear_g92_offsets(self) -> None:
        """Clear transient G92 offsets before assigning a durable WPos."""
        if self._offline:
            return
        assert self._mill is not None
        try:
            self._mill.execute_command("G92.1")
            self.logger.info("G92 offsets cleared")
        except (MillConnectionError, CommandExecutionError) as exc:
            self.logger.error("Error clearing G92 offsets: %s", exc)
            raise

    def enforce_work_position_reporting(self) -> None:
        """Force GRBL status reports to use WPos and absolute positioning."""
        if self._offline:
            return
        assert self._mill is not None
        try:
            self._mill._enforce_wpos_mode()
        except CommandExecutionError as exc:
            self.logger.error("Error enforcing WPos status reporting: %s", exc)
            raise

    def activate_work_coordinate_system(self, system: str = "G54") -> None:
        """Select the active GRBL work coordinate system."""
        if system not in {"G54", "G55", "G56", "G57", "G58", "G59"}:
            raise ValueError(f"Unsupported work coordinate system: {system!r}")
        if self._offline:
            return
        assert self._mill is not None
        try:
            self._mill.execute_command(system)
            self.logger.info("Activated work coordinate system %s", system)
        except (MillConnectionError, CommandExecutionError) as exc:
            self.logger.error(
                "Error activating work coordinate system %s: %s",
                system,
                exc,
            )
            raise

    def set_work_coordinates(
        self,
        x: float | None = None,
        y: float | None = None,
        z: float | None = None,
    ) -> None:
        """Assign the current physical pose to the given work coordinates."""
        if x is None and y is None and z is None:
            raise ValueError("At least one work-coordinate axis must be supplied.")
        x_work, y_work, z_work = (None, None, None)
        if x is not None or y is not None or z is not None:
            tx = 0.0 if x is None else x
            ty = 0.0 if y is None else y
            tz = 0.0 if z is None else z
            translated = to_machine_coordinates(tx, ty, tz)
            if x is not None:
                x_work = translated[0]
            if y is not None:
                y_work = translated[1]
            if z is not None:
                z_work = translated[2]
        if self._offline:
            if x_work is not None:
                self._offline_coords["x"] = x_work
            if y_work is not None:
                self._offline_coords["y"] = y_work
            if z_work is not None:
                self._offline_coords["z"] = z_work
            return
        assert self._mill is not None
        try:
            self._mill.execute_command(
                format_set_work_position_command(x_work, y_work, z_work)
            )
            self.logger.info(
                "Work coordinates set to X=%s Y=%s Z=%s",
                x_work,
                y_work,
                z_work,
            )
        except (MillConnectionError, CommandExecutionError) as exc:
            self.logger.error("Error setting work coordinates: %s", exc)
            raise

    def configure_speeds(
        self,
        homing_feed: Optional[float] = None,
        homing_seek: Optional[float] = None,
        max_rate: Optional[float] = None,
        acceleration: Optional[float] = None,
    ) -> None:
        """Apply speed and acceleration overrides to the GRBL controller."""
        if self._offline:
            return
        assert self._mill is not None
        if homing_feed is not None:
            self._mill.set_grbl_setting("24", str(homing_feed))
        if homing_seek is not None:
            self._mill.set_grbl_setting("25", str(homing_seek))
        if max_rate is not None:
            for code in ("110", "111", "112"):
                self._mill.set_grbl_setting(code, str(max_rate))
        if acceleration is not None:
            for code in ("120", "121", "122"):
                self._mill.set_grbl_setting(code, str(acceleration))
        self.logger.info("Speed config applied")

    def set_expected_grbl_settings(
        self,
        settings: Dict[str, float] | None,
        *,
        source: str = "gantry",
    ) -> None:
        """Set runtime GRBL expectations loaded from machine configuration."""
        self._expected_grbl_settings_override = dict(settings) if settings else None
        self._expected_grbl_settings_source = source if settings else None

    def read_grbl_settings(self) -> Dict[str, str]:
        """Read live GRBL settings from the connected controller."""
        if self._offline:
            return {}
        assert self._mill is not None
        return self._mill.grbl_settings()

    def set_grbl_setting(self, setting: str, value: float | int | bool) -> None:
        """Set one GRBL ``$`` setting."""
        if self._offline:
            return
        assert self._mill is not None
        code = setting[1:] if setting.startswith("$") else setting
        self._mill.set_grbl_setting(code, format_setting_value(value))

    def configure_soft_limits_from_spans(
        self,
        *,
        max_travel_x: float,
        max_travel_y: float,
        max_travel_z: float,
        tolerance_mm: float = 0.001,
    ) -> None:
        """Program GRBL soft limits from calibrated travel spans."""
        spans = {
            "$130": max_travel_x,
            "$131": max_travel_y,
            "$132": max_travel_z,
        }
        invalid = [
            f"{code}={value}"
            for code, value in spans.items()
            if float(value) <= tolerance_mm
        ]
        if invalid:
            raise ValueError(
                "Cannot configure soft limits with non-positive travel spans: "
                + ", ".join(invalid)
            )
        if self._offline:
            return

        # Disable soft limits while changing travel extents, then re-enable.
        soft_limits_disabled = False
        try:
            self.set_grbl_setting("$20", 0)
            soft_limits_disabled = True
            self.set_grbl_setting("$130", max_travel_x)
            self.set_grbl_setting("$131", max_travel_y)
            self.set_grbl_setting("$132", max_travel_z)
            self.set_grbl_setting("$22", 1)
            self.set_grbl_setting("$20", 1)
            soft_limits_disabled = False
        except Exception as exc:
            if soft_limits_disabled:
                try:
                    self.set_grbl_setting("$20", 1)
                except Exception as restore_exc:
                    raise MillConnectionError(
                        "Failed to restore GRBL soft limits after soft-limit "
                        f"programming failed. Original error: {exc}; "
                        f"restore error: {restore_exc}"
                    ) from exc
            raise

        live = self.read_grbl_settings()
        expected = {
            "$20": 1.0,
            "$22": 1.0,
            "$130": float(max_travel_x),
            "$131": float(max_travel_y),
            "$132": float(max_travel_z),
        }
        misses = []
        for code, expected_value in expected.items():
            live_raw = live.get(code)
            if live_raw is None:
                misses.append(f"{code}: missing")
                continue
            if abs(float(live_raw) - expected_value) > tolerance_mm:
                misses.append(f"{code}: expected {expected_value:g}, got {live_raw}")
        if misses:
            raise MillConnectionError(
                "GRBL soft-limit settings did not verify: " + "; ".join(misses)
            )

    def _homing_strategy(self) -> str:
        """Extract the configured homing strategy from dict or dataclass config."""
        if isinstance(self.config, dict):
            cnc = self.config.get("cnc", {})
            if isinstance(cnc, dict):
                return cnc.get("homing_strategy", "standard")
        if hasattr(self.config, "homing_strategy"):
            value = getattr(self.config, "homing_strategy")
            return getattr(value, "value", value)
        return "standard"

    def _extract_status(self) -> str:
        """Extract the GRBL state word from the last raw status string."""
        try:
            assert self._mill is not None
            raw = getattr(self._mill, "last_status", "") or ""
            if not raw:
                return "Unknown"
            match = _STATUS_RE.search(raw)
            if match:
                return match.group(1)
            if "alarm" in raw.lower():
                return "Alarm"
            return translate_status_string(raw)
        except (ValueError, AttributeError) as exc:
            self.logger.debug("Failed to extract status: %s", exc)
            return "Unknown"

    def _expected_grbl_settings(self) -> Optional[Dict[str, float]]:
        """Return expected GRBL settings normalized to $-code keys."""
        if self._expected_grbl_settings_override:
            return dict(self._expected_grbl_settings_override)

        if isinstance(self.config, dict):
            raw = self.config.get("grbl_settings")
            if not raw:
                return None
            return normalize_expected_grbl_settings(raw)

        expected = getattr(self.config, "expected_grbl_settings", None)
        return dict(expected) if expected else None

    def _validate_grbl_settings(self) -> None:
        """Compare configured GRBL expectations against the connected controller."""
        expected = self._expected_grbl_settings()
        if not expected or self._offline:
            return

        assert self._mill is not None
        live = self._mill.grbl_settings()
        mismatches = []
        for grbl_code, expected_value in expected.items():
            live_raw = live.get(grbl_code)
            if live_raw is None:
                self.logger.warning(
                    "GRBL setting %s not found on controller", grbl_code
                )
                continue
            if abs(float(live_raw) - float(expected_value)) > 0.001:
                mismatches.append((grbl_code, float(expected_value), float(live_raw)))

        if not mismatches:
            self.logger.info("GRBL settings validation passed")
            return

        critical = {
            "$3",
            "$20",
            "$22",
            "$23",
            "$100",
            "$101",
            "$102",
            "$130",
            "$131",
            "$132",
        }
        critical_mismatches = [item for item in mismatches if item[0] in critical]
        for grbl_code, expected_value, live_value in mismatches:
            self.logger.error(
                "GRBL mismatch: %s expected %.3f, controller has %.3f",
                grbl_code,
                expected_value,
                live_value,
            )
        if critical_mismatches:
            details = "; ".join(
                f"{code}: expected {expected_value}, got {live_value}"
                for code, expected_value, live_value in critical_mismatches
            )
            raise MillConnectionError(
                f"Critical GRBL settings mismatch — motion would be wrong. {details}"
            )

    def _check_alarm_state(self) -> None:
        """Log an alarm state after connect without raising."""
        if self._offline:
            return
        assert self._mill is not None
        raw = self._mill.query_raw_status()
        if raw and "Alarm" in raw:
            self.logger.warning(
                "GRBL is in Alarm state after connect. Home to clear. Status: %s",
                raw,
            )
