"""Tests for the user-facing setup/run_protocol.py CLI wrapper."""

from __future__ import annotations

import sys
import csv
from dataclasses import dataclass

from instruments.uvvis_ccs.models import UVVisSpectrum


@dataclass
class _ValidationResult:
    passed: bool
    output: str


def test_run_protocol_exports_result_csvs(tmp_path, monkeypatch, capsys):
    import setup.run_protocol as run_protocol

    db_path = tmp_path / "panda_data.db"

    def fake_create_campaign(data_store, **kwargs):
        del kwargs
        return data_store.create_campaign("test run")

    def fake_run_on_hardware(
        gantry_path,
        deck_path,
        protocol_path,
        *,
        data_store,
        campaign_id,
    ):
        del gantry_path, deck_path, protocol_path
        experiment_id = data_store.create_experiment(
            campaign_id,
            labware_name="plate",
            well_id="A1",
            contents_json="[]",
        )
        data_store.log_measurement(
            experiment_id,
            UVVisSpectrum(
                wavelengths=(400.0, 500.0),
                intensities=(0.1, 0.2),
                integration_time_s=0.24,
            ),
        )
        return ["ok"]

    monkeypatch.setattr(
        run_protocol,
        "run_setup_validation",
        lambda *args: _ValidationResult(passed=True, output="PASS"),
    )
    monkeypatch.setattr(run_protocol, "default_database_path", lambda: db_path)
    monkeypatch.setattr(
        run_protocol,
        "create_campaign_for_protocol_run",
        fake_create_campaign,
    )
    monkeypatch.setattr(run_protocol, "run_on_hardware", fake_run_on_hardware)
    monkeypatch.setattr(run_protocol, "project_root", tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_protocol.py", "gantry.yaml", "deck.yaml", "protocol.yaml"],
    )

    run_protocol.main()

    out = capsys.readouterr().out
    assert "Measurement data store:" in out
    assert "Result CSV files:" in out

    results_root = tmp_path / "data" / "results"
    matches = list(results_root.glob("campaign_1_*"))
    assert len(matches) == 1
    uvvis_csv = matches[0] / "uvvis.csv"
    assert uvvis_csv.exists()
    rows = list(csv.DictReader(uvvis_csv.open()))
    assert [row["well_id"] for row in rows] == ["A1", "A1"]
    assert [row["sample_index"] for row in rows] == ["0", "1"]
    assert [row["wavelength_nm"] for row in rows] == ["400.0", "500.0"]
    assert [row["intensity_au"] for row in rows] == ["0.1", "0.2"]
