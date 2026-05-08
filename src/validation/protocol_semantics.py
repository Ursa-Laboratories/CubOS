"""Semantic validation for protocol runtime movement assumptions.

The protocol model:

* ``measurement_height`` and ``interwell_scan_height`` are *labware-relative*
  offsets (mm above the well's calibrated surface Z; negative = below)
  and are first-class arguments to the protocol commands that use them.
* ``measurement_height`` is required on ``measure`` and ``scan``.
* ``interwell_scan_height`` is required on ``scan``.
* Instruments do not declare these heights.
* ``gantry.safe_z`` is the absolute deck-frame Z used for inter-labware
  travel and the entry approach for the first well of a scan. Resolved
  approach planes must satisfy ``well.z + interwell_scan_height <= safe_z``.
"""

from __future__ import annotations

import math
from typing import Any

from board.board import Board
from deck.deck import Deck
from deck.labware.well_plate import WellPlate
from gantry.gantry_config import GantryConfig
from gantry.machine_geometry import FixedStructureBox, fixed_structures_for_gantry
from protocol_engine.protocol import Protocol
from protocol_engine.scan_args import (
    NormalizedScanArguments,
    normalize_scan_arguments,
)

from .errors import ProtocolSemanticViolation

Point3D = tuple[float, float, float]


def _violation(step_index: int, command: str, message: str) -> ProtocolSemanticViolation:
    return ProtocolSemanticViolation(step_index, command, message)


def _finite_field_violation(
    step_index: int,
    command: str,
    field_name: str,
    value: Any,
) -> ProtocolSemanticViolation | None:
    """Return a per-field finite-number violation, or None when *value* passes.

    Mirrors the message format of ``_movement._assert_finite_number`` so a
    field name and the offending value (with type) are always surfaced.
    """
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        return _violation(
            step_index,
            command,
            f"{field_name} must be a finite number, got "
            f"{type(value).__name__} {value!r}.",
        )
    return None


def _resolved_safe_z(gantry: GantryConfig | None) -> float | None:
    if gantry is None:
        return None
    return gantry.resolved_safe_z


def _row_major_key(well_id: str) -> tuple[str, int]:
    return (well_id[0], int(well_id[1:]))


def _gantry_xyz_for_tip(
    board: Board,
    instrument: str,
    x: float,
    y: float,
    z: float,
) -> tuple[float, float, float]:
    instr = board.instruments[instrument]
    return (x - instr.offset_x, y - instr.offset_y, z + instr.depth)


def _format_box(box: FixedStructureBox) -> str:
    return (
        f"X[{box.x_min}, {box.x_max}] "
        f"Y[{box.y_min}, {box.y_max}] "
        f"Z[{box.z_min}, {box.z_max}]"
    )


def _segment_intersects_box(
    start: Point3D,
    end: Point3D,
    box: FixedStructureBox,
) -> bool:
    t_min = 0.0
    t_max = 1.0
    for start_value, end_value, low, high in (
        (start[0], end[0], box.x_min, box.x_max),
        (start[1], end[1], box.y_min, box.y_max),
        (start[2], end[2], box.z_min, box.z_max),
    ):
        delta = end_value - start_value
        if delta == 0:
            if start_value < low or start_value > high:
                return False
            continue
        t1 = (low - start_value) / delta
        t2 = (high - start_value) / delta
        axis_min = min(t1, t2)
        axis_max = max(t1, t2)
        t_min = max(t_min, axis_min)
        t_max = min(t_max, axis_max)
        if t_min > t_max:
            return False
    return True


def _validate_machine_structure_point(
    *,
    step_index: int,
    command_name: str,
    gantry: GantryConfig | None,
    label: str,
    instrument: str,
    x: float,
    y: float,
    z: float,
) -> list[ProtocolSemanticViolation]:
    if gantry is None:
        return []

    violations: list[ProtocolSemanticViolation] = []
    for box in fixed_structures_for_gantry(gantry):
        if box.contains(x, y, z):
            violations.append(_violation(
                step_index,
                command_name,
                f"{label} instrument point ({x}, {y}, {z}) will hit the "
                f"{box.name} ({_format_box(box)}) for instrument {instrument!r}.",
            ))
    return violations


def _validate_machine_structure_segment(
    *,
    step_index: int,
    command_name: str,
    gantry: GantryConfig | None,
    label: str,
    instrument: str,
    start: Point3D,
    end: Point3D,
) -> list[ProtocolSemanticViolation]:
    if gantry is None:
        return []

    violations: list[ProtocolSemanticViolation] = []
    for box in fixed_structures_for_gantry(gantry):
        if _segment_intersects_box(start, end, box):
            violations.append(_violation(
                step_index,
                command_name,
                f"{label} travel segment from {start} to {end} will hit "
                f"the {box.name} ({_format_box(box)}) for "
                f"instrument {instrument!r}.",
            ))
    return violations


def _transit_segments(
    current: Point3D,
    target: Point3D,
    travel_z: float,
) -> list[tuple[str, Point3D, Point3D]]:
    current_x, current_y = current[0], current[1]
    target_x, target_y = target[0], target[1]
    travel_start = (current_x, current_y, travel_z)
    x_done = (target_x, current_y, travel_z)
    y_done = (target_x, target_y, travel_z)
    segments = [
        ("travel_z lift/lower", current, travel_start),
        ("travel_z X travel", travel_start, x_done),
        ("travel_z Y travel", x_done, y_done),
        ("travel_z final Z", y_done, target),
    ]
    return [segment for segment in segments if segment[1] != segment[2]]


def _validate_known_transit(
    *,
    step_index: int,
    command_name: str,
    gantry: GantryConfig | None,
    label: str,
    instrument: str,
    current: Point3D | None,
    target: Point3D,
    travel_z: float,
) -> list[ProtocolSemanticViolation]:
    if current is None:
        return []

    violations: list[ProtocolSemanticViolation] = []
    for segment_label, start, end in _transit_segments(current, target, travel_z):
        violations.extend(_validate_machine_structure_segment(
            step_index=step_index,
            command_name=command_name,
            gantry=gantry,
            label=f"{label} {segment_label}",
            instrument=instrument,
            start=start,
            end=end,
        ))
    return violations


def _home_pose_for_instrument(
    gantry: GantryConfig,
    instrument: Any,
) -> Point3D:
    volume = gantry.working_volume
    return (
        volume.x_max + instrument.offset_x,
        volume.y_max + instrument.offset_y,
        volume.z_max - instrument.depth,
    )


def _validate_home_waypoints(
    *,
    step_index: int,
    board: Board,
    gantry: GantryConfig | None,
    current_poses: dict[str, Point3D],
) -> list[ProtocolSemanticViolation]:
    if gantry is None:
        current_poses.clear()
        return []

    violations: list[ProtocolSemanticViolation] = []
    for instrument_name, instrument in board.instruments.items():
        pose = _home_pose_for_instrument(gantry, instrument)
        violations.extend(_validate_machine_structure_point(
            step_index=step_index,
            command_name="home",
            gantry=gantry,
            label="home pose",
            instrument=instrument_name,
            x=pose[0],
            y=pose[1],
            z=pose[2],
        ))
        current_poses[instrument_name] = pose
    return violations


def _validate_gantry_waypoint(
    *,
    step_index: int,
    command_name: str,
    gantry: GantryConfig | None,
    label: str,
    instrument: str,
    board: Board,
    x: float,
    y: float,
    z: float,
) -> list[ProtocolSemanticViolation]:
    if gantry is None or instrument not in board.instruments:
        return []

    gx, gy, gz = _gantry_xyz_for_tip(board, instrument, x, y, z)
    volume = gantry.working_volume
    violations: list[ProtocolSemanticViolation] = []
    for axis, value, low, high in (
        ("x", gx, volume.x_min, volume.x_max),
        ("y", gy, volume.y_min, volume.y_max),
        ("z", gz, volume.z_min, volume.z_max),
    ):
        if value < low or value > high:
            violations.append(_violation(
                step_index,
                command_name,
                f"{label} gantry {axis}={value} is outside working volume "
                f"[{low}, {high}] for instrument {instrument!r}.",
            ))

    violations.extend(_validate_machine_structure_point(
        step_index=step_index,
        command_name=command_name,
        gantry=gantry,
        label=label,
        instrument=instrument,
        x=x,
        y=y,
        z=z,
    ))
    return violations


def _validate_below_safe_z(
    *,
    step_index: int,
    command_name: str,
    label: str,
    z: float | None,
    gantry: GantryConfig | None,
) -> list[ProtocolSemanticViolation]:
    """Verify that absolute Z *z* is at or below ``safe_z`` (the ceiling)."""
    safe_z = _resolved_safe_z(gantry)
    if safe_z is None or z is None:
        return []
    if z > safe_z:
        return [_violation(
            step_index,
            command_name,
            f"{label} ({z}) is above the gantry's safe_z ({safe_z}). "
            "All resolved action and approach Z values must satisfy "
            "z <= safe_z so the gantry can retract above them.",
        )]
    return []


def _validate_scan_points(
    *,
    step_index: int,
    plate: str,
    instrument: str,
    board: Board,
    gantry: GantryConfig | None,
    wells: list[tuple[str, Any]],
    action_abs: float,
    approach_abs: float,
    safe_z: float | None,
) -> list[ProtocolSemanticViolation]:
    violations: list[ProtocolSemanticViolation] = []
    for well_index, (well_id, well) in enumerate(wells):
        if well_index == 0 and safe_z is not None:
            violations.extend(_validate_gantry_waypoint(
                step_index=step_index,
                command_name="scan",
                gantry=gantry,
                label=f"{plate}.{well_id} safe_z",
                instrument=instrument,
                board=board,
                x=well.x,
                y=well.y,
                z=safe_z,
            ))
        violations.extend(_validate_gantry_waypoint(
            step_index=step_index,
            command_name="scan",
            gantry=gantry,
            label=f"{plate}.{well_id} action_z",
            instrument=instrument,
            board=board,
            x=well.x,
            y=well.y,
            z=action_abs,
        ))
        violations.extend(_validate_gantry_waypoint(
            step_index=step_index,
            command_name="scan",
            gantry=gantry,
            label=f"{plate}.{well_id} approach_z",
            instrument=instrument,
            board=board,
            x=well.x,
            y=well.y,
            z=approach_abs,
        ))
    return violations


def _validate_scan_segments(
    *,
    step_index: int,
    plate: str,
    instrument: str,
    gantry: GantryConfig | None,
    wells: list[tuple[str, Any]],
    current: Point3D | None,
    action_abs: float,
    approach_abs: float,
    safe_z: float | None,
) -> tuple[list[ProtocolSemanticViolation], Point3D | None]:
    violations: list[ProtocolSemanticViolation] = []
    pose = current

    for well_index, (well_id, well) in enumerate(wells):
        approach = (well.x, well.y, approach_abs)
        action = (well.x, well.y, action_abs)

        if well_index == 0 and safe_z is not None:
            entry = (well.x, well.y, safe_z)
            violations.extend(_validate_known_transit(
                step_index=step_index,
                command_name="scan",
                gantry=gantry,
                label=f"{plate}.{well_id} safe_z",
                instrument=instrument,
                current=pose,
                target=entry,
                travel_z=safe_z,
            ))
            violations.extend(_validate_machine_structure_segment(
                step_index=step_index,
                command_name="scan",
                gantry=gantry,
                label=f"{plate}.{well_id} safe_z to approach_z",
                instrument=instrument,
                start=entry,
                end=approach,
            ))
        elif well_index > 0:
            violations.extend(_validate_known_transit(
                step_index=step_index,
                command_name="scan",
                gantry=gantry,
                label=f"{plate}.{well_id} approach_z",
                instrument=instrument,
                current=pose,
                target=approach,
                travel_z=approach_abs,
            ))

        violations.extend(_validate_machine_structure_segment(
            step_index=step_index,
            command_name="scan",
            gantry=gantry,
            label=f"{plate}.{well_id} action_z descend",
            instrument=instrument,
            start=approach,
            end=action,
        ))
        pose = action

    if wells and pose is not None:
        last_well_id, last_well = wells[-1]
        final_approach = (last_well.x, last_well.y, approach_abs)
        violations.extend(_validate_machine_structure_segment(
            step_index=step_index,
            command_name="scan",
            gantry=gantry,
            label=f"{plate}.{last_well_id} final approach_z",
            instrument=instrument,
            start=pose,
            end=final_approach,
        ))
        pose = final_approach

    return violations, pose


def _validate_scan_command(
    *,
    step_index: int,
    args: dict[str, Any],
    board: Board,
    deck: Deck,
    gantry: GantryConfig | None,
    current_poses: dict[str, Point3D],
) -> list[ProtocolSemanticViolation]:
    violations: list[ProtocolSemanticViolation] = []

    try:
        normalized = normalize_scan_arguments(
            method_kwargs=args.get("method_kwargs"),
        )
    except ValueError as exc:
        return [_violation(step_index, "scan", str(exc))]

    relative_action = args.get("measurement_height")
    relative_approach = args.get("interwell_scan_height")
    if relative_action is None:
        violations.append(_violation(
            step_index,
            "scan",
            "`measurement_height` is required on `scan` (labware-relative "
            "offset, mm above the well's calibrated surface Z).",
        ))
        return violations
    if relative_approach is None:
        violations.append(_violation(
            step_index,
            "scan",
            "`interwell_scan_height` is required on `scan` (labware-relative "
            "offset for between-wells XY travel).",
        ))
        return violations

    instrument = args.get("instrument")
    plate = args.get("plate")
    if instrument not in board.instruments or plate not in deck:
        return violations
    plate_obj = deck[plate]
    if not isinstance(plate_obj, WellPlate):
        return violations

    try:
        ref_z = plate_obj.get_well_center("A1").z
    except KeyError:
        violations.append(_violation(
            step_index,
            "scan",
            f"plate {plate!r} has no calibrated A1 well; cannot resolve "
            "the surface Z reference for labware-relative heights.",
        ))
        return violations

    finite_violations = [
        v for v in (
            _finite_field_violation(
                step_index, "scan", "measurement_height", relative_action,
            ),
            _finite_field_violation(
                step_index, "scan", "interwell_scan_height", relative_approach,
            ),
        ) if v is not None
    ]
    if finite_violations:
        violations.extend(finite_violations)
        return violations

    if relative_approach < relative_action:
        violations.append(_violation(
            step_index,
            "scan",
            f"interwell_scan_height ({relative_approach}) is below "
            f"measurement_height ({relative_action}). In +Z-up, the "
            "approach must be at or above the action plane.",
        ))

    action_abs = ref_z + relative_action
    approach_abs = ref_z + relative_approach

    safe_z = _resolved_safe_z(gantry)
    if safe_z is not None and approach_abs > safe_z:
        violations.append(_violation(
            step_index,
            "scan",
            f"resolved approach Z ({approach_abs:.3f} = "
            f"{ref_z}+{relative_approach}) is above the gantry's safe_z "
            f"({safe_z}). Lower `interwell_scan_height` or raise `safe_z`.",
        ))

    sorted_wells = sorted(
        plate_obj.wells.items(),
        key=lambda item: _row_major_key(item[0]),
    )
    violations.extend(_validate_scan_points(
        step_index=step_index,
        plate=plate,
        instrument=instrument,
        board=board,
        gantry=gantry,
        wells=sorted_wells,
        action_abs=action_abs,
        approach_abs=approach_abs,
        safe_z=safe_z,
    ))

    segment_violations, final_pose = _validate_scan_segments(
        step_index=step_index,
        plate=plate,
        instrument=instrument,
        gantry=gantry,
        wells=sorted_wells,
        current=current_poses.get(instrument),
        action_abs=action_abs,
        approach_abs=approach_abs,
        safe_z=safe_z,
    )
    violations.extend(segment_violations)
    if final_pose is not None:
        current_poses[instrument] = final_pose

    violations.extend(_validate_asmi_indentation(
        step_index=step_index,
        args=args,
        ref_z=ref_z,
        relative_action=relative_action,
        normalized=normalized,
        board=board,
        gantry=gantry,
    ))
    indentation_limit_height = args.get("indentation_limit_height")
    if (
        indentation_limit_height is not None
        and isinstance(indentation_limit_height, (int, float))
        and not isinstance(indentation_limit_height, bool)
        and math.isfinite(float(indentation_limit_height))
        and indentation_limit_height > relative_action
    ):
        violations.append(_violation(
            step_index, "scan",
            f"indentation_limit_height ({indentation_limit_height}) is above "
            f"measurement_height ({relative_action}). The deepest descent "
            "plane must be at or below the action plane in +Z-up.",
        ))
    return violations


def _validate_measure_command(
    *,
    step_index: int,
    args: dict[str, Any],
    board: Board,
    deck: Deck,
    gantry: GantryConfig | None,
    current_poses: dict[str, Point3D],
) -> list[ProtocolSemanticViolation]:
    violations: list[ProtocolSemanticViolation] = []
    instrument = args.get("instrument")
    position = args.get("position")
    relative_action = args.get("measurement_height")

    if relative_action is None:
        violations.append(_violation(
            step_index,
            "measure",
            "`measurement_height` is required on `measure` (labware-relative "
            "offset, mm above the resolved coordinate's surface Z).",
        ))
        return violations

    if instrument not in board.instruments:
        return violations

    finite_violation = _finite_field_violation(
        step_index, "measure", "measurement_height", relative_action,
    )
    if finite_violation is not None:
        violations.append(finite_violation)
        return violations

    try:
        coord = deck.resolve(position)
    except (KeyError, AttributeError, ValueError):
        return violations

    action_abs = coord.z + relative_action
    action = (coord.x, coord.y, action_abs)
    safe_z = _resolved_safe_z(gantry)
    if safe_z is not None:
        safe_pose = (coord.x, coord.y, safe_z)
        violations.extend(_validate_gantry_waypoint(
            step_index=step_index,
            command_name="measure",
            gantry=gantry,
            label=f"measure {position!r} safe_z",
            instrument=instrument,
            board=board,
            x=safe_pose[0],
            y=safe_pose[1],
            z=safe_pose[2],
        ))
        violations.extend(_validate_known_transit(
            step_index=step_index,
            command_name="measure",
            gantry=gantry,
            label=f"measure {position!r} safe_z",
            instrument=instrument,
            current=current_poses.get(instrument),
            target=safe_pose,
            travel_z=safe_z,
        ))
        violations.extend(_validate_machine_structure_segment(
            step_index=step_index,
            command_name="measure",
            gantry=gantry,
            label=f"measure {position!r} action_z descend",
            instrument=instrument,
            start=safe_pose,
            end=action,
        ))

    violations.extend(_validate_gantry_waypoint(
        step_index=step_index,
        command_name="measure",
        gantry=gantry,
        label=f"measure {position!r} action_z",
        instrument=instrument,
        board=board,
        x=coord.x,
        y=coord.y,
        z=action_abs,
    ))
    violations.extend(_validate_below_safe_z(
        step_index=step_index,
        command_name="measure",
        label=f"measure {position!r} action_z",
        z=action_abs,
        gantry=gantry,
    ))
    current_poses[instrument] = action
    return violations


def _validate_move_waypoints(
    *,
    step_index: int,
    args: dict[str, Any],
    protocol: Protocol,
    board: Board,
    deck: Deck,
    gantry: GantryConfig | None,
    current_poses: dict[str, Point3D],
) -> list[ProtocolSemanticViolation]:
    violations: list[ProtocolSemanticViolation] = []
    instrument = args.get("instrument")
    position = args.get("position")
    travel_z = args.get("travel_z")
    if instrument not in board.instruments:
        return violations

    target: Point3D | None = None
    target_label = f"move target {position!r}"
    transit_z = travel_z
    if isinstance(position, (list, tuple)):
        target = (position[0], position[1], position[2])
    elif isinstance(position, str) and position in protocol.positions:
        named = protocol.positions[position]
        target = (named[0], named[1], named[2])
    elif isinstance(position, str):
        try:
            coord = deck.resolve(position)
        except (KeyError, AttributeError, ValueError) as exc:
            violations.append(_violation(
                step_index,
                "move",
                f"position {position!r} cannot be resolved on the deck: {exc}",
            ))
            return violations
        if travel_z is not None:
            violations.append(_violation(
                step_index,
                "move",
                "travel_z is only supported for literal/named XYZ targets, "
                f"not deck target {position!r}.",
            ))
            return violations
        safe_z = _resolved_safe_z(gantry)
        if safe_z is None:
            violations.append(_violation(
                step_index,
                "move",
                f"deck-target move to {position!r} requires gantry `safe_z` "
                "to be configured.",
            ))
            return violations
        target = (coord.x, coord.y, safe_z)
        target_label = f"move safe_z for {position!r}"
        transit_z = safe_z

    if target is None:
        return violations

    x, y, z = target
    violations.extend(_validate_gantry_waypoint(
        step_index=step_index,
        command_name="move",
        gantry=gantry,
        label=target_label,
        instrument=instrument,
        board=board,
        x=x,
        y=y,
        z=z,
    ))
    if travel_z is not None:
        violations.extend(_validate_gantry_waypoint(
            step_index=step_index,
            command_name="move",
            gantry=gantry,
            label=f"move travel_z for {position!r}",
            instrument=instrument,
            board=board,
            x=x,
            y=y,
            z=travel_z,
        ))
        violations.extend(_validate_below_safe_z(
            step_index=step_index,
            command_name="move",
            label=f"move travel_z for {position!r}",
            z=travel_z,
            gantry=gantry,
        ))
    if transit_z is not None:
        violations.extend(_validate_known_transit(
            step_index=step_index,
            command_name="move",
            gantry=gantry,
            label=target_label,
            instrument=instrument,
            current=current_poses.get(instrument),
            target=target,
            travel_z=transit_z,
        ))
    current_poses[instrument] = target
    return violations


def _validate_asmi_indentation(
    *,
    step_index: int,
    args: dict[str, Any],
    ref_z: float,
    relative_action: float,
    normalized: NormalizedScanArguments,
    board: Board,
    gantry: GantryConfig | None,
) -> list[ProtocolSemanticViolation]:
    """Bounds-check ASMI indentation against the working volume.

    ``indentation_limit_height`` is a *signed* labware-relative offset
    (mm above the well's calibrated surface Z; negative = below). The
    deepest absolute Z reached during the descent is
    ``ref_z + indentation_limit_height``.
    """
    # Match by *type* (not by the user-chosen instrument key) so a force
    # sensor named e.g. ``force_sensor`` or ``asmi_main`` still goes
    # through the depth-bound check. The deepest-Z bound is the only thing
    # protecting against driving the gantry through the deck.
    from instruments.asmi.driver import ASMI

    violations: list[ProtocolSemanticViolation] = []
    instrument = args.get("instrument")
    if (
        instrument not in board.instruments
        or not isinstance(board.instruments[instrument], ASMI)
        or args.get("method") != "indentation"
    ):
        return violations

    indentation_limit_height = args.get("indentation_limit_height")
    step_size = normalized.method_kwargs.get("step_size")

    if step_size is not None and step_size <= 0:
        violations.append(_violation(
            step_index,
            "scan",
            f"ASMI step_size must be positive, got {step_size}.",
        ))

    if indentation_limit_height is None or gantry is None:
        return violations
    deepest_abs = ref_z + indentation_limit_height
    if deepest_abs < gantry.working_volume.z_min:
        violations.append(_violation(
            step_index,
            "scan",
            f"ASMI indentation deepest absolute Z ({deepest_abs:.3f}) is "
            f"below working_volume.z_min ({gantry.working_volume.z_min}). "
            "Raise `indentation_limit_height`, raise the labware, or adjust "
            "z_min.",
        ))
    return violations


def validate_protocol_semantics(
    protocol: Protocol,
    board: Board,
    deck: Deck,
    gantry: GantryConfig | None = None,
) -> list[ProtocolSemanticViolation]:
    """Return protocol semantic violations that static bounds checks miss."""
    violations: list[ProtocolSemanticViolation] = []
    current_poses: dict[str, Point3D] = {}
    for step in protocol.steps:
        if step.command_name == "home":
            violations.extend(_validate_home_waypoints(
                step_index=step.index,
                board=board,
                gantry=gantry,
                current_poses=current_poses,
            ))
        elif step.command_name == "move":
            violations.extend(_validate_move_waypoints(
                step_index=step.index,
                args=step.args,
                protocol=protocol,
                board=board,
                deck=deck,
                gantry=gantry,
                current_poses=current_poses,
            ))
        elif step.command_name == "measure":
            violations.extend(_validate_measure_command(
                step_index=step.index,
                args=step.args,
                board=board,
                deck=deck,
                gantry=gantry,
                current_poses=current_poses,
            ))
        elif step.command_name == "scan":
            violations.extend(_validate_scan_command(
                step_index=step.index,
                args=step.args,
                board=board,
                deck=deck,
                gantry=gantry,
                current_poses=current_poses,
            ))
    return violations
