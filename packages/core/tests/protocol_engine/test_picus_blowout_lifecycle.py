"""Piston reset ordering with a real Picus driver and simulated gantry."""

from unittest.mock import MagicMock

import pytest

from cubos.deck.deck import Deck
from cubos.deck.labware.labware import Coordinate3D
from cubos.deck.labware.vial import Vial
from cubos.deck.labware.well_plate import WellPlate
from cubos.gantry.instrument_mount import InstrumentedGantry
from cubos.instruments.pipette.exceptions import PipetteCommandError
from cubos.instruments.pipette.vendors.opentrons import OpentronsPipette
from cubos.instruments.pipette.vendors.sartorius import SartoriusPicus2Pipette
from cubos.protocol_engine.commands.pipette import (
    blowout,
    flush_pipette,
    serial_transfer,
    transfer,
)
from cubos.protocol_engine.errors import ProtocolExecutionError
from cubos.protocol_engine.runtime import ProtocolContext


class RecordingController:
    def __init__(self, events, fail=None):
        self.config = {"working_volume": {"z_min": 0, "z_max": 120}}
        self.position = {"x": 0.0, "y": 0.0, "z": 120.0}
        self.events = events
        self.fail = fail

    def get_coordinates(self):
        return dict(self.position)

    def move_to(self, x, y, z, travel_z=None):
        after_blowout = self.events and self.events[-1][0] == "pipette" and (
            self.events[-1][1].startswith("BLOW_OUT")
        )
        self.events.append(("move", x, y, z, travel_z))
        if after_blowout and self.fail == "retract":
            raise RuntimeError("retract failed")
        self.position = {"x": x, "y": y, "z": z}


def _rig(*, safe_z=70.0, blowout_go_home=False, fail=None):
    events = []
    pipette = SartoriusPicus2Pipette(
        name="pipette", depth=10.0, blowout_go_home=blowout_go_home,
    )
    pipette.set_attached_tip_extension(20.0)
    pipette._initialized = True

    def send(command, **kwargs):
        events.append(("pipette", command))
        if fail == "home" and command == "HOME":
            raise PipetteCommandError("home failed")
        if fail == "blowout" and command.startswith("BLOW_OUT"):
            raise PipetteCommandError("blowout failed")

    pipette._send = send
    controller = RecordingController(events, fail)
    gantry = InstrumentedGantry(controller, {"pipette": pipette}, safe_z=safe_z)
    deck = Deck({
        "source": Vial(
            name="source", location=Coordinate3D(x=10, y=20, z=20),
            capacity_ul=5000, working_volume_ul=4000,
        ),
        "destination": Vial(
            name="destination", location=Coordinate3D(x=40, y=50, z=20),
            capacity_ul=5000, working_volume_ul=4000,
        ),
        "plate": WellPlate(
            name="plate", model_name="test", rows=1, columns=2,
            length=100, width=50, height=20,
            capacity_ul=200, working_volume_ul=150,
            wells={
                "A1": Coordinate3D(x=80, y=60, z=20),
                "A2": Coordinate3D(x=90, y=60, z=20),
            },
        ),
    })
    return ProtocolContext(gantry=gantry, deck=deck), pipette, events


def _blowout_indices(events):
    return [
        index for index, event in enumerate(events)
        if event[0] == "pipette" and event[1].startswith("BLOW_OUT")
    ]


def test_standalone_blowout_lifts_same_xy_before_homing():
    context, pipette, events = _rig()
    pipette._loaded_volume_ul = 50.0

    blowout(
        context, "destination", height=-5.0,
        x_offset_mm=3.0, y_offset_mm=-4.0,
    )

    index, = _blowout_indices(events)
    assert events[index:] == [
        ("pipette", "BLOW_OUT 0 5 3000"),
        ("move", 43.0, 46.0, 100.0, None),
        ("pipette", "HOME"),
    ]
    assert pipette.loaded_volume_ul == 0.0


@pytest.mark.parametrize("volume_ul, strokes", [(50.0, 1), (2500.0, 3)])
def test_transfer_resets_only_after_final_stroke(volume_ul, strokes):
    context, _, events = _rig()

    transfer(
        context, "source", "destination", volume_ul,
        source_height=-5.0, destination_height=-5.0,
    )

    aspirates = [event for event in events if event[0] == "pipette" and (
        event[1].startswith("RUN_ASPIRATE")
    )]
    assert len(aspirates) == strokes
    index, = _blowout_indices(events)
    assert events[index:] == [
        ("pipette", "BLOW_OUT 0 5 3000"),
        ("move", 40.0, 50.0, 100.0, None),
        ("pipette", "HOME"),
    ]


@pytest.mark.parametrize("command", ["serial", "flush"])
def test_composed_transfers_reset_before_next_aspiration(command):
    context, _, events = _rig()
    if command == "serial":
        serial_transfer(context, "source", "plate", "A", volumes=[50.0, 50.0])
    else:
        flush_pipette(
            context, 50.0, cycles=2, source="source", waste="destination",
        )

    indices = _blowout_indices(events)
    assert len(indices) == 2
    for index in indices:
        assert events[index + 1][0] == "move"
        assert events[index + 1][3:] == (100.0, None)
        assert events[index + 2] == ("pipette", "HOME")
    assert any(event[0] == "pipette" and event[1].startswith("RUN_ASPIRATE")
               for event in events[indices[0] + 3:indices[1]])


@pytest.mark.parametrize("safe_z", [None, float("nan"), float("inf"), 20.0, 15.0])
@pytest.mark.parametrize("command", ["blowout", "transfer"])
def test_missing_or_insufficient_clearance_fails_before_motion(safe_z, command):
    context, _, events = _rig(safe_z=safe_z)
    with pytest.raises(ProtocolExecutionError, match="clearance|safe_z"):
        if command == "blowout":
            blowout(context, "destination", height=-5.0)
        else:
            transfer(context, "source", "destination", 50.0)
    assert events == []


def test_clearance_must_also_be_above_positive_action_height():
    context, _, events = _rig(safe_z=70.0)
    with pytest.raises(ProtocolExecutionError, match="action height"):
        blowout(context, "destination", height=50.0)
    assert events == []


@pytest.mark.parametrize("failure", ["blowout", "retract", "home"])
def test_transfer_reset_failure_requires_reconciliation(failure):
    context, _, events = _rig(fail=failure)
    context.campaign_id = 7
    context.fluid_state_id = 11
    context.data_store = MagicMock()
    context.data_store.begin_fluid_transfer.return_value = True

    with pytest.raises((RuntimeError, PipetteCommandError), match=failure):
        transfer(context, "source", "destination", 50.0)

    context.data_store.complete_fluid_transfer.assert_not_called()
    context.data_store.mark_fluid_reconciliation_required.assert_called_once()
    if failure != "home":
        assert ("pipette", "HOME") not in events


def test_transfer_commits_only_after_successful_home():
    context, _, events = _rig()
    context.campaign_id = 7
    context.fluid_state_id = 11
    context.data_store = MagicMock()
    context.data_store.begin_fluid_transfer.return_value = True
    context.data_store.complete_fluid_transfer.side_effect = (
        lambda key: events.append(("commit", key))
    )

    transfer(context, "source", "destination", 50.0)

    assert events[-2] == ("pipette", "HOME")
    assert events[-1][0] == "commit"


def test_explicit_automatic_home_preserves_legacy_sequence():
    context, _, events = _rig(blowout_go_home=True)
    blowout(context, "destination", height=-5.0)
    index, = _blowout_indices(events)
    assert events[index:] == [("pipette", "BLOW_OUT 1 5 3000")]


def test_other_pipette_vendors_keep_their_blowout_sequence():
    context, _, events = _rig()
    pipette = OpentronsPipette(name="pipette", offline=True)
    pipette.blowout = lambda speed: events.append(("blowout", speed))
    pipette.home = lambda: pytest.fail("Opentrons must not receive extra home")
    context.gantry.instruments["pipette"] = pipette

    blowout(context, "destination", height=-5.0)

    assert pipette.requires_home_after_blowout is False
    assert events[-1] == ("blowout", 50.0)


def test_picuses_still_refuse_home_while_holding_liquid():
    _, pipette, events = _rig()
    pipette._loaded_volume_ul = 10.0
    with pytest.raises(PipetteCommandError, match="still holds"):
        pipette.home()
    assert events == []
