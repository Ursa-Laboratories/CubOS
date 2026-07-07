from __future__ import annotations

import math
import statistics
import time
from typing import Optional

from instruments.asmi.interface import ASMIInstrument
from instruments.asmi.exceptions import (
    ASMICommandError,
    ASMIConnectionError,
)
from instruments.asmi.models import ASMIStatus, MeasurementResult

_DEFAULT_FORCE_THRESHOLD = -100
_DEFAULT_SENSOR_CHANNELS = [1]
_STEP_COUNT_SAFETY_MARGIN = 10


def _step_count_bound(z_upper: float, z_lower: float, step_size: float) -> int:
    """Upper bound on steps needed to cross [z_lower, z_upper] at step_size.

    Ceil-based so that a non-integer number of steps still reaches the
    clamped endpoint. Used as a loop-iteration cap to guarantee termination
    if hardware stalls or rounding otherwise prevents the geometric exit
    condition from firing, and — in offline mode — as the actual step count.
    """
    if step_size <= 0:
        raise ValueError(f"step_size must be positive, got {step_size}")
    span = abs(z_upper - z_lower)
    raw_steps = math.ceil(span / step_size) if span > 0 else 0
    return raw_steps + _STEP_COUNT_SAFETY_MARGIN


class VernierASMI(ASMIInstrument):
    """Driver for the ASMI force sensor (Vernier GoDirect).

    Connects to a GoDirect force sensor over USB and provides force
    measurements.  All positioning is handled by the instrumented gantry.

    Pass ``offline=True`` for dry runs and testing — no USB connection,
    all readings return ``default_force``.
    """

    def __init__(
        self,
        name: Optional[str] = None,
        offset_x: float = 0.0,
        offset_y: float = 0.0,
        depth: float = 0.0,
        offline: bool = False,  # passed through to BaseInstrument
        default_force: float = 0.0,
        force_threshold: float = _DEFAULT_FORCE_THRESHOLD,
        sensor_channels: Optional[list[int]] = None,
        step_size: float = 0.01,
        force_limit: float = 15.0,
        baseline_samples: int = 10,
        idle_timeout: float = 10.0,
    ):
        super().__init__(
            name=name, offset_x=offset_x, offset_y=offset_y,
            depth=depth, offline=offline,
        )
        self._default_force = default_force
        self._force_threshold = force_threshold
        self._sensor_channels = sensor_channels or list(_DEFAULT_SENSOR_CHANNELS)
        self._step_size = step_size
        self._force_limit = force_limit
        self._baseline_samples = baseline_samples
        self._idle_timeout = idle_timeout
        self._godirect = None
        self._device = None
        self._sensor = None

    # ── BaseInstrument interface ──────────────────────────────────────────

    def connect(self) -> None:
        if self._offline:
            self.logger.info("ASMI connected (offline)")
            return
        try:
            from godirect import GoDirect
        except ImportError as exc:
            raise ASMIConnectionError(
                "godirect package required: pip install godirect"
            ) from exc

        try:
            self._godirect = GoDirect(use_ble=False, use_usb=True)
            device = self._godirect.get_device(threshold=self._force_threshold)
            if device is None:
                raise ASMIConnectionError(
                    "No GoDirect force sensor found. Check USB connection."
                )
            if not device.open(auto_start=False):
                raise ASMIConnectionError("Failed to open GoDirect device")

            device.enable_sensors(self._sensor_channels)
            sensors = device.get_enabled_sensors()
        except ASMIConnectionError:
            raise
        except Exception as exc:
            raise ASMIConnectionError(f"GoDirect connection failed: {exc}") from exc
        if not sensors:
            device.close()
            raise ASMIConnectionError("No sensors enabled on GoDirect device")

        self._device = device
        self._sensor = sensors[0]
        self.logger.info(
            "Connected to force sensor: %s", self._sensor.sensor_description
        )

    def disconnect(self) -> None:
        if self._offline:
            self.logger.info("ASMI disconnected (offline)")
            return
        if self._device is not None:
            try:
                self._device.close()
            except Exception:
                pass
            self._device = None
            self._sensor = None
        if self._godirect is not None:
            try:
                self._godirect.quit()
            except Exception:
                pass
            self._godirect = None
        self.logger.info("ASMI force sensor disconnected")

    def health_check(self) -> bool:
        if self._offline:
            return True
        if self._device is None or self._sensor is None:
            return False
        try:
            self.measure()
            return True
        except Exception:
            return False

    # ── ASMI-specific commands ────────────────────────────────────────────

    def measure(self, n_samples: int = 1) -> MeasurementResult:
        """Take one or more force readings and return the result."""
        if self._offline:
            readings = tuple(self._default_force for _ in range(n_samples))
            return MeasurementResult(
                readings=readings,
                mean_n=self._default_force,
                std_n=0.0,
                timestamp=time.time(),
            )

        if self._device is None or self._sensor is None:
            raise ASMICommandError("Force sensor not connected")

        readings: list[float] = []
        for _ in range(n_samples):
            self._device.start()
            try:
                if not self._device.read():
                    raise ASMICommandError("GoDirect force sensor read failed")
                value = self._sensor.values[0]
                self._sensor.clear()
            except ASMICommandError:
                raise
            except Exception as exc:
                raise ASMICommandError(f"GoDirect force sensor read failed: {exc}") from exc
            finally:
                self._device.stop()
            readings.append(value)

        mean = statistics.mean(readings)
        std = statistics.stdev(readings) if len(readings) > 1 else 0.0
        return MeasurementResult(
            readings=tuple(readings),
            mean_n=mean,
            std_n=std,
            timestamp=time.time(),
        )

    def get_status(self) -> ASMIStatus:
        """Return a snapshot of the sensor state."""
        if self._offline:
            return ASMIStatus(
                is_connected=True,
                sensor_description="OfflineSensor",
            )
        description = None
        if self._sensor is not None:
            try:
                description = self._sensor.sensor_description
            except Exception:
                pass
        return ASMIStatus(
            is_connected=self._device is not None and self._sensor is not None,
            sensor_description=description,
        )

    # ── Convenience methods ───────────────────────────────────────────────

    def get_force_reading(self) -> float:
        """Take a single force reading and return the value in Newtons."""
        return self.measure(n_samples=1).mean_n

    def get_baseline_force(self, samples: int = 10) -> tuple[float, float]:
        """Collect multiple force readings and return (mean, std) in Newtons."""
        result = self.measure(n_samples=samples)
        return (result.mean_n, result.std_n)

    def is_connected(self) -> bool:
        """Check if the force sensor is connected and operational."""
        if self._offline:
            return True
        return self._device is not None and self._sensor is not None

    # ── Indentation measurement ───────────────────────────────────────────

    def _wait_for_idle(self, gantry) -> bool:
        start = time.time()
        while time.time() - start < self._idle_timeout:
            if "Idle" in gantry.get_status():
                return True
            time.sleep(0.02)
        return False

    def _move_z(self, gantry, x, y, z):
        gantry.move_to(x, y, z)
        if not self._wait_for_idle(gantry):
            raise ASMICommandError(
                f"Gantry did not become Idle within {self._idle_timeout:.2f}s "
                f"after ASMI Z move to {z}."
            )

    @staticmethod
    def _validate_indentation_parameters(
        measurement_height: float,
        indentation_limit_height: float,
        step_size: float,
    ) -> None:
        """Validate indentation parameters.

        ``measurement_height`` and ``indentation_limit_height`` are
        labware-relative offsets (mm above the well surface; +above,
        -below). ``indentation_limit_height`` must be at or below
        ``measurement_height``; equality is legal (a zero-descent
        indentation collects baseline force samples and returns) and
        matches the inclusive ``≤`` spec used by the engine and
        validator.
        """
        if step_size <= 0:
            raise ValueError(f"step_size must be positive, got {step_size}")
        if indentation_limit_height > measurement_height:
            raise ValueError(
                f"indentation_limit_height ({indentation_limit_height}) "
                f"must be at or below measurement_height "
                f"({measurement_height}) — indentation descends in -Z."
            )

    def indentation(
        self,
        gantry,
        *,
        measurement_height: float,
        indentation_limit_height: float,
        well_z: float,
        step_size: float | None = None,
        force_limit: float | None = None,
        baseline_samples: int | None = None,
        measure_with_return: bool = False,
    ) -> dict:
        """Perform step-by-step indentation at the current XY position.

        Z inputs are labware-relative offsets resolved against ``well_z``.
        Descent decreases deck-frame Z; optional return samples increase Z
        back to the action plane. Every measurement is tagged with direction.
        """
        _step_size, _force_limit, _baseline_samples = (
            self._resolve_indentation_settings(
                step_size=step_size,
                force_limit=force_limit,
                baseline_samples=baseline_samples,
            )
        )
        self._validate_indentation_parameters(
            measurement_height, indentation_limit_height, _step_size,
        )
        action_z, target_z = self._resolve_indentation_z_targets(
            well_z=well_z,
            measurement_height=measurement_height,
            indentation_limit_height=indentation_limit_height,
        )

        if self._offline:
            return self._offline_indentation(
                gantry,
                target_z,
                _step_size,
                action_z,
                _force_limit,
                measure_with_return=measure_with_return,
            )

        cur_x, cur_y = self._move_to_indentation_start(
            gantry,
            action_z=action_z,
        )
        baseline_avg, baseline_std = self._collect_indentation_baseline(
            baseline_samples=_baseline_samples,
        )
        measurements, force_exceeded = self._run_indentation_descent(
            gantry,
            cur_x=cur_x,
            cur_y=cur_y,
            action_z=action_z,
            target_z=target_z,
            step_size=_step_size,
            force_limit=_force_limit,
            baseline_avg=baseline_avg,
        )

        if measure_with_return and measurements:
            self._run_indentation_return(
                gantry,
                cur_x=cur_x,
                cur_y=cur_y,
                action_z=action_z,
                target_z=target_z,
                step_size=_step_size,
                baseline_avg=baseline_avg,
                measurements=measurements,
            )

        return self._indentation_result(
            measurements=measurements,
            baseline_avg=baseline_avg,
            baseline_std=baseline_std,
            force_exceeded=force_exceeded,
            measure_with_return=measure_with_return,
            step_size_mm=_step_size,
            z_target_mm=target_z,
            force_limit_n=_force_limit,
        )

    def _resolve_indentation_settings(
        self,
        *,
        step_size: float | None,
        force_limit: float | None,
        baseline_samples: int | None,
    ) -> tuple[float, float, int]:
        resolved_step_size = step_size if step_size is not None else self._step_size
        resolved_force_limit = (
            force_limit if force_limit is not None else self._force_limit
        )
        resolved_baseline_samples = (
            baseline_samples
            if baseline_samples is not None
            else self._baseline_samples
        )
        return resolved_step_size, resolved_force_limit, resolved_baseline_samples

    @staticmethod
    def _resolve_indentation_z_targets(
        *,
        well_z: float,
        measurement_height: float,
        indentation_limit_height: float,
    ) -> tuple[float, float]:
        action_z = well_z + measurement_height
        target_z = well_z + indentation_limit_height
        return action_z, target_z

    def _move_to_indentation_start(
        self,
        gantry,
        *,
        action_z: float,
    ) -> tuple[float, float]:
        coords = gantry.get_coordinates()
        cur_x, cur_y = coords["x"], coords["y"]
        self._move_z(gantry, cur_x, cur_y, action_z)
        return cur_x, cur_y

    def _collect_indentation_baseline(
        self,
        *,
        baseline_samples: int,
    ) -> tuple[float, float]:
        baseline_avg, baseline_std = self.get_baseline_force(
            samples=baseline_samples
        )
        self.logger.info(
            "Baseline: %.3f +/- %.3f N", baseline_avg, baseline_std
        )
        return baseline_avg, baseline_std

    @staticmethod
    def _measurement_point(
        *,
        z_mm: float,
        raw_force_n: float,
        corrected_force_n: float,
        direction: str,
    ) -> dict:
        return {
            "timestamp": time.time(),
            "z_mm": z_mm,
            "raw_force_n": raw_force_n,
            "corrected_force_n": corrected_force_n,
            "direction": direction,
        }

    def _record_force_at_z(
        self,
        *,
        z_mm: float,
        baseline_avg: float,
        direction: str,
    ) -> tuple[dict, float, float]:
        force = self.get_force_reading()
        corrected = force - baseline_avg
        return (
            self._measurement_point(
                z_mm=z_mm,
                raw_force_n=force,
                corrected_force_n=corrected,
                direction=direction,
            ),
            force,
            corrected,
        )

    def _run_indentation_descent(
        self,
        gantry,
        *,
        cur_x: float,
        cur_y: float,
        action_z: float,
        target_z: float,
        step_size: float,
        force_limit: float,
        baseline_avg: float,
    ) -> tuple[list[dict], bool]:
        measurements: list[dict] = []
        force_exceeded = False
        max_steps = _step_count_bound(action_z, target_z, step_size)

        # Deck-origin +Z-up: descent decreases Z toward the deck.
        for _ in range(max_steps):
            coords = gantry.get_coordinates()
            current_z = coords["z"]
            if current_z <= target_z:
                self.logger.info("Reached target_z %.3f mm", target_z)
                break

            next_z = max(current_z - step_size, target_z)
            self._move_z(gantry, cur_x, cur_y, next_z)
            coords = gantry.get_coordinates()
            point, force, corrected = self._record_force_at_z(
                z_mm=coords["z"],
                baseline_avg=baseline_avg,
                direction="down",
            )
            measurements.append(point)

            if len(measurements) % 10 == 0:
                self.logger.info(
                    "Step #%d: Z=%.3f mm, F=%.3f N, dF=%.3f N",
                    len(measurements), point["z_mm"], force, corrected,
                )

            if abs(corrected) > force_limit:
                self.logger.info(
                    "Force limit exceeded: %.3f N > %.1f N",
                    corrected, force_limit,
                )
                force_exceeded = True
                break
        else:
            self.logger.warning(
                "Descent hit iteration cap %d before reaching target_z %.3f",
                max_steps, target_z,
            )

        return measurements, force_exceeded

    def _run_indentation_return(
        self,
        gantry,
        *,
        cur_x: float,
        cur_y: float,
        action_z: float,
        target_z: float,
        step_size: float,
        baseline_avg: float,
        measurements: list[dict],
    ) -> None:
        self.logger.info(
            "Starting return sweep (%d descent samples collected)",
            len(measurements),
        )
        return_cap = _step_count_bound(action_z, target_z, step_size)

        # Deck-origin +Z-up: return increases Z back to the action plane.
        for _ in range(return_cap):
            coords = gantry.get_coordinates()
            current_z = coords["z"]
            if current_z >= action_z:
                break

            next_z = min(current_z + step_size, action_z)
            self._move_z(gantry, cur_x, cur_y, next_z)
            coords = gantry.get_coordinates()
            if coords["z"] <= current_z:
                self.logger.warning(
                    "Return sweep aborted: gantry Z did not retract (%.3f)",
                    current_z,
                )
                break

            point, _, _ = self._record_force_at_z(
                z_mm=coords["z"],
                baseline_avg=baseline_avg,
                direction="up",
            )
            measurements.append(point)
        else:
            self.logger.warning(
                "Return sweep hit iteration cap %d before reaching action_z %.3f",
                return_cap, action_z,
            )

    @staticmethod
    def _indentation_result(
        *,
        measurements: list[dict],
        baseline_avg: float,
        baseline_std: float,
        force_exceeded: bool,
        measure_with_return: bool,
        step_size_mm: float,
        z_target_mm: float,
        force_limit_n: float,
    ) -> dict:
        return {
            "measurements": measurements,
            "baseline_avg": baseline_avg,
            "baseline_std": baseline_std,
            "force_exceeded": force_exceeded,
            "data_points": len(measurements),
            "measure_with_return": measure_with_return,
            "step_size_mm": step_size_mm,
            "z_target_mm": z_target_mm,
            "force_limit_n": force_limit_n,
        }

    def _offline_indentation(
        self,
        gantry,
        target_z,
        step_size,
        action_z,
        force_limit,
        measure_with_return: bool = False,
    ) -> dict:
        """Fast offline indentation — no idle-wait, synthetic data.

        Deck-origin +Z-up convention: descent DECREASES z toward
        ``target_z`` (which is at or below ``action_z``); the optional
        return sweep walks z back UP to ``action_z``. Both parameters are
        absolute deck-frame Z, resolved by the public ``indentation()``
        method from the labware-relative offsets it receives.
        """
        coords = gantry.get_coordinates()
        cur_x, cur_y = coords["x"], coords["y"]
        gantry.move_to(cur_x, cur_y, action_z)

        # Integer step counting avoids float accumulation drift at loop boundaries.
        n_down = _step_count_bound(
            action_z, target_z, step_size,
        ) - _STEP_COUNT_SAFETY_MARGIN
        measurements = []
        for i in range(1, n_down + 1):
            z = max(action_z - i * step_size, target_z)
            gantry.move_to(cur_x, cur_y, z)
            measurements.append({
                "timestamp": time.time(),
                "z_mm": z,
                "raw_force_n": self._default_force,
                "corrected_force_n": 0.0,
                "direction": "down",
            })
            if z <= target_z:
                break

        if measure_with_return:
            z_bottom = measurements[-1]["z_mm"] if measurements else action_z
            n_up = _step_count_bound(action_z, z_bottom, step_size) - _STEP_COUNT_SAFETY_MARGIN
            for i in range(1, n_up + 1):
                z = min(z_bottom + i * step_size, action_z)
                gantry.move_to(cur_x, cur_y, z)
                measurements.append({
                    "timestamp": time.time(),
                    "z_mm": z,
                    "raw_force_n": self._default_force,
                    "corrected_force_n": 0.0,
                    "direction": "up",
                })
                if z >= action_z:
                    break

        return {
            "measurements": measurements,
            "baseline_avg": self._default_force,
            "baseline_std": 0.0,
            "force_exceeded": False,
            "data_points": len(measurements),
            "measure_with_return": measure_with_return,
            "step_size_mm": step_size,
            "z_target_mm": target_z,
            "force_limit_n": force_limit,
        }
