from unittest.mock import MagicMock

import pytest
from cubos.gantry.instrument_mount import InstrumentedGantry
from cubos.instruments.pipette.vendors.opentrons import OpentronsPipette


@pytest.mark.parametrize("method", ["move", "move_to_labware", "move_carriage_exact"])
@pytest.mark.parametrize("by_key", [True, False])
def test_recorded_pose_identifies_registered_instance(method, by_key):
    controller = MagicMock()
    controller.get_coordinates.return_value = {"x": 0.0, "y": 0.0, "z": 0.0}
    first = OpentronsPipette(offline=True)
    second = OpentronsPipette(offline=True, offset_x=12, depth=5)
    assert first.name == second.name
    gantry = InstrumentedGantry(
        controller, {"first": first, "second": second}, safe_z=50,
    )
    instrument = "second" if by_key else second
    if method == "move_carriage_exact":
        gantry.move_carriage_exact((0, 0, 0), (0, 0, 10), instrument=instrument)
    else:
        getattr(gantry, method)(instrument, (12, 0, 10))
    pose = gantry.last_commanded_pose
    assert pose["instrument"] == "second"
    x, y, _z = pose["instrument_position"]
    gantry.move(pose["instrument"], (x, y, 50), travel_z=50)
    controller.move_to.assert_called_with(0, 0, 55, travel_z=55)


def test_unregistered_instance_retains_display_name_in_pose():
    controller = MagicMock()
    instrument = OpentronsPipette(offline=True, name="standalone")
    gantry = InstrumentedGantry(controller, safe_z=50)
    gantry.move(instrument, (0, 0, 10))
    assert gantry.last_commanded_pose["instrument"] == "standalone"
