"""Tests for optional per-well attributes on ``WellPlate``.

``well_attributes`` is an open mapping, optional by design: no plate is
ever required to declare it, no key is reserved, and every plate that
omits it stays fully addressable with an empty mapping.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from cubos.data.fluid_state import _layout_entry
from cubos.deck.labware.labware import Coordinate3D
from cubos.deck.labware.well_plate import WellPlate
from cubos.deck.labware.well_plate_holder import WellPlateHolder
from cubos.deck.loader import load_deck_from_yaml


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_plate(**overrides) -> WellPlate:
    kwargs = {
        "name": "plate_1",
        "model_name": "test_plate",
        "length": 127.76,
        "width": 85.47,
        "height": 14.35,
        "well_depth": 10.67,
        "rows": 1,
        "columns": 2,
        "wells": {
            "A1": Coordinate3D(x=0.0, y=0.0, z=-5.0),
            "A2": Coordinate3D(x=9.0, y=0.0, z=-5.0),
        },
        "capacity_ul": 200.0,
        "working_volume_ul": 150.0,
    }
    kwargs.update(overrides)
    return WellPlate(**kwargs)


def _load_deck_yaml(yaml_str: str):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as handle:
        handle.write(yaml_str)
        path = handle.name
    try:
        return load_deck_from_yaml(path)
    finally:
        Path(path).unlink(missing_ok=True)


# ─── The bag is open ─────────────────────────────────────────────────────────


def test_plate_without_well_attributes_defaults_to_empty_mapping():
    plate = _make_plate()

    assert plate.well_attributes == {}
    assert plate.well_attribute_float("diameter") is None


def test_well_attributes_accept_arbitrary_scalar_keys_and_types():
    plate = _make_plate(
        well_attributes={
            "diameter": 6.86,
            "bottom": "flat",
            "rows_addressable": 8,
            "conductive": True,
        }
    )

    assert plate.well_attributes["diameter"] == pytest.approx(6.86)
    assert plate.well_attributes["bottom"] == "flat"
    assert plate.well_attributes["rows_addressable"] == 8
    assert plate.well_attributes["conductive"] is True


def test_unknown_attribute_keys_are_stored_not_rejected():
    # The bag is deliberately open — the schema does not police key names.
    plate = _make_plate(well_attributes={"totally_made_up_key": 1.0})

    assert plate.well_attributes["totally_made_up_key"] == pytest.approx(1.0)


@pytest.mark.parametrize("value", [{"nested": 1}, [1, 2, 3], None])
def test_non_scalar_attribute_values_rejected(value):
    # Open on keys, closed on shape: values stay flat scalars so the bag
    # cannot grow into an unvalidated nested structure.
    with pytest.raises(ValidationError):
        _make_plate(well_attributes={"diameter": value})


# ─── Numeric accessor ────────────────────────────────────────────────────────


def test_well_attribute_float_returns_declared_number():
    plate = _make_plate(well_attributes={"diameter": 6.86})

    assert plate.well_attribute_float("diameter") == pytest.approx(6.86)


def test_well_attribute_float_coerces_int_to_float():
    plate = _make_plate(well_attributes={"diameter": 7})

    result = plate.well_attribute_float("diameter")

    assert isinstance(result, float)
    assert result == pytest.approx(7.0)


def test_well_attribute_float_returns_none_for_absent_key():
    plate = _make_plate(well_attributes={"bottom": "flat"})

    assert plate.well_attribute_float("diameter") is None


@pytest.mark.parametrize("value", ["6.86", True, False])
def test_well_attribute_float_returns_none_for_non_numeric(value):
    # Booleans are ints in Python; arithmetic callers must not silently
    # receive 1.0 from `conductive: true`.
    plate = _make_plate(well_attributes={"diameter": value})

    assert plate.well_attribute_float("diameter") is None


# ─── Deck YAML round-trip ────────────────────────────────────────────────────


TOP_LEVEL_PLATE_YAML = """
labware:
  plate_1:
    type: well_plate
    name: plate_1
    model_name: attribute_plate
    rows: 2
    columns: 2
    well_depth: 10.67
    well_attributes:
      diameter: 6.86
      bottom: flat
    calibration:
      a1: { x: 10.0, y: 20.0, z: -5.0 }
      a2: { x: 19.0, y: 20.0, z: -5.0 }
    x_offset: 9.0
    y_offset: 9.0
    capacity_ul: 200.0
    working_volume_ul: 150.0
"""


def test_top_level_plate_round_trips_well_attributes_through_deck_yaml():
    plate = _load_deck_yaml(TOP_LEVEL_PLATE_YAML)["plate_1"]

    assert isinstance(plate, WellPlate)
    assert plate.well_attributes == {"diameter": 6.86, "bottom": "flat"}
    assert plate.well_attribute_float("diameter") == pytest.approx(6.86)


NESTED_PLATE_YAML = """
labware:
  plate_holder:
    type: well_plate_holder
    name: plate_holder
    location:
      x: 221.75
      y: 78.5
      z: 183.0
    well_plate:
      model_name: nested_attribute_plate
      rows: 2
      columns: 2
      well_attributes:
        diameter: 6.86
        bottom: v
      calibration:
        a1: { x: 221.75, y: 78.5 }
        a2: { x: 230.75, y: 78.5 }
      x_offset: 9.0
      y_offset: 9.0
"""


def test_nested_plate_in_holder_retains_well_attributes():
    # Regression: `_build_nested_well_plate` enumerates fields by hand, so a
    # field missing from that call is silently dropped rather than erroring.
    holder = _load_deck_yaml(NESTED_PLATE_YAML)["plate_holder"]

    assert isinstance(holder, WellPlateHolder)
    plate = holder.contained_labware["plate"]
    assert isinstance(plate, WellPlate)
    assert plate.well_attributes == {"diameter": 6.86, "bottom": "v"}
    assert plate.well_attribute_float("diameter") == pytest.approx(6.86)


NESTED_PLATE_WITHOUT_ATTRIBUTES_YAML = """
labware:
  plate_holder:
    type: well_plate_holder
    name: plate_holder
    location:
      x: 221.75
      y: 78.5
      z: 183.0
    well_plate:
      model_name: plain_nested_plate
      rows: 2
      columns: 2
      calibration:
        a1: { x: 221.75, y: 78.5 }
        a2: { x: 230.75, y: 78.5 }
      x_offset: 9.0
      y_offset: 9.0
"""


def test_nested_plate_without_attributes_still_loads():
    holder = _load_deck_yaml(NESTED_PLATE_WITHOUT_ATTRIBUTES_YAML)["plate_holder"]

    plate = holder.contained_labware["plate"]
    assert plate.well_attributes == {}


# ─── load_name expansion carries attributes ──────────────────────────────────


SBS96_LOAD_NAME_YAML = """
labware:
  plate_1:
    load_name: sbs_96_wellplate
    calibration:
      a1: { x: -17.88, y: -42.23, z: -20.0 }
      a2: { x: -8.88, y: -42.23, z: -20.0 }
"""


def test_sbs_96_load_name_expands_with_well_attributes():
    plate = _load_deck_yaml(SBS96_LOAD_NAME_YAML)["plate_1"]

    assert isinstance(plate, WellPlate)
    assert plate.rows == 8
    assert plate.columns == 12
    assert len(plate.wells) == 96
    assert plate.well_depth == pytest.approx(10.67)
    assert plate.well_attribute_float("diameter") == pytest.approx(6.86)
    assert plate.well_attributes["bottom"] == "flat"


# ─── Fluid-state layout export ───────────────────────────────────────────────


def test_layout_entry_emits_diameter_from_well_attributes():
    plate = _make_plate(well_attributes={"diameter": 6.86})

    geometry = _layout_entry("plate_1", plate)["geometry"]

    assert geometry["diameter"] == pytest.approx(6.86)
    assert geometry["well_depth"] == pytest.approx(10.67)
    # Deliberately minimal: the payload is a cross-repo contract, so no new
    # keys were introduced alongside the populated one.
    assert set(geometry) == {"length", "width", "height", "well_depth", "diameter"}


def test_layout_entry_emits_none_diameter_without_attributes():
    plate = _make_plate()

    assert _layout_entry("plate_1", plate)["geometry"]["diameter"] is None


def test_layout_entry_emits_none_diameter_for_non_numeric_attribute():
    plate = _make_plate(well_attributes={"diameter": "wide"})

    assert _layout_entry("plate_1", plate)["geometry"]["diameter"] is None
