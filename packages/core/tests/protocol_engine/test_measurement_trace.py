from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from cubos.instruments.uvvis_ccs.models import UVVisSpectrum
from cubos.instruments.uvvis_ccs.vendors.thorlabs import _synthetic_spectrum
from cubos.protocol_engine.measurements import normalize_measurement
from cubos.protocol_engine.measurement_trace import (
    active_step, invoke, persistence_kwargs, record_resolved, well_scope,
)


class TraceContext:
    active_step_execution_id = "step-1"

    def __init__(self):
        self.resolved = {}
        self.errors = []
        self.scopes = []

    def record_resolved(self, **values):
        self.resolved.update(values)

    def recording_error(self, exc):
        self.errors.append(exc)

    @contextmanager
    def trace_scope(self, command, parameters, *, iteration_index):
        self.scopes.append((command, parameters, iteration_index))
        yield


def test_call_observation_preserves_result_and_separates_integration_time():
    context = TraceContext()
    instr = SimpleNamespace(_offline=True, _serial_number="configured-1")
    result = UVVisSpectrum((500.,), (0.5,), 99., {"acquisition_started_at": "reported"})
    observed, metadata = invoke(context, instr, lambda **kw: result,
                                {"gantry": object(), "gain": 2},
                                position="plate.A1", action_xyz=(1, 2, 3))
    assert observed is result
    assert metadata["method_kwargs"] == {"gain": 2}
    assert metadata["method_call"]["duration_ns"] >= 0
    assert "acquisition_started_at" not in metadata["method_call"]
    measurement = normalize_measurement("uv", "measure", result)
    assert measurement.metadata["integration_time_s"] == 99.
    assert measurement.metadata["acquisition_started_at"] == "reported"
    target = SimpleNamespace(labware_key="plate", labware_name="test", location_id="A1")
    extra = persistence_kwargs(context, metadata, measurement, target, [{"source": "dye"}])
    assert extra["step_execution_id"] == "step-1"
    assert extra["metadata"]["sample"]["contents"] == [{"source": "dye"}]
    assert extra["metadata"]["instrument"]["reported"] is None


def test_failed_method_preserves_error_and_records_resolution():
    context = TraceContext()
    def fail():
        raise RuntimeError("instrument failed")
    with pytest.raises(RuntimeError, match="instrument failed"):
        invoke(context, SimpleNamespace(), fail, {}, position="p.A1", action_xyz=(0, 0, 0))
    assert context.resolved["action_xyz"] == [0, 0, 0]
    assert "method_call" not in context.resolved


def test_legacy_context_and_scan_scope():
    context = SimpleNamespace()
    assert active_step(context) is None
    assert invoke(context, object(), lambda: 5, {}, position="p", action_xyz=(0, 0, 0)) == (5, {})
    assert persistence_kwargs(context, {}, None, None, None) == {}
    with well_scope(context, {}, 0):
        pass
    traced = TraceContext()
    with well_scope(traced, {"position": "p.A1"}, 3):
        pass
    assert traced.scopes == [("scan.well", {"position": "p.A1"}, 3)]


def test_result_metadata_and_synthetic_source_are_preserved():
    result = _synthetic_spectrum()
    measurement = normalize_measurement("uv", "measure", result)
    assert measurement.metadata["synthetic"] is True
    assert measurement.metadata["correction_state"] == "unknown"
    assert "acquisition_started_at" not in measurement.metadata
    assert UVVisSpectrum((500.,), (1.,), .1).metadata == {}


def test_resolved_recording_failure_latches():
    context = TraceContext()
    def fail(**values):
        raise RuntimeError("disk failed")
    context.record_resolved = fail
    record_resolved(context, action_xyz=[1, 2, 3])
    assert str(context.errors[0]) == "disk failed"


def test_measure_attaches_active_step_and_latches_persistence_failure():
    import logging
    from unittest.mock import MagicMock
    from cubos.protocol_engine.commands.measure import measure

    context = TraceContext()
    context.fluid_state_id = None
    context.campaign_id = 1
    context.logger = logging.getLogger("measurement_trace_test")
    result = UVVisSpectrum((500.,), (1.,), .1)
    sensor = SimpleNamespace(measure=lambda: result)
    context.gantry = MagicMock(instruments={"uv": sensor})
    target = SimpleNamespace(labware_key="plate", labware_name="test", location_id="A1")
    context.deck = SimpleNamespace(
        resolve_coordinate=lambda value: (1, 2, 3),
        resolve_labware_target=lambda value: target,
    )
    context.data_store = MagicMock()
    context.data_store.get_contents.return_value = []
    assert measure(context, "uv", "plate.A1", 2) is result
    call = context.data_store.log_experiment_measurement.call_args.kwargs
    assert call["step_execution_id"] == "step-1"
    assert call["metadata"]["action_xyz"] == [1, 2, 5]
    context.data_store.log_experiment_measurement.side_effect = OSError("write failed")
    assert measure(context, "uv", "plate.A1", 2) is result
    assert str(context.errors[-1]) == "write failed"


def test_scan_keeps_entered_wells_after_persistence_failure():
    import logging
    from unittest.mock import MagicMock
    from cubos.deck.deck import Deck
    from cubos.deck.labware.labware import Coordinate3D
    from cubos.deck.labware.well_plate import WellPlate
    from cubos.protocol_engine.commands.scan import scan

    context = TraceContext()
    context.fluid_state_id = None
    context.campaign_id = 1
    context.logger = logging.getLogger("measurement_trace_test")
    result = UVVisSpectrum((500.,), (1.,), .1)
    sensor = SimpleNamespace(measure=MagicMock(return_value=result))
    context.gantry = MagicMock(instruments={"uv": sensor})
    plate = WellPlate(name="plate", model_name="test", length=30, width=20,
                      height=10, rows=1, columns=2,
                      wells={"A1": Coordinate3D(x=1, y=2, z=3), "A2": Coordinate3D(x=2, y=2, z=3)},
                      capacity_ul=100, working_volume_ul=90)
    context.deck = Deck({"plate": plate})
    context.data_store = MagicMock()
    context.data_store.get_contents.return_value = []
    context.data_store.log_experiment_measurement.side_effect = [OSError("write failed"), None]
    results = scan(context, "plate", "uv", "measure", 2, 3)
    assert list(results) == ["A1", "A2"]
    assert sensor.measure.call_count == 2
    assert context.data_store.log_experiment_measurement.call_count == 2
    assert len(context.errors) == 1
    assert [scope[2] for scope in context.scopes] == [0, 1]


def test_slotted_instrument_and_metadata_callback_failure_preserve_call(monkeypatch):
    import cubos.data.record_metadata as metadata

    class Sensor:
        __slots__ = ()

    def fail(value):
        raise RuntimeError("metadata failed")

    monkeypatch.setattr(metadata, "sanitize", fail)
    context = TraceContext()
    result, observed = invoke(context, Sensor(), lambda **kw: 7, {},
                              position="plate.A1", action_xyz=(1, 2, 3))
    assert result == 7
    assert observed["method_kwargs"] == {"unavailable": True}
    assert str(context.errors[0]) == "metadata failed"


def test_real_scan_measurements_link_to_each_child_step(tmp_path):
    from unittest.mock import MagicMock
    from cubos.data import DataStore, register_deck_labware
    from cubos.deck.deck import Deck
    from cubos.deck.labware.labware import Coordinate3D
    from cubos.deck.labware.well_plate import WellPlate
    from cubos.protocol_engine.commands.scan import scan
    from cubos.protocol_engine.execution_trace import RunRecorder
    from cubos.protocol_engine.runtime import ProtocolContext

    plate = WellPlate(name="plate", model_name="test", length=30, width=20,
                      height=10, rows=1, columns=2,
                      wells={"A1": Coordinate3D(x=1, y=2, z=3),
                             "A2": Coordinate3D(x=2, y=2, z=3)},
                      capacity_ul=100, working_volume_ul=90)
    deck = Deck({"plate": plate})
    sensor = SimpleNamespace(measure=lambda: UVVisSpectrum((500.,), (1.,), .1))
    store = DataStore(tmp_path / "trace.db")
    try:
        campaign = store.create_campaign(description="trace")
        register_deck_labware(store, campaign, deck)
        context = ProtocolContext(gantry=MagicMock(instruments={"uv": sensor}),
                                  deck=deck, data_store=store, campaign_id=campaign)
        with RunRecorder(store) as recorder:
            context.execution_trace = recorder
            store.execution_records.update_run(recorder.run_id, campaign_id=campaign)
            with context.trace_scope("scan", {"plate": "plate"}):
                scan(context, "plate", "uv", "measure", 2, 3)
        steps = store.execution_records.list_steps(recorder.run_id)
        children = [step for step in steps if step["command"] == "scan.well"]
        assert [step["iteration_index"] for step in children] == [0, 1]
        assert [step["parent_step_execution_id"] for step in children] == [steps[0]["step_execution_id"]] * 2
        rows = store._conn.execute(
            "SELECT e.well_id,m.step_execution_id FROM experiments e "
            "JOIN uvvis_measurements m ON m.experiment_id=e.id ORDER BY e.id").fetchall()
        assert [(row[0], row[1]) for row in rows] == [
            (well, step["step_execution_id"]) for well, step in zip(("A1", "A2"), children)]
    finally:
        store.close()


def test_partial_aborted_measurement_retains_result_evidence():
    partial = SimpleNamespace(technique="ocp", time_s=[0., 1.], voltage_v=[.1, .2],
                              vendor="reported-vendor", duration_s=10.,
                              metadata={"aborted": True, "abort_reason": "operator",
                                        "acquisition_started_at": "2026-10-15T12:00:00Z"})
    measurement = normalize_measurement("configured", "measure_ocp", partial)
    assert measurement.payload == {"time_s": [0., 1.], "voltage_v": [.1, .2]}
    assert measurement.metadata["aborted"] is True
    assert measurement.metadata["abort_reason"] == "operator"
    assert measurement.metadata["schema_version"] == 1
    assert measurement.metadata["acquisition"] == {
        "started_at": "2026-10-15T12:00:00Z", "ended_at": None,
        "duration_ns": None, "source": "instrument_result"}
    assert measurement.metadata["processing"] == "unknown"
    unknown = normalize_measurement("uv", "measure", UVVisSpectrum((1.,), (2.,), 1.))
    assert unknown.metadata["acquisition"] == {
        "started_at": None, "ended_at": None, "duration_ns": None, "source": "unknown"}


def test_driver_orchestration_times_and_configured_model_are_not_acquisition_or_identity():
    raw = SimpleNamespace(technique="ocp", time_s=[0., 1.], voltage_v=[.1, .2],
                          vendor="emstat", duration_s=10., sample_period_s=.2,
                          metadata={"started_at": "2026-10-15T12:00:00Z",
                                    "stopped_at": "2026-10-15T12:00:01Z",
                                    "model": "configured-model"})
    measurement = normalize_measurement("pot", "run_OCP", raw)
    assert measurement.metadata["started_at"] == raw.metadata["started_at"]
    assert measurement.metadata["stopped_at"] == raw.metadata["stopped_at"]
    assert measurement.metadata["duration_s"] == 10.
    assert measurement.metadata["acquisition"]["source"] == "unknown"
    assert measurement.metadata["acquisition"]["duration_ns"] is None
    context = TraceContext()
    _, observed = invoke(context, SimpleNamespace(), lambda: raw, {},
                         position="plate.A1", action_xyz=(1, 2, 3))
    target = SimpleNamespace(labware_key="plate", labware_name="test", location_id="A1")
    envelope = persistence_kwargs(context, observed, measurement, target, [])["metadata"]
    assert envelope["instrument"]["reported"] is None
    assert envelope["result_metadata"]["model"] == "configured-model"
