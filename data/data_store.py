"""SQLite-backed data store for self-driving lab campaigns."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any, List, Optional, Union

from instruments.asmi.models import MeasurementResult as ASMIMeasurementResult
from instruments.filmetrics.models import MeasurementResult
from instruments.uvvis_ccs.models import UVVisSpectrum
from protocol_engine.measurements import InstrumentMeasurement, MeasurementType

DATA_DB_PATH_ENV = "CUBOS_DATA_DB_PATH"
SQLITE_MEMORY_DATABASE = ":memory:"


def default_database_path() -> Path:
    """Return the default SQLite path for CubOS runtime data."""
    override = os.environ.get(DATA_DB_PATH_ENV)
    if override:
        return Path(override).expanduser()
    return Path(__file__).resolve().parent / "databases" / "panda_data.db"

_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS campaigns (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    description     TEXT    NOT NULL,
    deck_config     TEXT,
    board_config    TEXT,
    gantry_config   TEXT,
    protocol_config TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    status          TEXT    NOT NULL DEFAULT 'running'
);

CREATE TABLE IF NOT EXISTS experiments (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id  INTEGER NOT NULL REFERENCES campaigns(id),
    labware_name TEXT    NOT NULL,
    well_id      TEXT,
    contents     TEXT,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS uvvis_measurements (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id     INTEGER NOT NULL REFERENCES experiments(id),
    wavelengths       TEXT    NOT NULL,
    intensities       TEXT    NOT NULL,
    integration_time_s REAL   NOT NULL,
    timestamp         TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS filmetrics_measurements (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id   INTEGER NOT NULL REFERENCES experiments(id),
    thickness_nm    REAL,
    goodness_of_fit REAL,
    timestamp       TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS camera_measurements (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id INTEGER NOT NULL REFERENCES experiments(id),
    image_path    TEXT    NOT NULL,
    timestamp     TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS asmi_measurements (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id   INTEGER NOT NULL REFERENCES experiments(id),
    sample_timestamps TEXT NOT NULL,
    z_positions     TEXT    NOT NULL,
    raw_forces      TEXT    NOT NULL,
    corrected_forces TEXT   NOT NULL,
    directions      TEXT    NOT NULL,
    baseline_avg    REAL    NOT NULL,
    baseline_std    REAL    NOT NULL,
    force_exceeded  INTEGER NOT NULL DEFAULT 0,
    data_points     INTEGER NOT NULL,
    step_size_mm    REAL    NOT NULL,
    z_target_mm     REAL    NOT NULL,
    force_limit_n   REAL    NOT NULL,
    timestamp       TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS potentiostat_measurements (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id     INTEGER NOT NULL REFERENCES experiments(id),
    technique         TEXT    NOT NULL,
    time_s            TEXT    NOT NULL,
    voltage_v         TEXT    NOT NULL,
    current_a         TEXT,
    sample_period_s   REAL,
    duration_s        REAL,
    step_potential_v  REAL,
    step_current_a    REAL,
    scan_rate_v_s     REAL,
    step_size_v       REAL,
    cycles            INTEGER,
    vendor            TEXT,
    device_id         TEXT,
    channel           INTEGER,
    started_at        TEXT,
    stopped_at        TEXT,
    aborted           INTEGER,
    stop_reason       TEXT,
    timestamp         TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS labware (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id       INTEGER NOT NULL REFERENCES campaigns(id),
    labware_key       TEXT    NOT NULL,
    labware_type      TEXT    NOT NULL,
    well_id           TEXT,
    total_volume_ul   REAL    NOT NULL,
    working_volume_ul REAL    NOT NULL,
    current_volume_ul REAL    NOT NULL DEFAULT 0.0,
    contents          TEXT,
    updated_at        TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(campaign_id, labware_key, well_id)
);
"""


class DataStore:
    """Local SQLite data store for experiment campaigns and measurements."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        resolved_path = default_database_path() if db_path is None else db_path
        if str(resolved_path) == SQLITE_MEMORY_DATABASE:
            sqlite_path = SQLITE_MEMORY_DATABASE
        else:
            path = Path(resolved_path).expanduser()
            path.parent.mkdir(parents=True, exist_ok=True)
            sqlite_path = str(path)
        self._conn = sqlite3.connect(sqlite_path)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._create_tables()

    def _create_tables(self) -> None:
        self._conn.executescript(_SCHEMA_SQL)

    def create_campaign(
        self,
        description: str,
        deck_config: Optional[str] = None,
        board_config: Optional[str] = None,
        gantry_config: Optional[str] = None,
        protocol_config: Optional[str] = None,
    ) -> int:
        cursor = self._conn.execute(
            "INSERT INTO campaigns (description, deck_config, board_config, "
            "gantry_config, protocol_config) VALUES (?, ?, ?, ?, ?)",
            (description, deck_config, board_config, gantry_config, protocol_config),
        )
        self._conn.commit()
        return cursor.lastrowid

    def create_experiment(
        self,
        campaign_id: int,
        labware_name: str,
        well_id: Optional[str],
        contents_json: Optional[str] = None,
    ) -> int:
        cursor = self._conn.execute(
            "INSERT INTO experiments (campaign_id, labware_name, well_id, contents) "
            "VALUES (?, ?, ?, ?)",
            (campaign_id, labware_name, well_id, contents_json),
        )
        self._conn.commit()
        return cursor.lastrowid

    def log_measurement(
        self,
        experiment_id: int,
        result: Union[InstrumentMeasurement, UVVisSpectrum, MeasurementResult, str],
    ) -> int:
        """Log a measurement result, dispatching by type.

        Args:
            experiment_id: FK to the experiments table.
            result: An InstrumentMeasurement or measurement value.

        Returns:
            The newly inserted measurement row ID.

        Raises:
            TypeError: If *result* is not a recognised measurement type.
        """
        if isinstance(result, InstrumentMeasurement):
            return self._log_instrument_measurement(experiment_id, result)
        if isinstance(result, UVVisSpectrum):
            return self._log_uvvis(experiment_id, result)
        if isinstance(result, MeasurementResult):
            return self._log_filmetrics(experiment_id, result)
        if isinstance(result, str):
            return self._log_camera(experiment_id, result)
        raise TypeError(
            f"Unsupported measurement type: {type(result).__name__}"
        )

    def _log_instrument_measurement(
        self,
        experiment_id: int,
        measurement: InstrumentMeasurement,
    ) -> int:
        if measurement.measurement_type == MeasurementType.UVVIS_SPECTRUM:
            wavelengths = tuple(measurement.payload["wavelength_nm"])
            intensities = tuple(measurement.payload["intensity_au"])
            integration_time_s = float(measurement.metadata["integration_time_s"])
            return self._log_uvvis_values(
                experiment_id=experiment_id,
                wavelengths=wavelengths,
                intensities=intensities,
                integration_time_s=integration_time_s,
            )

        if measurement.measurement_type == MeasurementType.ASMI_INDENTATION:
            return self._log_asmi(
                experiment_id=experiment_id,
                sample_timestamps=tuple(measurement.payload["sample_timestamps"]),
                z_positions=tuple(measurement.payload["z_positions_mm"]),
                raw_forces=tuple(measurement.payload["raw_forces_n"]),
                corrected_forces=tuple(measurement.payload["corrected_forces_n"]),
                directions=tuple(measurement.payload["directions"]),
                baseline_avg=float(measurement.metadata["baseline_avg"]),
                baseline_std=float(measurement.metadata["baseline_std"]),
                force_exceeded=bool(measurement.metadata["force_exceeded"]),
                data_points=int(measurement.metadata["data_points"]),
                step_size_mm=float(measurement.metadata["step_size_mm"]),
                z_target_mm=float(measurement.metadata["z_target_mm"]),
                force_limit_n=float(measurement.metadata["force_limit_n"]),
            )

        if measurement.measurement_type in {
            MeasurementType.POTENTIOSTAT_OCP,
            MeasurementType.POTENTIOSTAT_CA,
            MeasurementType.POTENTIOSTAT_CV,
            MeasurementType.POTENTIOSTAT_CP,
        }:
            payload = measurement.payload
            meta = measurement.metadata
            return self._log_potentiostat(
                experiment_id=experiment_id,
                technique=str(meta["technique"]),
                time_s=tuple(payload["time_s"]),
                voltage_v=tuple(payload["voltage_v"]),
                current_a=(
                    tuple(payload["current_a"])
                    if "current_a" in payload
                    else None
                ),
                sample_period_s=meta.get("sample_period_s"),
                duration_s=meta.get("duration_s"),
                step_potential_v=meta.get("step_potential_v"),
                step_current_a=meta.get("step_current_a"),
                scan_rate_v_s=meta.get("scan_rate_v_s"),
                step_size_v=meta.get("step_size_v"),
                cycles=meta.get("cycles"),
                vendor=meta.get("vendor"),
                device_id=meta.get("device_id"),
                channel=meta.get("channel"),
                started_at=meta.get("started_at"),
                stopped_at=meta.get("stopped_at"),
                aborted=meta.get("aborted"),
                stop_reason=meta.get("stop_reason"),
            )

        raise TypeError(
            "Unsupported instrument measurement type: "
            f"{measurement.measurement_type}"
        )

    def _log_uvvis(self, experiment_id: int, spectrum: UVVisSpectrum) -> int:
        return self._log_uvvis_values(
            experiment_id=experiment_id,
            wavelengths=spectrum.wavelengths,
            intensities=spectrum.intensities,
            integration_time_s=spectrum.integration_time_s,
        )

    def _log_uvvis_values(
        self,
        experiment_id: int,
        wavelengths: tuple[float, ...],
        intensities: tuple[float, ...],
        integration_time_s: float,
    ) -> int:
        cursor = self._conn.execute(
            "INSERT INTO uvvis_measurements "
            "(experiment_id, wavelengths, intensities, integration_time_s) "
            "VALUES (?, ?, ?, ?)",
            (
                experiment_id,
                json.dumps(list(wavelengths)),
                json.dumps(list(intensities)),
                integration_time_s,
            ),
        )
        self._conn.commit()
        return cursor.lastrowid

    def _log_filmetrics(self, experiment_id: int, result: MeasurementResult) -> int:
        cursor = self._conn.execute(
            "INSERT INTO filmetrics_measurements "
            "(experiment_id, thickness_nm, goodness_of_fit) VALUES (?, ?, ?)",
            (experiment_id, result.thickness_nm, result.goodness_of_fit),
        )
        self._conn.commit()
        return cursor.lastrowid

    def _log_asmi(
        self,
        experiment_id: int,
        sample_timestamps: tuple[float, ...],
        z_positions: tuple[float, ...],
        raw_forces: tuple[float, ...],
        corrected_forces: tuple[float, ...],
        directions: tuple[str, ...],
        baseline_avg: float,
        baseline_std: float,
        force_exceeded: bool,
        data_points: int,
        step_size_mm: float,
        z_target_mm: float,
        force_limit_n: float,
    ) -> int:
        cursor = self._conn.execute(
            "INSERT INTO asmi_measurements "
            "(experiment_id, sample_timestamps, z_positions, raw_forces, "
            "corrected_forces, directions, baseline_avg, baseline_std, "
            "force_exceeded, data_points, step_size_mm, z_target_mm, "
            "force_limit_n) "
            "VALUES (:experiment_id, :sample_timestamps, :z_positions, "
            ":raw_forces, :corrected_forces, :directions, :baseline_avg, "
            ":baseline_std, :force_exceeded, :data_points, :step_size_mm, "
            ":z_target_mm, :force_limit_n)",
            {
                "experiment_id": experiment_id,
                "sample_timestamps": json.dumps(list(sample_timestamps)),
                "z_positions": json.dumps(list(z_positions)),
                "raw_forces": json.dumps(list(raw_forces)),
                "corrected_forces": json.dumps(list(corrected_forces)),
                "directions": json.dumps(list(directions)),
                "baseline_avg": baseline_avg,
                "baseline_std": baseline_std,
                "force_exceeded": int(force_exceeded),
                "data_points": data_points,
                "step_size_mm": step_size_mm,
                "z_target_mm": z_target_mm,
                "force_limit_n": force_limit_n,
            },
        )
        self._conn.commit()
        return cursor.lastrowid

    def _log_potentiostat(
        self,
        experiment_id: int,
        technique: str,
        time_s: tuple[float, ...],
        voltage_v: tuple[float, ...],
        current_a: Optional[tuple[float, ...]],
        sample_period_s: Optional[float],
        duration_s: Optional[float],
        step_potential_v: Optional[float],
        step_current_a: Optional[float],
        scan_rate_v_s: Optional[float],
        step_size_v: Optional[float],
        cycles: Optional[int],
        vendor: Optional[str],
        device_id: Optional[str],
        channel: Optional[int],
        started_at: Optional[str],
        stopped_at: Optional[str],
        aborted: Optional[bool],
        stop_reason: Optional[str],
    ) -> int:
        cursor = self._conn.execute(
            "INSERT INTO potentiostat_measurements "
            "(experiment_id, technique, time_s, voltage_v, current_a, "
            "sample_period_s, duration_s, step_potential_v, step_current_a, "
            "scan_rate_v_s, step_size_v, cycles, vendor, device_id, channel, "
            "started_at, stopped_at, aborted, stop_reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                experiment_id,
                technique,
                json.dumps(list(time_s)),
                json.dumps(list(voltage_v)),
                json.dumps(list(current_a)) if current_a is not None else None,
                sample_period_s,
                duration_s,
                step_potential_v,
                step_current_a,
                scan_rate_v_s,
                step_size_v,
                cycles,
                vendor,
                device_id,
                channel,
                started_at,
                stopped_at,
                int(aborted) if aborted is not None else None,
                stop_reason,
            ),
        )
        self._conn.commit()
        return cursor.lastrowid

    def _log_camera(self, experiment_id: int, image_path: str) -> int:
        cursor = self._conn.execute(
            "INSERT INTO camera_measurements (experiment_id, image_path) "
            "VALUES (?, ?)",
            (experiment_id, image_path),
        )
        self._conn.commit()
        return cursor.lastrowid

    # ── Labware tracking ────────────────────────────────────────────────────

    def register_labware(self, campaign_id: int, labware_key: str, labware: Any) -> None:
        """Register a labware item for volume/content tracking.

        For a WellPlate, one row is created per well.
        For a Vial, a single row is created (well_id = NULL).

        Raises:
            TypeError: If *labware* is not a Labware instance (WellPlate or Vial).
            ValueError: If *labware_key* is already registered for the given campaign.
        """
        from deck.labware.labware import Labware
        from deck.labware.well_plate import WellPlate
        from deck.labware.vial import Vial

        if not isinstance(labware, Labware):
            raise TypeError(
                f"Expected a Labware instance, got {type(labware).__name__}"
            )

        existing = self._conn.execute(
            "SELECT COUNT(*) FROM labware WHERE campaign_id = ? AND labware_key = ?",
            (campaign_id, labware_key),
        ).fetchone()[0]
        if existing > 0:
            raise ValueError(
                f"Labware '{labware_key}' already registered for campaign {campaign_id}"
            )

        if isinstance(labware, WellPlate):
            for well_id in labware.wells:
                self._conn.execute(
                    "INSERT INTO labware (campaign_id, labware_key, labware_type, "
                    "well_id, total_volume_ul, working_volume_ul) "
                    "VALUES (?, ?, 'well_plate', ?, ?, ?)",
                    (campaign_id, labware_key, well_id,
                     labware.capacity_ul, labware.working_volume_ul),
                )
        elif isinstance(labware, Vial):
            self._conn.execute(
                "INSERT INTO labware (campaign_id, labware_key, labware_type, "
                "total_volume_ul, working_volume_ul) "
                "VALUES (?, ?, 'vial', ?, ?)",
                (campaign_id, labware_key,
                 labware.capacity_ul, labware.working_volume_ul),
            )
        else:
            raise TypeError(
                f"Unsupported labware type: {type(labware).__name__}. "
                f"Expected WellPlate or Vial."
            )
        self._conn.commit()

    def record_dispense(
        self,
        campaign_id: int,
        labware_key: str,
        well_id: Optional[str],
        source_name: str,
        volume_ul: float,
    ) -> None:
        """Record a dispense into a labware slot, updating volume and contents."""
        if well_id is not None:
            where = "campaign_id = ? AND labware_key = ? AND well_id = ?"
            params = (campaign_id, labware_key, well_id)
        else:
            where = "campaign_id = ? AND labware_key = ? AND well_id IS NULL"
            params = (campaign_id, labware_key)

        row = self._conn.execute(
            f"SELECT id, contents FROM labware WHERE {where}", params
        ).fetchone()

        if row is None:
            raise ValueError(
                f"Labware '{labware_key}' well '{well_id}' not registered "
                f"for campaign {campaign_id}"
            )

        try:
            existing = json.loads(row[1]) if row[1] else []
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Corrupt contents JSON for labware '{labware_key}' well '{well_id}' "
                f"in campaign {campaign_id}. Manual database inspection required."
            ) from exc
        existing.append({"source": source_name, "volume_ul": volume_ul})

        self._conn.execute(
            f"UPDATE labware SET current_volume_ul = current_volume_ul + ?, "
            f"contents = ?, updated_at = datetime('now') WHERE {where}",
            (volume_ul, json.dumps(existing)) + params,
        )
        self._conn.commit()

    def get_contents(
        self,
        campaign_id: int,
        labware_key: str,
        well_id: Optional[str],
    ) -> Optional[List[dict]]:
        """Return the parsed contents list for a labware slot, or None."""
        if well_id is not None:
            where = "campaign_id = ? AND labware_key = ? AND well_id = ?"
            params = (campaign_id, labware_key, well_id)
        else:
            where = "campaign_id = ? AND labware_key = ? AND well_id IS NULL"
            params = (campaign_id, labware_key)

        row = self._conn.execute(
            f"SELECT contents FROM labware WHERE {where}", params
        ).fetchone()

        if row is None or row[0] is None:
            return None
        try:
            return json.loads(row[0])
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Corrupt contents JSON for labware '{labware_key}' well '{well_id}' "
                f"in campaign {campaign_id}. Manual database inspection required."
            ) from exc

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> DataStore:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
