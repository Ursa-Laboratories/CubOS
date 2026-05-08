"""Multi-instrument gantry calibration flow.

Internal implementation used by the sole user-facing entrypoint:
``setup/calibrate_gantry.py``.
"""

from __future__ import annotations

import argparse
import copy
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol, Sequence

import yaml

project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

from gantry import Gantry, load_gantry_from_yaml  # noqa: E402
from gantry.origin import validate_deck_origin_minima  # noqa: E402
from setup.calibration.single_instrument_calibration import (  # noqa: E402
    _assert_near_xyz,
    _calculate_grbl_max_travel,
    _interactive_jog_to_reference,
    _load_raw_config,
    _maybe_write_gantry_yaml,
    _print_yaml_block,
    _restore_soft_limits_after_origin_jog,
    _round_mm,
    _set_serial_timeout_if_available,
    _temporarily_disable_soft_limits_for_origin_jog,
)
from setup.keyboard_input import flush_stdin, read_keypress_batch  # noqa: E402


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
    def move_to(
        self,
        x: float,
        y: float,
        z: float,
        travel_z: float | None = None,
    ) -> None: ...
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
    def configure_soft_limits_from_spans(
        self,
        *,
        max_travel_x: float,
        max_travel_y: float,
        max_travel_z: float,
        tolerance_mm: float = 0.001,
    ) -> None: ...


KeyReader = Callable[[], tuple[str, int]]


@dataclass(frozen=True)
class MultiInstrumentCalibrationResult:
    """Result of a multi-instrument board calibration run."""

    measured_working_volume: tuple[float, float, float]
    xy_bounds_after_origin: tuple[float, float, float]
    xy_origin_verification: tuple[float, float, float]
    z_origin_verification: tuple[float, float, float]
    instrument_calibrations: dict[str, dict[str, float]]
    grbl_max_travel: tuple[float, float, float]
    reference_instrument: str
    lowest_instrument: str
    block_reference_coordinates: dict[str, tuple[float, float, float]]


def _coords_tuple(coords: dict[str, float]) -> tuple[float, float, float]:
    return (float(coords["x"]), float(coords["y"]), float(coords["z"]))


def _assert_near_xy_origin(
    coords: dict[str, float],
    *,
    tolerance_mm: float,
) -> None:
    misses = [
        f"{axis}: got {float(coords[axis]):.4f}, expected 0.0000"
        for axis in ("x", "y")
        if abs(float(coords[axis])) > tolerance_mm
    ]
    if misses:
        raise RuntimeError(
            "Deck-origin XY reference did not verify within "
            f"{tolerance_mm} mm: " + "; ".join(misses)
        )


def compute_relative_instrument_calibrations(
    *,
    block_coordinates: dict[str, dict[str, float]],
    reference_instrument: str,
    lowest_instrument: str,
) -> dict[str, dict[str, float]]:
    """Compute offsets/depths from one shared, arbitrary block point.

    The block does not need known deck-frame X/Y/Z coordinates. The reference
    instrument defines zero XY offset, and the lowest instrument defines zero
    depth after the Z-reference step. For every other instrument, touching the
    same physical block point gives the relative WPos deltas needed by
    Board.move() semantics:
        offset_i = offset_ref + gantry_ref - gantry_i
        depth_i = depth_lowest + gantry_i_z - gantry_lowest_z
    with offset_ref=(0, 0) and depth_lowest=0 in this calibration flow.
    """
    missing = [
        name
        for name in (reference_instrument, lowest_instrument)
        if name not in block_coordinates
    ]
    if missing:
        raise ValueError(
            "Missing block coordinate(s) for required baseline instrument(s): "
            + ", ".join(missing)
        )
    reference_coords = block_coordinates[reference_instrument]
    lowest_coords = block_coordinates[lowest_instrument]
    calibrations: dict[str, dict[str, float]] = {}
    for instrument, coords in block_coordinates.items():
        calibrations[instrument] = {
            "offset_x": _round_mm(
                float(reference_coords["x"]) - float(coords["x"])
            ),
            "offset_y": _round_mm(
                float(reference_coords["y"]) - float(coords["y"])
            ),
            "depth": _round_mm(float(coords["z"]) - float(lowest_coords["z"])),
        }
    return calibrations


def _build_grbl_settings(
    raw_config: dict[str, Any],
    max_travel: dict[str, float],
) -> dict[str, Any]:
    return {
        "status_report": 0,
        "soft_limits": True,
        "homing_enable": True,
        "max_travel_x": max_travel["max_travel_x"],
        "max_travel_y": max_travel["max_travel_y"],
        "max_travel_z": max_travel["max_travel_z"],
    }


def _updated_yaml_text(
    raw_config: dict[str, Any],
    *,
    measured_coords: dict[str, float],
    instrument_calibrations: dict[str, dict[str, float]],
    max_travel: dict[str, float],
) -> str:
    updated = copy.deepcopy(raw_config)
    updated.setdefault("cnc", {})["total_z_range"] = _round_mm(measured_coords["z"])
    updated["working_volume"] = {
        "x_min": 0.0,
        "x_max": _round_mm(measured_coords["x"]),
        "y_min": 0.0,
        "y_max": _round_mm(measured_coords["y"]),
        "z_min": 0.0,
        "z_max": _round_mm(measured_coords["z"]),
    }
    updated["grbl_settings"] = _build_grbl_settings(raw_config, max_travel)

    instruments = updated.setdefault("instruments", {})
    for name, calibration in instrument_calibrations.items():
        entry = instruments.setdefault(name, {})
        entry.update(calibration)

    return yaml.safe_dump(updated, sort_keys=False)


def _validate_instrument_names(
    raw_config: dict[str, Any],
    names: Sequence[str],
) -> None:
    instruments = raw_config.get("instruments")
    if not isinstance(instruments, dict) or not instruments:
        raise ValueError("Gantry YAML must define top-level instruments to calibrate.")
    missing = [name for name in names if name not in instruments]
    if missing:
        available = ", ".join(sorted(instruments.keys()))
        raise ValueError(
            "Unknown instrument(s): "
            + ", ".join(missing)
            + f". Available instruments: {available}"
        )


def _instrument_names(raw_config: dict[str, Any]) -> tuple[str, ...]:
    instruments = raw_config.get("instruments")
    if not isinstance(instruments, dict) or not instruments:
        raise ValueError("Gantry YAML must define top-level instruments to calibrate.")
    return tuple(instruments.keys())


def _unique_instrument_sequence(names: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for name in names:
        if name not in seen:
            ordered.append(name)
            seen.add(name)
    return tuple(ordered)


def _prompt_z_reference_height(
    *,
    input_reader: Callable[[str], str],
    output: Callable[[str], None],
) -> float:
    output("")
    output("Z reference: use a calibration block. The lowest instrument should touch the block top.")
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


def _looks_like_serial_device_not_configured(exc: Exception) -> bool:
    message = str(exc).lower()
    return "device not configured" in message


def _home_with_serial_reconnect(
    gantry: _GantryLike,
    *,
    output: Callable[[str], None],
) -> None:
    try:
        gantry.home()
    except KeyboardInterrupt:
        raise
    except Exception as exc:
        if not _looks_like_serial_device_not_configured(exc):
            raise
        output(
            "Serial device disappeared during homing ('Device not configured'). "
            "Reconnecting once, then retrying $H."
        )
        gantry.disconnect()
        gantry.connect()
        gantry.home()


def _move_to_xy_center(
    gantry: _GantryLike,
    bounds_coords: dict[str, float],
    *,
    output: Callable[[str], None],
    label: str,
) -> dict[str, float]:
    center_x = _round_mm(float(bounds_coords["x"]) / 2.0)
    center_y = _round_mm(float(bounds_coords["y"]) / 2.0)
    z = float(bounds_coords["z"])
    output(
        f"Moving to deck XY center before {label}: "
        f"X={center_x:.3f} Y={center_y:.3f} while keeping Z={z:.3f}."
    )
    gantry.move_to(center_x, center_y, z)
    return dict(gantry.get_coordinates())


def _wait_until_idle_if_available(
    gantry: _GantryLike,
    *,
    timeout_s: float = 10.0,
    poll_interval_s: float = 0.1,
) -> None:
    status_reader = getattr(gantry, "get_status", None)
    if not callable(status_reader):
        return

    deadline = time.monotonic() + timeout_s
    last_status = ""
    while time.monotonic() < deadline:
        last_status = str(status_reader())
        if "idle" in last_status.lower():
            return
        time.sleep(poll_interval_s)

    raise RuntimeError(
        "Timed out waiting for gantry to become idle after jog; "
        f"last status: {last_status}"
    )


def _retract_up_after_contact(
    gantry: _GantryLike,
    *,
    retract_z_mm: float,
    feed_rate: float,
    output: Callable[[str], None],
) -> None:
    if retract_z_mm <= 0:
        return
    output(
        f"Raising Z by {retract_z_mm:g} mm before moving to the next tool/reference step."
    )
    gantry.jog(z=retract_z_mm, feed_rate=feed_rate)
    _wait_until_idle_if_available(gantry)


def run_multi_instrument_calibration(
    gantry_path: Path,
    *,
    reference_instrument: str | None = None,
    lowest_instrument: str | None = None,
    artifact_xyz: tuple[float, float, float] | None = None,
    instruments_to_calibrate: Sequence[str] | None = None,
    dry_run: bool = False,
    tolerance_mm: float = 0.25,
    jog_step_mm: float = 1.0,
    jog_feed_rate: float = 2000.0,
    post_contact_retract_z_mm: float = 15.0,
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
) -> MultiInstrumentCalibrationResult | None:
    """Run the guided multi-instrument calibration flow."""
    gantry_path = gantry_path.resolve()
    gantry_config = load_gantry_from_yaml(gantry_path)
    validate_deck_origin_minima(gantry_config)
    raw_config = _load_raw_config(gantry_path)
    if output_gantry_path is not None:
        output_gantry_path = output_gantry_path.resolve()
    available_instruments = _instrument_names(raw_config)
    output(f"Loaded deck-origin gantry config: {gantry_path}")
    output("Calibration overview:")
    output("  This guided routine creates the shared CubOS deck frame for the whole instrument board.")
    output("  Step 1 sets the system origin: place the origin block/artifact in the front-left")
    output("  corner, then jog the first/left-most tool's active tip/probe point over the X mark.")
    output("  The script sets only G54 WPos X=0 and Y=0 there; Z is set later after the full")
    output("  instrument board is attached and the lowest mounted tool touches the reference point.")
    output("")
    reference_instrument = reference_instrument or _prompt_instrument_name(
        "Pick the number for the first/left-most tool for front-left origin",
        available_instruments,
        raw_config=raw_config,
        input_reader=input_reader,
        output=output,
    )
    if artifact_xyz is not None:
        output(
            "Ignoring deprecated artifact_xyz/--artifact-* input: the block point "
            "no longer needs known deck-frame coordinates."
        )
    instruments = tuple(instruments_to_calibrate or available_instruments)
    names_to_validate = [reference_instrument, *instruments]
    if lowest_instrument is not None:
        names_to_validate.append(lowest_instrument)
    _validate_instrument_names(raw_config, names_to_validate)
    if dry_run:
        output(f"Loaded deck-origin gantry config: {gantry_path}")
        output("Dry run only. Physical calibration flow:")
        output("  $H")
        output("  temporarily disable stale GRBL soft limits during calibration jogs")
        output("  attach the first/left-most tool at the homed pose")
        output("  place an origin block/artifact at the front-left corner")
        output("  jog that tool's active tip/probe point over the X mark as closely as possible")
        output("  G10 L20 P1 X0 Y0  # XY only, do not set Z here")
        output("  $H and read X/Y bounds")
        output("  move to measured X/Y center for calibration-block work")
        output("  attach all instruments and jog lowest instrument to the shared Z/block point")
        output("  enter the calibration block height")
        output("  G10 L20 P1 Z<block_height>")
        output("  record the lowest instrument's X/Y/Z block coordinate immediately")
        output("  jog each remaining instrument to that same block point and compute offsets/depths")
        output("  $H and read final working-volume maxima")
        return None

    output("Preflight:")
    output("  - Keep E-stop reachable; calibration can move mounted tools and changes G54 WPos.")
    output(f"  - First/left-most tool for front-left origin: {reference_instrument}")
    if lowest_instrument is None:
        output("  - The lowest mounted tool will be selected later, after the full board is attached/verified.")
    else:
        output(f"  - Lowest mounted tool for Z/reference point: {lowest_instrument}")
    output(
        "  - Calibration block/reference point: place it near the deck center where every "
        "instrument can reach the same physical point. The lowest instrument will "
        "define Z and be recorded there first; its X/Y/Z coordinates will not be "
        "requested a second time."
    )
    output("")

    gantry_runtime_config = copy.deepcopy(raw_config)
    gantry_runtime_config.pop("grbl_settings", None)
    gantry = gantry_factory(config=gantry_runtime_config)
    restore_soft_limits_after_calibration = False
    try:
        output("Connecting to gantry...")
        gantry.connect()

        output("Homing to normalized BRT corner...")
        _set_serial_timeout_if_available(gantry, homing_serial_timeout_s)
        _home_with_serial_reconnect(gantry, output=output)
        _set_serial_timeout_if_available(gantry, jog_serial_timeout_s)
        output("Forcing GRBL WPos status reporting ($10=0), G90, G54, and clearing G92...")
        gantry.enforce_work_position_reporting()
        gantry.activate_work_coordinate_system("G54")
        gantry.clear_g92_offsets()
        restore_soft_limits_after_calibration = (
            _temporarily_disable_soft_limits_for_origin_jog(
                gantry,
                output=output,
            )
        )
        stdin_flusher()

        output(
            f"Attach {reference_instrument!r} at the homed BRT pose before jogging. "
            "Place the front-left origin block/artifact in the front-left corner. "
            "No automatic center move will be made."
        )
        _interactive_jog_to_reference(
            gantry,
            target_description=(
                f"Step 1: attach {reference_instrument!r} at the homed pose. "
                "Place the origin block/artifact in the front-left corner, then "
                "jog the tool's active tip/probe point (tool center point) directly "
                "over the X mark as closely as possible. Do not use this step to define Z."
            ),
            confirmation_description=(
                "Press ENTER when current X/Y should become WPos X=0, Y=0. "
                "The script will not change WPos Z in this step."
            ),
            key_reader=key_reader,
            output=output,
            feed_rate=jog_feed_rate,
            initial_step_mm=jog_step_mm,
            limit_pull_off_mm=5.0,
        )
        output("Setting current physical pose to WPos X=0, Y=0 only...")
        gantry.set_work_coordinates(x=0.0, y=0.0)
        xy_origin_coords = dict(gantry.get_coordinates())
        _assert_near_xy_origin(xy_origin_coords, tolerance_mm=tolerance_mm)

        output("Re-homing after XY origining to measure machine-derived X/Y bounds...")
        _set_serial_timeout_if_available(gantry, homing_serial_timeout_s)
        _home_with_serial_reconnect(gantry, output=output)
        _set_serial_timeout_if_available(gantry, jog_serial_timeout_s)
        xy_bounds_coords = dict(gantry.get_coordinates())

        center_before_z_coords = _move_to_xy_center(
            gantry,
            xy_bounds_coords,
            output=output,
            label="lowest-instrument Z calibration",
        )
        output(
            "Attach/verify the full instrument board at the deck XY center before setting Z."
        )
        if lowest_instrument is None:
            lowest_instrument = _prompt_instrument_name(
                "Pick the number for the lowest mounted tool / first Z-reference touch",
                available_instruments,
                raw_config=raw_config,
                input_reader=input_reader,
                output=output,
            )
            _validate_instrument_names(raw_config, (lowest_instrument,))
        _interactive_jog_to_reference(
            gantry,
            target_description=(
                f"Step 2: from the deck XY center "
                f"(X={center_before_z_coords['x']:.3f}, "
                f"Y={center_before_z_coords['y']:.3f}), jog the lowest instrument "
                f"({lowest_instrument!r}) to the shared calibration block/reference point. "
                "This one touch records its X/Y/Z and defines Z."
            ),
            confirmation_description=(
                "Press ENTER when this lowest instrument is touching the shared point. "
                "X/Y will not be changed when assigning the Z work coordinate, and this "
                "instrument will not be requested again in the per-instrument pass."
            ),
            key_reader=key_reader,
            output=output,
            feed_rate=jog_feed_rate,
            initial_step_mm=jog_step_mm,
            limit_pull_off_mm=5.0,
        )
        z_reference_height = _prompt_z_reference_height(
            input_reader=input_reader,
            output=output,
        )
        output(
            f"Setting current physical pose to WPos Z={z_reference_height:g} only..."
        )
        gantry.set_work_coordinates(z=z_reference_height)
        z_origin_coords = dict(gantry.get_coordinates())
        _assert_near_xyz(
            z_origin_coords,
            expected={
                "x": z_origin_coords["x"],
                "y": z_origin_coords["y"],
                "z": z_reference_height,
            },
            tolerance_mm=tolerance_mm,
            label="Lowest-instrument Z reference",
        )

        block_coordinates: dict[str, dict[str, float]] = {
            lowest_instrument: dict(z_origin_coords)
        }
        output(
            f"Recorded block WPos for lowest instrument {lowest_instrument}: "
            f"X={block_coordinates[lowest_instrument]['x']:.3f}, "
            f"Y={block_coordinates[lowest_instrument]['y']:.3f}, "
            f"Z={block_coordinates[lowest_instrument]['z']:.3f}"
        )
        _retract_up_after_contact(
            gantry,
            retract_z_mm=post_contact_retract_z_mm,
            feed_rate=jog_feed_rate,
            output=output,
        )
        output(
            "Now calibrate each remaining instrument against that same physical point. "
            "Do not move the block/reference point between instruments."
        )
        calibration_sequence = tuple(
            instrument
            for instrument in _unique_instrument_sequence(
                (reference_instrument, *instruments)
            )
            if instrument != lowest_instrument
        )
        for instrument in calibration_sequence:
            _interactive_jog_to_reference(
                gantry,
                target_description=(
                    f"Step 3: calibrate {instrument!r}. Jog this tool's active tip/probe point "
                    "(tool center point) to the same physical point used by the lowest instrument. The block's "
                    "deck-frame X/Y/Z coordinates do not need to be known."
                ),
                confirmation_description=(
                    "Press ENTER when this instrument is touching the same block point "
                    "used for the other instruments. Do not move the block between "
                    "instruments."
                ),
                key_reader=key_reader,
                output=output,
                feed_rate=jog_feed_rate,
                initial_step_mm=jog_step_mm,
                limit_pull_off_mm=5.0,
            )
            block_coordinates[instrument] = dict(gantry.get_coordinates())
            output(
                f"Recorded block WPos for {instrument}: "
                f"X={block_coordinates[instrument]['x']:.3f}, "
                f"Y={block_coordinates[instrument]['y']:.3f}, "
                f"Z={block_coordinates[instrument]['z']:.3f}"
            )
            _retract_up_after_contact(
                gantry,
                retract_z_mm=post_contact_retract_z_mm,
                feed_rate=jog_feed_rate,
                output=output,
            )

        output("Re-homing after instrument calibration to measure final working-volume maxima...")
        _set_serial_timeout_if_available(gantry, homing_serial_timeout_s)
        _home_with_serial_reconnect(gantry, output=output)
        _set_serial_timeout_if_available(gantry, jog_serial_timeout_s)
        measured_coords = dict(gantry.get_coordinates())
        max_travel = _calculate_grbl_max_travel(
            measured_coords,
            z_min_mm=0.0,
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
            restore_soft_limits_after_calibration = False

        all_calibrations = compute_relative_instrument_calibrations(
            block_coordinates=block_coordinates,
            reference_instrument=reference_instrument,
            lowest_instrument=lowest_instrument,
        )
        instrument_calibrations = {
            instrument: all_calibrations[instrument]
            for instrument in instruments
        }
        for instrument, calibration in instrument_calibrations.items():
            output(
                f"Computed {instrument}: "
                f"offset_x={calibration['offset_x']:.3f}, "
                f"offset_y={calibration['offset_y']:.3f}, "
                f"depth={calibration['depth']:.3f}"
            )

        yaml_text = _updated_yaml_text(
            raw_config,
            measured_coords=measured_coords,
            instrument_calibrations=instrument_calibrations,
            max_travel=max_travel,
        )
        _print_yaml_block(
            title="Full calibrated multi-instrument gantry YAML to copy/paste:",
            yaml_text=yaml_text,
            output=output,
        )
        _maybe_write_gantry_yaml(
            yaml_text=yaml_text,
            output_path=output_gantry_path,
            write_requested=write_gantry_yaml,
            input_reader=input_reader,
            output=output,
        )

        return MultiInstrumentCalibrationResult(
            measured_working_volume=_coords_tuple(measured_coords),
            xy_bounds_after_origin=_coords_tuple(xy_bounds_coords),
            xy_origin_verification=_coords_tuple(xy_origin_coords),
            z_origin_verification=_coords_tuple(z_origin_coords),
            instrument_calibrations=instrument_calibrations,
            grbl_max_travel=(
                max_travel["max_travel_x"],
                max_travel["max_travel_y"],
                max_travel["max_travel_z"],
            ),
            reference_instrument=reference_instrument,
            lowest_instrument=lowest_instrument,
            block_reference_coordinates={
                name: _coords_tuple(coords)
                for name, coords in block_coordinates.items()
            },
        )
    finally:
        try:
            if restore_soft_limits_after_calibration:
                restore_soft_limits_after_calibration = False
                _restore_soft_limits_after_origin_jog(gantry, output=output)
        finally:
            _set_serial_timeout_if_available(gantry, 0.05)
            output("Disconnecting...")
            gantry.disconnect()


def _prompt_instrument_name(
    label: str,
    available: Sequence[str],
    *,
    raw_config: dict[str, Any] | None = None,
    input_reader: Callable[[str], str],
    output: Callable[[str], None],
) -> str:
    instruments = raw_config.get("instruments", {}) if isinstance(raw_config, dict) else {}
    output("Available instruments:")
    for index, name in enumerate(available, start=1):
        instrument_config = instruments.get(name, {}) if isinstance(instruments, dict) else {}
        instrument_type = instrument_config.get("type") if isinstance(instrument_config, dict) else None
        suffix = f" ({instrument_type})" if instrument_type else ""
        output(f"  {index}. {name}{suffix}")
    while True:
        raw = input_reader(f"{label}: ").strip()
        if not raw:
            output(f"Pick which numbered tool to use: enter 1 to {len(available)}.")
            continue
        try:
            selected_index = int(raw)
        except ValueError:
            output(f"Enter a number from 1 to {len(available)}.")
            continue
        if not 1 <= selected_index <= len(available):
            output(f"Enter a number from 1 to {len(available)}.")
            continue
        selected = available[selected_index - 1]
        confirm = input_reader(f"You selected #{selected_index} {selected}. Continue? [y/N]: ").strip().lower()
        if confirm in {"y", "yes"}:
            return selected
        output("Selection cancelled; pick the numbered tool again.")


def _prompt_float(
    prompt: str,
    *,
    input_reader: Callable[[str], str],
    output: Callable[[str], None],
) -> float:
    while True:
        raw = input_reader(prompt).strip()
        try:
            return float(raw)
        except ValueError:
            output("Enter a numeric value in millimeters.")


def _prompt_artifact_xyz(
    *,
    input_reader: Callable[[str], str],
    output: Callable[[str], None],
) -> tuple[float, float, float]:
    output("Enter the known deck-frame artifact/block point in millimeters.")
    return (
        _prompt_float("Artifact X mm: ", input_reader=input_reader, output=output),
        _prompt_float("Artifact Y mm: ", input_reader=input_reader, output=output),
        _prompt_float("Artifact Z mm: ", input_reader=input_reader, output=output),
    )


def _artifact_xyz_from_args(args: argparse.Namespace) -> tuple[float, float, float] | None:
    supplied = [args.artifact_x is not None, args.artifact_y is not None, args.artifact_z is not None]
    if not any(supplied):
        return None
    if not all(supplied):
        raise ValueError("Supply all of --artifact-x, --artifact-y, and --artifact-z, or none.")
    return (float(args.artifact_x), float(args.artifact_y), float(args.artifact_z))
