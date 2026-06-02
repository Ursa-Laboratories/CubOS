"""Deck-origin coordinate contract tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from gantry.instrument_mount import InstrumentedGantry
from gantry.gantry import Gantry


@patch("gantry.gantry.Mill")
def test_gantry_move_to_sends_deck_origin_z_without_sign_flip(mock_mill_cls):
    gantry = Gantry(config={})

    gantry.move_to(10.0, 20.0, -5.0)

    mock_mill_cls.return_value.move_to.assert_called_once_with(
        x_coordinate=10.0,
        y_coordinate=20.0,
        z_coordinate=-5.0,
        travel_z=None,
    )


def test_board_move_to_labware_uses_safe_z_above_deck():
    instr = MagicMock()
    instr.name = "probe"
    instr.offset_x = 0.0
    instr.offset_y = 0.0
    instr.depth = 0.0
    instr.effective_depth = 0.0
    gantry = MagicMock()
    instrumented_gantry = InstrumentedGantry(controller=gantry, instruments={"probe": instr}, safe_z=20.0)
    labware = MagicMock()
    labware.x = 1.0
    labware.y = 2.0
    labware.z = 0.0

    instrumented_gantry.move_to_labware("probe", labware)

    gantry.move_to.assert_called_once_with(1.0, 2.0, 20.0, travel_z=20.0)
