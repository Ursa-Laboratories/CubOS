"""Offline simulation timeline: predicted per-step state and a rough duration.

Given a loaded protocol and deck (and, optionally, the fluids present at the
start), :func:`simulate_protocol` predicts after each step the container
volumes, tips consumed, and liquid held in the tip, plus a rough run-time
estimate. Nothing moves and nothing connects. Volume bookkeeping reuses
``validation.fluid_volumes`` (the same projection ``validate_setup`` runs), so
the timeline can never disagree with the preflight about what a step does.

Durations come from :class:`TimingModel`, whose defaults are assumptions rather
than measurements. Treat the total as an order-of-magnitude figure and replace
the model's numbers with measured ones for planning.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cubos.deck.deck import Deck
from cubos.deck.labware.tip_rack import TipRack
from cubos.instruments.pipette.models import PipetteConfig
from cubos.protocol_engine.commands._liquid_transfer import (
    LiquidTransferPreflightError,
    pipette_capacity,
    plan_strokes,
)
from cubos.protocol_engine.protocol import Protocol

from .errors import ProtocolSemanticViolation
from .fluid_volumes import (
    _container_key,
    _resolve,
    _serial_transfer_volumes,
    _wells_for_axis,
    project_step_volumes,
    seed_volumes,
)

_ContainerKey = tuple[str, str]

_PROJECTED_COMMANDS = frozenset({
    "transfer", "serial_transfer", "mix", "rinse_well", "flush_pipette",
    "purge_pipette", "clear_well",
})


@dataclass(frozen=True)
class TimingModel:
    """Assumed durations. Defaults are placeholders, not measurements."""

    travel_mm_per_s: float = 25.0
    plunger_stroke_s: float = 4.0
    plunger_overhead_s: float = 0.5
    blowout_s: float = 3.0
    tip_pickup_s: float = 3.0
    tip_drop_s: float = 2.0
    pipette_home_s: float = 2.0
    gantry_home_s: float = 30.0
    unknown_leg_travel_s: float = 6.0
    default_safe_z_lift_mm: float = 0.0

    def plunger_s(self, volume_ul: float, speed: float, max_volume_ul: float) -> float:
        flow = max_volume_ul / self.plunger_stroke_s * max(speed, 1.0) / 50.0
        return self.plunger_overhead_s + volume_ul / flow


@dataclass(frozen=True)
class TimelineStep:
    index: int
    command: str
    start_s: float
    duration_s: float
    volumes_ul: Mapping[str, float] | None
    changed_ul: Mapping[str, float]
    loaded_ul: float
    tip_attached: bool
    tips_used: int
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "command": self.command,
            "start_s": round(self.start_s, 3),
            "duration_s": round(self.duration_s, 3),
            "volumes_ul": None if self.volumes_ul is None else dict(self.volumes_ul),
            "changed_ul": dict(self.changed_ul),
            "loaded_ul": self.loaded_ul,
            "tip_attached": self.tip_attached,
            "tips_used": self.tips_used,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class SimulationTimeline:
    steps: tuple[TimelineStep, ...]
    total_duration_s: float
    initial_volumes_ul: Mapping[str, float] | None
    final_volumes_ul: Mapping[str, float] | None
    tips_used: int
    tips_available: int
    violations: tuple[ProtocolSemanticViolation, ...]
    unmodeled_commands: tuple[str, ...]
    assumptions: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return not self.violations and not any(step.warnings for step in self.steps)

    def to_dict(self) -> dict[str, Any]:
        return {
            "steps": [step.to_dict() for step in self.steps],
            "total_duration_s": round(self.total_duration_s, 3),
            "initial_volumes_ul": (
                None if self.initial_volumes_ul is None else dict(self.initial_volumes_ul)
            ),
            "final_volumes_ul": (
                None if self.final_volumes_ul is None else dict(self.final_volumes_ul)
            ),
            "tips_used": self.tips_used,
            "tips_available": self.tips_available,
            "violations": [
                {"step_index": v.step_index, "command": v.command_name, "message": v.message}
                for v in self.violations
            ],
            "unmodeled_commands": list(self.unmodeled_commands),
            "assumptions": list(self.assumptions),
        }


def _name(key: _ContainerKey) -> str:
    return f"{key[0]}.{key[1]}" if key[1] else key[0]


def _public(volumes: Mapping[_ContainerKey, float]) -> dict[str, float]:
    return {_name(key): round(value, 6) for key, value in sorted(volumes.items()) if value > 0}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


class _Clock:
    """Tracks the tool position to cost travel between visited targets."""

    def __init__(self, deck: Deck, model: TimingModel, safe_z: float | None) -> None:
        self.deck, self.model, self.safe_z = deck, model, safe_z
        self.at: tuple[float, float, float] | None = None

    def visit(self, position: Any) -> float:
        try:
            if isinstance(position, (list, tuple)):
                x, y, z = (float(v) for v in position)
            else:
                coord = self.deck.resolve_coordinate(position)
                x, y, z = float(coord.x), float(coord.y), float(coord.z)
        except (KeyError, ValueError, TypeError, AttributeError):
            self.at = None
            return self.model.unknown_leg_travel_s
        seconds = 0.0
        if self.at is not None:
            horizontal = math.hypot(x - self.at[0], y - self.at[1])
            lift = 0.0
            if self.safe_z is not None and horizontal > 0:
                lift = max(self.safe_z - self.at[2], 0.0) + max(self.safe_z - z, 0.0)
            seconds = (horizontal + lift) / self.model.travel_mm_per_s
        self.at = (x, y, z)
        return seconds


def _step_legs(step: Any, deck: Deck) -> list[tuple[str, Any, Any, float]]:
    """Liquid legs (kind, source, destination, volume) a compound step performs."""
    args = step.args
    name = step.command_name
    volume = args.get("volume_ul")
    if name == "transfer" and _is_number(volume):
        return [("transfer", args.get("source"), args.get("destination"), float(volume))]
    if name == "serial_transfer":
        try:
            plate = deck.resolve_labware(args.get("plate"))
        except (KeyError, ValueError):
            return []
        wells = _wells_for_axis(plate, args.get("axis"))
        volumes = _serial_transfer_volumes(args, len(wells))
        if len(volumes) != len(wells):
            return []
        return [
            ("transfer", args.get("source"), f"{args.get('plate')}.{well}", vol)
            for well, vol in zip(wells, volumes)
        ]
    if not _is_number(volume):
        return []
    volume = float(volume)
    cycles = args.get("cycles", 1 if name == "flush_pipette" else 3)
    cycles = cycles if isinstance(cycles, int) and cycles > 0 else 1
    if name == "rinse_well":
        legs: list[tuple[str, Any, Any, float]] = []
        for _ in range(cycles):
            legs.append(("transfer", args.get("source"), args.get("well"), volume))
            if args.get("mix_repetitions", 0):
                legs.append(("mix", args.get("well"), args.get("well"), volume))
            legs.append(("transfer", args.get("well"), args.get("waste"), volume))
        return legs
    if name == "flush_pipette":
        return [("transfer", args.get("source"), args.get("waste"), volume)] * cycles
    if name == "purge_pipette":
        return [("transfer", args.get("source"), args.get("waste"), volume)]
    if name == "clear_well":
        return [("transfer", args.get("well"), args.get("waste"), volume)]
    return []


def _transfer_extras(args: Any, strokes: list[float], plunger: Any) -> float:
    prewet = args.get("prewet_cycles", 0)
    dwell = float(args.get("aspirate_dwell_s", 0)) + float(args.get("dispense_dwell_s", 0))
    return sum(2 * prewet * plunger(stroke) + dwell for stroke in strokes)


def _duration(
    step: Any,
    deck: Deck,
    clock: _Clock,
    model: TimingModel,
    config: PipetteConfig | None,
    unmodeled: set[str],
) -> float:
    args = step.args
    name = step.command_name
    capacity = config.max_volume if config is not None else 200.0
    speed = float(args["speed"]) if _is_number(args.get("speed")) else 50.0

    def plunger(volume: float) -> float:
        return model.plunger_s(volume, speed, capacity)

    if name == "home":
        return model.gantry_home_s
    if name == "pause":
        return float(args["seconds"]) if _is_number(args.get("seconds")) else 0.0
    if name == "pipette_home":
        return model.pipette_home_s
    if name == "pick_up_tip":
        return clock.visit(args.get("position")) + model.tip_pickup_s
    if name == "drop_tip":
        return clock.visit(args.get("position")) + model.tip_drop_s
    if name in {"aspirate", "dispense"} and _is_number(args.get("volume_ul")):
        return clock.visit(args.get("position")) + plunger(float(args["volume_ul"]))
    if name == "blowout":
        return clock.visit(args.get("position")) + model.blowout_s
    if name == "mix" and _is_number(args.get("volume_ul")):
        cycles = args.get("cycles", 3)
        cycles = cycles if isinstance(cycles, int) and cycles > 0 else 1
        stroke = plunger(float(args["volume_ul"]))
        return clock.visit(args.get("position")) + cycles * 4 * stroke + model.blowout_s
    if name == "multi_dispense":
        volumes = [float(v) for v in args.get("volumes", []) if _is_number(v)]
        seconds = clock.visit(args.get("source")) + plunger(sum(volumes))
        for destination, volume in zip(args.get("destinations", []), volumes):
            seconds += clock.visit(destination) + plunger(volume)
        return seconds + model.blowout_s
    legs = _step_legs(step, deck)
    if legs:
        seconds = 0.0
        for kind, source, destination, volume in legs:
            if kind == "mix":
                seconds += clock.visit(source) + 4 * plunger(volume) + model.blowout_s
                continue
            strokes = [volume]
            try:
                strokes = plan_strokes(volume, config)
            except LiquidTransferPreflightError:
                pass
            for stroke in strokes:
                seconds += clock.visit(source) + plunger(stroke)
                seconds += clock.visit(destination) + plunger(stroke)
            seconds += model.blowout_s
            if name == "transfer":
                seconds += _transfer_extras(args, strokes, plunger)
        return seconds
    unmodeled.add(name)
    return 0.0


def simulate_protocol(
    protocol: Protocol,
    deck: Deck,
    *,
    initial_fluids: Mapping[str, Any] | None = None,
    pipette_config: PipetteConfig | None = None,
    safe_z: float | None = None,
    timing: TimingModel | None = None,
) -> SimulationTimeline:
    """Predict per-step state and duration for *protocol* on *deck*.

    ``initial_fluids`` is the mapping ``load_initial_fluids`` returns. Without
    it container volumes are not tracked (``volumes_ul`` is ``None``) because
    an unseeded deck cannot be assumed empty; tip, held-liquid and duration
    predictions are still produced.
    """
    model = timing or TimingModel()
    clock = _Clock(deck, model, safe_z)
    tracking = initial_fluids is not None
    volumes: dict[_ContainerKey, float] = (
        seed_volumes(deck, initial_fluids) if initial_fluids is not None else {}
    )
    initial = _public(volumes) if tracking else None
    tips_available = sum(
        sum(1 for present in rack.tip_present.values() if present)
        for rack in deck.labware.values()
        if isinstance(rack, TipRack)
    )
    violations: list[ProtocolSemanticViolation] = []
    unmodeled: set[str] = set()
    steps: list[TimelineStep] = []
    elapsed = 0.0
    tips_used = 0
    tip_attached = False
    loaded = 0.0

    for step in protocol.steps:
        name = step.command_name
        args = step.args
        warnings: list[str] = []
        before = dict(volumes)

        if name == "pick_up_tip":
            if tip_attached:
                warnings.append("pick_up_tip with a tip already attached")
            tip_attached = True
            tips_used += 1
            loaded = 0.0
        elif name == "drop_tip":
            if not tip_attached:
                warnings.append("drop_tip with no tip attached")
            if loaded > 1e-6:
                warnings.append(f"tip dropped while holding {loaded:g} uL")
            tip_attached, loaded = False, 0.0
        elif name in {
            "aspirate", "dispense", "blowout", "mix", "multi_dispense",
            *_PROJECTED_COMMANDS,
        } and not tip_attached:
            warnings.append(f"{name} with no tip attached")

        if name in {"aspirate", "dispense"} and _is_number(args.get("volume_ul")):
            amount = float(args["volume_ul"])
            try:
                key = _container_key(_resolve(deck, args.get("position")))
            except (KeyError, ValueError):
                key = None
            if name == "aspirate":
                loaded += amount
                if tracking and key is not None:
                    volumes[key] = max(volumes.get(key, 0.0) - amount, 0.0)
            else:
                if amount > loaded + 1e-6:
                    warnings.append(f"dispense {amount:g} uL but only {loaded:g} uL held")
                moved = min(amount, loaded)
                loaded -= moved
                if tracking and key is not None:
                    volumes[key] = volumes.get(key, 0.0) + moved
        elif name == "blowout":
            try:
                key = _container_key(_resolve(deck, args.get("position")))
            except (KeyError, ValueError):
                key = None
            if tracking and key is not None:
                volumes[key] = volumes.get(key, 0.0) + loaded
            loaded = 0.0
        elif name == "multi_dispense":
            planned = [float(v) for v in args.get("volumes", []) if _is_number(v)]
            if tracking:
                try:
                    source_key = _container_key(_resolve(deck, args.get("source")))
                    volumes[source_key] = max(volumes.get(source_key, 0.0) - sum(planned), 0.0)
                    for destination, volume in zip(args.get("destinations", []), planned):
                        key = _container_key(_resolve(deck, destination))
                        volumes[key] = volumes.get(key, 0.0) + volume
                except (KeyError, ValueError):
                    warnings.append("multi_dispense target could not be resolved")
            loaded = 0.0
        elif name in _PROJECTED_COMMANDS:
            if tracking:
                violations.extend(project_step_volumes(step, deck, volumes, pipette_config))
            loaded = 0.0

        duration = _duration(step, deck, clock, model, pipette_config, unmodeled)
        steps.append(TimelineStep(
            index=step.index,
            command=name,
            start_s=elapsed,
            duration_s=duration,
            volumes_ul=_public(volumes) if tracking else None,
            changed_ul={
                _name(key): round(volumes.get(key, 0.0) - before.get(key, 0.0), 6)
                for key in sorted(set(volumes) | set(before))
                if abs(volumes.get(key, 0.0) - before.get(key, 0.0)) > 1e-9
            },
            loaded_ul=round(loaded, 6),
            tip_attached=tip_attached,
            tips_used=tips_used,
            warnings=tuple(warnings),
        ))
        elapsed += duration

    travel = (
        f"travel at {model.travel_mm_per_s:g} mm/s with lifts to safe_z"
        if safe_z is not None
        else f"travel at {model.travel_mm_per_s:g} mm/s, horizontal distance only (no safe_z given)"
    )
    assumptions = (
        travel,
        (
            f"full plunger stroke {model.plunger_stroke_s:g} s at speed 50, "
            f"{model.plunger_overhead_s:g} s overhead per stroke"
        ),
        (
            f"blow-out {model.blowout_s:g} s, tip pickup {model.tip_pickup_s:g} s, "
            f"tip drop {model.tip_drop_s:g} s, gantry home {model.gantry_home_s:g} s"
        ),
        f"{model.unknown_leg_travel_s:g} s per move whose target cannot be resolved",
        "defaults are assumptions, not measurements",
    )
    return SimulationTimeline(
        steps=tuple(steps),
        total_duration_s=elapsed,
        initial_volumes_ul=initial,
        final_volumes_ul=_public(volumes) if tracking else None,
        tips_used=tips_used,
        tips_available=tips_available,
        violations=tuple(violations),
        unmodeled_commands=tuple(sorted(unmodeled)),
        assumptions=assumptions,
    )


def simulate_setup(
    gantry_path: str | Path,
    deck_path: str | Path,
    protocol_path: str | Path,
    initial_fluids_path: str | Path | None = None,
    *,
    timing: TimingModel | None = None,
) -> SimulationTimeline:
    """Load a gantry/deck/protocol triple offline and simulate it."""
    from cubos.data.fluid_state import load_initial_fluids
    from cubos.deck.loader import load_deck_from_yaml
    from cubos.gantry.gantry import Gantry
    from cubos.gantry.instrument_loader import load_instrumented_gantry_from_config
    from cubos.gantry.loader import load_gantry_from_yaml
    from cubos.protocol_engine.loader import load_protocol_from_yaml

    gantry_config = load_gantry_from_yaml(gantry_path)
    deck = load_deck_from_yaml(
        deck_path, factory_z_travel_mm=gantry_config.factory_z_travel_mm,
    )
    instrumented = load_instrumented_gantry_from_config(
        gantry_config, Gantry(offline=True), mock_mode=True,
    )
    protocol = load_protocol_from_yaml(protocol_path, deck=deck)
    initial_fluids = (
        load_initial_fluids(initial_fluids_path) if initial_fluids_path is not None else None
    )
    return simulate_protocol(
        protocol,
        deck,
        initial_fluids=initial_fluids,
        pipette_config=pipette_capacity(instrumented.instruments.get("pipette")),
        safe_z=gantry_config.resolved_safe_z,
        timing=timing,
    )


__all__ = [
    "SimulationTimeline",
    "TimelineStep",
    "TimingModel",
    "simulate_protocol",
    "simulate_setup",
]
