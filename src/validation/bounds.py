"""Bounds validation: deck positions and gantry-computed positions vs. gantry volume."""

from __future__ import annotations

from typing import List, Tuple

from board.board import Board
from deck.deck import Deck
from gantry.gantry_config import GantryConfig, WorkingVolume

from .errors import BoundsViolation


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
    """Extract every motion target as (labware_key, position_id, x, y, z)."""
    positions: List[Tuple[str, str, float, float, float]] = []
    for key in deck:
        labware = deck[key]
        for position_id, coord in labware.iter_motion_targets().items():
            positions.append((key, position_id, coord.x, coord.y, coord.z))
    return positions


def validate_deck_positions(
    gantry: GantryConfig, deck: Deck,
) -> List[BoundsViolation]:
    """Check every labware motion target is within the gantry working volume.

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
    gantry: GantryConfig, deck: Deck, board: Board,
) -> List[BoundsViolation]:
    """For each instrument and deck motion target, compute gantry bounds.

    Gantry formula (from board.py Board.move), all in user-facing coordinates:
        gantry_x = position_x - instrument.offset_x
        gantry_y = position_y - instrument.offset_y
        gantry_z = position_z + instrument.depth

    Returns a list of violations (empty if all pass).
    """
    violations: List[BoundsViolation] = []
    volume = gantry.working_volume
    for instr_name, instrument in board.instruments.items():
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
