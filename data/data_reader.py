"""Read-only query layer for the CubOS SQLite database.

Used after experiments for analysis — the write-side counterpart is DataStore.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


_VALID_MEASUREMENT_TABLES = frozenset({
    "uvvis_measurements",
    "filmetrics_measurements",
    "uv_curing_measurements",
    "camera_measurements",
    "asmi_measurements",
    "potentiostat_measurements",
})
_TABLE_TO_INSTRUMENT = {
    "uvvis_measurements": "uvvis",
    "filmetrics_measurements": "filmetrics",
    "uv_curing_measurements": "uv_curing",
    "camera_measurements": "camera",
    "asmi_measurements": "asmi",
    "potentiostat_measurements": "potentiostat",
}
_INSTRUMENT_TO_TABLE = {
    instrument: table for table, instrument in _TABLE_TO_INSTRUMENT.items()
}


@dataclass(frozen=True)
class CampaignRecord:
    """Read-only view of a campaign row."""

    id: int
    description: str
    deck_config: Optional[str]
    board_config: Optional[str]
    gantry_config: Optional[str]
    protocol_config: Optional[str]
    created_at: str
    status: str


@dataclass(frozen=True)
class ExperimentRecord:
    """Read-only view of an experiment row."""

    id: int
    campaign_id: int
    labware_name: str
    well_id: Optional[str]
    contents: Optional[str]
    created_at: str


@dataclass(frozen=True)
class LabwareRecord:
    """Read-only view of a labware row."""

    id: int
    campaign_id: int
    labware_key: str
    labware_type: str
    well_id: Optional[str]
    total_volume_ul: float
    working_volume_ul: float
    current_volume_ul: float
    contents: Optional[str]


class DataReader:
    """Read-only query interface for the CubOS SQLite database."""

    def __init__(
        self,
        db_path: Optional[str] = None,
        connection: Optional[sqlite3.Connection] = None,
    ) -> None:
        if connection is not None:
            self._conn = connection
        elif db_path is not None:
            self._conn = sqlite3.connect(db_path)
        else:
            raise ValueError("Either db_path or connection must be provided")
        self._conn.row_factory = sqlite3.Row
        self._owns_connection = connection is None

    # ── Campaign queries ──────────────────────────────────────────────────

    def get_campaign(self, campaign_id: int) -> Optional[CampaignRecord]:
        row = self._conn.execute(
            "SELECT id, description, deck_config, board_config, "
            "gantry_config, protocol_config, created_at, status "
            "FROM campaigns WHERE id = ?",
            (campaign_id,),
        ).fetchone()
        if row is None:
            return None
        return CampaignRecord(**dict(row))

    def list_campaigns(self) -> List[CampaignRecord]:
        rows = self._conn.execute(
            "SELECT id, description, deck_config, board_config, "
            "gantry_config, protocol_config, created_at, status "
            "FROM campaigns ORDER BY id",
        ).fetchall()
        return [CampaignRecord(**dict(r)) for r in rows]

    # ── Experiment queries ────────────────────────────────────────────────

    def get_experiments(
        self,
        campaign_id: int,
        labware_name: Optional[str] = None,
        well_id: Optional[str] = None,
    ) -> List[ExperimentRecord]:
        query = (
            "SELECT id, campaign_id, labware_name, well_id, contents, created_at "
            "FROM experiments WHERE campaign_id = ?"
        )
        params: list[Any] = [campaign_id]

        if labware_name is not None:
            query += " AND labware_name = ?"
            params.append(labware_name)
        if well_id is not None:
            query += " AND well_id = ?"
            params.append(well_id)

        query += " ORDER BY id"
        rows = self._conn.execute(query, params).fetchall()
        return [ExperimentRecord(**dict(r)) for r in rows]

    def get_experiment_ids_dataframe(self, campaign_id: int) -> Any:
        """Return a pandas DataFrame of experiment IDs for a campaign.

        This helper is intentionally simple for non-software users who only need a
        campaign → experiment list that can be exported to CSV.
        """
        pd = self._require_pandas()
        rows = self._conn.execute(
            "SELECT id AS experiment_id FROM experiments "
            "WHERE campaign_id = ? ORDER BY id",
            (campaign_id,),
        ).fetchall()
        return pd.DataFrame([dict(r) for r in rows], columns=["experiment_id"])

    # ── Labware queries ───────────────────────────────────────────────────

    def get_labware(
        self,
        campaign_id: int,
        labware_key: Optional[str] = None,
    ) -> List[LabwareRecord]:
        query = (
            "SELECT id, campaign_id, labware_key, labware_type, well_id, "
            "total_volume_ul, working_volume_ul, current_volume_ul, contents "
            "FROM labware WHERE campaign_id = ?"
        )
        params: list[Any] = [campaign_id]

        if labware_key is not None:
            query += " AND labware_key = ?"
            params.append(labware_key)

        query += " ORDER BY id"
        rows = self._conn.execute(query, params).fetchall()
        return [LabwareRecord(**dict(r)) for r in rows]

    # ── Measurement queries (generic) ─────────────────────────────────────

    def get_measurements(
        self,
        experiment_id: int,
        table: str,
    ) -> List[Dict[str, Any]]:
        if table not in _VALID_MEASUREMENT_TABLES:
            raise ValueError(
                f"'{table}' is not a valid measurement table. "
                f"Valid tables: {', '.join(sorted(_VALID_MEASUREMENT_TABLES))}"
            )
        rows = self._conn.execute(
            f"SELECT * FROM {table} WHERE experiment_id = ? ORDER BY id",
            (experiment_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_measurements_by_campaign(
        self,
        campaign_id: int,
        table: str,
    ) -> List[Dict[str, Any]]:
        if table not in _VALID_MEASUREMENT_TABLES:
            raise ValueError(
                f"'{table}' is not a valid measurement table. "
                f"Valid tables: {', '.join(sorted(_VALID_MEASUREMENT_TABLES))}"
            )
        rows = self._conn.execute(
            f"SELECT m.*, e.well_id, e.labware_name "
            f"FROM {table} m "
            f"JOIN experiments e ON m.experiment_id = e.id "
            f"WHERE e.campaign_id = ? ORDER BY m.id",
            (campaign_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_experiment_measurements_dataframe(self, experiment_id: int) -> Any:
        """Return all measurements for one experiment as a single DataFrame.

        The rows are instrument-agnostic and include:
        - `instrument` (e.g. uvvis, filmetrics, uv_curing, camera, asmi)
        - `measurement_id`
        - `experiment_id`
        - `timestamp`
        - `data_json` (instrument-specific payload serialized as JSON)
        """
        pd = self._require_pandas()
        rows: list[dict[str, Any]] = []
        for table, instrument in _TABLE_TO_INSTRUMENT.items():
            table_rows = self._conn.execute(
                f"SELECT * FROM {table} WHERE experiment_id = ? ORDER BY id",
                (experiment_id,),
            ).fetchall()
            for row in table_rows:
                row_dict = dict(row)
                rows.append({
                    "instrument": instrument,
                    "measurement_id": row_dict.get("id"),
                    "experiment_id": row_dict.get("experiment_id"),
                    "timestamp": row_dict.get("timestamp"),
                    "data_json": self._serialize_row_payload(row_dict),
                })
        return pd.DataFrame(
            rows,
            columns=[
                "instrument",
                "measurement_id",
                "experiment_id",
                "timestamp",
                "data_json",
            ],
        )

    def get_experiment_measurements_by_instrument_dataframe(
        self,
        experiment_id: int,
        instrument: str,
    ) -> Any:
        """Return measurements for one experiment filtered by instrument.

        Args:
            experiment_id: Experiment identifier.
            instrument: One of `uvvis`, `filmetrics`, `uv_curing`, `camera`,
                `asmi`, or `potentiostat`.
        """
        pd = self._require_pandas()
        normalized_instrument = instrument.strip().lower()
        table = _INSTRUMENT_TO_TABLE.get(normalized_instrument)
        if table is None:
            supported = ", ".join(sorted(_INSTRUMENT_TO_TABLE))
            raise ValueError(
                f"Unsupported instrument '{instrument}'. Supported: {supported}"
            )
        rows = self._conn.execute(
            f"SELECT * FROM {table} WHERE experiment_id = ? ORDER BY id",
            (experiment_id,),
        ).fetchall()
        return pd.DataFrame([dict(r) for r in rows])

    def export_dataframe_to_csv(
        self,
        dataframe: Any,
        output_path: str,
        *,
        include_index: bool = False,
    ) -> str:
        """Write a pandas DataFrame to CSV and return the output path."""
        if not hasattr(dataframe, "to_csv"):
            raise TypeError("Expected a pandas DataFrame-like object with to_csv()")
        dataframe.to_csv(output_path, index=include_index)
        return output_path

    # ── Lifecycle ─────────────────────────────────────────────────────────

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    @staticmethod
    def _require_pandas() -> Any:
        try:
            import pandas as pd
        except ImportError as exc:  # pragma: no cover - exercised only when missing
            raise ImportError(
                "pandas is required for DataFrame helpers. "
                "Install with: pip install pandas"
            ) from exc
        return pd

    @staticmethod
    def _serialize_row_payload(row_dict: Dict[str, Any]) -> str:
        payload: dict[str, Any] = {
            key: value for key, value in row_dict.items()
            if key not in {"id", "experiment_id", "timestamp"}
        }
        normalized_payload: dict[str, Any] = {}
        for key, value in payload.items():
            if isinstance(value, (bytes, bytearray)):
                raise ValueError(
                    f"Column '{key}' contains binary data (BLOB). "
                    f"This database was written before the JSON migration. "
                    f"Re-run your experiments or migrate the database to TEXT columns."
                )
            elif isinstance(value, str):
                try:
                    normalized_payload[key] = json.loads(value)
                except (json.JSONDecodeError, ValueError):
                    normalized_payload[key] = value
            else:
                normalized_payload[key] = value
        return json.dumps(normalized_payload)

    # _serialize_row_payload note: the str branch attempts json.loads so that
    # JSON-encoded array columns (wavelengths, z_positions, etc.) are embedded
    # as proper arrays rather than double-encoded strings. Plain-text columns
    # (image_path, etc.) that fail json.loads are passed through as-is — this
    # is intentional and safe for non-array string columns.

    def close(self) -> None:
        if self._owns_connection:
            self._conn.close()

    def __enter__(self) -> DataReader:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
