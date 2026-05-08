"""Single-instrument gantry calibration flow.

Internal implementation used by the sole user-facing entrypoint:
``setup/calibrate_gantry.py``.
"""

from __future__ import annotations

import copy
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

import yaml

project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

from gantry import Gantry, load_gantry_from_yaml  # noqa: E402
from gantry.gantry_driver.exceptions import (  # noqa: E402
    CommandExecutionError,
    MillConnectionError,
    StatusReturnError,
)
from gantry.origin import (  # noqa: E402
    DeckOriginCalibrationPlan,
    build_deck_origin_calibration_plan,
)
from setup.keyboard_input import flush_stdin, read_keypress_batch  # noqa: E402


@dataclass(frozen=True)
class DeckOriginCalibrationResult:
    """Result of one-instrument deck-origin calibration."""

    measured_working_volume: tuple[float, float, float]
    xy_origin_verification: tuple[float, float, float]
    z_reference_verification: tuple[float, float, float]
    z_min_mm: float
    z_reference_mode: str
    reachable_z_min_mm: float | None
    grbl_max_travel: tuple[float, float, float] | None
    instrument_name: str | None
    plan: DeckOriginCalibrationPlan

    @property
    def reference_verification(self) -> tuple[float, float, float]:
        """Backward-compatible alias for the final Z-reference verification."""
        return self.z_reference_verification

    @property
    def reference_surface_z_mm(self) -> float:
        """Deprecated alias for the one-instrument lower Z assignment."""
        return self.z_min_mm


class _GantryLike(Protocol):
    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    def home(self) -> None: ...
    def enforce_work_position_reporting(self) -> None: ...
    def activate_work_coordinate_system(self, system: str = "G54") -> None: ...
    def clear_g92_offsets(self) -> None: ...
    def set_work_coordinates(
        self,
        x: float | None = None,
        y: float | None = None,
        z: float | None = None,
    ) -> None: ...
    def get_coordinates(self) -> dict[str, float]: ...
    def get_status(self) -> str: ...
    def jog(
        self,
        x: float = 0,
        y: float = 0,
        z: float = 0,
        feed_rate: float = 2000,
    ) -> None: ...
    def jog_cancel(self) -> None: ...
    def stop(self) -> None: ...
    def unlock(self) -> None: ...
    def reset_and_unlock(self) -> None: ...
    def configure_soft_limits_from_spans(
        self,
        *,
        max_travel_x: float,
        max_travel_y: float,
        max_travel_z: float,
        tolerance_mm: float = 0.001,
    ) -> None: ...


KeyReader = Callable[[], tuple[str, int]]


CONTROLS_LEGEND = """
Jog controls after homing:
  RIGHT / LEFT       +X right / -X left
  UP / DOWN          +Y back-away / -Y front-toward-operator
  X / Z              +Z up / -Z down
  1 / 2 / 3 / 4 / 5 / 6 / 7
                      Set jog step to 0.1 / 1 / 5 / 10 / 25 / 50 / 100 mm
  SPACE              Cancel any active jog
  ENTER              Confirm the current calibration step
  Q                  Abort calibration
"""


def _load_raw_config(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    if not isinstance(config, dict):
        raise ValueError(f"Gantry config is empty or invalid: {path}")
    return config


def _coords_tuple(coords: dict[str, float]) -> tuple[float, float, float]:
    return (float(coords["x"]), float(coords["y"]), float(coords["z"]))


def _round_mm(value: float) -> float:
    return round(float(value), 3)


def _calculate_grbl_max_travel(
    measured_coords: dict[str, float],
    *,
    z_min_mm: float,
    tolerance_mm: float,
) -> dict[str, float]:
    x_span = _round_mm(float(measured_coords["x"]))
    y_span = _round_mm(float(measured_coords["y"]))
    z_span = _round_mm(float(measured_coords["z"]) - float(z_min_mm))
    spans = {
        "max_travel_x": x_span,
        "max_travel_y": y_span,
        "max_travel_z": z_span,
    }
    invalid = [f"{key}={value}" for key, value in spans.items() if value <= tolerance_mm]
    if invalid:
        raise RuntimeError(
            "Measured travel span is not positive enough for GRBL soft limits: "
            + ", ".join(invalid)
        )
    return spans


def _assert_near_xyz(
    coords: dict[str, float],
    *,
    expected: dict[str, float],
    tolerance_mm: float,
    label: str,
) -> None:
    misses = [
        f"{axis}: got {float(coords[axis]):.4f}, expected {float(expected[axis]):.4f}"
        for axis in ("x", "y", "z")
        if abs(float(coords[axis]) - float(expected[axis])) > tolerance_mm
    ]
    if misses:
        raise RuntimeError(
            f"{label} did not verify within {tolerance_mm} mm: "
            + "; ".join(misses)
        )


def _updated_gantry_yaml_text(
    raw_config: dict[str, Any],
    *,
    measured_coords: dict[str, float],
    z_min_mm: float,
    max_travel: dict[str, float] | None = None,
) -> str:
    updated = copy.deepcopy(raw_config)
    updated.setdefault("cnc", {})["total_z_range"] = _round_mm(measured_coords["z"])
    updated["working_volume"] = {
        "x_min": 0.0,
        "x_max": _round_mm(measured_coords["x"]),
        "y_min": 0.0,
        "y_max": _round_mm(measured_coords["y"]),
        "z_min": _round_mm(z_min_mm),
        "z_max": _round_mm(measured_coords["z"]),
    }
    if max_travel is not None:
        updated["grbl_settings"] = _build_gantry_grbl_settings(
            gantry_raw=raw_config,
            max_travel=max_travel,
        )
    return yaml.safe_dump(updated, sort_keys=False)


def _build_gantry_grbl_settings(
    *,
    gantry_raw: dict[str, Any],
    max_travel: dict[str, float],
) -> dict[str, Any]:
    settings = dict(gantry_raw.get("grbl_settings") or {})
    settings.update(
        {
            "status_report": 0,
            "soft_limits": True,
            "homing_enable": True,
            "max_travel_x": max_travel["max_travel_x"],
            "max_travel_y": max_travel["max_travel_y"],
            "max_travel_z": max_travel["max_travel_z"],
        }
    )
    return settings


def _print_yaml_block(
    *,
    title: str,
    yaml_text: str,
    output: Callable[[str], None],
) -> None:
    output("")
    output(title)
    output("```yaml")
    for line in yaml_text.rstrip().splitlines():
        output(line)
    output("```")


def _maybe_write_gantry_yaml(
    *,
    yaml_text: str,
    output_path: Path | None,
    write_requested: bool,
    input_reader: Callable[[str], str],
    output: Callable[[str], None],
) -> None:
    if output_path is None and not write_requested:
        return
    explicit_output_path = output_path is not None
    if output_path is None:
        raw = input_reader("Output gantry YAML filename: ").strip()
        if not raw:
            output("No gantry YAML filename supplied; skipping write.")
            return
        output_path = Path(raw)
    if not explicit_output_path:
        confirm = input_reader(
            f"Write updated gantry YAML to {output_path}? [y/N]: "
        ).strip().lower()
        if confirm not in ("y", "yes"):
            output("Skipping gantry YAML write.")
            return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(yaml_text, encoding="utf-8")
    output(f"Wrote updated gantry YAML: {output_path}")


def _assert_near_xy_origin(
    coords: dict[str, float],
    *,
    tolerance_mm: float,
) -> None:
    expected = {
        "x": 0.0,
        "y": 0.0,
    }
    misses = [
        f"{axis}: got {float(coords[axis]):.4f}, expected {expected[axis]:.4f}"
        for axis in ("x", "y")
        if abs(float(coords[axis]) - expected[axis]) > tolerance_mm
    ]
    if misses:
        raise RuntimeError(
            "Deck-origin XY reference did not verify within "
            f"{tolerance_mm} mm: " + "; ".join(misses)
        )


def _assert_near_z_reference(
    coords: dict[str, float],
    *,
    z_min_mm: float,
    tolerance_mm: float,
) -> None:
    expected = {"z": z_min_mm}
    misses = [
        f"{axis}: got {float(coords[axis]):.4f}, expected {expected[axis]:.4f}"
        for axis in ("z",)
        if abs(float(coords[axis]) - expected[axis]) > tolerance_mm
    ]
    if misses:
        raise RuntimeError(
            "Deck-origin Z reference did not verify within "
            f"{tolerance_mm} mm: " + "; ".join(misses)
        )


def _assert_positive_measured_volume(
    coords: dict[str, float],
    *,
    tolerance_mm: float,
) -> None:
    misses = [
        f"{axis}: got {float(coords[axis]):.4f}"
        for axis in ("x", "y", "z")
        if float(coords[axis]) <= tolerance_mm
    ]
    if misses:
        raise RuntimeError(
            "Measured homed WPos did not look like positive working-volume "
            "maxima: " + "; ".join(misses)
        )


def _print_config_patch(
    coords: dict[str, float],
    *,
    z_reference_coords: dict[str, float],
    z_min_mm: float,
    z_reference_mode: str,
    instrument_name: str | None,
    output: Callable[[str], None],
) -> None:
    x_max, y_max, z_max = _coords_tuple(coords)
    output("")
    output("Measured physical working volume from calibrated origin:")
    output(f"  X: 0.000 to {x_max:.3f} mm")
    output(f"  Y: 0.000 to {y_max:.3f} mm")
    output(f"  Z: {z_min_mm:.3f} to {z_max:.3f} mm")
    output("")
    output("Update the gantry YAML working_volume to:")
    output("  working_volume:")
    output("    x_min: 0.0")
    output(f"    x_max: {x_max:.3f}")
    output("    y_min: 0.0")
    output(f"    y_max: {y_max:.3f}")
    output(f"    z_min: {z_min_mm:.3f}")
    output(f"    z_max: {z_max:.3f}")
    output("")
    output("Also set cnc.total_z_range to:")
    output(f"  total_z_range: {z_max:.3f}")
    output("")
    output("Z reference point after XY origining:")
    output(
        "  WPos "
        f"X={z_reference_coords['x']:.3f} "
        f"Y={z_reference_coords['y']:.3f} "
        f"Z={z_reference_coords['z']:.3f}"
    )
    output(f"  mode: {z_reference_mode}")
    if z_min_mm > 0:
        reach_name = instrument_name or "reference_tcp"
        output("")
        output(
            "This one-instrument config starts above physical deck bottom "
            "because the TCP cannot reach Z=0."
        )
        output(f"  {reach_name}_reachable_z_min: {z_min_mm:.3f} mm")
        output(
            "For a future multi-instrument config, keep one shared deck frame "
            "and encode this as a per-instrument lower-reach limit instead of "
            "using one global z_min for every tool."
        )


def _print_dry_run(
    gantry_path: Path,
    plan: DeckOriginCalibrationPlan,
    *,
    tip_gap_mm: float | None,
    z_reference_mode: str,
    instrument_name: str | None,
    output: Callable[[str], None],
) -> None:
    output(f"Loaded deck-origin gantry config: {gantry_path}")
    if instrument_name:
        output(f"Instrument/TCP: {instrument_name}")
    output(f"Z reference mode: {z_reference_mode}")
    output("Dry run only. Physical calibration flow:")
    commands = _commands_for_z_min(
        plan,
        tip_gap_mm,
        z_reference_mode=z_reference_mode,
    )
    for command in commands:
        output(f"  {command}")
    output("")
    output("No configured max travel values will be trusted as measured volume.")


def _commands_for_z_min(
    plan: DeckOriginCalibrationPlan,
    tip_gap_mm: float | None,
    *,
    z_reference_mode: str = "ruler-gap",
) -> tuple[str, ...]:
    z_value = (
        "0"
        if z_reference_mode == "bottom"
        else ("<tip_gap_mm>" if tip_gap_mm is None else f"{tip_gap_mm:g}")
    )
    confirmation = "<confirm true deck-bottom contact>"
    if z_reference_mode in ("prompt", "ruler-gap", "known-height"):
        confirmation = "<confirm bottom contact or enter ruler-measured TCP gap>"
    return tuple(
        command.replace("<z_min_mm>", z_value).replace(
            "<confirm deck-bottom contact or enter ruler-measured TCP gap>",
            confirmation,
        )
        for command in plan.commands
    )


def _prompt_tip_gap_mm(
    *,
    input_reader: Callable[[str], str],
    output: Callable[[str], None],
) -> float:
    output("")
    output(
        "This TCP is not touching true deck bottom at its lower reach point."
    )
    output(
        "Measure the vertical gap from the deck surface to the TCP with a "
        "ruler, then enter that gap in millimeters."
    )
    while True:
        raw = input_reader("Deck-to-TCP gap in mm: ").strip()
        try:
            value = float(raw)
        except ValueError:
            output("Enter a numeric gap in millimeters.")
            continue
        if value <= 0:
            output("Deck-to-TCP gap must be > 0 mm. Use bottom mode for Z=0.")
            continue
        return value


def _prompt_block_height(
    *,
    input_reader: Callable[[str], str],
    output: Callable[[str], None],
) -> float:
    output("")
    output("Z reference: use a calibration block. The instrument should touch the block top.")
    while True:
        raw = input_reader("Calibration block height in mm: ").strip()
        try:
            value = float(raw)
        except ValueError:
            output("Enter a numeric block height in millimeters.")
            continue
        if value <= 0:
            output("Calibration block height must be > 0 mm.")
            continue
        return value


def _prompt_z_reference_mode(
    *,
    input_reader: Callable[[str], str],
    output: Callable[[str], None],
) -> str:
    output("")
    output("Z grounding mode:")
    output("  y = this TCP is touching true deck bottom, so set Z=0 here")
    output("  n = no/unsure; measure the deck-to-TCP gap with a ruler")
    while True:
        raw = input_reader(
            "Is the TCP touching true deck bottom at the current pose? [y/N]: "
        ).strip().lower()
        if raw in ("", "n", "no", "u", "unsure"):
            return "ruler-gap"
        if raw in ("y", "yes"):
            return "bottom"
        output("Enter y for true-bottom contact, or n/Enter for ruler-gap mode.")


def _set_serial_timeout_if_available(
    gantry: _GantryLike,
    timeout_s: float,
) -> None:
    setter = getattr(gantry, "set_serial_timeout", None)
    if callable(setter):
        setter(timeout_s)


def _looks_like_limit_alarm(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(
        token in message
        for token in (
            "alarm",
            "check limits",
            "hard limit",
            "limit",
            "pn:",
            "error:9",
        )
    )


def _looks_like_soft_limit_jog_rejection(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(
        token in message
        for token in (
            "error:15",
            "travel exceeded",
            "jog target exceeds machine travel",
        )
    )


def _soft_limits_enabled_from_settings(settings: object) -> bool | None:
    if not isinstance(settings, dict):
        return None
    value = settings.get("$20")
    if value is None:
        value = settings.get("20")
    if value is None:
        return None
    try:
        return float(value) != 0.0
    except (TypeError, ValueError):
        return None


def _read_soft_limits_enabled_if_available(
    gantry: _GantryLike,
    *,
    output: Callable[[str], None],
) -> bool | None:
    reader = getattr(gantry, "read_grbl_settings", None)
    if not callable(reader):
        return None
    try:
        return _soft_limits_enabled_from_settings(reader())
    except MillConnectionError:
        raise
    except (CommandExecutionError, StatusReturnError, ValueError) as exc:
        output(f"Could not read GRBL soft-limit state before jogging: {exc}")
        output("Continuing; any GRBL error:15 jog rejection will be handled in-place.")
        return None


def _set_soft_limits_enabled_if_available(
    gantry: _GantryLike,
    enabled: bool,
) -> bool:
    setter = getattr(gantry, "set_grbl_setting", None)
    if not callable(setter):
        return False
    setter("$20", 1 if enabled else 0)
    return True


def _temporarily_disable_soft_limits_for_origin_jog(
    gantry: _GantryLike,
    *,
    output: Callable[[str], None],
) -> bool:
    enabled = _read_soft_limits_enabled_if_available(gantry, output=output)
    if enabled is not True:
        return False
    output(
        "Temporarily disabling GRBL soft limits ($20=0) for the interactive "
        "origin jog so stale travel settings cannot block calibration."
    )
    output("Jog cautiously; this does not change the hard-limit setting.")
    if not _set_soft_limits_enabled_if_available(gantry, False):
        output("No GRBL setting writer is available; leaving soft limits unchanged.")
        return False
    return True


def _restore_soft_limits_after_origin_jog(
    gantry: _GantryLike,
    *,
    output: Callable[[str], None],
) -> None:
    output("Restoring GRBL soft limits ($20=1) after interactive origin jog.")
    if not _set_soft_limits_enabled_if_available(gantry, True):
        raise MillConnectionError(
            "Cannot restore GRBL soft limits because this gantry object has no "
            "setting writer."
        )


def _opposite_pull_off_delta(
    delta: dict[str, float],
    pull_off_mm: float,
) -> dict[str, float]:
    pull_off = {"x": 0.0, "y": 0.0, "z": 0.0}
    for axis, value in delta.items():
        if value == 0:
            continue
        if value > 0:
            pull_off[axis] = -pull_off_mm
        else:
            pull_off[axis] = pull_off_mm
    return pull_off


def _soft_reset_and_unlock_after_limit_alarm(
    gantry: _GantryLike,
    *,
    output: Callable[[str], None],
) -> None:
    reset_and_unlock = getattr(gantry, "reset_and_unlock", None)
    if not callable(reset_and_unlock):
        raise CommandExecutionError(
            "Limit recovery requires gantry.reset_and_unlock() so GRBL gets "
            "a soft reset (Ctrl-X) before $X unlock."
        )
    try:
        output("Soft-resetting GRBL, then unlocking before pull-off.")
        reset_and_unlock()
    except MillConnectionError:
        raise
    except (CommandExecutionError, StatusReturnError) as exc:
        output(f"Soft reset/unlock during limit recovery failed: {exc}")
        output("Use the controller/E-stop reset path before continuing.")
        raise


def _raise_if_limit_status(status: str) -> None:
    lower_status = status.lower()
    if "alarm" in lower_status:
        raise StatusReturnError(f"Alarm in status: {status}")
    # GRBL reports active limit pins as Pn:X, Pn:Y, Pn:Z (possibly combined).
    # Treat that as a limit condition during manual calibration so the operator
    # gets an immediate pull-off instead of discovering it on the next jog.
    if "pn:" in lower_status:
        pin_text = lower_status.split("pn:", 1)[1].split("|", 1)[0].split(">", 1)[0]
        if any(axis in pin_text for axis in ("x", "y", "z")):
            raise StatusReturnError(f"Limit pin active in status: {status}")


def _probe_for_limit_status_after_jog(gantry: _GantryLike) -> None:
    get_status = getattr(gantry, "get_status", None)
    if not callable(get_status):
        return
    time.sleep(0.05)
    _raise_if_limit_status(str(get_status()))


def _read_limit_recovery_status(gantry: _GantryLike) -> str | None:
    get_status = getattr(gantry, "get_status", None)
    if not callable(get_status):
        return None
    try:
        return str(get_status())
    except Exception:
        return None


def _needs_another_limit_pull_off(status: str | None) -> bool:
    if status is None:
        return False
    lower = status.lower()
    return any(
        token in lower
        for token in (
            "alarm",
            "reset to continue",
            "hard limit",
            "limit",
            "pn:",
            "statusqueryfailed",
            "failed",
        )
    )


def _recover_from_limit_alarm(
    gantry: _GantryLike,
    delta: dict[str, float],
    *,
    pull_off_mm: float,
    feed_rate: float,
    output: Callable[[str], None],
) -> dict[str, float] | None:
    effective_pull_off_mm = max(5.0, float(pull_off_mm))
    pull_off = _opposite_pull_off_delta(delta, effective_pull_off_mm)
    failed_direction = ", ".join(
        f"{axis.upper()}{value:+g} mm" for axis, value in delta.items() if value
    ) or "unknown direction"
    pull_off_direction = ", ".join(
        f"{axis.upper()}{value:+g} mm" for axis, value in pull_off.items() if value
    ) or "unknown direction"
    output(
        "Limit alarm detected while jogging "
        f"{failed_direction}. Soft-resetting/unlocking GRBL and pulling off "
        f"{pull_off_direction} at {feed_rate:g} mm/min."
    )
    try:
        gantry.jog_cancel()
    except MillConnectionError:
        raise
    except (CommandExecutionError, StatusReturnError) as exc:
        output(f"Jog cancel during recovery failed: {exc}")
        output("Aborting calibration; use E-stop and rerun before continuing.")
        raise

    max_pull_off_attempts = 5
    output(
        f"Attempting limit pull-off up to {max_pull_off_attempts} times; "
        "soft-resetting/unlocking between attempts."
    )
    for attempt in range(1, max_pull_off_attempts + 1):
        _soft_reset_and_unlock_after_limit_alarm(gantry, output=output)
        try:
            gantry.jog(feed_rate=feed_rate, **pull_off)
        except MillConnectionError:
            raise
        except (CommandExecutionError, StatusReturnError) as exc:
            if attempt >= max_pull_off_attempts:
                output(f"Limit pull-off failed after {max_pull_off_attempts} attempts: {exc}")
                output("Aborting calibration; gantry position is unknown.")
                raise
            output(
                f"Limit pull-off attempt {attempt}/{max_pull_off_attempts} did not clear; retrying."
            )
            continue

        status = _read_limit_recovery_status(gantry)
        if not _needs_another_limit_pull_off(status):
            break
        if attempt >= max_pull_off_attempts:
            output(
                "Pull-off jog still left the controller in a limit/alarm state "
                f"after {max_pull_off_attempts} attempts. Use E-stop/power reset "
                "and manually clear the switch before continuing."
            )
            raise StatusReturnError(
                "Limit pull-off did not clear the alarm after repeated attempts."
            )
        output(
            f"Limit pull-off attempt {attempt}/{max_pull_off_attempts} did not clear; retrying."
        )
    output(
        "Pulled off the limit switch. Skipping immediate WPos readback because "
        "GRBL may not report coordinates reliably right after a limit reset; "
        "position readback will resume on the next operator confirmation."
    )
    return None


def _interactive_jog_to_reference(
    gantry: _GantryLike,
    *,
    target_description: str,
    confirmation_description: str,
    key_reader: KeyReader,
    output: Callable[[str], None],
    feed_rate: float,
    initial_step_mm: float,
    limit_pull_off_mm: float,
) -> dict[str, float]:
    step_mm = initial_step_mm
    output(CONTROLS_LEGEND)
    output(target_description)
    output(confirmation_description)

    while True:
        key, count = key_reader()
        key = key.upper()
        count = max(1, int(count))
        distance = step_mm * count

        if key == "Q":
            raise KeyboardInterrupt
        if key in ("\r", "\n", "ENTER"):
            coords = gantry.get_coordinates()
            output(
                "Confirming current reported WPos "
                f"X={coords['x']:.3f} Y={coords['y']:.3f} Z={coords['z']:.3f}"
            )
            return coords
        if key == " ":
            gantry.jog_cancel()
            output("Jog canceled.")
            continue
        if key == "1":
            step_mm = 0.1
            output("Jog step set to 0.1 mm.")
            continue
        if key == "2":
            step_mm = 1.0
            output("Jog step set to 1.0 mm.")
            continue
        if key == "3":
            step_mm = 5.0
            output("Jog step set to 5.0 mm.")
            continue
        if key == "4":
            step_mm = 10.0
            output("Jog step set to 10.0 mm.")
            continue
        if key == "5":
            step_mm = 25.0
            output("Jog step set to 25.0 mm.")
            continue
        if key == "6":
            step_mm = 50.0
            output("Jog step set to 50.0 mm.")
            continue
        if key == "7":
            step_mm = 100.0
            output("Jog step set to 100.0 mm.")
            continue

        delta = {"x": 0.0, "y": 0.0, "z": 0.0}
        if key == "LEFT":
            delta["x"] = -distance
        elif key == "RIGHT":
            delta["x"] = distance
        elif key == "DOWN":
            delta["y"] = -distance
        elif key == "UP":
            delta["y"] = distance
        elif key == "Z":
            delta["z"] = -distance
        elif key == "X":
            delta["z"] = distance
        else:
            continue

        coords = None
        try:
            gantry.jog(feed_rate=feed_rate, **delta)
            coords = gantry.get_coordinates()
            _probe_for_limit_status_after_jog(gantry)
        except MillConnectionError:
            raise
        except (CommandExecutionError, StatusReturnError) as exc:
            if _looks_like_soft_limit_jog_rejection(exc):
                output(
                    "GRBL rejected that jog because the target exceeds the "
                    "current soft-limit travel. The jog was ignored; reduce "
                    "the step, choose another direction, or press ENTER if "
                    "this is the intended safe origin point."
                )
                try:
                    coords = gantry.get_coordinates()
                except MillConnectionError:
                    raise
                except (CommandExecutionError, StatusReturnError) as read_exc:
                    output(f"WPos readback after rejected jog failed: {read_exc}")
                    output("Aborting calibration; gantry position is unknown.")
                    raise
            elif not _looks_like_limit_alarm(exc):
                output(f"Jog command rejected by controller: {exc}")
                output("Aborting calibration; gantry position is unknown.")
                raise
            else:
                coords = _recover_from_limit_alarm(
                    gantry,
                    delta,
                    pull_off_mm=limit_pull_off_mm,
                    feed_rate=feed_rate,
                    output=output,
                )
        if coords is None:
            continue
        output(
            "WPos "
            f"X={coords['x']:.3f} Y={coords['y']:.3f} Z={coords['z']:.3f} "
            f"(step {step_mm:g} mm)"
        )


def _interactive_jog_to_xy_origin(
    gantry: _GantryLike,
    *,
    key_reader: KeyReader,
    output: Callable[[str], None],
    feed_rate: float,
    initial_step_mm: float,
    limit_pull_off_mm: float,
) -> dict[str, float]:
    return _interactive_jog_to_reference(
        gantry,
        target_description=(
            "Step 1/1: jog the one reference TCP as far as appropriate toward "
            "the physical front-left XY origin and its lowest safe reachable Z."
        ),
        confirmation_description=(
            "Press ENTER only when the current X/Y should become WPos X=0, "
            "Y=0. After confirmation, the script will set Z from either true "
            "deck-bottom contact or a ruler-measured deck-to-TCP gap."
        ),
        key_reader=key_reader,
        output=output,
        feed_rate=feed_rate,
        initial_step_mm=initial_step_mm,
        limit_pull_off_mm=limit_pull_off_mm,
    )


def run_calibration(
    gantry_path: Path,
    *,
    dry_run: bool = False,
    tolerance_mm: float = 0.25,
    jog_step_mm: float = 1.0,
    jog_feed_rate: float = 2500.0,
    limit_pull_off_mm: float = 5.0,
    tip_gap_mm: float | None = None,
    reference_surface_z_mm: float | None = None,
    z_reference_mode: str = "bottom",
    measure_reachable_z_min: bool | None = False,
    instrument_name: str | None = None,
    skip_soft_limit_config: bool = False,
    write_gantry_yaml: bool = False,
    output_gantry_path: Path | None = None,
    homing_serial_timeout_s: float = 10.0,
    jog_serial_timeout_s: float = 1.0,
    output: Callable[[str], None] = print,
    input_reader: Callable[[str], str] = input,
    gantry_factory: Callable[..., _GantryLike] = Gantry,
    key_reader: KeyReader = read_keypress_batch,
    stdin_flusher: Callable[[], None] = flush_stdin,
) -> DeckOriginCalibrationResult | DeckOriginCalibrationPlan:
    """Calibrate one reference TCP to the CubOS physical deck origin."""
    gantry_path = gantry_path.resolve()
    gantry_config = load_gantry_from_yaml(gantry_path)
    raw_config = _load_raw_config(gantry_path)
    if output_gantry_path is not None:
        output_gantry_path = output_gantry_path.resolve()
    plan = build_deck_origin_calibration_plan(gantry_config)
    if reference_surface_z_mm is not None:
        if tip_gap_mm is not None:
            raise ValueError("Use only one of tip_gap_mm or reference_surface_z_mm.")
        tip_gap_mm = reference_surface_z_mm
    deprecated_known_height_mode = z_reference_mode == "known-height"
    if deprecated_known_height_mode:
        z_reference_mode = "ruler-gap"
    if z_reference_mode not in ("prompt", "bottom", "ruler-gap", "block"):
        raise ValueError("z_reference_mode must be one of: prompt, bottom, ruler-gap, block")
    if deprecated_known_height_mode:
        output(
            "Deprecated z_reference_mode=known-height received; treating "
            "the supplied height as a ruler-measured deck-to-TCP gap."
        )

    if dry_run:
        _print_dry_run(
            gantry_path,
            plan,
            tip_gap_mm=tip_gap_mm,
            z_reference_mode=z_reference_mode,
            instrument_name=instrument_name,
            output=output,
        )
        return plan

    output(f"Loaded deck-origin gantry config: {gantry_path}")
    output("Preflight:")
    output("  - Attach exactly one reference instrument/TCP for this calibration.")
    output("  - Place a calibration block at the front-left origin point.")
    output("  - Jog the instrument tip/probe to touch the block top at that point.")
    output("  - This will set X=0, Y=0, and Z to the calibration block height at the same pose.")
    if measure_reachable_z_min is True:
        output(
            "  - --measure-reachable-z-min is deprecated; the lower reach is "
            "now recorded from the origin/gap calibration point."
        )
    if instrument_name:
        output(f"  - Instrument/TCP label for reach output: {instrument_name}")
    output("")

    gantry_runtime_config = copy.deepcopy(raw_config)
    gantry_runtime_config.pop("grbl_settings", None)
    gantry = gantry_factory(config=gantry_runtime_config)
    restore_soft_limits_after_origin_jog = False
    try:
        output("Connecting to gantry...")
        gantry.connect()

        output("Homing to normalized back-right-top corner...")
        _set_serial_timeout_if_available(gantry, homing_serial_timeout_s)
        gantry.home()
        _set_serial_timeout_if_available(gantry, jog_serial_timeout_s)
        output("Forcing GRBL WPos status reporting ($10=0) and G90...")
        gantry.enforce_work_position_reporting()
        output("Activating G54 work coordinate system...")
        gantry.activate_work_coordinate_system("G54")
        output("Clearing transient G92 offsets before origin calibration...")
        gantry.clear_g92_offsets()
        stdin_flusher()

        restore_soft_limits_after_origin_jog = (
            _temporarily_disable_soft_limits_for_origin_jog(
                gantry,
                output=output,
            )
        )
        try:
            _interactive_jog_to_xy_origin(
                gantry,
                key_reader=key_reader,
                output=output,
                feed_rate=jog_feed_rate,
                initial_step_mm=jog_step_mm,
                limit_pull_off_mm=limit_pull_off_mm,
            )
        finally:
            if restore_soft_limits_after_origin_jog:
                restore_soft_limits_after_origin_jog = False
                _restore_soft_limits_after_origin_jog(gantry, output=output)

        output("Setting current physical pose to WPos X=0, Y=0...")
        gantry.set_work_coordinates(x=0.0, y=0.0)
        xy_origin_coords = dict(gantry.get_coordinates())
        _assert_near_xy_origin(
            xy_origin_coords,
            tolerance_mm=tolerance_mm,
        )
        output(
            "Verified XY origin WPos: "
            f"X={xy_origin_coords['x']:.3f} "
            f"Y={xy_origin_coords['y']:.3f} "
            f"Z={xy_origin_coords['z']:.3f}"
        )

        if z_reference_mode == "prompt":
            z_reference_mode = _prompt_z_reference_mode(
                input_reader=input_reader,
                output=output,
            )
        if z_reference_mode == "bottom":
            if tip_gap_mm is not None and tip_gap_mm != 0:
                raise ValueError("Bottom Z mode cannot use a non-zero tip gap.")
            z_min_mm = 0.0
        elif z_reference_mode == "block":
            if tip_gap_mm is None:
                tip_gap_mm = _prompt_block_height(
                    input_reader=input_reader,
                    output=output,
                )
            if tip_gap_mm <= 0:
                raise ValueError("block height must be > 0 in block mode.")
            z_min_mm = float(tip_gap_mm)
        else:
            if tip_gap_mm is None:
                tip_gap_mm = _prompt_tip_gap_mm(
                    input_reader=input_reader,
                    output=output,
                )
            if tip_gap_mm <= 0:
                raise ValueError("tip_gap_mm must be > 0 in ruler-gap mode.")
            z_min_mm = float(tip_gap_mm)

        output(f"Setting current physical pose to WPos Z={z_min_mm:g}...")
        gantry.set_work_coordinates(z=z_min_mm)
        z_reference_coords = dict(gantry.get_coordinates())
        _assert_near_z_reference(
            z_reference_coords,
            z_min_mm=z_min_mm,
            tolerance_mm=tolerance_mm,
        )
        output(
            "Verified Z reference WPos: "
            f"X={z_reference_coords['x']:.3f} "
            f"Y={z_reference_coords['y']:.3f} "
            f"Z={z_reference_coords['z']:.3f}"
        )

        reachable_z_min_mm = z_min_mm

        output("Re-homing to measure physical working-volume maxima...")
        _set_serial_timeout_if_available(gantry, homing_serial_timeout_s)
        gantry.home()
        _set_serial_timeout_if_available(gantry, jog_serial_timeout_s)
        measured_coords = gantry.get_coordinates()
        _assert_positive_measured_volume(
            measured_coords,
            tolerance_mm=tolerance_mm,
        )
        max_travel = _calculate_grbl_max_travel(
            measured_coords,
            z_min_mm=z_min_mm,
            tolerance_mm=tolerance_mm,
        )
        if skip_soft_limit_config:
            output("Skipping GRBL soft-limit programming by request.")
        else:
            gantry.configure_soft_limits_from_spans(
                max_travel_x=max_travel["max_travel_x"],
                max_travel_y=max_travel["max_travel_y"],
                max_travel_z=max_travel["max_travel_z"],
                tolerance_mm=tolerance_mm,
            )

        _print_config_patch(
            measured_coords,
            z_reference_coords=z_reference_coords,
            z_min_mm=z_min_mm,
            z_reference_mode=z_reference_mode,
            instrument_name=instrument_name,
            output=output,
        )
        gantry_yaml_text = _updated_gantry_yaml_text(
            raw_config,
            measured_coords=measured_coords,
            z_min_mm=z_min_mm,
            max_travel=max_travel,
        )
        _print_yaml_block(
            title="Full gantry YAML to copy/paste:",
            yaml_text=gantry_yaml_text,
            output=output,
        )
        _maybe_write_gantry_yaml(
            yaml_text=gantry_yaml_text,
            output_path=output_gantry_path,
            write_requested=write_gantry_yaml,
            input_reader=input_reader,
            output=output,
        )

        return DeckOriginCalibrationResult(
            measured_working_volume=_coords_tuple(measured_coords),
            xy_origin_verification=_coords_tuple(xy_origin_coords),
            z_reference_verification=_coords_tuple(z_reference_coords),
            z_min_mm=z_min_mm,
            z_reference_mode=z_reference_mode,
            reachable_z_min_mm=reachable_z_min_mm,
            grbl_max_travel=(
                max_travel["max_travel_x"],
                max_travel["max_travel_y"],
                max_travel["max_travel_z"],
            ),
            instrument_name=instrument_name,
            plan=plan,
        )
    finally:
        try:
            if restore_soft_limits_after_origin_jog:
                restore_soft_limits_after_origin_jog = False
                _restore_soft_limits_after_origin_jog(gantry, output=output)
        finally:
            _set_serial_timeout_if_available(gantry, 0.05)
            output("Disconnecting...")
            gantry.disconnect()
