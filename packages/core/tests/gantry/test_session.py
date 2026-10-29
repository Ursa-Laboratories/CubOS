"""Tests for the persistent CubOS gantry session."""

from __future__ import annotations

import math
import threading
import time
from pathlib import Path

import pytest

from cubos.gantry.session import (
    CalibrationBlockedError,
    GantryAlarmError,
    GantryNotConnectedError,
    GantrySession,
    GantrySessionError,
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

    def unlock(self):
        self.calls.append(("unlock", None))

    def reset_and_unlock(self):
        self.calls.append(("reset_and_unlock", None))

    def reset_and_unlock_for_limit_recovery(self, *, axis, check_cancelled=None):
        self.reset_and_unlock()

    def resume(self):
        self.calls.append(("resume", None))

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

    def hard_limits_enabled(self):
        self.calls.append(("hard_limits_enabled", None))
        return float(self.grbl_settings.get("$21", "0")) != 0.0

    def set_hard_limits_enabled(self, enabled):
        self.calls.append(("set_hard_limits_enabled", enabled))
        self.grbl_settings["$21"] = "1" if enabled else "0"

    def configure_soft_limits_from_spans(self, **kwargs):
        self.calls.append(("configure_soft_limits_from_spans", kwargs))

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

    def get_recovery_status(self):
        return self.get_status()

    def get_recovery_position_info(self):
        return self.get_position_info()

    def get_status(self):
        self.calls.append(("get_status", None))
        return self.status

    def stop(self):
        self.calls.append(("stop", None))

    def feed_hold_realtime(self):
        self.calls.append(("feed_hold_realtime", None))

    def jog_for_limit_recovery(self, *, check_cancelled=None, **kwargs):
        if check_cancelled is not None:
            check_cancelled()
        return self.jog(**kwargs)

    def jog_cancel(self):
        self.calls.append(("jog_cancel", None))

    def set_work_coordinates(self, **kwargs):
        self.calls.append(("set_work_coordinates", kwargs))

    def finalize_deck_origin_calibration(self, **kwargs):
        self.calls.append(("finalize_deck_origin_calibration", kwargs))
        return {
            "measured_volume": {"x": 300.0, "y": 200.0, "z": 80.0},
            "z_calibration": {"block_height": 10.0},
            "max_travel": {"x": 310.0, "y": 210.0, "z": 90.0},
            "position": {"x": 300.0, "y": 200.0, "z": 80.0},
            "homing_pull_off_mm": 10.0,
            "origin_policy": kwargs.get("origin_policy", "deck_origin"),
            "working_volume": {"x_min": 0, "x_max": 300, "y_min": 0, "y_max": 200, "z_min": 0, "z_max": 80},
        }


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

    assert existing.disconnect_calls == 1
    assert session.connected is False
    assert session.operation_lock.locked() is False


def test_double_connect_disconnects_previous_gantry(tmp_path):
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _seconds: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    first = FakeGantry.instances[-1]

    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    second = FakeGantry.instances[-1]

    assert first.disconnect_calls == 1
    assert second is not first
    assert session._gantry is second


def test_disconnect_without_connection_returns_disconnected_snapshot():
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _seconds: None)

    snapshot = session.disconnect()

    assert snapshot.connected is False
    assert snapshot.status == "Disconnected"


def test_disconnect_reports_restore_and_disconnect_errors(tmp_path):
    class BadDisconnectGantry(FakeGantry):
        def soft_limits_enabled(self):
            return False

        def disconnect(self):
            super().disconnect()
            raise RuntimeError("close failed")

    session = GantrySession(gantry_factory=BadDisconnectGantry, sleep=lambda _seconds: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    session._calibration_restore_soft_limits = True

    with pytest.raises(GantrySessionError, match="Soft-limit restore and disconnect both failed"):
        session.disconnect()

    assert session.connected is False


def test_refresh_connected_config_only_for_matching_filename(tmp_path):
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _seconds: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]

    session.refresh_connected_config("other.yaml", {"serial_port": "/dev/ignored"})
    assert fake.config["serial_port"] == "/dev/test"

    session.refresh_connected_config(
        "gantry.yaml",
        {"serial_port": "/dev/new", "grbl_settings": {"status_report": 0}},
    )

    assert session._connected_gantry_config["serial_port"] == "/dev/new"
    assert fake.config == {"serial_port": "/dev/new"}


def test_connect_handshake_failure_disconnects_staged_gantry(tmp_path):
    class PositionFailingGantry(FakeGantry):
        def get_position_info(self):
            raise RuntimeError("position read failed")

    session = GantrySession(
        gantry_factory=PositionFailingGantry,
        sleep=lambda _seconds: None,
    )

    with pytest.raises(RuntimeError, match="position read failed"):
        session.connect(_write_gantry(tmp_path), filename="gantry.yaml")

    staged = PositionFailingGantry.instances[-1]
    assert staged.disconnect_calls == 1
    assert session.connected is False
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


def test_position_uses_alarm_status_when_read_raises_alarm(tmp_path):
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _seconds: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    FakeGantry.instances[-1].get_position_info = lambda: (_ for _ in ()).throw(
        RuntimeError("ALARM:1 hard limit")
    )

    snapshot = session.position()

    assert snapshot.status == "ALARM:1"


def test_simple_locked_wrappers_call_gantry_and_return_position(tmp_path):
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _seconds: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]

    assert session.home().connected
    assert session.unlock().connected
    assert session.reset_and_unlock().connected
    assert session.resume().connected
    assert session.feed_hold().connected
    assert session.jog_cancel().connected
    assert session.set_work_coordinates(x=1.0, y=None, z=2.0).connected

    assert ("home", None) in fake.calls
    assert ("unlock", None) in fake.calls
    assert ("reset_and_unlock", None) in fake.calls
    assert ("resume", None) in fake.calls
    assert ("stop", None) in fake.calls
    assert ("jog_cancel", None) in fake.calls
    assert ("set_work_coordinates", {"x": 1.0, "y": None, "z": 2.0}) in fake.calls


def test_grbl_setting_helpers_normalize_and_parse_values(tmp_path):
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _seconds: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]

    settings = session.set_grbl_setting("20", "0")

    assert ("set_grbl_setting", ("$20", 0.0)) in fake.calls
    assert settings["$20"] == "1"
    assert session.read_grbl_settings()["$10"] == "0"

    for bad_setting in ("abc", "$x", "20.5"):
        with pytest.raises(ValueError, match="numeric code"):
            session.set_grbl_setting(bad_setting, "1")
    for bad_value in ("", "1\n2", "abc"):
        with pytest.raises(ValueError):
            session.set_grbl_setting("$20", bad_value)


def test_move_and_jog_reject_invalid_targets(tmp_path):
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _seconds: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")

    with pytest.raises(MovementOutOfBoundsError, match="outside"):
        session.move_to_blocking(x=301.0, y=20.0, z=30.0)

    with pytest.raises(ValueError, match="finite"):
        session.jog(x=0.0, y=0.0, z=math.nan)


def test_movement_error_marks_reconnect_required_for_missing_working_volume(tmp_path):
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _seconds: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    session._connected_gantry_config.pop("working_volume")

    with pytest.raises(MovementOutOfBoundsError) as exc_info:
        session.move_to_blocking(x=10.0, y=20.0, z=30.0)

    assert exc_info.value.requires_reconnect is True


def test_movement_error_marks_reconnect_required_for_missing_current_position(tmp_path):
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _seconds: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    FakeGantry.instances[-1].get_position_info = lambda: {
        "coords": None,
        "work_pos": None,
        "status": "Idle",
    }

    with pytest.raises(MovementOutOfBoundsError) as exc_info:
        session.jog(x=1.0)

    assert exc_info.value.requires_reconnect is True


def test_movement_error_does_not_mark_reconnect_required_for_bounds_violation(tmp_path):
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _seconds: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")

    with pytest.raises(MovementOutOfBoundsError) as exc_info:
        session.jog(x=500.0)

    assert exc_info.value.requires_reconnect is False


def test_move_worker_publishes_and_resets_errors(tmp_path):
    class OneFailureGantry(FakeGantry):
        def __init__(self, config=None):
            super().__init__(config=config)
            self.fail_next = True

        def move_to(self, *args, **kwargs):
            if self.fail_next:
                self.fail_next = False
                raise RuntimeError("out of bounds")
            return super().move_to(*args, **kwargs)

    session = GantrySession(gantry_factory=OneFailureGantry, sleep=lambda _seconds: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")

    session._move_worker(1.0, 2.0, 3.0)
    assert session.position().move_error == "out of bounds"

    session._move_worker(4.0, 5.0, 6.0)
    snapshot = session.position()
    assert snapshot.move_error is None
    assert (snapshot.x, snapshot.y, snapshot.z) == (4.0, 5.0, 6.0)


def test_move_to_background_rejects_out_of_bounds_before_thread(tmp_path):
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _seconds: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")

    with pytest.raises(MovementOutOfBoundsError):
        session.move_to(x=-1.0, y=0.0, z=0.0)


def test_calibration_active_reflects_calibration_flags(tmp_path):
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _seconds: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    assert session.calibration_active is False

    session.prepare_calibration_origin()
    assert session.calibration_active is True

    session.restore_calibration_soft_limits()
    assert session.calibration_active is False


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


def test_calibration_prepare_enforces_hard_limits_and_restore_reverts(tmp_path):
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _seconds: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    assert fake.grbl_settings["$21"] == "0"

    session.prepare_calibration_origin()
    assert ("set_hard_limits_enabled", True) in fake.calls
    assert fake.grbl_settings["$21"] == "1"
    assert session.calibration_active

    session.restore_calibration_soft_limits()
    assert ("set_hard_limits_enabled", False) in fake.calls
    assert fake.grbl_settings["$21"] == "0"
    assert not session.calibration_active


def test_calibration_prepare_leaves_hard_limits_alone_when_already_on(tmp_path):
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _seconds: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    fake.grbl_settings["$21"] = "1"

    session.prepare_calibration_origin()
    session.restore_calibration_soft_limits()

    # $21 was already enabled: never written, and never reverted.
    assert not any(name == "set_hard_limits_enabled" for name, _ in fake.calls)
    assert fake.grbl_settings["$21"] == "1"


def test_configure_soft_limits_reverts_calibration_hard_limits(tmp_path):
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _seconds: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]

    session.prepare_calibration_origin()
    assert fake.grbl_settings["$21"] == "1"
    session.configure_soft_limits(
        max_travel_x=310.0,
        max_travel_y=210.0,
        max_travel_z=90.0,
    )

    # The fixture YAML sets hard_limits: false, so the manual span-programming
    # path also reverts the calibration-window enforcement.
    assert ("set_hard_limits_enabled", False) in fake.calls
    assert fake.grbl_settings["$21"] == "0"


def test_hard_limit_restore_failure_warns_and_clears_flag(tmp_path):
    class FailingHardRestoreGantry(FakeGantry):
        def set_hard_limits_enabled(self, enabled):
            super().set_hard_limits_enabled(enabled)
            if not enabled:
                raise RuntimeError("serial died mid-restore")

    session = GantrySession(
        gantry_factory=FailingHardRestoreGantry, sleep=lambda _seconds: None
    )
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")

    session.prepare_calibration_origin()
    # A failed $21 revert must not raise — the machine is left in the safer
    # state — and must not leave the flag set (no retry loop).
    session.restore_calibration_soft_limits()
    assert session._calibration_restore_hard_limits is False
    assert not session.calibration_active


def test_finalize_reverts_calibration_hard_limits_unless_configured(tmp_path):
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _seconds: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]

    session.prepare_calibration_origin()
    assert fake.grbl_settings["$21"] == "1"
    session.finalize_calibration_origin(
        home_z=80.0,
        block_touch_z=10.0,
        block_height=5.0,
        factory_z_travel=90.0,
    )

    # The fixture YAML sets hard_limits: false, so the calibration-window
    # enforcement is reverted once calibrated soft limits are in place.
    assert ("set_hard_limits_enabled", False) in fake.calls
    assert fake.grbl_settings["$21"] == "0"
    assert session.calibration_active
    session.refresh_connected_config("gantry.yaml", session.connected_gantry_config)
    assert not session.calibration_active


def test_finalize_keeps_hard_limits_when_yaml_configures_them(tmp_path):
    gantry_path = tmp_path / "gantry.yaml"
    gantry_path.write_text(
        GANTRY_YAML.replace("hard_limits: false", "hard_limits: true"),
        encoding="utf-8",
    )
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _seconds: None)
    session.connect(gantry_path, filename="gantry.yaml")
    fake = FakeGantry.instances[-1]

    session.prepare_calibration_origin()
    session.finalize_calibration_origin(
        home_z=80.0,
        block_touch_z=10.0,
        block_height=5.0,
        factory_z_travel=90.0,
    )

    assert ("set_hard_limits_enabled", True) in fake.calls
    assert ("set_hard_limits_enabled", False) not in fake.calls
    assert fake.grbl_settings["$21"] == "1"
    assert session.calibration_active
    session.refresh_connected_config("gantry.yaml", session.connected_gantry_config)
    assert not session.calibration_active


def test_feed_hold_interrupt_does_not_wait_for_operation_lock(tmp_path):
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _seconds: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    session.operation_lock.acquire()
    try:
        session.feed_hold_interrupt()
    finally:
        session.operation_lock.release()

    assert ("feed_hold_realtime", None) in fake.calls
    assert ("stop", None) not in fake.calls


def test_feed_hold_interrupt_reports_timeout(tmp_path):
    class TimeoutGantry(FakeGantry):
        def feed_hold_realtime(self):
            raise RuntimeError("Error executing command !: Command execution timed out")

    session = GantrySession(gantry_factory=TimeoutGantry, sleep=lambda _seconds: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")

    with pytest.raises(InterruptFeedHoldTimeoutError):
        session.feed_hold_interrupt()


def test_interrupt_helpers_require_connection():
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _seconds: None)

    with pytest.raises(GantryNotConnectedError):
        session.feed_hold_interrupt()
    with pytest.raises(GantryNotConnectedError):
        session.jog_cancel_interrupt()


def test_jog_queued_behind_cancel_is_dropped(tmp_path):
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _seconds: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]

    jog_done = threading.Event()

    def queued_jog():
        session.jog(x=1.0)
        jog_done.set()

    # Hold the operation lock so the jog request blocks after snapshotting
    # its cancel generation — the same interleaving as a jog request queued
    # behind a held-jog burst on the API server when the cancel arrives.
    session._lock.acquire()
    try:
        worker = threading.Thread(target=queued_jog, daemon=True)
        worker.start()
        time.sleep(0.1)
        session.jog_cancel_interrupt()
    finally:
        session._lock.release()
    assert jog_done.wait(timeout=2.0)

    assert ("jog_cancel", None) in fake.calls
    assert not any(name == "jog" for name, _ in fake.calls)

    # A fresh jog issued after the cancel proceeds normally.
    session.jog(x=1.0)
    assert any(name == "jog" for name, _ in fake.calls)


def test_locked_jog_cancel_also_drops_queued_jogs(tmp_path):
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _seconds: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]

    generation = session._jog_cancel_generation
    session.jog_cancel()
    assert session._jog_cancel_generation == generation + 1
    assert ("jog_cancel", None) in fake.calls


def test_jog_zero_delta_is_noop_and_alarm_is_wrapped(tmp_path):
    class AlarmJogGantry(FakeGantry):
        def jog(self, **kwargs):
            raise RuntimeError("ALARM:1")

    session = GantrySession(gantry_factory=AlarmJogGantry, sleep=lambda _seconds: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")

    session.jog()
    with pytest.raises(GantryAlarmError):
        session.jog(x=1.0)


def test_jog_blocking_idle_alarm_and_timeout_paths(tmp_path):
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _seconds: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]

    assert session.jog_blocking(x=1.0, timeout_s=0.1).connected

    fake.status = "<Alarm|WPos:0,0,0>"
    with pytest.raises(GantryAlarmError):
        session.jog_blocking(x=1.0, timeout_s=0.1)

    fake.status = "<Run|WPos:0,0,0>"
    with pytest.raises(GantrySessionError, match="Timed out"):
        session._wait_until_idle_locked(timeout_s=0.0)


def test_finalize_calibration_failure_restores_soft_limits_and_keeps_flag_if_unverified(tmp_path):
    class FailingFinalizeGantry(FakeGantry):
        def __init__(self, config=None):
            super().__init__(config=config)
            self.soft_limits_verified = False
            self.soft_limit_reads = 0

        def finalize_deck_origin_calibration(self, **kwargs):
            self.calls.append(("finalize_deck_origin_calibration", kwargs))
            raise RuntimeError("calibration failed")

        def soft_limits_enabled(self):
            self.calls.append(("soft_limits_enabled", None))
            self.soft_limit_reads += 1
            if self.soft_limit_reads == 1:
                return True
            return self.soft_limits_verified

    session = GantrySession(gantry_factory=FailingFinalizeGantry, sleep=lambda _seconds: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FailingFinalizeGantry.instances[-1]
    session.prepare_calibration_origin()

    with pytest.raises(RuntimeError, match="calibration failed"):
        session.finalize_calibration_origin(
            home_z=80.0,
            block_touch_z=10.0,
            block_height=5.0,
            factory_z_travel=90.0,
        )

    assert ("set_soft_limits_enabled", True) in fake.calls
    assert ("set_soft_limits_enabled", False) in fake.calls
    assert session._calibration_restore_soft_limits is True


def test_run_protocol_uses_existing_gantry_and_preserves_connection(monkeypatch, tmp_path):
    import cubos.gantry.session as session_module

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
            events.append("cubos.instruments.connect")

        def disconnect_instruments(self):
            events.append("cubos.instruments.disconnect")

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
        "cubos.instruments.connect",
        "protocol.execute",
        "cubos.instruments.disconnect",
        "store.close",
    ]


def test_run_protocol_links_fluid_state_to_campaign_and_context(monkeypatch, tmp_path):
    """The fluid state must reach BOTH the campaign record (tip/cap state
    journals resolve it through the campaign) and setup_protocol (context
    tracking) — missing either silently breaks durable tracking."""
    import cubos.gantry.session as session_module

    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _seconds: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")

    seen = {}

    class FakeStore:
        def __init__(self, db_path=None):
            self.db_path = db_path

        def close(self):
            pass

    class FakeInstrumented:
        def connect_instruments(self):
            pass

        def disconnect_instruments(self):
            pass

    class FakeProtocol:
        def execute(self, context):
            return []

    context = type("Context", (), {"gantry": FakeInstrumented()})()

    def fake_create_campaign(data_store, **kwargs):
        seen["campaign_fluid_state_id"] = kwargs.get("fluid_state_id")
        return 78

    def fake_setup_protocol(*args, **kwargs):
        seen["setup_fluid_state_id"] = kwargs.get("fluid_state_id")
        return FakeProtocol(), context

    monkeypatch.setattr(session_module, "DataStore", FakeStore)
    monkeypatch.setattr(session_module, "create_campaign_for_protocol_run", fake_create_campaign)
    monkeypatch.setattr(session_module, "setup_protocol", fake_setup_protocol)

    session.run_protocol(
        gantry_path=tmp_path / "gantry.yaml",
        deck_path=tmp_path / "deck.yaml",
        protocol_path=tmp_path / "protocol.yaml",
        gantry_file="gantry.yaml",
        deck_file="deck.yaml",
        protocol_file="protocol.yaml",
        db_path=tmp_path / "data.db",
        fluid_state_id=3,
    )

    assert seen["campaign_fluid_state_id"] == 3
    assert seen["setup_fluid_state_id"] == 3


def test_run_protocol_does_not_block_on_calibration_warning(tmp_path):
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _seconds: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    session._calibration_warning = "settings differ"

    # A GRBL-settings mismatch is advisory, not blocking: run_protocol must get
    # past the calibration gate. It still fails here on the missing deck/protocol
    # fixtures, but never with CalibrationBlockedError.
    with pytest.raises(Exception) as excinfo:
        session.run_protocol(
            gantry_path=tmp_path / "gantry.yaml",
            deck_path=tmp_path / "deck.yaml",
            protocol_path=tmp_path / "protocol.yaml",
            gantry_file="gantry.yaml",
            deck_file="deck.yaml",
            protocol_file="protocol.yaml",
        )
    assert not isinstance(excinfo.value, CalibrationBlockedError)


def test_run_protocol_blocks_initial_unhealthy_gantry(tmp_path):
    class UnhealthyGantry(FakeGantry):
        def is_healthy(self):
            return False

    session = GantrySession(gantry_factory=UnhealthyGantry, sleep=lambda _seconds: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")

    with pytest.raises(GantrySessionHealthCheckError, match="not connected"):
        session.run_protocol(
            gantry_path=tmp_path / "gantry.yaml",
            deck_path=tmp_path / "deck.yaml",
            protocol_path=tmp_path / "protocol.yaml",
            gantry_file="gantry.yaml",
            deck_file="deck.yaml",
            protocol_file="protocol.yaml",
        )


def test_run_protocol_disconnects_instruments_on_failure(monkeypatch, tmp_path):
    import cubos.gantry.session as session_module

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
            events.append("cubos.instruments.connect")

        def disconnect_instruments(self):
            events.append("cubos.instruments.disconnect")

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

    assert events == ["cubos.instruments.connect", "cubos.instruments.disconnect", "store.close"]


def test_run_protocol_health_failure_after_instruments_uses_session_error(
    monkeypatch,
    tmp_path,
):
    import cubos.gantry.session as session_module

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
            events.append("cubos.instruments.connect")

        def disconnect_instruments(self):
            events.append("cubos.instruments.disconnect")

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

    assert events == ["cubos.instruments.connect", "cubos.instruments.disconnect", "store.close"]


@pytest.mark.parametrize("action", ["home", "unlock", "reset_and_unlock", "resume", "set_work_coordinates"])
def test_disconnected_locked_action_releases_lock_and_allows_reconnect(tmp_path, action):
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _seconds: None)
    with pytest.raises(GantryNotConnectedError):
        getattr(session, action)()
    acquired = session.operation_lock.acquire(blocking=False)
    assert acquired, "A disconnected action must not retain the serial-operation lock."
    session.operation_lock.release()
    assert session.connect(_write_gantry(tmp_path), filename="gantry.yaml").connected
    assert session.home().connected
    assert ("home", None) in FakeGantry.instances[-1].calls


@pytest.mark.parametrize("error", [RuntimeError("connection check failed"), KeyboardInterrupt()])
def test_locked_entry_failure_preserves_exception_and_releases_lock(monkeypatch, tmp_path, error):
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _seconds: None)

    def fail_connection_check():
        raise error

    with monkeypatch.context() as patch:
        patch.setattr(session, "_require_connected", fail_connection_check)
        with pytest.raises(type(error)) as raised:
            session.home()
        assert raised.value is error
    acquired = session.operation_lock.acquire(blocking=False)
    assert acquired, "An interrupted context entry must release the acquired lock."
    session.operation_lock.release()
    assert session.connect(_write_gantry(tmp_path), filename="gantry.yaml").connected


@pytest.mark.parametrize("status", ["<Idle|WPos:0,0,0|Pn:Z>", "<idle|Pn:XY>"])
def test_blocking_jog_rejects_idle_with_active_limit(tmp_path, status):
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    fake.status = status
    fake.calls.clear()

    with pytest.raises(GantryAlarmError):
        session.jog_blocking(z=1)

    assert not fake.calls


def test_alarm_stays_latched_across_failed_queries_and_cached_idle_until_verified_unlock(tmp_path):
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    original_position = fake.get_position_info

    for failure in [RuntimeError("ALARM:3"), RuntimeError("No position: [MSG:Check Limits]"), RuntimeError("No parsable position")]:
        fake.get_position_info = lambda error=failure: (_ for _ in ()).throw(error)
        snapshot = session.position()
        assert snapshot.status == "ALARM:3"
        assert snapshot.work_x is snapshot.work_y is snapshot.work_z is None

    fake.get_position_info = original_position
    assert session.position().status == "ALARM:3"
    fake.calls.clear()
    with pytest.raises(GantryAlarmError):
        session.jog(z=1)
    with pytest.raises(GantryAlarmError):
        session.move_to_blocking(x=1, y=1, z=1)
    assert not fake.calls

    fake.status = "[MSG:Check Limits]"
    with pytest.raises(GantryAlarmError):
        session.unlock()
    assert session.position().status == "ALARM:3"

    fake.status = "Idle"
    snapshot = session.unlock()
    assert snapshot.status == "Home required"
    assert snapshot.work_z is None
    with pytest.raises(CalibrationBlockedError, match="Home before"):
        session.jog(z=1)
    snapshot = session.home()
    assert snapshot.status == "Idle"
    assert snapshot.work_z == 30
    assert session.position().status == "Idle"


def test_failed_position_query_never_returns_cached_idle_coordinates(tmp_path):
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    fake.get_position_info = lambda: (_ for _ in ()).throw(RuntimeError("No parsable position"))

    snapshot = session.position()

    assert snapshot.status == "Query failed"
    assert snapshot.work_x is snapshot.work_y is snapshot.work_z is None
    assert snapshot.x == 10


@pytest.mark.parametrize("status", ["<Idle|Pn:Z>", "<Hold:0>", "[MSG:Check Limits]"])
def test_unlock_acknowledgement_does_not_clear_fault_without_verified_idle(tmp_path, status):
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    session._latch_alarm_locked("ALARM:3")
    fake.status = status

    with pytest.raises(GantrySessionError):
        session.unlock()

    assert session.position().status.startswith("ALARM:3")


def test_position_latches_limit_from_raw_status_and_blocks_jog_before_actuation(tmp_path):
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    fake.get_position_info = lambda: {
        "coords": fake.coords, "work_pos": fake.coords,
        "status": "Idle", "raw_status": "<Idle|WPos:10,20,30|Pn:Z>",
    }

    snapshot = session.position()

    assert "Pn:Z" in snapshot.status
    assert snapshot.work_z is None
    with pytest.raises(GantryAlarmError):
        session.jog(z=1)


def test_unlock_connection_failure_keeps_alarm_and_propagates(tmp_path):
    from cubos.gantry.errors import MillConnectionError

    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    failure = MillConnectionError("USB disconnected")
    session._latch_alarm_locked("ALARM:3")
    fake.get_status = lambda: (_ for _ in ()).throw(failure)

    with pytest.raises(MillConnectionError) as caught:
        session.unlock()

    assert caught.value is failure
    assert session.position().status == "ALARM:3"


def test_guarded_z_recovery_preserves_original_direction_and_requires_home(tmp_path):
    class RecoveringZ(FakeGantry):
        def reset_and_unlock(self):
            super().reset_and_unlock()
            self.status = "<Idle|Pn:Z>"

        def jog(self, **kwargs):
            super().jog(**kwargs)
            self.status = "Idle"

    session = GantrySession(gantry_factory=RecoveringZ, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    session.jog(z=-1)
    fake.status = "<Alarm|Pn:Z>"
    session.position()

    with pytest.raises(GantryAlarmError):
        session.jog(z=1)
    with pytest.raises(GantryAlarmError, match="matching failed jog"):
        session.recover_calibration_limit(z=1)
    fake.calls.clear()

    result, _ = session.recover_calibration_limit(z=-1)

    assert result.pull_off_delta == {"x": 0, "y": 0, "z": 5}
    assert [name for name, _ in fake.calls].count("reset_and_unlock") == 1
    assert [value for name, value in fake.calls if name == "jog"] == [{"x": 0, "y": 0, "z": 5, "feed_rate": 100}]
    assert not any(name in ("home", "set_hard_limits_enabled", "set_soft_limits_enabled") for name, _ in fake.calls)
    assert session.position().status == "Home required"
    assert session.position().work_z is None
    with pytest.raises(CalibrationBlockedError):
        session.set_work_coordinates(z=0)
    assert session.home().status == "Idle"


@pytest.mark.parametrize("status", ["ALARM:3", "[MSG:Check Limits]", "<Alarm|Pn:X>", "<Alarm|Pn:XZ>"])
def test_recovery_without_confirmed_z_pin_never_actuates(tmp_path, status):
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    session.jog(z=-1)
    fake.status = status
    session.position()
    fake.calls.clear()

    with pytest.raises(GantryAlarmError):
        session.recover_calibration_limit(z=-1)

    assert fake.calls == [("get_status", None)]


def test_recovery_cancel_during_reset_prevents_pull_off(tmp_path):
    class CancelDuringReset(FakeGantry):
        def reset_and_unlock(self):
            super().reset_and_unlock()
            session.jog_cancel_interrupt()

    from cubos.gantry.errors import CommandExecutionError

    session = GantrySession(gantry_factory=CancelDuringReset, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    session.jog(z=-1)
    fake.status = "<Alarm|Pn:Z>"
    session.position()
    fake.calls.clear()

    with pytest.raises(CommandExecutionError, match="cancelled"):
        session.recover_calibration_limit(z=-1)

    assert not any(name == "jog" for name, _ in fake.calls)
    assert session.position().work_z is None


def test_recovery_rejects_unknown_jog_even_with_z_pin(tmp_path):
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    fake.status = "<Alarm|Pn:Z>"
    session.position()
    fake.calls.clear()

    with pytest.raises(GantryAlarmError, match="matching failed jog"):
        session.recover_calibration_limit(z=-1)

    assert not fake.calls


def test_home_clears_incident_warning_but_preserves_calibration_warning_and_failure(tmp_path):
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    session._calibration_warning = "Saved calibration mismatch."
    session._calibration_frame_unverified = True
    session._latch_alarm_locked("ALARM:3")
    assert "Home before" in session.calibration_warning

    snapshot = session.home()

    assert snapshot.status == "Idle"
    assert snapshot.calibration_warning == "Saved calibration mismatch."
    with pytest.raises(CalibrationBlockedError, match="Restart full calibration"):
        session.jog(z=1)


def test_failed_home_keeps_position_reference_untrusted(tmp_path):
    from cubos.gantry.errors import StatusReturnError

    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    session._latch_alarm_locked("ALARM:3")
    failure = StatusReturnError("Homing failed")
    fake.home = lambda: (_ for _ in ()).throw(failure)

    with pytest.raises(StatusReturnError) as caught:
        session.home()

    assert caught.value is failure
    assert session.position().work_z is None
    assert "Home before" in session.calibration_warning


def test_failed_home_cannot_reuse_previous_jog_as_recovery_direction(tmp_path):
    from cubos.gantry.errors import StatusReturnError

    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    session.jog(z=-1)
    fake.home = lambda: (_ for _ in ()).throw(StatusReturnError("ALARM:8"))
    with pytest.raises(StatusReturnError):
        session.home()
    fake.status = "<Alarm|Pn:Z>"
    session.position()

    with pytest.raises(GantryAlarmError, match="matching failed jog"):
        session.recover_calibration_limit(z=-1)


def test_query_failure_stays_unknown_while_operation_lock_is_held(tmp_path):
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    fake.get_position_info = lambda: (_ for _ in ()).throw(RuntimeError("No position"))
    assert session.position().status == "Query failed"

    with session.operation_lock:
        snapshot = session.position()

    assert snapshot.status == "Query failed"
    assert snapshot.work_z is None


def test_first_fault_invalidates_queued_move_even_after_operator_home(tmp_path):
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    queued_generation = session._jog_cancel_generation
    session._latch_alarm_locked("ALARM:3")
    generation_after_alarm = session._jog_cancel_generation
    session._latch_alarm_locked("[MSG:Check Limits]")
    assert session._jog_cancel_generation == generation_after_alarm
    assert generation_after_alarm > queued_generation
    session.home()
    fake.calls.clear()

    session._move_worker(10, 20, 30, queued_generation)

    assert not fake.calls


def test_stale_idle_after_accepted_jog_cannot_create_unverified_recovery_direction(tmp_path):
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    session.jog(z=-1)
    session.position()
    fake.status = "<Alarm|Pn:Z>"
    session.position()
    fake.calls.clear()

    with pytest.raises(GantryAlarmError, match="matching failed jog"):
        session.recover_calibration_limit(z=-1)

    assert not fake.calls


def test_operator_recovery_cannot_request_longer_pull_off(tmp_path):
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    fake.calls.clear()

    with pytest.raises(ValueError, match="5 mm"):
        session.recover_calibration_limit(z=-1, pull_off_mm=100)

    assert not fake.calls


@pytest.mark.parametrize("raw_status,work_pos", [("<Idle|Pn:Z>", {"x": 0, "y": 0, "z": 0}), ("<Idle>", None), ("<Jog>", {"x": 0, "y": 0, "z": 0})])
def test_unlock_needs_verified_fresh_coordinates_and_status_after_idle_probe(tmp_path, raw_status, work_pos):
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    session._latch_alarm_locked("ALARM:3")
    fake.get_position_info = lambda: {"status": "Idle", "raw_status": raw_status, "work_pos": work_pos, "coords": fake.coords}

    with pytest.raises(GantrySessionError):
        session.unlock()

    assert session.position().status.startswith("ALARM:3")
    assert session.position().work_z is None


@pytest.mark.parametrize("blocking", [False, True])
@pytest.mark.parametrize("response", ["error:8", "", "<Jog|WPos:10,20,30>"])
def test_only_explicit_jog_ack_can_supply_recovery_direction(tmp_path, monkeypatch, blocking, response):
    from unittest.mock import MagicMock

    from cubos.gantry.errors import CommandExecutionError
    from cubos.gantry.gantry_driver.driver import Mill
    from tests.gantry.fake_serial import FakeGrblSerial

    monkeypatch.setattr("cubos.gantry.gantry_driver.driver.set_up_mill_logger", lambda _: MagicMock())
    monkeypatch.setattr("cubos.gantry.gantry_driver.driver.set_up_command_logger", lambda _: MagicMock())

    class SerialJogGantry(FakeGantry):
        def __init__(self, config=None):
            super().__init__(config=config)
            self.mill = Mill()
            self.serial = FakeGrblSerial()
            self.mill.ser_mill = self.serial

        def jog(self, **kwargs):
            self.mill.jog(**kwargs)
            super().jog(**kwargs)

    session = GantrySession(gantry_factory=SerialJogGantry, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    session.jog(z=-1)
    fake.serial.jog_response = response

    with pytest.raises(CommandExecutionError):
        (session.jog_blocking if blocking else session.jog)(z=1)

    fake.status = "<Alarm|Pn:Z>"
    session.position()
    expected_candidate = {"x": 0, "y": 0, "z": -1} if response == "error:8" else None
    assert session._failed_jog_delta == expected_candidate
    with pytest.raises(GantryAlarmError, match="matching failed jog"):
        session.recover_calibration_limit(z=1)
    assert fake.serial.writes == [b"$J=G91 Z-1.000 F2000\n", b"$J=G91 Z1.000 F2000\n"]


@pytest.mark.parametrize("blocking", [False, True])
def test_jog_connection_loss_invalidates_old_direction_and_propagates(tmp_path, blocking):
    from cubos.gantry.errors import MillConnectionError

    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    session.jog(z=-1)
    failure = MillConnectionError("USB disconnected before jog acknowledgement")
    fake.jog = lambda **_: (_ for _ in ()).throw(failure)

    with pytest.raises(MillConnectionError) as caught:
        (session.jog_blocking if blocking else session.jog)(z=1)

    assert caught.value is failure
    assert session._last_jog_delta is None
    assert session.position().status == "Home required"
    assert session.position().work_z is None


@pytest.mark.parametrize("entrypoint", ["home", "prepare_calibration_origin", "calibration_home_and_center"])
def test_normal_homing_poll_is_in_progress_not_a_home_required_fault(tmp_path, entrypoint):
    observed = []

    class PollDuringHome(FakeGantry):
        def home(self):
            super().home()
            observed.append(session.position())

        def get_coordinates(self):
            return dict(self.coords)

    session = GantrySession(gantry_factory=PollDuringHome, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")

    getattr(session, entrypoint)()

    assert observed[0].status == "Homing"
    assert observed[0].work_x is observed[0].work_y is observed[0].work_z is None
    assert not observed[0].calibration_warning or "Home before moving" not in observed[0].calibration_warning
    assert session.position().status == "Idle"
    assert session.position().work_z is not None


def test_existing_alarm_is_not_hidden_by_in_progress_homing(tmp_path):
    observed = []

    class PollDuringHome(FakeGantry):
        def home(self):
            super().home()
            observed.append(session.position())

    session = GantrySession(gantry_factory=PollDuringHome, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    session._latch_alarm_locked("ALARM:3")

    assert session.home().status == "Idle"

    assert observed[0].status == "ALARM:3"
    assert observed[0].work_z is None


@pytest.mark.parametrize("entrypoint", ["home", "prepare_calibration_origin", "calibration_home_and_center"])
def test_homing_flag_covers_verification_and_clears_on_failure(tmp_path, entrypoint):
    from cubos.gantry.errors import StatusReturnError

    observed = []
    failure = StatusReturnError("Status verification failed")

    class FailVerification(FakeGantry):
        def get_status(self):
            observed.append(session.position())
            raise failure

        def get_coordinates(self):
            return dict(self.coords)

    session = GantrySession(gantry_factory=FailVerification, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")

    with pytest.raises(StatusReturnError) as caught:
        getattr(session, entrypoint)()

    assert caught.value is failure
    assert observed[0].status == "Homing"
    assert observed[0].work_z is None
    assert session.position().status == "Home required"
    assert session.position().work_z is None
    assert not session._homing_active


def test_fault_observed_while_homing_is_preserved_after_failure(tmp_path):
    observed = []

    class AlarmDuringHome(FakeGantry):
        def home(self):
            super().home()
            self.status = "<Alarm|Pn:Y>"
            observed.append(session.position())

    session = GantrySession(gantry_factory=AlarmDuringHome, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")

    with pytest.raises(GantryAlarmError):
        session.home()

    assert "Alarm" in observed[0].status
    assert "Pn:Y" in observed[0].status
    assert observed[0].work_z is None
    assert "Pn:Y" in session.position().status
    assert not session._homing_active


@pytest.mark.parametrize("axis,direction", [("x", 1), ("x", -1), ("y", 1), ("y", -1), ("z", 1), ("z", -1)])
def test_known_single_axis_recovery_uses_authoritative_candidate_and_fixed_speed(tmp_path, axis, direction):
    class RecoveringAxis(FakeGantry):
        def reset_and_unlock(self):
            super().reset_and_unlock()
            self.status = f"<Idle|Pn:{axis.upper()}>"

        def jog(self, **kwargs):
            super().jog(**kwargs)
            self.status = "Idle"

    session = GantrySession(gantry_factory=RecoveringAxis, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    session.jog(**{axis: direction})
    fake.status = f"<Alarm|Pn:{axis.upper()}>"
    fake.calls.clear()

    context = session.limit_recovery_context()

    assert context.eligible and context.manual_available
    assert context.active_limit_axes == [axis]
    assert context.failed_jog_delta[axis] == direction
    assert context.pull_off_delta[axis] == -5 * direction
    assert fake.calls == [("get_status", None)]
    fake.calls.clear()
    result, _ = session.recover_calibration_limit(**{axis: direction})
    assert result.mode == "known_jog"
    assert result.failed_delta == context.failed_jog_delta
    assert result.commanded_delta == context.pull_off_delta
    assert result.attempts == 1
    jog = [args for name, args in fake.calls if name == "jog"]
    assert jog == [{"x": context.pull_off_delta["x"], "y": context.pull_off_delta["y"], "z": context.pull_off_delta["z"], "feed_rate": 100}]
    assert sum(name == "reset_and_unlock" for name, _ in fake.calls) == 1
    assert not any(name in ("home", "set_soft_limits_enabled", "set_hard_limits_enabled", "set_work_coordinates") for name, _ in fake.calls)
    assert session.position().status == "Home required"
    assert session.position().work_z is None


@pytest.mark.parametrize("axis,away", [("x", 1), ("x", -1), ("y", 1), ("y", -1), ("z", 1), ("z", -1)])
def test_manual_recovery_is_one_mm_and_does_not_invent_failed_history(tmp_path, axis, away):
    class ManualGantry(FakeGantry):
        def reset_and_unlock(self):
            super().reset_and_unlock()
            self.status = f"<Idle|Pn:{axis.upper()}>"

        def jog(self, **kwargs):
            super().jog(**kwargs)
            self.status = "Idle"

    session = GantrySession(gantry_factory=ManualGantry, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    fake.status = f"<Alarm|Pn:{axis.upper()}>"
    fake.calls.clear()

    result, _ = session.recover_calibration_limit_manual(axis=axis, away_direction=away, operator_confirmed=True)

    assert result.mode == "manual"
    assert result.failed_delta is None
    assert result.commanded_delta == {key: float(away) if key == axis else 0 for key in ("x", "y", "z")}
    assert result.pull_off_delta == result.commanded_delta
    assert result.attempts == 1
    jogs = [args for name, args in fake.calls if name == "jog"]
    assert jogs == [{**result.commanded_delta, "feed_rate": 100}]
    assert sum(name == "reset_and_unlock" for name, _ in fake.calls) == 1
    assert not any(name in ("home", "set_soft_limits_enabled", "set_hard_limits_enabled", "set_work_coordinates") for name, _ in fake.calls)
    assert session._failed_jog_delta is None
    assert session.position().status == "Home required"
    assert session.position().work_z is None


@pytest.mark.parametrize("status", ["<Idle>", "<Alarm|Pn:XY>", "<Alarm|Pn:YP>", "<Alarm|Pn:P>", "<Jog|Pn:Y>", "<Hold:0|Pn:Y>"])
def test_recovery_context_and_manual_guard_reject_unknown_multiple_or_unrelated_pins(tmp_path, status):
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    fake.status = status
    fake.calls.clear()
    context = session.limit_recovery_context()
    assert not context.eligible
    assert not context.manual_available
    assert context.blocked_reason
    assert context.pull_off_delta is None
    with pytest.raises(GantryAlarmError):
        session.recover_calibration_limit_manual(axis="y", away_direction=1, operator_confirmed=True)
    assert all(name == "get_status" for name, _ in fake.calls)


@pytest.mark.parametrize("kwargs", [{"axis": "Y"}, {"away_direction": 0}, {"away_direction": float("nan")}, {"away_direction": True}, {"operator_confirmed": False}, {"operator_confirmed": 1}, {"operator_confirmed": "true"}])
def test_manual_recovery_requires_literal_confirmation_and_signed_direction(tmp_path, kwargs):
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    fake.calls.clear()
    request = {"axis": "y", "away_direction": 1, "operator_confirmed": True, **kwargs}
    with pytest.raises(ValueError):
        session.recover_calibration_limit_manual(**request)
    assert not fake.calls


def test_manual_post_rechecks_pin_after_context_changes(tmp_path):
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    fake.status = "<Alarm|Pn:Y>"
    assert session.limit_recovery_context().manual_available
    fake.status = "<Alarm|Pn:X>"
    fake.calls.clear()
    with pytest.raises(GantryAlarmError):
        session.recover_calibration_limit_manual(axis="y", away_direction=1, operator_confirmed=True)
    assert fake.calls == [("get_status", None)]


def test_manual_recovery_does_not_jog_when_pin_changes_after_reset(tmp_path):
    class ChangedPin(FakeGantry):
        def reset_and_unlock(self):
            super().reset_and_unlock()
            self.status = "<Idle|Pn:X>"

    from cubos.gantry.errors import StatusReturnError
    session = GantrySession(gantry_factory=ChangedPin, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    fake.status = "<Alarm|Pn:Y>"
    fake.calls.clear()
    with pytest.raises(StatusReturnError, match="did not verify"):
        session.recover_calibration_limit_manual(axis="y", away_direction=1, operator_confirmed=True)
    assert not any(name == "jog" for name, _ in fake.calls)
    assert sum(name == "reset_and_unlock" for name, _ in fake.calls) == 1


def test_stop_during_initial_manual_context_check_prevents_actuation(tmp_path):
    class StopWhileReading(FakeGantry):
        def get_recovery_status(self):
            session.jog_cancel_interrupt()
            return self.status

    from cubos.gantry.errors import CommandExecutionError
    session = GantrySession(gantry_factory=StopWhileReading, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    fake.status = "<Alarm|Pn:Y>"
    fake.calls.clear()
    with pytest.raises(CommandExecutionError, match="cancelled"):
        session.recover_calibration_limit_manual(axis="y", away_direction=1, operator_confirmed=True)
    assert not any(name in ("jog", "reset_and_unlock") for name, _ in fake.calls)


@pytest.mark.parametrize("recovery_request", [{}, {"x": 1, "y": 1}, {"x": float("nan")}, {"y": float("inf")}, {"z": 1, "feed_rate": 2500}])
def test_known_recovery_rejects_invalid_vector_or_speed_before_queries(tmp_path, recovery_request):
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    fake.calls.clear()
    with pytest.raises(ValueError):
        session.recover_calibration_limit(**recovery_request)
    assert not fake.calls


@pytest.mark.parametrize("candidate", [{"x": 1, "y": 1, "z": 0}, {"x": float("inf"), "y": 0, "z": 0}])
def test_context_never_offers_known_recovery_from_invalid_candidate(tmp_path, candidate):
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    fake.status = "<Alarm|Pn:X>"
    session._failed_jog_delta = candidate
    fake.calls.clear()
    context = session.limit_recovery_context()
    assert not context.eligible
    assert context.manual_available
    assert context.pull_off_delta is None
    assert fake.calls == [("get_status", None)]


@pytest.mark.parametrize("phase", ["context", "reset", "jog", "post_status", "final_position"])
def test_manual_recovery_connection_loss_is_terminal_and_preserved(tmp_path, phase):
    from cubos.gantry.errors import MillConnectionError
    failure = MillConnectionError(f"USB disconnected at {phase}")

    class ConnectionFailure(FakeGantry):
        reads = 0

        def get_recovery_status(self):
            self.reads += 1
            if phase == "context" or (phase == "post_status" and self.reads == 3):
                raise failure
            return self.status

        def reset_and_unlock(self):
            super().reset_and_unlock()
            if phase == "reset":
                raise failure
            self.status = "<Idle|Pn:Y>"

        def jog(self, **kwargs):
            if phase == "jog":
                raise failure
            super().jog(**kwargs)
            self.status = "Idle"

        def get_recovery_position_info(self):
            if phase == "final_position":
                raise failure
            return self.get_position_info()

    session = GantrySession(gantry_factory=ConnectionFailure, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    fake.status = "<Alarm|Pn:Y>"
    fake.calls.clear()
    with pytest.raises(MillConnectionError) as caught:
        session.recover_calibration_limit_manual(axis="y", away_direction=1, operator_confirmed=True)
    assert caught.value is failure
    assert sum(name == "reset_and_unlock" for name, _ in fake.calls) <= 1
    assert sum(name == "jog" for name, _ in fake.calls) <= 1
    assert not any(name in ("home", "connect", "set_soft_limits_enabled", "set_hard_limits_enabled") for name, _ in fake.calls)


def test_stop_during_final_recovery_verification_does_not_report_success(tmp_path):
    from cubos.gantry.errors import CommandExecutionError

    class StopFinal(FakeGantry):
        def reset_and_unlock(self):
            super().reset_and_unlock()
            self.status = "<Idle|Pn:Y>"

        def jog(self, **kwargs):
            super().jog(**kwargs)
            self.status = "Idle"

        def get_recovery_position_info(self):
            session.jog_cancel_interrupt()
            return self.get_position_info()

    session = GantrySession(gantry_factory=StopFinal, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    fake.status = "<Alarm|Pn:Y>"
    fake.calls.clear()
    with pytest.raises(CommandExecutionError, match="cancelled"):
        session.recover_calibration_limit_manual(axis="y", away_direction=1, operator_confirmed=True)
    assert sum(name == "jog" for name, _ in fake.calls) == 1
    assert session.position().status == "Home required"
    assert session.position().work_z is None


def test_connect_on_pressed_y_publishes_only_a_faulted_recovery_session(tmp_path):
    from cubos.gantry.errors import StatusReturnError

    class PressedY(FakeGantry):
        def get_position_info(self):
            raise StatusReturnError("Error in status: [MSG:Check Limits]")

        def get_recovery_status(self):
            self.calls.append(("get_recovery_status", None))
            return "<Alarm|Pn:Y>"

    session = GantrySession(gantry_factory=PressedY, sleep=lambda _: None)
    snapshot = session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]

    assert snapshot.connected
    assert snapshot.work_x is snapshot.work_y is snapshot.work_z is None
    assert "Check Limits" in snapshot.status
    assert "Pn:Y" in snapshot.status
    assert "Home before" in snapshot.calibration_warning
    context = session.limit_recovery_context()
    assert context.manual_available
    assert context.active_limit_axes == ["y"]
    assert not context.eligible
    assert context.failed_jog_delta is None
    for action in [lambda: session.jog(y=1), lambda: session.move_to_blocking(x=1, y=1, z=1), lambda: session.set_work_coordinates(y=0)]:
        with pytest.raises(GantryAlarmError):
            action()
    assert not any(name in ("jog", "home", "unlock", "reset_and_unlock", "set_work_coordinates", "set_soft_limits_enabled", "set_hard_limits_enabled") for name, _ in fake.calls)
    assert fake.disconnect_calls == 0


@pytest.mark.parametrize("frame", ["<Idle|WPos:1,2,3>", "<Alarm|Pn:Y>", "ALARM:1"])
def test_recognized_connect_fault_never_publishes_a_trusted_pose(tmp_path, frame):
    from cubos.gantry.errors import StatusReturnError

    class FaultedConnect(FakeGantry):
        def get_position_info(self):
            raise StatusReturnError("ALARM:3")

        def get_recovery_status(self):
            if frame == "ALARM:1":
                raise StatusReturnError("Error in status: ALARM:1")
            return frame

    session = GantrySession(gantry_factory=FaultedConnect, sleep=lambda _: None)
    snapshot = session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    assert snapshot.connected
    assert snapshot.status.startswith("ALARM:3")
    assert snapshot.work_x is snapshot.work_y is snapshot.work_z is None
    assert session._position_reference_untrusted


@pytest.mark.parametrize("phase", ["normal_position", "recovery_status", "settings"])
def test_connect_transport_failure_closes_without_recovery_or_motion(tmp_path, phase):
    from cubos.gantry.errors import MillConnectionError, StatusReturnError
    failure = MillConnectionError("USB disconnected")

    class ConnectionFailure(FakeGantry):
        def get_position_info(self):
            if phase == "normal_position":
                raise failure
            raise StatusReturnError("[MSG:Check Limits]")

        def get_recovery_status(self):
            raise failure

        def read_grbl_settings(self):
            if phase == "settings":
                raise failure
            return super().read_grbl_settings()

    session = GantrySession(gantry_factory=ConnectionFailure, sleep=lambda _: None)
    with pytest.raises(MillConnectionError) as caught:
        session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    assert caught.value is failure
    assert not session.connected
    fake = FakeGantry.instances[-1]
    assert fake.disconnect_calls == 1
    assert not any(name in ("home", "unlock", "jog", "reset_and_unlock") for name, _ in fake.calls)


@pytest.mark.parametrize("frame", ["", "ok", "<Unknown|Pn:Y>", "[MSG:Check Limits]"])
def test_connect_fault_without_verified_controller_status_still_closes(tmp_path, frame):
    from cubos.gantry.errors import StatusReturnError

    class UnknownResponse(FakeGantry):
        def get_position_info(self):
            raise StatusReturnError("[MSG:Check Limits]")

        def get_recovery_status(self):
            return frame

    session = GantrySession(gantry_factory=UnknownResponse, sleep=lambda _: None)
    with pytest.raises(GantrySessionError, match="could not be verified"):
        session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    assert not session.connected
    assert FakeGantry.instances[-1].disconnect_calls == 1


def test_connect_without_current_work_coordinates_does_not_publish_defaults(tmp_path):
    class MissingCoordinates(FakeGantry):
        def get_position_info(self):
            return {"coords": self.coords, "work_pos": None, "status": "Idle"}

    session = GantrySession(gantry_factory=MissingCoordinates, sleep=lambda _: None)
    with pytest.raises(GantrySessionError, match="did not verify current work coordinates"):
        session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    assert not session.connected
    assert FakeGantry.instances[-1].disconnect_calls == 1


def test_restore_refreshes_stale_soft_limits_warning_after_verified_enable(tmp_path):
    class LiveSettings(FakeGantry):
        def set_soft_limits_enabled(self, enabled):
            super().set_soft_limits_enabled(enabled)
            self.grbl_settings["$20"] = "1" if enabled else "0"

        def soft_limits_enabled(self):
            self.calls.append(("soft_limits_enabled", None))
            return self.grbl_settings["$20"] == "1"

    session = GantrySession(gantry_factory=LiveSettings, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    fake.grbl_settings["$20"] = "0"
    session._calibration_restore_soft_limits = True
    session._calibration_jog_bypass_working_volume = True
    session._calibration_warning = session._calibration_mismatch_warning(fake, session.connected_gantry_config)
    assert "$20: expected 1, got 0" in session.calibration_warning
    fake.calls.clear()

    snapshot = session.restore_calibration_soft_limits()

    assert not session.calibration_active
    assert fake.grbl_settings["$20"] == "1"
    assert snapshot.calibration_warning is None
    assert session.calibration_warning is None
    assert fake.calls == [("set_soft_limits_enabled", True), ("soft_limits_enabled", None), ("read_grbl_settings", None)]


def test_verified_home_refreshes_unknown_settings_warning_with_fresh_read(tmp_path):
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    session._calibration_warning = "Calibration status unknown: prior fault prevented reading settings."
    session._latch_alarm_locked("ALARM:1")
    fake.calls.clear()

    snapshot = session.home()

    assert snapshot.status == "Idle"
    assert snapshot.calibration_warning is None
    assert session.calibration_warning is None
    assert [name for name, _ in fake.calls] == ["home", "get_status", "read_grbl_settings"]


@pytest.mark.parametrize("action", ["home", "restore_calibration_soft_limits"])
@pytest.mark.parametrize("live_state", ["mismatch", "read_failure"])
def test_warning_refresh_preserves_actual_mismatch_or_unknown_settings(tmp_path, action, live_state):
    from cubos.gantry.errors import StatusReturnError

    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    session._calibration_warning = "Old warning."
    if live_state == "mismatch":
        fake.grbl_settings["$20"] = "0"
    else:
        fake.read_grbl_settings = lambda: (_ for _ in ()).throw(StatusReturnError("settings dump unavailable"))
    fake.calls.clear()

    snapshot = getattr(session, action)()

    assert ("$20: expected 1, got 0" if live_state == "mismatch" else "Calibration status unknown") in snapshot.calibration_warning
    if live_state == "read_failure":
        assert "settings dump unavailable" in snapshot.calibration_warning
    assert not any(name in ("jog", "reset_and_unlock", "unlock", "set_soft_limits_enabled", "set_hard_limits_enabled", "set_work_coordinates") for name, _ in fake.calls)


@pytest.mark.parametrize("action", ["home", "restore_calibration_soft_limits"])
def test_warning_refresh_propagates_connection_loss_without_clearing_fault_guards(tmp_path, action):
    from cubos.gantry.errors import MillConnectionError

    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    session._calibration_warning = "Existing warning."
    session._latch_alarm_locked("ALARM:1")
    failure = MillConnectionError("USB disconnected during settings read")
    fake.read_grbl_settings = lambda: (_ for _ in ()).throw(failure)

    with pytest.raises(MillConnectionError) as caught:
        getattr(session, action)()

    assert caught.value is failure
    assert session._calibration_warning == "Existing warning."
    assert session._alarm_status == "ALARM:1"
    assert session._position_reference_untrusted


@pytest.mark.parametrize("action", ["home", "restore_calibration_soft_limits"])
def test_settings_refresh_does_not_clear_origin_failure_or_pending_config(tmp_path, action):
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    session._calibration_frame_unverified = True
    session._calibration_warning = "Calibration origin did not verify. Restart full calibration."
    session._calibration_pending_config = {"unsaved": True}
    fake.calls.clear()

    snapshot = getattr(session, action)()

    assert snapshot.calibration_warning == "Calibration origin did not verify. Restart full calibration."
    assert session._calibration_frame_unverified
    assert session._calibration_pending_config == {"unsaved": True}
    assert not any(name == "read_grbl_settings" for name, _ in fake.calls)


def test_restore_refresh_does_not_clear_existing_alarm_or_untrusted_reference(tmp_path):
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    session._latch_alarm_locked("ALARM:1")
    session._calibration_warning = "Stale settings mismatch."

    snapshot = session.restore_calibration_soft_limits()

    assert snapshot.status == "ALARM:1"
    assert snapshot.work_z is None
    assert session._position_reference_untrusted
    assert "Home before" in snapshot.calibration_warning


class CorrelatedRecoveryGantry(FakeGantry):
    trip_next = False

    def jog(self, **kwargs):
        super().jog(**kwargs)
        self.status = "<Alarm|Pn:Y>" if self.trip_next else "Idle"
        self.trip_next = False

    def reset_and_unlock(self):
        super().reset_and_unlock()
        self.status = "<Idle|Pn:Y>"


def _correlated_fault(tmp_path, *, blocking=False, jog_id="wizard-owned"):
    session = GantrySession(gantry_factory=CorrelatedRecoveryGantry, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    fake.trip_next = True
    if blocking:
        with pytest.raises(GantryAlarmError):
            session.jog_blocking(y=0.25, jog_id=jog_id)
    else:
        session.jog(y=0.25, jog_id=jog_id)
    session.position()
    return session, fake


@pytest.mark.parametrize("blocking", [False, True])
def test_accepted_jog_id_is_exposed_with_its_failed_vector_and_consumed_once(tmp_path, blocking):
    session, fake = _correlated_fault(tmp_path, blocking=blocking)
    context = session.limit_recovery_context()
    assert context.failed_jog_id == "wizard-owned"
    assert context.failed_jog_delta == {"x": 0, "y": 0.25, "z": 0}
    assert context.eligible
    fake.calls.clear()

    result, _ = session.recover_calibration_limit(y=0.25, jog_id=context.failed_jog_id)

    assert result.mode == "known_jog"
    assert result.commanded_delta == {"x": 0, "y": -5, "z": 0}
    assert session._last_jog_id is session._failed_jog_id is None
    assert session.position().status == "Home required"
    writes = list(fake.calls)
    with pytest.raises(GantryAlarmError):
        session.recover_calibration_limit(y=0.25, jog_id="wizard-owned")
    assert fake.calls == writes
    assert sum(name == "reset_and_unlock" for name, _ in writes) == 1


@pytest.mark.parametrize("jog_id", ["foreign", "stale"])
def test_foreign_jog_id_is_rejected_before_controller_queries(tmp_path, jog_id):
    session, fake = _correlated_fault(tmp_path)
    fake.calls.clear()
    with pytest.raises(GantryAlarmError, match="jog_id"):
        session.recover_calibration_limit(y=0.25, jog_id=jog_id)
    assert not fake.calls


def test_last_accepted_jog_replaces_old_id_and_legacy_acceptance_has_no_id(tmp_path):
    session = GantrySession(gantry_factory=CorrelatedRecoveryGantry, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    session.jog(y=0.25, jog_id="old-id")
    fake.trip_next = True
    session.jog(y=0.25)
    session.position()
    context = session.limit_recovery_context()
    assert context.eligible
    assert context.failed_jog_id is None
    with pytest.raises(GantryAlarmError, match="jog_id"):
        session.recover_calibration_limit(y=0.25, jog_id="old-id")
    assert session.recover_calibration_limit(y=0.25)[0].mode == "known_jog"


@pytest.mark.parametrize("blocking", [False, True])
@pytest.mark.parametrize("rejection", ["error:8", "error:9"])
def test_rejected_jog_never_overwrites_accepted_id(tmp_path, blocking, rejection):
    from cubos.gantry.errors import CommandExecutionError

    session = GantrySession(gantry_factory=CorrelatedRecoveryGantry, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    session.jog(y=0.25, jog_id="accepted")
    fake.status = "<Jog|WPos:10,20,30>"
    fake.jog = lambda **_: (_ for _ in ()).throw(CommandExecutionError(f"Jog failed: {rejection}"))
    with pytest.raises((CommandExecutionError, GantryAlarmError)):
        (session.jog_blocking if blocking else session.jog)(y=-0.25, jog_id="rejected")
    fake.status = "<Alarm|Pn:Y>"
    session.position()
    context = session.limit_recovery_context()
    assert context.failed_jog_id == "accepted"
    assert context.failed_jog_delta["y"] == 0.25


@pytest.mark.parametrize("blocking", [False, True])
@pytest.mark.parametrize("failure_type", ["unknown_ack", "connection"])
def test_unknown_jog_acceptance_clears_all_correlation(tmp_path, blocking, failure_type):
    from cubos.gantry.errors import JogAcceptanceUnknownError, MillConnectionError

    session = GantrySession(gantry_factory=CorrelatedRecoveryGantry, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    session.jog(y=0.25, jog_id="old-accepted")
    failure = (JogAcceptanceUnknownError if failure_type == "unknown_ack" else MillConnectionError)("No verified jog acknowledgement")
    fake.jog = lambda **_: (_ for _ in ()).throw(failure)
    with pytest.raises(type(failure)) as caught:
        (session.jog_blocking if blocking else session.jog)(y=0.25, jog_id="unknown")
    assert caught.value is failure
    fake.status = "<Alarm|Pn:Y>"
    session.position()
    context = session.limit_recovery_context()
    assert context.failed_jog_id is None
    assert context.failed_jog_delta is None
    assert not context.eligible


@pytest.mark.parametrize("action", ["jog", "jog_blocking", "recover_calibration_limit"])
@pytest.mark.parametrize("jog_id", ["", "   ", "x" * 129, 42, True])
def test_invalid_correlation_is_rejected_without_controller_calls(tmp_path, action, jog_id):
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    fake.calls.clear()
    with pytest.raises(ValueError, match="jog_id"):
        getattr(session, action)(y=0.25, jog_id=jog_id)
    assert not fake.calls


@pytest.mark.parametrize("cancel_method", ["jog_cancel", "jog_cancel_interrupt"])
def test_post_stop_correlated_recovery_cannot_reuse_still_known_vector(tmp_path, cancel_method):
    session, fake = _correlated_fault(tmp_path)
    getattr(session, cancel_method)()
    context = session.limit_recovery_context()
    assert context.eligible
    assert context.failed_jog_delta["y"] == 0.25
    assert context.failed_jog_id is None
    fake.calls.clear()
    with pytest.raises(GantryAlarmError, match="jog_id"):
        session.recover_calibration_limit(y=0.25, jog_id="wizard-owned")
    assert not fake.calls


@pytest.mark.parametrize("blocking", [False, True])
def test_ack_after_stop_does_not_resurrect_jog_ownership(tmp_path, blocking):
    class CancelBeforeAck(CorrelatedRecoveryGantry):
        def jog(self, **kwargs):
            super().jog(**kwargs)
            session.jog_cancel_interrupt()

    session = GantrySession(gantry_factory=CancelBeforeAck, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    fake.trip_next = True
    if blocking:
        with pytest.raises(GantryAlarmError):
            session.jog_blocking(y=0.25, jog_id="cancelled-before-ack")
    else:
        session.jog(y=0.25, jog_id="cancelled-before-ack")
    session.position()
    assert session.limit_recovery_context().failed_jog_id is None


def test_cancel_during_pin_refresh_revokes_id_before_reset(tmp_path):
    session, fake = _correlated_fault(tmp_path)

    def status():
        session.jog_cancel_interrupt()
        return "<Alarm|Pn:Y>"

    fake.get_recovery_status = status
    fake.calls.clear()
    with pytest.raises(GantryAlarmError, match="jog_id"):
        session.recover_calibration_limit(y=0.25, jog_id="wizard-owned")
    assert fake.calls == [("jog_cancel", None)]


def test_duplicate_correlated_requests_serialize_to_one_recovery(tmp_path):
    entered = threading.Event()
    release = threading.Event()

    class PausedRecovery(CorrelatedRecoveryGantry):
        def reset_and_unlock(self):
            entered.set()
            assert release.wait(2)
            super().reset_and_unlock()

    session = GantrySession(gantry_factory=PausedRecovery, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    fake.trip_next = True
    session.jog(y=0.25, jog_id="once")
    session.position()
    fake.calls.clear()
    outcomes = []

    def recover():
        try:
            outcomes.append(session.recover_calibration_limit(y=0.25, jog_id="once"))
        except GantryAlarmError as exc:
            outcomes.append(exc)

    first = threading.Thread(target=recover)
    second = threading.Thread(target=recover)
    first.start()
    assert entered.wait(2)
    second.start()
    release.set()
    first.join(2)
    second.join(2)
    assert not first.is_alive() and not second.is_alive()
    assert sum(isinstance(item, GantryAlarmError) for item in outcomes) == 1
    assert len(outcomes) == 2
    assert sum(name == "reset_and_unlock" for name, _ in fake.calls) == 1
    assert sum(name == "jog" for name, _ in fake.calls) == 1


def test_failed_recovery_attempt_consumes_correlated_id_before_actuation(tmp_path):
    from cubos.gantry.errors import CommandExecutionError

    session, fake = _correlated_fault(tmp_path)
    fake.reset_and_unlock = lambda: (_ for _ in ()).throw(CommandExecutionError("Controller rejected reset"))
    with pytest.raises(CommandExecutionError):
        session.recover_calibration_limit(y=0.25, jog_id="wizard-owned")
    fake.calls.clear()
    with pytest.raises(GantryAlarmError):
        session.recover_calibration_limit(y=0.25, jog_id="wizard-owned")
    assert not fake.calls


@pytest.mark.parametrize("action", ["position", "home", "reset_and_unlock", "disconnect", "move_to_blocking", "move_worker"])
def test_jog_id_is_invalidated_with_existing_history_boundaries(tmp_path, action):
    session = GantrySession(gantry_factory=FakeGantry, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    session.jog(y=0.25, jog_id="old")
    if action == "move_to_blocking":
        session.move_to_blocking(x=10, y=20, z=30)
    elif action == "move_worker":
        session._move_worker(10, 20, 30)
    else:
        getattr(session, action)()
    assert session._last_jog_id is session._failed_jog_id is None


@pytest.mark.parametrize("blocking", [False, True])
@pytest.mark.parametrize("response", ["ALARM:1", "[MSG:Check Limits]"])
def test_alarm_before_ack_cannot_attribute_opposite_attempt_to_prior_accepted_jog(tmp_path, blocking, response):
    from cubos.gantry.errors import CommandExecutionError

    session = GantrySession(gantry_factory=CorrelatedRecoveryGantry, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    session.jog(y=-0.25, jog_id="accepted-opposite-A")

    def unacknowledged(**kwargs):
        fake.status = "<Alarm|Pn:Y>"
        raise CommandExecutionError(f"Jog failed: {response}")

    fake.jog = unacknowledged
    with pytest.raises(GantryAlarmError):
        (session.jog_blocking if blocking else session.jog)(y=0.25, jog_id="unacknowledged-B")
    context = session.limit_recovery_context()
    assert context.failed_jog_id is None
    assert context.failed_jog_delta is None
    assert not context.eligible
    assert context.manual_available
    fake.calls.clear()
    with pytest.raises(GantryAlarmError):
        session.recover_calibration_limit(y=-0.25, jog_id="accepted-opposite-A")
    assert not fake.calls


def test_alarm_from_blocking_probe_after_ack_preserves_current_accepted_id(tmp_path):
    from cubos.gantry.errors import StatusReturnError

    session = GantrySession(gantry_factory=CorrelatedRecoveryGantry, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    session.jog(y=-0.25, jog_id="prior-A")
    original_status = fake.get_status
    fake.get_status = lambda: (_ for _ in ()).throw(StatusReturnError("Error in status: ALARM:1"))
    with pytest.raises(GantryAlarmError):
        session.jog_blocking(y=0.25, jog_id="accepted-B")
    fake.get_status = original_status
    fake.status = "<Alarm|Pn:Y>"
    context = session.limit_recovery_context()
    assert context.failed_jog_id == "accepted-B"
    assert context.failed_jog_delta == {"x": 0, "y": 0.25, "z": 0}
    assert context.eligible


@pytest.mark.parametrize("reader", ["position", "context", "preflight", "wait"])
def test_fresh_healthy_idle_retires_auto_id_before_later_switch_activation(tmp_path, reader):
    session = GantrySession(gantry_factory=CorrelatedRecoveryGantry, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    session.jog(y=0.25, jog_id="completed-jog")
    if reader == "position":
        session.position()
    elif reader == "context":
        session.limit_recovery_context()
    elif reader == "preflight":
        with session.operation_lock:
            session._current_work_position_locked()
    else:
        with session.operation_lock:
            session._wait_until_idle_locked()
    fake.status = "<Alarm|Pn:Y>"
    session.position()
    context = session.limit_recovery_context()
    assert context.failed_jog_id is None
    fake.calls.clear()
    with pytest.raises(GantryAlarmError):
        session.recover_calibration_limit(y=0.25, jog_id="completed-jog")
    assert not fake.calls


@pytest.mark.parametrize("reader", ["position", "context"])
def test_fresh_idle_after_latched_alarm_revokes_auto_id_but_preserves_fault_and_vector(tmp_path, reader):
    session, fake = _correlated_fault(tmp_path)
    assert session.limit_recovery_context().failed_jog_id == "wizard-owned"
    fake.status = "<Idle|WPos:10,20,30>"
    (session.position if reader == "position" else session.limit_recovery_context)()
    assert session._alarm_status is not None
    assert session._position_reference_untrusted
    assert session._failed_jog_delta == {"x": 0, "y": 0.25, "z": 0}
    fake.status = "<Alarm|Pn:Y>"
    context = session.limit_recovery_context()
    assert context.failed_jog_id is None
    assert context.manual_available
    fake.calls.clear()
    with pytest.raises(GantryAlarmError, match="jog_id"):
        session.recover_calibration_limit(y=0.25, jog_id="wizard-owned")
    assert not fake.calls


def test_cached_idle_snapshot_cannot_retire_unresolved_accepted_jog_id(tmp_path):
    session = GantrySession(gantry_factory=CorrelatedRecoveryGantry, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    session.jog(y=0.25, jog_id="unresolved-jog")
    with session.operation_lock:
        assert session.position().status == "Idle"
    assert session._last_jog_id == "unresolved-jog"
    fake.status = "<Alarm|Pn:Y>"
    session.position()
    assert session.limit_recovery_context().failed_jog_id == "unresolved-jog"


@pytest.mark.parametrize("status", ["<Alarm|Pn:Y>", "<Idle|Pn:Y>"])
def test_active_limit_before_any_healthy_idle_keeps_accepted_auto_ownership(tmp_path, status):
    session = GantrySession(gantry_factory=CorrelatedRecoveryGantry, sleep=lambda _: None)
    session.connect(_write_gantry(tmp_path), filename="gantry.yaml")
    fake = FakeGantry.instances[-1]
    session.jog(y=0.25, jog_id="active-step")
    fake.status = status
    session.position()
    context = session.limit_recovery_context()
    assert context.failed_jog_id == "active-step"
    assert context.eligible
