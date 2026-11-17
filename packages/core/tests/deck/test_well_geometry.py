from __future__ import annotations

import pytest
from pydantic import ValidationError

from cubos.deck.labware.labware import Coordinate3D
from cubos.deck.labware.vial import Vial
from cubos.deck.labware.well_plate import WellPlate
from cubos.deck.loader import load_deck_from_yaml

WELLS = {"A1": Coordinate3D(x=1.0, y=1.0, z=10.0)}


def _plate(**kwargs) -> WellPlate:
    return WellPlate(name="p", rows=1, columns=1, wells=WELLS, **kwargs)


def _vial(**kwargs) -> Vial:
    return Vial(
        name="v", location=Coordinate3D(x=0.0, y=0.0, z=10.0),
        capacity_ul=100.0, working_volume_ul=50.0, **kwargs,
    )


def test_geometry_fields_default_to_unspecified():
    plate = _plate()
    assert plate.well_shape is None and plate.well_diameter is None
    assert _vial().inner_depth is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"well_shape": "circular", "well_diameter": 6.9},
        {"well_shape": "rectangular", "well_x_dimension": 8.0, "well_y_dimension": 70.0},
        {"well_diameter": 6.9},
        {"well_x_dimension": 8.0, "well_y_dimension": 70.0},
    ],
)
def test_consistent_cross_sections_accepted(kwargs):
    assert _plate(well_depth=10.0, **kwargs).well_depth == 10.0


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"well_diameter": 6.9, "well_x_dimension": 8.0, "well_y_dimension": 8.0}, "cannot be combined"),
        ({"well_x_dimension": 8.0}, "set together"),
        ({"well_shape": "circular", "well_x_dimension": 8.0, "well_y_dimension": 8.0}, "circular"),
        ({"well_shape": "rectangular", "well_diameter": 6.9}, "rectangular"),
        ({"well_shape": "circular"}, "requires well_diameter"),
        ({"well_shape": "rectangular"}, "requires well_x_dimension"),
        ({"well_diameter": 0.0}, "positive"),
        ({"well_shape": "hexagonal", "well_diameter": 1.0}, "well_shape"),
    ],
)
def test_inconsistent_cross_sections_rejected(kwargs, match):
    with pytest.raises(ValidationError, match=match):
        _plate(**kwargs)


def test_vial_inner_depth_bounded_by_height():
    assert _vial(height=40.0, inner_depth=38.0).inner_depth == 38.0
    with pytest.raises(ValidationError, match="inner_depth"):
        _vial(height=40.0, inner_depth=41.0)
    with pytest.raises(ValidationError):
        _vial(inner_depth=0.0)


DECK_YAML = """\
labware:
  plate:
    type: well_plate
    name: plate
    rows: 1
    columns: 2
    height: 14.0
    well_depth: 10.0
    well_shape: circular
    well_diameter: 6.4
    calibration:
      a1: {x: 10.0, y: 10.0, z: 20.0}
      a2: {x: 19.0, y: 10.0}
    x_offset: 9.0
    y_offset: 9.0
    capacity_ul: 300.0
    working_volume_ul: 200.0
  vial:
    type: vial
    name: vial
    height: 40.0
    diameter: 20.0
    inner_depth: 37.0
    location: {x: 50.0, y: 50.0, z: 20.0}
    capacity_ul: 5000.0
    working_volume_ul: 4500.0
  grid:
    type: vial_grid
    name: grid
    rows: 1
    columns: 2
    calibration:
      a1: {x: 80.0, y: 10.0, z: 20.0}
      a2: {x: 100.0, y: 10.0}
    x_offset: 20.0
    y_offset: 20.0
    vial_height: 30.0
    vial_diameter: 15.0
    vial_inner_depth: 27.0
    capacity_ul: 1000.0
    working_volume_ul: 900.0
"""


def test_yaml_geometry_reaches_labware(tmp_path):
    path = tmp_path / "deck.yaml"
    path.write_text(DECK_YAML, encoding="utf-8")
    deck = load_deck_from_yaml(path)
    plate, vial = deck["plate"], deck["vial"]
    assert (plate.well_shape, plate.well_diameter, plate.well_depth) == ("circular", 6.4, 10.0)
    assert vial.inner_depth == 37.0
    assert deck["grid"].vials["A1"].inner_depth == 27.0
