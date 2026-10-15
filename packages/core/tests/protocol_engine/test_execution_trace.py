"""Offline checks for durable command boundaries and process ownership."""

from __future__ import annotations

import json
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from cubos.data.data_store import DataStore
from cubos.protocol_engine import execution_trace as trace


@pytest.fixture
def store():
    with DataStore(":memory:") as store:
        yield store


@pytest.fixture(autouse=True)
def cheap_identity(monkeypatch):
    monkeypatch.setattr(trace, "software_identity", lambda: {"cubos_version": "test"})


def test_success_nested_repeat_order_resolved_and_skip(store):
    with trace.RunRecorder(store, run_id="run") as recorder:
        assert trace.current_trace() is recorder
        assert recorder.active_step_id is None
        recorder.update_metadata(operator="Ada")
        recorder.resolved(ignored=True)
        recorder.skipped("ignored without a step")
        with recorder.step("repeat", {"count": 2}, source={"pointer": "/protocol/0"}):
            parent = recorder.active_step_id
            for iteration in range(2):
                with recorder.step(
                    "measure", {"well": "A1"}, iteration_index=iteration
                ):
                    recorder.resolved(well="A2", temperature=23)
            with recorder.step("scan", {"wells": []}):
                recorder.skipped("no usable wells")
    assert trace.current_trace() is None
    run = store.execution_records.get_run("run")
    assert run["status"] == "completed" and run["duration_ns"] >= 0
    assert run["metadata"]["operator"] == "Ada"
    steps = store.execution_records.list_steps("run")
    assert [s["sequence"] for s in steps] == [1, 2, 4, 6]
    assert [s["terminal_sequence"] for s in steps] == [8, 3, 5, 7]
    assert [s["parent_step_execution_id"] for s in steps] == [
        None,
        parent,
        parent,
        parent,
    ]
    assert [s["iteration_index"] for s in steps] == [None, 0, 1, None]
    assert steps[1]["parameters"]["resolved"] == {"well": "A2", "temperature": 23}
    assert steps[1]["source"] == {"pointer": "/protocol/0"}
    assert steps[-1]["status"] == "skipped"
    assert steps[-1]["details"]["stage"] == "preflight"
    assert run["terminal_sequence"] == 9


def test_failure_preserves_original_exception_and_redacts_message(store):
    error = ValueError("password=super-secret")
    with pytest.raises(ValueError) as caught:
        with trace.RunRecorder(store, run_id="run") as recorder:
            with recorder.step("measure"):
                raise error
    assert caught.value is error
    run = store.execution_records.get_run("run")
    step = store.execution_records.list_steps("run")[0]
    assert run["status"] == step["status"] == "failed"
    assert step["details"] == {
        "kind": "error",
        "type": "ValueError",
        "stage": "execution",
        "message_omitted": True,
    }
    assert "super-secret" not in json.dumps(run)
    assert trace.current_trace() is None


def test_duration_uses_monotonic_clock_despite_utc_rollback(store, monkeypatch):
    utc_values = iter(
        [
            "2026-10-15T12:00:00Z",
            "2026-10-15T11:00:00Z",
            "2026-10-15T10:00:00Z",
            "2026-10-15T09:00:00Z",
        ]
    )
    monotonic_values = iter([100, 120, 160, 200])
    monkeypatch.setattr(trace, "utc_now", lambda: next(utc_values))
    monkeypatch.setattr(trace.time, "monotonic_ns", lambda: next(monotonic_values))
    with trace.RunRecorder(store, run_id="run") as recorder:
        with recorder.step("wait"):
            pass
    assert store.execution_records.get_run("run")["duration_ns"] == 100
    step = store.execution_records.list_steps("run")[0]
    assert step["duration_ns"] == 40
    assert step["ended_at"] < step["started_at"]


def test_cancellation_before_next_root_and_nested_boundary(store):
    event = threading.Event()
    executed = []
    with pytest.raises(trace.ProtocolCancelled):
        with trace.RunRecorder(store, run_id="run", cancel_event=event) as recorder:
            with recorder.step("first"):
                executed.append("first")
                event.set()
            with recorder.step("second"):
                executed.append("second")
    assert executed == ["first"]
    assert store.execution_records.get_run("run")["status"] == "cancelled"
    assert len(store.execution_records.list_steps("run")) == 1
    with pytest.raises(KeyboardInterrupt):
        with trace.RunRecorder(store, run_id="interrupt") as recorder:
            with recorder.step("read"):
                raise KeyboardInterrupt()
    assert store.execution_records.list_steps("interrupt")[0]["status"] == "cancelled"


@pytest.mark.parametrize("failure_at", ["start", "finish", "resolved"])
def test_nested_recording_failure_latches_and_stops_next_root(
    store, monkeypatch, failure_at
):
    executed = []
    with pytest.raises(trace.RecordingError):
        with trace.RunRecorder(store, run_id="run") as recorder:
            method = {
                "start": "start_step",
                "finish": "finish_step",
                "resolved": "update_step_parameters",
            }[failure_at]
            original = getattr(recorder.records, method)

            def fail(*args, **kwargs):
                if (method == "start_step" and kwargs["command"] == "child") or (
                    method != "start_step" and len(recorder.stack) > 1
                ):
                    raise OSError("disk unavailable")
                return original(*args, **kwargs)

            monkeypatch.setattr(recorder.records, method, fail)
            with pytest.raises(trace.RecordingError):
                with recorder.step("repeat"):
                    with recorder.step("child"):
                        executed.append("child")
                        recorder.resolved(well="A1")
            with recorder.step("next"):
                executed.append("next")
    assert executed == ["child"]
    run = store.execution_records.get_run("run")
    assert run["status"] == "failed"
    assert run["details"] == {"kind": "recording_failure"}
    assert run["recording_errors"][0]["stage"] == "recording"


def test_root_start_and_run_finish_recording_failures(store, monkeypatch):
    with pytest.raises(trace.RecordingError):
        with trace.RunRecorder(store, run_id="start") as recorder:
            monkeypatch.setattr(
                recorder.records,
                "start_step",
                lambda *a, **kw: (_ for _ in ()).throw(OSError()),
            )
            with recorder.step("never"):
                pytest.fail("unrecorded root action executed")
    with pytest.raises(trace.RecordingError):
        with trace.RunRecorder(store, run_id="finish") as recorder:
            monkeypatch.setattr(
                recorder.records,
                "finish_run",
                lambda *a, **kw: (_ for _ in ()).throw(OSError()),
            )
    assert trace.current_trace() is None
    assert store.execution_records.get_run("finish")["status"] == "running"


def test_live_owner_and_process_death_recovery(tmp_path):
    database = tmp_path / "runs.db"
    script = """
import sys
from cubos.data.data_store import DataStore
from cubos.protocol_engine.execution_trace import RunRecorder
store = DataStore(sys.argv[1])
with RunRecorder(store, run_id='child') as recorder:
    with recorder.step('pending'):
        print('ready', flush=True)
        sys.stdin.read()
"""
    process = subprocess.Popen(
        [sys.executable, "-u", "-c", script, str(database)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout.readline().strip() == "ready"
        with DataStore(database) as store:
            assert trace.recover_abandoned_runs(store) == []
            process.kill()
            process.wait(timeout=10)
            assert trace.recover_abandoned_runs(store) == ["child"]
            assert trace.recover_abandoned_runs(store) == []
            run = store.execution_records.get_run("child")
            step = store.execution_records.list_steps("child")[0]
            assert run["status"] == step["status"] == "interrupted"
            assert run["duration_ns"] is step["duration_ns"] is None
            assert run["ended_at"] is step["ended_at"] is None
            assert run["recovered_at"] == step["recovered_at"]
            assert run["details"] == {"kind": "owner_lost"}
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        for pipe in (process.stdin, process.stdout, process.stderr):
            pipe.close()


def test_local_lock_reentrance_foreign_owner_and_memory_recovery(store, tmp_path):
    assert trace.recover_abandoned_runs(store) == []
    database = tmp_path / "runs.db"
    first, second = trace.RunLock(database, "same"), trace.RunLock(database, "same")
    assert first.acquire()
    assert not second.acquire()
    first.release()
    assert second.acquire()
    second.release()
    with DataStore(database) as disk:
        disk.execution_records.create_run(
            "foreign", metadata={"owner": {"host": "other-host"}}
        )
        disk.execution_records.create_run(
            "other-db",
            metadata={
                "owner": {"host": socket.gethostname(), "database": "/elsewhere"}
            },
        )
        assert trace.recover_abandoned_runs(disk) == []
        with trace.RunRecorder(disk, run_id="owner"):
            with pytest.raises(trace.RecordingError, match="ownership"):
                with trace.RunRecorder(disk, run_id="owner"):
                    pass


def test_thousand_step_recording_benchmark(tmp_path):
    database = tmp_path / "benchmark.db"
    with DataStore(database) as store:
        before = database.stat().st_size
        started = time.perf_counter()
        with trace.RunRecorder(store, run_id="benchmark") as recorder:
            for index in range(1000):
                with recorder.step(
                    "wait", {"seconds": 0}, source={"pointer": f"/protocol/{index}"}
                ):
                    pass
        elapsed = time.perf_counter() - started
        growth = database.stat().st_size - before
        rows = store.execution_records.list_steps("benchmark", limit=1001)
        assert len(rows) == 1000
        assert rows[-1]["sequence"] == 1999
        assert store.execution_records.get_run("benchmark")["terminal_sequence"] == 2001
        print(f"1000 persisted steps: {elapsed:.3f}s; database growth {growth} bytes")


def fake_protocol(source=None):
    return SimpleNamespace(
        steps=[SimpleNamespace(index=0, command_name="wait", args={"seconds": 0})],
        source_path=source,
    )


def fake_context(store=None):
    return SimpleNamespace(
        gantry=SimpleNamespace(
            controller=SimpleNamespace(_offline=True),
            instruments={"sensor": SimpleNamespace(_offline=True)},
        ),
        gantry_config={"model": "offline"},
        positions={},
        fluid_state_id=None,
        campaign_id=None,
        data_store=store,
        deck=SimpleNamespace(),
        execution_trace=None,
        connections_observed=True,
    )


def test_attach_and_metadata_identity(store):
    context = fake_context(store)
    protocol = fake_protocol()
    trace.ensure_campaign(context)
    with trace.RunRecorder(store, run_id="run") as recorder:
        recorder.attach(context, protocol)
        assert recorder.protocol is protocol
    run = store.execution_records.get_run("run")
    assert run["campaign_id"] == context.campaign_id
    metadata = run["metadata"]
    assert metadata["execution_mode"] == "simulated"
    assert metadata["protocol"]["hash_kind"] == "sanitized_plan_v1"
    assert metadata["protocol"]["content_sha256"] == metadata["protocol"]["plan_sha256"]
    protocol.source_bytes = b"protocol: []"
    protocol.source_sha256 = "source-digest"
    protocol.source_snapshot = {"protocol": []}
    source = trace.protocol_metadata(protocol)
    assert source["hash_kind"] == "source_bytes"
    assert source["content_sha256"] == "source-digest"
    assert source["snapshot"] == {"protocol": []}
    context.gantry.instruments["sensor"]._offline = False
    assert trace.context_metadata(context)["execution_mode"] == "mixed"
    context.gantry.controller._offline = False
    assert trace.context_metadata(context)["execution_mode"] == "hardware"
    context.gantry.instruments = object()
    context.gantry.controller = object()
    assert trace.context_metadata(context)["execution_mode"] == "unknown"


def test_bound_arguments_defaults_and_uninspectable_fallback():
    def handler(context, *, seconds=1):
        pass

    assert trace.bound_args(handler, object(), {}) == {"seconds": 1}
    assert trace.bound_args(handler, object(), {"unknown": 1}) == {"unknown": 1}


def test_protocol_recording_reuses_active_owner_and_restores_context(store):
    context = fake_context()
    previous = object()
    context.execution_trace = previous
    with trace.RunRecorder(store, run_id="active") as owner:
        with trace.protocol_recording(fake_protocol(), context) as recorder:
            assert recorder is owner
            assert context.data_store is store
            assert context.execution_trace is owner
        assert context.execution_trace is previous
    assert len(store.execution_records.list_runs()) == 1
    assert (
        store.execution_records.get_run("active")["campaign_id"] is not None
    )
    context = fake_context(store)
    with trace.protocol_recording(fake_protocol(), context) as recorder:
        assert trace.current_trace() is recorder
        with recorder.step("wait"):
            pass
    assert context.execution_trace is None
    assert store.execution_records.get_run(context.run_id)["status"] == "completed"
    context = fake_context(object())
    with trace.protocol_recording(fake_protocol(), context) as recorder:
        assert recorder is None


def test_protocol_recording_owns_default_store_and_clears_context(
    tmp_path, monkeypatch
):
    database = tmp_path / "default.db"
    monkeypatch.setenv("CUBOS_DATA_DB_PATH", str(database))
    context = fake_context()
    with trace.protocol_recording(fake_protocol(), context):
        assert isinstance(context.data_store, DataStore)
        assert context.campaign_id is not None
    assert context.data_store is None
    assert context.campaign_id is None
    with DataStore(database) as persisted:
        assert (
            persisted.execution_records.get_run(context.run_id)["status"] == "completed"
        )


def test_recorded_run_freezes_setup_and_persists_preflight_failure(store, tmp_path):
    protocol_path = tmp_path / "protocol.yaml"
    protocol_path.write_text("protocol: []\n")

    @trace.recorded_run("test_setup")
    def execute(*, data_store=None, protocol_path=None, mock_mode=None):
        assert trace.current_trace() is not None
        return 42

    assert execute(data_store=store, protocol_path=protocol_path, mock_mode=True) == 42
    run = store.execution_records.list_runs()[0]
    assert run["metadata"]["lifecycle_scope"] == "test_setup"
    assert run["metadata"]["requested_setup"][str(protocol_path.resolve())] == {
        "protocol": []
    }
    assert run["metadata"]["requested_mock_mode"] is True
    with trace.RunRecorder(store, run_id="outer"):
        assert execute(data_store=store) == 42
    assert len(store.execution_records.list_runs()) == 2
    protocol_path.write_text("protocol: [\n")
    with pytest.raises(Exception):
        execute(data_store=store, protocol_path=protocol_path)
    assert (
        sum(r["status"] == "failed" for r in store.execution_records.list_runs()) == 1
    )

    @trace.recorded_run("compatibility")
    def compatibility(*, data_store):
        return trace.current_trace()

    assert compatibility(data_store=object()) is None


def test_recorded_run_owns_database_and_releases_on_failure(tmp_path):
    database = tmp_path / "owned.db"

    @trace.recorded_run("owned")
    def execute(*, db_path):
        raise RuntimeError("preflight failure")

    with pytest.raises(RuntimeError):
        execute(db_path=database)
    with DataStore(database) as store:
        assert store.execution_records.list_runs()[0]["status"] == "failed"
    assert trace.current_trace() is None


def test_enter_failure_releases_disk_lock(tmp_path):
    with DataStore(tmp_path / "runs.db") as store:
        with trace.RunRecorder(store, run_id="duplicate"):
            pass
        with pytest.raises(Exception):
            with trace.RunRecorder(store, run_id="duplicate"):
                pass
        lock = trace.RunLock(store.db_path, "duplicate")
        assert lock.acquire()
        lock.release()


def test_nested_database_rejected_before_context_mutation(store):
    with DataStore(":memory:") as other:
        context = fake_context(other)
        with trace.RunRecorder(store):
            with pytest.raises(trace.RecordingError, match="same experiment database"):
                with trace.protocol_recording(fake_protocol(), context):
                    pytest.fail("wrong database executed")
            assert context.execution_trace is None
            assert context.campaign_id is None
            assert context.data_store is other


def test_nested_attachment_failure_restores_context(store, monkeypatch):
    context = fake_context(store)
    with trace.RunRecorder(store) as recorder:
        monkeypatch.setattr(recorder, "attach", lambda *args: (_ for _ in ()).throw(ValueError("attach")))
        with pytest.raises(ValueError):
            with trace.protocol_recording(fake_protocol(), context):
                pass
        assert context.execution_trace is None
        assert recorder.protocol is None


def test_nested_session_does_not_erase_requested_mode(store):
    @trace.recorded_run("connected_session")
    def session(*, data_store):
        return None
    with trace.RunRecorder(store, metadata={"requested_mock_mode": False}) as recorder:
        session(data_store=store)
    assert store.execution_records.get_run(recorder.run_id)["metadata"]["requested_mock_mode"] is False


def test_cleanup_failure_does_not_rewrite_completed_steps(store):
    with pytest.raises(trace.ProtocolCleanupError):
        with trace.RunRecorder(store) as recorder:
            with recorder.step("measure"):
                pass
            recorder.cleanup_error(RuntimeError("password=secret"))
    run = store.execution_records.get_run(recorder.run_id)
    assert run["status"] == "failed"
    assert run["details"]["kind"] == "cleanup_failure"
    assert store.execution_records.list_steps(recorder.run_id)[0]["status"] == "completed"
    assert "secret" not in json.dumps(run)


def test_requested_hardware_is_not_proof_of_connection():
    context = fake_context()
    context.gantry.controller._offline = False
    context.gantry.instruments['sensor']._offline = False
    context.connections_observed = False
    metadata = trace.context_metadata(context)
    assert metadata['execution_mode'] == 'unknown'
    assert metadata['connection_observation'] == 'unknown'


def test_latched_failure_does_not_repeat_blocked_child_start_writes(store, monkeypatch):
    with pytest.raises(trace.RecordingError):
        with trace.RunRecorder(store) as recorder:
            with recorder.step("compound"):
                calls = []
                def fail(*args, **kwargs):
                    calls.append(1)
                    raise OSError("storage unavailable")
                monkeypatch.setattr(recorder.records, "start_step", fail)
                for index in range(3):
                    with recorder.step("child", iteration_index=index):
                        recorder.resolved(value=index)
                assert len(calls) == 1
