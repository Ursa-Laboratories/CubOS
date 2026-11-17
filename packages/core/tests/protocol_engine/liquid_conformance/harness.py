"""Conformance harness for liquid-handling protocol commands.

A physical-world model (``SimWorld``) is driven by a gantry and pipette whose
every call can be made to fail. After any command, durable fluid/tip state is
compared with that world: the two may differ only where a pending
(``reconciliation_required``) journal entry says they might.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from cubos.data.data_store import DataStore
from cubos.deck.labware.tip_rack import TipRack
from cubos.deck.labware.vial import Vial
from cubos.deck.labware.vial_grid import VialGrid
from cubos.deck.labware.well_plate import WellPlate
from cubos.deck.loader import load_deck_from_yaml_safe
from cubos.instruments.pipette.exceptions import PipetteCommandError
from cubos.instruments.pipette.interface import PipetteInstrument
from cubos.instruments.pipette.models import (
    AspirateResult,
    PICUS2_MODELS,
    PIPETTE_MODELS,
    PipetteConfig,
    PipetteFamily,
    PipetteStatus,
)
from cubos.instruments.pipette.vendors.opentrons import OpentronsPipette
from cubos.instruments.pipette.vendors.sartorius import SartoriusPicus2Pipette
from cubos.protocol_engine.builder import ProtocolBuilder
from cubos.protocol_engine.runtime import ProtocolContext

TOLERANCE_UL = 1e-6
PENDING = ("started", "reconciliation_required")

DECK_YAML = """\
labware:
  stock:
    type: vial
    name: stock
    model_name: stock_vial
    role: stock
    solution: water
    height: 100.0
    diameter: 20.0
    location: {x: 5.0, y: 5.0, z: 50.0}
    capacity_ul: 5000.0
    working_volume_ul: 4500.0
    dead_volume_ul: 100.0

  dest:
    type: vial
    name: dest
    model_name: dest_vial
    height: 80.0
    diameter: 25.0
    location: {x: 40.0, y: 5.0, z: 45.0}
    capacity_ul: 2000.0
    working_volume_ul: 1500.0

  waste:
    type: vial
    name: waste
    model_name: waste_vial
    role: waste
    height: 80.0
    diameter: 25.0
    location: {x: 60.0, y: 5.0, z: 45.0}
    capacity_ul: 5000.0
    working_volume_ul: 4500.0

  plate:
    type: well_plate
    name: destination_plate
    model_name: six_well_plate
    length: 40.0
    width: 30.0
    height: 14.0
    well_depth: 10.0
    rows: 2
    columns: 3
    calibration:
      a1: {x: 70.0, y: 20.0, z: 15.0}
      a2: {x: 79.0, y: 20.0, z: 15.0}
    x_offset: 9.0
    y_offset: 9.0
    capacity_ul: 400.0
    working_volume_ul: 300.0

  tip_rack:
    type: tip_rack
    name: tip_rack
    rows: 1
    columns: 4
    calibration:
      a1: {x: 100.0, y: 60.0, z: 40.0}
      a2: {x: 109.0, y: 60.0, z: 40.0}
    x_offset: 9.0
    y_offset: 9.0
    pickup_z: 40.0
    drop_z: 40.0
    tip_length: 50.0

  tip_disposal:
    type: tip_disposal
    name: tip_disposal
    location: {x: 150.0, y: 60.0, z: 30.0}
    slots:
      discard:
        description: discard
        location: {x: 150.0, y: 60.0, z: 30.0}
        supported_labware_types: [pipette_tip]
"""

SIM_CONFIG = PipetteConfig(
    name="sim_100",
    family=PipetteFamily.PICUS2,
    channels=1,
    max_volume=100.0,
    min_volume=5.0,
    volume_increment_ul=0.1,
)

Phase = Literal["before", "after"]


@dataclass
class Fault:
    """Raise ``error()`` on the *nth* call to *site*.

    ``before`` fails ahead of any physical effect; ``after`` fails once the
    effect has happened (a lost acknowledgement), which is the case where
    durable state cannot know the outcome.
    """

    site: str
    error: Callable[[], BaseException]
    nth: int = 1
    phase: Phase = "before"


class FaultPlan:
    def __init__(self, faults: list[Fault] | None = None) -> None:
        self.faults = list(faults or [])
        self.calls: dict[str, int] = {}
        self.fired: list[Fault] = []
        self.raised: BaseException | None = None

    def arm(self, fault: Fault) -> None:
        """Add *fault*, counting its ``nth`` from the calls made so far."""
        self.faults.append(
            Fault(fault.site, fault.error, fault.nth + self.calls.get(fault.site, 0), fault.phase)
        )

    def before(self, site: str) -> None:
        self.calls[site] = self.calls.get(site, 0) + 1
        self._maybe_raise(site, "before")

    def after(self, site: str) -> None:
        self._maybe_raise(site, "after")

    def _maybe_raise(self, site: str, phase: Phase) -> None:
        for fault in self.faults:
            if (
                fault.site == site
                and fault.phase == phase
                and fault.nth == self.calls.get(site, 0)
                and fault not in self.fired
            ):
                self.fired.append(fault)
                self.raised = fault.error()
                raise self.raised


class SimWorld:
    """Physical truth: liquid per container, tips per slot, tip attachment."""

    def __init__(self, deck: Any, store: DataStore, state_id: int) -> None:
        self.volumes: dict[str, float] = {}
        self._where: dict[tuple[float, float], tuple[str, str]] = {}
        snapshot = store.get_fluid_snapshot(state_id)
        for container in snapshot["containers"]:
            target = _target_name(container["labware_key"], container["location_id"])
            self.volumes[target] = float(container["current_volume_ul"])
            coord = deck.resolve_coordinate(target)
            self._where[(round(coord.x, 3), round(coord.y, 3))] = ("container", target)
        self.tips: dict[str, bool] = {}
        for key, labware in deck.labware.items():
            if isinstance(labware, TipRack):
                for slot, coord in labware.tips.items():
                    name = f"{key}.{slot}"
                    self.tips[name] = bool(labware.tip_present.get(slot, False))
                    self._where[(round(coord.x, 3), round(coord.y, 3))] = ("tip", name)
        disposal = deck.resolve_coordinate("tip_disposal.discard")
        self._where[(round(disposal.x, 3), round(disposal.y, 3))] = ("disposal", "")
        self.tip_attached = False
        self.loaded_ul = 0.0
        self.discarded_ul = 0.0
        self.initial_total = sum(self.volumes.values())

    def at(self, xy: tuple[float, float]) -> tuple[str, str]:
        key = (round(xy[0], 3), round(xy[1], 3))
        if key not in self._where:
            raise AssertionError(f"tip at {xy} is not over any container, tip or disposal")
        return self._where[key]

    def total(self) -> float:
        return sum(self.volumes.values()) + self.loaded_ul + self.discarded_ul


def _target_name(labware_key: str, location_id: str) -> str:
    return f"{labware_key}.{location_id}" if location_id else labware_key


class SimGantry:
    """Records tip position; routes every move through the fault plan."""

    def __init__(self, faults: FaultPlan, safe_z: float = 200.0) -> None:
        self.faults = faults
        self.safe_z = safe_z
        self.instruments: dict[str, Any] = {}
        self.xy: tuple[float, float] = (0.0, 0.0)
        self.z = safe_z
        self.moves: list[tuple[str, tuple[float, float, float]]] = []

    @staticmethod
    def _xyz(position: Any) -> tuple[float, float, float]:
        if isinstance(position, (tuple, list)):
            return float(position[0]), float(position[1]), float(position[2])
        return float(position.x), float(position.y), float(position.z)

    def move_to_labware(self, instrument: Any, coord: Any) -> None:
        self.faults.before("gantry.move_to_labware")
        x, y, _ = self._xyz(coord)
        self.xy, self.z = (x, y), self.safe_z
        self.moves.append(("move_to_labware", (x, y, self.safe_z)))
        self.faults.after("gantry.move_to_labware")

    def move(self, instrument: Any, position: Any, travel_z: float | None = None) -> None:
        self.faults.before("gantry.move")
        x, y, z = self._xyz(position)
        self.xy, self.z = (x, y), z
        self.moves.append(("move", (x, y, z)))
        self.faults.after("gantry.move")


class _WorldBound:
    """Mixin: ties a pipette driver to the world, gantry and fault plan."""

    world: SimWorld
    sim_gantry: SimGantry
    faults: FaultPlan

    def bind(self, world: SimWorld, gantry: SimGantry, faults: FaultPlan) -> None:
        self.world, self.sim_gantry, self.faults = world, gantry, faults

    def _loaded(self) -> float:
        return float(self.loaded_volume_ul or 0.0)

    def _kind_and_name(self) -> tuple[str, str]:
        return self.world.at(self.sim_gantry.xy)

    def aspirate(self, volume_ul: float, speed: float = 50.0) -> AspirateResult:
        self.faults.before("pipette.aspirate")
        before = self._loaded()
        result = super().aspirate(volume_ul, speed)
        taken = self._loaded() - before
        kind, name = self._kind_and_name()
        if kind != "container":
            raise AssertionError(f"aspirated over a {kind}, not a container")
        if self.world.volumes[name] + TOLERANCE_UL < taken:
            raise AssertionError(
                f"aspirated {taken:g} uL from {name} holding {self.world.volumes[name]:g} uL"
            )
        self.world.volumes[name] -= taken
        self.world.loaded_ul += taken
        self.faults.after("pipette.aspirate")
        return result

    def dispense(self, volume_ul: float, speed: float = 50.0) -> AspirateResult:
        self.faults.before("pipette.dispense")
        before = self._loaded()
        result = super().dispense(volume_ul, speed)
        given = before - self._loaded()
        kind, name = self._kind_and_name()
        if kind != "container":
            raise AssertionError(f"dispensed over a {kind}, not a container")
        self.world.volumes[name] += given
        self.world.loaded_ul -= given
        self.faults.after("pipette.dispense")
        return result

    def blowout(self, speed: float = 50.0) -> None:
        self.faults.before("pipette.blowout")
        before = self._loaded()
        super().blowout(speed)
        kind, name = self._kind_and_name()
        if kind != "container":
            raise AssertionError(f"blew out over a {kind}, not a container")
        self.world.volumes[name] += before
        self.world.loaded_ul -= before
        self.faults.after("pipette.blowout")

    def home(self) -> None:
        self.faults.before("pipette.home")
        before = self._loaded()
        super().home()
        self.world.discarded_ul += before
        self.world.loaded_ul -= before
        self.faults.after("pipette.home")

    def pick_up_tip(self, speed: float = 50.0) -> None:
        self.faults.before("pipette.pick_up_tip")
        kind, name = self._kind_and_name()
        if kind != "tip" or not self.world.tips[name]:
            raise AssertionError(f"no tip to pick up at {kind} {name!r}")
        if self.world.tip_attached:
            raise AssertionError("pick_up_tip with a tip already attached")
        super().pick_up_tip(speed)
        self.world.tips[name] = False
        self.world.tip_attached = True
        self.faults.after("pipette.pick_up_tip")

    def drop_tip(self, speed: float = 50.0) -> None:
        self.faults.before("pipette.drop_tip")
        kind, _ = self._kind_and_name()
        if kind not in ("disposal", "tip"):
            raise AssertionError(f"dropped a tip over a {kind}")
        super().drop_tip(speed)
        self.world.discarded_ul += self.world.loaded_ul
        self.world.loaded_ul = 0.0
        self.world.tip_attached = False
        self.faults.after("pipette.drop_tip")


class StrictSimPipette(PipetteInstrument):
    """Vendor-neutral strict simulator.

    Unlike the offline vendor drivers it refuses to aspirate without a tip and
    to dispense more than it holds. Like the Picus it moves the volume rounded
    to the model increment, which is what the world model sees.
    """

    def __init__(self, config: PipetteConfig = SIM_CONFIG, *, home_after_blowout: bool = True) -> None:
        super().__init__(name="pipette", offline=True)
        self.config = config
        self._home_after_blowout = home_after_blowout
        self._loaded_volume = 0.0
        self._has_tip = False
        self._extension = 0.0
        self.ledger: list[tuple[str, float, float]] = []

    @property
    def loaded_volume_ul(self) -> float:
        return self._loaded_volume

    @property
    def requires_home_after_blowout(self) -> bool:
        return self._home_after_blowout

    @property
    def attached_tip_extension(self) -> float:
        return self._extension

    def set_attached_tip_extension(self, extension_mm: float) -> None:
        self._extension = float(extension_mm)

    def clear_attached_tip_extension(self) -> None:
        self._extension = 0.0

    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def health_check(self) -> bool:
        return True

    def _check_volume(self, volume_ul: float) -> float:
        increment = self.config.volume_increment_ul
        volume = round(round(volume_ul / increment) * increment, 6)
        if not (self.config.min_volume <= volume <= self.config.max_volume):
            raise PipetteCommandError(f"{volume_ul} uL outside {self.config.name} range")
        return volume

    def home(self) -> None:
        if self._loaded_volume > 0:
            raise PipetteCommandError("refusing to home while holding liquid")
        self._loaded_volume = 0.0

    def prime(self, speed: float = 50.0) -> None:
        pass

    def aspirate(self, volume_ul: float, speed: float = 50.0) -> AspirateResult:
        if not self._has_tip:
            raise PipetteCommandError("aspirate without a tip")
        volume = self._check_volume(volume_ul)
        if self._loaded_volume + volume > self.config.max_volume + TOLERANCE_UL:
            raise PipetteCommandError("aspirate would overfill the tip")
        self._loaded_volume += volume
        self.ledger.append(("aspirate", volume, self._loaded_volume))
        return AspirateResult(True, volume, 0.0, self._loaded_volume)

    def dispense(self, volume_ul: float, speed: float = 50.0) -> AspirateResult:
        if not self._has_tip:
            raise PipetteCommandError("dispense without a tip")
        volume = self._check_volume(volume_ul)
        if volume > self._loaded_volume + TOLERANCE_UL:
            raise PipetteCommandError(
                f"dispense of {volume:g} uL but only {self._loaded_volume:g} uL held"
            )
        self._loaded_volume = max(0.0, self._loaded_volume - volume)
        self.ledger.append(("dispense", volume, self._loaded_volume))
        return AspirateResult(True, volume, 0.0, self._loaded_volume)

    def blowout(self, speed: float = 50.0) -> None:
        if not self._has_tip:
            raise PipetteCommandError("blowout without a tip")
        self.ledger.append(("blowout", self._loaded_volume, 0.0))
        self._loaded_volume = 0.0

    def pick_up_tip(self, speed: float = 50.0) -> None:
        if self._has_tip:
            raise PipetteCommandError("pick_up_tip with a tip already attached")
        self._has_tip = True

    def drop_tip(self, speed: float = 50.0) -> None:
        self._has_tip = False
        self._loaded_volume = 0.0
        self._extension = 0.0

    def get_status(self) -> PipetteStatus:
        return PipetteStatus(True, 0.0, self.config.max_volume, self._has_tip, True)


class SimPipette(_WorldBound, StrictSimPipette):
    pass


class _PicusSim(_WorldBound, SartoriusPicus2Pipette):
    pass


class _OpentronsSim(_WorldBound, OpentronsPipette):
    pass


PIPETTE_KINDS = ("sim", "picus", "opentrons")


def make_pipette(kind: str) -> Any:
    if kind == "sim":
        return SimPipette()
    if kind == "picus":
        return _PicusSim(pipette_model="picus2_1ch_120", offline=True)
    if kind == "opentrons":
        return _OpentronsSim(pipette_model="p300_single_gen2", offline=True)
    raise ValueError(kind)


def vendor_volume_scale(kind: str) -> float:
    """Largest stroke the kind's pipette accepts, for sizing test volumes."""
    return {"sim": 100.0, "picus": PICUS2_MODELS["picus2_1ch_120"].max_volume,
            "opentrons": PIPETTE_MODELS["p300_single_gen2"].max_volume}[kind]


@dataclass
class Env:
    deck: Any
    store: DataStore
    state_id: int | None
    campaign_id: int | None
    world: SimWorld
    faults: FaultPlan
    gantry: SimGantry
    pipette: Any
    context: ProtocolContext
    kind: str
    deck_path: Any
    initial_fluids: dict[str, Any] = field(default_factory=dict)

    @property
    def tracked(self) -> bool:
        return self.state_id is not None

    def run(self, *steps: tuple[str, dict[str, Any]]) -> BaseException | None:
        builder = ProtocolBuilder()
        for command, args in steps:
            builder.add_command(command, **args)
        try:
            builder.build().execute(self.context)
        except BaseException as exc:  # noqa: BLE001 - the harness inspects every failure
            return exc
        return None

    def next_campaign(self) -> None:
        """Start a new campaign on the same fluid state so step keys are fresh."""
        self.campaign_id = self.store.create_campaign("conformance", fluid_state_id=self.state_id)
        self.context.campaign_id = self.campaign_id

    def restart(self, faults: FaultPlan | None = None) -> None:
        """Simulate a fresh process: new driver and context, same store and world."""
        self.faults = faults or FaultPlan()
        self.gantry = SimGantry(self.faults)
        self.gantry.xy = self.world_xy_default()
        self.pipette = make_pipette(self.kind)
        self.pipette.bind(self.world, self.gantry, self.faults)
        self.gantry.instruments["pipette"] = self.pipette
        self.pipette._has_tip = self.world.tip_attached
        if self.tracked:
            self.store.restore_pipette_attachment(self.state_id, self.pipette)
        self.context = ProtocolContext(
            gantry=self.gantry,
            deck=self.deck,
            data_store=self.store if self.tracked else None,
            campaign_id=self.campaign_id,
            fluid_state_id=self.state_id,
            logger=logging.getLogger("liquid_conformance"),
        )

    def world_xy_default(self) -> tuple[float, float]:
        return (0.0, 0.0)

    def durable_volumes(self) -> dict[str, float]:
        snapshot = self.store.get_fluid_snapshot(self.state_id)
        return {
            _target_name(c["labware_key"], c["location_id"]): float(c["current_volume_ul"])
            for c in snapshot["containers"]
        }

    def fluid_operations(self) -> list[dict[str, Any]]:
        return list(self.store.get_fluid_snapshot(self.state_id)["operations"])

    def tip_operations(self) -> list[dict[str, Any]]:
        return list(self.store.get_tip_snapshot(self.state_id)["operations"])

    def pending_fluid(self) -> list[dict[str, Any]]:
        return [op for op in self.fluid_operations() if op["status"] in PENDING]

    def pending_tip(self) -> list[dict[str, Any]]:
        return [op for op in self.tip_operations() if op["status"] in PENDING]


def build_env(
    tmp_path: Any,
    *,
    kind: str = "sim",
    tracked: bool = True,
    faults: list[Fault] | None = None,
    initial: dict[str, Any] | None = None,
    deck_yaml: str = DECK_YAML,
) -> Env:
    deck_path = tmp_path / "deck.yaml"
    deck_path.write_text(deck_yaml, encoding="utf-8")
    deck = load_deck_from_yaml_safe(deck_path)
    store = DataStore(db_path=":memory:")
    fluids = initial if initial is not None else {
        "stock": {"volume_ul": 2000.0, "composition": {"water": 2000.0}},
    }
    state_id = store.create_fluid_state(deck_path, deck, initial_fluids=fluids)
    campaign_id = store.create_campaign("conformance", fluid_state_id=state_id)
    world = SimWorld(deck, store, state_id)
    env = Env(
        deck=deck, store=store, state_id=state_id if tracked else None,
        campaign_id=campaign_id if tracked else None, world=world,
        faults=FaultPlan(), gantry=None, pipette=None, context=None,  # type: ignore[arg-type]
        kind=kind, deck_path=deck_path, initial_fluids=fluids,
    )
    env.restart(FaultPlan(faults))
    return env


def assert_world_matches_durable(env: Env) -> None:
    """Durable state may differ from the world only where the journal says so."""
    durable = env.durable_volumes()
    pending = env.pending_fluid()
    flagged: set[str] = set()
    for op in pending:
        flagged.add(op["source"])
        flagged.add(op["destination"])
    for target, volume in durable.items():
        if target in flagged:
            continue
        assert abs(volume - env.world.volumes[target]) <= 1e-4, (
            f"{target}: durable {volume:g} uL but physically {env.world.volumes[target]:g} uL "
            "with no pending journal entry covering it"
        )
    assert abs(sum(durable.values()) - env.world.initial_total) <= 1e-4, (
        "durable volumes no longer sum to the seeded total"
    )
    assert abs(env.world.total() - env.world.initial_total) <= 1e-4, "harness world leaked liquid"
    if not pending and not env.pending_tip():
        assert env.world.loaded_ul <= 1e-6 or env.world.tip_attached, "liquid lost with no tip"


def assert_no_started_left(env: Env) -> None:
    left = [op["operation_key"] for op in env.fluid_operations() + env.tip_operations()
            if op["status"] == "started"]
    assert not left, f"operations left in 'started' after an exception: {left}"


def assert_tips_match_durable(env: Env) -> None:
    tips = env.store.get_tip_snapshot(env.state_id)
    flagged = {(op["rack_key"], op["slot_id"]) for op in env.pending_tip()}
    for slot in tips["containers"]:
        if (slot["rack_key"], slot["slot_id"]) in flagged:
            continue
        name = f"{slot['rack_key']}.{slot['slot_id']}"
        if slot["status"] == "available":
            assert env.world.tips[name], f"{name} durable available but physically gone"
        elif slot["status"] == "consumed":
            assert not env.world.tips[name], f"{name} durable consumed but physically present"
    attachment = tips["pipette"]
    if not env.pending_tip() and not attachment["attachment_uncertain"]:
        attached = attachment["rack_key"] is not None
        assert attached == env.world.tip_attached, "durable tip attachment differs from the world"


def operator_reconcile(env: Env) -> None:
    """Resolve every pending operation the way a careful operator would."""
    durable = env.durable_volumes()
    for op in env.pending_fluid():
        src, dst, volume = op["source"], op["destination"], float(op["volume_ul"])
        if env.world.loaded_ul > TOLERANCE_UL:
            env.world.volumes[src] += env.world.loaded_ul
            env.world.loaded_ul = 0.0
        if op["operation_type"] == "mix":
            env.store.resolve_fluid_operation(op["operation_key"], "applied", detail="operator")
            continue
        post = (
            abs(env.world.volumes[src] - (durable[src] - volume)) <= 1e-4
            and abs(env.world.volumes[dst] - (durable[dst] + volume)) <= 1e-4
        )
        env.store.resolve_fluid_operation(
            op["operation_key"], "applied" if post else "not_applied", detail="operator",
        )
    for op in env.pending_tip():
        name = f"{op['rack_key']}.{op['slot_id']}"
        if op["operation_type"] == "pick_up_tip":
            done = env.world.tip_attached and not env.world.tips[name]
        else:
            done = not env.world.tip_attached
        env.store.resolve_tip_operation(
            op["operation_key"], "applied" if done else "not_applied", detail="operator",
        )


def durable_composition_totals(env: Env) -> dict[str, float]:
    totals: dict[str, float] = {}
    for container in env.store.get_fluid_snapshot(env.state_id)["containers"]:
        volume = float(container["current_volume_ul"])
        parts = container["composition"]
        assert abs(sum(parts.values()) - volume) <= 1e-4, (
            f"{container['labware_key']}.{container['location_id']}: composition "
            f"sums to {sum(parts.values()):g} uL in a {volume:g} uL container"
        )
        for solute, amount in parts.items():
            totals[solute] = totals.get(solute, 0.0) + float(amount)
    return totals
