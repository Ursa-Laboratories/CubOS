"""Tests for the persistent CubOS gantry session."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from gantry.session import (
    GantrySession,
    GantrySessionHealthCheckError,
    InterruptFeedHoldTimeoutError,
    MovementOutOfBoundsError,
)


GANTRY_YAML = """\
serial_port: /dev/test
gantry_type: cub_xl
cnc:
  factory_z_travel_mm: 90.0
working_volume:
  x_min: 0.0
  x_max: 300.0
  y_min: 0.0
  y_max: 200.0
  z_min: 0.0
  z_max: 80.0
grbl_settings:
  status_report: 0
  soft_limits: true
  hard_limits: false
  homing_enable: true
  homing_pull_off: 10.0
  max_travel_x: 310.0
  max_travel_y: 210.0
  max_travel_z: 90.0
instruments: {}
"""


class FakeGantry:
    instances: list["FakeGantry"] = []

    def __init__(self, config=None):
        self.config = config or {}
        self.connected = False
        self.coords = {"x": 10.0, "y": 20.0, "z": 30.0}
        self.status = "Idle"
        self.calls: list[tuple[str, object]] = []
        self.disconnect_calls = 0
        self.connect_should_fail = False
        self.grbl_settings = {
            "$10": "0",
            "$20": "1",
            "$21": "0",
            "$22": "1",
            "$27": "10",
            "$130": "310",
            "$131": "210",
            "$132": "90",
        }
        FakeGantry.instances.append(self)

    def connect(self, port=None):
        self.calls.append(("connect", port))
        if self.connect_should_fail:
            raise RuntimeError("connect failed")
        self.connected = True

    def disconnect(self):
        self.disconnect_calls += 1
        self.calls.append(("disconnect", None))
        self.connected = False

    def get_position_info(self):
        return {"coords": self.coords, "work_pos": self.coords, "status": self.status}

    def _extract_status(self):
        return self.status

    def read_grbl_settings(self):
        self.calls.append(("read_grbl_settings", None))
        return dict(self.grbl_settings)

    def is_healthy(self):
        self.calls.append(("is_healthy", None))
        return True

    def prepare_for_protocol_run(self):
        self.calls.append(("prepare_for_protocol_run", None))

    def connect_instruments(self):
        self.calls.append(("connect_instruments", None))

    def disconnect_instruments(self):
        self.calls.append(("disconnect_instruments", None))

    def home(self):
        self.calls.append(("home", None))

    def enforce_work_position_reporting(self):
        self.calls.append(("enforce_work_position_reporting", None))

    def activate_work_coordinate_system(self, system):
        self.calls.append(("activate_work_coordinate_system", system))

    def clear_g92_offsets(self):
        self.calls.append(("clear_g92_offsets", None))

    def soft_limits_enabled(self):
        self.calls.append(("soft_limits_enabled", None))
        return True

    def set_soft_limits_enabled(self, enabled):
        self.calls.append(("set_soft_limits_enabled", enabled))

    def set_grbl_setting(self, setting, value):
        self.calls.append(("set_grbl_setting", (setting, value)))

    def move_to(self, *args, **kwargs):
        self.calls.append(("move_to", args or kwargs))
        if args:
            x, y, z = args
        else:
            x, y, z = kwargs["x"], kwargs["y"], kwargs["z"]
        self.coords = {"x": float(x), "y": float(y), "z": float(z)}

    def jog(self, **kwargs):
        self.calls.append(("jog", kwargs))
        self.coords = {
            "x": self.coords["x"] + float(kwargs.get("x", 0.0)),
            "y": self.coords["y"] + float(kwargs.get("y", 0.0)),
            "z": self.coords["z"] + float(kwargs.get("z", 0.0)),
        }

    def get_status(self):
        self.calls.append(("get_status", None))
        return self.status

    def stop(self):
        self.calls.append(("stop", None))

    def jog_cancel(self):
        self.calls.append(("jog_cancel", None))


def _write_gantry(path: Path) -> Path:
    gantry_path = path / "gantry.yaml"
    gantry_path.write_text(GANTRY_YAML, encoding="utf-8")
    return gantry_path


@pytest.fixture(autouse=True)
def _clear_fake_gantry_instances():
    FakeGantry.instances.clear()
    yield
    FakeGantry.instances.clear()


def test_connect_stages_and_publishes_after_success(tmp_path):
    observations: list[tuple[str, bool]] = []
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _seconds: None)

    class ObservingGantry(FakeGantry):
        def connect(self, port=None):
            observations.append(("session_connected_during_connect", session.connected))
            observations.append(("lock_held", session.operation_lock.locked()))
            super().connect(port=port)

    session = GantrySession(gantry_factory=ObservingGantry, sleep=lambda _seconds: None)
    snapshot = session.connect(_write_gantry(tmp_path), filename="gantry.yaml")

    assert snapshot.connected is True
    assert observations == [
        ("session_connected_during_connect", False),
        ("lock_held", True),
    ]
    assert session.connected is True
    assert ObservingGantry.instances[-1].calls[0] == ("connect", "/dev/test")


def test_connect_failure_preserves_existing_session(tmp_path):
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _seconds: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    existing = FakeGantry.instances[-1]

    class FailingGantry(FakeGantry):
        def connect(self, port=None):
            raise RuntimeError("serial failure")

    session._gantry_factory = FailingGantry

    with pytest.raises(RuntimeError, match="serial failure"):
        session.connect(_write_gantry(tmp_path), filename="gantry.yaml")

    assert session.connected is True
    assert session._gantry is existing
    assert session.operation_lock.locked() is False


def test_position_returns_cached_status_while_operation_lock_is_held(tmp_path):
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _seconds: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    FakeGantry.instances[-1].status = "Run"
    session.operation_lock.acquire()
    try:
        snapshot = session.position()
    finally:
        session.operation_lock.release()

    assert snapshot.x == 10.0
    assert snapshot.status == "Run"


def test_move_and_jog_reject_invalid_targets(tmp_path):
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _seconds: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")

    with pytest.raises(MovementOutOfBoundsError, match="outside"):
        session.move_to_blocking(x=301.0, y=20.0, z=30.0)

    with pytest.raises(ValueError, match="finite"):
        session.jog(x=0.0, y=0.0, z=math.nan)


def test_calibration_prepare_disables_and_restore_reenables_soft_limits(tmp_path):
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _seconds: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]

    session.prepare_calibration_origin()
    session.restore_calibration_soft_limits()

    assert ("set_grbl_setting", ("$10", 0.0)) in fake.calls
    assert ("set_grbl_setting", ("$27", 10.0)) in fake.calls
    assert ("home", None) in fake.calls
    assert ("set_soft_limits_enabled", False) in fake.calls
    assert ("set_soft_limits_enabled", True) in fake.calls


def test_feed_hold_interrupt_does_not_wait_for_operation_lock(tmp_path):
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _seconds: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    session.operation_lock.acquire()
    try:
        session.feed_hold_interrupt()
    finally:
        session.operation_lock.release()

    assert ("stop", None) in fake.calls


def test_feed_hold_interrupt_reports_timeout(tmp_path):
    class TimeoutGantry(FakeGantry):
        def stop(self):
            raise RuntimeError("Error executing command !: Command execution timed out")

    session = GantrySession(gantry_factory=TimeoutGantry, sleep=lambda _seconds: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")

    with pytest.raises(InterruptFeedHoldTimeoutError):
        session.feed_hold_interrupt()


def test_run_protocol_uses_existing_gantry_and_preserves_connection(monkeypatch, tmp_path):
    import gantry.session as session_module

    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _seconds: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    events: list[str] = []

    class FakeStore:
        def __init__(self, db_path=None):
            self.db_path = db_path
            events.append(f"store:{db_path}")

        def close(self):
            events.append("store.close")

    class FakeInstrumented:
        def connect_instruments(self):
            events.append("instruments.connect")

        def disconnect_instruments(self):
            events.append("instruments.disconnect")

    class FakeProtocol:
        def execute(self, context):
            events.append("protocol.execute")
            assert context.gantry is instrumented
            return ["a", "b"]

    instrumented = FakeInstrumented()
    context = type("Context", (), {"gantry": instrumented})()

    def fake_create_campaign(data_store, **kwargs):
        events.append("campaign.create")
        assert data_store.db_path == tmp_path / "data.db"
        return 77

    def fake_setup_protocol(*args, **kwargs):
        events.append("setup_protocol")
        assert kwargs["gantry"] is fake
        assert kwargs["campaign_id"] == 77
        return FakeProtocol(), context

    monkeypatch.setattr(session_module, "DataStore", FakeStore)
    monkeypatch.setattr(session_module, "create_campaign_for_protocol_run", fake_create_campaign)
    monkeypatch.setattr(session_module, "setup_protocol", fake_setup_protocol)

    result = session.run_protocol(
        gantry_path=tmp_path / "gantry.yaml",
        deck_path=tmp_path / "deck.yaml",
        protocol_path=tmp_path / "protocol.yaml",
        gantry_file="gantry.yaml",
        deck_file="deck.yaml",
        protocol_file="protocol.yaml",
        db_path=tmp_path / "data.db",
    )

    assert result.campaign_id == 77
    assert result.steps_executed == 2
    assert ("prepare_for_protocol_run", None) in fake.calls
    assert fake.disconnect_calls == 0
    assert events == [
        f"store:{tmp_path / 'data.db'}",
        "campaign.create",
        "setup_protocol",
        "instruments.connect",
        "protocol.execute",
        "instruments.disconnect",
        "store.close",
    ]


def test_run_protocol_disconnects_instruments_on_failure(monkeypatch, tmp_path):
    import gantry.session as session_module

    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _seconds: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    events: list[str] = []

    class FakeStore:
        def __init__(self, db_path=None):
            pass

        def close(self):
            events.append("store.close")

    class FakeInstrumented:
        def connect_instruments(self):
            events.append("instruments.connect")

        def disconnect_instruments(self):
            events.append("instruments.disconnect")

    class FailingProtocol:
        def execute(self, context):
            raise RuntimeError("boom")

    context = type("Context", (), {"gantry": FakeInstrumented()})()
    monkeypatch.setattr(session_module, "DataStore", FakeStore)
    monkeypatch.setattr(
        session_module,
        "create_campaign_for_protocol_run",
        lambda *_args, **_kwargs: 88,
    )
    monkeypatch.setattr(
        session_module,
        "setup_protocol",
        lambda *_args, **_kwargs: (FailingProtocol(), context),
    )

    with pytest.raises(RuntimeError, match="boom"):
        session.run_protocol(
            gantry_path=tmp_path / "gantry.yaml",
            deck_path=tmp_path / "deck.yaml",
            protocol_path=tmp_path / "protocol.yaml",
            gantry_file="gantry.yaml",
            deck_file="deck.yaml",
            protocol_file="protocol.yaml",
            db_path=tmp_path / "data.db",
        )

    assert events == ["instruments.connect", "instruments.disconnect", "store.close"]


def test_run_protocol_health_failure_after_instruments_uses_session_error(
    monkeypatch,
    tmp_path,
):
    import gantry.session as session_module

    class HealthDropGantry(FakeGantry):
        def __init__(self, config=None):
            super().__init__(config=config)
            self.health_checks = 0

        def is_healthy(self):
            self.health_checks += 1
            return self.health_checks == 1

    session = GantrySession(gantry_factory=HealthDropGantry, sleep=lambda _seconds: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    events: list[str] = []

    class FakeStore:
        def __init__(self, db_path=None):
            pass

        def close(self):
            events.append("store.close")

    class FakeInstrumented:
        def connect_instruments(self):
            events.append("instruments.connect")

        def disconnect_instruments(self):
            events.append("instruments.disconnect")

    class UnreachedProtocol:
        def execute(self, context):
            raise AssertionError("protocol should not execute")

    context = type("Context", (), {"gantry": FakeInstrumented()})()
    monkeypatch.setattr(session_module, "DataStore", FakeStore)
    monkeypatch.setattr(
        session_module,
        "create_campaign_for_protocol_run",
        lambda *_args, **_kwargs: 88,
    )
    monkeypatch.setattr(
        session_module,
        "setup_protocol",
        lambda *_args, **_kwargs: (UnreachedProtocol(), context),
    )

    with pytest.raises(GantrySessionHealthCheckError, match="health check failed"):
        session.run_protocol(
            gantry_path=tmp_path / "gantry.yaml",
            deck_path=tmp_path / "deck.yaml",
            protocol_path=tmp_path / "protocol.yaml",
            gantry_file="gantry.yaml",
            deck_file="deck.yaml",
            protocol_file="protocol.yaml",
            db_path=tmp_path / "data.db",
        )

    assert events == ["instruments.connect", "instruments.disconnect", "store.close"]
