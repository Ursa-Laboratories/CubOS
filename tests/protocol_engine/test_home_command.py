"""Tests for protocol home command work-coordinate behavior."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from gantry.gantry_config import (
    GantryConfig,
    GantryType,
    HomingStrategy,
    WorkingVolume,
)
from protocol_engine.commands.home import home


def _context(gantry_config: GantryConfig | None):
    gantry = MagicMock()
    return SimpleNamespace(
        board=SimpleNamespace(gantry=gantry),
        gantry=gantry_config,
        logger=MagicMock(),
    ), gantry


def test_home_preserves_calibrated_wpos_for_deck_origin_config():
    config = GantryConfig(
        serial_port="/dev/ttyUSB0",
        gantry_type=GantryType.CUB_XL,
        homing_strategy=HomingStrategy.STANDARD,
        total_z_range=100.0,
        working_volume=WorkingVolume(
            x_min=0.0,
            x_max=400.0,
            y_min=0.0,
            y_max=300.0,
            z_min=0.0,
            z_max=100.0,
        ),
    )
    context, gantry = _context(config)

    home(context)

    gantry.home.assert_called_once_with()
    gantry.clear_g92_offsets.assert_not_called()
    gantry.set_work_coordinates.assert_not_called()
    assert gantry.set_serial_timeout.call_args_list[0].args == (10,)
    assert gantry.set_serial_timeout.call_args_list[-1].args == (0.05,)


def test_home_preserves_calibrated_wpos_for_one_instrument_nonzero_z_min():
    config = GantryConfig(
        serial_port="/dev/ttyUSB0",
        gantry_type=GantryType.CUB_XL,
        homing_strategy=HomingStrategy.STANDARD,
        total_z_range=105.0,
        working_volume=WorkingVolume(
            x_min=0.0,
            x_max=400.0,
            y_min=0.0,
            y_max=300.0,
            z_min=5.0,
            z_max=105.0,
        ),
    )
    context, gantry = _context(config)

    home(context)

    gantry.home.assert_called_once_with()
    gantry.clear_g92_offsets.assert_not_called()
    gantry.set_work_coordinates.assert_not_called()


def test_home_preserves_calibrated_wpos_for_negative_space_config():
    config = GantryConfig(
        serial_port="/dev/ttyUSB0",
        gantry_type=GantryType.CUB_XL,
        homing_strategy=HomingStrategy.STANDARD,
        total_z_range=100.0,
        working_volume=WorkingVolume(
            x_min=-400.0,
            x_max=-0.01,
            y_min=-300.0,
            y_max=-0.01,
            z_min=0.0,
            z_max=100.0,
        ),
    )
    context, gantry = _context(config)

    home(context)

    gantry.home.assert_called_once_with()
    gantry.clear_g92_offsets.assert_not_called()
    gantry.set_work_coordinates.assert_not_called()


def test_home_preserves_calibrated_wpos_for_zero_minimum_config():
    config = GantryConfig(
        serial_port="/dev/ttyUSB0",
        gantry_type=GantryType.CUB_XL,
        homing_strategy=HomingStrategy.STANDARD,
        total_z_range=100.0,
        working_volume=WorkingVolume(
            x_min=0.0,
            x_max=400.0,
            y_min=0.0,
            y_max=300.0,
            z_min=0.0,
            z_max=100.0,
        ),
    )
    context, gantry = _context(config)

    home(context)

    gantry.home.assert_called_once_with()
    gantry.clear_g92_offsets.assert_not_called()
    gantry.set_work_coordinates.assert_not_called()


def test_home_preserves_calibrated_wpos_without_config():
    context, gantry = _context(None)

    home(context)

    gantry.home.assert_called_once_with()
    gantry.clear_g92_offsets.assert_not_called()
    gantry.set_work_coordinates.assert_not_called()
