"""Filesystem export manifests count CSV records, including multiline fields."""

import csv

import pytest
from cubos.data.data_store import DataStore
from cubos.data.exports import export_campaign_results_csvs
from cubos.protocol_engine.measurements import InstrumentMeasurement, MeasurementType


@pytest.mark.parametrize(
    ("stop_reason", "sample_count"),
    [
        ("Completed", 2),
        ('Stopped after "sample", 2\nOperator note', 2),
        ('Stopped after "sample", 3\r\nOperator note', 3),
        ("No samples\nOperator note", 0),
    ],
    ids=["single-line", "multiline-lf", "multiline-crlf", "header-only"],
)
def test_result_manifest_counts_exported_records(tmp_path, stop_reason, sample_count):
    db_path = tmp_path / "measurements.db"
    times = [float(index) for index in range(sample_count)]
    with DataStore(db_path=db_path) as store:
        campaign_id = store.create_campaign(description="Synthetic export fixture")
        experiment_id = store.create_experiment(campaign_id, "plate", "A1", "[]")
        store.log_measurement(
            experiment_id,
            InstrumentMeasurement(
                measurement_type=MeasurementType.POTENTIOSTAT_CA,
                payload={
                    "time_s": times,
                    "voltage_v": [0.5] * sample_count,
                    "current_a": [1e-6] * sample_count,
                },
                metadata={"technique": "ca", "stop_reason": stop_reason},
            ),
        )

    written = export_campaign_results_csvs(
        db_path, campaign_id, output_dir=tmp_path / "results",
    )
    files = {path.name: path for path in written}
    with files["potentiostat.csv"].open(encoding="utf-8", newline="") as handle:
        samples = list(csv.DictReader(handle))
    with files["manifest.csv"].open(encoding="utf-8", newline="") as handle:
        manifest = list(csv.DictReader(handle))

    assert [float(row["time_s"]) for row in samples] == times
    assert [row["stop_reason"] for row in samples] == [stop_reason] * sample_count
    assert manifest == [{
        "instrument": "potentiostat",
        "row_count": str(sample_count),
        "file": "potentiostat.csv",
    }]
