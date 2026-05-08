"""Tests for deck and gantry bounds validation."""

from __future__ import annotations

from unittest.mock import MagicMock

from board.board import Board
from deck.deck import Deck
from deck.labware.labware import Coordinate3D
from deck.labware.tip_disposal import TipDisposal
from deck.labware.vial import Vial
from deck.labware.wall import Wall
from deck.labware.well_plate import WellPlate
from deck.labware.well_plate_holder import WellPlateHolder
from instruments.base_instrument import BaseInstrument
from gantry.gantry_config import GantryConfig, GantryType, HomingStrategy, WorkingVolume
from validation.bounds import validate_deck_positions, validate_gantry_positions


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_gantry(
    x_min: float = 0.0,
    x_max: float = 300.0,
    y_min: float = 0.0,
    y_max: float = 200.0,
    z_min: float = 0.0,
    z_max: float = 80.0,
    total_z_height: float = 90.0,
) -> GantryConfig:
    return GantryConfig(
        serial_port="/dev/ttyUSB0",
        gantry_type=GantryType.CUB_XL,
        homing_strategy=HomingStrategy.STANDARD,
        total_z_height=total_z_height,
        working_volume=WorkingVolume(
            x_min=x_min, x_max=x_max,
            y_min=y_min, y_max=y_max,
            z_min=z_min, z_max=z_max,
        ),
    )


def _make_vial(
    name: str = "test_vial",
    x: float = 30.0,
    y: float = 40.0,
    z: float = 20.0,
) -> Vial:
    return Vial(
        name=name,
        model_name="standard_vial",
        height_mm=66.75,
        diameter_mm=28.0,
        location=Coordinate3D(x=x, y=y, z=z),
        capacity_ul=1500.0,
        working_volume_ul=1200.0,
    )


def _make_plate(
    name: str = "test_plate",
    a1_x: float = 10.0,
    a1_y: float = 10.0,
    a1_z: float = 15.0,
    rows: int = 2,
    columns: int = 2,
    x_offset: float = 5.0,
    y_offset: float = 5.0,
) -> WellPlate:
    """Create a small well plate with derived wells."""
    wells = {}
    row_labels = [chr(65 + r) for r in range(rows)]
    for r_idx, row in enumerate(row_labels):
        for c_idx in range(columns):
            well_id = f"{row}{c_idx + 1}"
            wells[well_id] = Coordinate3D(
                x=a1_x + x_offset * c_idx,
                y=a1_y + y_offset * r_idx,
                z=a1_z,
            )
    return WellPlate(
        name=name,
        model_name="test_plate_model",
        length_mm=50.0,
        width_mm=30.0,
        height_mm=14.0,
        rows=rows,
        columns=columns,
        wells=wells,
        capacity_ul=200.0,
        working_volume_ul=150.0,
    )


def _make_deck(**labware) -> Deck:
    return Deck(labware)


def _make_instrument(
    offset_x: float = 0.0,
    offset_y: float = 0.0,
    depth: float = 0.0,
) -> BaseInstrument:
    instr = MagicMock(spec=BaseInstrument)
    instr.offset_x = offset_x
    instr.offset_y = offset_y
    instr.depth = depth
    instr.name = "mock_instrument"
    return instr


def _make_board(*instruments: tuple) -> Board:
    """Build a Board with named instruments and a mock gantry."""
    gantry = MagicMock()
    instr_dict = {}
    for name, instr in instruments:
        instr_dict[name] = instr
    return Board(gantry=gantry, instruments=instr_dict)


# ── Deck position validation ────────────────────────────────────────────


class TestValidateDeckPositions:

    def test_all_positions_within_bounds_passes(self):
        gantry = _make_gantry()
        deck = _make_deck(vial_1=_make_vial(x=30.0, y=40.0, z=20.0))
        violations = validate_deck_positions(gantry, deck)
        assert violations == []

    def test_well_plate_all_wells_within_bounds_passes(self):
        gantry = _make_gantry()
        plate = _make_plate(a1_x=10.0, a1_y=10.0, a1_z=15.0)
        deck = _make_deck(plate_1=plate)
        violations = validate_deck_positions(gantry, deck)
        assert violations == []

    def test_vial_outside_x_min_fails(self):
        gantry = _make_gantry(x_min=0.0)
        deck = _make_deck(vial_1=_make_vial(x=-0.001))
        violations = validate_deck_positions(gantry, deck)
        assert len(violations) == 1
        assert violations[0].labware_key == "vial_1"
        assert violations[0].position_id == "location"
        assert violations[0].axis == "x"
        assert violations[0].bound_name == "x_min"

    def test_vial_outside_x_max_fails(self):
        gantry = _make_gantry(x_max=300.0)
        deck = _make_deck(vial_1=_make_vial(x=300.001))
        violations = validate_deck_positions(gantry, deck)
        assert len(violations) == 1
        assert violations[0].axis == "x"
        assert violations[0].bound_name == "x_max"

    def test_well_plate_corner_well_outside_y_max_fails(self):
        gantry = _make_gantry(y_max=20.0)
        # B1 well will be at y = 10.0 + 15.0 = 25.0, outside y_max=20
        plate = _make_plate(a1_y=10.0, y_offset=15.0)
        deck = _make_deck(plate_1=plate)
        violations = validate_deck_positions(gantry, deck)
        assert len(violations) > 0
        lw_keys = {v.labware_key for v in violations}
        assert "plate_1" in lw_keys

    def test_well_plate_corner_well_outside_z_min_fails(self):
        gantry = _make_gantry(z_min=20.0)
        plate = _make_plate(a1_z=15.0)
        deck = _make_deck(plate_1=plate)
        violations = validate_deck_positions(gantry, deck)
        assert len(violations) > 0
        assert all(v.axis == "z" for v in violations)

    def test_position_exactly_on_boundary_passes(self):
        gantry = _make_gantry(x_min=0.0)
        deck = _make_deck(vial_1=_make_vial(x=0.0))
        violations = validate_deck_positions(gantry, deck)
        assert violations == []

    def test_position_epsilon_beyond_boundary_fails(self):
        gantry = _make_gantry(x_min=0.0)
        deck = _make_deck(vial_1=_make_vial(x=-0.001))
        violations = validate_deck_positions(gantry, deck)
        assert len(violations) == 1

    def test_empty_deck_passes(self):
        gantry = _make_gantry()
        deck = _make_deck()
        violations = validate_deck_positions(gantry, deck)
        assert violations == []

    def test_mixed_labware_one_out_of_bounds_fails(self):
        gantry = _make_gantry(x_min=0.0)
        vial_ok = _make_vial(name="ok_vial", x=100.0)
        vial_bad = _make_vial(name="bad_vial", x=-1.0)
        deck = _make_deck(ok=vial_ok, bad=vial_bad)
        violations = validate_deck_positions(gantry, deck)
        assert len(violations) == 1
        assert violations[0].labware_key == "bad"

    def test_multiple_violations_reported(self):
        gantry = _make_gantry(x_min=50.0, y_min=50.0)
        vial_bad_x = _make_vial(name="v1", x=20.0, y=80.0, z=20.0)
        vial_bad_y = _make_vial(name="v2", x=80.0, y=20.0, z=20.0)
        deck = _make_deck(v1=vial_bad_x, v2=vial_bad_y)
        violations = validate_deck_positions(gantry, deck)
        assert len(violations) == 2

    def test_violation_identifies_labware_and_position(self):
        gantry = _make_gantry(x_min=50.0)
        deck = _make_deck(my_vial=_make_vial(x=20.0))
        violations = validate_deck_positions(gantry, deck)
        assert violations[0].labware_key == "my_vial"
        assert violations[0].position_id == "location"
        assert violations[0].coordinate_type == "deck"
        assert violations[0].instrument_name is None

    def test_holder_anchor_below_z_min_is_not_a_motion_target(self):
        gantry = _make_gantry(z_min=80.0, z_max=101.5, total_z_height=101.5)
        plate = _make_plate(a1_x=15.0, a1_y=17.0, a1_z=89.5)
        holder = WellPlateHolder(
            name="plate_holder",
            location=Coordinate3D(x=0.0, y=0.0, z=0.0),
            contained_labware={"plate": plate},
        )
        deck = _make_deck(plate_holder=holder)

        assert validate_deck_positions(gantry, deck) == []

    def test_nested_holder_plate_motion_target_below_z_min_still_fails(self):
        gantry = _make_gantry(z_min=80.0, z_max=101.5, total_z_height=101.5)
        plate = _make_plate(a1_x=15.0, a1_y=17.0, a1_z=79.9)
        holder = WellPlateHolder(
            name="plate_holder",
            location=Coordinate3D(x=0.0, y=0.0, z=0.0),
            contained_labware={"plate": plate},
        )
        deck = _make_deck(plate_holder=holder)

        violations = validate_deck_positions(gantry, deck)

        assert violations
        assert all(v.position_id == "plate" or v.position_id.startswith("plate.")
                   for v in violations)
        assert all(v.axis == "z" for v in violations)

    def test_wall_geometry_is_not_a_motion_target(self):
        gantry = _make_gantry(z_min=80.0, z_max=101.5, total_z_height=101.5)
        wall = Wall(
            name="front_stop",
            corner_1=Coordinate3D(x=0.0, y=0.0, z=0.0),
            corner_2=Coordinate3D(x=10.0, y=10.0, z=10.0),
        )
        deck = _make_deck(front_stop=wall)

        assert validate_deck_positions(gantry, deck) == []

    def test_tip_disposal_location_remains_a_motion_target(self):
        gantry = _make_gantry(z_min=80.0, z_max=101.5, total_z_height=101.5)
        disposal = TipDisposal(
            name="waste",
            location=Coordinate3D(x=20.0, y=20.0, z=79.9),
        )
        deck = _make_deck(waste=disposal)

        violations = validate_deck_positions(gantry, deck)

        assert len(violations) == 1
        assert violations[0].labware_key == "waste"
        assert violations[0].position_id == "location"
        assert violations[0].axis == "z"


# ── Gantry position validation ──────────────────────────────────────────


class TestValidateGantryPositions:

    def test_all_gantry_positions_within_bounds_passes(self):
        gantry = _make_gantry()
        deck = _make_deck(vial_1=_make_vial(x=30.0, y=40.0, z=20.0))
        instr = _make_instrument(offset_x=5.0, offset_y=0.0, depth=0.0)
        board = _make_board(("instr_1", instr))
        violations = validate_gantry_positions(gantry, deck, board)
        assert violations == []

    def test_instrument_offset_pushes_gantry_outside_x_max_fails(self):
        # vial at x=299.0, instrument offset_x=-5.0
        # gantry_x = 299.0 - (-5.0) = 304.0 > x_max=300.0
        gantry = _make_gantry(x_max=300.0)
        deck = _make_deck(vial_1=_make_vial(x=299.0, y=40.0, z=20.0))
        instr = _make_instrument(offset_x=-5.0)
        board = _make_board(("probe", instr))
        violations = validate_gantry_positions(gantry, deck, board)
        assert len(violations) >= 1
        assert any(v.axis == "x" and v.bound_name == "x_max" for v in violations)

    def test_instrument_offset_pushes_gantry_outside_x_min_fails(self):
        # vial at x=5.0, instrument offset_x=10.0
        # gantry_x = 5.0 - 10.0 = -5.0 < x_min=0.0
        gantry = _make_gantry(x_min=0.0)
        deck = _make_deck(vial_1=_make_vial(x=5.0, y=40.0, z=20.0))
        instr = _make_instrument(offset_x=10.0)
        board = _make_board(("probe", instr))
        violations = validate_gantry_positions(gantry, deck, board)
        assert len(violations) >= 1
        assert any(v.axis == "x" and v.bound_name == "x_min" for v in violations)

    def test_instrument_depth_pushes_gantry_outside_z_max_fails(self):
        # vial at z=75.0, instrument depth=10.0
        # gantry_z = 75.0 + 10.0 = 85.0 > z_max=80.0
        gantry = _make_gantry(z_max=80.0)
        deck = _make_deck(vial_1=_make_vial(x=30.0, y=40.0, z=75.0))
        instr = _make_instrument(depth=10.0)
        board = _make_board(("deep_instr", instr))
        violations = validate_gantry_positions(gantry, deck, board)
        assert len(violations) >= 1
        assert any(v.axis == "z" and v.bound_name == "z_max" for v in violations)

    def test_gantry_position_exactly_on_boundary_passes(self):
        # vial at x=5.0, offset_x=5.0 -> gantry_x = 0.0 = x_min
        gantry = _make_gantry(x_min=0.0)
        deck = _make_deck(vial_1=_make_vial(x=5.0, y=40.0, z=20.0))
        instr = _make_instrument(offset_x=5.0)
        board = _make_board(("instr_1", instr))
        violations = validate_gantry_positions(gantry, deck, board)
        assert violations == []

    def test_gantry_position_epsilon_beyond_boundary_fails(self):
        # vial at x=4.999, offset_x=5.0 -> gantry_x = -0.001 < x_min=0.0
        gantry = _make_gantry(x_min=0.0)
        deck = _make_deck(vial_1=_make_vial(x=4.999, y=40.0, z=20.0))
        instr = _make_instrument(offset_x=5.0)
        board = _make_board(("instr_1", instr))
        violations = validate_gantry_positions(gantry, deck, board)
        assert len(violations) >= 1

    def test_zero_offset_instrument_gantry_equals_deck_position(self):
        gantry = _make_gantry()
        deck = _make_deck(vial_1=_make_vial(x=30.0, y=40.0, z=20.0))
        instr = _make_instrument(offset_x=0.0, offset_y=0.0, depth=0.0)
        board = _make_board(("instr_1", instr))
        violations = validate_gantry_positions(gantry, deck, board)
        assert violations == []

    def test_multiple_instruments_one_ok_one_fails(self):
        gantry = _make_gantry(x_min=0.0)
        deck = _make_deck(vial_1=_make_vial(x=2.0, y=40.0, z=20.0))
        ok_instr = _make_instrument(offset_x=0.0)
        bad_instr = _make_instrument(offset_x=5.0)
        board = _make_board(("ok", ok_instr), ("bad", bad_instr))
        violations = validate_gantry_positions(gantry, deck, board)
        assert len(violations) >= 1
        instr_names = {v.instrument_name for v in violations}
        assert "bad" in instr_names
        assert "ok" not in instr_names

    def test_error_identifies_instrument_labware_and_position(self):
        gantry = _make_gantry(x_min=0.0)
        deck = _make_deck(my_vial=_make_vial(x=2.0, y=40.0, z=20.0))
        instr = _make_instrument(offset_x=5.0)
        board = _make_board(("my_probe", instr))
        violations = validate_gantry_positions(gantry, deck, board)
        assert violations[0].instrument_name == "my_probe"
        assert violations[0].labware_key == "my_vial"
        assert violations[0].position_id == "location"
        assert violations[0].coordinate_type == "gantry"

    def test_empty_deck_passes_gantry_validation(self):
        gantry = _make_gantry()
        deck = _make_deck()
        instr = _make_instrument(offset_x=-15.0)
        board = _make_board(("instr_1", instr))
        violations = validate_gantry_positions(gantry, deck, board)
        assert violations == []

    def test_empty_board_no_instruments_passes(self):
        gantry = _make_gantry()
        deck = _make_deck(vial_1=_make_vial())
        board = _make_board()
        violations = validate_gantry_positions(gantry, deck, board)
        assert violations == []

    def test_well_plate_gantry_validation_checks_all_wells(self):
        # 2x2 plate: A1.x=10, A2.x=15. instrument offset_x=15.
        # A1 gantry_x = 10 - 15 = -5 (out of bounds), A2 gantry_x = 15 - 15 = 0 (boundary).
        gantry = _make_gantry(x_min=0.0)
        plate = _make_plate(a1_x=10.0, a1_y=10.0, a1_z=15.0)
        deck = _make_deck(plate_1=plate)
        instr = _make_instrument(offset_x=15.0)
        board = _make_board(("big_offset", instr))
        violations = validate_gantry_positions(gantry, deck, board)
        # At least one well should violate x_min.
        assert len(violations) > 0
        assert all(v.instrument_name == "big_offset" for v in violations)

    def test_holder_anchor_below_z_min_is_not_a_gantry_motion_target(self):
        gantry = _make_gantry(z_min=80.0, z_max=101.5, total_z_height=101.5)
        plate = _make_plate(a1_x=15.0, a1_y=17.0, a1_z=89.5)
        holder = WellPlateHolder(
            name="plate_holder",
            location=Coordinate3D(x=0.0, y=0.0, z=0.0),
            contained_labware={"plate": plate},
        )
        deck = _make_deck(plate_holder=holder)
        board = _make_board(("uv_curing", _make_instrument()))

        assert validate_gantry_positions(gantry, deck, board) == []
