"""Export ASMI indentation measurements as ASMI_new-compatible raw CSV files."""

from __future__ import annotations

import csv
import json
import re
import sqlite3
from pathlib import Path
from typing import Any


def export_asmi_raw_csvs(
    *,
    db_path: str,
    campaign_id: int,
    output_dir: str | Path,
) -> list[Path]:
    """Export ASMI measurements for a campaign as per-well raw CSV files.

    The output layout matches the raw measurement files consumed by
    ``projects/ASMI_new``: metadata rows, a blank separator, then sample rows
    with ``Timestamp(s), Z_Position(mm), Raw_Force(N), Corrected_Force(N)`` and
    an optional ``Direction`` column.
    """
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
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
    finally:
        conn.close()

    written: list[Path] = []
    for row in rows:
        path = destination / _filename_for_row(row)
        _write_asmi_new_csv(row, path)
        written.append(path)
    return written


def _write_asmi_new_csv(row: sqlite3.Row, path: Path) -> None:
    z_positions = _json_array(row["z_positions"], "z_positions")
    raw_forces = _json_array(row["raw_forces"], "raw_forces")
    corrected_forces = _json_array(row["corrected_forces"], "corrected_forces")
    timestamps = _json_array_or_default(
        row["sample_timestamps"],
        "sample_timestamps",
        default=[None] * len(z_positions),
    )
    directions = _json_array_or_default(
        row["directions"],
        "directions",
        default=[None] * len(z_positions),
    )
    _validate_equal_lengths(
        z_positions=z_positions,
        raw_forces=raw_forces,
        corrected_forces=corrected_forces,
        sample_timestamps=timestamps,
        directions=directions,
    )

    has_directions = any(direction not in (None, "") for direction in directions)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Test_Time", row["timestamp"]])
        writer.writerow(["Well", row["well_id"] or ""])
        writer.writerow(["Target_Z(mm)", _format_optional(row["z_target_mm"], 3)])
        writer.writerow(["Step_Size(mm)", _format_optional(row["step_size_mm"], 3)])
        writer.writerow(["Force_Limit(N)", _format_optional(row["force_limit_n"], 1)])
        writer.writerow(["Baseline_Force(N)", _format_optional(row["baseline_avg"], 3)])
        writer.writerow(["Baseline_Std(N)", _format_optional(row["baseline_std"], 3)])
        writer.writerow(["Force_Exceeded", str(bool(row["force_exceeded"]))])
        writer.writerow([])
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


def _filename_for_row(row: sqlite3.Row) -> str:
    well = row["well_id"] or f"measurement_{row['measurement_id']}"
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
        raise ValueError(f"ASMI field '{field_name}' is missing")
    parsed = json.loads(value) if isinstance(value, str) else value
    if not isinstance(parsed, list):
        raise ValueError(f"ASMI field '{field_name}' must be a JSON array")
    return parsed


def _json_array_or_default(
    value: Any,
    field_name: str,
    *,
    default: list[Any],
) -> list[Any]:
    if value is None:
        return list(default)
    return _json_array(value, field_name)


def _validate_equal_lengths(**arrays: list[Any]) -> None:
    lengths = {name: len(value) for name, value in arrays.items()}
    expected = next(iter(lengths.values()), 0)
    mismatches = {
        name: length for name, length in lengths.items()
        if length != expected
    }
    if mismatches:
        details = ", ".join(f"{name}={length}" for name, length in lengths.items())
        raise ValueError(f"ASMI measurement arrays must have equal lengths: {details}")


def _format_optional(value: Any, digits: int) -> str:
    if value is None:
        return ""
    return f"{float(value):.{digits}f}"
