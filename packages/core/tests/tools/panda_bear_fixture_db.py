"""Synthetic PANDA-BEAR SQLite fixture builder for import tests.

Schema (``CREATE TABLE`` text) is copied verbatim from the production
snapshot's ``sqlite_master`` so generated columns (``top``, ``bottom``,
``volume_height``) behave identically to the real DB. No real snapshot data
is included or committed -- every row below is synthetic.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

DDL = """
CREATE TABLE panda_vials (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    position       TEXT,
    category       INTEGER,
    name           TEXT,
    contents       TEXT,
    viscosity_cp   REAL,
    concentration  REAL,
    density        REAL,
    height         REAL    DEFAULT (57.0),
    radius         REAL    DEFAULT (14.0),
    volume         REAL    DEFAULT (20000.0),
    capacity       REAL    DEFAULT (20000.0),
    contamination  INTEGER DEFAULT (0),
    coordinates    TEXT,
    base_thickness REAL    DEFAULT (1.0),
    dead_volume    REAL    DEFAULT (1000.0),
    volume_height  REAL    GENERATED ALWAYS AS (round(coalesce(json_extract(coordinates, '$.z'), 0) + base_thickness + (volume / (pi() * power(radius, 2) ) ), 2) ) STORED,
    bottom         REAL    GENERATED ALWAYS AS (round(coalesce(json_extract(coordinates, '$.z'), 0) + base_thickness + (dead_volume / (pi() * power(radius, 2) ) ), 2) ) STORED,
    top            REAL    GENERATED ALWAYS AS (round(coalesce(json_extract(coordinates, '$.z'), 0) + base_thickness + height, 2) ) STORED,
    updated        TEXT    DEFAULT (CURRENT_TIMESTAMP),
    active         INTEGER DEFAULT (1),
    panda_unit_id  INTEGER
);

CREATE TABLE panda_wellplate_types (
    id                   INTEGER PRIMARY KEY,
    substrate            TEXT,
    gasket               TEXT,
    count                INTEGER,
    shape                TEXT,
    radius_mm            REAL,
    x_spacing            REAL,
    gasket_height_mm     REAL,
    max_liquid_height_mm REAL,
    capacity_ul          REAL,
    rows                 TEXT    DEFAULT ABCDEFGH,
    cols                 INTEGER DEFAULT (12),
    y_spacing            REAL,
    gasket_length_mm     REAL,
    gasket_width_mm      REAL,
    x_offset             REAL,
    y_offset             REAL,
    base_thickness       REAL    DEFAULT (1)
);

CREATE TABLE panda_wellplates (
    id             INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    type_id        INTEGER REFERENCES panda_wellplate_types (id),
    current        BOOLEAN DEFAULT 0,
    a1_x           NUMERIC DEFAULT ( -221.75),
    a1_y           NUMERIC DEFAULT ( -78.5),
    orientation    INTEGER DEFAULT (0),
    rows           INTEGER DEFAULT (13),
    cols           TEXT    DEFAULT ABCDEFGH,
    bottom         NUMERIC GENERATED ALWAYS AS ( (round(coalesce(json_extract(coordinates, '$.z'), 0) + base_thickness, 2) ) ) STORED,
    top            NUMERIC GENERATED ALWAYS AS ( (round(coalesce(json_extract(coordinates, '$.z'), 0) + base_thickness + height, 2) ) ) STORED,
    echem_height   NUMERIC DEFAULT ( -70),
    image_height   REAL    DEFAULT (0),
    coordinates    TEXT,
    base_thickness REAL,
    height,
    name,
    panda_unit_id  INTEGER
);

CREATE TABLE panda_well_hx (
    plate_id       INTEGER,
    well_id        TEXT,
    experiment_id  INTEGER,
    project_id     INTEGER,
    status         TEXT,
    contents       TEXT,
    volume         REAL,
    coordinates    TEXT,
    base_thickness REAL    DEFAULT (1),
    height         REAL    DEFAULT (6),
    radius         REAL    DEFAULT (3.25),
    capacity       REAL    DEFAULT (150),
    contamination  INTEGER DEFAULT (0),
    dead_volume    REAL    DEFAULT (0.01),
    name           TEXT,
    top            REAL    GENERATED ALWAYS AS (round(json_extract(coordinates, '$.z') + base_thickness + height, 2) ) STORED,
    bottom         REAL    GENERATED ALWAYS AS (round(json_extract(coordinates, '$.z') + base_thickness, 2) ) STORED,
    volume_height  REAL    GENERATED ALWAYS AS (round(json_extract(coordinates, '$.z') + base_thickness + round(dead_volume / (pi() * radius * radius), 3), 2) ) STORED,
    status_date    TEXT    DEFAULT (CURRENT_TIMESTAMP),
    updated        TEXT    DEFAULT (CURRENT_TIMESTAMP),
    PRIMARY KEY (plate_id, well_id)
);

CREATE TABLE panda_tiprack_types (
    id INTEGER PRIMARY KEY,
    count INTEGER NOT NULL,
    rows TEXT NOT NULL,
    cols INTEGER NOT NULL,
    shape TEXT NOT NULL,
    radius_mm FLOAT NOT NULL,
    y_spacing FLOAT NOT NULL,
    x_spacing FLOAT NOT NULL,
    rack_length_mm FLOAT NOT NULL,
    rack_width_mm FLOAT NOT NULL,
    rack_height_mm FLOAT NOT NULL,
    x_offset FLOAT NOT NULL,
    y_offset FLOAT NOT NULL
);

CREATE TABLE panda_tipracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type_id INTEGER NOT NULL,
    current BOOLEAN DEFAULT FALSE,
    a1_x FLOAT NOT NULL,
    a1_y FLOAT NOT NULL,
    orientation INTEGER DEFAULT 0,
    rows TEXT DEFAULT 'ABCDEFGH',
    cols INTEGER DEFAULT 12,
    pickup_height FLOAT NOT NULL,
    panda_unit_id INTEGER NOT NULL,
    drop_coordinates JSON
);

CREATE TABLE panda_tips (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  rack_id INTEGER NOT NULL,
  tip_id TEXT NOT NULL,
  tip_length REAL DEFAULT 0,
  pickup_height REAL DEFAULT 0,
  radius_mm REAL DEFAULT 0,
  capacity INTEGER DEFAULT 300,
  volume REAL DEFAULT 0,
  dead_volume REAL DEFAULT 0,
  contamination INTEGER DEFAULT 0,
  coordinates TEXT,
  drop_coordinates TEXT DEFAULT '{}',
  name TEXT DEFAULT 'default',
  status TEXT DEFAULT 'ready',
  status_date TEXT DEFAULT '',
  updated TEXT DEFAULT '',
  UNIQUE(rack_id, tip_id)
);
"""


def _coords(x: float, y: float, z: float) -> str:
    return json.dumps({"x": x, "y": y, "z": z})


def vial_row(
    *,
    id: int,
    position: str,
    category: int,
    x: float,
    y: float,
    z: float,
    name: str = "fluid",
    contents: dict | None = None,
    volume: float = 1000.0,
    capacity: float = 5000.0,
    height: float = 57.0,
    base_thickness: float = 1.0,
    active: bool = True,
) -> dict[str, Any]:
    return {
        "id": id,
        "position": position,
        "category": category,
        "name": name,
        "contents": json.dumps(contents if contents is not None else {name: volume}),
        "volume": volume,
        "capacity": capacity,
        "height": height,
        "base_thickness": base_thickness,
        "coordinates": _coords(x, y, z),
        "active": 1 if active else 0,
    }


def well_row(
    *,
    plate_id: int,
    well_id: str,
    x: float,
    y: float,
    z: float,
    height: float = 5.0,
    base_thickness: float = 1.0,
    radius: float = 2.5,
    capacity: float = 100.0,
) -> dict[str, Any]:
    return {
        "plate_id": plate_id,
        "well_id": well_id,
        "coordinates": _coords(x, y, z),
        "base_thickness": base_thickness,
        "height": height,
        "radius": radius,
        "capacity": capacity,
    }


def tip_row(
    *,
    id: int,
    rack_id: int,
    tip_id: str,
    x: float,
    y: float,
    z: float,
    tip_length: float | None = 50.0,
    radius_mm: float = 3.8,
) -> dict[str, Any]:
    return {
        "id": id,
        "rack_id": rack_id,
        "tip_id": tip_id,
        "tip_length": tip_length,
        "pickup_height": z,
        "radius_mm": radius_mm,
        "coordinates": _coords(x, y, z),
        "drop_coordinates": "{}",
    }


def build_fixture_db(
    path: Path,
    *,
    vials: list[dict],
    wellplate_types: list[dict],
    wellplates: list[dict],
    wells: list[dict],
    tipracks: list[dict],
    tips: list[dict],
) -> Path:
    """Create a synthetic PANDA-BEAR snapshot at *path* from row dicts."""
    if path.exists():
        path.unlink()
    connection = sqlite3.connect(path)
    try:
        connection.executescript(DDL)
        for row in vials:
            _insert(connection, "panda_vials", row)
        for row in wellplate_types:
            _insert(connection, "panda_wellplate_types", row)
        for row in wellplates:
            _insert(connection, "panda_wellplates", row)
        for row in wells:
            _insert(connection, "panda_well_hx", row)
        for row in tipracks:
            _insert(connection, "panda_tipracks", row)
        for row in tips:
            _insert(connection, "panda_tips", row)
        connection.commit()
    finally:
        connection.close()
    return path


def _insert(connection: sqlite3.Connection, table: str, row: dict[str, Any]) -> None:
    columns = ", ".join(row.keys())
    placeholders = ", ".join("?" for _ in row)
    connection.execute(
        f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", tuple(row.values()),
    )


def default_wellplate_type(*, id: int = 1, capacity_ul: float = 100.0) -> dict:
    return {"id": id, "capacity_ul": capacity_ul}


def default_wellplate(*, id: int = 10, type_id: int = 1, current: bool = True, height: float = 5.0) -> dict:
    return {"id": id, "type_id": type_id, "current": 1 if current else 0, "height": height}


def default_tiprack(
    *,
    id: int = 1,
    rows: str = "AB",
    cols: int = 2,
    pickup_height: float = -20.0,
    drop_x: float = -90.0,
    drop_y: float = -90.0,
    drop_z: float = -20.0,
) -> dict:
    return {
        "id": id,
        "type_id": 1,
        "rows": rows,
        "cols": cols,
        "a1_x": 0.0,
        "a1_y": 0.0,
        "pickup_height": pickup_height,
        "panda_unit_id": 1,
        "drop_coordinates": _coords(drop_x, drop_y, drop_z),
    }


def default_2x2_wells(plate_id: int = 10) -> list[dict]:
    """A1/A2/B1/B2 grid: columns step -10 in y, rows step -10 in x."""
    return [
        well_row(plate_id=plate_id, well_id="A1", x=-60.0, y=-50.0, z=-30.0),
        well_row(plate_id=plate_id, well_id="A2", x=-60.0, y=-60.0, z=-30.0),
        well_row(plate_id=plate_id, well_id="B1", x=-70.0, y=-50.0, z=-30.0),
        well_row(plate_id=plate_id, well_id="B2", x=-70.0, y=-60.0, z=-30.0),
    ]


def default_2x2_tips(rack_id: int = 1, tip_length: float | None = 50.0) -> list[dict]:
    """A1/A2/B1/B2 tip grid: columns step -10 in y, rows step -10 in x."""
    return [
        tip_row(id=1, rack_id=rack_id, tip_id="A1", x=-50.0, y=-30.0, z=-20.0, tip_length=tip_length),
        tip_row(id=2, rack_id=rack_id, tip_id="A2", x=-50.0, y=-40.0, z=-20.0, tip_length=tip_length),
        tip_row(id=3, rack_id=rack_id, tip_id="B1", x=-60.0, y=-30.0, z=-20.0, tip_length=tip_length),
        tip_row(id=4, rack_id=rack_id, tip_id="B2", x=-60.0, y=-40.0, z=-20.0, tip_length=tip_length),
    ]


def default_vials() -> list[dict]:
    return [
        vial_row(id=1, position="s1", category=0, x=-50.0, y=-10.0, z=-70.0, name="water", volume=1000.0),
        vial_row(id=2, position="w1", category=1, x=-50.0, y=-40.0, z=-70.0, name="waste", volume=500.0),
        vial_row(id=3, position="e1", category=2, x=-350.0, y=-270.0, z=-70.0, name="ebath", volume=2000.0),
    ]


def build_happy_path_db(path: Path) -> Path:
    """A minimal, internally-consistent snapshot with no conflicts at all.

    All coordinates land within the real cub_xl_panda_home_origin.yaml
    working volume (x[-401,0] y[-301,0] z[-85,0]) under the zero-offset
    identity conversion used by most tests, so it also exercises
    ``run_setup_validation`` cleanly end-to-end.
    """
    return build_fixture_db(
        path,
        vials=default_vials(),
        wellplate_types=[default_wellplate_type()],
        wellplates=[default_wellplate()],
        wells=default_2x2_wells(),
        tipracks=[default_tiprack()],
        tips=default_2x2_tips(),
    )
