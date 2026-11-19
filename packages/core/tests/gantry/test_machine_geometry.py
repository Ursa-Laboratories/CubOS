"""Tests for built-in gantry machine geometry."""

from __future__ import annotations

from cubos.gantry.gantry_config import GantryConfig, GantryType, OriginPolicy, WorkingVolume
from cubos.gantry.machine_geometry import (
    fixed_structures_for_gantry,
    fixed_structures_for_gantry_type,
)


def _cub_xl_config(
    *,
    origin_policy: OriginPolicy = OriginPolicy.DECK_ORIGIN,
    expected_grbl_settings: dict[str, float] | None = None,
) -> GantryConfig:
    working_volume = WorkingVolume(
        x_min=0.0, x_max=400.0, y_min=0.0, y_max=300.0,
        z_min=0.0, z_max=100.0,
    )
    return GantryConfig(
        serial_port="/dev/null",
        gantry_type=GantryType.CUB_XL,
        factory_z_travel_mm=100.0,
        working_volume=working_volume,
        origin_policy=origin_policy,
        expected_grbl_settings=expected_grbl_settings,
    )


def test_cub_xl_exposes_right_x_max_rail_geometry():
    structures = fixed_structures_for_gantry_type(GantryType.CUB_XL)

    assert len(structures) == 1
    rail = structures[0]
    assert rail.name == "Cub XL right X-max rail"
    assert rail.contains(500.0, 150.0, 50.0) is True
    assert rail.contains(500.0, 150.0, 81.0) is False


def test_cub_exposes_no_fixed_machine_geometry():
    assert fixed_structures_for_gantry_type(GantryType.CUB) == ()


def test_genmitsu_4040_pro_max_does_not_inherit_cub_xl_rail_geometry():
    assert fixed_structures_for_gantry_type(GantryType.GENMITSU_4040_PRO_MAX) == ()


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
    assert rail.z_max == 80.0








def test_fixed_structures_for_gantry_none_returns_empty_tuple():
    assert fixed_structures_for_gantry(None) == ()
