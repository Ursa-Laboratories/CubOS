from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from unittest.mock import Mock

import pytest

from cubos.data import DataStore
from cubos.deck.loader import _build_deck_from_raw
from cubos.gantry.gantry_config import GantryConfig, GantryType, WorkingVolume
from cubos.gantry.gantry import Gantry
from cubos.gantry.instrument_mount import InstrumentedGantry
from cubos.instruments.camera.interface import CameraInstrument
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

    def move_linear_to(self, x, y, z):
        self.move_to(x, y, z)

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

    def blowout(self, speed=50):
        self.actions.append("blowout")


class FakeCamera(CameraInstrument):
    def __init__(self) -> None:
        super().__init__(
            name="camera", offset_x=0.0, offset_y=-10.0, depth=-20.0,
            offline=True,
        )
        self.captures: list[str] = []

    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def health_check(self) -> bool:
        return True

    def capture(self, *args, **kwargs) -> str:
        path = str(kwargs["save_path"])
        Path(path).write_bytes(b"fake-image")
        self.captures.append(path)
        return path

    def control_fingerprint(self):
        return {"fingerprint": "offline-camera-profile"}

    def last_frame_metadata(self):
        return {
            "frame_id": len(self.captures),
            "capture_profile": {"fingerprint": "offline-camera-profile"},
        }


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


def _context(
    *, blocker: bool = False, with_camera: bool = False,
) -> tuple[ProtocolContext, FakeController, FakePipette]:
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
                        "strategy": "vertical",
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
    instruments = {"pipette": FakePipette()}
    instrument_configs = {"pipette": {"type": "pipette", "vendor": "fake"}}
    motion_envelopes = {
        "pipette": {
            "box": {
                "offset": {"x": -2, "y": -2, "z": 0},
                "size": {"x": 4, "y": 4, "z": 20},
            },
            "attached_tip_radius_mm": 1,
        }
    }
    if with_camera:
        instruments["camera"] = FakeCamera()
        instrument_configs["camera"] = {"type": "camera", "vendor": "fake"}
        motion_envelopes["camera"] = {
            "box": {
                "offset": {"x": -2, "y": -2, "z": 0},
                "size": {"x": 4, "y": 4, "z": 20},
            },
        }
    config = GantryConfig(
        serial_port="offline",
        gantry_type=GantryType.CUB,
        factory_z_travel_mm=80,
        working_volume=WorkingVolume(0, 120, 0, 100, 0, 80),
        safe_z=80,
        instruments=instrument_configs,
        motion_envelopes=motion_envelopes,
    )
    controller = FakeController()
    pipette = instruments["pipette"]
    gantry = InstrumentedGantry(
        controller,
        instruments,
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


def _camera_capture_protocol():
    calls = [CommandCall("pick_up_tip", {"position": "tips.A1"})]
    for index in range(1, 4):
        calls.extend([
            CommandCall("transfer", {
                "source": "source",
                "destination": "destination",
                "volume_ul": 100,
            }),
            CommandCall("move", {
                "instrument": "camera",
                "position": "destination",
            }),
            CommandCall("capture", {
                "instrument": "camera",
                "position": "destination",
                "label": f"destination_after_dispense_{index}",
            }),
        ])
    calls.append(CommandCall("drop_tip", {"position": "waste"}))
    return compile_protocol(calls)


def test_native_planned_commands_execute_preflighted_exact_segments() -> None:
    context, controller, pipette = _context()

    _native_protocol().execute(context)

    assert pipette.actions == [
        "pick_up_tip",
        "aspirate:100.0",
        "dispense:100.0",
        "blowout",
        "aspirate:50.0",
        "dispense:50.0",
        "aspirate:50.0",
        "dispense:50.0",
        "blowout",
        "drop_tip",
    ]
    assert controller.moves
    assert all(travel_z is None for *_xyz, travel_z in controller.moves)
    serialized = context.serialized_motion_plans()
    assert serialized
    assert any(plan["state_changes"] for plan in serialized)
    assert all(
        segment["axis"] in {"x", "y", "z", "xy"}
        for plan in serialized
        for segment in plan["segments"]
    )


def test_vertical_pickup_attaches_between_engagement_and_retraction() -> None:
    context, controller, pipette = _context()
    observed = []
    move = controller.move_linear_to

    def record_move(x, y, z):
        observed.append(((x, y, z), pipette.attached_tip_extension))
        move(x, y, z)

    controller.move_linear_to = record_move
    compile_protocol([CommandCall("pick_up_tip", {"position": "tips.A1"})]).execute(context)

    pickup = context.planned_motion_steps[0]
    assert [plan.operation for plan in pickup.plans] == ["approach", "engage", "departure"]
    assert observed == [
        ((20, 20, 80), 0),
        ((20, 20, 30), 0),
        ((20, 20, 80), 20),
    ]
    assert all(segment.axis == "z" for plan in pickup.plans[1:] for segment in plan.segments)
    assert pickup.plans[2].state_changes[0].position == pickup.plans[1].end
    assert not context.deck["tips"].is_tip_present("A1")
    assert pipette.actions == ["pick_up_tip"]


@pytest.mark.parametrize("obstruction", ["long_tip", "neighbor_tip", "passive_camera"])
def test_vertical_pickup_collision_rejects_before_movement(obstruction) -> None:
    context, controller, pipette = _context(with_camera=obstruction == "passive_camera")
    rack = context.deck["tips"]
    if obstruction == "long_tip":
        rack.tip_length = 70
    elif obstruction == "neighbor_tip":
        rack.tips["A2"] = type(rack.tips["A1"])(x=22, y=20, z=50)
        rack.tip_present["A2"] = True
    else:
        context.gantry.instruments["camera"].offset_y = 0

    with pytest.raises(ProtocolExecutionError, match="preflight failed"):
        compile_protocol([CommandCall("pick_up_tip", {"position": "tips.A1"})]).execute(context)

    assert controller.moves == []
    assert pipette.actions == []
    assert rack.is_tip_present("A1")


@pytest.mark.parametrize("fail_retraction", [False, True])
def test_tracked_vertical_pickup_commits_only_after_retraction(fail_retraction) -> None:
    from cubos.gantry.gantry_driver.exceptions import MillConnectionError

    context, controller, pipette = _context()
    context.fluid_state_id, context.campaign_id = 17, 7
    store = context.data_store = Mock()
    store.get_tip_snapshot.return_value = {"containers": [
        {"rack_key": "tips", "slot_id": "A1", "status": "available"},
    ]}
    store.begin_pick_up_tip.return_value = (True, "A1", 20)
    failure = MillConnectionError("retraction interrupted")
    move = controller.move_linear_to

    def retract(x, y, z):
        if fail_retraction and pipette.attached_tip_extension:
            raise failure
        move(x, y, z)

    def commit(_operation_key):
        assert controller.get_coordinates() == {"x": 20, "y": 20, "z": 80}

    controller.move_linear_to = retract
    store.complete_pick_up_tip.side_effect = commit
    protocol = compile_protocol([CommandCall("pick_up_tip", {"position": "tips.A1"})])
    if fail_retraction:
        with pytest.raises(MillConnectionError) as raised:
            protocol.execute(context)
        assert raised.value is failure
        store.complete_pick_up_tip.assert_not_called()
        store.mark_tip_reconciliation_required.assert_called_once()
    else:
        protocol.execute(context)
        store.complete_pick_up_tip.assert_called_once()
        store.mark_tip_reconciliation_required.assert_not_called()
    assert not context.deck["tips"].is_tip_present("A1")
    assert pipette.attached_tip_extension == 20


def test_transfer_destination_no_route_rejects_before_pickup_or_aspirate() -> None:
    context, controller, pipette = _context(blocker=True)

    with pytest.raises(ProtocolExecutionError, match="preflight failed"):
        _native_protocol().execute(context)

    assert controller.moves == []
    assert pipette.actions == []
    assert pipette.attached_tip_extension == 0


@pytest.mark.parametrize("command,args", [
    ("home", {}),
])
def test_unsupported_command_rejects_before_earlier_supported_movement(command, args) -> None:
    context, controller, pipette = _context()
    protocol = compile_protocol([
        CommandCall("pick_up_tip", {"position": "tips.A1"}),
        CommandCall(command, args),
    ])

    with pytest.raises(ProtocolExecutionError, match=rf"step 1 \({command}\)"):
        protocol.execute(context)

    assert controller.moves == []
    assert pipette.actions == []


def test_measure_remains_unsupported_for_planning_before_prior_movement() -> None:
    context, controller, pipette = _context()
    protocol = compile_protocol([
        CommandCall("pick_up_tip", {"position": "tips.A1"}),
        CommandCall("measure", {
            "instrument": "pipette",
            "position": "destination",
            "measurement_height": 0.0,
        }),
    ])

    with pytest.raises(ProtocolExecutionError, match=r"step 1 \(measure\)"):
        protocol.execute(context)

    assert controller.moves == []
    assert pipette.actions == []


@pytest.mark.parametrize("instrument", ["pipette", "missing"])
def test_invalid_planned_capture_rejects_before_prior_movement(instrument) -> None:
    context, controller, pipette = _context(with_camera=True)
    protocol = compile_protocol([
        CommandCall("pick_up_tip", {"position": "tips.A1"}),
        CommandCall("capture", {"instrument": instrument}),
    ])

    with pytest.raises(ProtocolExecutionError, match="capture instrument"):
        protocol.execute(context)

    assert controller.moves == []
    assert pipette.actions == []


def test_invalid_capture_position_rejects_before_prior_movement() -> None:
    context, controller, pipette = _context(with_camera=True)
    protocol = compile_protocol([
        CommandCall("pick_up_tip", {"position": "tips.A1"}),
        CommandCall("capture", {
            "instrument": "camera",
            "position": "missing.A1",
        }),
    ])

    with pytest.raises(ProtocolExecutionError, match="missing.A1"):
        protocol.execute(context)

    assert controller.moves == []
    assert pipette.actions == []


def test_transfer_camera_capture_cycles_use_safe_tool_handoffs(
    tmp_path, monkeypatch,
) -> None:
    context, controller, pipette = _context(with_camera=True)
    monkeypatch.setattr("cubos.protocol_engine.commands.camera.default_images_dir", lambda: tmp_path)
    context.campaign_id = None
    protocol = _camera_capture_protocol()

    results = protocol.execute(context)

    camera = context.gantry.instruments["camera"]
    assert len(camera.captures) == 3
    assert len(set(camera.captures)) == 3
    assert all(Path(path).is_file() for path in camera.captures)
    assert [results[index] for index in (3, 6, 9)] == camera.captures
    for capture_index in (3, 6, 9):
        assert context.planned_motion_steps[capture_index].plans == ()
    for move_index in (2, 5, 8):
        segments = context.planned_motion_steps[move_index].plans[0].segments
        departure = segments[0]
        assert departure.axis == "z"
        assert departure.access.allowed_fixture_names == ("destination",)
        assert departure.access.allowed_tool_names == ("pipette",)
        assert departure.tool_state.instrument == "pipette"
        assert departure.tool_state.attached_tip_extension_mm == 20
        assert any(
            segment.access.allowed_tool_names == ("camera",)
            for segment in segments[1:]
        )
    assert len(controller.moves) == sum(
        len(plan.segments) for plan in context.motion_plans
    )
    assert pipette.actions.count("dispense:100.0") == 3


def test_later_unroutable_camera_move_rejects_before_pickup() -> None:
    context, controller, pipette = _context(with_camera=True)
    context.gantry.instruments["camera"].offset_x = -100.0

    with pytest.raises(ProtocolExecutionError, match="preflight failed"):
        _camera_capture_protocol().execute(context)

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


def test_durable_tip_state_selects_an_available_tip() -> None:
    context, controller, _pipette = _context()
    rack = context.deck["tips"]
    coordinate_type = type(rack.tips["A1"])
    rack.tips["A2"] = coordinate_type(x=30, y=20, z=50)
    rack.tip_present["A2"] = True
    context.fluid_state_id = 17
    context.data_store = Mock()
    context.data_store.get_tip_snapshot.return_value = {
        "containers": [
            {"rack_key": "tips", "slot_id": "A1", "status": "consumed"},
            {"rack_key": "tips", "slot_id": "A2", "status": "available"},
        ],
    }
    protocol = compile_protocol([
        CommandCall("pick_up_tip", {"position": "tips.A2"}),
        CommandCall("drop_tip", {"position": "waste"}),
    ])

    prepare_planning_context(protocol, context)

    assert context.planned_motion_steps[0].data["position"] == "tips.A2"
    assert controller.moves == []


def test_durable_tip_state_rejects_consumed_explicit_target_before_motion() -> None:
    context, controller, _pipette = _context()
    context.fluid_state_id = 17
    context.data_store = Mock()
    context.data_store.get_tip_snapshot.return_value = {
        "containers": [
            {"rack_key": "tips", "slot_id": "A1", "status": "consumed"},
        ],
    }

    with pytest.raises(ProtocolExecutionError, match="tips.A1.*unavailable"):
        prepare_planning_context(_native_protocol(), context)

    assert controller.moves == []








def test_native_move_executes_cached_intermediate_detour_when_both_direct_orders_block() -> None:
    def tall_blocker(name, x, y):
        value = _vial(name, x, y)
        value["motion"]["box"] = {
            "anchor": "location",
            "offset": {"x": -5, "y": -5, "z": -40},
            "size": {"x": 10, "y": 10, "z": 140},
        }
        return value

    deck = _build_deck_from_raw({
        "motion_planning": {"clearance_mm": 1},
        "labware": {
            "blocks_x_first": tall_blocker("blocks x first", 60, 20),
            "blocks_y_first": tall_blocker("blocks y first", 20, 60),
        },
    })
    config = GantryConfig(
        serial_port="offline",
        gantry_type=GantryType.CUB,
        factory_z_travel_mm=100,
        working_volume=WorkingVolume(0, 100, 0, 100, 0, 80),
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
    controller.coords = {"x": 20.0, "y": 20.0, "z": 80.0}
    pipette = FakePipette()
    pipette.depth = 0.0
    gantry = InstrumentedGantry(
        controller,
        {"pipette": pipette},
        safe_z=80,
        motion_envelopes=config.motion_envelopes,
    )
    context = ProtocolContext(gantry=gantry, deck=deck, gantry_config=config)
    protocol = compile_protocol([
        CommandCall("move", {
            "instrument": "pipette",
            "position": [80, 80, 80],
        }),
    ])

    protocol.execute(context)

    plan = context.motion_plans[0]
    assert "detour:" in plan.strategy
    assert len(plan.segments) == 3
    assert [move[:3] for move in controller.moves] == [
        (segment.end.x, segment.end.y, segment.end.z)
        for segment in plan.segments
    ]
    assert all(move[3] is None for move in controller.moves)
    assert all(
        segment.access.allowed_tool_names == ("pipette",)
        and not segment.access.allowed_fixture_names
        and not segment.access.allowed_corridor_names
        for segment in plan.segments
    )


def test_routed_ordinary_transit_uses_diagonal_with_instrument_identity() -> None:
    context, controller, _pipette = _context()
    controller.coords = {"x": 20.0, "y": 20.0, "z": 80.0}
    protocol = compile_protocol([
        CommandCall("move", {
            "instrument": "pipette",
            "position": [80, 80, 80],
        }),
    ])

    protocol.execute(context)

    plan = context.motion_plans[0]
    diagonal_segments = [segment for segment in plan.segments if segment.axis == "xy"]
    assert len(diagonal_segments) == 1
    diagonal = diagonal_segments[0]
    assert diagonal.access.allowed_tool_names == ("pipette",)
    assert not diagonal.access.allowed_fixture_names
    assert not diagonal.access.allowed_corridor_names
    assert diagonal.start.z == diagonal.end.z == 80.0
    assert diagonal.end.x == 80.0
    assert diagonal.end.y == 80.0
    assert [move[:3] for move in controller.moves] == [
        (segment.end.x, segment.end.y, segment.end.z)
        for segment in plan.segments
    ]
    assert all(move[3] is None for move in controller.moves)


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


def _standalone_call(command, position="destination", height=0.0):
    args = {"position": position, "height": height, "speed": 25.0}
    if command != "blowout":
        args["volume_ul"] = 100.0
    return CommandCall(command, args)


def test_standalone_yaml_executes_exact_plans_and_pause_preserves_pose(tmp_path, monkeypatch):
    import importlib
    from cubos.protocol_engine.loader import load_protocol_from_yaml

    context, controller, pipette = _context()
    path = tmp_path / "standalone.yaml"
    path.write_text("""protocol:
- pick_up_tip: {position: tips.A1}
- aspirate: {position: source, volume_ul: 100, speed: 25, height: -5}
- pause: {seconds: 300, reason: settling}
- dispense: {position: destination, volume_ul: 100, speed: 25, height: -3}
- blowout: {position: destination, speed: 25, height: 0}
- drop_tip: {position: waste}
""")
    pause_poses = []
    pause_module = importlib.import_module("cubos.protocol_engine.commands.pause")
    monkeypatch.setattr(pause_module.time, "sleep", lambda seconds: pause_poses.append(
        (seconds, controller.get_coordinates(), list(pipette.actions)),
    ))
    action_poses = {}
    for command in ("aspirate", "dispense", "blowout"):
        original = getattr(pipette, command)
        def record(*args, _command=command, _original=original):
            action_poses[_command] = controller.get_coordinates()
            return _original(*args)
        setattr(pipette, command, Mock(side_effect=record))
    # Any fallback to legacy engagement fails the test.
    monkeypatch.setattr(context.gantry, "move_to_labware", Mock(side_effect=AssertionError("legacy move")))

    load_protocol_from_yaml(path).execute(context)

    assert pipette.actions == ["pick_up_tip", "aspirate:100.0", "dispense:100.0", "blowout", "drop_tip"]
    assert pause_poses == [(300.0, {"x": 60.0, "y": 60.0, "z": 35.0}, ["pick_up_tip", "aspirate:100.0"])]
    assert context.planned_motion_steps[2].plans == ()
    assert action_poses == {
        "aspirate": {"x": 60.0, "y": 60.0, "z": 35.0},
        "dispense": {"x": 80.0, "y": 60.0, "z": 37.0},
        "blowout": {"x": 80.0, "y": 60.0, "z": 40.0},
    }
    pipette.aspirate.assert_called_once_with(100.0, 25.0)
    pipette.dispense.assert_called_once_with(100.0, 25.0)
    pipette.blowout.assert_called_once_with(25.0)
    assert controller.moves == [
        (segment.end.x, segment.end.y, segment.end.z, None)
        for plan in context.motion_plans for segment in plan.segments
    ]


@pytest.mark.parametrize("command", ["aspirate", "dispense", "blowout"])
def test_standalone_blocked_destination_rejects_before_pickup(command):
    context, controller, pipette = _context(blocker=True)
    protocol = compile_protocol([
        CommandCall("pick_up_tip", {"position": "tips.A1"}),
        _standalone_call("aspirate", "source"),
        _standalone_call(command),
    ])
    with pytest.raises(ProtocolExecutionError, match="preflight failed"):
        protocol.execute(context)
    assert controller.moves == []
    assert pipette.actions == []


@pytest.mark.parametrize("command", ["aspirate", "dispense", "blowout"])
def test_standalone_missing_tip_rejects_before_movement(command):
    context, controller, pipette = _context()
    with pytest.raises(ProtocolExecutionError, match="requires an attached pipette tip"):
        compile_protocol([_standalone_call(command)]).execute(context)
    assert controller.moves == []
    assert pipette.actions == []


@pytest.mark.parametrize("command", ["aspirate", "dispense", "blowout"])
def test_standalone_durable_tracking_rejects_before_pickup(command):
    context, controller, pipette = _context()
    context.fluid_state_id = 1
    context.campaign_id = 1
    context.data_store = Mock()
    protocol = compile_protocol([
        CommandCall("pick_up_tip", {"position": "tips.A1"}),
        _standalone_call(command),
    ])
    with pytest.raises(ProtocolExecutionError, match="durable fluid tracking"):
        protocol.execute(context)
    assert controller.moves == []
    assert pipette.actions == []


@pytest.mark.parametrize("command", ["aspirate", "dispense", "blowout"])
def test_standalone_out_of_bounds_height_rejects_before_pickup(command):
    context, controller, pipette = _context()
    protocol = compile_protocol([
        CommandCall("pick_up_tip", {"position": "tips.A1"}),
        _standalone_call(command, height=100),
    ])
    with pytest.raises(ProtocolExecutionError, match="preflight failed"):
        protocol.execute(context)
    assert controller.moves == []
    assert pipette.actions == []


@pytest.mark.parametrize("position", [[90.0, 70.0, 80.0], "park", "destination"])
def test_planned_move_applies_offsets_to_every_position_form(position):
    context, controller, _ = _context()
    context.positions["park"] = (90.0, 70.0, 80.0)
    protocol = compile_protocol([CommandCall("move", {
        "instrument": "pipette", "position": position,
        "x_offset_mm": 2.0, "y_offset_mm": -3.0,
    })])
    protocol.positions["park"] = (90.0, 70.0, 80.0)
    protocol.execute(context)
    expected = (82.0, 57.0, 80.0) if position == "destination" else (92.0, 67.0, 60.0)
    assert controller.moves[-1] == (*expected, None)


@pytest.mark.parametrize("command", ["aspirate", "dispense", "blowout", "mix", "drop_tip", "transfer"])
def test_routed_liquid_commands_preserve_offsets_and_execute_only_planned_segments(command, monkeypatch):
    context, controller, pipette = _context()
    poses = []
    for action in ("aspirate", "dispense", "blowout", "drop_tip"):
        original = getattr(pipette, action)
        def record(*args, _action=action, _original=original):
            poses.append((_action, controller.get_coordinates()))
            return _original(*args)
        monkeypatch.setattr(pipette, action, record)
    monkeypatch.setattr(context.gantry, "move", Mock(side_effect=AssertionError("legacy move")))
    if command == "transfer":
        args = {
            "source": "source", "destination": "destination", "volume_ul": 50,
            "source_x_offset_mm": -2.0, "source_y_offset_mm": 1.0,
            "destination_x_offset_mm": 2.0, "destination_y_offset_mm": -3.0,
        }
    else:
        args = {"position": "destination", "x_offset_mm": 2.0, "y_offset_mm": -3.0}
        if command in {"aspirate", "dispense", "mix"}:
            args["volume_ul"] = 50.0
        if command == "mix":
            args["cycles"] = 1
    compile_protocol([
        CommandCall("pick_up_tip", {"position": "tips.A1"}),
        CommandCall(command, args),
    ]).execute(context)
    if command == "transfer":
        assert poses[0] == ("aspirate", {"x": 58.0, "y": 61.0, "z": 40.0})
    assert any(pose == {"x": 82.0, "y": 57.0, "z": 40.0} for _, pose in poses)
    assert controller.moves == [
        (segment.end.x, segment.end.y, segment.end.z, None)
        for plan in context.motion_plans for segment in plan.segments
    ]


@pytest.mark.parametrize("command", ["move", "aspirate", "transfer"])
def test_offset_collision_fails_whole_protocol_before_pickup(command):
    context, controller, pipette = _context()
    if command == "move":
        args = {"instrument": "pipette", "position": [80, 60, 40], "x_offset_mm": 100}
    elif command == "transfer":
        args = {"source": "source", "destination": "destination", "volume_ul": 50,
                "destination_x_offset_mm": 100}
    else:
        args = {"position": "destination", "volume_ul": 50, "x_offset_mm": 100}
    with pytest.raises(ProtocolExecutionError, match="preflight failed"):
        compile_protocol([
            CommandCall("pick_up_tip", {"position": "tips.A1"}), CommandCall(command, args),
        ]).execute(context)
    assert controller.moves == []
    assert pipette.actions == []


@pytest.mark.parametrize("offset", [{"x_offset_mm": 1}, {"y_offset_mm": -1}])
def test_planned_tip_pickup_rejects_shift_away_from_registered_slot(offset):
    context, controller, pipette = _context()
    with pytest.raises(ProtocolExecutionError, match="zero XY offsets"):
        compile_protocol([
            CommandCall("pick_up_tip", {"position": "tips.A1", **offset}),
        ]).execute(context)
    assert controller.moves == []
    assert pipette.actions == []


@pytest.mark.parametrize("command", ["blowout", "transfer", "mix"])
@pytest.mark.parametrize("failure", [None, "withdrawal", "home"])
def test_routed_picus_blowout_withdrawal_is_planned_and_precedes_home(command, failure, monkeypatch):
    from cubos.gantry.errors import MillConnectionError

    context, controller, pipette = _context()
    pipette.requires_home_after_blowout = True
    events = []
    original_move = controller.move_linear_to
    def move(x, y, z):
        events.append(("move", x, y, z))
        if failure == "withdrawal" and len(events) > 1 and events[-2] == ("blowout",):
            raise MillConnectionError("withdrawal failed")
        original_move(x, y, z)
    monkeypatch.setattr(controller, "move_linear_to", move)
    monkeypatch.setattr(context.gantry, "move", Mock(side_effect=AssertionError("legacy move")))
    monkeypatch.setattr(pipette, "blowout", lambda speed: events.append(("blowout",)))
    def home():
        events.append(("home",))
        if failure == "home":
            raise RuntimeError("home failed")
    pipette.home = home
    args = {"destination_x_offset_mm": 2, "destination_y_offset_mm": -3,
            "source": "source", "destination": "destination", "volume_ul": 50,
            "destination_height": -5} if command == "transfer" else {
                "position": "destination", "height": -5, "x_offset_mm": 2, "y_offset_mm": -3,
            }
    if command == "mix":
        args.update(volume_ul=50, cycles=1, blowout_height=3)
    protocol = compile_protocol([
        CommandCall("pick_up_tip", {"position": "tips.A1"}),
        CommandCall(command, args),
        CommandCall("aspirate", {"position": "source", "volume_ul": 50}),
    ])
    if failure:
        with pytest.raises((MillConnectionError, RuntimeError), match=f"{failure} failed"):
            protocol.execute(context)
    else:
        protocol.execute(context)
        assert controller.moves == [
            (segment.end.x, segment.end.y, segment.end.z, None)
            for plan in context.motion_plans for segment in plan.segments
        ]
    i = events.index(("blowout",))
    assert events[i + 1] == ("move", 82.0, 57.0, 80.0)
    if failure == "withdrawal":
        assert ("home",) not in events
    else:
        assert events[i + 2] == ("home",)


def test_routed_picus_invalid_withdrawal_fails_before_pickup():
    context, controller, pipette = _context()
    pipette.requires_home_after_blowout = True
    context.gantry.safe_z = 100.0
    with pytest.raises(ProtocolExecutionError, match="preflight failed"):
        compile_protocol([
            CommandCall("pick_up_tip", {"position": "tips.A1"}),
            CommandCall("blowout", {"position": "destination"}),
        ]).execute(context)
    assert controller.moves == []
    assert pipette.actions == []


@pytest.mark.parametrize("command, volume, strokes", [("blowout", 0, 0), ("transfer", 50, 1), ("transfer", 2500, 3)])
def test_real_picus_routed_reset_preserves_next_step_start(command, volume, strokes, monkeypatch):
    from cubos.instruments.pipette.vendors.sartorius import SartoriusPicus2Pipette

    context, controller, _ = _context()
    pipette = SartoriusPicus2Pipette(name="pipette", depth=-20.0)
    pipette._initialized = True
    context.gantry.instruments["pipette"] = pipette
    events = []
    monkeypatch.setattr(pipette, "_send", lambda cmd, **kwargs: events.append((cmd, controller.get_coordinates())))
    args = {"position": "destination", "height": -5} if command == "blowout" else {
        "source": "source", "destination": "destination", "volume_ul": volume,
        "destination_height": -5,
    }
    compile_protocol([
        CommandCall("pick_up_tip", {"position": "tips.A1"}),
        CommandCall(command, args),
        CommandCall("aspirate", {"position": "source", "volume_ul": 50}),
    ]).execute(context)
    blowout_index, = [i for i, (cmd, _) in enumerate(events) if cmd.startswith("BLOW_OUT")]
    assert events[blowout_index][1] == {"x": 80.0, "y": 60.0, "z": 35.0}
    assert events[blowout_index + 1] == ("HOME", {"x": 80.0, "y": 60.0, "z": 80.0})
    assert events[blowout_index + 2][0].startswith("RUN_ASPIRATE")
    assert events[blowout_index + 2][1] == {"x": 60.0, "y": 60.0, "z": 40.0}
    assert sum(cmd.startswith("RUN_ASPIRATE") for cmd, _ in events) == strokes + 1
    assert controller.moves == [
        (segment.end.x, segment.end.y, segment.end.z, None)
        for plan in context.motion_plans for segment in plan.segments
    ]


@pytest.mark.parametrize("command, args", [
    ("image_well", {"camera": "camera", "well": "source", "image_height": 20}),
    ("pipette_home", {}),
])
def test_new_unsupported_commands_remain_fail_closed_on_routed_decks(command, args):
    context, controller, pipette = _context(with_camera=True)
    with pytest.raises(ProtocolExecutionError, match="does not support"):
        compile_protocol([
            CommandCall("pick_up_tip", {"position": "tips.A1"}), CommandCall(command, args),
        ]).execute(context)
    assert controller.moves == []
    assert pipette.actions == []


@pytest.fixture(params=["opentrons", "picus"])
def multi_rig(request, monkeypatch):
    from cubos.instruments.pipette.vendors.opentrons import OpentronsPipette
    from cubos.instruments.pipette.vendors.sartorius import SartoriusPicus2Pipette

    monkeypatch.setattr("serial.Serial", lambda *a, **kw: pytest.fail("No physical serial ports"))
    context, controller, _ = _context()
    cls, model = (OpentronsPipette, "p300_single_gen2") if request.param == "opentrons" else (
        SartoriusPicus2Pipette, "picus2_1ch_120",
    )
    pipette = cls(name="pipette", depth=-20, pipette_model=model, offline=True)
    context.gantry.instruments["pipette"] = pipette
    events = []
    for name in ("pick_up_tip", "aspirate", "dispense", "blowout", "home", "drop_tip"):
        original = getattr(pipette, name)

        def record(*args, name=name, original=original):
            result = original(*args)
            events.append((name, args, pipette.loaded_volume_ul))
            return result

        monkeypatch.setattr(pipette, name, record)
    original_move = controller.move_linear_to

    def move(x, y, z):
        original_move(x, y, z)
        events.append(("move", (x, y, z)))

    monkeypatch.setattr(controller, "move_linear_to", move)
    monkeypatch.setattr(context.gantry, "move", lambda *a, **kw: pytest.fail("Unplanned movement"))
    return context, controller, pipette, events


def _multi_protocol(**overrides):
    args = {"source": "source", "destinations": ["destination", "waste"], "volumes": [40.0, 60.0]}
    args.update(overrides)
    return compile_protocol([
        CommandCall("pick_up_tip", {"position": "tips.A1"}),
        CommandCall("multi_dispense", args),
        CommandCall("drop_tip", {"position": "waste"}),
    ])


def test_routed_multi_dispense_executes_exact_plans_and_one_aspiration(multi_rig):
    context, controller, pipette, events = multi_rig
    protocol = _multi_protocol(source_height=-2, destination_height=3)
    prepare_planning_context(protocol, context)
    segments = [segment for plan in context.motion_plans for segment in plan.segments]
    assert not events
    protocol.execute(context)
    assert [(x, y, z) for x, y, z, _ in controller.moves] == [
        (segment.end.x, segment.end.y, segment.end.z) for segment in segments
    ]
    assert [(e[0], e[1][0], e[2]) for e in events if e[0] in ("aspirate", "dispense")] == [
        ("aspirate", 100, 100), ("dispense", 40, 60), ("dispense", 60, 0),
    ]
    assert len([e for e in events if e[0] == "blowout"]) == 1
    index = next(i for i, e in enumerate(events) if e[0] == "blowout")
    assert events[index - 1] == ("dispense", (60.0, 50.0), 0)
    if pipette.requires_home_after_blowout:
        assert events[index + 1:index + 3] == [("move", (100.0, 60.0, 80.0)), ("home", (), 0)]
    assert pipette.loaded_volume_ul == 0
    assert pipette.attached_tip_extension == 0


@pytest.mark.parametrize("destinations,volumes", [(["destination"], [100.0]), (["destination", "destination"], [40.0, 60.0])])
def test_routed_multi_dispense_single_and_repeated_targets(multi_rig, destinations, volumes):
    context, _, _, events = multi_rig
    _multi_protocol(destinations=destinations, volumes=volumes).execute(context)
    assert len([e for e in events if e[0] == "aspirate"]) == 1
    assert [e[1][0] for e in events if e[0] == "dispense"] == volumes


@pytest.mark.parametrize("overrides,match", [
    ({"destinations": ["destination", "missing"]}, "missing"),
    ({"volumes": [1000.0, 1000.0]}, "volume|stroke"),
    ({"volumes": []}, "one volume"),
    ({"destination_height": 50.0}, "safe_z"),
    ({"destination_height": -100.0}, "preflight failed"),
    ({"speed": 101.0}, "speed"),
])
def test_routed_multi_dispense_bad_last_target_or_batch_prevents_prior_pickup(multi_rig, overrides, match):
    context, controller, _, events = multi_rig
    with pytest.raises(ProtocolExecutionError, match=match):
        _multi_protocol(**overrides).execute(context)
    assert controller.moves == []
    assert events == []


def test_routed_multi_dispense_blocked_final_destination_rejects_entire_protocol(multi_rig):
    context, controller, _, events = multi_rig
    raw = {"motion_planning": {"clearance_mm": 1}, "labware": {
        "source": _vial("source", 60, 60),
        "destination": _vial("destination", 80, 60),
        "waste": _vial("waste", 100, 60),
        "blocker": _vial("blocker", 100, 60, size=16),
    }}
    context.deck = _build_deck_from_raw(raw)
    context.gantry.instruments["pipette"].set_attached_tip_extension(20)
    protocol = compile_protocol([CommandCall("multi_dispense", _multi_protocol().steps[1].args)])
    with pytest.raises(ProtocolExecutionError, match="preflight failed"):
        protocol.execute(context)
    assert controller.moves == []
    assert events == []


def test_routed_multi_dispense_detours_around_tall_obstacle(multi_rig):
    context, controller, pipette, events = multi_rig
    obstacle = _vial("obstacle", 70, 60, size=8)
    obstacle["motion"]["box"]["size"]["z"] = 100
    context.deck = _build_deck_from_raw({"motion_planning": {"clearance_mm": 1}, "labware": {
        "source": _vial("source", 50, 60), "destination": _vial("destination", 90, 60),
        "waste": _vial("waste", 105, 60), "obstacle": obstacle,
    }})
    pipette.set_attached_tip_extension(20)
    protocol = compile_protocol([CommandCall("multi_dispense", _multi_protocol().steps[1].args)])
    prepare_planning_context(protocol, context)
    transit = context.planned_motion_steps[0].plans[1]
    assert any(abs(segment.end.y - 60) > 6 for segment in transit.segments)
    protocol.execute(context)
    assert len([e for e in events if e[0] == "aspirate"]) == 1
    assert controller.moves


@pytest.mark.parametrize("kind", ["tip", "pose", "loaded", "arguments", "blowout"])
def test_routed_multi_dispense_runtime_rejects_stale_state_or_arguments(multi_rig, kind):
    from cubos.protocol_engine.commands.pipette import multi_dispense

    context, controller, pipette, events = multi_rig
    pipette.set_attached_tip_extension(20)
    args = _multi_protocol().steps[1].args
    protocol = compile_protocol([CommandCall("multi_dispense", args)])
    prepare_planning_context(protocol, context)
    context.active_step_index = 0
    if kind == "tip":
        pipette.clear_attached_tip_extension()
    elif kind == "pose":
        controller.coords["x"] -= 1
    elif kind == "loaded":
        pipette.aspirate(40)
        events.clear()
    elif kind == "arguments":
        args = {**args, "destinations": ["waste", "destination"]}
    else:
        # Toggle only the simulated pipette capability after its plan was built.
        from unittest.mock import PropertyMock, patch
        with patch.object(type(pipette), "requires_home_after_blowout", new_callable=PropertyMock, return_value=not pipette.requires_home_after_blowout):
            with pytest.raises(ProtocolExecutionError, match="requirements changed"):
                multi_dispense(context, **args)
        assert not events
        return
    with pytest.raises((ProtocolExecutionError, ValueError)):
        multi_dispense(context, **args)
    assert controller.moves == []
    assert events == []


@pytest.mark.parametrize("stage", ["aspirate", "second_dispense", "move", "blowout", "retract", "home"])
def test_routed_multi_dispense_failure_stops_without_retry_or_recovery(multi_rig, monkeypatch, stage):
    from cubos.gantry.errors import MillConnectionError

    context, _, pipette, events = multi_rig
    if stage in {"retract", "home"} and not pipette.requires_home_after_blowout:
        pytest.skip("This pipette does not retract/home after blowout")
    failure = MillConnectionError("simulated connection loss")
    protocol = _multi_protocol()
    prepare_planning_context(protocol, context)
    if stage in {"aspirate", "blowout", "home"}:
        monkeypatch.setattr(pipette, stage, Mock(side_effect=failure))
    elif stage == "second_dispense":
        original = pipette.dispense
        calls = []
        def dispense(*args):
            calls.append(args)
            if len(calls) == 2:
                raise failure
            return original(*args)
        monkeypatch.setattr(pipette, "dispense", dispense)
    else:
        original = context.routing_session.execute
        planned = context.planned_motion_steps[1]
        target = planned.data["blowout_retract"] if stage == "retract" else planned.plans[2]
        def execute(plan):
            if plan is target:
                raise failure
            original(plan)
        monkeypatch.setattr(context.routing_session, "execute", execute)
    with pytest.raises(MillConnectionError) as caught:
        protocol.execute(context)
    assert caught.value is failure
    assert len([e for e in events if e[0] == "aspirate"]) <= 1
    assert not any(e[0] == "drop_tip" for e in events)
    if stage in {"move", "second_dispense"}:
        assert pipette.loaded_volume_ul == 60
        assert not any(e[0] in {"blowout", "home"} for e in events)


def test_routed_multi_dispense_requires_tip_and_rejects_durable_tracking(multi_rig):
    context, controller, _, events = multi_rig
    protocol = compile_protocol([CommandCall("multi_dispense", _multi_protocol().steps[1].args)])
    with pytest.raises(ProtocolExecutionError, match="attached pipette tip"):
        protocol.execute(context)
    context.fluid_state_id = 1
    context.data_store = Mock()
    with pytest.raises(ProtocolExecutionError, match="durable fluid tracking"):
        _multi_protocol().execute(context)
    assert controller.moves == []
    assert events == []
