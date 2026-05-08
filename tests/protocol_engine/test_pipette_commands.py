"""Tests for pipette protocol commands."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, call

import pytest

from deck.labware.labware import Coordinate3D
from deck.labware.well_plate import WellPlate
from protocol_engine.errors import ProtocolExecutionError
from protocol_engine.protocol import ProtocolContext


# ─── Helpers ──────────────────────────────────────────────────────────────────


PIPETTE_HEIGHT_MM = 14.10


def _mock_context(
    resolve_return: Coordinate3D | None = None,
    has_pipette: bool = True,
    height: float | None = PIPETTE_HEIGHT_MM,
) -> ProtocolContext:
    coord = resolve_return or Coordinate3D(x=100.0, y=50.0, z=PIPETTE_HEIGHT_MM)

    board = MagicMock()
    deck = MagicMock()
    deck.resolve.return_value = coord
    labware = MagicMock(height=height)
    deck.__getitem__ = MagicMock(return_value=labware)

    if has_pipette:
        pipette = MagicMock()
        pipette.aspirate.return_value = MagicMock(success=True, volume_ul=100.0)
        pipette.dispense.return_value = MagicMock(success=True, volume_ul=100.0)
        pipette.mix.return_value = MagicMock(success=True, volume_ul=50.0, repetitions=3)
        # Default: pipette's instrument-config measurement_height is 0 (well surface).
        board.instruments = {"pipette": pipette}
    else:
        board.instruments = {}

    return ProtocolContext(
        board=board,
        deck=deck,
        logger=logging.getLogger("test_pipette_commands"),
    )


def _get_pipette(ctx: ProtocolContext) -> MagicMock:
    return ctx.board.instruments["pipette"]


# ─── _parse_position tests ───────────────────────────────────────────────────


class TestParsePosition:

    def test_plate_and_well(self):
        from protocol_engine.commands.pipette import _parse_position

        assert _parse_position("plate_1.A1") == ("plate_1", "A1")

    def test_vial_no_well(self):
        from protocol_engine.commands.pipette import _parse_position

        assert _parse_position("vial_1") == ("vial_1", None)

    def test_dotted_well_takes_first_split(self):
        from protocol_engine.commands.pipette import _parse_position

        assert _parse_position("plate_1.A1.extra") == ("plate_1", "A1.extra")

    def test_return_type(self):
        from protocol_engine.commands.pipette import _parse_position

        result = _parse_position("plate_1.B2")
        assert isinstance(result, tuple)
        assert isinstance(result[0], str)
        assert isinstance(result[1], str)

        result_none = _parse_position("vial_1")
        assert result_none[1] is None


# ─── aspirate tests ──────────────────────────────────────────────────────────


class TestAspirateCommand:

    def test_resolves_position_via_deck(self):
        from protocol_engine.commands.pipette import aspirate

        ctx = _mock_context()
        aspirate(ctx, position="plate_1.A1", volume_ul=100.0)
        ctx.deck.resolve.assert_called_once_with("plate_1.A1")

    def test_moves_then_aspirates(self):
        from protocol_engine.commands.pipette import aspirate

        ctx = _mock_context()
        call_order = []
        ctx.board.move_to_labware.side_effect = lambda *a, **kw: call_order.append("move")
        _get_pipette(ctx).aspirate.side_effect = lambda *a: call_order.append("aspirate")

        aspirate(ctx, position="plate_1.A1", volume_ul=100.0)
        assert call_order == ["move", "aspirate"]

    def test_passes_volume_and_speed(self):
        from protocol_engine.commands.pipette import aspirate

        ctx = _mock_context()
        aspirate(ctx, position="plate_1.A1", volume_ul=75.0, speed=25.0)
        _get_pipette(ctx).aspirate.assert_called_once_with(75.0, 25.0)

    def test_default_speed(self):
        from protocol_engine.commands.pipette import aspirate

        ctx = _mock_context()
        aspirate(ctx, position="plate_1.A1", volume_ul=100.0)
        _get_pipette(ctx).aspirate.assert_called_once_with(100.0, 50.0)

    def test_moves_pipette_to_resolved_coord(self):
        from protocol_engine.commands.pipette import aspirate

        coord = Coordinate3D(x=10.0, y=20.0, z=75.0)
        ctx = _mock_context(resolve_return=coord)
        aspirate(ctx, position="plate_1.A1", volume_ul=100.0)
        ctx.board.move_to_labware.assert_called_once_with("pipette", coord)

    def test_descends_to_well_bottom_after_approach(self):
        """aspirate descends to ``height + 0`` (the labware reference Z,
        i.e. the well bottom). Pipette commands engage at the labware
        surface — per-command Z offsets aren't surfaced yet."""
        from protocol_engine.commands.pipette import aspirate

        coord = Coordinate3D(x=10.0, y=20.0, z=PIPETTE_HEIGHT_MM)
        ctx = _mock_context(resolve_return=coord)
        aspirate(ctx, position="plate_1.A1", volume_ul=100.0)
        ctx.board.move.assert_called_once_with(
            "pipette", (10.0, 20.0, PIPETTE_HEIGHT_MM),
        )

    def test_approach_then_descend_then_aspirate(self):
        """Ordering: approach (move_to_labware) -> descent (move) -> aspirate."""
        from protocol_engine.commands.pipette import aspirate

        ctx = _mock_context()
        order = []
        ctx.board.move_to_labware.side_effect = lambda *a, **k: order.append("approach")
        ctx.board.move.side_effect = lambda *a, **k: order.append("descent")
        _get_pipette(ctx).aspirate.side_effect = lambda *a: order.append("aspirate")

        aspirate(ctx, position="plate_1.A1", volume_ul=100.0)
        assert order == ["approach", "descent", "aspirate"]

    def test_raises_when_no_pipette(self):
        from protocol_engine.commands.pipette import aspirate

        ctx = _mock_context(has_pipette=False)
        with pytest.raises(ProtocolExecutionError, match="[Nn]o pipette"):
            aspirate(ctx, position="plate_1.A1", volume_ul=100.0)


# ─── dispense tests ──────────────────────────────────────────────────────────


class TestDispenseCommand:

    def test_resolves_position_via_deck(self):
        from protocol_engine.commands.pipette import dispense

        ctx = _mock_context()
        dispense(ctx, position="plate_1.A1", volume_ul=100.0)
        ctx.deck.resolve.assert_called_once_with("plate_1.A1")

    def test_moves_then_dispenses(self):
        from protocol_engine.commands.pipette import dispense

        ctx = _mock_context()
        call_order = []
        ctx.board.move_to_labware.side_effect = lambda *a, **kw: call_order.append("move")
        _get_pipette(ctx).dispense.side_effect = lambda *a: call_order.append("dispense")

        dispense(ctx, position="plate_1.A1", volume_ul=100.0)
        assert call_order == ["move", "dispense"]

    def test_passes_volume_and_speed(self):
        from protocol_engine.commands.pipette import dispense

        ctx = _mock_context()
        dispense(ctx, position="plate_1.A1", volume_ul=80.0, speed=30.0)
        _get_pipette(ctx).dispense.assert_called_once_with(80.0, 30.0)

    def test_default_speed(self):
        from protocol_engine.commands.pipette import dispense

        ctx = _mock_context()
        dispense(ctx, position="plate_1.A1", volume_ul=100.0)
        _get_pipette(ctx).dispense.assert_called_once_with(100.0, 50.0)

    def test_raises_when_no_pipette(self):
        from protocol_engine.commands.pipette import dispense

        ctx = _mock_context(has_pipette=False)
        with pytest.raises(ProtocolExecutionError, match="[Nn]o pipette"):
            dispense(ctx, position="plate_1.A1", volume_ul=100.0)


# ─── blowout tests ───────────────────────────────────────────────────────────


class TestBlowoutCommand:

    def test_resolves_position_via_deck(self):
        from protocol_engine.commands.pipette import blowout

        ctx = _mock_context()
        blowout(ctx, position="plate_1.A1")
        ctx.deck.resolve.assert_called_once_with("plate_1.A1")

    def test_moves_then_blows_out(self):
        from protocol_engine.commands.pipette import blowout

        ctx = _mock_context()
        call_order = []
        ctx.board.move_to_labware.side_effect = lambda *a, **kw: call_order.append("move")
        _get_pipette(ctx).blowout.side_effect = lambda *a: call_order.append("blowout")

        blowout(ctx, position="plate_1.A1")
        assert call_order == ["move", "blowout"]

    def test_passes_speed(self):
        from protocol_engine.commands.pipette import blowout

        ctx = _mock_context()
        blowout(ctx, position="plate_1.A1", speed=25.0)
        _get_pipette(ctx).blowout.assert_called_once_with(25.0)

    def test_default_speed(self):
        from protocol_engine.commands.pipette import blowout

        ctx = _mock_context()
        blowout(ctx, position="plate_1.A1")
        _get_pipette(ctx).blowout.assert_called_once_with(50.0)

    def test_raises_when_no_pipette(self):
        from protocol_engine.commands.pipette import blowout

        ctx = _mock_context(has_pipette=False)
        with pytest.raises(ProtocolExecutionError, match="[Nn]o pipette"):
            blowout(ctx, position="plate_1.A1")


# ─── mix tests ────────────────────────────────────────────────────────────────


class TestMixCommand:

    def test_resolves_position_via_deck(self):
        from protocol_engine.commands.pipette import mix

        ctx = _mock_context()
        mix(ctx, position="plate_1.A1", volume_ul=50.0)
        ctx.deck.resolve.assert_called_once_with("plate_1.A1")

    def test_moves_then_mixes(self):
        from protocol_engine.commands.pipette import mix

        ctx = _mock_context()
        call_order = []
        ctx.board.move_to_labware.side_effect = lambda *a, **kw: call_order.append("move")
        _get_pipette(ctx).mix.side_effect = lambda *a: call_order.append("mix")

        mix(ctx, position="plate_1.A1", volume_ul=50.0)
        assert call_order == ["move", "mix"]

    def test_passes_volume_repetitions_and_speed(self):
        from protocol_engine.commands.pipette import mix

        ctx = _mock_context()
        mix(ctx, position="plate_1.A1", volume_ul=50.0, repetitions=5, speed=20.0)
        _get_pipette(ctx).mix.assert_called_once_with(50.0, 5, 20.0)

    def test_default_repetitions_and_speed(self):
        from protocol_engine.commands.pipette import mix

        ctx = _mock_context()
        mix(ctx, position="plate_1.A1", volume_ul=50.0)
        _get_pipette(ctx).mix.assert_called_once_with(50.0, 3, 50.0)

    def test_raises_when_no_pipette(self):
        from protocol_engine.commands.pipette import mix

        ctx = _mock_context(has_pipette=False)
        with pytest.raises(ProtocolExecutionError, match="[Nn]o pipette"):
            mix(ctx, position="plate_1.A1", volume_ul=50.0)


# ─── pick_up_tip tests ───────────────────────────────────────────────────────


class TestPickUpTipCommand:

    def test_resolves_position_via_deck(self):
        from protocol_engine.commands.pipette import pick_up_tip

        ctx = _mock_context()
        pick_up_tip(ctx, position="tiprack_1.A1")
        ctx.deck.resolve.assert_called_once_with("tiprack_1.A1")

    def test_moves_then_picks_up(self):
        from protocol_engine.commands.pipette import pick_up_tip

        ctx = _mock_context()
        call_order = []
        ctx.board.move_to_labware.side_effect = lambda *a, **kw: call_order.append("move")
        _get_pipette(ctx).pick_up_tip.side_effect = lambda *a: call_order.append("pick_up_tip")

        pick_up_tip(ctx, position="tiprack_1.A1")
        assert call_order == ["move", "pick_up_tip"]

    def test_passes_speed(self):
        from protocol_engine.commands.pipette import pick_up_tip

        ctx = _mock_context()
        pick_up_tip(ctx, position="tiprack_1.A1", speed=10.0)
        _get_pipette(ctx).pick_up_tip.assert_called_once_with(10.0)

    def test_default_speed(self):
        from protocol_engine.commands.pipette import pick_up_tip

        ctx = _mock_context()
        pick_up_tip(ctx, position="tiprack_1.A1")
        _get_pipette(ctx).pick_up_tip.assert_called_once_with(50.0)

    def test_raises_when_no_pipette(self):
        from protocol_engine.commands.pipette import pick_up_tip

        ctx = _mock_context(has_pipette=False)
        with pytest.raises(ProtocolExecutionError, match="[Nn]o pipette"):
            pick_up_tip(ctx, position="tiprack_1.A1")


# ─── drop_tip tests ──────────────────────────────────────────────────────────


class TestDropTipCommand:

    def test_resolves_position_via_deck(self):
        from protocol_engine.commands.pipette import drop_tip

        ctx = _mock_context()
        drop_tip(ctx, position="waste_1")
        ctx.deck.resolve.assert_called_once_with("waste_1")

    def test_moves_then_drops(self):
        from protocol_engine.commands.pipette import drop_tip

        ctx = _mock_context()
        call_order = []
        ctx.board.move_to_labware.side_effect = lambda *a, **kw: call_order.append("move")
        _get_pipette(ctx).drop_tip.side_effect = lambda *a: call_order.append("drop_tip")

        drop_tip(ctx, position="waste_1")
        assert call_order == ["move", "drop_tip"]

    def test_passes_speed(self):
        from protocol_engine.commands.pipette import drop_tip

        ctx = _mock_context()
        drop_tip(ctx, position="waste_1", speed=10.0)
        _get_pipette(ctx).drop_tip.assert_called_once_with(10.0)

    def test_default_speed(self):
        from protocol_engine.commands.pipette import drop_tip

        ctx = _mock_context()
        drop_tip(ctx, position="waste_1")
        _get_pipette(ctx).drop_tip.assert_called_once_with(50.0)

    def test_raises_when_no_pipette(self):
        from protocol_engine.commands.pipette import drop_tip

        ctx = _mock_context(has_pipette=False)
        with pytest.raises(ProtocolExecutionError, match="[Nn]o pipette"):
            drop_tip(ctx, position="waste_1")


# ─── transfer tests ──────────────────────────────────────────────────────────


def _mock_context_multi_resolve(has_pipette: bool = True) -> ProtocolContext:
    """Context where deck.resolve returns different coords per position string."""
    board = MagicMock()
    deck = MagicMock()

    coords = {
        "plate_1.A1": Coordinate3D(x=10.0, y=20.0, z=75.0),
        "plate_1.B1": Coordinate3D(x=10.0, y=28.0, z=75.0),
    }
    deck.resolve.side_effect = lambda pos: coords.get(pos, Coordinate3D(x=0.0, y=0.0, z=0.0))

    if has_pipette:
        pipette = MagicMock()
        # Real numeric heights so the dispatch finite-number guards pass;
        # test fixtures elsewhere set realistic values for engagement math.
        pipette.aspirate.return_value = MagicMock(success=True, volume_ul=100.0)
        pipette.dispense.return_value = MagicMock(success=True, volume_ul=100.0)
        board.instruments = {"pipette": pipette}
    else:
        board.instruments = {}

    return ProtocolContext(
        board=board,
        deck=deck,
        logger=logging.getLogger("test_pipette_commands"),
    )


class TestTransferCommand:

    def test_resolves_both_positions(self):
        from protocol_engine.commands.pipette import transfer

        ctx = _mock_context_multi_resolve()
        transfer(ctx, source="plate_1.A1", destination="plate_1.B1", volume_ul=100.0)

        ctx.deck.resolve.assert_any_call("plate_1.A1")
        ctx.deck.resolve.assert_any_call("plate_1.B1")
        assert ctx.deck.resolve.call_count == 2

    def test_aspirates_from_source_then_dispenses_to_destination(self):
        from protocol_engine.commands.pipette import transfer

        ctx = _mock_context_multi_resolve()
        pip = ctx.board.instruments["pipette"]
        call_order = []
        ctx.board.move_to_labware.side_effect = lambda *a, **kw: call_order.append(("move", a[1]))
        pip.aspirate.side_effect = lambda *a: call_order.append("aspirate")
        pip.dispense.side_effect = lambda *a: call_order.append("dispense")

        transfer(ctx, source="plate_1.A1", destination="plate_1.B1", volume_ul=100.0)

        source_coord = Coordinate3D(x=10.0, y=20.0, z=75.0)
        dest_coord = Coordinate3D(x=10.0, y=28.0, z=75.0)
        assert call_order == [
            ("move", source_coord),
            "aspirate",
            ("move", dest_coord),
            "dispense",
        ]

    def test_passes_volume_and_speed(self):
        from protocol_engine.commands.pipette import transfer

        ctx = _mock_context_multi_resolve()
        pip = ctx.board.instruments["pipette"]

        transfer(ctx, source="plate_1.A1", destination="plate_1.B1", volume_ul=75.0, speed=25.0)

        pip.aspirate.assert_called_once_with(75.0, 25.0)
        pip.dispense.assert_called_once_with(75.0, 25.0)

    def test_default_speed(self):
        from protocol_engine.commands.pipette import transfer

        ctx = _mock_context_multi_resolve()
        pip = ctx.board.instruments["pipette"]

        transfer(ctx, source="plate_1.A1", destination="plate_1.B1", volume_ul=100.0)

        pip.aspirate.assert_called_once_with(100.0, 50.0)
        pip.dispense.assert_called_once_with(100.0, 50.0)

    def test_raises_when_no_pipette(self):
        from protocol_engine.commands.pipette import transfer

        ctx = _mock_context_multi_resolve(has_pipette=False)
        with pytest.raises(ProtocolExecutionError, match="[Nn]o pipette"):
            transfer(ctx, source="plate_1.A1", destination="plate_1.B1", volume_ul=100.0)


# ─── serial_transfer tests ───────────────────────────────────────────────────


def _make_2x3_plate() -> WellPlate:
    """2 rows (A-B) x 3 columns (1-3) plate for serial_transfer tests."""
    return WellPlate(
        name="plate_1",
        model_name="test_model",
        length=127.71,
        width=85.43,
        height=14.10,
        rows=2,
        columns=3,
        wells={
            "A1": Coordinate3D(x=0.0, y=0.0, z=75.0),
            "A2": Coordinate3D(x=10.0, y=0.0, z=75.0),
            "A3": Coordinate3D(x=20.0, y=0.0, z=75.0),
            "B1": Coordinate3D(x=0.0, y=8.0, z=75.0),
            "B2": Coordinate3D(x=10.0, y=8.0, z=75.0),
            "B3": Coordinate3D(x=20.0, y=8.0, z=75.0),
        },
        capacity_ul=200.0,
        working_volume_ul=150.0,
    )


def _serial_transfer_context(
    plate: WellPlate | None = None,
    has_pipette: bool = True,
) -> ProtocolContext:
    plate = plate or _make_2x3_plate()

    board = MagicMock()
    deck = MagicMock()
    deck.__getitem__ = MagicMock(return_value=plate)
    deck.resolve.side_effect = lambda pos: Coordinate3D(x=0.0, y=0.0, z=0.0)

    if has_pipette:
        pipette = MagicMock()
        pipette.aspirate.return_value = MagicMock(success=True)
        pipette.dispense.return_value = MagicMock(success=True)
        board.instruments = {"pipette": pipette}
    else:
        board.instruments = {}

    return ProtocolContext(
        board=board,
        deck=deck,
        logger=logging.getLogger("test_serial_transfer"),
    )


class TestSerialTransferCommand:

    def test_row_axis_transfers_to_each_well_in_order(self):
        from protocol_engine.commands.pipette import serial_transfer

        ctx = _serial_transfer_context()
        serial_transfer(
            ctx, source="vial_1", plate="plate_1", axis="A",
            volumes=[10.0, 20.0, 30.0],
        )

        pip = ctx.board.instruments["pipette"]
        assert pip.aspirate.call_count == 3
        assert pip.dispense.call_count == 3

        # Verify resolve was called with the right destination strings
        resolve_calls = [c.args[0] for c in ctx.deck.resolve.call_args_list]
        # Each transfer resolves source + destination, so 6 calls total
        # Destinations should be plate_1.A1, plate_1.A2, plate_1.A3
        assert "plate_1.A1" in resolve_calls
        assert "plate_1.A2" in resolve_calls
        assert "plate_1.A3" in resolve_calls

    def test_column_axis_transfers_to_each_well_in_order(self):
        from protocol_engine.commands.pipette import serial_transfer

        ctx = _serial_transfer_context()
        serial_transfer(
            ctx, source="vial_1", plate="plate_1", axis="2",
            volumes=[10.0, 20.0],
        )

        pip = ctx.board.instruments["pipette"]
        assert pip.aspirate.call_count == 2
        assert pip.dispense.call_count == 2

        resolve_calls = [c.args[0] for c in ctx.deck.resolve.call_args_list]
        assert "plate_1.A2" in resolve_calls
        assert "plate_1.B2" in resolve_calls

    def test_explicit_volumes_passed_correctly(self):
        from protocol_engine.commands.pipette import serial_transfer

        ctx = _serial_transfer_context()
        serial_transfer(
            ctx, source="vial_1", plate="plate_1", axis="A",
            volumes=[10.0, 50.0, 100.0],
        )

        pip = ctx.board.instruments["pipette"]
        aspirate_volumes = [c.args[0] for c in pip.aspirate.call_args_list]
        dispense_volumes = [c.args[0] for c in pip.dispense.call_args_list]
        assert aspirate_volumes == [10.0, 50.0, 100.0]
        assert dispense_volumes == [10.0, 50.0, 100.0]

    def test_volume_range_linearly_spaced(self):
        from protocol_engine.commands.pipette import serial_transfer

        ctx = _serial_transfer_context()
        serial_transfer(
            ctx, source="vial_1", plate="plate_1", axis="A",
            volume_range=[10.0, 30.0],
        )

        pip = ctx.board.instruments["pipette"]
        aspirate_volumes = [c.args[0] for c in pip.aspirate.call_args_list]
        # 3 wells in row A, linspace(10, 30, 3) = [10.0, 20.0, 30.0]
        assert aspirate_volumes == pytest.approx([10.0, 20.0, 30.0])

    def test_volume_range_single_well_column(self):
        """volume_range with a 1-well axis uses the start value."""
        from protocol_engine.commands.pipette import serial_transfer

        # Make a 1x3 plate so column "1" has only 1 well (A1)
        plate = WellPlate(
            name="plate_1", model_name="t", length=100.0,
            width=80.0, height=10.0, rows=1, columns=3,
            wells={
                "A1": Coordinate3D(x=0.0, y=0.0, z=75.0),
                "A2": Coordinate3D(x=10.0, y=0.0, z=75.0),
                "A3": Coordinate3D(x=20.0, y=0.0, z=75.0),
            },
            capacity_ul=200.0, working_volume_ul=150.0,
        )
        ctx = _serial_transfer_context(plate=plate)
        serial_transfer(
            ctx, source="vial_1", plate="plate_1", axis="1",
            volume_range=[10.0, 100.0],
        )

        pip = ctx.board.instruments["pipette"]
        assert pip.aspirate.call_count == 1
        aspirate_volumes = [c.args[0] for c in pip.aspirate.call_args_list]
        assert aspirate_volumes == [10.0]

    def test_custom_speed_passed_through(self):
        from protocol_engine.commands.pipette import serial_transfer

        ctx = _serial_transfer_context()
        serial_transfer(
            ctx, source="vial_1", plate="plate_1", axis="A",
            volumes=[10.0, 20.0, 30.0], speed=25.0,
        )

        pip = ctx.board.instruments["pipette"]
        for c in pip.aspirate.call_args_list:
            assert c.args[1] == 25.0
        for c in pip.dispense.call_args_list:
            assert c.args[1] == 25.0

    def test_volumes_length_mismatch_raises(self):
        from protocol_engine.commands.pipette import serial_transfer

        ctx = _serial_transfer_context()
        with pytest.raises(ProtocolExecutionError, match="length"):
            serial_transfer(
                ctx, source="vial_1", plate="plate_1", axis="A",
                volumes=[10.0, 20.0],  # row A has 3 wells
            )

    def test_neither_volumes_nor_range_raises(self):
        from protocol_engine.commands.pipette import serial_transfer

        ctx = _serial_transfer_context()
        with pytest.raises(ProtocolExecutionError, match="volumes.*volume_range"):
            serial_transfer(
                ctx, source="vial_1", plate="plate_1", axis="A",
            )

    def test_both_volumes_and_range_raises(self):
        from protocol_engine.commands.pipette import serial_transfer

        ctx = _serial_transfer_context()
        with pytest.raises(ProtocolExecutionError, match="volumes.*volume_range"):
            serial_transfer(
                ctx, source="vial_1", plate="plate_1", axis="A",
                volumes=[10.0, 20.0, 30.0], volume_range=[10.0, 30.0],
            )

    def test_invalid_axis_raises(self):
        from protocol_engine.commands.pipette import serial_transfer

        ctx = _serial_transfer_context()
        with pytest.raises(ProtocolExecutionError, match="axis"):
            serial_transfer(
                ctx, source="vial_1", plate="plate_1", axis="Z",
                volumes=[10.0],
            )

    def test_raises_when_no_pipette(self):
        from protocol_engine.commands.pipette import serial_transfer

        ctx = _serial_transfer_context(has_pipette=False)
        with pytest.raises(ProtocolExecutionError, match="[Nn]o pipette"):
            serial_transfer(
                ctx, source="vial_1", plate="plate_1", axis="A",
                volumes=[10.0, 20.0, 30.0],
            )

    def test_validates_plate_is_wellplate(self):
        from protocol_engine.commands.pipette import serial_transfer

        ctx = _serial_transfer_context()
        ctx.deck.__getitem__ = MagicMock(return_value=MagicMock(spec=[]))

        with pytest.raises(ProtocolExecutionError, match="WellPlate"):
            serial_transfer(
                ctx, source="vial_1", plate="plate_1", axis="A",
                volumes=[10.0],
            )
