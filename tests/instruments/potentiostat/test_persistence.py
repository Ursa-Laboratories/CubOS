"""End-to-end tests for potentiostat result → normalize → DataStore.

Exercises the protocol-engine normalization layer (`normalize_measurement`)
and the DataStore persistence path (`log_measurement` → SQL insert) for each
of the four supported potentiostat techniques.
"""

from __future__ import annotations

import json

import pytest

from data.data_store import DataStore
from instruments.potentiostat.models import (
    CAResult, CPResult, CVResult, OCPResult,
)
from protocol_engine.measurements import (
    InstrumentMeasurement,
    MeasurementType,
    normalize_measurement,
)


def _make_store() -> DataStore:
    store = DataStore(db_path=":memory:")
    cid = store.create_campaign("unit-test")
    eid = store.create_experiment(cid, labware_name="plate", well_id="A1")
    store._experiment_id = eid  # type: ignore[attr-defined]
    return store


# --- normalize_measurement ---------------------------------------------------


class TestNormalize:

    def test_ocp_result(self):
        raw = OCPResult(
            time_s=(0.0, 0.1),
            voltage_v=(0.35, 0.36),
            sample_period_s=0.1,
            duration_s=0.2,
            vendor="admiral",
            metadata={"device_id": "unit-test"},
        )
        m = normalize_measurement("pstat_a", "run_OCP", raw)
        assert m.measurement_type == MeasurementType.POTENTIOSTAT_OCP
        assert m.payload == {"time_s": [0.0, 0.1], "voltage_v": [0.35, 0.36]}
        assert m.metadata["technique"] == "ocp"
        assert m.metadata["vendor"] == "admiral"
        assert m.metadata["instrument_name"] == "pstat_a"
        assert m.metadata["method_name"] == "run_OCP"
        assert m.metadata["device_id"] == "unit-test"
        assert m.metadata["duration_s"] == 0.2

    def test_ca_result(self):
        raw = CAResult(
            time_s=(0.0,),
            voltage_v=(0.5,),
            current_a=(1e-6,),
            sample_period_s=0.01,
            duration_s=1.0,
            step_potential_v=0.5,
            vendor="admiral",
        )
        m = normalize_measurement("pstat_a", "run_CA", raw)
        assert m.measurement_type == MeasurementType.POTENTIOSTAT_CA
        assert m.payload["current_a"] == [1e-6]
        assert m.metadata["step_potential_v"] == 0.5

    def test_cp_result(self):
        raw = CPResult(
            time_s=(0.0,),
            voltage_v=(0.1,),
            current_a=(1e-3,),
            sample_period_s=0.01,
            duration_s=1.0,
            step_current_a=1e-3,
            vendor="admiral",
        )
        m = normalize_measurement("pstat_a", "run_CP", raw)
        assert m.measurement_type == MeasurementType.POTENTIOSTAT_CP
        assert m.metadata["step_current_a"] == 1e-3
        assert m.payload["voltage_v"] == [0.1]

    def test_cv_result(self):
        raw = CVResult(
            time_s=(0.0, 0.01),
            voltage_v=(0.0, 0.05),
            current_a=(1e-6, 2e-6),
            scan_rate_v_s=0.05,
            step_size_v=0.0005,
            cycles=3,
            vendor="admiral",
        )
        m = normalize_measurement("pstat_a", "run_CV", raw)
        assert m.measurement_type == MeasurementType.POTENTIOSTAT_CV
        assert m.metadata["cycles"] == 3
        assert m.metadata["scan_rate_v_s"] == 0.05
        assert m.metadata["step_size_v"] == 0.0005


# --- DataStore persistence ---------------------------------------------------


class TestPersistence:

    def test_schema_includes_potentiostat_measurements_table(self):
        store = _make_store()
        tables = {
            row[0]
            for row in store._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "potentiostat_measurements" in tables
        store.close()

    def test_log_ocp_result_persists_row(self):
        store = _make_store()
        raw = OCPResult(
            time_s=(0.0, 0.1),
            voltage_v=(0.35, 0.36),
            sample_period_s=0.1,
            duration_s=0.2,
            vendor="admiral",
            metadata={"device_id": "unit-test"},
        )
        m = normalize_measurement("pstat_a", "run_OCP", raw)
        row_id = store.log_measurement(store._experiment_id, m)
        assert isinstance(row_id, int)

        row = store._conn.execute(
            "SELECT technique, time_s, voltage_v, current_a, sample_period_s, "
            "duration_s, vendor, device_id "
            "FROM potentiostat_measurements WHERE id = ?",
            (row_id,),
        ).fetchone()
        technique, time_s, voltage_v, current_a, sample_period_s, duration_s, vendor, device_id = row
        assert technique == "ocp"
        assert json.loads(time_s) == [0.0, 0.1]
        assert json.loads(voltage_v) == [0.35, 0.36]
        assert current_a is None
        assert sample_period_s == 0.1
        assert duration_s == 0.2
        assert vendor == "admiral"
        assert device_id == "unit-test"
        store.close()

    def test_log_cv_result_writes_technique_columns(self):
        store = _make_store()
        raw = CVResult(
            time_s=(0.0, 0.01, 0.02),
            voltage_v=(0.0, 0.1, 0.2),
            current_a=(1e-6, 2e-6, 3e-6),
            scan_rate_v_s=0.05,
            step_size_v=0.0005,
            cycles=2,
            vendor="admiral",
        )
        m = normalize_measurement("pstat_a", "run_CV", raw)
        row_id = store.log_measurement(store._experiment_id, m)

        row = store._conn.execute(
            "SELECT technique, scan_rate_v_s, step_size_v, cycles, current_a "
            "FROM potentiostat_measurements WHERE id = ?",
            (row_id,),
        ).fetchone()
        technique, scan_rate, step, cycles, current_a = row
        assert technique == "cv"
        assert scan_rate == 0.05
        assert step == 0.0005
        assert cycles == 2
        assert json.loads(current_a) == [1e-6, 2e-6, 3e-6]
        store.close()

    def test_log_ca_result_writes_step_potential(self):
        store = _make_store()
        raw = CAResult(
            time_s=(0.0,),
            voltage_v=(0.5,),
            current_a=(1e-6,),
            sample_period_s=0.01,
            duration_s=1.0,
            step_potential_v=0.5,
            vendor="admiral",
        )
        m = normalize_measurement("pstat_a", "run_CA", raw)
        row_id = store.log_measurement(store._experiment_id, m)
        step_potential_v = store._conn.execute(
            "SELECT step_potential_v FROM potentiostat_measurements WHERE id = ?",
            (row_id,),
        ).fetchone()[0]
        assert step_potential_v == 0.5
        store.close()

    def test_log_cp_result_writes_step_current(self):
        store = _make_store()
        raw = CPResult(
            time_s=(0.0,),
            voltage_v=(0.1,),
            current_a=(1e-3,),
            sample_period_s=0.01,
            duration_s=1.0,
            step_current_a=1e-3,
            vendor="admiral",
        )
        m = normalize_measurement("pstat_a", "run_CP", raw)
        row_id = store.log_measurement(store._experiment_id, m)
        step_current_a = store._conn.execute(
            "SELECT step_current_a FROM potentiostat_measurements WHERE id = ?",
            (row_id,),
        ).fetchone()[0]
        assert step_current_a == 1e-3
        store.close()

    def test_promoted_metadata_fields_persist(self):
        """device_id / channel / started_at / stopped_at / aborted / stop_reason
        land in their own typed columns rather than a JSON blob.
        """
        store = _make_store()
        raw = OCPResult(
            time_s=(0.0, 0.1),
            voltage_v=(0.35, 0.36),
            sample_period_s=0.1,
            duration_s=0.2,
            vendor="admiral",
            metadata={
                "device_id": "SquidStatPlus-42",
                "channel": 1,
                "started_at": "2026-04-13T12:34:56+00:00",
                "stopped_at": "2026-04-13T12:35:01+00:00",
                "aborted": False,
                "stop_reason": "completed",
            },
        )
        m = normalize_measurement("pstat_a", "run_OCP", raw)
        row_id = store.log_measurement(store._experiment_id, m)

        row = store._conn.execute(
            "SELECT device_id, channel, started_at, stopped_at, aborted, "
            "stop_reason FROM potentiostat_measurements WHERE id = ?",
            (row_id,),
        ).fetchone()
        device_id, channel, started_at, stopped_at, aborted, stop_reason = row
        assert device_id == "SquidStatPlus-42"
        assert channel == 1
        assert started_at == "2026-04-13T12:34:56+00:00"
        assert stopped_at == "2026-04-13T12:35:01+00:00"
        assert aborted == 0   # SQLite stores bool as int
        assert stop_reason == "completed"
        store.close()

    def test_aborted_true_persists_as_one(self):
        store = _make_store()
        raw = OCPResult(
            time_s=(0.0,),
            voltage_v=(0.3,),
            sample_period_s=0.1,
            duration_s=0.1,
            vendor="admiral",
            metadata={"aborted": True, "stop_reason": "user_stop"},
        )
        m = normalize_measurement("pstat_a", "run_OCP", raw)
        row_id = store.log_measurement(store._experiment_id, m)
        aborted = store._conn.execute(
            "SELECT aborted FROM potentiostat_measurements WHERE id = ?",
            (row_id,),
        ).fetchone()[0]
        assert aborted == 1
        store.close()
