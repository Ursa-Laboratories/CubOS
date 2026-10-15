"""Bounds validation for deck positions and protocol motion targets."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any, List, Tuple

logger = logging.getLogger(__name__)

from cubos.deck.deck import Deck
from cubos.deck.labware.labware import Coordinate3D
from cubos.deck.labware.tip_rack import (
    TipRackResolutionError,
    resolve_tip_rack_slot,
)
from cubos.deck.labware.well_plate import WellPlate
from cubos.deck.labware.vial import Vial
from cubos.gantry.gantry_config import GantryConfig, WorkingVolume
from cubos.gantry.instrument_mount import InstrumentedGantry
from cubos.protocol_engine.protocol import Protocol

from .errors import BoundsViolation


@dataclass(frozen=True)
class ProtocolMotionTarget:
    """One concrete point a protocol command can ask an instrument to reach."""

    labware_key: str
    position_id: str
    instrument_name: str
    x: float
    y: float
    z: float
    tip_extension: float = 0.0


def _check_point(
    volume: WorkingVolume, x: float, y: float, z: float,
) -> List[Tuple[str, str, float]]:
    """Return (axis, bound_name, bound_value) for each violated bound."""
    violations: List[Tuple[str, str, float]] = []
    if x < volume.x_min:
        violations.append(("x", "x_min", volume.x_min))
    if x > volume.x_max:
        violations.append(("x", "x_max", volume.x_max))
    if y < volume.y_min:
        violations.append(("y", "y_min", volume.y_min))
    if y > volume.y_max:
        violations.append(("y", "y_max", volume.y_max))
    if z < volume.z_min:
        violations.append(("z", "z_min", volume.z_min))
    if z > volume.z_max:
        violations.append(("z", "z_max", volume.z_max))
    return violations


def _get_all_positions(
    deck: Deck,
) -> List[Tuple[str, str, float, float, float]]:
    """Extract every (labware_key, position_id, x, y, z) from the deck."""
    positions: List[Tuple[str, str, float, float, float]] = []
    for key in deck:
        labware = deck[key]
        for position_id, coord in labware.iter_positions().items():
            positions.append((key, position_id, coord.x, coord.y, coord.z))
    return positions


def _is_finite_number(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
    )


def _xyz_from_sequence(value: Any) -> tuple[float, float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    if not all(_is_finite_number(coord) for coord in value):
        return None
    return (float(value[0]), float(value[1]), float(value[2]))


def _resolve_deck_coord(deck: Deck, target: Any) -> Coordinate3D | None:
    if not isinstance(target, str):
        return None
    try:
        return deck.resolve_coordinate(target)
    except KeyError:
        return None


def _resolve_labware(deck: Deck, target: Any) -> Any | None:
    if not isinstance(target, str):
        return None
    try:
        return deck.resolve_labware(target)
    except KeyError:
        return None


def _tip_length_for_pickup(deck: Deck, target: Any) -> float | None:
    try:
        rack, _ = resolve_tip_rack_slot(deck, target)
    except TipRackResolutionError:
        return None
    if not _is_finite_number(rack.tip_length):
        return None
    return float(rack.tip_length)


def _height_arg(step_args: dict[str, Any], name: str, default: float = 0.0) -> float | None:
    value = step_args.get(name, default)
    if not _is_finite_number(value):
        # Bounds validation is the last line of defense. If a non-finite
        # height slips past the semantic validator we cannot meaningfully
        # bounds-check the implied target, but we must not silently drop
        # it without leaving a trace — log loudly so the missing target
        # is visible to operators reviewing logs after a failed run.
        logger.error(
            "non-finite %s=%r in step %r; bounds target skipped. "
            "Run validate_protocol_semantics() to surface this as a violation.",
            name, value, step_args,
        )
        return None
    return float(value)


def _target_label(target: str, suffix: str) -> tuple[str, str]:
    if "." in target:
        labware_key, position_id = target.rsplit(".", 1)
        return labware_key, f"{position_id}.{suffix}"
    return target, f"location.{suffix}"


def _append_target(
    targets: list[ProtocolMotionTarget],
    *,
    target: str,
    suffix: str,
    instrument: str,
    x: float,
    y: float,
    z: float,
    tip_extension: float = 0.0,
) -> None:
    labware_key, position_id = _target_label(target, suffix)
    targets.append(ProtocolMotionTarget(
        labware_key=labware_key,
        position_id=position_id,
        instrument_name=instrument,
        x=x,
        y=y,
        z=z,
        tip_extension=tip_extension,
    ))


def _append_engage_targets(
    targets: list[ProtocolMotionTarget],
    *,
    target: str,
    coord: Coordinate3D,
    instrument: str,
    measurement_height: float,
    gantry: GantryConfig,
    tip_extension: float = 0.0,
    x_offset_mm: float = 0.0,
    y_offset_mm: float = 0.0,
) -> None:
    x = coord.x + x_offset_mm
    y = coord.y + y_offset_mm
    _append_target(
        targets,
        target=target,
        suffix="safe_z",
        instrument=instrument,
        x=x,
        y=y,
        z=gantry.resolved_safe_z,
        tip_extension=tip_extension,
    )
    _append_target(
        targets,
        target=target,
        suffix="action_z",
        instrument=instrument,
        x=x,
        y=y,
        z=coord.z + measurement_height,
        tip_extension=tip_extension,
    )


def _append_position_engage(
    targets: list[ProtocolMotionTarget],
    *,
    deck: Deck,
    gantry: GantryConfig,
    position: Any,
    instrument: str,
    measurement_height: float,
    tip_extension: float = 0.0,
    x_offset_mm: float = 0.0,
    y_offset_mm: float = 0.0,
) -> None:
    if (
        not isinstance(position, str)
        or not _is_finite_number(measurement_height)
        or not _is_finite_number(x_offset_mm)
        or not _is_finite_number(y_offset_mm)
    ):
        return
    coord = _resolve_deck_coord(deck, position)
    if coord is None:
        return
    _append_engage_targets(
        targets,
        target=position,
        coord=coord,
        instrument=instrument,
        measurement_height=float(measurement_height),
        gantry=gantry,
        tip_extension=tip_extension,
        x_offset_mm=float(x_offset_mm),
        y_offset_mm=float(y_offset_mm),
    )


def _row_major_key(well_id: str) -> tuple[str, int]:
    return (well_id[0], int(well_id[1:]))


def _wells_for_axis(plate: WellPlate, axis: Any) -> list[str]:
    if not isinstance(axis, str):
        return []
    axis = axis.upper()
    if axis.isalpha():
        wells = [well for well in plate.wells if well[0] == axis]
    else:
        wells = [well for well in plate.wells if well[1:] == axis]
    return sorted(wells, key=_row_major_key)


def _append_move_targets(
    targets: list[ProtocolMotionTarget],
    *,
    step_args: dict[str, Any],
    protocol: Protocol,
    deck: Deck,
    gantry: GantryConfig,
    pipette_tip_extension: float = 0.0,
) -> None:
    instrument = step_args.get("instrument")
    position = step_args.get("position")
    travel_z = step_args.get("travel_z")
    x_offset = _height_arg(step_args, "x_offset_mm")
    y_offset = _height_arg(step_args, "y_offset_mm")
    if not isinstance(instrument, str):
        return
    if x_offset is None or y_offset is None:
        return
    tip_ext = pipette_tip_extension if instrument == "pipette" else 0.0

    target_xyz: tuple[float, float, float] | None = None
    target_label = f"step.move.{position!r}"
    if isinstance(position, str) and position in protocol.positions:
        target_xyz = _xyz_from_sequence(protocol.positions[position])
        target_label = position
    elif isinstance(position, str):
        coord = _resolve_deck_coord(deck, position)
        if coord is None:
            return
        _append_target(
            targets,
            target=position,
            suffix="safe_z",
            instrument=instrument,
            x=coord.x + x_offset,
            y=coord.y + y_offset,
            z=gantry.resolved_safe_z,
            tip_extension=tip_ext,
        )
        return
    else:
        target_xyz = _xyz_from_sequence(position)

    if target_xyz is None:
        return
    x, y, z = target_xyz
    x += x_offset
    y += y_offset
    _append_target(
        targets,
        target=target_label,
        suffix="target",
        instrument=instrument,
        x=x,
        y=y,
        z=z,
        tip_extension=tip_ext,
    )
    if _is_finite_number(travel_z):
        _append_target(
            targets,
            target=target_label,
            suffix="travel_z",
            instrument=instrument,
            x=x,
            y=y,
            z=float(travel_z),
            tip_extension=tip_ext,
        )


def _append_measure_targets(
    targets: list[ProtocolMotionTarget],
    *,
    step_args: dict[str, Any],
    deck: Deck,
    gantry: GantryConfig,
    pipette_tip_extension: float = 0.0,
) -> None:
    instrument = step_args.get("instrument")
    if not isinstance(instrument, str):
        return
    tip_ext = pipette_tip_extension if instrument == "pipette" else 0.0
    position = step_args.get("position")
    measurement_height = step_args.get("measurement_height")
    x_offset = _height_arg(step_args, "x_offset_mm")
    y_offset = _height_arg(step_args, "y_offset_mm")
    if x_offset is None or y_offset is None:
        return
    _append_position_engage(
        targets,
        deck=deck,
        gantry=gantry,
        position=position,
        instrument=instrument,
        measurement_height=measurement_height,
        tip_extension=tip_ext,
        x_offset_mm=x_offset,
        y_offset_mm=y_offset,
    )
    if not isinstance(position, str):
        return
    indentation_limit_height = step_args.get("indentation_limit_height")
    if not _is_finite_number(indentation_limit_height):
        return
    coord = _resolve_deck_coord(deck, position)
    if coord is None:
        return

    method_kwargs = step_args.get("method_kwargs") or {}
    if isinstance(method_kwargs, dict) and method_kwargs.get("detect_surface"):
        # Surface detection anchors the limit to a Z found at runtime; the
        # statically-checkable worst case is a surface at the bottom of the
        # search window, with the indentation continuing below it.
        if not _is_finite_number(measurement_height):
            return
        from cubos.instruments.asmi.interface import (
            DEFAULT_SURFACE_SEARCH_MAX_TRAVEL_MM,
        )
        max_travel = method_kwargs.get(
            "surface_search_max_travel", DEFAULT_SURFACE_SEARCH_MAX_TRAVEL_MM,
        )
        if not _is_finite_number(max_travel):
            return
        deepest_z = (
            coord.z + float(measurement_height) - float(max_travel)
            + min(float(indentation_limit_height), 0.0)
        )
    else:
        deepest_z = coord.z + float(indentation_limit_height)

    _append_target(
        targets,
        target=position,
        suffix="indentation_limit_z",
        instrument=instrument,
        x=coord.x + x_offset,
        y=coord.y + y_offset,
        z=deepest_z,
        tip_extension=tip_ext,
    )


def _append_rinse_targets(
    targets: list[ProtocolMotionTarget],
    *,
    step_args: dict[str, Any],
    deck: Deck,
    gantry: GantryConfig,
) -> None:
    instrument = step_args.get("instrument")
    vial = step_args.get("vial")
    height = step_args.get("measurement_height")
    if (
        not isinstance(instrument, str)
        or not isinstance(vial, str)
        or not _is_finite_number(height)
    ):
        return
    try:
        target = deck.resolve_labware(vial)
    except (KeyError, ValueError):
        return
    if not isinstance(target, Vial):
        return
    coord = deck.resolve_coordinate(vial)
    for suffix in ("safe_z", "action_z"):
        z = gantry.resolved_safe_z if suffix == "safe_z" else coord.z + float(height)
        _append_target(
            targets, target=vial, suffix=suffix, instrument=instrument,
            x=coord.x, y=coord.y, z=z,
        )


def _append_scan_targets(
    targets: list[ProtocolMotionTarget],
    *,
    step_args: dict[str, Any],
    deck: Deck,
    gantry: GantryConfig,
    pipette_tip_extension: float = 0.0,
) -> None:
    instrument = step_args.get("instrument")
    plate = step_args.get("plate")
    measurement_height = step_args.get("measurement_height")
    interwell_scan_height = step_args.get("interwell_scan_height")
    x_offset = _height_arg(step_args, "x_offset_mm")
    y_offset = _height_arg(step_args, "y_offset_mm")
    if (
        not isinstance(instrument, str)
        or not isinstance(plate, str)
        or not _is_finite_number(measurement_height)
        or not _is_finite_number(interwell_scan_height)
        or x_offset is None
        or y_offset is None
    ):
        return
    tip_ext = pipette_tip_extension if instrument == "pipette" else 0.0

    plate_obj = _resolve_labware(deck, plate)
    if not isinstance(plate_obj, WellPlate):
        return

    try:
        ref_z = plate_obj.get_well_center("A1").z
    except KeyError:
        return

    action_z = ref_z + float(measurement_height)
    approach_z = ref_z + float(interwell_scan_height)
    sorted_wells = sorted(
        plate_obj.wells.items(), key=lambda item: _row_major_key(item[0]),
    )
    for well_index, (well_id, well) in enumerate(sorted_wells):
        well_target = f"{plate}.{well_id}"
        if well_index == 0:
            _append_target(
                targets,
                target=well_target,
                suffix="safe_z",
                instrument=instrument,
                x=well.x + x_offset,
                y=well.y + y_offset,
                z=gantry.resolved_safe_z,
                tip_extension=tip_ext,
            )
        _append_target(
            targets,
            target=well_target,
            suffix="approach_z",
            instrument=instrument,
            x=well.x + x_offset,
            y=well.y + y_offset,
            z=approach_z,
            tip_extension=tip_ext,
        )
        _append_target(
            targets,
            target=well_target,
            suffix="action_z",
            instrument=instrument,
            x=well.x + x_offset,
            y=well.y + y_offset,
            z=action_z,
            tip_extension=tip_ext,
        )


def _append_image_well_targets(
    targets: list[ProtocolMotionTarget],
    *,
    step_args: dict[str, Any],
    deck: Deck,
    gantry: GantryConfig,
) -> None:
    camera = step_args.get("camera")
    well = step_args.get("well")
    image_height = _height_arg(step_args, "image_height")
    x_offset = _height_arg(step_args, "x_offset_mm")
    y_offset = _height_arg(step_args, "y_offset_mm")
    if (
        not isinstance(camera, str)
        or not isinstance(well, str)
        or image_height is None
        or x_offset is None
        or y_offset is None
    ):
        return
    try:
        coord = deck.resolve_coordinate(well)
    except (KeyError, ValueError):
        return
    deepest_height = image_height
    if step_args.get("mode", "standard") == "curvature":
        z_steps = step_args.get("z_steps", 11)
        z_step_mm = step_args.get("z_step_mm", 0.2)
        if (
            isinstance(z_steps, int)
            and z_steps >= 1
            and _is_finite_number(z_step_mm)
        ):
            deepest_height -= (z_steps - 1) * float(z_step_mm)
    image_x = coord.x + x_offset
    image_y = coord.y + y_offset
    for suffix, z in (
        ("safe_z", gantry.resolved_safe_z),
        ("action_z", coord.z + deepest_height),
    ):
        _append_target(
            targets,
            target=well,
            suffix=suffix,
            instrument=camera,
            x=image_x,
            y=image_y,
            z=z,
        )


def _append_capper_targets(
    targets: list[ProtocolMotionTarget],
    *,
    command_name: str,
    step_args: dict[str, Any],
    deck: Deck,
    gantry: GantryConfig,
) -> None:
    instrument = step_args.get("instrument")
    vial = step_args.get("vial")
    x_offset = _height_arg(step_args, "x_offset_mm")
    y_offset = _height_arg(step_args, "y_offset_mm")
    if (
        not isinstance(instrument, str)
        or not isinstance(vial, str)
        or x_offset is None
        or y_offset is None
    ):
        return
    coord = _resolve_deck_coord(deck, vial)
    config = gantry.instruments.get(instrument, {})
    engage_depth = config.get("engage_depth_mm")
    if coord is None or not _is_finite_number(engage_depth):
        return
    x = coord.x + x_offset
    y = coord.y + y_offset
    action_z = coord.z + float(engage_depth)
    if command_name == "cap":
        overtravel = config.get("release_overtravel_mm", 0.0)
        if not _is_finite_number(overtravel):
            return
        action_z -= float(overtravel)
    for suffix, target_x, target_y, target_z in (
        ("safe_z", x, y, gantry.resolved_safe_z),
        ("action_z", x, y, action_z),
    ):
        _append_target(
            targets, target=vial, suffix=suffix, instrument=instrument,
            x=target_x, y=target_y, z=target_z,
        )
    if command_name == "decap":
        shimmy = config.get("decap_release_shimmy_y_mm", 0.0)
        if _is_finite_number(shimmy) and float(shimmy):
            _append_target(
                targets, target=vial, suffix="release_shimmy_y",
                instrument=instrument, x=x, y=y + float(shimmy), z=action_z,
            )


def _append_pipette_targets(
    targets: list[ProtocolMotionTarget],
    *,
    command_name: str,
    step_args: dict[str, Any],
    deck: Deck,
    gantry: GantryConfig,
    tip_extension: float,
) -> float:
    if command_name in {"aspirate", "blowout", "dispense", "mix"}:
        height = _height_arg(step_args, "height")
        x_offset = _height_arg(step_args, "x_offset_mm")
        y_offset = _height_arg(step_args, "y_offset_mm")
        if height is None or x_offset is None or y_offset is None:
            return tip_extension
        _append_position_engage(
            targets,
            deck=deck,
            gantry=gantry,
            position=step_args.get("position"),
            instrument="pipette",
            measurement_height=height,
            tip_extension=tip_extension,
            x_offset_mm=x_offset,
            y_offset_mm=y_offset,
        )
    elif command_name == "pick_up_tip":
        x_offset = _height_arg(step_args, "x_offset_mm")
        y_offset = _height_arg(step_args, "y_offset_mm")
        if x_offset is None or y_offset is None:
            return tip_extension
        _append_position_engage(
            targets,
            deck=deck,
            gantry=gantry,
            position=step_args.get("position"),
            instrument="pipette",
            measurement_height=0.0,
            tip_extension=tip_extension,
            x_offset_mm=x_offset,
            y_offset_mm=y_offset,
        )
        picked_up_tip_length = _tip_length_for_pickup(deck, step_args.get("position"))
        if picked_up_tip_length is not None:
            return picked_up_tip_length
    elif command_name == "drop_tip":
        x_offset = _height_arg(step_args, "x_offset_mm")
        y_offset = _height_arg(step_args, "y_offset_mm")
        if x_offset is None or y_offset is None:
            return tip_extension
        _append_position_engage(
            targets,
            deck=deck,
            gantry=gantry,
            position=step_args.get("position"),
            instrument="pipette",
            measurement_height=0.0,
            tip_extension=tip_extension,
            x_offset_mm=x_offset,
            y_offset_mm=y_offset,
        )
        return 0.0
    elif command_name == "transfer":
        for position_key, height_key, offset_prefix in (
            ("source", "source_height", "source"),
            ("destination", "destination_height", "destination"),
        ):
            height = _height_arg(step_args, height_key)
            x_offset = _height_arg(step_args, f"{offset_prefix}_x_offset_mm")
            y_offset = _height_arg(step_args, f"{offset_prefix}_y_offset_mm")
            if height is None or x_offset is None or y_offset is None:
                continue
            _append_position_engage(
                targets,
                deck=deck,
                gantry=gantry,
                position=step_args.get(position_key),
                instrument="pipette",
                measurement_height=height,
                tip_extension=tip_extension,
                x_offset_mm=x_offset,
                y_offset_mm=y_offset,
            )
    elif command_name == "serial_transfer":
        source_height = _height_arg(step_args, "source_height")
        source_x_offset = _height_arg(step_args, "source_x_offset_mm")
        source_y_offset = _height_arg(step_args, "source_y_offset_mm")
        if source_height is None:
            source_height = 0.0
        if source_x_offset is None or source_y_offset is None:
            return tip_extension
        _append_position_engage(
            targets,
            deck=deck,
            gantry=gantry,
            position=step_args.get("source"),
            instrument="pipette",
            measurement_height=source_height,
            tip_extension=tip_extension,
            x_offset_mm=source_x_offset,
            y_offset_mm=source_y_offset,
        )
        plate_name = step_args.get("plate")
        plate_obj = _resolve_labware(deck, plate_name)
        if not isinstance(plate_obj, WellPlate) or not isinstance(plate_name, str):
            return tip_extension
        destination_height = _height_arg(step_args, "destination_height")
        destination_x_offset = _height_arg(
            step_args, "destination_x_offset_mm",
        )
        destination_y_offset = _height_arg(
            step_args, "destination_y_offset_mm",
        )
        if (
            destination_height is None
            or destination_x_offset is None
            or destination_y_offset is None
        ):
            return tip_extension
        for well_id in _wells_for_axis(plate_obj, step_args.get("axis")):
            _append_position_engage(
                targets,
                deck=deck,
                gantry=gantry,
                position=f"{plate_name}.{well_id}",
                instrument="pipette",
                measurement_height=destination_height,
                tip_extension=tip_extension,
                x_offset_mm=destination_x_offset,
                y_offset_mm=destination_y_offset,
            )
    return tip_extension


def collect_protocol_motion_targets(
    gantry: GantryConfig,
    protocol: Protocol,
    deck: Deck,
) -> list[ProtocolMotionTarget]:
    """Return concrete working-volume targets implied by *protocol*.

    This intentionally ignores unused deck labware. A deck may contain fixture
    geometry or spare labware that is not reachable in the current run; setup
    bounds validation should only fail for points this protocol can command.
    """
    targets: list[ProtocolMotionTarget] = []
    pipette_tip_extension = 0.0
    for step in protocol.steps:
        if step.command_name == "move":
            _append_move_targets(
                targets,
                step_args=step.args,
                protocol=protocol,
                deck=deck,
                gantry=gantry,
                pipette_tip_extension=pipette_tip_extension,
            )
        elif step.command_name in {"measure", "cure"}:
            _append_measure_targets(
                targets,
                step_args=step.args,
                deck=deck,
                gantry=gantry,
                pipette_tip_extension=pipette_tip_extension,
            )
        elif step.command_name == "rinse":
            _append_rinse_targets(
                targets, step_args=step.args, deck=deck, gantry=gantry,
            )
        elif step.command_name == "scan":
            _append_scan_targets(
                targets,
                step_args=step.args,
                deck=deck,
                gantry=gantry,
                pipette_tip_extension=pipette_tip_extension,
            )
        elif step.command_name == "image_well":
            _append_image_well_targets(
                targets,
                step_args=step.args,
                deck=deck,
                gantry=gantry,
            )
        elif step.command_name in {"cap", "decap"}:
            _append_capper_targets(
                targets,
                command_name=step.command_name,
                step_args=step.args,
                deck=deck,
                gantry=gantry,
            )
        else:
            pipette_tip_extension = _append_pipette_targets(
                targets,
                command_name=step.command_name,
                step_args=step.args,
                deck=deck,
                gantry=gantry,
                tip_extension=pipette_tip_extension,
            )
    return targets


def validate_protocol_motion_bounds(
    gantry: GantryConfig,
    protocol: Protocol,
    deck: Deck,
    instrumented_gantry: InstrumentedGantry,
) -> list[BoundsViolation]:
    """Validate gantry positions for only the points this protocol can command."""
    violations: list[BoundsViolation] = []
    volume = gantry.working_volume
    for target in collect_protocol_motion_targets(gantry, protocol, deck):
        instrument = instrumented_gantry.instruments.get(target.instrument_name)
        if instrument is None:
            continue
        gx = target.x - instrument.offset_x
        gy = target.y - instrument.offset_y
        gz = target.z + instrument.depth + target.tip_extension
        for axis, bound_name, bound_value in _check_point(volume, gx, gy, gz):
            violations.append(BoundsViolation(
                labware_key=target.labware_key,
                position_id=target.position_id,
                instrument_name=target.instrument_name,
                coordinate_type="gantry",
                x=gx, y=gy, z=gz,
                axis=axis,
                bound_name=bound_name,
                bound_value=bound_value,
            ))
    return violations


def validate_deck_positions(
    gantry: GantryConfig, deck: Deck,
) -> List[BoundsViolation]:
    """Check every labware position is within the gantry working volume.

    Coordinates are validated in user-facing positive space.
    Returns a list of violations (empty if all pass).
    """
    violations: List[BoundsViolation] = []
    volume = gantry.working_volume
    for lw_key, pos_id, x, y, z in _get_all_positions(deck):
        for axis, bound_name, bound_value in _check_point(volume, x, y, z):
            violations.append(BoundsViolation(
                labware_key=lw_key,
                position_id=pos_id,
                instrument_name=None,
                coordinate_type="deck",
                x=x, y=y, z=z,
                axis=axis,
                bound_name=bound_name,
                bound_value=bound_value,
            ))
    return violations


def validate_gantry_positions(
    gantry: GantryConfig, deck: Deck, instrumented_gantry: InstrumentedGantry,
) -> List[BoundsViolation]:
    """For each instrument and deck position, compute gantry bounds.

    Gantry formula (from InstrumentedGantry.move), all in user-facing coordinates:
        gantry_x = position_x - instrument.offset_x
        gantry_y = position_y - instrument.offset_y
        gantry_z = position_z + instrument.depth

    Returns a list of violations (empty if all pass).
    """
    violations: List[BoundsViolation] = []
    volume = gantry.working_volume
    for instr_name, instrument in instrumented_gantry.instruments.items():
        for lw_key, pos_id, x, y, z in _get_all_positions(deck):
            gx = x - instrument.offset_x
            gy = y - instrument.offset_y
            gz = z + instrument.depth
            for axis, bound_name, bound_value in _check_point(volume, gx, gy, gz):
                violations.append(BoundsViolation(
                    labware_key=lw_key,
                    position_id=pos_id,
                    instrument_name=instr_name,
                    coordinate_type="gantry",
                    x=gx, y=gy, z=gz,
                    axis=axis,
                    bound_name=bound_name,
                    bound_value=bound_value,
                ))
    return violations
