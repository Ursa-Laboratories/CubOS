"""Offline fluid-volume validation for protocols with known initial fluids.

When an operator supplies a tracked initial-fluids seed (the same
``fluids:`` YAML shape ``cubos.data.load_initial_fluids`` accepts), the
liquid moved by a protocol becomes statically computable: this module walks
``transfer``/``serial_transfer``/``mix`` steps, simulates container volumes,
and reports the same before-motion guards ``transfer`` enforces at runtime
-- invalid volumes for the configured pipette model, source draws crossing a
vial's ``dead_volume_ul`` floor, and destination fills above
``working_volume_ul`` -- as ordinary semantic violations, so a doomed
protocol fails at validate time rather than mid-run.

Containers not named in the seed start at 0 uL: the seed is a complete
declaration of what liquid exists at protocol start.
"""

from __future__ import annotations

from typing import Any, Mapping

from cubos.deck.deck import Deck
from cubos.instruments.pipette.models import PipetteConfig
from cubos.protocol_engine.commands._liquid_transfer import (
    LiquidTransferPreflightError,
    plan_strokes,
    validate_dead_volume,
    validate_destination_overflow,
    vial_for_target,
    working_volume_for_target,
)
from cubos.protocol_engine.protocol import Protocol

from .errors import ProtocolSemanticViolation

_ContainerKey = tuple[str, str]


def _violation(step_index: int, command: str, message: str) -> ProtocolSemanticViolation:
    return ProtocolSemanticViolation(step_index, command, message)


def _resolve(deck: Deck, target: str):
    return deck.resolve_labware_target(target)


def _container_key(target: Any) -> _ContainerKey:
    return (target.labware_key, target.location_id or "")


def _seed_volumes(
    deck: Deck,
    initial_fluids: Mapping[str, Any],
) -> dict[_ContainerKey, float]:
    volumes: dict[_ContainerKey, float] = {}
    for name, definition in initial_fluids.items():
        target = _resolve(deck, name)
        volume = definition["volume_ul"] if isinstance(definition, Mapping) else definition
        volumes[_container_key(target)] = float(volume)
    return volumes


def _linspace(start: float, end: float, count: int) -> list[float]:
    if count == 1:
        return [start]
    step = (end - start) / (count - 1)
    return [start + index * step for index in range(count)]


def _serial_transfer_volumes(args: Mapping[str, Any], well_count: int) -> list[float]:
    volumes = args.get("volumes")
    if volumes is not None:
        return [float(volume) for volume in volumes]
    volume_range = args.get("volume_range")
    if volume_range is not None and len(volume_range) == 2 and well_count > 0:
        return _linspace(float(volume_range[0]), float(volume_range[1]), well_count)
    return []


def _wells_for_axis(plate: Any, axis: Any) -> list[str]:
    if not isinstance(axis, str) or not hasattr(plate, "wells"):
        return []
    if axis.isalpha():
        wells = [well for well in plate.wells if well[0] == axis.upper()]
    else:
        wells = [well for well in plate.wells if well[1:] == axis]
    return sorted(wells, key=lambda well: (well[0], int(well[1:])))


def _check_transfer(
    *,
    step_index: int,
    command_name: str,
    deck: Deck,
    volumes: dict[_ContainerKey, float],
    source: Any,
    destination: Any,
    volume_ul: float,
    pipette_config: PipetteConfig | None,
    label: str,
) -> list[ProtocolSemanticViolation]:
    """Validate and apply one logical transfer against the simulated volumes.

    The projected state is advanced even when a violation fires, so one bad
    step doesn't cascade misleading follow-on errors.
    """
    violations: list[ProtocolSemanticViolation] = []
    try:
        source_target = _resolve(deck, source)
        destination_target = _resolve(deck, destination)
    except (KeyError, ValueError) as exc:
        return [_violation(
            step_index, command_name,
            f"{label}: cannot resolve fluid target: {exc}",
        )]

    try:
        plan_strokes(volume_ul, pipette_config)
    except LiquidTransferPreflightError as exc:
        violations.append(_violation(step_index, command_name, f"{label}: {exc}"))

    source_key = _container_key(source_target)
    destination_key = _container_key(destination_target)
    source_volume = volumes.get(source_key, 0.0)
    destination_volume = volumes.get(destination_key, 0.0)

    source_vial = vial_for_target(source_target)
    dead_volume_ul = (
        float(source_vial.dead_volume_ul) if source_vial is not None else 0.0
    )
    if volume_ul > 0:
        try:
            validate_dead_volume(
                source_current_volume_ul=source_volume,
                dead_volume_ul=dead_volume_ul,
                requested_volume_ul=volume_ul,
                source_label=str(source),
            )
        except LiquidTransferPreflightError as exc:
            violations.append(_violation(step_index, command_name, f"{label}: {exc}"))

        working_volume = working_volume_for_target(destination_target)
        if working_volume is not None:
            try:
                validate_destination_overflow(
                    destination_current_volume_ul=destination_volume,
                    working_volume_ul=working_volume,
                    requested_volume_ul=volume_ul,
                    destination_label=str(destination),
                )
            except LiquidTransferPreflightError as exc:
                violations.append(
                    _violation(step_index, command_name, f"{label}: {exc}")
                )

        volumes[source_key] = max(0.0, source_volume - volume_ul)
        volumes[destination_key] = destination_volume + volume_ul
    return violations


def validate_protocol_fluid_volumes(
    protocol: Protocol,
    deck: Deck,
    initial_fluids: Mapping[str, Any],
    pipette_config: PipetteConfig | None = None,
) -> list[ProtocolSemanticViolation]:
    """Statically simulate protocol liquid handling against seeded volumes.

    *initial_fluids* is the normalized mapping ``load_initial_fluids``
    returns (``{target: {"volume_ul": ..., "composition": ...}}``);
    *pipette_config* enables per-model volume-bound checks (min/max/split
    feasibility) when the configured pipette model is known.
    """
    violations: list[ProtocolSemanticViolation] = []
    volumes = _seed_volumes(deck, initial_fluids)

    for step in protocol.steps:
        args = step.args
        if step.command_name == "transfer":
            volume = args.get("volume_ul")
            if not isinstance(volume, (int, float)) or isinstance(volume, bool):
                continue  # schema-level validation reports the type error
            violations.extend(_check_transfer(
                step_index=step.index,
                command_name="transfer",
                deck=deck,
                volumes=volumes,
                source=args.get("source"),
                destination=args.get("destination"),
                volume_ul=float(volume),
                pipette_config=pipette_config,
                label=f"transfer {args.get('source')!r} -> "
                      f"{args.get('destination')!r}",
            ))
        elif step.command_name == "serial_transfer":
            plate_name = args.get("plate")
            try:
                plate = deck.resolve_labware(plate_name)
            except (KeyError, ValueError):
                continue  # semantic validator reports the unknown plate
            well_ids = _wells_for_axis(plate, args.get("axis"))
            step_volumes = _serial_transfer_volumes(args, len(well_ids))
            if len(step_volumes) != len(well_ids):
                continue  # runtime command validation reports the mismatch
            for well_id, volume in zip(well_ids, step_volumes):
                violations.extend(_check_transfer(
                    step_index=step.index,
                    command_name="serial_transfer",
                    deck=deck,
                    volumes=volumes,
                    source=args.get("source"),
                    destination=f"{plate_name}.{well_id}",
                    volume_ul=volume,
                    pipette_config=pipette_config,
                    label=f"serial_transfer {args.get('source')!r} -> "
                          f"{plate_name}.{well_id}",
                ))
        elif step.command_name == "mix":
            volume = args.get("volume_ul")
            position = args.get("position")
            if not isinstance(volume, (int, float)) or isinstance(volume, bool):
                continue
            try:
                target = _resolve(deck, position)
            except (KeyError, ValueError):
                continue
            available = volumes.get(_container_key(target), 0.0)
            if float(volume) > available + 1e-6:
                violations.append(_violation(
                    step.index, "mix",
                    f"mix {position!r} needs {float(volume):g} uL but only "
                    f"{available:g} uL will be present at this step.",
                ))
    return violations


__all__ = ["validate_protocol_fluid_volumes"]
