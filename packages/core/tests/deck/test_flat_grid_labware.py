"""Additive flat-grid labware and legacy-address compatibility tests."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest
from pydantic import ValidationError

from cubos.data.data_store import DataStore
from cubos.data.protocol_runs import register_deck_labware
from cubos.deck import (
    BoundingBoxGeometry,
    Coordinate3D,
    VialGrid,
    VialHolder,
    Vial,
    WellPlate,
    WellPlateHolder,
)
from cubos.deck.loader import load_deck_from_yaml, resolve_load_names


def _write_deck(tmp_path: Path, name: str, contents: str) -> Path:
    path = tmp_path / name
    path.write_text(dedent(contents), encoding="utf-8")
    return path


def _vial_coordinates(grid: VialGrid) -> dict[str, Coordinate3D]:
    return {position_id: vial.location for position_id, vial in grid.vials.items()}


def _runtime_vial(
    name: str,
    *,
    x: float = 1.0,
    height: float | None = None,
    diameter: float | None = None,
) -> Vial:
    return Vial(
        name=name,
        model_name="runtime_vial",
        height=height,
        diameter=diameter,
        location=Coordinate3D(x=x, y=2.0, z=3.0),
        capacity_ul=1000.0,
        working_volume_ul=900.0,
    )


LEGACY_PLATE = """
labware:
  plate_holder:
    type: well_plate_holder
    name: legacy_plate_holder
    location: {x: 4.0, y: 6.0, z: 10.0}
    well_plate_surface_height_from_bottom: 5.0
    well_plate:
      name: paired_plate
      model_name: paired_2x3
      rows: 2
      columns: 3
      calibration:
        a1: {x: 100.0, y: 50.0}
        a2: {x: 109.0, y: 50.0}
      x_offset: 9.0
      y_offset: 8.0
      capacity_ul: 200.0
      working_volume_ul: 150.0
"""


FLAT_PLATE = """
labware:
  plate_holder__plate:
    type: well_plate
    name: paired_plate
    model_name: paired_2x3
    rows: 2
    columns: 3
    calibration:
      a1: {x: 100.0, y: 50.0, z: 15.0}
      a2: {x: 109.0, y: 50.0, z: 15.0}
    x_offset: 9.0
    y_offset: 8.0
    capacity_ul: 200.0
    working_volume_ul: 150.0
"""


LEGACY_REGULAR_VIALS = """
labware:
  vial_holder:
    type: vial_holder
    name: legacy_vial_holder
    location: {x: 0.0, y: 0.0, z: 8.0}
    labware_seat_height_from_bottom: 3.0
    slot_count: 4
    vials:
      A1:
        model_name: paired_vial
        height: 40.0
        diameter: 10.0
        location: {x: 10.0, y: 20.0}
        capacity_ul: 1000.0
        working_volume_ul: 900.0
      A2:
        model_name: paired_vial
        height: 40.0
        diameter: 10.0
        location: {x: 10.0, y: 25.0}
        capacity_ul: 1000.0
        working_volume_ul: 900.0
      B1:
        model_name: paired_vial
        height: 40.0
        diameter: 10.0
        location: {x: 16.0, y: 20.0}
        capacity_ul: 1000.0
        working_volume_ul: 900.0
      B2:
        model_name: paired_vial
        height: 40.0
        diameter: 10.0
        location: {x: 16.0, y: 25.0}
        capacity_ul: 1000.0
        working_volume_ul: 900.0
"""


FLAT_REGULAR_VIALS = """
labware:
  vial_holder__vials:
    type: vial_grid
    name: paired_vials
    label: Paired reagent vials
    model_name: paired_2x2_grid
    rows: 2
    columns: 2
    calibration:
      a1: {x: 10.0, y: 20.0, z: 11.0}
      a2: {x: 10.0, y: 25.0, z: 11.0}
    x_offset: 6.0
    y_offset: 5.0
    vial_model_name: paired_vial
    vial_height: 40.0
    vial_diameter: 10.0
    capacity_ul: 1000.0
    working_volume_ul: 900.0
    aliases:
      source: A1
      product: B2
"""


def test_legacy_nested_plate_and_flat_plate_match_every_coordinate(tmp_path: Path) -> None:
    legacy = load_deck_from_yaml(_write_deck(tmp_path, "legacy_plate.yaml", LEGACY_PLATE))
    flat = load_deck_from_yaml(_write_deck(tmp_path, "flat_plate.yaml", FLAT_PLATE))

    legacy_plate = legacy.volume_labware["plate_holder__plate"]
    flat_plate = flat.volume_labware["plate_holder__plate"]
    assert isinstance(legacy_plate, WellPlate)
    assert isinstance(flat_plate, WellPlate)
    assert legacy_plate.wells == flat_plate.wells

    for well_id, expected in flat_plate.wells.items():
        old_address = f"plate_holder.plate.{well_id}"
        canonical_address = f"plate_holder__plate.{well_id}"
        assert legacy.resolve_coordinate(old_address) == expected
        assert legacy.resolve_coordinate(canonical_address) == expected
        assert legacy.canonicalize_target(old_address) == canonical_address

        old_target = legacy.resolve_labware_target(old_address)
        canonical_target = legacy.resolve_labware_target(canonical_address)
        assert (old_target.labware_key, old_target.location_id) == (
            "plate_holder__plate",
            well_id,
        )
        assert (canonical_target.labware_key, canonical_target.location_id) == (
            old_target.labware_key,
            old_target.location_id,
        )

    holder = legacy["plate_holder"]
    assert isinstance(holder, WellPlateHolder)
    assert legacy.resolve_labware("plate_holder.plate") is holder.contained_labware["plate"]
    assert legacy.resolve_coordinate("plate_holder.plate") == flat_plate.wells["A1"]
    assert legacy.canonicalize_target("plate_holder.plate") == "plate_holder__plate"
    assert flat.canonicalize_target("plate_holder__plate.A1") == "plate_holder__plate.A1"


def test_legacy_regular_vials_and_flat_grid_match_every_coordinate(tmp_path: Path) -> None:
    legacy = load_deck_from_yaml(
        _write_deck(tmp_path, "legacy_vials.yaml", LEGACY_REGULAR_VIALS)
    )
    flat = load_deck_from_yaml(
        _write_deck(tmp_path, "flat_vials.yaml", FLAT_REGULAR_VIALS)
    )

    legacy_grid = legacy.volume_labware["vial_holder__vials"]
    flat_grid = flat.volume_labware["vial_holder__vials"]
    assert isinstance(legacy_grid, VialGrid)
    assert isinstance(flat_grid, VialGrid)
    assert _vial_coordinates(legacy_grid) == _vial_coordinates(flat_grid)

    for position_id, expected in _vial_coordinates(flat_grid).items():
        old_address = f"vial_holder.{position_id}"
        canonical_address = f"vial_holder__vials.{position_id}"
        assert legacy.resolve_coordinate(old_address) == expected
        assert legacy.resolve_coordinate(canonical_address) == expected
        assert legacy.canonicalize_target(old_address) == canonical_address
        resolved = legacy.resolve_labware_target(old_address)
        assert (resolved.labware_key, resolved.location_id) == (
            "vial_holder__vials",
            position_id,
        )

    assert flat_grid.label == "Paired reagent vials"
    assert flat_grid.aliases == {"source": "A1", "product": "B2"}
    assert flat.resolve_coordinate("vial_holder__vials.source") == flat_grid.vials["A1"].location
    assert flat.canonicalize_target("vial_holder__vials.source") == "vial_holder__vials.A1"
    assert flat.canonicalize_target("vial_holder__vials.A1") == "vial_holder__vials.A1"


def test_legacy_irregular_vials_preserve_exact_coordinates_and_metadata(
    tmp_path: Path,
) -> None:
    deck = load_deck_from_yaml(
        _write_deck(
            tmp_path,
            "irregular.yaml",
            """
            labware:
              irregular:
                type: vial_holder
                name: irregular_holder
                location: {x: 50.0, y: 60.0, z: 8.0}
                labware_seat_height_from_bottom: 3.0
                slot_count: 6
                vials:
                  source:
                    name: source_vial
                    model_name: small_source
                    height: 40.0
                    diameter: 10.0
                    location: {x: 1.125, y: 2.25}
                    capacity_ul: 1000.0
                    working_volume_ul: 900.0
                  product:
                    name: product_vial
                    model_name: large_product
                    height: 55.5
                    diameter: 17.25
                    location: {x: 17.75, y: 31.5}
                    capacity_ul: 2500.0
                    working_volume_ul: 1800.0
            """,
        )
    )

    holder = deck["irregular"]
    grid = deck.volume_labware["irregular__vials"]
    assert isinstance(holder, VialHolder)
    assert isinstance(grid, VialGrid)
    assert list(grid.vials) == ["source", "product"]
    assert grid.vials["source"] is holder.contained_labware["source"]
    assert grid.vials["product"] is holder.contained_labware["product"]

    assert grid.vials["source"].location == Coordinate3D(x=1.125, y=2.25, z=11.0)
    assert grid.vials["source"].height == pytest.approx(40.0)
    assert grid.vials["source"].diameter == pytest.approx(10.0)
    assert grid.vials["source"].capacity_ul == pytest.approx(1000.0)
    assert grid.vials["source"].working_volume_ul == pytest.approx(900.0)

    assert grid.vials["product"].location == Coordinate3D(x=17.75, y=31.5, z=11.0)
    assert grid.vials["product"].height == pytest.approx(55.5)
    assert grid.vials["product"].diameter == pytest.approx(17.25)
    assert grid.vials["product"].capacity_ul == pytest.approx(2500.0)
    assert grid.vials["product"].working_volume_ul == pytest.approx(1800.0)

    assert deck.resolve_coordinate("irregular.source") == grid.vials["source"].location
    assert deck.resolve_coordinate("irregular__vials.source") == grid.vials["source"].location
    assert deck.canonicalize_target("irregular.product") == "irregular__vials.product"


def test_reserved_holder_anchor_paths_are_not_legacy_vial_aliases(
    tmp_path: Path,
) -> None:
    deck = load_deck_from_yaml(
        _write_deck(
            tmp_path,
            "reserved_holder_paths.yaml",
            """
            labware:
              holder:
                type: vial_holder
                name: fixture_runtime_name
                location: {x: 100.0, y: 200.0, z: 10.0}
                labware_seat_height_from_bottom: 3.0
                slot_count: 4
                vials:
                  location:
                    model_name: vial
                    height: 40.0
                    diameter: 10.0
                    location: {x: 1.0, y: 2.0}
                    capacity_ul: 1000.0
                    working_volume_ul: 900.0
                  anchor:
                    model_name: vial
                    height: 40.0
                    diameter: 10.0
                    location: {x: 3.0, y: 4.0}
                    capacity_ul: 1000.0
                    working_volume_ul: 900.0
                  fixture_runtime_name:
                    model_name: vial
                    height: 40.0
                    diameter: 10.0
                    location: {x: 5.0, y: 6.0}
                    capacity_ul: 1000.0
                    working_volume_ul: 900.0
                  ordinary:
                    model_name: vial
                    height: 40.0
                    diameter: 10.0
                    location: {x: 7.0, y: 8.0}
                    capacity_ul: 1000.0
                    working_volume_ul: 900.0
            """,
        )
    )

    holder_anchor = Coordinate3D(x=100.0, y=200.0, z=10.0)
    grid = deck.volume_labware["holder__vials"]
    assert isinstance(grid, VialGrid)

    expected_vials = {
        "location": Coordinate3D(x=1.0, y=2.0, z=13.0),
        "anchor": Coordinate3D(x=3.0, y=4.0, z=13.0),
        "fixture_runtime_name": Coordinate3D(x=5.0, y=6.0, z=13.0),
    }
    for position_id, expected in expected_vials.items():
        legacy_target = f"holder.{position_id}"
        canonical_target = f"holder__vials.{position_id}"
        assert legacy_target not in deck.target_aliases
        assert deck.resolve_coordinate(legacy_target) == holder_anchor
        assert deck.resolve_coordinate(canonical_target) == expected

    assert deck.canonicalize_target("holder.ordinary") == "holder__vials.ordinary"
    assert deck.resolve_coordinate("holder.ordinary") == Coordinate3D(
        x=7.0,
        y=8.0,
        z=13.0,
    )


def test_partial_and_empty_legacy_holders_are_not_filled_in(tmp_path: Path) -> None:
    deck = load_deck_from_yaml(
        _write_deck(
            tmp_path,
            "partial.yaml",
            """
            labware:
              partial:
                type: vial_holder
                name: partial_holder
                location: {x: 0.0, y: 0.0, z: 10.0}
                slot_count: 9
                vials:
                  vial_2:
                    model_name: vial
                    height: 40.0
                    diameter: 10.0
                    location: {x: 5.0, y: 7.0}
                    capacity_ul: 1000.0
                    working_volume_ul: 900.0
                  vial_8:
                    model_name: vial
                    height: 40.0
                    diameter: 10.0
                    location: {x: 11.0, y: 19.0}
                    capacity_ul: 1000.0
                    working_volume_ul: 900.0
              empty_vials:
                type: vial_holder
                name: empty_vials
                location: {x: 20.0, y: 30.0, z: 10.0}
                slot_count: 9
              empty_plate:
                type: well_plate_holder
                name: empty_plate
                location: {x: 40.0, y: 50.0, z: 10.0}
            """,
        )
    )

    assert list(deck.volume_labware["partial__vials"].vials) == ["vial_2", "vial_8"]
    assert "empty_vials__vials" not in deck.volume_labware
    assert "empty_plate__plate" not in deck.volume_labware
    assert isinstance(deck["empty_vials"], VialHolder)
    assert isinstance(deck["empty_plate"], WellPlateHolder)


@pytest.mark.parametrize(
    ("yaml_contents", "colliding_id"),
    [
        (
            """
            labware:
              holder:
                type: well_plate_holder
                name: holder
                location: {x: 0.0, y: 0.0, z: 10.0}
                well_plate:
                  name: plate
                  model_name: plate
                  rows: 1
                  columns: 2
                  calibration:
                    a1: {x: 1.0, y: 2.0}
                    a2: {x: 10.0, y: 2.0}
                  x_offset: 9.0
                  y_offset: 9.0
              holder__plate:
                type: vial
                name: collision
                model_name: collision
                height: 10.0
                diameter: 5.0
                location: {x: 50.0, y: 60.0, z: 20.0}
                capacity_ul: 100.0
                working_volume_ul: 80.0
            """,
            "holder__plate",
        ),
        (
            """
            labware:
              holder:
                type: vial_holder
                name: holder
                location: {x: 0.0, y: 0.0, z: 10.0}
                vials:
                  vial_1:
                    model_name: vial
                    height: 40.0
                    diameter: 10.0
                    location: {x: 1.0, y: 2.0}
                    capacity_ul: 1000.0
                    working_volume_ul: 900.0
              holder__vials:
                type: vial
                name: collision
                model_name: collision
                height: 10.0
                diameter: 5.0
                location: {x: 50.0, y: 60.0, z: 20.0}
                capacity_ul: 100.0
                working_volume_ul: 80.0
            """,
            "holder__vials",
        ),
    ],
)
def test_generated_legacy_id_collision_is_rejected(
    tmp_path: Path,
    yaml_contents: str,
    colliding_id: str,
) -> None:
    path = _write_deck(tmp_path, "collision.yaml", yaml_contents)

    with pytest.raises(ValueError, match=colliding_id):
        load_deck_from_yaml(path)


def test_vial_grid_load_name_expands_and_user_fields_override_defaults(
    tmp_path: Path,
) -> None:
    raw = {
        "labware": {
            "reagents": {
                "load_name": "ursa_9_vial_grid",
                "label": "Reagent bank",
                "rows": 2,
                "columns": 2,
                "calibration": {
                    "a1": {"x": 10.0, "y": 20.0, "z": 30.0},
                    "a2": {"x": 10.0, "y": 25.0, "z": 30.0},
                },
                "x_offset": 6.0,
                "y_offset": 5.0,
                "vial_model_name": "overridden_vial",
                "vial_height": 41.0,
                "vial_diameter": 11.0,
                "capacity_ul": 1200.0,
                "working_volume_ul": 950.0,
                "aliases": {"buffer": "A1", "catalyst": "B2"},
            }
        }
    }

    expanded = resolve_load_names(raw)
    entry = expanded["labware"]["reagents"]
    assert "load_name" not in entry
    assert entry["type"] == "vial_grid"
    assert entry["name"] == "reagents"
    assert entry["label"] == "Reagent bank"
    assert entry["vial_model_name"] == "overridden_vial"
    assert entry["capacity_ul"] == pytest.approx(1200.0)
    assert entry["working_volume_ul"] == pytest.approx(950.0)

    path = tmp_path / "definition_grid.yaml"
    path.write_text(
        dedent(
            """
            labware:
              reagents:
                load_name: ursa_9_vial_grid
                label: Reagent bank
                rows: 2
                columns: 2
                calibration:
                  a1: {x: 10.0, y: 20.0, z: 30.0}
                  a2: {x: 10.0, y: 25.0, z: 30.0}
                x_offset: 6.0
                y_offset: 5.0
                vial_model_name: overridden_vial
                vial_height: 41.0
                vial_diameter: 11.0
                capacity_ul: 1200.0
                working_volume_ul: 950.0
                aliases: {buffer: A1, catalyst: B2}
            """
        ),
        encoding="utf-8",
    )
    deck = load_deck_from_yaml(path)
    grid = deck.volume_labware["reagents"]

    assert isinstance(grid, VialGrid)
    assert list(grid.vials) == ["A1", "A2", "B1", "B2"]
    assert grid.label == "Reagent bank"
    assert grid.aliases == {"buffer": "A1", "catalyst": "B2"}
    assert all(vial.model_name == "overridden_vial" for vial in grid.vials.values())
    assert all(vial.height == pytest.approx(41.0) for vial in grid.vials.values())
    assert all(vial.diameter == pytest.approx(11.0) for vial in grid.vials.values())
    assert deck.resolve_coordinate("reagents.buffer") == Coordinate3D(
        x=10.0, y=20.0, z=30.0
    )


def test_ursa_vial_grid_definition_supplies_layout_and_vial_defaults(
    tmp_path: Path,
) -> None:
    deck = load_deck_from_yaml(
        _write_deck(
            tmp_path,
            "definition_defaults.yaml",
            """
            labware:
              reagents:
                load_name: ursa_9_vial_grid
                label: Reagent bank
                calibration:
                  a1: {x: 10.0, y: 20.0, z: 40.0}
                  a2: {x: 10.0, y: 53.0, z: 40.0}
                aliases:
                  buffer: A1
                  catalyst: A9
            """,
        )
    )

    grid = deck.volume_labware["reagents"]
    assert isinstance(grid, VialGrid)
    assert grid.name == "reagents"
    assert grid.label == "Reagent bank"
    assert grid.rows == 1
    assert grid.columns == 9
    assert list(grid.vials) == [f"A{index}" for index in range(1, 10)]
    assert grid.aliases == {"buffer": "A1", "catalyst": "A9"}
    assert grid.vials["A1"].location == Coordinate3D(x=10.0, y=20.0, z=40.0)
    assert grid.vials["A9"].location == Coordinate3D(x=10.0, y=284.0, z=40.0)
    assert all(vial.model_name == "20ml_vial" for vial in grid.vials.values())
    assert all(vial.height == pytest.approx(57.0) for vial in grid.vials.values())
    assert all(vial.diameter == pytest.approx(28.0) for vial in grid.vials.values())
    assert all(vial.capacity_ul == pytest.approx(20000.0) for vial in grid.vials.values())
    assert all(
        vial.working_volume_ul == pytest.approx(20000.0)
        for vial in grid.vials.values()
    )


def test_vial_grid_runtime_exposes_only_canonical_positions() -> None:
    a1 = _runtime_vial("A1")
    a2 = _runtime_vial("A2", x=6.0)
    grid = VialGrid(
        name="reagents",
        rows=1,
        columns=2,
        vials={"A1": a1, "A2": a2},
        aliases={"buffer": "A1"},
    )

    assert grid.canonical_position_ids == ("A1", "A2")
    assert grid.canonicalize_location_id("A1") == "A1"
    assert grid.canonicalize_location_id("buffer") == "A1"
    assert grid.get_vial("buffer") is a1
    assert grid.get_location("buffer") == a1.location
    assert grid.iter_positions() == {"A1": a1.location, "A2": a2.location}
    assert "buffer" not in grid.iter_positions()
    with pytest.raises(KeyError, match="missing"):
        grid.canonicalize_location_id("missing")


def test_vial_grid_rejects_empty_or_inconsistent_layouts_and_bad_aliases() -> None:
    a1 = _runtime_vial("A1")

    with pytest.raises(ValidationError, match="at least one vial"):
        VialGrid(name="empty", vials={})
    with pytest.raises(ValidationError, match="provided together"):
        VialGrid(name="half_grid", rows=1, vials={"A1": a1})
    with pytest.raises(ValidationError, match=r"rows\*columns"):
        VialGrid(name="wrong_count", rows=1, columns=2, vials={"A1": a1})
    with pytest.raises(ValidationError, match="conflicts with a canonical"):
        VialGrid(name="collision", vials={"A1": a1}, aliases={"A1": "A1"})
    with pytest.raises(ValidationError, match="unknown canonical"):
        VialGrid(name="unknown", vials={"A1": a1}, aliases={"buffer": "A2"})


def test_display_labels_are_optional_but_blank_labels_are_rejected() -> None:
    a1 = _runtime_vial("A1")
    with pytest.raises(ValidationError, match="label must be a non-empty"):
        VialGrid(name="reagents", label=" ", vials={"A1": a1})

    with pytest.raises(ValidationError, match="label must be a non-empty"):
        WellPlate(
            name="plate",
            label=" ",
            rows=1,
            columns=1,
            wells={"A1": Coordinate3D(x=1.0, y=2.0, z=3.0)},
        )


def test_vial_outer_geometry_is_optional_but_positive_when_provided() -> None:
    dimensionless = _runtime_vial("sample")
    assert dimensionless.height is None
    assert dimensionless.diameter is None
    assert dimensionless.geometry == BoundingBoxGeometry()

    with pytest.raises(ValidationError, match="height must be positive"):
        _runtime_vial("bad_height", height=-1.0)
    with pytest.raises(ValidationError, match="diameter must be positive"):
        _runtime_vial("bad_diameter", diameter=0.0)


def test_dimensionless_vial_grid_keeps_optional_outer_geometry_unset(
    tmp_path: Path,
) -> None:
    deck = load_deck_from_yaml(
        _write_deck(
            tmp_path,
            "dimensionless_grid.yaml",
            """
            labware:
              samples:
                type: vial_grid
                name: samples
                model_name: dimensionless_1x2
                rows: 1
                columns: 2
                calibration:
                  a1: {x: 1.0, y: 2.0, z: 3.0}
                  a2: {x: 6.0, y: 2.0, z: 3.0}
                x_offset: 5.0
                y_offset: 7.0
                vial_model_name: unknown_vial
                capacity_ul: 500.0
                working_volume_ul: 400.0
            """,
        )
    )

    grid = deck.volume_labware["samples"]
    assert isinstance(grid, VialGrid)
    assert list(grid.vials) == ["A1", "A2"]
    for vial in grid.vials.values():
        assert vial.height is None
        assert vial.diameter is None
        assert vial.geometry == BoundingBoxGeometry()


def test_legacy_vial_aliases_register_only_canonical_grid_rows(tmp_path: Path) -> None:
    deck = load_deck_from_yaml(
        _write_deck(tmp_path, "legacy_irregular.yaml", LEGACY_REGULAR_VIALS)
    )
    store = DataStore(":memory:")
    campaign_id = store.create_campaign("legacy grid persistence")

    register_deck_labware(store, campaign_id, deck)

    rows = store._conn.execute(
        "SELECT labware_key, well_id, total_volume_ul, working_volume_ul "
        "FROM labware WHERE campaign_id = ? ORDER BY labware_key, well_id",
        (campaign_id,),
    ).fetchall()
    store.close()

    assert [(row[0], row[1]) for row in rows] == [
        ("vial_holder__vials", "A1"),
        ("vial_holder__vials", "A2"),
        ("vial_holder__vials", "B1"),
        ("vial_holder__vials", "B2"),
    ]
    assert all(row[2] == pytest.approx(1000.0) for row in rows)
    assert all(row[3] == pytest.approx(900.0) for row in rows)
    assert not any(row[0].startswith("vial_holder.") for row in rows)


def _grid_positions(
    prefix: str,
    *,
    rows: int,
    columns: int,
    a1: tuple[float, float, float],
    column_delta: tuple[float, float],
    row_delta: tuple[float, float],
) -> dict[str, tuple[float, float, float]]:
    positions: dict[str, tuple[float, float, float]] = {prefix: a1}
    for row_index in range(rows):
        row = chr(ord("A") + row_index)
        for column_index in range(columns):
            positions[f"{prefix}.{row}{column_index + 1}"] = (
                a1[0] + row_delta[0] * row_index + column_delta[0] * column_index,
                a1[1] + row_delta[1] * row_index + column_delta[1] * column_index,
                a1[2],
            )
    return positions


def _current_deck_expected_positions() -> dict[str, dict[str, tuple[float, float, float]]]:
    expected = {
        "asmi_deck.yaml": _grid_positions(
            "plate", rows=8, columns=12, a1=(347.0, 42.0, 30.0),
            column_delta=(-9.0, 0.0), row_delta=(0.0, 9.0),
        ),
        "filmetrics_deck.yaml": _grid_positions(
            "plate_1", rows=8, columns=12, a1=(270.0, 140.0, 70.0),
            column_delta=(0.0, -9.0), row_delta=(-9.0, 0.0),
        ),
        "sharc_uv_deck.yaml": {
            "plate_holder": (0.0, 0.0, 0.0),
            "plate_holder.location": (0.0, 0.0, 0.0),
            "plate_holder.plate": (15.0, 17.0, 89.5),
            **_grid_positions(
                "plate_holder.plate", rows=8, columns=12,
                a1=(15.0, 17.0, 89.5), column_delta=(0.0, 9.0),
                row_delta=(9.0, 0.0),
            ),
        },
        "sterling_deck.yaml": {
            "vial_holder": (223.0, 159.0, 39.0),
            "vial_holder.location": (223.0, 159.0, 39.0),
            **{
                f"vial_holder.vial_{index}": (223.0, 25.0 + 33.5 * (index - 1), 57.0)
                for index in range(1, 9)
            },
        },
    }
    panda = {
        "well_plate_holder": (72.0, 34.0, 5.0),
        "well_plate_holder.location": (72.0, 34.0, 5.0),
        "well_plate_holder.plate": (92.0, 62.0, 26.0),
        **_grid_positions(
            "well_plate_holder.plate", rows=8, columns=12,
            a1=(92.0, 62.0, 26.0), column_delta=(0.0, 9.0),
            row_delta=(9.0, 0.0),
        ),
        **_grid_positions(
            "tip_rack_left", rows=2, columns=15,
            a1=(168.0, 58.0, 43.0), column_delta=(0.0, 8.5),
            row_delta=(8.5, 0.0),
        ),
        **_grid_positions(
            "tip_rack_right", rows=2, columns=15,
            a1=(236.0, 58.0, 43.0), column_delta=(0.0, 8.5),
            row_delta=(8.5, 0.0),
        ),
        "tip_rack_left.location": (168.0, 58.0, 43.0),
        "tip_rack_right.location": (236.0, 58.0, 43.0),
        "tip_disposal": (306.0, 118.0, 38.0),
        "tip_disposal.location": (306.0, 118.0, 38.0),
        "tip_disposal.discard": (306.0, 118.0, 38.0),
        "vial_holder": (366.0, 154.0, 50.0),
        "vial_holder.location": (366.0, 154.0, 50.0),
        **{
            f"vial_holder.vial_{index}": (366.0, 42.0 + 28.0 * (index - 1), 68.0)
            for index in range(1, 10)
        },
    }
    expected["panda_deck.yaml"] = panda
    return expected


@pytest.mark.parametrize(
    ("filename", "expected"),
    sorted(_current_deck_expected_positions().items()),
)
def test_current_deck_yaml_bytes_and_all_existing_addresses_are_unchanged(
    filename: str,
    expected: dict[str, tuple[float, float, float]],
) -> None:
    path = Path("configs/deck") / filename
    before = path.read_bytes()

    deck = load_deck_from_yaml(path)

    assert path.read_bytes() == before
    for address, xyz in expected.items():
        assert deck.resolve_coordinate(address) == Coordinate3D(
            x=xyz[0], y=xyz[1], z=xyz[2]
        ), address
