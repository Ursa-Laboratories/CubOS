import json
import sqlite3

import pytest

from cubos.data.data_store import DataStore
from cubos.protocol_engine.measurements import InstrumentMeasurement, MeasurementType


@pytest.fixture
def store():
    with DataStore(":memory:") as value:
        yield value


def step(records, name="s", run="r", **kw):
    return records.start_step(
        name,
        run,
        command="measure",
        source={"path": [0]},
        parameters={"well": "A1"},
        started_at="2026-10-15T12:00:00Z",
        **kw,
    )


def test_order_parent_pagination_and_recovery(store):
    records = store.execution_records
    records.create_run("r", metadata={"protocol": {"steps": []}})
    records.create_run("other", metadata={})
    assert step(records)["sequence"] == 1
    with pytest.raises(ValueError, match="same run"):
        step(records, "bad", "other", parent_step_execution_id="s")
    assert step(records, "child", parent_step_execution_id="s")["sequence"] == 2
    with pytest.raises(sqlite3.IntegrityError):
        step(records, "child")
    assert step(records, "third")["sequence"] == 3
    records.update_step_parameters("s", {"resolved": {"well": "B2"}})
    assert records.list_steps("r", limit=1)[0]["parameters"]["resolved"] == {
        "well": "B2"
    }
    assert [r["sequence"] for r in records.list_steps("r", after_sequence=1)] == [2, 3]
    records.finish_step("child", status="completed", ended_at="end", duration_ns=20)
    records.recover_run("r", "recovered")
    rows = records.list_steps("r")
    assert rows[0]["status"] == "interrupted"
    assert rows[0]["ended_at"] is None and rows[0]["duration_ns"] is None
    assert rows[1]["ended_at"] == "end" and rows[1]["duration_ns"] == 20
    assert records.get_run("r")["details"] == {"kind": "owner_lost"}
    assert len(records.list_runs(limit=1, offset=1)) == 1
    with pytest.raises(ValueError):
        records.list_steps("r", limit=0)
    with pytest.raises(ValueError):
        step(records, "closed")


def test_measurement_metadata_link_and_atomic_failure(store):
    campaign = store.create_campaign("one")
    other = store.create_campaign("two")
    records = store.execution_records
    records.create_run("r", campaign_id=campaign, metadata={})
    step(records)
    result = InstrumentMeasurement(
        MeasurementType.FILMETRICS_THICKNESS,
        {"thickness_nm": 2, "goodness_of_fit": 0.9},
        {"vendor": "test", "nested": {"a": [1, 2]}},
    )
    exp, measurement = store.log_experiment_measurement(
        campaign_id=campaign,
        labware_key="plate",
        labware_name="plate",
        well_id="A1",
        contents_json=None,
        result=result,
        step_execution_id="s",
        metadata={"operator": "A"},
    )
    row = store._conn.execute(
        "SELECT step_execution_id,metadata_json FROM filmetrics_measurements WHERE id=?",
        (measurement,),
    ).fetchone()
    assert row[0] == "s"
    assert json.loads(row[1]) == {**result.metadata, "operator": "A"}
    with pytest.raises(ValueError):
        store.log_experiment_measurement(
            campaign_id=other,
            labware_key="plate",
            labware_name="plate",
            well_id="A1",
            contents_json=None,
            result=result,
            step_execution_id="s",
        )
    assert store._conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0] == 1
    with pytest.raises(ValueError):
        records.update_run("r", campaign_id=other)
    with pytest.raises(TypeError):
        store.log_measurement(exp, object(), metadata={"bad": float("nan")})
    assert (
        store._conn.execute("SELECT COUNT(*) FROM filmetrics_measurements").fetchone()[
            0
        ]
        == 1
    )
    store.log_measurement(exp, "image.png")
    assert store._conn.execute(
        "SELECT step_execution_id,metadata_json FROM camera_measurements"
    ).fetchone() == (None, None)


def test_legacy_migration_preserves_nulls_and_reopens(tmp_path):
    path = tmp_path / "legacy.db"
    with DataStore(path) as store:
        campaign = store.create_campaign("legacy")
        exp = store.create_experiment(campaign, "vial", None)
        store.log_measurement(exp, "old.png")
        for table in ("protocol_runs", "step_executions"):
            store._conn.execute(f"DROP TABLE {table}")
        store._conn.execute("DROP INDEX camera_measurements_step")
        store._conn.execute(
            "ALTER TABLE camera_measurements DROP COLUMN step_execution_id"
        )
        store._conn.execute("ALTER TABLE camera_measurements DROP COLUMN metadata_json")
        store._conn.commit()
    with DataStore(path) as store:
        assert store._conn.execute(
            "SELECT image_path,step_execution_id,metadata_json FROM camera_measurements"
        ).fetchone() == ("old.png", None, None)
        store.execution_records.create_run("r", metadata={})
    with DataStore(path) as store:
        assert store.execution_records.get_run("r")["metadata"] == {}


def test_transactions_and_invalid_updates(store):
    records = store.execution_records
    store._conn.execute("BEGIN")
    with pytest.raises(RuntimeError):
        records.create_run("r", metadata={})
    with pytest.raises(RuntimeError):
        store.log_measurement(1, "image.png")
    assert store._conn.in_transaction
    store._conn.rollback()
    records.create_run("r", metadata={})
    records.update_run("r", metadata={"name": "new"})
    assert records.get_run("r")["metadata"] == {"name": "new"}
    assert records.get_run("missing") is None
    for action in [
        lambda: records.update_run("missing", status="failed"),
        lambda: records.update_run("r", bogus=1),
        lambda: records.finish_run("r", status="running"),
        lambda: records.finish_step("missing", status="failed"),
        lambda: records.update_step_parameters("missing", {}),
        lambda: records.finish_step("missing", status="running"),
    ]:
        with pytest.raises(ValueError):
            action()
    step(records)
    records.finish_step("s", status="failed", details={"error": "failure"})
    records.finish_run(
        "r",
        status="failed",
        ended_at="end",
        duration_ns=8,
        recording_errors=["write failed"],
    )
    records.recover_run("r", "later")
    assert records.get_run("r")["ended_at"] == "end"
    assert records.get_run("r")["recording_errors"] == ["write failed"]


def test_terminal_sequences_and_state_guards(store):
    records = store.execution_records
    records.create_run("r", metadata={"name": "original"}, status="queued")
    assert records.get_run("r")["started_at"] is None
    assert step(records)["sequence"] == 1
    records.finish_step("s", status="completed", duration_ns=10)
    assert records.get_step("s")["terminal_sequence"] == 2
    records.finish_step("s", status="completed", duration_ns=10)
    for action in [
        lambda: records.finish_step("s", status="failed"),
        lambda: records.update_step_parameters("s", {}),
        lambda: step(records, "child", parent_step_execution_id="s"),
    ]:
        with pytest.raises(ValueError):
            action()
    assert step(records, "next")["sequence"] == 3
    with pytest.raises(ValueError):
        records.finish_step("next", status="completed", duration_ns=-1)
    with pytest.raises(ValueError):
        records.finish_run("r", status="completed", duration_ns=-1)
    records.finish_run("r", status="completed", duration_ns=20)
    assert records.get_run("r")["terminal_sequence"] == 4
    records.finish_run("r", status="completed", duration_ns=20)
    for fields in [
        {"status": "running"},
        {"metadata": {"name": "changed"}},
        {"metadata": {"name": "original", "extra": True}},
    ]:
        with pytest.raises(ValueError):
            records.update_run("r", **fields)
    records.update_run(
        "r", metadata={"name": "original", "projection_errors": ["failure"]}
    )
    assert records.get_run("r")["metadata"]["projection_errors"] == ["failure"]
    with pytest.raises(ValueError):
        records.create_run("bad", metadata={}, status="succeeded")
    assert records.get_step("absent") is None


def test_camera_link_failure_rolls_back_payload_and_experiment(store):
    campaign = store.create_campaign("camera")
    store.execution_records.create_run("r", campaign_id=campaign, metadata={})
    step(store.execution_records)
    store._conn.execute("CREATE TRIGGER reject_camera_metadata BEFORE UPDATE ON camera_measurements BEGIN SELECT RAISE(ABORT, 'storage failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        store.log_experiment_measurement(campaign_id=campaign, labware_key="plate", labware_name="plate", well_id="A1", contents_json=None, result="image.png", step_execution_id="s")
    assert store._conn.execute("SELECT COUNT(*) FROM camera_measurements").fetchone()[0] == 0
    assert store._conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0] == 0
