"""Tests for Gantry mixed-axis coordinate behavior."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from gantry.gantry import Gantry


def _config() -> dict:
    return {
        "cnc": {"homing_strategy": "standard", "total_z_range": 90.0},
        "working_volume": {
            "x_min": 0.0,
            "x_max": 300.0,
            "y_min": 0.0,
            "y_max": 200.0,
            "z_min": 0.0,
            "z_max": 80.0,
        },
    }


@patch("gantry.gantry.Mill")
def test_move_to_preserves_xyz_without_hidden_z_flip(mock_mill_cls) -> None:
    gantry = Gantry(config=_config())
    gantry.move_to(150.0, 100.0, 40.0)
    mock_mill_cls.return_value.move_to_position.assert_called_once_with(
        x_coordinate=150.0,
        y_coordinate=100.0,
        z_coordinate=40.0,
        travel_z=None,
    )


@patch("gantry.gantry.Mill")
def test_get_coordinates_preserves_xyz_without_hidden_z_flip(mock_mill_cls) -> None:
    mock_mill_cls.return_value.current_coordinates.return_value = SimpleNamespace(
        x=150.0,
        y=100.0,
        z=-40.0,
    )
    gantry = Gantry(config=_config())
    coords = gantry.get_coordinates()
    assert coords == {"x": 150.0, "y": 100.0, "z": -40.0}


@patch("gantry.gantry.Mill")
def test_get_status_preserves_visible_z_without_hidden_flip(mock_mill_cls) -> None:
    mock_mill_cls.return_value.current_status.return_value = (
        "<Idle|MPos:150.000,100.000,-40.000|Bf:15,127|FS:0,0>"
    )
    gantry = Gantry(config=_config())
    status = gantry.get_status()
    assert status == "<Idle|MPos:150.000,100.000,-40.000|Bf:15,127|FS:0,0>"


@patch("gantry.gantry.Mill")
def test_zero_home_coordinates_stay_zero(mock_mill_cls) -> None:
    mock_mill_cls.return_value.current_coordinates.return_value = SimpleNamespace(
        x=0.0,
        y=0.0,
        z=0.0,
    )
    gantry = Gantry(config=_config())
    assert gantry.get_coordinates() == {"x": 0.0, "y": 0.0, "z": 0.0}


@patch("gantry.gantry.Mill")
def test_boundary_translation(mock_mill_cls) -> None:
    gantry = Gantry(config=_config())
    gantry.move_to(300.0, 200.0, 80.0)
    mock_mill_cls.return_value.move_to_position.assert_called_once_with(
        x_coordinate=300.0,
        y_coordinate=200.0,
        z_coordinate=80.0,
        travel_z=None,
    )


@patch("gantry.gantry.Mill")
def test_travel_z_translates_to_machine_space(mock_mill_cls) -> None:
    """travel_z is given in deck-frame space; mill receives the same Z."""
    gantry = Gantry(config=_config())
    gantry.move_to(150.0, 100.0, 40.0, travel_z=70.0)
    mock_mill_cls.return_value.move_to_position.assert_called_once_with(
        x_coordinate=150.0,
        y_coordinate=100.0,
        z_coordinate=40.0,
        travel_z=70.0,
    )


@patch("gantry.gantry.Mill")
def test_jog_preserves_xyz_without_hidden_z_flip(mock_mill_cls) -> None:
    gantry = Gantry(config=_config())
    gantry.jog(x=5.0, y=3.0, z=1.0)
    mock_mill_cls.return_value.jog.assert_called_once_with(
        x=5.0, y=3.0, z=1.0, feed_rate=2000,
    )


@patch("gantry.gantry.Mill")
def test_jog_cancel_delegates_to_mill(mock_mill_cls) -> None:
    gantry = Gantry(config=_config())
    gantry.jog_cancel()
    mock_mill_cls.return_value.jog_cancel.assert_called_once()


@patch("gantry.gantry.Mill")
def test_unlock_delegates_to_mill_reset(mock_mill_cls) -> None:
    gantry = Gantry(config=_config())
    gantry.unlock()
    mock_mill_cls.return_value.reset.assert_called_once()


def test_total_z_range_property_from_config() -> None:
    gantry = Gantry(config=_config())
    assert gantry.total_z_range == 90.0
