"""Offline contracts for safe run artifacts and durable trace reads."""

import json

import pytest

from cubos_api.models.runs import RunRecord
from cubos_api.services.run_store import RunStore


def make_store(tmp_path):
    store = RunStore(tmp_path)
    record = RunRecord(run_id="trace", state="queued", created_at=1, metadata={"password": "secret-value"})
    store.create(record, gantry_yaml="name: gantry\npassword: secret-value\n", deck_yaml="labware: {}\n", protocol_yaml="protocol: [{home: null}]\n")
    return store


def test_snapshots_and_metadata_do_not_expose_credentials(tmp_path):
    store = make_store(tmp_path)
    assert "secret-value" not in (store.run_dir("trace") / "gantry.yaml").read_text()
    assert "secret-value" not in (store.run_dir("trace") / "run.json").read_text()
    assert "gantry_snapshot_sha256" in store.read("trace").digests


def test_incomplete_tail_is_repaired_and_sequence_uses_maximum(tmp_path):
    store = make_store(tmp_path)
    path = store.run_dir("trace") / "events.jsonl"
    event = json.loads(path.read_text())
    event["sequence"] = 9
    path.write_text(json.dumps(event) + '\n{"sequence":')
    store = RunStore(tmp_path)
    assert len(store.events("trace")) == 1
    assert store.append_event("trace", state="running", message="start").sequence == 10
    assert [event.sequence for event in store.events("trace")] == [9, 10]


def test_interior_event_corruption_is_reported(tmp_path):
    store = make_store(tmp_path)
    path = store.run_dir("trace") / "events.jsonl"
    path.write_text('{bad}\n' + path.read_text())
    with pytest.raises(ValueError):
        RunStore(tmp_path).append_event("trace", state="running", message="start")


def test_saved_plan_does_not_recompile_sanitized_artifact(monkeypatch):
    from types import SimpleNamespace
    from cubos_api.routers import runs

    record = RunRecord(run_id="trace", state="succeeded", created_at=1, metadata={"protocol": {"plan": [{"index": 0, "command": "home", "args": {}, "source": {"index": 0}}]}})
    monkeypatch.setattr(runs, "get_run_manager", lambda: SimpleNamespace(get=lambda _: record))
    plan = runs.get_run_plan("trace")
    assert plan.steps[0].summary == "home"
    assert plan.steps[0].source == {"index": 0}


def test_steps_response_retains_pagination_cursor(monkeypatch):
    from types import SimpleNamespace
    from cubos_api.routers import runs

    calls = []
    def steps(run_id, **kwargs):
        calls.append((run_id, kwargs))
        return [{"sequence": 7, "parameters": {"volume_ul": 10}, "status": "completed"}]
    monkeypatch.setattr(runs, "get_run_manager", lambda: SimpleNamespace(get=lambda _: object(), steps=steps))
    page = runs.get_run_steps("trace", after_sequence=3, limit=1)
    assert page.next_after_sequence == 7
    assert page.steps[0]["parameters"] == {"volume_ul": 10}
    assert calls == [("trace", {"after_sequence": 3, "limit": 1})]


def test_sqlite_terminal_state_overrides_stale_sidecar(tmp_path):
    from cubos.data import DataStore
    from cubos_api.config import get_settings
    from cubos_api.services.run_manager import RunManager

    manager = RunManager(get_settings())
    record = RunRecord(run_id="authority", state="running", created_at=1, finished_at=99)
    manager.store.create(record, gantry_yaml="{}", deck_yaml="{}", protocol_yaml="{}")
    store = DataStore(get_settings().data_db_path)
    try:
        store.execution_records.create_run("authority", metadata={"saved": True})
        store.execution_records.recover_run("authority", "2026-10-15T00:00:00+00:00")
    finally:
        store.close()
    actual = manager.get("authority")
    assert actual.state == "failed"
    assert actual.core_status == "interrupted"
    assert actual.finished_at is None
    assert actual.metadata == {"saved": True}
    assert actual.recovered_at is not None


def test_restart_legacy_run_has_no_fabricated_finish_time(tmp_path):
    from cubos_api.config import get_settings
    from cubos_api.services.run_manager import RunManager

    settings = get_settings()
    store = RunStore(settings.ensure_run_dir())
    store.create(RunRecord(run_id="legacy", state="running", created_at=1), gantry_yaml="{}", deck_yaml="{}", protocol_yaml="{}")
    recovered = RunManager(settings).get("legacy")
    assert recovered.state == "failed"
    assert recovered.finished_at is None
    assert recovered.recovered_at is not None


def test_failure_after_cancel_request_is_still_failed(monkeypatch):
    import time
    from threading import Event
    from cubos_api.config import get_settings
    from cubos_api.models.runs import RunSubmission
    from cubos_api.services.run_manager import RunManager
    from cubos_api.routers import gantry

    entered, release = Event(), Event()
    def fail(**kwargs):
        entered.set()
        release.wait(2)
        raise RuntimeError("secret driver failure")
    monkeypatch.setattr(gantry, "run_protocol_on_session", fail)
    monkeypatch.setattr(gantry, "request_feed_hold_interrupt", lambda: None)
    manager = RunManager(get_settings())
    manager.submit(RunSubmission(run_id="cancel-failure", gantry_config="{}", deck_config="{}", protocol_yaml="protocol: [{home: null}]"))
    assert entered.wait(2)
    manager.cancel("cancel-failure")
    release.set()
    deadline = time.monotonic() + 3
    while manager.active_run_id and time.monotonic() < deadline:
        time.sleep(.01)
    record = manager.get("cancel-failure")
    assert record.state == "failed"
    assert "secret driver failure" not in (manager.store.run_dir(record.run_id) / "error.txt").read_text()


def prepare_worker(manager, run_id="worker"):
    from threading import Event
    record = RunRecord(run_id=run_id, state="queued", created_at=1, metadata={"software": "user-overwrite", "password": "hidden"})
    bundle = ("{}", "{}", "protocol: [{home: null}]")
    manager.store.create(record, gantry_yaml=bundle[0], deck_yaml=bundle[1], protocol_yaml=bundle[2])
    manager._bundles[run_id] = bundle
    manager._cancel_events[run_id] = Event()
    manager._active_run_id = run_id


def test_projection_failure_preserves_completed_core_run(monkeypatch):
    from cubos_api.config import get_settings
    from cubos_api.services.run_manager import RunManager

    manager = RunManager(get_settings())
    prepare_worker(manager)
    monkeypatch.setattr(manager, "_dispatch", lambda *args: {"ok": True})
    def fail_projection(*args):
        raise OSError("secret filesystem information")
    monkeypatch.setattr(manager.store, "write_result", fail_projection)
    manager._execute("worker")
    record = manager.get("worker")
    assert record.state == "succeeded"
    assert record.core_status == "completed"
    assert record.recording_errors[-1]["stage"] == "api_projection"
    assert "secret filesystem information" not in json.dumps(record.recording_errors)
    assert record.metadata["software"] != "user-overwrite"
    assert record.metadata["user_metadata"]["software"] == "user-overwrite"
    assert manager.active_run_id is None


def test_worker_setup_failure_always_releases_reservation(monkeypatch):
    from cubos_api.config import get_settings
    from cubos_api.services import run_manager

    manager = run_manager.RunManager(get_settings())
    prepare_worker(manager)
    def fail_open(*args):
        raise OSError("database unavailable")
    monkeypatch.setattr(run_manager, "DataStore", fail_open)
    manager._execute("worker")
    assert manager.active_run_id is None
    assert "worker" not in manager._bundles
    assert "worker" not in manager._cancel_events
    assert manager.store.read("worker").state == "failed"


def test_result_serialization_omits_opaque_object_attributes():
    from cubos_api.services.run_manager import _jsonable
    class Secret:
        password = "should not leak"
        def __repr__(self):
            raise AssertionError("must not invoke repr")
    assert _jsonable(Secret()) == "[omitted object]"


def test_step_events_carry_durable_trace_identifiers(tmp_path):
    from cubos.data import DataStore
    from cubos.protocol_engine.execution_trace import RunRecorder
    from cubos_api.services.step_observer import RunStoreStepObserver

    store = make_store(tmp_path / "runs")
    db = DataStore(tmp_path / "trace.sqlite")
    try:
        observer = RunStoreStepObserver(store, "trace")
        with RunRecorder(db, run_id="trace") as recorder:
            with recorder.step("home"):
                outer = recorder.active_step_id
                with recorder.step("nested"):
                    inner = recorder.active_step_id
                    observer.step_started(index=0, command="nested", substep="nested")
        data = store.events("trace")[-1].data
        assert data["run_id"] == "trace"
        assert data["step_execution_id"] == inner
        assert data["parent_step_execution_id"] == outer
    finally:
        db.close()


def test_legacy_reads_do_not_create_database():
    from cubos_api.config import get_settings
    from cubos_api.services.run_manager import RunManager
    settings = get_settings()
    path = settings.data_db_path
    assert not path.exists()
    manager = RunManager(settings)
    prepare_worker(manager)
    assert manager.get("worker").state == "queued"
    assert manager.steps("worker") == []
    assert not path.exists()


def test_trace_reads_are_read_only_and_work_during_writer_transaction():
    from cubos.data import DataStore
    from cubos_api.config import get_settings
    from cubos_api.services.run_manager import RunManager
    settings = get_settings()
    manager = RunManager(settings)
    prepare_worker(manager)
    store = DataStore(settings.data_db_path)
    try:
        store.execution_records.create_run("worker", metadata={})
        before = settings.data_db_path.stat().st_mtime_ns
        schema = store._conn.execute("PRAGMA schema_version").fetchone()
        store._conn.execute("BEGIN IMMEDIATE")
        assert manager.get("worker").core_status == "running"
        assert manager.steps("worker") == []
        assert settings.data_db_path.stat().st_mtime_ns == before
        assert store._conn.execute("PRAGMA schema_version").fetchone() == schema
        store._conn.rollback()
    finally:
        store.close()


def test_api_terminal_state_waits_for_result_projection(monkeypatch):
    from threading import Event, Thread
    from cubos_api.config import get_settings
    from cubos_api.services.run_manager import RunManager
    manager = RunManager(get_settings())
    prepare_worker(manager)
    entered, release = Event(), Event()
    original = manager.store.write_result
    def blocked_write(record, result):
        entered.set()
        assert release.wait(3)
        original(record, result)
    monkeypatch.setattr(manager, "_dispatch", lambda *args: {"value": 3})
    monkeypatch.setattr(manager.store, "write_result", blocked_write)
    worker = Thread(target=manager._execute, args=("worker",))
    worker.start()
    try:
        assert entered.wait(3)
        pending = manager.get("worker")
        assert pending.core_status == "completed"
        assert pending.state == "running"
        assert pending.artifacts_pending is True
    finally:
        release.set()
        worker.join(3)
    done = manager.get("worker")
    assert done.state == "succeeded"
    assert done.artifacts_pending is False
    assert done.result == {"value": 3}


def test_submission_cannot_reuse_id_from_another_run_directory():
    from cubos.data import DataStore
    from cubos_api.config import get_settings
    from cubos_api.models.runs import RunSubmission
    from cubos_api.services.run_manager import RunManager, RunConflictError

    manager = RunManager(get_settings())
    with DataStore(get_settings().data_db_path) as store:
        store.execution_records.create_run('used-id', metadata={})
        store.execution_records.finish_run('used-id', status='completed')
    submission = RunSubmission(run_id='used-id', gantry_config='{}', deck_config='{}',
                               protocol_yaml='protocol: [{home: null}]', mock_mode=True)
    with pytest.raises(RunConflictError, match='experiment database'):
        manager.submit(submission)
    assert not manager.store.run_dir('used-id').exists()


def test_historical_missing_mode_remains_unknown():
    record = RunRecord.model_validate({"run_id": "old", "state": "succeeded", "created_at": 1})
    assert record.mock_mode is None
