from __future__ import annotations

from unittest.mock import Mock

import pytest

from cubos.protocol_engine.compiler import CommandCall, compile_protocol
from cubos.protocol_engine.errors import ProtocolExecutionError
from cubos.protocol_engine.routing import prepare_planning_context

from test_protocol_routing import _context


def _mix_protocol(blowout_height: float = 0.0):
    return compile_protocol([
        CommandCall("pick_up_tip", {"position": "tips.A1"}),
        CommandCall("mix", {
            "position": "destination",
            "volume_ul": 50.0,
            "cycles": 2,
            "height": -10.0,
            "blowout_height": blowout_height,
        }),
        CommandCall("drop_tip", {"position": "waste"}),
    ])


@pytest.mark.parametrize("blowout_height", [0.0, 3.0])
def test_routed_mix_preflights_and_executes_vertical_blowout(blowout_height):
    context, controller, pipette = _context()
    events = []
    blowout_poses = []
    move_to = controller.move_to

    def record_move(x, y, z, travel_z=None):
        events.append(("move", x, y, z))
        move_to(x, y, z, travel_z)

    controller.move_to = record_move
    for action in ("pick_up_tip", "aspirate", "dispense", "blowout", "drop_tip"):
        original = getattr(pipette, action)

        def record_action(*args, _action=action, _original=original, **kwargs):
            events.append((_action,))
            if _action == "blowout":
                blowout_poses.append(controller.get_coordinates())
            return _original(*args, **kwargs)

        setattr(pipette, action, record_action)

    protocol = _mix_protocol(blowout_height)
    prepare_planning_context(protocol, context)
    mix_step = context.planned_motion_steps[1]
    endpoint = mix_step.plans[-1].end

    assert (endpoint.x, endpoint.y, endpoint.z) == (80.0, 60.0, 40.0 + blowout_height)
    finish_plan = mix_step.plans[-1]
    assert len(finish_plan.segments) == 1
    assert finish_plan.segments[0].axis == "z"
    assert finish_plan.start.x == endpoint.x
    assert finish_plan.start.y == endpoint.y
    assert finish_plan.start.z == 30.0

    protocol.execute(context)

    assert controller.moves == [
        (segment.end.x, segment.end.y, segment.end.z, None)
        for plan in context.motion_plans
        for segment in plan.segments
    ]
    blowout_index = events.index(("blowout",))
    assert blowout_index < events.index(("drop_tip",))
    assert blowout_poses == [{"x": 80.0, "y": 60.0, "z": 40.0 + blowout_height}]
    assert pipette.actions[-2:] == ["blowout", "drop_tip"]
    assert events[blowout_index - 1] == ("move", endpoint.x, endpoint.y, endpoint.z)


@pytest.mark.parametrize("blowout_height", [float("nan"), float("inf"), 100.0])
def test_invalid_mix_blowout_height_rejects_before_any_motion(blowout_height):
    context, controller, pipette = _context()

    with pytest.raises(ProtocolExecutionError, match="preflight failed"):
        _mix_protocol(blowout_height).execute(context)

    assert controller.moves == []
    assert pipette.actions == []


def test_mix_with_finish_keeps_collision_preflight():
    context, controller, pipette = _context(blocker=True)

    with pytest.raises(ProtocolExecutionError, match="preflight failed"):
        _mix_protocol(3.0).execute(context)

    assert controller.moves == []
    assert pipette.actions == []


@pytest.mark.parametrize("failure_point", ["finish_move", "blowout"])
def test_tracked_mix_finish_failure_requires_reconciliation_and_stops_protocol(failure_point):
    context, controller, pipette = _context()
    context.fluid_state_id = 11
    context.campaign_id = 7
    store = context.data_store = Mock()
    store.get_tip_snapshot.return_value = {"containers": [
        {"rack_key": "tips", "slot_id": "A1", "status": "available"},
    ]}
    store.begin_pick_up_tip.return_value = (True, "A1", 20.0)
    store.begin_fluid_mix.return_value = True

    if failure_point == "finish_move":
        move_to = controller.move_to

        def fail_finish_move(x, y, z, travel_z=None):
            if (x, y, z) == (80.0, 60.0, 43.0):
                raise RuntimeError("finish movement failed")
            move_to(x, y, z, travel_z)

        controller.move_to = fail_finish_move
    else:
        pipette.blowout = Mock(side_effect=RuntimeError("blowout failed"))

    with pytest.raises(RuntimeError, match="failed"):
        _mix_protocol(3.0).execute(context)

    store.mark_fluid_reconciliation_required.assert_called_once()
    store.complete_fluid_mix.assert_not_called()
    store.begin_drop_tip.assert_not_called()
    assert "drop_tip" not in pipette.actions
