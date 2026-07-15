"""Read-only PANDA-BEAR SQLite access.

PANDA table names and SQL are confined to this module. The connection is
opened with ``mode=ro`` (refuses to write even if something upstream got
this wrong) and the source file's SHA-256 is hashed before and after the
read so a snapshot mutated mid-import is refused rather than silently
imported half-old, half-new.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path


class SourceChangedError(RuntimeError):
    """Raised when the source DB file's hash changes during the import read."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class VialRow:
    id: int
    position: str
    category: int
    name: str
    contents: dict
    volume: float
    capacity: float
    x: float
    y: float
    top: float
    active: bool


@dataclass(frozen=True)
class WellplateRow:
    id: int
    current: bool
    height: float
    capacity_ul: float


@dataclass(frozen=True)
class WellRow:
    plate_id: int
    well_id: str
    x: float
    y: float
    top: float
    height: float


@dataclass(frozen=True)
class TiprackRow:
    id: int
    rows: str
    cols: int
    pickup_height: float
    drop_x: float
    drop_y: float
    drop_z: float


@dataclass(frozen=True)
class TipRow:
    id: int
    rack_id: int
    tip_id: str
    tip_length: float | None
    pickup_height: float
    x: float
    y: float
    z: float


@dataclass(frozen=True)
class PandaBearSnapshot:
    db_path: str
    sha256: str
    vials: tuple[VialRow, ...]
    wellplates: tuple[WellplateRow, ...]
    wells: tuple[WellRow, ...]
    tipracks: tuple[TiprackRow, ...]
    tips: tuple[TipRow, ...]


def read_snapshot(db_path: str | Path) -> PandaBearSnapshot:
    """Read every table the importer needs, read-only, with a hash guard.

    Raises ``SourceChangedError`` if the file's SHA-256 differs before vs.
    after the read (concurrent mutation) -- the caller must not write any
    output in that case.
    """
    path = Path(db_path).expanduser().resolve()
    hash_before = sha256_file(path)

    uri = f"{path.as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        connection.execute("PRAGMA query_only = ON")
        vials = _read_vials(connection)
        wellplates = _read_wellplates(connection)
        current_plate_ids = tuple(w.id for w in wellplates if w.current)
        wells = _read_wells(connection, current_plate_ids)
        tipracks = _read_tipracks(connection)
        tips = _read_tips(connection)
    finally:
        connection.close()

    hash_after = sha256_file(path)
    if hash_before != hash_after:
        raise SourceChangedError(
            f"Source DB {path} changed while it was being read "
            f"(sha256 {hash_before} -> {hash_after}); aborting with no writes."
        )

    return PandaBearSnapshot(
        db_path=str(path),
        sha256=hash_after,
        vials=vials,
        wellplates=wellplates,
        wells=wells,
        tipracks=tipracks,
        tips=tips,
    )


def _read_vials(connection: sqlite3.Connection) -> tuple[VialRow, ...]:
    rows = connection.execute(
        "SELECT id, position, category, name, contents, volume, capacity, "
        "json_extract(coordinates, '$.x'), json_extract(coordinates, '$.y'), "
        "top, active "
        "FROM panda_vials ORDER BY id"
    ).fetchall()
    result = []
    for (
        vial_id, position, category, name, contents_raw, volume, capacity,
        x, y, top, active,
    ) in rows:
        result.append(
            VialRow(
                id=int(vial_id),
                position=str(position),
                category=int(category),
                name=str(name),
                contents=_load_json_object(contents_raw),
                volume=float(volume),
                capacity=float(capacity),
                x=float(x),
                y=float(y),
                top=float(top),
                active=bool(active),
            )
        )
    return tuple(result)


def _read_wellplates(connection: sqlite3.Connection) -> tuple[WellplateRow, ...]:
    rows = connection.execute(
        "SELECT wp.id, wp.current, CAST(wp.height AS REAL), wpt.capacity_ul "
        "FROM panda_wellplates wp "
        "JOIN panda_wellplate_types wpt ON wp.type_id = wpt.id "
        "ORDER BY wp.id"
    ).fetchall()
    return tuple(
        WellplateRow(
            id=int(plate_id),
            current=bool(current),
            height=float(height),
            capacity_ul=float(capacity_ul),
        )
        for plate_id, current, height, capacity_ul in rows
    )


def _read_wells(
    connection: sqlite3.Connection, plate_ids: tuple[int, ...],
) -> tuple[WellRow, ...]:
    if not plate_ids:
        return ()
    placeholders = ",".join("?" for _ in plate_ids)
    rows = connection.execute(
        "SELECT plate_id, well_id, json_extract(coordinates, '$.x'), "
        "json_extract(coordinates, '$.y'), top, height "
        f"FROM panda_well_hx WHERE plate_id IN ({placeholders}) "
        "ORDER BY plate_id, well_id",
        plate_ids,
    ).fetchall()
    return tuple(
        WellRow(
            plate_id=int(plate_id),
            well_id=str(well_id),
            x=float(x),
            y=float(y),
            top=float(top),
            height=float(height),
        )
        for plate_id, well_id, x, y, top, height in rows
    )


def _read_tipracks(connection: sqlite3.Connection) -> tuple[TiprackRow, ...]:
    rows = connection.execute(
        "SELECT id, rows, cols, pickup_height, "
        "json_extract(drop_coordinates, '$.x'), "
        "json_extract(drop_coordinates, '$.y'), "
        "json_extract(drop_coordinates, '$.z') "
        "FROM panda_tipracks ORDER BY id"
    ).fetchall()
    return tuple(
        TiprackRow(
            id=int(rack_id),
            rows=str(rows_str),
            cols=int(cols),
            pickup_height=float(pickup_height),
            drop_x=float(drop_x),
            drop_y=float(drop_y),
            drop_z=float(drop_z),
        )
        for rack_id, rows_str, cols, pickup_height, drop_x, drop_y, drop_z in rows
    )


def _read_tips(connection: sqlite3.Connection) -> tuple[TipRow, ...]:
    rows = connection.execute(
        "SELECT id, rack_id, tip_id, tip_length, pickup_height, "
        "json_extract(coordinates, '$.x'), json_extract(coordinates, '$.y'), "
        "json_extract(coordinates, '$.z') "
        "FROM panda_tips ORDER BY rack_id, id"
    ).fetchall()
    return tuple(
        TipRow(
            id=int(tip_id_pk),
            rack_id=int(rack_id),
            tip_id=str(tip_id),
            tip_length=None if tip_length is None else float(tip_length),
            pickup_height=float(pickup_height),
            x=float(x),
            y=float(y),
            z=float(z),
        )
        for tip_id_pk, rack_id, tip_id, tip_length, pickup_height, x, y, z in rows
    )


def _load_json_object(raw: str | None) -> dict:
    if raw is None:
        return {}
    decoded = json.loads(raw)
    return decoded if isinstance(decoded, dict) else {}
