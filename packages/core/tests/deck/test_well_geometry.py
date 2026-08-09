"""Tests for optional per-well lateral geometry on ``WellPlate``.

``well_geometry`` is optional by design: no plate is ever required to
declare it, and every plate that omits it stays fully addressable. The
shape variants form a discriminated union so per-shape completeness is
enforced by the schema rather than by after-the-fact validation.
"""

from __future__ import annotations

import math
import tempfile
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from cubos.data.fluid_state import _layout_entry
from cubos.deck.labware.labware import (
    CircularWellGeometry,
    Coordinate3D,
    RectangularWellGeometry,
    WellGeometry,
)
from cubos.deck.labware.well_plate import WellPlate
from cubos.deck.labware.well_plate_holder import WellPlateHolder
from cubos.deck.loader import load_deck_from_yaml


# ─── Helpers ──────────────────────────────────────────────────────────────────


class _GeometryHolder(BaseModel):
    """Minimal wrapper used to validate the union in isolation."""

    well_geometry: WellGeometry


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


# ─── Shape variants: valid input and derived quantities ──────────────────────


def test_circular_well_geometry_computes_area_and_inscribed_radius():
    geometry = CircularWellGeometry(diameter=6.86)

    assert geometry.shape == "circular"
    assert geometry.bottom == "flat"  # default
    assert geometry.cross_section_area_mm2 == pytest.approx(math.pi * 3.43**2)
    assert geometry.inscribed_radius_mm == pytest.approx(3.43)


def test_rectangular_well_geometry_computes_area_and_inscribed_radius():
    geometry = RectangularWellGeometry(x_dimension=8.0, y_dimension=4.0)

    assert geometry.shape == "rectangular"
    assert geometry.bottom == "flat"
    assert geometry.cross_section_area_mm2 == pytest.approx(32.0)
    # The inscribed radius is bounded by the *narrow* side, not the wide one.
    assert geometry.inscribed_radius_mm == pytest.approx(2.0)


@pytest.mark.parametrize("bottom", ["flat", "round", "v"])
def test_bottom_profile_accepts_every_supported_value(bottom):
    assert CircularWellGeometry(diameter=6.0, bottom=bottom).bottom == bottom
    assert (
        RectangularWellGeometry(x_dimension=6.0, y_dimension=6.0, bottom=bottom).bottom
        == bottom
    )


def test_unknown_bottom_profile_rejected():
    with pytest.raises(ValidationError):
        CircularWellGeometry(diameter=6.0, bottom="conical")


# ─── Illegal states are unrepresentable ──────────────────────────────────────


def test_circular_geometry_rejects_rectangular_dimension():
    """A circular well carrying `x_dimension` is a mixed, underspecified shape."""
    with pytest.raises(ValidationError):
        _GeometryHolder(
            well_geometry={"shape": "circular", "diameter": 6.0, "x_dimension": 8.0}
        )


def test_rectangular_geometry_rejects_missing_y_dimension():
    with pytest.raises(ValidationError):
        _GeometryHolder(well_geometry={"shape": "rectangular", "x_dimension": 8.0})


def test_rectangular_geometry_rejects_circular_diameter():
    with pytest.raises(ValidationError):
        _GeometryHolder(
            well_geometry={
                "shape": "rectangular",
                "x_dimension": 8.0,
                "y_dimension": 8.0,
                "diameter": 6.0,
            }
        )


def test_unknown_shape_rejected():
    with pytest.raises(ValidationError):
        _GeometryHolder(well_geometry={"shape": "hexagonal", "diameter": 6.0})


def test_missing_shape_discriminator_rejected():
    with pytest.raises(ValidationError):
        _GeometryHolder(well_geometry={"diameter": 6.0})


@pytest.mark.parametrize("diameter", [0.0, -1.0])
def test_circular_geometry_rejects_non_positive_diameter(diameter):
    with pytest.raises(ValidationError):
        CircularWellGeometry(diameter=diameter)


@pytest.mark.parametrize(
    "x_dimension,y_dimension",
    [(0.0, 4.0), (-1.0, 4.0), (4.0, 0.0), (4.0, -1.0)],
)
def test_rectangular_geometry_rejects_non_positive_dimensions(x_dimension, y_dimension):
    with pytest.raises(ValidationError):
        RectangularWellGeometry(x_dimension=x_dimension, y_dimension=y_dimension)


# ─── Backward compatibility: omitting well_geometry stays valid ──────────────


def test_plate_without_well_geometry_is_valid_and_accessors_return_none():
    """The backward-compat guarantee: nothing becomes required."""
    plate = _make_plate()

    assert plate.well_geometry is None
    assert plate.well_cross_section_area_mm2 is None
    assert plate.well_inscribed_radius_mm is None
    # Still fully addressable.
    assert plate.get_well_center("A2") == Coordinate3D(x=9.0, y=0.0, z=-5.0)
    assert sorted(plate.iter_positions()) == ["A1", "A2"]


def test_plate_accessors_delegate_to_declared_geometry():
    circular = _make_plate(well_geometry=CircularWellGeometry(diameter=6.86))
    assert circular.well_cross_section_area_mm2 == pytest.approx(math.pi * 3.43**2)
    assert circular.well_inscribed_radius_mm == pytest.approx(3.43)

    rectangular = _make_plate(
        well_geometry=RectangularWellGeometry(x_dimension=8.0, y_dimension=4.0)
    )
    assert rectangular.well_cross_section_area_mm2 == pytest.approx(32.0)
    assert rectangular.well_inscribed_radius_mm == pytest.approx(2.0)


def test_plate_accepts_well_geometry_as_plain_mapping():
    plate = _make_plate(well_geometry={"shape": "circular", "diameter": 6.86})

    assert isinstance(plate.well_geometry, CircularWellGeometry)
    assert plate.well_geometry.bottom == "flat"


# ─── Deck YAML round-trips ───────────────────────────────────────────────────


TOP_LEVEL_PLATE_YAML = """
labware:
  plate_1:
    type: well_plate
    name: geometry_plate
    model_name: geometry_plate
    rows: 1
    columns: 2
    length: 127.76
    width: 85.47
    height: 14.35
    well_depth: 10.67
    well_geometry:
      shape: circular
      diameter: 6.86
      bottom: round
    calibration:
      a1: { x: -10.0, y: -10.0, z: -15.0 }
      a2: { x: -1.0, y: -10.0, z: -15.0 }
    x_offset: 9.0
    y_offset: 9.0
    capacity_ul: 200.0
    working_volume_ul: 150.0
"""


def test_top_level_plate_round_trips_well_geometry_through_deck_yaml():
    plate = _load_deck_yaml(TOP_LEVEL_PLATE_YAML)["plate_1"]

    assert isinstance(plate, WellPlate)
    assert isinstance(plate.well_geometry, CircularWellGeometry)
    assert plate.well_geometry.diameter == pytest.approx(6.86)
    assert plate.well_geometry.bottom == "round"
    assert plate.well_cross_section_area_mm2 == pytest.approx(math.pi * 3.43**2)


TOP_LEVEL_RECTANGULAR_PLATE_YAML = """
labware:
  plate_1:
    type: well_plate
    name: rect_plate
    rows: 1
    columns: 2
    well_geometry:
      shape: rectangular
      x_dimension: 8.0
      y_dimension: 4.0
    calibration:
      a1: { x: -10.0, y: -10.0, z: -15.0 }
      a2: { x: -1.0, y: -10.0, z: -15.0 }
    x_offset: 9.0
    y_offset: 9.0
"""


def test_top_level_plate_round_trips_rectangular_geometry():
    plate = _load_deck_yaml(TOP_LEVEL_RECTANGULAR_PLATE_YAML)["plate_1"]

    assert isinstance(plate.well_geometry, RectangularWellGeometry)
    assert plate.well_inscribed_radius_mm == pytest.approx(2.0)


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
      model_name: nested_geometry_plate
      rows: 2
      columns: 2
      well_geometry:
        shape: circular
        diameter: 6.86
        bottom: v
      calibration:
        a1: { x: 221.75, y: 78.5 }
        a2: { x: 230.75, y: 78.5 }
      x_offset: 9.0
      y_offset: 9.0
"""


def test_nested_plate_in_holder_retains_well_geometry():
    """Regression: ``_build_nested_well_plate`` enumerates fields by hand, so a
    newly added field is silently dropped (no error, just ``None``) unless it
    is explicitly forwarded."""
    holder = _load_deck_yaml(NESTED_PLATE_YAML)["plate_holder"]

    assert isinstance(holder, WellPlateHolder)
    plate = holder.contained_labware["plate"]
    assert isinstance(plate, WellPlate)
    assert plate.well_geometry is not None, (
        "nested well plate silently lost its well_geometry"
    )
    assert isinstance(plate.well_geometry, CircularWellGeometry)
    assert plate.well_geometry.diameter == pytest.approx(6.86)
    assert plate.well_geometry.bottom == "v"
    assert plate.well_cross_section_area_mm2 == pytest.approx(math.pi * 3.43**2)


def test_nested_plate_without_geometry_still_loads():
    yaml_str = NESTED_PLATE_YAML.replace(
        """      well_geometry:
        shape: circular
        diameter: 6.86
        bottom: v
""",
        "",
    )
    holder = _load_deck_yaml(yaml_str)["plate_holder"]
    plate = holder.contained_labware["plate"]

    assert plate.well_geometry is None
    assert plate.well_cross_section_area_mm2 is None


def test_deck_yaml_rejects_invalid_nested_well_geometry():
    yaml_str = NESTED_PLATE_YAML.replace("diameter: 6.86", "diameter: -1.0")
    with pytest.raises(Exception):
        _load_deck_yaml(yaml_str)


# ─── load_name expansion carries well geometry ───────────────────────────────


SBS96_LOAD_NAME_YAML = """
labware:
  plate_1:
    load_name: sbs_96_wellplate
    calibration:
      a1: { x: -17.88, y: -42.23, z: -20.0 }
      a2: { x: -8.88, y: -42.23, z: -20.0 }
"""


def test_sbs_96_load_name_expands_to_expected_geometry():
    plate = _load_deck_yaml(SBS96_LOAD_NAME_YAML)["plate_1"]

    assert isinstance(plate, WellPlate)
    assert plate.model_name == "sbs_96_wellplate"
    assert plate.rows == 8
    assert plate.columns == 12
    assert len(plate.wells) == 96
    assert plate.well_depth == pytest.approx(10.67)
    assert isinstance(plate.well_geometry, CircularWellGeometry)
    assert plate.well_geometry.diameter == pytest.approx(6.86)
    assert plate.well_geometry.bottom == "flat"
    assert plate.well_cross_section_area_mm2 == pytest.approx(math.pi * 3.43**2)
    assert plate.well_inscribed_radius_mm == pytest.approx(3.43)


# ─── Fluid-state layout export ───────────────────────────────────────────────


def test_layout_entry_emits_diameter_for_circular_well_plate():
    plate = _make_plate(well_geometry=CircularWellGeometry(diameter=15.6))

    geometry = _layout_entry("plate_1", plate)["geometry"]

    assert geometry["diameter"] == pytest.approx(15.6)
    assert geometry["well_depth"] == pytest.approx(10.67)
    # Deliberately minimal: the payload is a cross-repo contract, so no new
    # keys were introduced alongside the populated one.
    assert set(geometry) == {"length", "width", "height", "well_depth", "diameter"}


def test_layout_entry_emits_none_diameter_without_geometry():
    geometry = _layout_entry("plate_1", _make_plate())["geometry"]

    assert geometry["diameter"] is None


def test_layout_entry_emits_none_diameter_for_rectangular_wells():
    """Rectangular wells have no single meaningful diameter."""
    plate = _make_plate(
        well_geometry=RectangularWellGeometry(x_dimension=8.0, y_dimension=4.0)
    )

    assert _layout_entry("plate_1", plate)["geometry"]["diameter"] is None
