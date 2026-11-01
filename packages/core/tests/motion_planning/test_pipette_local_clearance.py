from __future__ import annotations

from typing import Any

import pytest

from cubos.deck.loader import _build_deck_from_raw
from cubos.gantry.gantry_config import GantryConfig, GantryType, WorkingVolume
from cubos.gantry.errors import MillConnectionError
from cubos.gantry.instrument_mount import InstrumentedGantry
from cubos.instruments.pipette.liquid_class import IDENTITY_CORRECTION
from cubos.instruments.pipette.models import PipetteConfig, PipetteFamily
from cubos.motion_planning import Point3D, ToolState
from cubos.protocol_engine.compiler import CommandCall, compile_protocol
from cubos.protocol_engine.errors import ProtocolExecutionError
from cubos.protocol_engine.routing import prepare_planning_context
from cubos.protocol_engine.runtime import ProtocolContext


class _Controller:
    def __init__(self) -> None:
        self.coords = {"x": 60.0, "y": 50.0, "z": 80.0}
        self.moves: list[tuple[float, float, float, float | None]] = []

    def get_coordinates(self) -> dict[str, float]:
        return dict(self.coords)

    def move_linear_to(self, x: float, y: float, z: float) -> None:
        self.move_to(x, y, z)

    def move_to(self, x: float, y: float, z: float, travel_z: float | None = None) -> None:
        self.moves.append((x, y, z, travel_z))
        self.coords = {"x": x, "y": y, "z": z}


class _Pipette:
    name = "pipette"
    offset_x = 0.0
    offset_y = 0.0
    depth = -20.0

    def __init__(self) -> None:
        self.attached_tip_extension = 20.0
        self.actions: list[tuple[str, tuple[Any, ...]]] = []
        self.config: PipetteConfig | None = None

    @property
    def effective_depth(self) -> float:
        return self.depth + self.attached_tip_extension

    def correction_for(self, _liquid_class: str | None = None):
        return IDENTITY_CORRECTION

    def aspirate(self, *args) -> None:
        self.actions.append(("aspirate", args))

    def dispense(self, *args) -> None:
        self.actions.append(("dispense", args))

    def blowout(self, *args) -> None:
        self.actions.append(("blowout", args))


class _Camera:
    name = "camera"
    offset_x = 0.0
    offset_y = 0.0
    depth = -20.0


def _plate(*, camera: bool = False, wall: bool = False, second_plate: bool = False) -> tuple[ProtocolContext, _Controller, _Pipette]:
    labware: dict[str, dict[str, Any]] = {
        "plate": {
            "type": "well_plate",
            "name": "plate",
            "model_name": "two_well_plate",
            "length": 40.0,
            "width": 20.0,
            "height": 14.0,
            "well_depth": 10.0,
            "rows": 1,
            "columns": 2,
            "calibration": {
                "a1": {"x": 60.0, "y": 50.0, "z": 40.0},
                "a2": {"x": 80.0, "y": 50.0, "z": 40.0},
            },
            "x_offset": 20.0,
            "y_offset": 10.0,
            "capacity_ul": 200.0,
            "working_volume_ul": 150.0,
            "motion": {
                "box": {
                    "anchor": "A1",
                    "offset": {"x": -10.0, "y": -10.0, "z": -14.0},
                    "size": {"x": 40.0, "y": 20.0, "z": 14.0},
                },
            },
        },
    }
    if wall:
        labware["wall"] = {
            "type": "vial",
            "name": "wall",
            "height": 70.0,
            "diameter": 8.0,
            "location": {"x": 70.0, "y": 0.0, "z": 0.0},
            "capacity_ul": 1000.0,
            "working_volume_ul": 900.0,
            "motion": {
                "box": {
                    "anchor": "location",
                    "offset": {"x": -1.0, "y": 0.0, "z": 0.0},
                    "size": {"x": 2.0, "y": 100.0, "z": 70.0},
                },
            },
        }
    if second_plate:
        other = dict(labware["plate"])
        other["name"] = "other_plate"
        other["calibration"] = {
            "a1": {"x": 105.0, "y": 50.0, "z": 40.0},
            "a2": {"x": 115.0, "y": 50.0, "z": 40.0},
        }
        other["x_offset"] = 10.0
        labware["other_plate"] = other

    deck = _build_deck_from_raw({
        "motion_planning": {"clearance_mm": 1.0},
        "labware": labware,
    })
    controller = _Controller()
    pipette = _Pipette()
    instruments: dict[str, Any] = {"pipette": pipette}
    instrument_configs: dict[str, dict[str, str]] = {
        "pipette": {"type": "pipette", "vendor": "fake"},
    }
    envelopes: dict[str, dict[str, Any]] = {
        "pipette": {
            "box": {
                "offset": {"x": -2.0, "y": -2.0, "z": 0.0},
                "size": {"x": 4.0, "y": 4.0, "z": 20.0},
            },
            "attached_tip_radius_mm": 2.0,
        },
    }
    if camera:
        instruments["camera"] = _Camera()
        instrument_configs["camera"] = {"type": "camera", "vendor": "fake"}
        envelopes["camera"] = {
            "box": {
                "offset": {"x": -2.0, "y": -2.0, "z": 0.0},
                "size": {"x": 4.0, "y": 4.0, "z": 20.0},
            },
        }
    config = GantryConfig(
        serial_port="offline",
        gantry_type=GantryType.CUB,
        factory_z_travel_mm=100,
        working_volume=WorkingVolume(0, 120, 0, 100, 0, 100),
        safe_z=100,
        instruments=instrument_configs,
        motion_envelopes=envelopes,
    )
    gantry = InstrumentedGantry(
        controller, instruments, safe_z=100, motion_envelopes=config.motion_envelopes,
    )
    return ProtocolContext(gantry=gantry, deck=deck, gantry_config=config), controller, pipette


def _engage_protocol(*, next_position: str = "plate.A2", clearance: Any = ...):
    first = {"position": "plate.A1", "volume_ul": 25.0}
    second = {"position": next_position, "volume_ul": 25.0}
    if clearance is not ...:
        first["travel_clearance"] = clearance
        second["travel_clearance"] = clearance
    return compile_protocol([
        CommandCall("aspirate", first),
        CommandCall("dispense", second),
    ])


def _local_transit(plan) -> tuple[Any, ...]:
    return tuple(
        segment for segment in plan.segments
        if segment.axis in {"x", "xy"}
        and segment.start.z < 99.0
        and segment.access.allowed_fixture_names == ()
    )


@pytest.mark.parametrize(
    ("clearance", "minimum_height"),
    [(..., 43.0), (8.0, 48.0), (0.0, 41.0)],
)
def test_same_plate_well_change_uses_requested_clearance_and_executes_preview(
    clearance: Any, minimum_height: float,
) -> None:
    context, controller, _pipette = _plate()
    protocol = _engage_protocol(clearance=clearance)

    protocol.execute(context)

    second_plan = context.planned_motion_steps[1].plans[0]
    transit = _local_transit(second_plan)
    assert transit
    transit_z = transit[0].start.z
    assert transit[0].end.z == transit_z
    assert transit_z == pytest.approx(minimum_height)
    assert any(segment.axis == "z" for segment in second_plan.segments)
    assert all(
        segment.access.allowed_tool_names == ("pipette",)
        for segment in second_plan.segments
    )
    assert controller.moves == [
        (segment.end.x, segment.end.y, segment.end.z, None)
        for plan in context.motion_plans for segment in plan.segments
    ]


def test_explicit_null_retains_ceiling_retraction() -> None:
    context, _controller, _pipette = _plate()
    protocol = _engage_protocol(clearance=None)

    protocol.execute(context)

    plan = context.planned_motion_steps[1].plans[0]
    assert not _local_transit(plan)
    assert any(segment.end.z == context.gantry_config.working_volume.z_max for segment in plan.segments)


def test_same_well_engage_is_stationary_and_does_not_send_motion() -> None:
    context, controller, pipette = _plate()
    protocol = _engage_protocol(next_position="plate.A1")

    protocol.execute(context)

    assert not context.planned_motion_steps[1].plans[0].segments
    assert controller.moves == [
        (segment.end.x, segment.end.y, segment.end.z, None)
        for segment in context.planned_motion_steps[0].plans[0].segments
    ]
    assert [name for name, _args in pipette.actions] == ["aspirate", "dispense"]


@pytest.mark.parametrize("mutation", ["tip_state", "pose", "readback"])
def test_stationary_plan_rejects_stale_state_before_liquid_action(mutation: str) -> None:
    context, controller, pipette = _plate()
    protocol = _engage_protocol(next_position="plate.A1")
    prepare_planning_context(protocol, context)
    stationary_plan = context.planned_motion_steps[1].plans[0]
    assert not stationary_plan.segments
    controller.coords = stationary_plan.start.to_dict()
    if mutation == "tip_state":
        pipette.attached_tip_extension = 19.0
    elif mutation == "pose":
        controller.coords["x"] += 0.1
    else:
        readback_error = MillConnectionError("readback lost")
        def fail_readback():
            raise readback_error
        controller.get_coordinates = fail_readback

    if mutation == "readback":
        with pytest.raises(MillConnectionError) as raised:
            context.routing_session.execute(stationary_plan)
        assert raised.value is readback_error
    else:
        with pytest.raises(ProtocolExecutionError):
            context.routing_session.execute(stationary_plan)

    assert controller.moves == []
    assert pipette.actions == []


def test_local_route_falls_back_when_an_obstacle_blocks_its_transit() -> None:
    context, _controller, _pipette = _plate(wall=True)
    protocol = _engage_protocol()

    protocol.execute(context)

    plan = context.planned_motion_steps[1].plans[0]
    assert not _local_transit(plan)
    assert any(segment.end.z == context.gantry_config.working_volume.z_max for segment in plan.segments)


def test_inactive_camera_envelope_does_not_change_pipette_local_route() -> None:
    context, _controller, _pipette = _plate(camera=True)
    protocol = _engage_protocol()

    protocol.execute(context)

    plan = context.planned_motion_steps[1].plans[0]
    assert _local_transit(plan)
    assert all(segment.access.allowed_tool_names == ("pipette",) for segment in plan.segments)


def test_change_to_another_fixture_uses_full_retraction() -> None:
    context, _controller, _pipette = _plate(second_plate=True)
    protocol = compile_protocol([
        CommandCall("aspirate", {"position": "plate.A1", "volume_ul": 25.0}),
        CommandCall("dispense", {"position": "other_plate.A1", "volume_ul": 25.0}),
    ])

    protocol.execute(context)

    plan = context.planned_motion_steps[1].plans[0]
    assert not _local_transit(plan)
    assert any(segment.end.z == context.gantry_config.working_volume.z_max for segment in plan.segments)


def test_change_from_another_instrument_uses_full_retraction() -> None:
    from cubos.protocol_engine.routing import RoutingSession

    context, _controller, _pipette = _plate(camera=True)
    session = RoutingSession(context)
    session.preview_protocol(compile_protocol([]))
    plan, _end = session._plan_engage(
        Point3D(60.0, 50.0, 43.0),
        "plate.A2",
        0.0,
        "pipette",
        ToolState("pipette", 20.0),
        command="aspirate",
        operation="aspirate",
        previous_target="plate",
        previous_instrument="camera",
        travel_clearance=3.0,
    )

    assert not _local_transit(plan)
    assert any(segment.end.z == context.gantry_config.working_volume.z_max for segment in plan.segments)


def test_out_of_bounds_well_rejects_before_any_command_executes() -> None:
    context, controller, pipette = _plate()
    coordinate_type = type(context.deck["plate"].wells["A2"])
    context.deck["plate"].wells["A2"] = coordinate_type(x=80.0, y=50.0, z=110.0)
    protocol = compile_protocol([
        CommandCall("aspirate", {"position": "plate.A1", "volume_ul": 25.0}),
        CommandCall("dispense", {"position": "plate.A2", "volume_ul": 25.0}),
    ])

    with pytest.raises(ProtocolExecutionError, match="preflight failed"):
        protocol.execute(context)

    assert controller.moves == []
    assert pipette.actions == []


def test_multistroke_transfer_and_repeated_mix_reuse_local_plate_routes() -> None:
    context, _controller, pipette = _plate()
    pipette.config = PipetteConfig(
        name="test-50",
        family=PipetteFamily.OT2,
        channels=1,
        max_volume=50.0,
        min_volume=1.0,
    )
    protocol = compile_protocol([
        CommandCall("transfer", {
            "source": "plate.A1",
            "destination": "plate.A2",
            "volume_ul": 100.0,
        }),
        CommandCall("mix", {
            "position": "plate.A1",
            "volume_ul": 10.0,
            "cycles": 2,
        }),
    ])
    prepare_planning_context(protocol, context)

    transfer_plans = context.planned_motion_steps[0].plans
    assert len(transfer_plans) == 4
    assert all(_local_transit(plan) for plan in transfer_plans[1:])
    mix_plans = context.planned_motion_steps[1].plans
    assert len(mix_plans) == 5
    assert _local_transit(mix_plans[0])
    assert all(
        segment.access.allowed_fixture_names == ("plate",)
        for plan in mix_plans[1:] for segment in plan.segments
    )


@pytest.mark.parametrize("height", [-10.0, 5.0])
def test_same_well_changes_depth_with_one_vertical_segment(height):
    context, controller, _pipette = _plate()
    protocol = compile_protocol([
        CommandCall("dispense", {"position": "plate.A1", "volume_ul": 25}),
        CommandCall("mix", {
            "position": "plate.A1", "volume_ul": 10, "cycles": 1,
            "height": height,
        }),
    ])
    protocol.execute(context)
    plan = context.planned_motion_steps[1].plans[0]
    assert len(plan.segments) == 1
    assert plan.segments[0].axis == "z"
    assert plan.length_mm == abs(height)
    assert plan.end.z == 40 + height
    assert controller.moves == [
        (s.end.x, s.end.y, s.end.z, None)
        for p in context.motion_plans for s in p.segments
    ]


def test_attached_tip_length_is_included_in_local_carriage_height():
    context, _controller, pipette = _plate()
    pipette.attached_tip_extension = 30
    _engage_protocol().execute(context)
    plan = context.planned_motion_steps[1].plans[0]
    assert {s.start.z for s in _local_transit(plan)} == {53.0}


def test_lower_inactive_tool_raises_local_carriage_clearance():
    context, _controller, _pipette = _plate(camera=True)
    camera = context.gantry.instruments["camera"]
    camera.depth = 15
    camera.offset_y = -40
    _engage_protocol().execute(context)
    plan = context.planned_motion_steps[1].plans[0]
    assert {s.start.z for s in _local_transit(plan)} == {58.0}


def test_registered_plate_top_controls_clearance_above_reference_z():
    context, _controller, _pipette = _plate()
    context.deck["plate"].motion["resolved_box"]["max"]["z"] = 45
    _engage_protocol().execute(context)
    plan = context.planned_motion_steps[1].plans[0]
    assert {s.start.z for s in _local_transit(plan)} == {48.0}


def test_unreachable_requested_clearance_falls_back_to_ceiling():
    context, _controller, _pipette = _plate()
    _engage_protocol(clearance=100).execute(context)
    plan = context.planned_motion_steps[1].plans[0]
    assert not _local_transit(plan)
    assert max(s.end.z for s in plan.segments) == 100
