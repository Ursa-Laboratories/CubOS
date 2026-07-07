"""Tests for strict deck YAML loading and labware object mapping."""

import tempfile
from pathlib import Path

import pytest

from pydantic import ValidationError

from deck import (
    LABWARE_YAML_ENTRY_MODELS,
    WellPlate,
    Vial,
    Coordinate3D,
    Deck,
    TipRack,
    Wall,
    derive_wells_preview,
    resolve_load_names,
)
from deck.loader import (
    DeckLoaderError,
    _PlateOrientation,
    _resolve_plate_orientation,
    load_deck_from_yaml,
    load_deck_from_yaml_safe,
)
from deck.yaml_schema import WellPlateYamlEntry, _YamlCalibrationPoints, _YamlPoint3D


# ----- Valid deck YAML fixtures -----

VALID_DECK_ONE_PLATE_ONE_VIAL = """
labware:
  plate_1:
    type: well_plate
    name: opentrons_96_well_20ml
    model_name: opentrons_96_well_20ml
    rows: 8
    columns: 12
    length: 127.71
    width: 85.43
    height: 14.10
    calibration:
      a1:
        x: -10.0
        y: -10.0
        z: -15.0
      a2:
        x: -1.0
        y: -10.0
        z: -15.0
    x_offset: 9.0
    y_offset: 9.0
    capacity_ul: 200.0
    working_volume_ul: 150.0
  vial_1:
    type: vial
    name: standard_vial_rack
    model_name: standard_1_5ml_vial
    height: 66.75
    diameter: 28.0
    location:
      x: -30.0
      y: -40.0
      z: -20.0
    capacity_ul: 1500.0
    working_volume_ul: 1200.0
"""


def test_load_valid_deck_returns_deck_with_labware():
    """Valid deck YAML yields a Deck containing labware keyed by configured names."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(VALID_DECK_ONE_PLATE_ONE_VIAL)
        path = f.name
    try:
        deck = load_deck_from_yaml(path)
        assert isinstance(deck, Deck)
        assert "plate_1" in deck
        assert "vial_1" in deck
        assert len(deck) == 2
        assert isinstance(deck["plate_1"], WellPlate)
        assert isinstance(deck["vial_1"], Vial)
    finally:
        Path(path).unlink(missing_ok=True)


def test_duplicate_yaml_key_in_deck_file_names_file_and_key(tmp_path):
    path = tmp_path / "duplicate_deck.yaml"
    path.write_text(
        """
labware:
  plate:
    type: vial
    name: first
    model_name: vial
    height: 10.0
    diameter: 5.0
    location: {x: 1.0, y: 2.0, z: 3.0}
    capacity_ul: 10.0
    working_volume_ul: 5.0
  plate:
    type: vial
    name: second
    model_name: vial
    height: 10.0
    diameter: 5.0
    location: {x: 4.0, y: 5.0, z: 6.0}
    capacity_ul: 10.0
    working_volume_ul: 5.0
""",
        encoding="utf-8",
    )

    with pytest.raises(Exception) as exc_info:
        load_deck_from_yaml(path)

    message = str(exc_info.value)
    assert str(path) in message
    assert "duplicate YAML key 'plate'" in message


def test_loaded_well_plate_has_derived_wells_and_volume():
    """Loaded WellPlate has correct well count, A1 anchor, and volume fields."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(VALID_DECK_ONE_PLATE_ONE_VIAL)
        path = f.name
    try:
        result = load_deck_from_yaml(path)
        plate = result["plate_1"]
        assert plate.rows == 8
        assert plate.columns == 12
        assert len(plate.wells) == 8 * 12
        assert plate.get_well_center("A1").x == pytest.approx(-10.0)
        assert plate.get_well_center("A1").y == pytest.approx(-10.0)
        assert plate.get_well_center("A1").z == pytest.approx(-15.0)
        assert plate.model_name == "opentrons_96_well_20ml"
        assert plate.capacity_ul == pytest.approx(200.0)
        assert plate.working_volume_ul == pytest.approx(150.0)
    finally:
        Path(path).unlink(missing_ok=True)


def test_public_derive_wells_preview_matches_loader_calibration_logic():
    entry = WellPlateYamlEntry.model_validate({
        "type": "well_plate",
        "name": "preview_plate",
        "rows": 2,
        "columns": 2,
        "calibration": {
            "a1": {"x": 10.0, "y": 20.0, "z": 5.0},
            "a2": {"x": 19.0, "y": 20.0, "z": 5.0},
        },
        "x_offset": 9.0,
        "y_offset": 8.0,
    })

    wells = derive_wells_preview(entry, resolved_z=12.3456)

    assert wells == {
        "A1": Coordinate3D(x=10.0, y=20.0, z=12.346),
        "A2": Coordinate3D(x=19.0, y=20.0, z=12.346),
        "B1": Coordinate3D(x=10.0, y=12.0, z=12.346),
        "B2": Coordinate3D(x=19.0, y=12.0, z=12.346),
    }


def test_public_derive_wells_preview_rejects_bad_orientation():
    entry = WellPlateYamlEntry.model_validate({
        "type": "well_plate",
        "name": "preview_plate",
        "rows": 1,
        "columns": 2,
        "calibration": {
            "a1": {"x": 10.0, "y": 20.0, "z": 5.0},
            "a2": {"x": 18.0, "y": 20.0, "z": 5.0},
        },
        "x_offset": 9.0,
        "y_offset": 8.0,
    })

    with pytest.raises(ValueError, match="A2 must match"):
        derive_wells_preview(entry, resolved_z=5.0)


def test_public_resolve_load_names_expands_definition_defaults():
    raw = {
        "labware": {
            "tiprack": {
                "type": "tip_rack",
                "load_name": "ursa_tip_rack",
                "calibration": {
                    "a1": {"x": 1.0, "y": 2.0, "z": 3.0},
                    "a2": {"x": 10.0, "y": 2.0, "z": 3.0},
                },
                "pickup_z": 4.0,
            }
        }
    }

    resolved = resolve_load_names(raw)

    assert resolved["labware"]["tiprack"]["name"] == "tiprack"
    assert resolved["labware"]["tiprack"]["type"] == "tip_rack"
    assert "load_name" not in resolved["labware"]["tiprack"]


def test_public_resolve_load_names_unknown_definition_raises_clear_error():
    with pytest.raises(DeckLoaderError, match="Unknown `load_name"):
        resolve_load_names({
            "labware": {
                "thing": {
                    "load_name": "missing_definition",
                }
            }
        })


def test_labware_yaml_entry_models_exposes_public_type_mapping():
    assert LABWARE_YAML_ENTRY_MODELS["well_plate"] is WellPlateYamlEntry
    assert LABWARE_YAML_ENTRY_MODELS["vial"].model_fields["diameter"].is_required()
    assert sorted(LABWARE_YAML_ENTRY_MODELS) == [
        "tip_disposal",
        "tip_rack",
        "vial",
        "vial_holder",
        "wall",
        "well_plate",
        "well_plate_holder",
    ]


def test_loaded_vial_has_location_and_volume():
    """Loaded Vial has a single location and volume fields."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(VALID_DECK_ONE_PLATE_ONE_VIAL)
        path = f.name
    try:
        result = load_deck_from_yaml(path)
        vial = result["vial_1"]
        assert vial.get_vial_center().x == pytest.approx(-30.0)
        assert vial.model_name == "standard_1_5ml_vial"
        assert vial.capacity_ul == pytest.approx(1500.0)
        assert vial.working_volume_ul == pytest.approx(1200.0)
    finally:
        Path(path).unlink(missing_ok=True)


def test_vial_location_z_is_direct_deck_frame_z() -> None:
    yaml = """
labware:
  vial_1:
    type: vial
    name: standard_vial_rack
    model_name: standard_1_5ml_vial
    height: 66.75
    diameter: 28.0
    location:
      x: 30.0
      y: 40.0
      z: 30.0
    capacity_ul: 1500.0
    working_volume_ul: 1200.0
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml)
        path = f.name
    try:
        result = load_deck_from_yaml(path, factory_z_travel_mm=80.0)
        vial = result["vial_1"]
        assert vial.location.z == pytest.approx(30.0)
    finally:
        Path(path).unlink(missing_ok=True)


def test_well_plate_calibration_z_is_direct_deck_frame_z() -> None:
    yaml = """
labware:
  plate_1:
    type: well_plate
    name: opentrons_96_well_20ml
    model_name: opentrons_96_well_20ml
    rows: 2
    columns: 2
    length: 127.71
    width: 85.43
    height: 14.10
    calibration:
      a1: { x: 10.0, y: 10.0, z: 15.0 }
      a2: { x: 19.0, y: 10.0, z: 15.0 }
    x_offset: 9.0
    y_offset: 9.0
    capacity_ul: 200.0
    working_volume_ul: 150.0
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml)
        path = f.name
    try:
        result = load_deck_from_yaml(path, factory_z_travel_mm=80.0)
        plate = result["plate_1"]
        assert plate.get_well_center("A1").z == pytest.approx(15.0)
        assert plate.get_well_center("B2").z == pytest.approx(15.0)
    finally:
        Path(path).unlink(missing_ok=True)


def test_raw_z_works_without_factory_z_travel_mm() -> None:
    yaml = """
labware:
  vial_1:
    type: vial
    name: standard_vial_rack
    model_name: standard_1_5ml_vial
    height: 66.75
    diameter: 28.0
    location:
      x: 30.0
      y: 40.0
      z: 20.0
    capacity_ul: 1500.0
    working_volume_ul: 1200.0
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml)
        path = f.name
    try:
        result = load_deck_from_yaml(path)
        vial = result["vial_1"]
        assert vial.location.z == pytest.approx(20.0)
    finally:
        Path(path).unlink(missing_ok=True)


def test_explicit_z_does_not_require_factory_z_travel_mm() -> None:
    yaml = """
labware:
  vial_1:
    type: vial
    name: standard_vial_rack
    model_name: standard_1_5ml_vial
    height: 66.75
    diameter: 28.0
    location:
      x: 30.0
      y: 40.0
      z: 30.0
    capacity_ul: 1500.0
    working_volume_ul: 1200.0
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml)
        path = f.name
    try:
        result = load_deck_from_yaml(path)
        assert result["vial_1"].location.z == pytest.approx(30.0)
    finally:
        Path(path).unlink(missing_ok=True)


# ----- Calibration anchor as the single source of truth for surface Z -----


def test_well_plate_missing_calibration_z_raises():
    """The legacy ``height`` z-hint shorthand was removed when the
    dimensional ``height`` field took over the name. A well plate that
    omits ``calibration.a1.z`` must raise a clear error pointing at the
    calibration anchor."""
    yaml = """
labware:
  plate_1:
    type: well_plate
    name: small
    model_name: small
    rows: 2
    columns: 2
    length: 20.0
    width: 20.0
    height: 10.0
    calibration:
      a1: { x: 0.0, y: 0.0 }
      a2: { x: 10.0, y: 0.0 }
    x_offset: 9.0
    y_offset: 9.0
"""
    path = _write_yaml = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
    path.write(yaml); path.close()
    try:
        with pytest.raises(ValueError, match="calibration anchor"):
            load_deck_from_yaml(path.name)
    finally:
        Path(path.name).unlink(missing_ok=True)


def test_vial_missing_location_z_raises():
    yaml = """
labware:
  vial_1:
    type: vial
    name: standard_vial_rack
    model_name: standard_1_5ml_vial
    height: 66.75
    diameter: 28.0
    location:
      x: 30.0
      y: 40.0
    capacity_ul: 1500.0
    working_volume_ul: 1200.0
"""
    path = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
    path.write(yaml); path.close()
    try:
        with pytest.raises(ValueError, match="calibration anchor"):
            load_deck_from_yaml(path.name)
    finally:
        Path(path.name).unlink(missing_ok=True)


# ----- Two-point calibration orientations -----

def test_calibration_horizontal_increasing_columns():
    """A2.x > A1.x, A2.y == A1.y: columns along +X."""
    yaml = """
labware:
  p:
    type: well_plate
    name: small
    model_name: small
    rows: 2
    columns: 2
    length: 20.0
    width: 20.0
    height: 10.0
    calibration:
      a1: { x: 0.0, y: 0.0, z: -5.0 }
      a2: { x: 10.0, y: 0.0, z: -5.0 }
    x_offset: 10.0
    y_offset: 8.0
    capacity_ul: 100.0
    working_volume_ul: 80.0
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml)
        path = f.name
    try:
        result = load_deck_from_yaml(path)
        plate = result["p"]
        assert plate.get_well_center("A1").x == pytest.approx(0.0)
        assert plate.get_well_center("A1").y == pytest.approx(0.0)
        assert plate.get_well_center("A2").x == pytest.approx(10.0)
        assert plate.get_well_center("A2").y == pytest.approx(0.0)
        assert plate.get_well_center("B1").x == pytest.approx(0.0)
        assert plate.get_well_center("B1").y == pytest.approx(-8.0)
    finally:
        Path(path).unlink(missing_ok=True)


def test_explicit_row_direction_positive_overrides_horizontal_default():
    yaml = """
labware:
  p:
    type: well_plate
    name: small
    model_name: small
    rows: 2
    columns: 2
    calibration:
      a1: { x: 0.0, y: 0.0, z: 5.0 }
      a2: { x: 10.0, y: 0.0, z: 5.0 }
    x_offset: 10.0
    y_offset: 8.0
    row_direction: positive
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml)
        path = f.name
    try:
        plate = load_deck_from_yaml(path)["p"]
        assert plate.get_well_center("B1").x == pytest.approx(0.0)
        assert plate.get_well_center("B1").y == pytest.approx(8.0)
    finally:
        Path(path).unlink(missing_ok=True)


def test_explicit_row_direction_negative_overrides_vertical_default():
    yaml = """
labware:
  p:
    type: well_plate
    name: small
    model_name: small
    rows: 2
    columns: 2
    calibration:
      a1: { x: 0.0, y: 0.0, z: 5.0 }
      a2: { x: 0.0, y: 8.0, z: 5.0 }
    x_offset: 10.0
    y_offset: 8.0
    row_direction: negative
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml)
        path = f.name
    try:
        plate = load_deck_from_yaml(path)["p"]
        assert plate.get_well_center("B1").x == pytest.approx(-10.0)
        assert plate.get_well_center("B1").y == pytest.approx(0.0)
    finally:
        Path(path).unlink(missing_ok=True)


def test_calibration_horizontal_decreasing_columns():
    """A2.x < A1.x, A2.y == A1.y: A2 determines columns along -X."""
    yaml = """
labware:
  p:
    type: well_plate
    name: small
    model_name: small
    rows: 2
    columns: 2
    length: 20.0
    width: 20.0
    height: 10.0
    calibration:
      a1: { x: 10.0, y: 0.0, z: -5.0 }
      a2: { x: 0.0, y: 0.0, z: -5.0 }
    x_offset: 10.0
    y_offset: 8.0
    capacity_ul: 100.0
    working_volume_ul: 80.0
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml)
        path = f.name
    try:
        result = load_deck_from_yaml(path)
        plate = result["p"]
        assert plate.get_well_center("A1").x == pytest.approx(10.0)
        assert plate.get_well_center("A2").x == pytest.approx(0.0)
        assert plate.get_well_center("A2").y == pytest.approx(0.0)
    finally:
        Path(path).unlink(missing_ok=True)


@pytest.mark.parametrize("x_offset_literal", ["+10.0", "10.0"])
def test_calibration_column_sign_comes_from_a1_a2_not_x_offset_sign(x_offset_literal):
    """Positive and unsigned X offsets allow A1/A2 to set column sign."""
    yaml = f"""
labware:
  p:
    type: well_plate
    name: small
    model_name: small
    rows: 2
    columns: 2
    length: 20.0
    width: 20.0
    height: 10.0
    calibration:
      a1: {{ x: 10.0, y: 0.0, z: -5.0 }}
      a2: {{ x: 0.0, y: 0.0, z: -5.0 }}
    x_offset: {x_offset_literal}
    y_offset: 8.0
    capacity_ul: 100.0
    working_volume_ul: 80.0
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml)
        path = f.name
    try:
        result = load_deck_from_yaml(path)
        plate = result["p"]
        assert plate.get_well_center("A1").x == pytest.approx(10.0)
        assert plate.get_well_center("A2").x == pytest.approx(0.0)
        assert plate.get_well_center("A2").y == pytest.approx(0.0)
    finally:
        Path(path).unlink(missing_ok=True)


def test_calibration_vertical_increasing_rows():
    """A2.y > A1.y, A2.x == A1.x: column direction is Y; A2 at (a1.x, a1.y + y_offset)."""
    yaml = """
labware:
  p:
    type: well_plate
    name: small
    model_name: small
    rows: 2
    columns: 2
    length: 20.0
    width: 20.0
    height: 10.0
    calibration:
      a1: { x: 0.0, y: 0.0, z: -5.0 }
      a2: { x: 0.0, y: 8.0, z: -5.0 }
    x_offset: 10.0
    y_offset: 8.0
    capacity_ul: 100.0
    working_volume_ul: 80.0
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml)
        path = f.name
    try:
        result = load_deck_from_yaml(path)
        plate = result["p"]
        assert plate.get_well_center("A1").x == pytest.approx(0.0)
        assert plate.get_well_center("A1").y == pytest.approx(0.0)
        assert plate.get_well_center("A2").x == pytest.approx(0.0)
        assert plate.get_well_center("A2").y == pytest.approx(8.0)
        assert plate.get_well_center("B1").x == pytest.approx(10.0)
        assert plate.get_well_center("B1").y == pytest.approx(0.0)
    finally:
        Path(path).unlink(missing_ok=True)


def test_calibration_vertical_decreasing_rows():
    """A2.y < A1.y, A2.x == A1.x."""
    yaml = """
labware:
  p:
    type: well_plate
    name: small
    model_name: small
    rows: 2
    columns: 2
    length: 20.0
    width: 20.0
    height: 10.0
    calibration:
      a1: { x: 0.0, y: 8.0, z: -5.0 }
      a2: { x: 0.0, y: 0.0, z: -5.0 }
    x_offset: 10.0
    y_offset: 8.0
    capacity_ul: 100.0
    working_volume_ul: 80.0
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml)
        path = f.name
    try:
        result = load_deck_from_yaml(path)
        plate = result["p"]
        assert plate.get_well_center("A1").y == pytest.approx(8.0)
        assert plate.get_well_center("A2").y == pytest.approx(0.0)
        assert plate.get_well_center("A2").x == pytest.approx(0.0)
    finally:
        Path(path).unlink(missing_ok=True)


@pytest.mark.parametrize("y_offset_literal", ["+8.0", "8.0"])
def test_calibration_column_sign_comes_from_a1_a2_not_y_offset_sign(y_offset_literal):
    """Positive and unsigned Y offsets allow A1/A2 to set column sign."""
    yaml = f"""
labware:
  p:
    type: well_plate
    name: small
    model_name: small
    rows: 2
    columns: 2
    length: 20.0
    width: 20.0
    height: 10.0
    calibration:
      a1: {{ x: 0.0, y: 8.0, z: -5.0 }}
      a2: {{ x: 0.0, y: 0.0, z: -5.0 }}
    x_offset: 10.0
    y_offset: {y_offset_literal}
    capacity_ul: 100.0
    working_volume_ul: 80.0
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml)
        path = f.name
    try:
        result = load_deck_from_yaml(path)
        plate = result["p"]
        assert plate.get_well_center("A1").y == pytest.approx(8.0)
        assert plate.get_well_center("A2").x == pytest.approx(0.0)
        assert plate.get_well_center("A2").y == pytest.approx(0.0)
    finally:
        Path(path).unlink(missing_ok=True)


def test_calibration_diagonal_fails():
    """A1 and A2 with both x and y different (diagonal) must fail."""
    yaml = """
labware:
  p:
    type: well_plate
    name: small
    model_name: small
    rows: 2
    columns: 2
    length: 20.0
    width: 20.0
    height: 10.0
    calibration:
      a1: { x: 0.0, y: 0.0, z: -5.0 }
      a2: { x: 10.0, y: 5.0, z: -5.0 }
    x_offset: 10.0
    y_offset: 8.0
    capacity_ul: 100.0
    working_volume_ul: 80.0
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml)
        path = f.name
    try:
        with pytest.raises(ValidationError, match="axis.aligned|diagonal|orientation"):
            load_deck_from_yaml(path)
    finally:
        Path(path).unlink(missing_ok=True)


def test_safe_loader_returns_clean_error_message():
    """Safe loader raises DeckLoaderError with concise fix guidance."""
    yaml = """
labware:
  p:
    type: well_plate
    name: small
    model_name: small
    rows: 2
    columns: 2
    length: 20.0
    width: 20.0
    height: 10.0
    calibration:
      a1: { x: 0.0, y: 0.0, z: -5.0 }
      a2: { x: 10.0, y: 5.0, z: -5.0 }
    x_offset: 10.0
    y_offset: 8.0
    capacity_ul: 100.0
    working_volume_ul: 80.0
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml)
        path = f.name
    try:
        with pytest.raises(DeckLoaderError) as exc_info:
            load_deck_from_yaml_safe(path)
        message = str(exc_info.value)
        assert message.startswith("❌")
        assert "How to fix:" in message
        assert "axis-aligned" in message or "shares either the same x or the same y" in message
    finally:
        Path(path).unlink(missing_ok=True)


def test_safe_loader_yaml_parse_error_has_clean_message():
    """Safe loader reports YAML parse issues without traceback noise."""
    bad_yaml = "labware:\n  plate_1:\n    type: well_plate\n    calibration: [\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(bad_yaml)
        path = f.name
    try:
        with pytest.raises(DeckLoaderError) as exc_info:
            load_deck_from_yaml_safe(path)
        message = str(exc_info.value)
        assert message.startswith("❌")
        assert "parse error" in message.lower()
        assert "How to fix:" in message
    finally:
        Path(path).unlink(missing_ok=True)


def test_safe_loader_missing_file_has_clean_message():
    """Safe loader reports missing-file errors as DeckLoaderError."""
    missing_path = "/tmp/this_file_does_not_exist_12345.yaml"
    with pytest.raises(DeckLoaderError) as exc_info:
        load_deck_from_yaml_safe(missing_path)
    message = str(exc_info.value)
    assert message.startswith("❌")
    assert "deck loader error" in message.lower()
    assert "How to fix:" in message


def test_zero_offsets_fail_schema_validation():
    """x/y offsets must be positive in well plate schema."""
    yaml = """
labware:
  p:
    type: well_plate
    name: x
    model_name: x
    rows: 8
    columns: 12
    length: 127.71
    width: 85.43
    height: 14.10
    calibration:
      a1: { x: 0.0, y: 0.0, z: -15.0 }
      a2: { x: 9.0, y: 0.0, z: -15.0 }
    x_offset: 0.0
    y_offset: 9.0
    capacity_ul: 200.0
    working_volume_ul: 150.0
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml)
        path = f.name
    try:
        with pytest.raises(ValidationError):
            load_deck_from_yaml(path)
    finally:
        Path(path).unlink(missing_ok=True)


@pytest.mark.parametrize(
    ("x_offset", "y_offset"),
    [(-9.0, 9.0), (9.0, -9.0)],
)
def test_negative_offsets_fail_schema_validation(x_offset, y_offset):
    """Offset fields are spacing magnitudes and must not be negative."""
    yaml = f"""
labware:
  p:
    type: well_plate
    name: x
    model_name: x
    rows: 8
    columns: 12
    length: 127.71
    width: 85.43
    height: 14.10
    calibration:
      a1: {{ x: 0.0, y: 0.0, z: -15.0 }}
      a2: {{ x: 9.0, y: 0.0, z: -15.0 }}
    x_offset: {x_offset}
    y_offset: {y_offset}
    capacity_ul: 200.0
    working_volume_ul: 150.0
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml)
        path = f.name
    try:
        with pytest.raises(ValidationError, match="greater than 0"):
            load_deck_from_yaml(path)
    finally:
        Path(path).unlink(missing_ok=True)


def test_calibration_identical_points_fails():
    """A1 and A2 identical must fail."""
    yaml = """
labware:
  p:
    type: well_plate
    name: small
    model_name: small
    rows: 2
    columns: 2
    length: 20.0
    width: 20.0
    height: 10.0
    calibration:
      a1: { x: 0.0, y: 0.0, z: -5.0 }
      a2: { x: 0.0, y: 0.0, z: -5.0 }
    x_offset: 10.0
    y_offset: 8.0
    capacity_ul: 100.0
    working_volume_ul: 80.0
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml)
        path = f.name
    try:
        with pytest.raises(ValidationError, match="identical|degenerate|same"):
            load_deck_from_yaml(path)
    finally:
        Path(path).unlink(missing_ok=True)


# ----- Missing required fields -----

def test_missing_top_level_labware_fails():
    """Deck YAML without 'labware' key fails."""
    yaml = "other: 1\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml)
        path = f.name
    try:
        with pytest.raises(ValidationError):
            load_deck_from_yaml(path)
    finally:
        Path(path).unlink(missing_ok=True)


def test_missing_well_plate_required_field_fails():
    """Well plate entry missing e.g. 'rows' or 'calibration' fails."""
    yaml = """
labware:
  p:
    type: well_plate
    name: x
    model_name: x
    columns: 12
    length: 127.71
    width: 85.43
    height: 14.10
    calibration:
      a1: { x: 0.0, y: 0.0, z: -15.0 }
      a2: { x: 9.0, y: 0.0, z: -15.0 }
    x_offset: 9.0
    y_offset: 9.0
    capacity_ul: 200.0
    working_volume_ul: 150.0
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml)
        path = f.name
    try:
        with pytest.raises(ValidationError):
            load_deck_from_yaml(path)
    finally:
        Path(path).unlink(missing_ok=True)


def test_missing_vial_required_field_fails():
    """Vial entry missing e.g. 'location' fails."""
    yaml = """
labware:
  v:
    type: vial
    name: v1
    model_name: m1
    height: 66.0
    diameter: 28.0
    capacity_ul: 1500.0
    working_volume_ul: 1200.0
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml)
        path = f.name
    try:
        with pytest.raises(ValidationError):
            load_deck_from_yaml(path)
    finally:
        Path(path).unlink(missing_ok=True)


# ----- Extra fields -----

def test_extra_top_level_field_fails():
    """Unknown top-level key in deck YAML fails."""
    yaml = """
labware: {}
gantry: {}
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml)
        path = f.name
    try:
        with pytest.raises(ValidationError):
            load_deck_from_yaml(path)
    finally:
        Path(path).unlink(missing_ok=True)


def test_extra_labware_entry_field_fails():
    """Unknown key inside a labware entry fails."""
    yaml = """
labware:
  p:
    type: well_plate
    name: x
    model_name: x
    rows: 8
    columns: 12
    length: 127.71
    width: 85.43
    height: 14.10
    calibration:
      a1: { x: 0.0, y: 0.0, z: -15.0 }
      a2: { x: 9.0, y: 0.0, z: -15.0 }
    x_offset: 9.0
    y_offset: 9.0
    capacity_ul: 200.0
    working_volume_ul: 150.0
    unknown_field: 1
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml)
        path = f.name
    try:
        with pytest.raises(ValidationError):
            load_deck_from_yaml(path)
    finally:
        Path(path).unlink(missing_ok=True)


def test_labware_key_with_dot_is_rejected_at_load_time():
    yaml = """
labware:
  plate.1:
    type: vial
    name: dotted
    model_name: vial
    height: 10.0
    diameter: 5.0
    location: {x: 1.0, y: 2.0, z: 3.0}
    capacity_ul: 10.0
    working_volume_ul: 5.0
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml)
        path = f.name
    try:
        with pytest.raises(ValidationError, match="cannot contain"):
            load_deck_from_yaml(path)
    finally:
        Path(path).unlink(missing_ok=True)


# ----- Type coercion and invalid types -----

def test_numeric_string_coercion_allowed():
    """Numeric strings for numbers (e.g. rows: '8') are coerced where valid."""
    yaml = """
labware:
  p:
    type: well_plate
    name: x
    model_name: x
    rows: "8"
    columns: "12"
    length: "127.71"
    width: "85.43"
    height: "14.10"
    calibration:
      a1: { x: 0.0, y: 0.0, z: -15.0 }
      a2: { x: 9.0, y: 0.0, z: -15.0 }
    x_offset: 9.0
    y_offset: 9.0
    capacity_ul: 200.0
    working_volume_ul: 150.0
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml)
        path = f.name
    try:
        result = load_deck_from_yaml(path)
        assert result["p"].rows == 8
        assert result["p"].columns == 12
    finally:
        Path(path).unlink(missing_ok=True)


def test_non_coercible_type_fails():
    """rows: 'eight' (non-numeric string) fails."""
    yaml = """
labware:
  p:
    type: well_plate
    name: x
    model_name: x
    rows: eight
    columns: 12
    length: 127.71
    width: 85.43
    height: 14.10
    calibration:
      a1: { x: 0.0, y: 0.0, z: -15.0 }
      a2: { x: 9.0, y: 0.0, z: -15.0 }
    x_offset: 9.0
    y_offset: 9.0
    capacity_ul: 200.0
    working_volume_ul: 150.0
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml)
        path = f.name
    try:
        with pytest.raises(ValidationError):
            load_deck_from_yaml(path)
    finally:
        Path(path).unlink(missing_ok=True)


# ----- Volume validation -----

def test_working_volume_exceeds_capacity_fails():
    """working_volume_ul > capacity_ul must fail."""
    yaml = """
labware:
  p:
    type: well_plate
    name: x
    model_name: x
    rows: 8
    columns: 12
    length: 127.71
    width: 85.43
    height: 14.10
    calibration:
      a1: { x: 0.0, y: 0.0, z: -15.0 }
      a2: { x: 9.0, y: 0.0, z: -15.0 }
    x_offset: 9.0
    y_offset: 9.0
    capacity_ul: 200.0
    working_volume_ul: 250.0
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml)
        path = f.name
    try:
        with pytest.raises(ValidationError):
            load_deck_from_yaml(path)
    finally:
        Path(path).unlink(missing_ok=True)


def test_negative_capacity_fails():
    """capacity_ul <= 0 fails."""
    yaml = """
labware:
  p:
    type: well_plate
    name: x
    model_name: x
    rows: 8
    columns: 12
    length: 127.71
    width: 85.43
    height: 14.10
    calibration:
      a1: { x: 0.0, y: 0.0, z: -15.0 }
      a2: { x: 9.0, y: 0.0, z: -15.0 }
    x_offset: 9.0
    y_offset: 9.0
    capacity_ul: 0.0
    working_volume_ul: 0.0
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml)
        path = f.name
    try:
        with pytest.raises(ValidationError):
            load_deck_from_yaml(path)
    finally:
        Path(path).unlink(missing_ok=True)


# ----- Optional fields -----

def test_well_plate_without_geometry_and_volume():
    """Well plate with only required fields (no L/W/H, no capacity/volume) loads fine."""
    yaml_str = """
labware:
  p:
    type: well_plate
    name: minimal plate
    model_name: custom
    rows: 2
    columns: 3
    calibration:
      a1: { x: 10.0, y: 20.0, z: -5.0 }
      a2: { x: 19.0, y: 20.0, z: -5.0 }
    x_offset: 9.0
    y_offset: 9.0
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_str)
        path = f.name
    try:
        deck = load_deck_from_yaml(path)
        plate = deck.labware["p"]
        assert isinstance(plate, WellPlate)
        assert plate.length is None
        assert plate.width is None
        # height is the plate's physical outer dimension and is None
        # when the YAML omits it (this fixture omits it). The deck-frame
        # surface Z lives on each well's coordinate.
        assert plate.height is None
        assert plate.wells["A1"].z == -5.0
        assert plate.capacity_ul is None
        assert plate.working_volume_ul is None
        assert len(plate.wells) == 6
    finally:
        Path(path).unlink(missing_ok=True)


def test_well_plate_partial_volume_ok():
    """Specifying only capacity_ul without working_volume_ul is valid."""
    yaml_str = """
labware:
  p:
    type: well_plate
    name: partial vol
    model_name: custom
    rows: 1
    columns: 2
    calibration:
      a1: { x: 0.0, y: 0.0, z: 0.0 }
      a2: { x: 9.0, y: 0.0, z: 0.0 }
    x_offset: 9.0
    y_offset: 9.0
    capacity_ul: 200.0
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_str)
        path = f.name
    try:
        deck = load_deck_from_yaml(path)
        plate = deck.labware["p"]
        assert plate.capacity_ul == 200.0
        assert plate.working_volume_ul is None
    finally:
        Path(path).unlink(missing_ok=True)


# ----- Empty labware -----

def test_empty_labware_dict_allowed():
    """Deck with labware: {} is valid and returns empty Deck."""
    yaml = "labware: {}\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml)
        path = f.name
    try:
        deck = load_deck_from_yaml(path)
        assert isinstance(deck, Deck)
        assert len(deck) == 0
    finally:
        Path(path).unlink(missing_ok=True)


# ----- _resolve_plate_orientation unit tests -----


def _make_entry(
    a1_x=0.0, a1_y=0.0, a2_x=10.0, a2_y=0.0,
    x_offset=10.0, y_offset=8.0, z=-5.0,
) -> WellPlateYamlEntry:
    """Build a minimal WellPlateYamlEntry for orientation tests."""
    return WellPlateYamlEntry(
        name="t", model_name="t",
        rows=2, columns=2,
        length=20.0, width=20.0, height=10.0,
        calibration=_YamlCalibrationPoints(
            a1=_YamlPoint3D(x=a1_x, y=a1_y, z=z),
            a2=_YamlPoint3D(x=a2_x, y=a2_y, z=z),
        ),
        x_offset=x_offset, y_offset=y_offset,
        capacity_ul=100.0, working_volume_ul=80.0,
    )


class TestResolvePlateOrientation:

    def test_horizontal_columns_along_x(self):
        entry = _make_entry(a1_x=0.0, a1_y=0.0, a2_x=10.0, a2_y=0.0,
                            x_offset=10.0, y_offset=8.0)
        orient = _resolve_plate_orientation(entry)
        assert orient == _PlateOrientation(
            col_delta_x=10.0, col_delta_y=0.0,
            row_delta_x=0.0, row_delta_y=-8.0,
        )

    def test_explicit_positive_row_direction_for_horizontal_columns(self):
        entry = _make_entry(a1_x=0.0, a1_y=0.0, a2_x=10.0, a2_y=0.0)
        entry.row_direction = "positive"
        orient = _resolve_plate_orientation(entry)
        assert orient == _PlateOrientation(
            col_delta_x=10.0, col_delta_y=0.0,
            row_delta_x=0.0, row_delta_y=8.0,
        )

    def test_vertical_columns_along_y(self):
        entry = _make_entry(a1_x=0.0, a1_y=0.0, a2_x=0.0, a2_y=8.0,
                            x_offset=10.0, y_offset=8.0)
        orient = _resolve_plate_orientation(entry)
        assert orient == _PlateOrientation(
            col_delta_x=0.0, col_delta_y=8.0,
            row_delta_x=10.0, row_delta_y=0.0,
        )

    def test_explicit_negative_row_direction_for_vertical_columns(self):
        entry = _make_entry(a1_x=0.0, a1_y=0.0, a2_x=0.0, a2_y=8.0)
        entry.row_direction = "negative"
        orient = _resolve_plate_orientation(entry)
        assert orient == _PlateOrientation(
            col_delta_x=0.0, col_delta_y=8.0,
            row_delta_x=-10.0, row_delta_y=0.0,
        )

    def test_negative_offsets_fail_schema_validation(self):
        with pytest.raises(ValidationError, match="greater than 0"):
            _make_entry(a1_x=10.0, a1_y=0.0, a2_x=0.0, a2_y=0.0,
                        x_offset=-10.0, y_offset=8.0)
        with pytest.raises(ValidationError, match="greater than 0"):
            _make_entry(a1_x=10.0, a1_y=0.0, a2_x=0.0, a2_y=0.0,
                        x_offset=10.0, y_offset=-8.0)

    def test_negative_x_column_step_allows_positive_offset_magnitude(self):
        entry = _make_entry(a1_x=10.0, a1_y=0.0, a2_x=0.0, a2_y=0.0,
                            x_offset=10.0, y_offset=8.0)
        orient = _resolve_plate_orientation(entry)
        assert orient.col_delta_x == pytest.approx(-10.0)
        assert orient.col_delta_y == pytest.approx(0.0)

    def test_negative_y_column_step(self):
        entry = _make_entry(a1_x=0.0, a1_y=8.0, a2_x=0.0, a2_y=0.0,
                            x_offset=10.0, y_offset=8.0)
        orient = _resolve_plate_orientation(entry)
        assert orient.col_delta_y == pytest.approx(-8.0)
        assert orient.col_delta_x == pytest.approx(0.0)

    def test_negative_y_column_step_allows_positive_offset_magnitude(self):
        entry = _make_entry(a1_x=0.0, a1_y=8.0, a2_x=0.0, a2_y=0.0,
                            x_offset=10.0, y_offset=8.0)
        orient = _resolve_plate_orientation(entry)
        assert orient.col_delta_y == pytest.approx(-8.0)
        assert orient.col_delta_x == pytest.approx(0.0)

    def test_mismatched_x_offset_raises(self):
        entry = _make_entry(a1_x=0.0, a1_y=0.0, a2_x=10.0, a2_y=0.0,
                            x_offset=5.0, y_offset=8.0)
        with pytest.raises(ValueError, match="delta x magnitude must equal x_offset magnitude"):
            _resolve_plate_orientation(entry)

    def test_mismatched_y_offset_raises(self):
        entry = _make_entry(a1_x=0.0, a1_y=0.0, a2_x=0.0, a2_y=8.0,
                            x_offset=10.0, y_offset=4.0)
        with pytest.raises(ValueError, match="delta y magnitude must equal y_offset magnitude"):
            _resolve_plate_orientation(entry)

    def test_returns_frozen_dataclass(self):
        entry = _make_entry()
        orient = _resolve_plate_orientation(entry)
        assert isinstance(orient, _PlateOrientation)
        with pytest.raises(AttributeError):
            orient.col_delta_x = 99.0


# ----- TipRack dimension forwarding -----

TIPRACK_WITH_EXPLICIT_DIMS = """
labware:
  rack:
    type: tip_rack
    name: test_rack
    rows: 1
    columns: 2
    length: 130.0
    width: 5.0
    height: 40.0
    pickup_z: 30.0
    tip_length: 59.3
    calibration:
      a1:
        x: 10.0
        y: 50.0
      a2:
        x: 110.0
        y: 50.0
    x_offset: 100.0
    y_offset: 1.0
"""

TIPRACK_WITHOUT_EXPLICIT_DIMS = """
labware:
  rack:
    type: tip_rack
    name: test_rack
    rows: 1
    columns: 2
    pickup_z: 30.0
    tip_length: 59.3
    calibration:
      a1:
        x: 10.0
        y: 50.0
      a2:
        x: 110.0
        y: 50.0
    x_offset: 100.0
    y_offset: 1.0
"""


class TestTipRackDimensionForwarding:

    def test_explicit_dimensions_preserved(self):
        """YAML-specified length/width/height must not be overridden by auto-derivation."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(TIPRACK_WITH_EXPLICIT_DIMS)
            path = f.name
        try:
            deck = load_deck_from_yaml(path)
            rack = deck["rack"]
            assert isinstance(rack, TipRack)
            assert rack.length == pytest.approx(130.0)
            assert rack.width == pytest.approx(5.0)
            assert rack.height == pytest.approx(40.0)
        finally:
            Path(path).unlink(missing_ok=True)

    def test_omitted_dimensions_auto_derived(self):
        """When dimensions are omitted, TipRack should auto-derive from tip positions."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(TIPRACK_WITHOUT_EXPLICIT_DIMS)
            path = f.name
        try:
            deck = load_deck_from_yaml(path)
            rack = deck["rack"]
            assert isinstance(rack, TipRack)
            # Auto-derived: length from tip spread (110-10=100), width clamped to 1.0
            assert rack.length == pytest.approx(100.0)
            assert rack.width == pytest.approx(1.0)
            # height auto-derives to 1.0 when drop_z is not provided
            assert rack.height == pytest.approx(1.0)
            assert rack.tip_length == pytest.approx(59.3)
        finally:
            Path(path).unlink(missing_ok=True)


# ----- Wall labware -----

VALID_WALL = """
labware:
  front_wall:
    type: wall
    name: front_wall
    corner_1: { x: 96.0, y: 155.0, z: 0.0 }
    corner_2: { x: 226.0, y: 160.0, z: 40.0 }
"""


class TestWallLabware:

    def test_wall_loads_with_correct_corners(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(VALID_WALL)
            path = f.name
        try:
            deck = load_deck_from_yaml(path)
            wall = deck["front_wall"]
            assert isinstance(wall, Wall)
            assert wall.corner_1.x == pytest.approx(96.0)
            assert wall.corner_1.y == pytest.approx(155.0)
            assert wall.corner_1.z == pytest.approx(0.0)
            assert wall.corner_2.x == pytest.approx(226.0)
            assert wall.corner_2.y == pytest.approx(160.0)
            assert wall.corner_2.z == pytest.approx(40.0)
        finally:
            Path(path).unlink(missing_ok=True)

    def test_wall_derives_dimensions_from_corners(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(VALID_WALL)
            path = f.name
        try:
            deck = load_deck_from_yaml(path)
            wall = deck["front_wall"]
            assert wall.length == pytest.approx(130.0)
            assert wall.width == pytest.approx(5.0)
            assert wall.height == pytest.approx(40.0)
        finally:
            Path(path).unlink(missing_ok=True)

    def test_wall_bounding_box_properties(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(VALID_WALL)
            path = f.name
        try:
            deck = load_deck_from_yaml(path)
            wall = deck["front_wall"]
            assert wall.x_min == pytest.approx(96.0)
            assert wall.x_max == pytest.approx(226.0)
            assert wall.y_min == pytest.approx(155.0)
            assert wall.y_max == pytest.approx(160.0)
            assert wall.z_min == pytest.approx(0.0)
            assert wall.z_max == pytest.approx(40.0)
        finally:
            Path(path).unlink(missing_ok=True)

    def test_wall_iter_positions_returns_corners(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(VALID_WALL)
            path = f.name
        try:
            deck = load_deck_from_yaml(path)
            wall = deck["front_wall"]
            positions = wall.iter_positions()
            assert "min" in positions
            assert "max" in positions
            assert positions["min"].x == pytest.approx(96.0)
            assert positions["max"].x == pytest.approx(226.0)
        finally:
            Path(path).unlink(missing_ok=True)

    def test_wall_inverted_corners_fails(self):
        yaml_str = """
labware:
  bad_wall:
    type: wall
    name: bad_wall
    corner_1: { x: 200.0, y: 50.0, z: 0.0 }
    corner_2: { x: 100.0, y: 55.0, z: 40.0 }
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_str)
            path = f.name
        try:
            with pytest.raises(Exception, match="corner_1.x must be < corner_2.x"):
                load_deck_from_yaml(path)
        finally:
            Path(path).unlink(missing_ok=True)

    def test_wall_missing_corner_z_has_actionable_message(self):
        yaml_str = """
labware:
  bad_wall:
    type: wall
    name: bad_wall
    corner_1: { x: 10.0, y: 20.0 }
    corner_2: { x: 110.0, y: 25.0 }
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_str)
            path = f.name
        try:
            with pytest.raises(ValidationError) as exc_info:
                load_deck_from_yaml(path)
            message = str(exc_info.value)
            assert "corner_1.z" in message
            assert "corner_2.z" in message
            assert "explicit Z" in message
        finally:
            Path(path).unlink(missing_ok=True)

    def test_wall_rejects_extra_fields(self):
        yaml_str = """
labware:
  bad_wall:
    type: wall
    name: bad_wall
    corner_1: { x: 10.0, y: 20.0, z: 0.0 }
    corner_2: { x: 110.0, y: 25.0, z: 40.0 }
    slots:
      s1:
        location: { x: 15.0, y: 25.0, z: 5.0 }
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_str)
            path = f.name
        try:
            with pytest.raises(Exception):
                load_deck_from_yaml(path)
        finally:
            Path(path).unlink(missing_ok=True)


# ----- well_depth tests -----

WELL_DEPTH_DECK_YAML = """
labware:
  plate_1:
    type: well_plate
    name: deep_well_test
    rows: 8
    columns: 12
    height: 14.35
    well_depth: 10.67
    calibration:
      a1: { x: 10.0, y: 10.0, z: 25.9 }
      a2: { x: 19.0, y: 10.0, z: 25.9 }
    x_offset: 9.0
    y_offset: 9.0
"""


def test_well_plate_carries_well_depth_to_plate_object():
    """The plate definition's inside-floor depth must reach the WellPlate
    object so analysis pipelines can compute sample thickness from a1.z
    rather than dragging a manual `well_bottom_z` knob in user configs.
    """
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(WELL_DEPTH_DECK_YAML)
        path = f.name
    try:
        deck = load_deck_from_yaml(path)
        plate = deck["plate_1"]
        assert plate.well_depth == pytest.approx(10.67)
        # well floor (where the sample sits) is a1.z minus inside depth.
        rim_z = plate.get_well_center("A1").z
        assert rim_z - plate.well_depth == pytest.approx(15.23)
    finally:
        Path(path).unlink(missing_ok=True)


def test_well_plate_well_depth_is_optional_default_none():
    """Existing deck YAMLs that don't declare `well_depth` keep loading."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(VALID_DECK_ONE_PLATE_ONE_VIAL)
        path = f.name
    try:
        deck = load_deck_from_yaml(path)
        plate = deck["plate_1"]
        assert plate.well_depth is None
    finally:
        Path(path).unlink(missing_ok=True)


def test_well_plate_well_depth_negative_is_rejected():
    """Strictly negative inside depth is nonsensical and must fail."""
    bad_yaml = WELL_DEPTH_DECK_YAML.replace("well_depth: 10.67", "well_depth: -1.0")
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(bad_yaml)
        path = f.name
    try:
        with pytest.raises(ValidationError, match="well_depth"):
            load_deck_from_yaml(path)
    finally:
        Path(path).unlink(missing_ok=True)


def test_well_plate_well_depth_zero_is_rejected():
    """Boundary case: `gt=0` (not `ge=0`) means zero must also fail.

    Pinning the boundary explicitly so `gt=0 -> ge=0` regressions are caught.
    """
    bad_yaml = WELL_DEPTH_DECK_YAML.replace("well_depth: 10.67", "well_depth: 0")
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(bad_yaml)
        path = f.name
    try:
        with pytest.raises(ValidationError, match="well_depth"):
            load_deck_from_yaml(path)
    finally:
        Path(path).unlink(missing_ok=True)


def test_well_plate_well_depth_cannot_exceed_height():
    """Inside depth must fit within outer plate height.

    Catches the realistic miscalibration bug (e.g. swapped values) that the
    `gt=0` per-field check alone would let through. Uses a YAML that sets a
    sensible outer `height` and a clearly-too-large `well_depth`.
    """
    bad_yaml = WELL_DEPTH_DECK_YAML.replace("well_depth: 10.67", "well_depth: 50.0")
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(bad_yaml)
        path = f.name
    try:
        with pytest.raises(ValidationError, match=r"well_depth.*height"):
            load_deck_from_yaml(path)
    finally:
        Path(path).unlink(missing_ok=True)


def test_well_plate_direct_construction_rejects_negative_well_depth():
    """The runtime `WellPlate` model also enforces positivity, not just the
    YAML schema. Guards against future test-only or programmatic constructors
    bypassing schema validation.
    """
    a1 = Coordinate3D(x=10.0, y=10.0, z=25.9)
    wells = {f"{r}{c}": a1 for r in "ABCDEFGH" for c in range(1, 13)}
    with pytest.raises(ValidationError, match="well_depth"):
        WellPlate(
            name="bad",
            rows=8, columns=12,
            wells=wells,
            well_depth=-1.0,
        )


def test_load_name_sbs_96_wellplate_carries_default_well_depth():
    """The shipped SBS96 definition supplies a sane default inside depth so
    `load_name: sbs_96_wellplate` users get it without per-deck overrides.

    The exact value (10.67 mm) lives in `sbs_96_wellplate/SBS96WellPlate.yaml`;
    this test pins it so a registry typo is caught.
    """
    yaml_str = """
labware:
  plate:
    load_name: sbs_96_wellplate
    calibration:
      a1: { x: 10.0, y: 10.0, z: 25.9 }
      a2: { x: 19.0, y: 10.0, z: 25.9 }
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_str)
        path = f.name
    try:
        deck = load_deck_from_yaml(path)
        plate = deck["plate"]
        assert plate.well_depth == pytest.approx(10.67)
    finally:
        Path(path).unlink(missing_ok=True)


def test_load_name_analytical_sales_aluminum_vial_well_plate():
    """The Analytical Sales aluminum vial plate definition loads from the registry."""
    yaml_str = """
labware:
  vial_plate:
    load_name: analytical_sales_96_aluminum_vial_well_plate
    calibration:
      a1: { x: 10.0, y: 20.0, z: 30.0 }
      a2: { x: 19.0, y: 20.0, z: 30.0 }
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_str)
        path = f.name
    try:
        deck = load_deck_from_yaml(path)
        plate = deck["vial_plate"]
        assert isinstance(plate, WellPlate)
        assert plate.name == "vial_plate"
        assert plate.model_name == "analytical_sales_101960_rev6f"
        assert plate.rows == 8
        assert plate.columns == 12
        assert plate.length == pytest.approx(127.8)
        assert plate.width == pytest.approx(85.5)
        assert plate.height == pytest.approx(46.2)
        assert plate.capacity_ul == pytest.approx(1000.0)
        assert plate.well_depth is None
        assert plate.get_well_center("A1") == Coordinate3D(x=10.0, y=20.0, z=30.0)
        assert plate.get_well_center("A2") == Coordinate3D(x=19.0, y=20.0, z=30.0)
        assert plate.get_well_center("H12") == Coordinate3D(x=109.0, y=-43.0, z=30.0)
    finally:
        Path(path).unlink(missing_ok=True)


def test_load_name_sbs_96_wellplate_well_depth_user_override_wins():
    """Deck-level `well_depth` overrides the registry default.

    Regression guard for the registry merge order — confirms user-supplied
    fields win over the definition's defaults (matches the comment in
    `_resolve_load_names`).
    """
    yaml_str = """
labware:
  plate:
    load_name: sbs_96_wellplate
    well_depth: 8.5
    calibration:
      a1: { x: 10.0, y: 10.0, z: 25.9 }
      a2: { x: 19.0, y: 10.0, z: 25.9 }
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_str)
        path = f.name
    try:
        deck = load_deck_from_yaml(path)
        plate = deck["plate"]
        assert plate.well_depth == pytest.approx(8.5)
    finally:
        Path(path).unlink(missing_ok=True)


def test_nested_well_plate_carries_well_depth():
    """Wellplates declared inside a holder must also carry `well_depth`
    through to the WellPlate model.

    The top-level `_build_well_plate` auto-wires fields via
    `_entry_kwargs_for_model`, but `_build_nested_well_plate` is an explicit
    constructor — without this test, dropping the field there would not be
    caught by any other case.
    """
    yaml_str = """
labware:
  plate_holder:
    type: well_plate_holder
    name: plate_holder
    location: { x: 221.75, y: 78.5, z: 183.0 }
    well_plate:
      model_name: panda_96_wellplate
      rows: 2
      columns: 2
      well_depth: 9.5
      calibration:
        a1: { x: 221.75, y: 78.5 }
        a2: { x: 230.75, y: 78.5 }
      x_offset: 9.0
      y_offset: 9.0
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_str)
        path = f.name
    try:
        deck = load_deck_from_yaml(path)
        holder = deck["plate_holder"]
        nested = holder.contained_labware["plate"]
        assert isinstance(nested, WellPlate)
        assert nested.well_depth == pytest.approx(9.5)
    finally:
        Path(path).unlink(missing_ok=True)


def test_nested_well_plate_explicit_row_direction_is_honored():
    yaml_str = """
labware:
  plate_holder:
    type: well_plate_holder
    name: plate_holder
    location: { x: 10.0, y: 20.0, z: 30.0 }
    well_plate:
      model_name: nested
      rows: 2
      columns: 2
      calibration:
        a1: { x: 10.0, y: 20.0 }
        a2: { x: 19.0, y: 20.0 }
      x_offset: 9.0
      y_offset: 9.0
      row_direction: positive
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_str)
        path = f.name
    try:
        deck = load_deck_from_yaml(path)
        assert deck.resolve_coordinate("plate_holder.plate.B1").y == pytest.approx(29.0)
    finally:
        Path(path).unlink(missing_ok=True)
