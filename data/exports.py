"""Campaign result summaries and ZIP exports for CubOS runtime data."""

from __future__ import annotations

import base64
import csv
import io
import json
import re
import sqlite3
import zipfile
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MeasurementTable:
    instrument: str
    table: str


@dataclass(frozen=True)
class CampaignSummary:
    campaign_id: int
    campaign_description: str
    created_at: str
    latest_measurement_at: str | None
    experiment_count: int
    well_count: int
    measurement_count: int
    measurement_counts: dict[str, int]
    asmi_measurement_count: int


MEASUREMENT_TABLES = (
    MeasurementTable("uvvis", "uvvis_measurements"),
    MeasurementTable("filmetrics", "filmetrics_measurements"),
    MeasurementTable("uv_curing", "uv_curing_measurements"),
    MeasurementTable("camera", "camera_measurements"),
    MeasurementTable("asmi", "asmi_measurements"),
    MeasurementTable("potentiostat", "potentiostat_measurements"),
)


class DataExportError(Exception):
    """Base class for CubOS data export/query failures."""


class DataDatabaseNotFoundError(DataExportError):
    """Raised when the configured runtime database is missing."""


class DataSchemaError(DataExportError):
    """Raised when a database exists but lacks required CubOS tables."""


class CampaignNotFoundError(DataExportError):
    """Raised when a campaign-specific export targets an unknown campaign."""


class MeasurementExportNotFoundError(DataExportError):
    """Raised when the requested export has no measurement rows."""


class MeasurementDataError(DataExportError):
    """Raised when stored measurement rows are malformed."""


def list_campaign_summaries(db_path: str | Path) -> list[CampaignSummary]:
    """Return campaign rows with measurement metadata for the CubOS UI/API."""
    path = Path(db_path).expanduser().resolve()
    if not path.is_file():
        return []

    with closing(_connect(path)) as conn:
        _ensure_tables(conn, ("campaigns", "experiments"))
        rows = conn.execute(
            """
            SELECT
                c.id AS campaign_id,
                c.description AS campaign_description,
                c.created_at,
                COUNT(DISTINCT e.id) AS experiment_count,
                COUNT(DISTINCT e.well_id) AS well_count
            FROM campaigns c
            LEFT JOIN experiments e ON e.campaign_id = c.id
            GROUP BY c.id, c.description, c.created_at
            """
        ).fetchall()
        present_tables = _present_tables(conn)
        measurement_counts = _campaign_measurement_counts(conn, present_tables)
        latest_measurements = _campaign_latest_measurements(conn, present_tables)

    summaries = []
    for row in rows:
        campaign_id = row["campaign_id"]
        counts = {
            table.instrument: measurement_counts.get(campaign_id, {}).get(
                table.instrument, 0,
            )
            for table in MEASUREMENT_TABLES
        }
        summaries.append(
            CampaignSummary(
                **dict(row),
                latest_measurement_at=latest_measurements.get(campaign_id),
                measurement_count=sum(counts.values()),
                measurement_counts=counts,
                asmi_measurement_count=counts["asmi"],
            )
        )

    summaries.sort(
        key=lambda summary: (
            summary.latest_measurement_at or summary.created_at,
            summary.campaign_id,
        ),
        reverse=True,
    )
    return summaries


def export_campaign_measurements_zip(db_path: str | Path, campaign_id: int) -> bytes:
    """Export non-empty instrument measurement tables for a campaign as CSV."""
    path = Path(db_path).expanduser().resolve()
    if not path.is_file():
        raise DataDatabaseNotFoundError(f"Data database not found: {path}")

    archive = io.BytesIO()
    with closing(_connect(path)) as conn:
        _ensure_tables(conn, ("campaigns", "experiments"))
        if not _campaign_exists(conn, campaign_id):
            raise CampaignNotFoundError(f"Campaign {campaign_id} not found")

        present_tables = _present_tables(conn)
        table_exports = [
            (table, _measurement_table_rows(conn, table, campaign_id))
            for table in MEASUREMENT_TABLES
            if table.table in present_tables
        ]
        table_exports = [
            (table, rows) for table, rows in table_exports
            if len(rows) > 0
        ]
        measurement_count = sum(len(rows) for _, rows in table_exports)
        if measurement_count == 0:
            raise MeasurementExportNotFoundError(
                f"No instrument measurements found for campaign {campaign_id}"
            )

        with zipfile.ZipFile(
            archive, mode="w", compression=zipfile.ZIP_DEFLATED,
        ) as zip_handle:
            manifest_rows = []
            for table, rows in table_exports:
                filename = f"measurements/{table.table}.csv"
                zip_handle.writestr(
                    filename,
                    _measurement_table_csv(conn, table.table, rows),
                )
                manifest_rows.append(
                    {
                        "instrument": table.instrument,
                        "table": table.table,
                        "row_count": len(rows),
                        "file": filename,
                    }
                )
            zip_handle.writestr("manifest.csv", _manifest_csv(manifest_rows))
            zip_handle.writestr(
                "experiments.csv",
                _experiments_csv(conn, campaign_id),
            )
    return archive.getvalue()


def export_campaign_asmi_zip(db_path: str | Path, campaign_id: int) -> bytes:
    """Export a campaign's ASMI measurements as raw CSV files plus metadata."""
    path = Path(db_path).expanduser().resolve()
    if not path.is_file():
        raise DataDatabaseNotFoundError(f"Data database not found: {path}")

    with closing(_connect(path)) as conn:
        _ensure_tables(conn, ("experiments", "asmi_measurements"))
        rows = conn.execute(
            """
            SELECT
                m.id AS measurement_id,
                m.sample_timestamps,
                m.z_positions,
                m.raw_forces,
                m.corrected_forces,
                m.directions,
                m.baseline_avg,
                m.baseline_std,
                m.force_exceeded,
                m.data_points,
                m.step_size_mm,
                m.z_target_mm,
                m.force_limit_n,
                m.timestamp,
                e.well_id
            FROM asmi_measurements m
            JOIN experiments e ON e.id = m.experiment_id
            WHERE e.campaign_id = ?
            ORDER BY m.id
            """,
            (campaign_id,),
        ).fetchall()

    if not rows:
        raise MeasurementExportNotFoundError(
            f"No ASMI measurement found for campaign {campaign_id}"
        )

    archive = io.BytesIO()
    with zipfile.ZipFile(
        archive, mode="w", compression=zipfile.ZIP_DEFLATED,
    ) as zip_handle:
        zip_handle.writestr("metadata.csv", _metadata_csv(rows))
        for row in rows:
            zip_handle.writestr(_filename_for_row(row), _raw_samples_csv(row))
    return archive.getvalue()


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_tables(conn: sqlite3.Connection, tables: tuple[str, ...]) -> None:
    present = _present_tables(conn)
    missing = [table for table in tables if table not in present]
    if missing:
        raise DataSchemaError(
            f"Data database is missing table(s): {', '.join(missing)}"
        )


def _present_tables(conn: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'",
        ).fetchall()
    }


def _campaign_exists(conn: sqlite3.Connection, campaign_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM campaigns WHERE id = ?",
        (campaign_id,),
    ).fetchone()
    return row is not None


def _campaign_measurement_counts(
    conn: sqlite3.Connection,
    present_tables: set[str],
) -> dict[int, dict[str, int]]:
    counts: dict[int, dict[str, int]] = {}
    for table in MEASUREMENT_TABLES:
        if table.table not in present_tables:
            continue
        rows = conn.execute(
            f"""
            SELECT e.campaign_id, COUNT(m.id) AS measurement_count
            FROM {table.table} m
            JOIN experiments e ON e.id = m.experiment_id
            GROUP BY e.campaign_id
            """
        ).fetchall()
        for row in rows:
            campaign_counts = counts.setdefault(row["campaign_id"], {})
            campaign_counts[table.instrument] = row["measurement_count"]
    return counts


def _campaign_latest_measurements(
    conn: sqlite3.Connection,
    present_tables: set[str],
) -> dict[int, str]:
    latest: dict[int, str] = {}
    for table in MEASUREMENT_TABLES:
        if table.table not in present_tables:
            continue
        rows = conn.execute(
            f"""
            SELECT e.campaign_id, MAX(m.timestamp) AS latest_measurement_at
            FROM {table.table} m
            JOIN experiments e ON e.id = m.experiment_id
            GROUP BY e.campaign_id
            """
        ).fetchall()
        for row in rows:
            timestamp = row["latest_measurement_at"]
            if timestamp is None:
                continue
            campaign_id = row["campaign_id"]
            if campaign_id not in latest or timestamp > latest[campaign_id]:
                latest[campaign_id] = timestamp
    return latest


def _measurement_table_rows(
    conn: sqlite3.Connection,
    table: MeasurementTable,
    campaign_id: int,
) -> list[sqlite3.Row]:
    return conn.execute(
        f"""
        SELECT
            m.*,
            e.labware_name AS experiment_labware_name,
            e.well_id AS experiment_well_id,
            e.contents AS experiment_contents,
            e.created_at AS experiment_created_at
        FROM {table.table} m
        JOIN experiments e ON e.id = m.experiment_id
        WHERE e.campaign_id = ?
        ORDER BY m.id
        """,
        (campaign_id,),
    ).fetchall()


def _measurement_table_csv(
    conn: sqlite3.Connection,
    table_name: str,
    rows: list[sqlite3.Row],
) -> str:
    table_columns = _table_columns(conn, table_name)
    columns = [
        *table_columns,
        "experiment_labware_name",
        "experiment_well_id",
        "experiment_contents",
        "experiment_created_at",
    ]
    return _rows_csv(columns, rows)


def _experiments_csv(conn: sqlite3.Connection, campaign_id: int) -> str:
    columns = _table_columns(conn, "experiments")
    rows = conn.execute(
        """
        SELECT *
        FROM experiments
        WHERE campaign_id = ?
        ORDER BY id
        """,
        (campaign_id,),
    ).fetchall()
    return _rows_csv(columns, rows)


def _table_columns(conn: sqlite3.Connection, table_name: str) -> list[str]:
    return [
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    ]


def _rows_csv(columns: list[str], rows: list[sqlite3.Row]) -> str:
    handle = io.StringIO()
    writer = csv.writer(handle, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_format_cell(row[column]) for column in columns])
    return handle.getvalue()


def _manifest_csv(rows: list[dict[str, Any]]) -> str:
    columns = ["instrument", "table", "row_count", "file"]
    handle = io.StringIO()
    writer = csv.DictWriter(handle, columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return handle.getvalue()


def _format_cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return "base64:" + base64.b64encode(value).decode("ascii")
    if isinstance(value, str):
        return _format_json_text(value)
    return value


def _format_json_text(value: str) -> str:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return value
    if isinstance(parsed, (list, dict)):
        return json.dumps(parsed, ensure_ascii=False)
    return value


def _raw_samples_csv(row: sqlite3.Row) -> str:
    timestamps, z_positions, raw_forces, corrected_forces, directions = _sample_arrays(row)
    has_directions = any(direction not in (None, "") for direction in directions)
    handle = io.StringIO()
    writer = csv.writer(handle, lineterminator="\n")
    header = [
        "Timestamp(s)",
        "Z_Position(mm)",
        "Raw_Force(N)",
        "Corrected_Force(N)",
    ]
    if has_directions:
        header.append("Direction")
    writer.writerow(header)

    for timestamp, z_pos, raw_force, corrected_force, direction in zip(
        timestamps,
        z_positions,
        raw_forces,
        corrected_forces,
        directions,
    ):
        sample_row = [
            _format_optional(timestamp, 3),
            _format_optional(z_pos, 3),
            _format_optional(raw_force, 3),
            _format_optional(corrected_force, 3),
        ]
        if has_directions:
            sample_row.append("" if direction is None else str(direction))
        writer.writerow(sample_row)
    return handle.getvalue()


def _metadata_csv(rows: list[sqlite3.Row]) -> str:
    handle = io.StringIO()
    writer = csv.writer(handle, lineterminator="\n")
    writer.writerow(
        [
            "File",
            "Measurement_ID",
            "Test_Time",
            "Well",
            "Target_Z(mm)",
            "Step_Size(mm)",
            "Force_Limit(N)",
            "Baseline_Force(N)",
            "Baseline_Std(N)",
            "Force_Exceeded",
            "Data_Points",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                _filename_for_row(row),
                row["measurement_id"],
                row["timestamp"],
                row["well_id"] or "",
                _format_optional(row["z_target_mm"], 3),
                _format_optional(row["step_size_mm"], 3),
                _format_optional(row["force_limit_n"], 1),
                _format_optional(row["baseline_avg"], 3),
                _format_optional(row["baseline_std"], 3),
                str(bool(row["force_exceeded"])),
                row["data_points"],
            ]
        )
    return handle.getvalue()


def _sample_arrays(
    row: sqlite3.Row,
) -> tuple[list[Any], list[Any], list[Any], list[Any], list[Any]]:
    z_positions = _json_array(row["z_positions"], "z_positions")
    raw_forces = _json_array(row["raw_forces"], "raw_forces")
    corrected_forces = _json_array(row["corrected_forces"], "corrected_forces")
    timestamps = _json_array(row["sample_timestamps"], "sample_timestamps")
    directions = _json_array(row["directions"], "directions")
    _validate_equal_lengths(
        z_positions=z_positions,
        raw_forces=raw_forces,
        corrected_forces=corrected_forces,
        sample_timestamps=timestamps,
        directions=directions,
    )
    return timestamps, z_positions, raw_forces, corrected_forces, directions


def _filename_for_row(row: sqlite3.Row) -> str:
    well = row["well_id"] or f"experiment_{row['measurement_id']}"
    timestamp = _timestamp_suffix(str(row["timestamp"]))
    return f"well_{well}_{timestamp}.csv"


def _timestamp_suffix(timestamp: str) -> str:
    match = re.match(
        r"(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})",
        timestamp,
    )
    if match is None:
        safe = re.sub(r"[^0-9A-Za-z]+", "_", timestamp).strip("_")
        return safe or "unknown_time"
    return "".join(match.groups()[:3]) + "_" + "".join(match.groups()[3:])


def _json_array(value: Any, field_name: str) -> list[Any]:
    if value is None:
        raise MeasurementDataError(f"ASMI field '{field_name}' is missing")
    parsed = json.loads(value) if isinstance(value, str) else value
    if not isinstance(parsed, list):
        raise MeasurementDataError(
            f"ASMI field '{field_name}' must be a JSON array"
        )
    return parsed


def _validate_equal_lengths(**arrays: list[Any]) -> None:
    lengths = {name: len(value) for name, value in arrays.items()}
    expected = next(iter(lengths.values()), 0)
    mismatches = {
        name: length for name, length in lengths.items()
        if length != expected
    }
    if mismatches:
        details = ", ".join(f"{name}={length}" for name, length in lengths.items())
        raise MeasurementDataError(
            f"ASMI measurement arrays must have equal lengths: {details}"
        )


def _format_optional(value: Any, digits: int) -> str:
    if value is None:
        return ""
    return f"{float(value):.{digits}f}"
