"""Tests for the user-facing packages/core/src/cubos/tools/run_protocol.py CLI wrapper."""

from __future__ import annotations

import sys
import csv
from dataclasses import dataclass

import pytest

from cubos.instruments.uvvis_ccs.models import UVVisSpectrum


@dataclass
class _ValidationResult:
    passed: bool
    output: str


def test_run_protocol_exports_result_csvs(tmp_path, monkeypatch, capsys):
    import cubos.tools.run_protocol as run_protocol

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


def test_run_protocol_exports_partial_results_after_failure(tmp_path, monkeypatch, capsys):
    import cubos.tools.run_protocol as run_protocol

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
            labware_key="plate_1",
            labware_name="Display Plate",
            well_id="A1",
            contents_json="[]",
        )
        data_store.log_measurement(
            experiment_id,
            UVVisSpectrum(
                wavelengths=(400.0,),
                intensities=(0.1,),
                integration_time_s=0.24,
            ),
        )
        raise RuntimeError("hardware stopped")

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

    with pytest.raises(SystemExit) as exc_info:
        run_protocol.main()

    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "Protocol did not complete" in out
    results_root = tmp_path / "data" / "results"
    matches = list(results_root.glob("campaign_1_*"))
    assert len(matches) == 1
    rows = list(csv.DictReader((matches[0] / "uvvis.csv").open()))
    assert rows[0]["labware_key"] == "plate_1"
    assert rows[0]["labware_name"] == "Display Plate"


def test_run_protocol_usage_exits_1(monkeypatch, capsys):
    import cubos.tools.run_protocol as run_protocol

    monkeypatch.setattr(sys, "argv", ["run_protocol.py", "gantry.yaml"])

    with pytest.raises(SystemExit) as exc_info:
        run_protocol.main()

    assert exc_info.value.code == 1
    assert "Usage: python -m cubos.tools.run_protocol" in capsys.readouterr().out


def test_run_protocol_validation_failure_exits_before_hardware(monkeypatch, capsys):
    import cubos.tools.run_protocol as run_protocol

    monkeypatch.setattr(sys, "argv", ["run_protocol.py", "g.yaml", "d.yaml", "p.yaml"])
    monkeypatch.setattr(
        run_protocol,
        "run_setup_validation",
        lambda *args: _ValidationResult(passed=False, output="FAIL"),
    )

    with pytest.raises(SystemExit) as exc_info:
        run_protocol.main()

    assert exc_info.value.code == 1
    assert "Aborting" in capsys.readouterr().out


def test_run_protocol_export_failure_sets_exit_1(tmp_path, monkeypatch, capsys):
    import cubos.tools.run_protocol as run_protocol

    db_path = tmp_path / "panda_data.db"
    monkeypatch.setattr(sys, "argv", ["run_protocol.py", "g.yaml", "d.yaml", "p.yaml"])
    monkeypatch.setattr(
        run_protocol,
        "run_setup_validation",
        lambda *args: _ValidationResult(passed=True, output="PASS"),
    )
    monkeypatch.setattr(run_protocol, "default_database_path", lambda: db_path)
    monkeypatch.setattr(run_protocol, "create_campaign_for_protocol_run", lambda data_store, **kwargs: data_store.create_campaign("run"))
    monkeypatch.setattr(run_protocol, "run_on_hardware", lambda *args, **kwargs: ["one"])
    monkeypatch.setattr(run_protocol, "export_campaign_results_csvs", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("disk full")))

    with pytest.raises(SystemExit) as exc_info:
        run_protocol.main()

    assert exc_info.value.code == 1
    assert "ERROR exporting result CSVs" in capsys.readouterr().out
