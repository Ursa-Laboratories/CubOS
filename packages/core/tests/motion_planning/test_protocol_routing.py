from __future__ import annotations

from dataclasses import dataclass

import pytest

from cubos.deck.loader import _build_deck_from_raw
from cubos.gantry.gantry_config import GantryConfig, GantryType, WorkingVolume
from cubos.gantry.gantry import Gantry
from cubos.gantry.instrument_mount import InstrumentedGantry
from cubos.protocol_engine.compiler import CommandCall, compile_protocol
from cubos.protocol_engine.errors import ProtocolExecutionError
from cubos.protocol_engine.runtime import ProtocolContext
from cubos.protocol_engine.routing import RoutingSession, prepare_planning_context
from cubos.protocol_engine.setup import run_on_hardware, setup_protocol
from cubos.protocol_engine.setup_validator import run_setup_validation


class FakeController:
    def __init__(self) -> None:
        self.coords = {"x": 110.0, "y": 90.0, "z": 80.0}
        self.moves: list[tuple[float, float, float, float | None]] = []

    def get_coordinates(self):
        return dict(self.coords)

    def move_to(self, x, y, z, travel_z=None):
        self.moves.append((x, y, z, travel_z))
        self.coords = {"x": x, "y": y, "z": z}


class FakePipette:
    name = "pipette"
    offset_x = 0.0
    offset_y = 0.0
    depth = -20.0

    def __init__(self) -> None:
        self.attached_tip_extension = 0.0
        self.actions: list[str] = []

    @property
    def effective_depth(self):
        return self.depth + self.attached_tip_extension

    def set_attached_tip_extension(self, value):
        self.attached_tip_extension = float(value)

    def clear_attached_tip_extension(self):
        self.attached_tip_extension = 0.0

    def pick_up_tip(self, speed=50):
        self.actions.append("pick_up_tip")

    def drop_tip(self, speed=50):
        self.actions.append("drop_tip")

    def aspirate(self, volume_ul, speed=50):
        self.actions.append(f"aspirate:{volume_ul}")

    def dispense(self, volume_ul, speed=50):
        self.actions.append(f"dispense:{volume_ul}")


def _vial(name: str, x: float, y: float, *, size: float = 10) -> dict:
    return {
        "type": "vial",
        "name": name,
        "height": 20,
        "diameter": size,
        "location": {"x": x, "y": y, "z": 40},
        "capacity_ul": 1000,
        "working_volume_ul": 900,
        "motion": {
            "box": {
                "anchor": "location",
                "offset": {"x": -size / 2, "y": -size / 2, "z": -20},
                "size": {"x": size, "y": size, "z": 20},
            }
        },
    }


def _context(*, blocker: bool = False) -> tuple[ProtocolContext, FakeController, FakePipette]:
    labware = {
        "tips": {
            "type": "tip_rack",
            "name": "tips",
            "rows": 1,
            "columns": 1,
            "pickup_z": 50,
            "tip_length": 20,
            "calibration": {
                "a1": {"x": 20, "y": 20, "z": 50},
                "a2": {"x": 30, "y": 20},
            },
            "x_offset": 10,
            "y_offset": 10,
            "tip_present": {"A1": True},
            "motion": {
                "box": {
                    "anchor": "A1",
                    "offset": {"x": -5, "y": -5, "z": -20},
                    "size": {"x": 20, "y": 10, "z": 18},
                },
                "occupied_tip_radius_mm": 1,
                "access": {
                    "pick_up_tip": {
                        "strategy": "side_exit",
                        "lift_mm": 30,
                        "exit_edge": "x_min",
                        "clearance_mm": 5,
                    }
                },
            },
        },
        "source": _vial("source", 60, 60),
        "destination": _vial("destination", 80, 60),
        "waste": _vial("waste", 100, 60),
    }
    if blocker:
        labware["blocker"] = _vial("blocker", 80, 60, size=16)
    deck = _build_deck_from_raw({
        "motion_planning": {"clearance_mm": 1},
        "labware": labware,
    })
    config = GantryConfig(
        serial_port="offline",
        gantry_type=GantryType.CUB,
        factory_z_travel_mm=80,
        working_volume=WorkingVolume(0, 120, 0, 100, 0, 80),
        safe_z=80,
        instruments={"pipette": {"type": "pipette", "vendor": "fake"}},
        motion_envelopes={
            "pipette": {
                "box": {
                    "offset": {"x": -2, "y": -2, "z": 0},
                    "size": {"x": 4, "y": 4, "z": 20},
                },
                "attached_tip_radius_mm": 1,
            }
        },
    )
    controller = FakeController()
    pipette = FakePipette()
    gantry = InstrumentedGantry(
        controller,
        {"pipette": pipette},
        safe_z=80,
        motion_envelopes=config.motion_envelopes,
    )
    return ProtocolContext(gantry=gantry, deck=deck, gantry_config=config), controller, pipette


def _native_protocol():
    return compile_protocol([
        CommandCall("pick_up_tip", {"position": "tips.A1"}),
        CommandCall("transfer", {
            "source": "source",
            "destination": "destination",
            "volume_ul": 100,
        }),
        CommandCall("mix", {"position": "destination", "volume_ul": 50, "cycles": 1}),
        CommandCall("drop_tip", {"position": "waste"}),
    ])


def test_native_planned_commands_execute_preflighted_exact_segments() -> None:
    context, controller, pipette = _context()

    _native_protocol().execute(context)

    assert pipette.actions == [
        "pick_up_tip",
        "aspirate:100.0",
        "dispense:100.0",
        "aspirate:50.0",
        "dispense:50.0",
        "aspirate:50.0",
        "dispense:50.0",
        "drop_tip",
    ]
    assert controller.moves
    assert all(travel_z is None for *_xyz, travel_z in controller.moves)
    serialized = context.serialized_motion_plans()
    assert serialized
    assert any(plan["state_changes"] for plan in serialized)
    assert all(segment["axis"] in {"x", "y", "z"} for plan in serialized for segment in plan["segments"])


def test_transfer_destination_no_route_rejects_before_pickup_or_aspirate() -> None:
    context, controller, pipette = _context(blocker=True)

    with pytest.raises(ProtocolExecutionError, match="preflight failed"):
        _native_protocol().execute(context)

    assert controller.moves == []
    assert pipette.actions == []
    assert pipette.attached_tip_extension == 0


def test_unsupported_command_rejects_before_earlier_supported_movement() -> None:
    context, controller, pipette = _context()
    protocol = compile_protocol([
        CommandCall("pick_up_tip", {"position": "tips.A1"}),
        CommandCall("home", {}),
    ])

    with pytest.raises(ProtocolExecutionError, match=r"step 1 \(home\)"):
        protocol.execute(context)

    assert controller.moves == []
    assert pipette.actions == []


def test_cached_bare_plan_rejects_unexpected_attached_tip_before_motion() -> None:
    context, controller, pipette = _context()
    protocol = _native_protocol()
    prepare_planning_context(protocol, context)
    pipette.set_attached_tip_extension(20)

    with pytest.raises(ProtocolExecutionError, match="tool state does not match"):
        context.routing_session.execute(context.motion_plans[0])

    assert controller.moves == []


def test_planner_owned_move_order_rejects_travel_z_before_prior_motion() -> None:
    context, controller, pipette = _context()
    protocol = compile_protocol([
        CommandCall("pick_up_tip", {"position": "tips.A1"}),
        CommandCall("move", {
            "instrument": "pipette",
            "position": [50, 50, 50],
            "travel_z": 70,
        }),
    ])

    with pytest.raises(ProtocolExecutionError, match="rejects travel_z"):
        protocol.execute(context)

    assert controller.moves == []
    assert pipette.actions == []


def test_require_uncapped_rejects_before_prior_planned_pickup() -> None:
    context, controller, pipette = _context()
    protocol = compile_protocol([
        CommandCall("pick_up_tip", {"position": "tips.A1"}),
        CommandCall("transfer", {
            "source": "source",
            "destination": "destination",
            "volume_ul": 100,
            "require_uncapped": ["source"],
        }),
    ])

    with pytest.raises(ProtocolExecutionError, match="does not support require_uncapped"):
        protocol.execute(context)

    assert controller.moves == []
    assert pipette.actions == []


def test_repeated_explicit_tip_rejects_whole_protocol_before_motion() -> None:
    context, controller, pipette = _context()
    protocol = compile_protocol([
        CommandCall("pick_up_tip", {"position": "tips.A1"}),
        CommandCall("drop_tip", {"position": "waste"}),
        CommandCall("pick_up_tip", {"position": "tips.A1"}),
    ])

    with pytest.raises(ProtocolExecutionError, match="tips.A1.*unavailable"):
        protocol.execute(context)

    assert controller.moves == []
    assert pipette.actions == []


def test_consumed_tip_is_absent_from_later_unscoped_transit_scene(monkeypatch) -> None:
    context, _controller, _pipette = _context()
    observed_fixture_sets = []
    original = RoutingSession._scene_and_access

    def recording_scene(self, instrument, targets, consumed, start, end, state):
        scene, access = original(
            self, instrument, targets, consumed, start, end, state,
        )
        if "tips.tip.A1" in consumed and not targets:
            observed_fixture_sets.append({fixture.name for fixture in scene.fixtures})
        return scene, access

    monkeypatch.setattr(RoutingSession, "_scene_and_access", recording_scene)

    prepare_planning_context(_native_protocol(), context)

    assert observed_fixture_sets
    assert all("tips.tip.A1" not in names for names in observed_fixture_sets)


def _write_planned_move_files(tmp_path):
    gantry = tmp_path / "gantry.yaml"
    gantry.write_text("""
serial_port: offline
gantry_type: cub
cnc:
  factory_z_travel_mm: 100
working_volume:
  x_min: 0
  x_max: 120
  y_min: 0
  y_max: 100
  z_min: 0
  z_max: 80
instruments:
  pipette:
    type: pipette
    vendor: opentrons
    depth: 0
    motion_envelope:
      box:
        offset: {x: -2, y: -2, z: 0}
        size: {x: 4, y: 4, z: 20}
      attached_tip_radius_mm: 1
""")
    deck = tmp_path / "deck.yaml"
    deck.write_text("motion_planning: {clearance_mm: 1}\nlabware: {}\n")
    protocol = tmp_path / "protocol.yaml"
    protocol.write_text("""
positions:
  park: [50, 50, 40]
protocol:
  - move:
      instrument: pipette
      position: park
""")
    return gantry, deck, protocol


def test_offline_setup_validation_returns_the_shared_serialized_plans(tmp_path) -> None:
    gantry, deck, protocol = _write_planned_move_files(tmp_path)

    result = run_setup_validation(gantry, deck, protocol)

    assert result.passed
    assert result.motion_plans
    assert "immutable plan" in result.output


def test_setup_protocol_prepares_plans_from_nominal_offline_pose(tmp_path) -> None:
    gantry, deck, protocol = _write_planned_move_files(tmp_path)

    loaded, context = setup_protocol(gantry, deck, protocol, mock_mode=True)

    assert len(loaded) == 1
    assert context.routing_session is not None
    assert context.motion_plans


def test_hardware_orchestrator_plans_before_offline_instrument_connect(tmp_path) -> None:
    gantry_path, deck, protocol = _write_planned_move_files(tmp_path)

    class Store:
        def __init__(self):
            self.finished = []

        def get_campaign_fluid_state_id(self, campaign_id):
            return None

        def finish_campaign(self, campaign_id, status):
            self.finished.append((campaign_id, status))

    store = Store()
    results = run_on_hardware(
        gantry_path,
        deck,
        protocol,
        gantry=Gantry(offline=True),
        mock_mode=True,
        data_store=store,
        campaign_id=7,
    )

    assert results == [None]
    assert store.finished == [(7, "completed")]
