"""Tests for the export_helpers CLI."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from data.data_store import DataStore
from data.export_helpers import main
from protocol_engine.measurements import InstrumentMeasurement, MeasurementType


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


def _seed_asmi_db(path: str) -> None:
    store = DataStore(db_path=path)
    cid = store.create_campaign(description="asmi export test")
    eid = store.create_experiment(cid, "plate_1", "A1", "[]")
    store.log_measurement(
        eid,
        InstrumentMeasurement(
            measurement_type=MeasurementType.ASMI_INDENTATION,
            payload={
                "timestamps_s": [1761841220.199],
                "z_positions_mm": [-74.01],
                "raw_forces_n": [0.463],
                "corrected_forces_n": [0.004],
                "directions": ["down"],
            },
            metadata={
                "baseline_avg": 0.459,
                "baseline_std": 0.003,
                "force_exceeded": False,
                "data_points": 1,
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


# ─── campaign-experiments subcommand ─────────────────────────────────────────


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


class TestASMIRawCSVSubcommand:

    def test_writes_asmi_new_raw_csvs(self, tmp_path, capsys, monkeypatch):
        db = str(tmp_path / "test.db")
        out_dir = tmp_path / "measurements"
        _seed_asmi_db(db)
        monkeypatch.setattr(
            sys, "argv",
            ["export", "--db-path", db, "asmi-raw-csv", "1", str(out_dir)],
        )

        result = main()

        assert result == 0
        assert "Wrote CSV:" in capsys.readouterr().out
        output = out_dir / "well_A1_20251030_122107.csv"
        assert output.exists()
        assert "Timestamp(s),Z_Position(mm),Raw_Force(N)" in output.read_text()
