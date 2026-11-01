"""Verify routed segments reach GRBL without changing legacy axis order."""
from unittest.mock import Mock

import pytest

from cubos.gantry.coordinates import Coordinates
from cubos.gantry.errors import MillConnectionError
from cubos.gantry.gantry import Gantry
from cubos.gantry.gantry_driver.driver import Mill
from cubos.gantry.instrument_mount import InstrumentedGantry
from cubos.motion_planning import Point3D


def _mill():
    mill = Mill.__new__(Mill)
    mill.default_feed_rate = 1234
    mill.execute_command = Mock()
    return mill


def test_exact_diagonal_reaches_driver_as_one_command():
    mill = _mill()
    mill.current_coordinates = Mock(return_value=Coordinates(x=1, y=2, z=30))
    gantry = Gantry(offline=True)
    gantry._offline = False
    gantry._mill = mill
    board = InstrumentedGantry(gantry)
    board.move_carriage_exact(Point3D(1, 2, 30), Point3D(10, 20, 30))
    mill.execute_command.assert_called_once_with("G01 X10.0 Y20.0 Z30.0 F1234")


def test_legacy_xy_still_uses_separate_axes():
    mill = _mill()
    assert mill._build_direct_move(Coordinates(x=1, y=2, z=30), Coordinates(x=10, y=20, z=30)) == [
        "G01 X10.0 F1234", "G01 Y20.0 F1234",
    ]


@pytest.mark.parametrize("bad", [float('nan'), float('inf')])
def test_exact_driver_rejects_nonfinite_before_command(bad):
    mill = _mill()
    with pytest.raises(ValueError, match="finite"):
        mill.move_linear_to(bad, 20, 30)
    mill.execute_command.assert_not_called()


def test_exact_gantry_propagates_connection_loss():
    gantry = Gantry(offline=True)
    gantry._offline = False
    gantry._mill = _mill()
    error = MillConnectionError('lost')
    gantry._mill.execute_command.side_effect = error
    with pytest.raises(MillConnectionError) as caught:
        gantry.move_linear_to(10, 20, 30)
    assert caught.value is error


def test_exact_gantry_offline_updates_pose():
    gantry = Gantry(offline=True)
    gantry.move_linear_to(10, 20, 30)
    assert gantry.get_coordinates() == {"x": 10, "y": 20, "z": 30}


def test_exact_segment_propagates_readback_connection_loss_before_motion():
    controller = Mock()
    error = MillConnectionError('readback lost')
    controller.get_coordinates.side_effect = error
    board = InstrumentedGantry(controller)
    with pytest.raises(MillConnectionError) as caught:
        board.move_carriage_exact(Point3D(1, 2, 30), Point3D(10, 20, 30))
    assert caught.value is error
    controller.move_linear_to.assert_not_called()
