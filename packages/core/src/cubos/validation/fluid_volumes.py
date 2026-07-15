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

from typing import Any, Callable, Mapping, Optional

from cubos.deck.deck import Deck
from cubos.instruments.pipette.models import PipetteConfig
from cubos.protocol_engine.commands._liquid_selection import (
    LiquidSelectionError,
    select_stock_container,
    select_waste_container,
    target_position,
)
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


def _static_volume_lookup(
    volumes: dict[_ContainerKey, float],
) -> Callable[[Any], float]:
    """Simulated-volume lookup for ``_liquid_selection``: unseeded == 0 uL.

    Matches this module's own convention (see module docstring): a
    container absent from ``volumes`` starts at 0 uL, never "unknown" (that
    distinction only matters for the ``None``-tolerant runtime lookup in
    ``cubos.protocol_engine.commands.pipette._current_volume_lookup``).
    """
    def _lookup(target: Any) -> float:
        return volumes.get(_container_key(target), 0.0)
    return _lookup


def _resolve_stock_position(
    *,
    step_index: int,
    command_name: str,
    label: str,
    deck: Deck,
    volumes: dict[_ContainerKey, float],
    source: Any,
    solution: Any,
    volume_ul: float,
) -> tuple[Optional[str], list[ProtocolSemanticViolation]]:
    """Resolve a compound command's stock source, statically, for simulation.

    Mirrors ``cubos.protocol_engine.commands.pipette._resolve_stock_source``:
    exactly one of *source*/*solution* is expected (the semantic validator
    reports the shape error otherwise, so this silently no-ops here rather
    than duplicating that message).
    """
    if source is not None:
        return source, []
    if not isinstance(solution, str) or not solution.strip():
        return None, []
    try:
        target = select_stock_container(
            deck, solution, volume_ul, _static_volume_lookup(volumes),
        )
    except LiquidSelectionError as exc:
        return None, [_violation(step_index, command_name, f"{label}: {exc}")]
    return target_position(target), []


def _resolve_waste_position(
    *,
    step_index: int,
    command_name: str,
    label: str,
    deck: Deck,
    volumes: dict[_ContainerKey, float],
    waste: Any,
    solution: Any,
    volume_ul: float,
) -> tuple[Optional[str], list[ProtocolSemanticViolation]]:
    """Resolve a compound command's waste target, statically, for simulation."""
    if waste is not None:
        return waste, []
    try:
        target = select_waste_container(
            deck, volume_ul, _static_volume_lookup(volumes),
            solution=solution if isinstance(solution, str) else None,
        )
    except LiquidSelectionError as exc:
        return None, [_violation(step_index, command_name, f"{label}: {exc}")]
    return target_position(target), []


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _check_rinse_well(
    *,
    step_index: int,
    args: Mapping[str, Any],
    deck: Deck,
    volumes: dict[_ContainerKey, float],
    pipette_config: PipetteConfig | None,
) -> list[ProtocolSemanticViolation]:
    violations: list[ProtocolSemanticViolation] = []
    well = args.get("well")
    volume = args.get("volume_ul")
    cycles = args.get("cycles", 3)
    if not _is_number(volume) or not isinstance(cycles, int) or isinstance(cycles, bool) or cycles <= 0:
        return violations
    volume = float(volume)
    mix_repetitions = args.get("mix_repetitions", 0)
    mix_volume = args.get("mix_volume_ul")
    source = args.get("source")
    solution = args.get("solution")
    waste = args.get("waste")

    for cycle in range(cycles):
        source_position, source_violations = _resolve_stock_position(
            step_index=step_index, command_name="rinse_well",
            label=f"rinse_well cycle {cycle} fill", deck=deck, volumes=volumes,
            source=source, solution=solution, volume_ul=volume,
        )
        violations.extend(source_violations)
        if source_position is None:
            # Selection failure aborts the whole command at runtime (see
            # `pipette._resolve_stock_source`) -- later cycles never run,
            # so simulating a "remove" against a well that was never
            # filled would only produce a misleading follow-on violation.
            break
        violations.extend(_check_transfer(
            step_index=step_index, command_name="rinse_well", deck=deck,
            volumes=volumes, source=source_position, destination=well,
            volume_ul=volume, pipette_config=pipette_config,
            label=f"rinse_well cycle {cycle} fill {source_position!r} -> {well!r}",
        ))

        if isinstance(mix_repetitions, int) and not isinstance(mix_repetitions, bool) and mix_repetitions > 0:
            try:
                well_target = _resolve(deck, well)
            except (KeyError, ValueError):
                well_target = None
            if well_target is not None:
                available = volumes.get(_container_key(well_target), 0.0)
                needed = float(mix_volume) if _is_number(mix_volume) else volume
                if needed > available + 1e-6:
                    violations.append(_violation(
                        step_index, "rinse_well",
                        f"rinse_well cycle {cycle} mix {well!r} needs "
                        f"{needed:g} uL but only {available:g} uL will be "
                        "present at this point.",
                    ))

        waste_position, waste_violations = _resolve_waste_position(
            step_index=step_index, command_name="rinse_well",
            label=f"rinse_well cycle {cycle} remove", deck=deck, volumes=volumes,
            waste=waste, solution=solution, volume_ul=volume,
        )
        violations.extend(waste_violations)
        if waste_position is None:
            break
        violations.extend(_check_transfer(
            step_index=step_index, command_name="rinse_well", deck=deck,
            volumes=volumes, source=well, destination=waste_position,
            volume_ul=volume, pipette_config=pipette_config,
            label=f"rinse_well cycle {cycle} remove {well!r} -> {waste_position!r}",
        ))
    return violations


def _check_flush_pipette(
    *,
    step_index: int,
    args: Mapping[str, Any],
    deck: Deck,
    volumes: dict[_ContainerKey, float],
    pipette_config: PipetteConfig | None,
) -> list[ProtocolSemanticViolation]:
    violations: list[ProtocolSemanticViolation] = []
    volume = args.get("volume_ul")
    cycles = args.get("cycles", 1)
    if not _is_number(volume) or not isinstance(cycles, int) or isinstance(cycles, bool) or cycles <= 0:
        return violations
    volume = float(volume)
    source = args.get("source")
    solution = args.get("solution")
    waste = args.get("waste")

    for cycle in range(cycles):
        source_position, source_violations = _resolve_stock_position(
            step_index=step_index, command_name="flush_pipette",
            label=f"flush_pipette cycle {cycle}", deck=deck, volumes=volumes,
            source=source, solution=solution, volume_ul=volume,
        )
        violations.extend(source_violations)
        waste_position, waste_violations = _resolve_waste_position(
            step_index=step_index, command_name="flush_pipette",
            label=f"flush_pipette cycle {cycle}", deck=deck, volumes=volumes,
            waste=waste, solution=solution, volume_ul=volume,
        )
        violations.extend(waste_violations)
        if source_position is None or waste_position is None:
            # Matches `pipette._resolve_stock_source`/`_resolve_waste_target`:
            # a selection failure aborts the whole command, so later cycles
            # never run and would only duplicate this violation.
            break
        if source_position is not None and waste_position is not None:
            violations.extend(_check_transfer(
                step_index=step_index, command_name="flush_pipette", deck=deck,
                volumes=volumes, source=source_position, destination=waste_position,
                volume_ul=volume, pipette_config=pipette_config,
                label=f"flush_pipette cycle {cycle} {source_position!r} -> "
                      f"{waste_position!r}",
            ))
    return violations


def _check_purge_pipette(
    *,
    step_index: int,
    args: Mapping[str, Any],
    deck: Deck,
    volumes: dict[_ContainerKey, float],
    pipette_config: PipetteConfig | None,
) -> list[ProtocolSemanticViolation]:
    violations: list[ProtocolSemanticViolation] = []
    volume = args.get("volume_ul")
    if not _is_number(volume):
        return violations
    volume = float(volume)
    source_position, source_violations = _resolve_stock_position(
        step_index=step_index, command_name="purge_pipette",
        label="purge_pipette", deck=deck, volumes=volumes,
        source=args.get("source"), solution=args.get("solution"), volume_ul=volume,
    )
    violations.extend(source_violations)
    waste_position, waste_violations = _resolve_waste_position(
        step_index=step_index, command_name="purge_pipette",
        label="purge_pipette", deck=deck, volumes=volumes,
        waste=args.get("waste"), solution=args.get("solution"), volume_ul=volume,
    )
    violations.extend(waste_violations)
    if source_position is not None and waste_position is not None:
        violations.extend(_check_transfer(
            step_index=step_index, command_name="purge_pipette", deck=deck,
            volumes=volumes, source=source_position, destination=waste_position,
            volume_ul=volume, pipette_config=pipette_config,
            label=f"purge_pipette {source_position!r} -> {waste_position!r}",
        ))
    return violations


def _check_clear_well(
    *,
    step_index: int,
    args: Mapping[str, Any],
    deck: Deck,
    volumes: dict[_ContainerKey, float],
    pipette_config: PipetteConfig | None,
) -> list[ProtocolSemanticViolation]:
    violations: list[ProtocolSemanticViolation] = []
    well = args.get("well")
    explicit_volume = args.get("volume_ul")
    if explicit_volume is not None:
        if not _is_number(explicit_volume):
            return violations
        removal_volume = float(explicit_volume)
    else:
        try:
            well_target = _resolve(deck, well)
        except (KeyError, ValueError):
            return violations
        target_volume = args.get("target_volume_ul", 0.0)
        target_volume = float(target_volume) if _is_number(target_volume) else 0.0
        removal_volume = volumes.get(_container_key(well_target), 0.0) - target_volume

    if removal_volume <= 1e-9:
        return violations

    waste_position, waste_violations = _resolve_waste_position(
        step_index=step_index, command_name="clear_well",
        label="clear_well", deck=deck, volumes=volumes,
        waste=args.get("waste"), solution=args.get("solution"),
        volume_ul=removal_volume,
    )
    violations.extend(waste_violations)
    if waste_position is not None:
        violations.extend(_check_transfer(
            step_index=step_index, command_name="clear_well", deck=deck,
            volumes=volumes, source=well, destination=waste_position,
            volume_ul=removal_volume, pipette_config=pipette_config,
            label=f"clear_well {well!r} -> {waste_position!r}",
        ))
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
        elif step.command_name == "rinse_well":
            violations.extend(_check_rinse_well(
                step_index=step.index, args=args, deck=deck, volumes=volumes,
                pipette_config=pipette_config,
            ))
        elif step.command_name == "flush_pipette":
            violations.extend(_check_flush_pipette(
                step_index=step.index, args=args, deck=deck, volumes=volumes,
                pipette_config=pipette_config,
            ))
        elif step.command_name == "purge_pipette":
            violations.extend(_check_purge_pipette(
                step_index=step.index, args=args, deck=deck, volumes=volumes,
                pipette_config=pipette_config,
            ))
        elif step.command_name == "clear_well":
            violations.extend(_check_clear_well(
                step_index=step.index, args=args, deck=deck, volumes=volumes,
                pipette_config=pipette_config,
            ))
    return violations


__all__ = ["validate_protocol_fluid_volumes"]
