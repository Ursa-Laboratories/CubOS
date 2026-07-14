"""Tests for built-in gantry machine geometry."""

from __future__ import annotations

from cubos.gantry.gantry_config import GantryConfig, GantryType, OriginPolicy, WorkingVolume
from cubos.gantry.machine_geometry import (
    fixed_structures_for_gantry,
    fixed_structures_for_gantry_type,
)


def _cub_xl_config(*, origin_policy: OriginPolicy = OriginPolicy.DECK_ORIGIN) -> GantryConfig:
    if origin_policy is OriginPolicy.HOME_ORIGIN:
        working_volume = WorkingVolume(
            x_min=-400.0, x_max=0.0,
            y_min=-300.0, y_max=0.0,
            z_min=-100.0, z_max=0.0,
        )
    else:
        working_volume = WorkingVolume(
            x_min=0.0, x_max=400.0,
            y_min=0.0, y_max=300.0,
            z_min=0.0, z_max=100.0,
        )
    return GantryConfig(
        serial_port="/dev/null",
        gantry_type=GantryType.CUB_XL,
        factory_z_travel_mm=100.0,
        working_volume=working_volume,
        origin_policy=origin_policy,
    )


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


def test_fixed_structures_for_gantry_deck_origin_matches_type_lookup():
    config = _cub_xl_config(origin_policy=OriginPolicy.DECK_ORIGIN)

    structures = fixed_structures_for_gantry(config)

    assert structures == fixed_structures_for_gantry_type(GantryType.CUB_XL)
    rail = structures[0]
    assert rail.x_min == 480.0
    assert rail.x_max == 540.0
    assert rail.y_min == 0.0
    assert rail.y_max == 300.0
    assert rail.z_min == 0.0
    assert rail.z_max == 100.0


def test_fixed_structures_for_gantry_home_origin_returns_translated_rail():
    config = _cub_xl_config(origin_policy=OriginPolicy.HOME_ORIGIN)

    structures = fixed_structures_for_gantry(config)

    assert len(structures) == 1
    rail = structures[0]
    assert rail.name == "Cub XL right X-max rail"
    assert rail.x_min == -60.0
    assert rail.x_max == 0.0
    assert rail.y_min == -300.0
    assert rail.y_max == 0.0
    assert rail.z_min == -100.0
    assert rail.z_max == 0.0


def test_fixed_structures_for_gantry_none_returns_empty_tuple():
    assert fixed_structures_for_gantry(None) == ()
