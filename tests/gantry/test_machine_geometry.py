"""Tests for built-in gantry machine geometry."""

from __future__ import annotations

from gantry.gantry_config import GantryType
from gantry.machine_geometry import fixed_structures_for_gantry_type


def test_cub_xl_exposes_right_x_max_rail_geometry():
    structures = fixed_structures_for_gantry_type(GantryType.CUB_XL)

    assert len(structures) == 1
    rail = structures[0]
    assert rail.name == "Cub XL right X-max rail"
    assert rail.contains(500.0, 150.0, 50.0) is True
    assert rail.contains(500.0, 150.0, 101.0) is False


def test_cub_exposes_no_fixed_machine_geometry():
    assert fixed_structures_for_gantry_type(GantryType.CUB) == ()


def test_fixed_geometry_is_returned_as_immutable_tuple():
    structures = fixed_structures_for_gantry_type(GantryType.CUB_XL)

    assert isinstance(structures, tuple)
