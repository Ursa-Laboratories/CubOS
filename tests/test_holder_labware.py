import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from deck import (
    BoundingBoxGeometry,
    Coordinate3D,
    Deck,
    LabwareSlot,
    TipDisposal,
    Vial,
    VialHolder,
    WellPlate,
    WellPlateHolder,
)
from deck.loader import load_deck_from_yaml
from gantry.gantry_config import GantryConfig, GantryType, HomingStrategy, WorkingVolume
from validation.bounds import validate_deck_positions


def _make_gantry() -> GantryConfig:
    return GantryConfig(
        serial_port="/dev/ttyUSB0",
        gantry_type=GantryType.CUB_XL,
        homing_strategy=HomingStrategy.STANDARD,
        total_z_range=90.0,
        working_volume=WorkingVolume(
            x_min=0.0,
            x_max=300.0,
            y_min=0.0,
            y_max=300.0,
            z_min=0.0,
            z_max=100.0,
        ),
    )


def test_holder_seat_offset_metadata_is_encoded():
    vial_holder = VialHolder(
        name="vial_holder",
        location=Coordinate3D(x=0.0, y=0.0, z=0.0),
    )
    plate_holder = WellPlateHolder(
        name="plate_holder",
        location=Coordinate3D(x=0.0, y=0.0, z=0.0),
    )

    assert vial_holder.height == pytest.approx(35.1)
    assert vial_holder.labware_support_height == pytest.approx(35.1)
    assert vial_holder.labware_seat_height_from_bottom == pytest.approx(18.0)
    assert vial_holder.geometry == BoundingBoxGeometry(
        length=36.2,
        width=300.2,
        height=35.1,
    )

    # Keep the existing collision-envelope height, while separately storing
    # the base/support geometry that defines the seated plate offset.
    assert plate_holder.height == pytest.approx(14.8)
    assert plate_holder.labware_support_height == pytest.approx(10.0)
    assert plate_holder.labware_seat_height_from_bottom == pytest.approx(5.0)
    assert plate_holder.geometry == BoundingBoxGeometry(
        length=100.0,
        width=155.0,
        height=14.8,
    )


def test_well_plate_holder_resolves_named_slot_positions():
    holder = WellPlateHolder(
        name="slide_holder",
        location=Coordinate3D(x=50.0, y=60.0, z=12.0),
        slots={
            "plate": LabwareSlot(
                location=Coordinate3D(x=51.0, y=61.0, z=12.0),
                supported_labware_types=("well_plate",),
            ),
        },
    )

    assert holder.length == pytest.approx(100.0)
    assert holder.width == pytest.approx(155.0)
    assert holder.height == pytest.approx(14.8)
    assert holder.get_location("plate") == Coordinate3D(x=51.0, y=61.0, z=12.0)
    assert holder.iter_positions()["plate"] == Coordinate3D(x=51.0, y=61.0, z=12.0)


def test_vial_holder_rejects_more_slots_than_capacity():
    too_many_slots = {
        f"vial_{index}": LabwareSlot(
            location=Coordinate3D(x=float(index), y=0.0, z=0.0),
            supported_labware_types=("vial",),
        )
        for index in range(1, 11)
    }

    with pytest.raises(ValidationError, match="slot_count"):
        VialHolder(
            name="vial_holder",
            location=Coordinate3D(x=0.0, y=0.0, z=0.0),
            slots=too_many_slots,
        )


def test_tip_disposal_resolves_from_deck():
    deck = Deck(
        {
            "waste": TipDisposal(
                name="waste",
                location=Coordinate3D(x=100.0, y=110.0, z=15.0),
            ),
        }
    )

    assert deck.resolve("waste") == Coordinate3D(x=100.0, y=110.0, z=15.0)


def test_load_holder_labware_from_yaml():
    yaml_str = """
labware:
  waste:
    type: tip_disposal
    name: waste
    location:
      x: 25.0
      y: 35.0
      z: 10.0
    height: 10.0
  slide_holder:
    type: well_plate_holder
    name: slide_holder
    location:
      x: 50.0
      y: 60.0
      z: 12.0
    slots:
      plate:
        location:
          x: 51.0
          y: 61.0
        supported_labware_types:
          - well_plate
  vial_holder:
    type: vial_holder
    name: vial_holder
    location:
      x: 70.0
      y: 80.0
      z: 15.0
    slots:
      vial_1:
        location:
          x: 71.0
          y: 81.0
        supported_labware_types:
          - vial
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as handle:
        handle.write(yaml_str)
        path = handle.name

    try:
        deck = load_deck_from_yaml(path, total_z_range=90.0)
        assert isinstance(deck["waste"], TipDisposal)
        assert isinstance(deck["slide_holder"], WellPlateHolder)
        assert isinstance(deck["vial_holder"], VialHolder)
        assert deck["waste"].location.z == pytest.approx(10.0)
        assert deck.resolve("slide_holder.plate") == Coordinate3D(x=51.0, y=61.0, z=12.0)
        assert deck.resolve("vial_holder.vial_1") == Coordinate3D(x=71.0, y=81.0, z=15.0)
    finally:
        Path(path).unlink(missing_ok=True)


def test_nested_vials_in_holder_use_seat_height_for_z_generation():
    yaml_str = """
labware:
  vial_holder:
    type: vial_holder
    name: vial_holder
    location:
      x: 17.1
      y: 132.9
      z: 164.0
    vials:
      vial_1:
        model_name: 20ml_vial
        height: 57.0
        diameter: 28.0
        location:
          x: 17.1
          y: 0.9
        capacity_ul: 20000.0
        working_volume_ul: 6500.0
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as handle:
        handle.write(yaml_str)
        path = handle.name

    try:
        deck = load_deck_from_yaml(path)
        holder = deck["vial_holder"]

        assert isinstance(holder, VialHolder)
        assert isinstance(holder.contained_labware["vial_1"], Vial)
        assert deck.resolve("vial_holder.vial_1") == Coordinate3D(x=17.1, y=0.9, z=182.0)
    finally:
        Path(path).unlink(missing_ok=True)


def test_nested_well_plate_in_holder_uses_seat_height_for_a1_z_generation():
    yaml_str = """
labware:
  plate_holder:
    type: well_plate_holder
    name: plate_holder
    location:
      x: 221.75
      y: 78.5
      z: 183.0
    well_plate:
      model_name: panda_96_wellplate
      rows: 2
      columns: 2
      calibration:
        a1:
          x: 221.75
          y: 78.5
        a2:
          x: 230.75
          y: 78.5
      x_offset: 9.0
      y_offset: 9.0
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as handle:
        handle.write(yaml_str)
        path = handle.name

    try:
        deck = load_deck_from_yaml(path)
        holder = deck["plate_holder"]

        assert isinstance(holder, WellPlateHolder)
        assert isinstance(holder.contained_labware["plate"], WellPlate)
        assert deck.resolve("plate_holder.plate") == Coordinate3D(x=221.75, y=78.5, z=188.0)
        assert deck.resolve("plate_holder.plate.A1") == Coordinate3D(x=221.75, y=78.5, z=188.0)
        assert deck.resolve("plate_holder.plate.B2") == Coordinate3D(x=230.75, y=69.5, z=188.0)
    finally:
        Path(path).unlink(missing_ok=True)


def test_deck_yaml_load_name_expands_from_definitions_registry():
    """A deck YAML may reference a definition via `load_name:` and supply only
    the user-specific fields (typically just `location`)."""
    yaml_str = """
labware:
  my_vials:
    load_name: ursa_vial_holder
    location:
      x: 17.1
      y: 132.9
      z: 164.0
  my_plate_holder:
    load_name: ursa_wellplate_holder_conductive
    location:
      x: 50.0
      y: 60.0
      z: 12.0
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as handle:
        handle.write(yaml_str)
        path = handle.name

    try:
        deck = load_deck_from_yaml(path)

        vials = deck["my_vials"]
        assert isinstance(vials, VialHolder)
        assert vials.name == "my_vials"  # defaulted to deck key
        assert vials.length == pytest.approx(36.2)
        assert vials.width == pytest.approx(300.2)
        assert vials.height == pytest.approx(35.1)
        assert vials.labware_seat_height_from_bottom == pytest.approx(18.0)
        assert vials.slot_count == 9
        assert vials.location == Coordinate3D(x=17.1, y=132.9, z=164.0)

        plate_holder = deck["my_plate_holder"]
        assert isinstance(plate_holder, WellPlateHolder)
        assert plate_holder.name == "my_plate_holder"
        assert plate_holder.length == pytest.approx(100.0)
        assert plate_holder.width == pytest.approx(155.0)
        assert plate_holder.height == pytest.approx(14.8)
        assert plate_holder.labware_seat_height_from_bottom == pytest.approx(5.0)
    finally:
        Path(path).unlink(missing_ok=True)


def test_deck_yaml_unknown_load_name_raises_clear_error():
    yaml_str = """
labware:
  broken:
    load_name: no_such_definition
    location: {x: 0.0, y: 0.0, z: 0.0}
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as handle:
        handle.write(yaml_str)
        path = handle.name

    try:
        with pytest.raises(Exception, match="no_such_definition"):
            load_deck_from_yaml(path)
    finally:
        Path(path).unlink(missing_ok=True)


def test_holder_slots_participate_in_bounds_validation():
    gantry = _make_gantry()
    holder = VialHolder(
        name="vial_holder",
        location=Coordinate3D(x=20.0, y=20.0, z=20.0),
        slots={
            "vial_1": LabwareSlot(
                location=Coordinate3D(x=301.0, y=20.0, z=20.0),
                supported_labware_types=("vial",),
            )
        },
    )
    deck = Deck({"vials": holder})

    violations = validate_deck_positions(gantry, deck)

    assert len(violations) == 1
    assert violations[0].labware_key == "vials"
    assert violations[0].position_id == "vial_1"
    assert violations[0].axis == "x"
    assert violations[0].bound_name == "x_max"
