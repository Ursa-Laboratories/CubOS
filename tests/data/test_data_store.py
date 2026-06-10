"""Tests for the DataStore SQLite persistence layer."""

from __future__ import annotations

import json

import pytest

from data.data_store import DataStore
from instruments.filmetrics.models import MeasurementResult
from instruments.uvvis_ccs.models import UVVisSpectrum
from protocol_engine.measurements import InstrumentMeasurement, MeasurementType


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_store() -> DataStore:
    """Create an in-memory DataStore for testing."""
    return DataStore(db_path=":memory:")


def _make_uvvis_spectrum(n: int = 10) -> UVVisSpectrum:
    wavelengths = tuple(400.0 + i for i in range(n))
    intensities = tuple(0.1 * i for i in range(n))
    return UVVisSpectrum(
        wavelengths=wavelengths,
        intensities=intensities,
        integration_time_s=0.24,
    )


def _make_filmetrics_result() -> MeasurementResult:
    return MeasurementResult(thickness_nm=150.5, goodness_of_fit=0.95)


# ─── Schema creation ─────────────────────────────────────────────────────────


class TestSchemaCreation:

    def test_tables_exist(self):
        store = _make_store()
        cursor = store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row[0] for row in cursor.fetchall()}
        expected = {
            "campaigns", "experiments",
            "uvvis_measurements", "filmetrics_measurements",
            "camera_measurements", "asmi_measurements", "labware",
        }
        assert expected.issubset(tables)
        store.close()

    def test_idempotent_table_creation(self):
        store = _make_store()
        store._create_tables()
        store._create_tables()
        store.close()

    def test_in_memory_db_works(self):
        store = _make_store()
        assert store._conn is not None
        store.close()

    def test_default_db_path_uses_env_override(self, monkeypatch, tmp_path):
        db_path = tmp_path / "runtime" / "panda_data.db"
        monkeypatch.setenv("CUBOS_DATA_DB_PATH", str(db_path))

        store = DataStore()
        store.close()

        assert db_path.is_file()

    def test_foreign_key_enforcement(self):
        store = _make_store()
        with pytest.raises(Exception):
            store.create_experiment(
                campaign_id=9999,
                labware_name="plate_1",
                well_id="A1",
                contents_json="[]",
            )
        store.close()


# ─── Campaign CRUD ────────────────────────────────────────────────────────────


class TestCampaignCRUD:

    def test_create_returns_id(self):
        store = _make_store()
        cid = store.create_campaign(description="test campaign")
        assert isinstance(cid, int)
        assert cid > 0
        store.close()

    def test_stores_description(self):
        store = _make_store()
        cid = store.create_campaign(description="MOF screening run")
        row = store._conn.execute(
            "SELECT description FROM campaigns WHERE id = ?", (cid,)
        ).fetchone()
        assert row[0] == "MOF screening run"
        store.close()

    def test_stores_config_paths(self):
        store = _make_store()
        cid = store.create_campaign(
            description="test",
            deck_config="mock/deck.yaml",
            board_config="legacy-board.yaml",
            gantry_config="mock/gantry.yaml",
            protocol_config="mock/protocol.yaml",
        )
        row = store._conn.execute(
            "SELECT deck_config, board_config, gantry_config, protocol_config "
            "FROM campaigns WHERE id = ?",
            (cid,),
        ).fetchone()
        assert row == ("mock/deck.yaml", "legacy-board.yaml",
                       "mock/gantry.yaml", "mock/protocol.yaml")
        store.close()

    def test_default_status(self):
        store = _make_store()
        cid = store.create_campaign(description="test")
        row = store._conn.execute(
            "SELECT status FROM campaigns WHERE id = ?", (cid,)
        ).fetchone()
        assert row[0] == "running"
        store.close()


# ─── Experiment CRUD ──────────────────────────────────────────────────────────


class TestExperimentCRUD:

    def test_create_returns_id(self):
        store = _make_store()
        cid = store.create_campaign(description="test")
        eid = store.create_experiment(
            campaign_id=cid,
            labware_name="plate_1",
            well_id="A1",
            contents_json="[]",
        )
        assert isinstance(eid, int)
        assert eid > 0
        store.close()

    def test_stores_labware_and_well(self):
        store = _make_store()
        cid = store.create_campaign(description="test")
        eid = store.create_experiment(
            campaign_id=cid,
            labware_name="plate_1",
            well_id="B3",
            contents_json='[{"source_name": "vial_1", "volume_ul": 50.0}]',
        )
        row = store._conn.execute(
            "SELECT labware_name, well_id, contents FROM experiments WHERE id = ?",
            (eid,),
        ).fetchone()
        assert row[0] == "plate_1"
        assert row[1] == "B3"
        parsed = json.loads(row[2])
        assert parsed[0]["source_name"] == "vial_1"
        store.close()


# ─── UVVis measurement logging ───────────────────────────────────────────────


class TestUVVisMeasurementLogging:

    def test_blob_round_trip(self):
        store = _make_store()
        cid = store.create_campaign(description="test")
        eid = store.create_experiment(cid, "plate_1", "A1", "[]")

        spectrum = _make_uvvis_spectrum(20)
        mid = store.log_measurement(eid, spectrum)
        assert isinstance(mid, int)

        row = store._conn.execute(
            "SELECT wavelengths, intensities, integration_time_s "
            "FROM uvvis_measurements WHERE id = ?",
            (mid,),
        ).fetchone()

        assert tuple(json.loads(row[0])) == spectrum.wavelengths
        assert tuple(json.loads(row[1])) == spectrum.intensities
        assert row[2] == pytest.approx(0.24)
        store.close()

    def test_integration_time_stored(self):
        store = _make_store()
        cid = store.create_campaign(description="test")
        eid = store.create_experiment(cid, "plate_1", "A1", "[]")

        spectrum = UVVisSpectrum(
            wavelengths=(500.0,), intensities=(0.5,), integration_time_s=1.5
        )
        mid = store.log_measurement(eid, spectrum)

        row = store._conn.execute(
            "SELECT integration_time_s FROM uvvis_measurements WHERE id = ?",
            (mid,),
        ).fetchone()
        assert row[0] == pytest.approx(1.5)
        store.close()


# ─── Filmetrics measurement logging ──────────────────────────────────────────


class TestFilmetricsMeasurementLogging:

    def test_stores_thickness_and_gof(self):
        store = _make_store()
        cid = store.create_campaign(description="test")
        eid = store.create_experiment(cid, "plate_1", "A1", "[]")

        result = _make_filmetrics_result()
        mid = store.log_measurement(eid, result)

        row = store._conn.execute(
            "SELECT thickness_nm, goodness_of_fit "
            "FROM filmetrics_measurements WHERE id = ?",
            (mid,),
        ).fetchone()
        assert row[0] == pytest.approx(150.5)
        assert row[1] == pytest.approx(0.95)
        store.close()

    def test_handles_none_values(self):
        store = _make_store()
        cid = store.create_campaign(description="test")
        eid = store.create_experiment(cid, "plate_1", "A1", "[]")

        result = MeasurementResult(thickness_nm=None, goodness_of_fit=None)
        mid = store.log_measurement(eid, result)

        row = store._conn.execute(
            "SELECT thickness_nm, goodness_of_fit "
            "FROM filmetrics_measurements WHERE id = ?",
            (mid,),
        ).fetchone()
        assert row[0] is None
        assert row[1] is None
        store.close()


# ─── Camera measurement logging ──────────────────────────────────────────────


class TestCameraMeasurementLogging:

    def test_stores_image_path(self):
        store = _make_store()
        cid = store.create_campaign(description="test")
        eid = store.create_experiment(cid, "plate_1", "A1", "[]")

        mid = store.log_measurement(eid, "/images/A1_001.png")

        row = store._conn.execute(
            "SELECT image_path FROM camera_measurements WHERE id = ?",
            (mid,),
        ).fetchone()
        assert row[0] == "/images/A1_001.png"
        store.close()


# ─── Dispatch ─────────────────────────────────────────────────────────────────


class TestLogMeasurementDispatch:

    def test_routes_uvvis(self):
        store = _make_store()
        cid = store.create_campaign(description="test")
        eid = store.create_experiment(cid, "plate_1", "A1", "[]")
        mid = store.log_measurement(eid, _make_uvvis_spectrum())
        assert store._conn.execute(
            "SELECT COUNT(*) FROM uvvis_measurements WHERE id = ?", (mid,)
        ).fetchone()[0] == 1
        store.close()

    def test_routes_filmetrics(self):
        store = _make_store()
        cid = store.create_campaign(description="test")
        eid = store.create_experiment(cid, "plate_1", "A1", "[]")
        mid = store.log_measurement(eid, _make_filmetrics_result())
        assert store._conn.execute(
            "SELECT COUNT(*) FROM filmetrics_measurements WHERE id = ?", (mid,)
        ).fetchone()[0] == 1
        store.close()

    def test_routes_camera(self):
        store = _make_store()
        cid = store.create_campaign(description="test")
        eid = store.create_experiment(cid, "plate_1", "A1", "[]")
        mid = store.log_measurement(eid, "/path/to/image.png")
        assert store._conn.execute(
            "SELECT COUNT(*) FROM camera_measurements WHERE id = ?", (mid,)
        ).fetchone()[0] == 1
        store.close()

    def test_unknown_type_raises_type_error(self):
        store = _make_store()
        cid = store.create_campaign(description="test")
        eid = store.create_experiment(cid, "plate_1", "A1", "[]")
        with pytest.raises(TypeError, match="Unsupported measurement type"):
            store.log_measurement(eid, 42)
        store.close()

    def test_routes_uvvis_instrument_measurement(self):
        store = _make_store()
        cid = store.create_campaign(description="test")
        eid = store.create_experiment(cid, "plate_1", "A1", "[]")

        measurement = InstrumentMeasurement(
            measurement_type=MeasurementType.UVVIS_SPECTRUM,
            payload={
                "wavelength_nm": [500.0, 501.0],
                "intensity_au": [0.5, 0.6],
            },
            metadata={"integration_time_s": 0.24},
        )
        mid = store.log_measurement(eid, measurement)
        assert store._conn.execute(
            "SELECT COUNT(*) FROM uvvis_measurements WHERE id = ?", (mid,)
        ).fetchone()[0] == 1
        store.close()

    def test_uvvis_instrument_measurement_blob_round_trip(self):
        store = _make_store()
        cid = store.create_campaign(description="test")
        eid = store.create_experiment(cid, "plate_1", "A1", "[]")

        measurement = InstrumentMeasurement(
            measurement_type=MeasurementType.UVVIS_SPECTRUM,
            payload={
                "wavelength_nm": [500.0, 501.0, 502.0],
                "intensity_au": [0.5, 0.6, 0.7],
            },
            metadata={"integration_time_s": 1.5},
        )
        mid = store.log_measurement(eid, measurement)
        row = store._conn.execute(
            "SELECT wavelengths, intensities, integration_time_s "
            "FROM uvvis_measurements WHERE id = ?",
            (mid,),
        ).fetchone()

        assert json.loads(row[0]) == [500.0, 501.0, 502.0]
        assert json.loads(row[1]) == [0.5, 0.6, 0.7]
        assert row[2] == pytest.approx(1.5)
        store.close()


# ─── ASMI InstrumentMeasurement round-trip ───────────────────────────────────


class TestASMIInstrumentMeasurementLogging:

    def test_asmi_json_round_trip(self):
        store = _make_store()
        cid = store.create_campaign(description="asmi test")
        eid = store.create_experiment(cid, "film_plate", "B1", "[]")

        measurement = InstrumentMeasurement(
            measurement_type=MeasurementType.ASMI_INDENTATION,
            payload={
                "sample_timestamps": [1.0, 1.1, 1.2],
                "z_positions_mm": [0.0, 0.1, 0.2],
                "raw_forces_n": [0.01, 0.02, 0.03],
                "corrected_forces_n": [0.005, 0.015, 0.025],
                "directions": ["down", "down", "up"],
            },
            metadata={
                "baseline_avg": 0.005,
                "baseline_std": 0.001,
                "force_exceeded": False,
                "data_points": 3,
                "step_size_mm": 0.1,
                "z_target_mm": -2.0,
                "force_limit_n": 10.0,
            },
        )
        mid = store.log_measurement(eid, measurement)

        row = store._conn.execute(
            "SELECT sample_timestamps, z_positions, raw_forces, "
            "corrected_forces, directions, step_size_mm, z_target_mm, "
            "force_limit_n FROM asmi_measurements WHERE id = ?",
            (mid,),
        ).fetchone()

        assert json.loads(row[0]) == [1.0, 1.1, 1.2]
        assert json.loads(row[1]) == [0.0, 0.1, 0.2]
        assert json.loads(row[2]) == [0.01, 0.02, 0.03]
        assert json.loads(row[3]) == [0.005, 0.015, 0.025]
        assert json.loads(row[4]) == ["down", "down", "up"]
        assert row[5] == pytest.approx(0.1)
        assert row[6] == pytest.approx(-2.0)
        assert row[7] == pytest.approx(10.0)
        store.close()


# ─── Context manager ─────────────────────────────────────────────────────────


class TestContextManager:

    def test_context_manager(self):
        with DataStore(db_path=":memory:") as store:
            cid = store.create_campaign(description="ctx test")
            assert cid > 0
