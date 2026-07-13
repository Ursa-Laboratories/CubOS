"""Protocol commands for pipette operations."""

from __future__ import annotations

import logging
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
    from ..runtime import ProtocolContext


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


def _tracked_fluid_state(context: ProtocolContext) -> bool:
    """Return whether durable tracking is active, rejecting partial context.

    A normal campaign may have a data store without a fluid state. Once a
    ``fluid_state_id`` is present, however, both the store and campaign link
    are required before any motion or liquid actuation.
    """
    if context.fluid_state_id is None:
        return False
    missing = []
    if context.data_store is None:
        missing.append("data_store")
    if context.campaign_id is None:
        missing.append("campaign_id")
    if missing:
        raise ProtocolExecutionError(
            "Durable fluid tracking context is incomplete: fluid_state_id is "
            f"set but {', '.join(missing)} is missing. No motion was attempted."
        )
    return True


def _parse_position(position: str) -> tuple[str, Optional[str]]:
    """Compatibility helper that preserves nested labware paths.

    Runtime tracking resolves targets through :class:`deck.deck.Deck`; this
    helper remains for callers that only need the string split.
    """
    if "." not in position:
        return position, None
    labware_key, location_id = position.rsplit(".", 1)
    return labware_key, location_id


def _resolve_fluid_target(context: ProtocolContext, position: str):
    try:
        return context.deck.resolve_labware_target(position)
    except (KeyError, ValueError) as exc:
        raise ProtocolExecutionError(
            f"Cannot resolve tracked fluid target {position!r}: {exc}"
        ) from exc


def _begin_tracked_transfer(
    context: ProtocolContext,
    *,
    source: str,
    destination: str,
    volume_ul: float,
) -> tuple[str, bool]:
    """Preflight and journal a tracked transfer before liquid actuation.

    Returns the operation key and whether hardware should execute. ``False``
    means this exact campaign step was already applied and must not be replayed.
    """
    source_target = _resolve_fluid_target(context, source)
    destination_target = _resolve_fluid_target(context, destination)
    try:
        operation_key = context.fluid_operation_key("transfer")
        should_execute = context.data_store.begin_fluid_transfer(
            context.fluid_state_id,
            operation_key,
            source_target.labware_key,
            source_target.location_id,
            destination_target.labware_key,
            destination_target.location_id,
            volume_ul,
            campaign_id=context.campaign_id,
        )
    except Exception as exc:
        raise ProtocolExecutionError(
            f"Fluid-state preflight failed for {source!r} -> "
            f"{destination!r}: {type(exc).__name__}: {exc}"
        ) from exc
    return operation_key, should_execute


def _begin_tracked_mix(
    context: ProtocolContext,
    *,
    position: str,
    volume_ul: float,
    repetitions: int,
    speed: float,
    height: float,
) -> tuple[str, bool]:
    target = _resolve_fluid_target(context, position)
    try:
        operation_key = context.fluid_operation_key("mix")
        should_execute = context.data_store.begin_fluid_mix(
            context.fluid_state_id,
            operation_key,
            target,
            volume_ul,
            repetitions,
            speed,
            height,
            campaign_id=context.campaign_id,
        )
    except Exception as exc:
        raise ProtocolExecutionError(
            f"Fluid-state mix preflight failed for {position!r}: "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    return operation_key, should_execute


def _record_transfer_to_store(
    context: ProtocolContext,
    source: str,
    destination: str,
    volume_ul: float,
) -> None:
    """Persist an ordinary campaign transfer using canonical deck identity."""
    if context.data_store is not None and context.campaign_id is not None:
        try:
            source_target = context.deck.resolve_labware_target(source)
            destination_target = context.deck.resolve_labware_target(destination)
            context.data_store.record_transfer(
                context.campaign_id,
                source_target.labware_key,
                source_target.location_id,
                destination_target.labware_key,
                destination_target.location_id,
                volume_ul,
            )
        except Exception as exc:
            logger.warning(
                "Failed to record transfer from %s to %s: %s",
                source, destination, exc,
                exc_info=True,
            )


def _mark_transfer_uncertain(
    context: ProtocolContext,
    operation_key: str,
    exc: BaseException,
) -> None:
    """Best-effort marker for physical actions whose outcome needs review."""
    try:
        context.data_store.mark_fluid_reconciliation_required(
            operation_key,
            f"{type(exc).__name__}: {exc}",
        )
    except Exception:
        logger.exception(
            "Failed to mark fluid operation %s reconciliation-required",
            operation_key,
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
    if _tracked_fluid_state(context):
        raise ProtocolExecutionError(
            "Standalone aspirate is disabled while durable fluid tracking is "
            "active because it cannot conserve well/vial state without a "
            "known destination. Use transfer or serial_transfer."
        )
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
    if _tracked_fluid_state(context):
        raise ProtocolExecutionError(
            "Standalone dispense is disabled while durable fluid tracking is "
            "active because its source is unknown. Use transfer or serial_transfer."
        )
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
    tracked = _tracked_fluid_state(context)
    pipette = _get_pipette(context)
    operation_key = None
    if tracked:
        operation_key, should_execute = _begin_tracked_mix(
            context,
            position=position,
            volume_ul=volume_ul,
            repetitions=repetitions,
            speed=speed,
            height=height,
        )
        if not should_execute:
            context.logger.info(
                "Skipping already-applied fluid operation %s", operation_key,
            )
            return None
    try:
        _engage(context, position, command_label="mix", height=height)
        result = pipette.mix(volume_ul, repetitions, speed)
    except BaseException as exc:
        if operation_key is not None:
            _mark_transfer_uncertain(context, operation_key, exc)
        raise
    if operation_key is not None:
        try:
            context.data_store.complete_fluid_mix(operation_key)
        except Exception as exc:
            _mark_transfer_uncertain(context, operation_key, exc)
            raise ProtocolExecutionError(
                "Physical mix completed, but its fluid-state commit failed for "
                f"operation {operation_key!r}: {type(exc).__name__}: {exc}. "
                "Reconciliation is required."
            ) from exc
    return result


@protocol_command("pick_up_tip")
def pick_up_tip(
    context: ProtocolContext,
    position: str,
    speed: float = 50.0,
) -> None:
    """Move pipette to *position*, then pick up a tip.

    Tip-rack consumption is currently in-memory only. Re-running a protocol
    cannot know which physical slots were emptied by an earlier run; operators
    must refresh/replace racks or update the deck definition before reruns.
    """
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
    tracked = _tracked_fluid_state(context)
    pipette = _get_pipette(context)
    operation_key = None
    if tracked:
        operation_key, should_execute = _begin_tracked_transfer(
            context,
            source=source,
            destination=destination,
            volume_ul=volume_ul,
        )
        if not should_execute:
            context.logger.info(
                "Skipping already-applied fluid operation %s", operation_key,
            )
            return

    try:
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
    except BaseException as exc:
        if operation_key is not None:
            _mark_transfer_uncertain(context, operation_key, exc)
        raise

    if operation_key is not None:
        try:
            context.data_store.complete_fluid_transfer(operation_key)
        except Exception as exc:
            _mark_transfer_uncertain(context, operation_key, exc)
            raise ProtocolExecutionError(
                "Physical transfer completed, but its fluid-state commit "
                f"failed for operation {operation_key!r}: "
                f"{type(exc).__name__}: {exc}. Reconciliation is required."
            ) from exc
    else:
        _record_transfer_to_store(context, source, destination, volume_ul)


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

    previous_substep = context.active_substep
    try:
        for index, (well_id, vol) in enumerate(zip(well_ids, volumes)):
            destination = f"{plate}.{well_id}"
            context.active_substep = f"{index}:{destination}"
            transfer(context, source=source, destination=destination,
                     volume_ul=vol, speed=speed, source_height=source_height,
                     destination_height=destination_height)
    finally:
        context.active_substep = previous_substep
