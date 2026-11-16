"""Tests for the export_helpers CLI."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest
from cubos.data.data_store import DataStore
from cubos.data.export_helpers import main
from cubos.protocol_engine.measurements import InstrumentMeasurement, MeasurementType

# ─── Helpers ──────────────────────────────────────────────────────────────────


def _seed_db(path: str) -> None:
    store = DataStore(db_path=path)
    cid = store.create_campaign(description="export test")
    eid = store.create_experiment(cid, "plate_1", "A1", "[]")
    store.log_measurement(
        eid,
        InstrumentMeasurement(
            measurement_type=MeasurementType.UVVIS_SPECTRUM,
            payload={
                "wavelength_nm": [400.0, 500.0],
                "intensity_au": [0.1, 0.5],
            },
            metadata={"integration_time_s": 0.24},
        ),
    )
    store.close()


# ─── campaign-experiments subcommand ─────────────────────────────────────────


def test_help_documents_runtime_database_defaults(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["export", "--help"])

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "CUBOS_DATA_DB_PATH" in output
    assert "~/.cubos/panda_data.db" in output


@pytest.mark.parametrize("use_override", [False, True])
@pytest.mark.parametrize("command, expected", [
    (["campaign-experiments", "1"], "experiment_id"),
    (["experiment-all", "1"], "uvvis"),
    (["experiment-instrument", "1", "uvvis"], "wavelengths"),
])
def test_uses_runtime_database_default(
    tmp_path, monkeypatch, capsys, use_override, command, expected,
):
    pytest.importorskip("pandas")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    if use_override:
        db = tmp_path / "custom" / "results.db"
        monkeypatch.setenv("CUBOS_DATA_DB_PATH", str(db))
    else:
        monkeypatch.delenv("CUBOS_DATA_DB_PATH", raising=False)
        db = tmp_path / ".cubos" / "panda_data.db"
    _seed_db(str(db))
    monkeypatch.setattr(sys, "argv", ["export", *command])

    assert main() == 0
    assert expected in capsys.readouterr().out
    assert not (tmp_path / "data").exists()


def test_explicit_database_overrides_environment(tmp_path, monkeypatch, capsys):
    pytest.importorskip("pandas")
    db = tmp_path / "explicit.db"
    _seed_db(str(db))
    monkeypatch.setenv("CUBOS_DATA_DB_PATH", str(tmp_path / "missing.db"))
    monkeypatch.setattr(sys, "argv", [
        "export", "--db-path", str(db), "campaign-experiments", "1",
    ])

    assert main() == 0
    assert "experiment_id" in capsys.readouterr().out
    assert not (tmp_path / "missing.db").exists()


class TestCampaignExperimentsSubcommand:

    def test_prints_experiment_ids(self, tmp_path, capsys, monkeypatch):
        pytest.importorskip("pandas")
        db = str(tmp_path / "test.db")
        _seed_db(db)
        monkeypatch.setattr(sys, "argv", ["export", "--db-path", db, "campaign-experiments", "1"])
        result = main()
        assert result == 0
        assert "experiment_id" in capsys.readouterr().out

    def test_writes_csv(self, tmp_path, monkeypatch):
        pytest.importorskip("pandas")
        db = str(tmp_path / "test.db")
        out_csv = str(tmp_path / "out.csv")
        _seed_db(db)
        monkeypatch.setattr(
            sys, "argv",
            ["export", "--db-path", db, "campaign-experiments", "1", "--csv", out_csv],
        )
        result = main()
        assert result == 0
        assert Path(out_csv).exists()
        assert "experiment_id" in Path(out_csv).read_text()

    def test_prints_no_rows_found_for_empty_campaign(self, tmp_path, capsys, monkeypatch):
        pytest.importorskip("pandas")
        db = str(tmp_path / "empty.db")
        store = DataStore(db_path=db)
        store.create_campaign(description="empty")
        store.close()
        monkeypatch.setattr(sys, "argv", ["export", "--db-path", db, "campaign-experiments", "1"])
        result = main()
        assert result == 0
        assert "No rows found" in capsys.readouterr().out


# ─── experiment-all subcommand ────────────────────────────────────────────────


class TestExperimentAllSubcommand:

    def test_csv_preserves_text_metadata_and_expands_measurement_arrays(
        self, tmp_path, monkeypatch,
    ):
        pytest.importorskip("pandas")
        db = tmp_path / "measurements.db"
        output = tmp_path / "measurements.csv"
        with DataStore(db_path=db) as store:
            campaign_id = store.create_campaign(description="CSV metadata round trip")
            experiment_id = store.create_experiment(campaign_id, "plate", "A1")
            measurement_id = store.log_measurement(
                experiment_id,
                InstrumentMeasurement(
                    measurement_type=MeasurementType.POTENTIOSTAT_CA,
                    payload={
                        "time_s": [0.0, 1.0],
                        "voltage_v": [0.5, 0.5],
                        "current_a": [0.01, 0.02],
                    },
                    metadata={
                        "technique": "ca",
                        "device_id": "123",
                        "stop_reason": "null",
                        "channel": 1,
                    },
                ),
            )
        monkeypatch.setattr(sys, "argv", [
            "export", "--db-path", str(db), "experiment-all", str(experiment_id),
            "--csv", str(output),
        ])

        assert main() == 0

        with output.open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert len(rows) == 1
        assert rows[0]["instrument"] == "potentiostat"
        assert rows[0]["experiment_id"] == str(experiment_id)
        assert rows[0]["measurement_id"] == str(measurement_id)
        payload = json.loads(rows[0]["data_json"])
        assert payload["device_id"] == "123"
        assert payload["stop_reason"] == "null"
        assert payload["channel"] == 1
        assert payload["time_s"] == [0.0, 1.0]
        assert payload["voltage_v"] == [0.5, 0.5]
        assert payload["current_a"] == [0.01, 0.02]

    def test_prints_all_measurements(self, tmp_path, capsys, monkeypatch):
        pytest.importorskip("pandas")
        db = str(tmp_path / "test.db")
        _seed_db(db)
        monkeypatch.setattr(sys, "argv", ["export", "--db-path", db, "experiment-all", "1"])
        result = main()
        assert result == 0
        out = capsys.readouterr().out
        assert "uvvis" in out

    def test_writes_csv(self, tmp_path, monkeypatch):
        pytest.importorskip("pandas")
        db = str(tmp_path / "test.db")
        out_csv = str(tmp_path / "all.csv")
        _seed_db(db)
        monkeypatch.setattr(
            sys, "argv",
            ["export", "--db-path", db, "experiment-all", "1", "--csv", out_csv],
        )
        result = main()
        assert result == 0
        assert Path(out_csv).exists()


# ─── experiment-instrument subcommand ────────────────────────────────────────


class TestExperimentInstrumentSubcommand:

    def test_prints_uvvis_measurements(self, tmp_path, capsys, monkeypatch):
        pytest.importorskip("pandas")
        db = str(tmp_path / "test.db")
        _seed_db(db)
        monkeypatch.setattr(
            sys, "argv",
            ["export", "--db-path", db, "experiment-instrument", "1", "uvvis"],
        )
        result = main()
        assert result == 0
        out = capsys.readouterr().out
        assert "wavelengths" in out

    def test_prints_no_rows_found_for_wrong_instrument(self, tmp_path, capsys, monkeypatch):
        pytest.importorskip("pandas")
        db = str(tmp_path / "test.db")
        _seed_db(db)
        monkeypatch.setattr(
            sys, "argv",
            ["export", "--db-path", db, "experiment-instrument", "1", "asmi"],
        )
        result = main()
        assert result == 0
        assert "No rows found" in capsys.readouterr().out
