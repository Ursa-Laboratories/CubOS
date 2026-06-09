"""Tests for ASMI raw per-well CSV export."""

from __future__ import annotations

import csv
from pathlib import Path

from data.asmi_raw_csv import export_asmi_raw_csvs
from data.data_store import DataStore
from protocol_engine.measurements import InstrumentMeasurement, MeasurementType


def _seed_asmi_measurement(db_path: Path) -> int:
    store = DataStore(db_path=str(db_path))
    campaign_id = store.create_campaign(description="asmi raw csv export")
    experiment_id = store.create_experiment(
        campaign_id,
        labware_name="asmi_96_well_deck_origin",
        well_id="A1",
        contents_json="[]",
    )
    store.log_measurement(
        experiment_id,
        InstrumentMeasurement(
            measurement_type=MeasurementType.ASMI_INDENTATION,
            payload={
                "timestamps_s": [1761841220.199, 1761841220.327],
                "z_positions_mm": [-74.01, -74.02],
                "raw_forces_n": [0.463, 0.457],
                "corrected_forces_n": [0.004, -0.002],
                "directions": ["down", "up"],
            },
            metadata={
                "baseline_avg": 0.459,
                "baseline_std": 0.003,
                "force_exceeded": True,
                "data_points": 2,
                "step_size_mm": 0.01,
                "z_target_mm": -80.0,
                "force_limit_n": 10.0,
            },
        ),
    )
    store._conn.execute(
        "UPDATE asmi_measurements SET timestamp = ?",
        ("2025-10-30 12:21:07",),
    )
    store._conn.commit()
    store.close()
    return campaign_id


def test_exports_asmi_new_raw_per_well_csv_from_datastore(tmp_path: Path):
    db_path = tmp_path / "asmi.db"
    campaign_id = _seed_asmi_measurement(db_path)
    output_dir = tmp_path / "measurements"

    written = export_asmi_raw_csvs(
        db_path=str(db_path),
        campaign_id=campaign_id,
        output_dir=output_dir,
    )

    assert written == [output_dir / "well_A1_20251030_122107.csv"]

    with written[0].open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))

    assert rows == [
        ["Test_Time", "2025-10-30 12:21:07"],
        ["Well", "A1"],
        ["Target_Z(mm)", "-80.000"],
        ["Step_Size(mm)", "0.010"],
        ["Force_Limit(N)", "10.0"],
        ["Baseline_Force(N)", "0.459"],
        ["Baseline_Std(N)", "0.003"],
        ["Force_Exceeded", "True"],
        [],
        [
            "Timestamp(s)",
            "Z_Position(mm)",
            "Raw_Force(N)",
            "Corrected_Force(N)",
            "Direction",
        ],
        ["1761841220.199", "-74.010", "0.463", "0.004", "down"],
        ["1761841220.327", "-74.020", "0.457", "-0.002", "up"],
    ]
