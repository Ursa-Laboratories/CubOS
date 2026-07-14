"""Cross-command movement contracts under the labware-relative model.

These are smoke-level guards that the move/measure/scan/pipette commands
agree on the same motion primitives:

* ``InstrumentedGantry.move_to_labware`` travels XY at the gantry's ``safe_z``
  (absolute deck-frame).
* Engaging commands take ``measurement_height`` as a first-class command
  argument and descend to ``well.z + measurement_height`` (where
  ``well.z`` is the calibrated deck-frame surface Z carried on the
  resolved coordinate). Pipette commands default to the labware reference
  Z and can take command-specific labware-relative height arguments.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

from cubos.gantry.instrument_mount import InstrumentedGantry
from cubos.deck.labware.labware import Coordinate3D
from cubos.deck.labware.well_plate import WellPlate
from cubos.protocol_engine.runtime import ProtocolContext


# Calibrated deck-frame surface Z (the well coordinate's z). This is the
# value motion code reads via the resolved coordinate; ``WellPlate.height``
# is a separate physical-dimension field that doesn't drive Z.
WELL_Z = 14.10
PLATE_HEIGHT = 14.35  # outer dimension only — not used in motion math.


def _instrument(name: str = "tool"):
    return SimpleNamespace(
        name=name,
        offset_x=0.0,
        offset_y=0.0,
        depth=0.0,
        effective_depth=0.0,
    )


def _plate() -> WellPlate:
    return WellPlate(
        name="plate_1",
        model_name="test_plate",
        length=127.71,
        width=85.43,
        height=PLATE_HEIGHT,
        rows=1,
        columns=2,
        wells={
            "A1": Coordinate3D(x=10.0, y=20.0, z=WELL_Z),
            "A2": Coordinate3D(x=19.0, y=20.0, z=WELL_Z),
        },
        capacity_ul=200.0,
        working_volume_ul=150.0,
    )


def _ctx(instr_name: str, instr, plate=None):
    plate = plate or _plate()
    instrumented_gantry = MagicMock()
    instrumented_gantry.instruments = {instr_name: instr}
    deck = MagicMock()
    deck.__getitem__ = MagicMock(return_value=plate or _plate())
    deck.resolve_coordinate = MagicMock(return_value=Coordinate3D(x=10.0, y=20.0, z=WELL_Z))
    deck.resolve_labware = MagicMock(return_value=plate or _plate())
    return ProtocolContext(gantry=instrumented_gantry, deck=deck, logger=logging.getLogger("test"))


def test_board_move_to_labware_uses_absolute_safe_z():
    gantry = MagicMock()
    instr = _instrument()
    instrumented_gantry = InstrumentedGantry(controller=gantry, instruments={"tool": instr}, safe_z=20.0)

    instrumented_gantry.move_to_labware("tool", Coordinate3D(x=10.0, y=20.0, z=WELL_Z))

    gantry.move_to.assert_called_once_with(10.0, 20.0, 20.0, travel_z=20.0)


def test_measure_descends_to_well_z_plus_relative_offset():
    from cubos.protocol_engine.commands.measure import measure

    instr = _instrument(name="uvvis")
    instr.measure = MagicMock(return_value="ok")
    ctx = _ctx("uvvis", instr)

    measure(ctx, instrument="uvvis", position="plate_1.A1", measurement_height=2.0)

    ctx.gantry.move_to_labware.assert_called_once()
    ctx.gantry.move.assert_called_once_with("uvvis", (10.0, 20.0, WELL_Z + 2.0))


def test_scan_first_well_descends_to_well_z_plus_relative_offset():
    from cubos.protocol_engine.commands.scan import scan

    instr = _instrument(name="uvvis")
    instr.measure = MagicMock(return_value="ok")
    ctx = _ctx("uvvis", instr)

    scan(
        ctx,
        plate="plate_1",
        instrument="uvvis",
        method="measure",
        measurement_height=1.0,
        interwell_scan_height=10.0,
    )

    move_calls = ctx.gantry.move.call_args_list
    assert move_calls[0].args == ("uvvis", (10.0, 20.0, WELL_Z + 10.0))
    assert move_calls[1].args == ("uvvis", (10.0, 20.0, WELL_Z + 1.0))


def test_pipette_aspirate_descends_to_labware_reference_by_default():
    """Pipette commands engage at the labware reference Z by default."""
    from cubos.protocol_engine.commands.pipette import aspirate

    pipette = _instrument(name="pipette")
    pipette.aspirate = MagicMock(return_value="ok")
    ctx = _ctx("pipette", pipette)

    aspirate(ctx, position="plate_1.A1", volume_ul=10.0)

    ctx.gantry.move_to_labware.assert_called_once()
    ctx.gantry.move.assert_called_once_with(
        "pipette", (10.0, 20.0, WELL_Z),
    )


def test_pipette_aspirate_height_is_labware_relative():
    from cubos.protocol_engine.commands.pipette import aspirate

    pipette = _instrument(name="pipette")
    pipette.aspirate = MagicMock(return_value="ok")
    ctx = _ctx("pipette", pipette)

    aspirate(ctx, position="plate_1.A1", volume_ul=10.0, height=3.0)

    ctx.gantry.move_to_labware.assert_called_once()
    ctx.gantry.move.assert_called_once_with(
        "pipette", (10.0, 20.0, WELL_Z + 3.0),
    )


def test_move_named_park_position_passes_travel_z_unchanged():
    from cubos.protocol_engine.commands.move import move

    instrumented_gantry = MagicMock()
    instrumented_gantry.instruments = {"uvvis": _instrument(name="uvvis")}
    ctx = ProtocolContext(
        gantry=instrumented_gantry,
        deck=MagicMock(),
        positions={"park_position": [0.0, 0.0, 20.0]},
        logger=logging.getLogger("test"),
    )

    move(ctx, instrument="uvvis", position="park_position", travel_z=20.0)

    instrumented_gantry.move.assert_called_once_with(
        "uvvis",
        (0.0, 0.0, 20.0),
        travel_z=20.0,
    )
