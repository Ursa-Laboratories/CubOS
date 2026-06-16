"""Tests for CubOS campaign summary and ZIP export helpers."""

from __future__ import annotations

import csv
import io
import zipfile

import pytest

from data.data_store import DataStore
from data.exports import (
    MeasurementDataError,
    export_campaign_asmi_zip,
    export_campaign_measurements_zip,
    list_campaign_summaries,
    _json_array,
)
from protocol_engine.measurements import InstrumentMeasurement, MeasurementType


def _seed_store(path):
    store = DataStore(db_path=path)
    campaign_id = store.create_campaign(
        description="Export test",
        deck_config="deck.yaml",
        gantry_config="gantry.yaml",
        protocol_config="protocol.yaml",
    )
    store._conn.execute(
        "UPDATE campaigns SET created_at = ? WHERE id = ?",
        ("2026-06-11 10:00:00", campaign_id),
    )
    uvvis_experiment = store.create_experiment(campaign_id, "plate", "A1", "[]")
    asmi_experiment = store.create_experiment(campaign_id, "plate", "B2", "[]")
    uvvis_id = store.log_measurement(
        uvvis_experiment,
        InstrumentMeasurement(
            measurement_type=MeasurementType.UVVIS_SPECTRUM,
            payload={
                "wavelength_nm": [400.0, 500.0],
                "intensity_au": [0.1, 0.2],
            },
            metadata={"integration_time_s": 0.24},
        ),
    )
    asmi_id = store.log_measurement(
        asmi_experiment,
        InstrumentMeasurement(
            measurement_type=MeasurementType.ASMI_INDENTATION,
            payload={
                "sample_timestamps": [1.0, 1.1],
                "z_positions_mm": [-74.0, -74.1],
                "raw_forces_n": [0.5, 0.6],
                "corrected_forces_n": [0.1, 0.2],
                "directions": ["down", "up"],
            },
            metadata={
                "baseline_avg": 0.4,
                "baseline_std": 0.01,
                "force_exceeded": False,
                "data_points": 2,
                "step_size_mm": 0.01,
                "z_target_mm": -80.0,
                "force_limit_n": 10.0,
            },
        ),
    )
    store._conn.execute(
        "UPDATE uvvis_measurements SET timestamp = ? WHERE id = ?",
        ("2026-06-11 10:01:00", uvvis_id),
    )
    store._conn.execute(
        "UPDATE asmi_measurements SET timestamp = ? WHERE id = ?",
        ("2026-06-11 10:02:00", asmi_id),
    )
    store._conn.commit()
    store.close()
    return campaign_id


def test_list_campaign_summaries_counts_measurements(tmp_path):
    db_path = tmp_path / "panda_data.db"
    campaign_id = _seed_store(db_path)

    summaries = list_campaign_summaries(db_path)

    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.campaign_id == campaign_id
    assert summary.latest_measurement_at == "2026-06-11 10:02:00"
    assert summary.experiment_count == 2
    assert summary.measurement_count == 2
    assert summary.measurement_counts["uvvis"] == 1
    assert summary.measurement_counts["asmi"] == 1


def test_list_campaign_summaries_closes_database_connection(monkeypatch, tmp_path):
    import data.exports as exports

    db_path = tmp_path / "panda_data.db"
    _seed_store(db_path)
    real_connect = exports._connect
    closed = []

    class ClosingProbe:
        def __init__(self, conn):
            self._conn = conn

        def close(self):
            closed.append(True)
            self._conn.close()

        def __getattr__(self, name):
            return getattr(self._conn, name)

    monkeypatch.setattr(
        exports,
        "_connect",
        lambda path: ClosingProbe(real_connect(path)),
    )

    assert list_campaign_summaries(db_path)
    assert closed == [True]


def test_export_campaign_measurements_zip_preserves_table_archive_shape(tmp_path):
    db_path = tmp_path / "panda_data.db"
    campaign_id = _seed_store(db_path)

    content = export_campaign_measurements_zip(db_path, campaign_id)

    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        assert set(archive.namelist()) == {
            "manifest.csv",
            "experiments.csv",
            "measurements/uvvis_measurements.csv",
            "measurements/asmi_measurements.csv",
        }
        assert archive.read("manifest.csv").decode().splitlines() == [
            "instrument,table,row_count,file",
            "uvvis,uvvis_measurements,1,measurements/uvvis_measurements.csv",
            "asmi,asmi_measurements,1,measurements/asmi_measurements.csv",
        ]
        uvvis_rows = list(csv.reader(io.StringIO(
            archive.read("measurements/uvvis_measurements.csv").decode()
        )))
        assert uvvis_rows[0][:5] == [
            "id",
            "experiment_id",
            "wavelengths",
            "intensities",
            "integration_time_s",
        ]
        assert uvvis_rows[1][2:5] == ["[400.0, 500.0]", "[0.1, 0.2]", "0.24"]


def test_export_campaign_asmi_zip_preserves_raw_archive_shape(tmp_path):
    db_path = tmp_path / "panda_data.db"
    campaign_id = _seed_store(db_path)

    content = export_campaign_asmi_zip(db_path, campaign_id)

    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        assert archive.namelist() == [
            "metadata.csv",
            "well_B2_20260611_100200.csv",
        ]
        assert archive.read("metadata.csv").decode().splitlines()[0] == (
            "File,Measurement_ID,Test_Time,Well,Target_Z(mm),Step_Size(mm),"
            "Force_Limit(N),Baseline_Force(N),Baseline_Std(N),"
            "Force_Exceeded,Data_Points"
        )
        assert archive.read("well_B2_20260611_100200.csv").decode().splitlines() == [
            "Timestamp(s),Z_Position(mm),Raw_Force(N),Corrected_Force(N),Direction",
            "1.000,-74.000,0.500,0.100,down",
            "1.100,-74.100,0.600,0.200,up",
        ]


def test_json_array_reports_malformed_asmi_rows():
    with pytest.raises(MeasurementDataError, match="must be a JSON array"):
        _json_array("{}", "raw_forces")
