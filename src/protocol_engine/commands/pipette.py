"""Protocol commands for pipette operations."""

from __future__ import annotations

import logging
import sqlite3
from typing import TYPE_CHECKING, Any, List, Optional

from deck.labware.tip_rack import (
    TipRackResolutionError,
    resolve_tip_rack_slot,
)
from deck.labware.well_plate import WellPlate

from ..errors import ProtocolExecutionError
from ..registry import protocol_command
from ._movement import engage_at_labware

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ..protocol import ProtocolContext


def _get_pipette(context: ProtocolContext):
    """Return the pipette instrument or raise ProtocolExecutionError."""
    if "pipette" not in context.gantry.instruments:
        raise ProtocolExecutionError(
            "No pipette registered on the gantry. "
            "Add one under the gantry YAML top-level `instruments` key."
        )
    return context.gantry.instruments["pipette"]


def _engage(
    context: ProtocolContext,
    position: str,
    *,
    command_label: str,
    height: float = 0.0,
) -> float:
    """Wrap ``engage_at_labware`` so configuration errors surface as
    ``ProtocolExecutionError`` instead of bare ``ValueError``s — matching
    how ``measure`` and ``scan`` handle their command boundary.

    Pipette commands default to the resolved labware coordinate
    (``height=0``). ``height`` is a labware-relative
    offset in the same convention as ``measurement_height`` for measure/scan."""
    try:
        _, action_z = engage_at_labware(
            context, "pipette", position,
            measurement_height=height, command_label=command_label,
        )
        return action_z
    except ValueError as exc:
        raise ProtocolExecutionError(str(exc)) from exc


def _parse_position(position: str) -> tuple[str, Optional[str]]:
    """Split ``"plate_1.A1"`` into ``("plate_1", "A1")`` or ``"vial_1"`` into ``("vial_1", None)``."""
    parts = position.split(".", 1)
    if len(parts) == 2:
        return (parts[0], parts[1])
    return (parts[0], None)


def _record_dispense_to_store(
    context: ProtocolContext,
    labware_key: str,
    well_id: Optional[str],
    source_name: str,
    volume_ul: float,
) -> None:
    """Persist a dispense to the DataStore if one is configured."""
    if context.data_store is not None and context.campaign_id is not None:
        try:
            context.data_store.record_dispense(
                context.campaign_id, labware_key, well_id, source_name, volume_ul,
            )
        except (sqlite3.Error, ValueError, KeyError) as exc:
            logger.warning(
                "Failed to record dispense for %s well %s: %s",
                labware_key, well_id, exc,
            )


@protocol_command("aspirate")
def aspirate(
    context: ProtocolContext,
    position: str,
    volume_ul: float,
    speed: float = 50.0,
    height: float = 0.0,
) -> Any:
    """Move pipette to *position*, then aspirate."""
    pipette = _get_pipette(context)
    _engage(context, position, command_label="aspirate", height=height)
    return pipette.aspirate(volume_ul, speed)


def dispense(
    context: ProtocolContext,
    position: str,
    volume_ul: float,
    speed: float = 50.0,
    height: float = 0.0,
) -> Any:
    """Move pipette to *position*, then dispense.

    Not exposed as a YAML protocol command — use ``transfer`` instead,
    which correctly tracks source labware for DB logging.
    """
    pipette = _get_pipette(context)
    _engage(context, position, command_label="dispense", height=height)
    return pipette.dispense(volume_ul, speed)


@protocol_command("blowout")
def blowout(
    context: ProtocolContext,
    position: str,
    speed: float = 50.0,
    height: float = 0.0,
) -> None:
    """Move pipette to *position*, then blowout."""
    pipette = _get_pipette(context)
    _engage(context, position, command_label="blowout", height=height)
    pipette.blowout(speed)


@protocol_command("mix")
def mix(
    context: ProtocolContext,
    position: str,
    volume_ul: float,
    repetitions: int = 3,
    speed: float = 50.0,
    height: float = 0.0,
) -> Any:
    """Move pipette to *position*, then mix."""
    pipette = _get_pipette(context)
    _engage(context, position, command_label="mix", height=height)
    return pipette.mix(volume_ul, repetitions, speed)


@protocol_command("pick_up_tip")
def pick_up_tip(
    context: ProtocolContext,
    position: str,
    speed: float = 50.0,
) -> None:
    """Move pipette to *position*, then pick up a tip."""
    pipette = _get_pipette(context)
    try:
        rack, tip_id = resolve_tip_rack_slot(context.deck, position)
    except TipRackResolutionError as exc:
        raise ProtocolExecutionError(str(exc)) from exc
    if tip_id is None:
        raise ProtocolExecutionError(
            f"pick_up_tip position {position!r} must include an explicit "
            "tip slot such as `tips.A1`."
        )
    if not rack.is_tip_present(tip_id):
        raise ProtocolExecutionError(
            f"pick_up_tip target {position!r} is not available "
            "(slot is unknown or already consumed)."
        )
    _engage(context, position, command_label="pick_up_tip")
    pipette.pick_up_tip(speed)
    pipette.set_attached_tip_extension(rack.tip_length)
    rack.mark_tip_used(tip_id)


@protocol_command("transfer")
def transfer(
    context: ProtocolContext,
    source: str,
    destination: str,
    volume_ul: float,
    speed: float = 50.0,
    source_height: float = 0.0,
    destination_height: float = 0.0,
) -> None:
    """Aspirate from *source* and dispense into *destination*."""
    pipette = _get_pipette(context)
    _engage(
        context, source, command_label="transfer.aspirate",
        height=source_height,
    )
    pipette.aspirate(volume_ul, speed)
    _engage(
        context, destination, command_label="transfer.dispense",
        height=destination_height,
    )
    pipette.dispense(volume_ul, speed)

    source_key, _ = _parse_position(source)
    dest_key, dest_well = _parse_position(destination)
    _record_dispense_to_store(context, dest_key, dest_well, source_key, volume_ul)


@protocol_command("drop_tip")
def drop_tip(
    context: ProtocolContext,
    position: str,
    speed: float = 50.0,
) -> None:
    """Move pipette to *position*, then drop the tip."""
    pipette = _get_pipette(context)
    _engage(context, position, command_label="drop_tip")
    pipette.drop_tip(speed)
    pipette.clear_attached_tip_extension()


# -- Compound helpers ----------------------------------------------------------


def _linspace(start: float, end: float, n: int) -> list:
    """Return *n* evenly spaced values from *start* to *end* inclusive."""
    if n == 1:
        return [start]
    step = (end - start) / (n - 1)
    return [start + i * step for i in range(n)]


def _wells_for_axis(plate: WellPlate, axis: str) -> list:
    """Return well IDs along *axis* in natural order.

    If *axis* is a letter (e.g. ``"A"``), returns the row (A1, A2, ...).
    If *axis* is a digit string (e.g. ``"3"``), returns the column (A3, B3, ...).
    """
    if axis.isalpha():
        wells = [w for w in plate.wells if w[0] == axis.upper()]
    else:
        wells = [w for w in plate.wells if w[1:] == axis]
    return sorted(wells, key=lambda w: (w[0], int(w[1:])))


@protocol_command("serial_transfer")
def serial_transfer(
    context: ProtocolContext,
    source: str,
    plate: str,
    axis: str,
    volumes: Optional[List[float]] = None,
    volume_range: Optional[List[float]] = None,
    speed: float = 50.0,
    source_height: float = 0.0,
    destination_height: float = 0.0,
) -> None:
    """Transfer from *source* to each well along a row or column.

    Provide exactly one of *volumes* (explicit list) or *volume_range*
    ([min, max] linearly spaced across the axis).
    """
    _get_pipette(context)

    try:
        plate_obj = context.deck.resolve_labware(plate)
    except KeyError as exc:
        raise ProtocolExecutionError(str(exc)) from exc
    if not isinstance(plate_obj, WellPlate):
        raise ProtocolExecutionError(
            f"serial_transfer requires a WellPlate, but '{plate}' is "
            f"{type(plate_obj).__name__}."
        )

    well_ids = _wells_for_axis(plate_obj, axis)
    if not well_ids:
        raise ProtocolExecutionError(
            f"No wells found for axis '{axis}' on plate '{plate}'."
        )

    has_volumes = volumes is not None
    has_range = volume_range is not None
    if has_volumes == has_range:
        raise ProtocolExecutionError(
            "Provide exactly one of volumes or volume_range, not both or neither."
        )

    if has_range:
        volumes = _linspace(volume_range[0], volume_range[1], len(well_ids))

    if len(volumes) != len(well_ids):
        raise ProtocolExecutionError(
            f"volumes length ({len(volumes)}) does not match axis '{axis}' "
            f"well count ({len(well_ids)})."
        )

    for well_id, vol in zip(well_ids, volumes):
        destination = f"{plate}.{well_id}"
        transfer(context, source=source, destination=destination,
                 volume_ul=vol, speed=speed, source_height=source_height,
                 destination_height=destination_height)
