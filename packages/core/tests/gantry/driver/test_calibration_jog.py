"""Correlated calibration steps fence ACKs and keep one moving owner."""

from collections import deque
from unittest.mock import MagicMock

import pytest

from cubos.gantry.errors import CommandExecutionError, JogAcceptanceUnknownError, MillConnectionError, StatusReturnError
from cubos.gantry.gantry import Gantry
from cubos.gantry.gantry_driver.driver import Mill
from cubos.gantry.session import CalibrationBlockedError, GantryAlarmError, GantryJogCancelledError, GantrySession, GantrySessionError
from tests.gantry.fake_serial import FakeGrblSerial


@pytest.fixture
def runtime(monkeypatch):
    monkeypatch.setattr("cubos.gantry.gantry_driver.driver.set_up_mill_logger", lambda _: MagicMock())
    monkeypatch.setattr("cubos.gantry.gantry_driver.driver.set_up_command_logger", lambda _: MagicMock())
    monkeypatch.setattr("cubos.gantry.gantry_driver.driver.time.sleep", lambda _: None)
    mill = Mill()
    mill.config = {"$100": "800", "$101": "800", "$102": "800"}
    gantry = Gantry(offline=True)
    gantry._offline = False
    gantry._mill = mill
    session = GantrySession(sleep=lambda _: None)
    session._gantry = gantry
    session._calibration_jog_bypass_working_volume = True
    return session, gantry, mill


class StepSerial(FakeGrblSerial):
    def __init__(self, *, responses=("ok",), positions=("<Idle|WPos:10,20,29>",), **kwargs):
        super().__init__(status="<Idle|WPos:10,20,30>", **kwargs)
        self.responses = responses
        self.positions = deque(positions)
        self.step_started = False
        self.on_read = None

    def write(self, data):
        if data.startswith(b"$J="):
            self.writes.append(data)
            self.step_started = True
            for response in self.responses:
                self.queue_line(response)
            return len(data)
        if data == b"?" and self.step_started and self.positions:
            self.status = self.positions.popleft()
        return super().write(data)

    def readline(self):
        if self.on_read:
            callback, self.on_read = self.on_read, None
            callback()
        return super().readline()


def jogs(serial):
    return [write for write in serial.writes if write.startswith(b"$J=")]


def test_exact_courtesy_then_own_ack_preserves_z_owner_through_alarm(runtime):
    session, _, mill = runtime
    serial = StepSerial(
        responses=("[MSG:Check Limits]", "ok"),
        positions=("<Alarm|WPos:10,20,28.844|Pn:Z>",),
    )
    mill.ser_mill = serial
    with pytest.raises(GantryAlarmError):
        session.jog_blocking(z=-1, jog_id="accepted-down")
    assert session._failed_jog_delta == {"x": 0, "y": 0, "z": -1}
    assert session._failed_jog_id == "accepted-down"
    assert session.limit_recovery_context().eligible
    with pytest.raises(GantryAlarmError):
        session.jog_blocking(z=-1, jog_id="queued-next")
    assert len(jogs(serial)) == 1
    assert not any(write in (b"$H\n", b"$X\n", b"\x18") for write in serial.writes)


@pytest.mark.parametrize("response", ["ALARM:3", "error:8", "[MSG:Other]", "[MSG:Check Limits extra]", ""])
def test_unaccepted_step_never_inherits_opposite_earlier_direction(runtime, response):
    session, _, mill = runtime
    serial = StepSerial(responses=(response,), positions=("<Alarm|WPos:10,20,30|Pn:Z>",))
    mill.ser_mill = serial
    session._last_jog_delta = {"x": 0, "y": 0, "z": 1}
    session._last_jog_id = "old-up"
    with pytest.raises((GantryAlarmError, CommandExecutionError)):
        session.jog_blocking(z=-1, jog_id="unknown-down")
    assert session._last_jog_id is session._failed_jog_id is None
    assert session._last_jog_delta is session._failed_jog_delta is None
    assert len(jogs(serial)) == 1


@pytest.mark.parametrize("queued", ["ok", "<Idle|WPos:10,20,29>"])
def test_preexisting_reply_cannot_ack_or_complete_new_step(runtime, queued):
    session, _, mill = runtime
    serial = StepSerial(responses=())
    serial.queue_line(queued)
    mill.ser_mill = serial
    with pytest.raises(JogAcceptanceUnknownError):
        session.jog_blocking(z=-1, jog_id="missing-own-ack")
    assert session._position_reference_untrusted
    assert len(jogs(serial)) == 1
    assert serial.writes.count(b"\x85") == 1


@pytest.mark.parametrize("pending", ["ALARM:3", "[MSG:Check Limits]", "error:9", "<Idle|WPos:10,20,30|Pn:Z>"])
def test_queued_fault_is_not_discarded_before_command(runtime, pending):
    session, _, mill = runtime
    serial = StepSerial()
    serial.queue_line(pending)
    mill.ser_mill = serial
    with pytest.raises(GantryAlarmError):
        session.jog_blocking(z=-1, jog_id="not-sent")
    assert not jogs(serial)


def test_stale_idle_does_not_finish_before_small_step_progress(runtime):
    session, _, mill = runtime
    serial = StepSerial(positions=("<Idle|WPos:10,20,30>", "<Idle|WPos:10,20,29.999>"))
    mill.ser_mill = serial
    result = session.jog_blocking(z=-0.001, jog_id="tiny-step")
    assert result.work_z == 29.999
    assert serial.writes.count(b"?") == 3
    assert session._last_jog_id is None
    assert len(jogs(serial)) == 1


def test_step_quantization_does_not_false_alarm_or_accept_early_idle(runtime):
    session, _, mill = runtime
    mill.config["$102"] = "250"
    serial = StepSerial(positions=("<Idle|WPos:10,20,30>", "<Idle|WPos:10,20,29.752>"))
    mill.ser_mill = serial
    result = session.jog_blocking(z=-0.25, jog_id="quantized-step")
    assert result.work_z == 29.752
    assert serial.writes.count(b"?") == 3


def test_smaller_than_one_controller_step_rejects_without_losing_reference(runtime):
    session, _, mill = runtime
    mill.config["$102"] = "250"
    serial = StepSerial()
    mill.ser_mill = serial
    with pytest.raises(ValueError, match="step resolution"):
        session.jog_blocking(z=-0.001, jog_id="no-controller-step")
    assert not jogs(serial)
    assert not session._position_reference_untrusted


def test_busy_preflight_sends_no_next_jog(runtime):
    session, _, mill = runtime
    serial = StepSerial()
    serial.status = "<Jog|WPos:10,20,29.624>"
    mill.ser_mill = serial
    with pytest.raises(GantrySessionError, match="verified Idle"):
        session.jog_blocking(z=-1, jog_id="would-queue")
    assert not jogs(serial)


def test_normal_jog_remains_strict_on_pre_ack_courtesy(runtime):
    _, _, mill = runtime
    serial = StepSerial(responses=("[MSG:Check Limits]", "ok"))
    mill.ser_mill = serial
    with pytest.raises(CommandExecutionError):
        mill.jog(z=-1)
    assert len(jogs(serial)) == 1
    assert serial.readline().strip() == b"ok"


def test_stop_during_buffer_fence_prevents_any_jog_write(runtime):
    session, _, mill = runtime
    serial = StepSerial()
    mill.ser_mill = serial
    original = mill._drain_calibration_jog_input
    calls = 0

    def cancel_on_command_fence():
        nonlocal calls
        calls += 1
        if calls == 2:
            serial.queue_line("ok")
            serial.on_read = session.jog_cancel_interrupt
        original()

    mill._drain_calibration_jog_input = cancel_on_command_fence
    with pytest.raises(GantryJogCancelledError):
        session.jog_blocking(z=-1, jog_id="stopped-before-write")
    assert not jogs(serial)
    assert not session._position_reference_untrusted


def test_actual_z_repeat_trace_keeps_current_owner_and_never_sends_a_next_step(runtime):
    session, _, mill = runtime
    serial = StepSerial(positions=(
        "<Jog|WPos:10,20,14.845>", "<Jog|WPos:10,20,14.065>",
        "<Alarm|WPos:10,20,14.065|Pn:Z>",
    ))
    serial.status = "<Idle|WPos:10,20,15.221>"
    mill.ser_mill = serial
    with pytest.raises(GantryAlarmError):
        session.jog_blocking(z=-1, jog_id="present-moving-step")
    context = session.limit_recovery_context()
    assert context.eligible
    assert context.failed_jog_id == "present-moving-step"
    assert context.failed_jog_delta == {"x": 0, "y": 0, "z": -1}
    assert len(jogs(serial)) == 1
    assert b"\x85" not in serial.writes


def test_courtesy_ack_then_healthy_idle_stays_faulted_without_auto_recovery(runtime):
    session, _, mill = runtime
    serial = StepSerial(responses=("[MSG:Check Limits]", "ok"))
    mill.ser_mill = serial
    with pytest.raises(GantryAlarmError, match="Check Limits"):
        session.jog_blocking(z=-1, jog_id="courtesy-step")
    assert session._failed_jog_id == "courtesy-step"
    context = session.limit_recovery_context()
    assert not context.eligible
    assert context.failed_jog_id is None
    assert session._position_reference_untrusted
    assert len(jogs(serial)) == 1


@pytest.mark.parametrize("prefix", [(), ("[MSG:Check Limits]",)])
def test_stale_buffered_ok_cannot_replace_missing_own_jog_ack(runtime, prefix):
    _, _, mill = runtime
    serial = StepSerial(responses=prefix)
    serial.queue_line("ok")
    mill.ser_mill = serial
    with pytest.raises(JogAcceptanceUnknownError):
        mill.jog(z=-1, calibration=True)
    assert len(jogs(serial)) == 1


@pytest.mark.parametrize("response", ["ALARM:3", "error:8", "[MSG:unrelated]"])
def test_courtesy_without_own_ack_or_with_terminal_failure_is_not_accepted(runtime, response):
    session, _, mill = runtime
    serial = StepSerial(responses=("[MSG:Check Limits]", response))
    mill.ser_mill = serial
    with pytest.raises((CommandExecutionError, GantryAlarmError)):
        session.jog_blocking(z=-1, jog_id="not-accepted")
    assert session._last_jog_id is session._failed_jog_id is None
    assert session._last_jog_delta is session._failed_jog_delta is None
    assert len(jogs(serial)) == 1


def test_post_ack_stale_idle_is_fenced_before_fresh_z_alarm(runtime):
    session, _, mill = runtime
    serial = StepSerial(responses=("ok", "<Idle|WPos:10,20,30>"), positions=("<Idle|WPos:10,20,29|Pn:Z>",))
    mill.ser_mill = serial
    with pytest.raises(GantryAlarmError):
        session.jog_blocking(z=-1, jog_id="z-current")
    assert session._failed_jog_id == "z-current"
    assert session.limit_recovery_context().eligible
    assert len(jogs(serial)) == 1


@pytest.mark.parametrize("endpoint", ["29.5", "31", "30"])
def test_jog_seen_then_wrong_endpoint_idle_cancels_once_and_blocks_followups(runtime, endpoint):
    session, _, mill = runtime
    serial = StepSerial(positions=("<Jog|WPos:10,20,29.9>", f"<Idle|WPos:10,20,{endpoint}>"))
    mill.ser_mill = serial
    with pytest.raises(GantrySessionError, match="Timed out"):
        session.jog_blocking(z=-1, jog_id="incomplete", timeout_s=0.005)
    assert serial.writes.count(b"\x85") == 1
    assert session._position_reference_untrusted
    assert session._last_jog_id is session._failed_jog_id is None
    with pytest.raises(CalibrationBlockedError):
        session.jog_blocking(z=-1, jog_id="after-timeout")
    assert len(jogs(serial)) == 1


def test_explicit_stop_during_motion_verifies_idle_without_forcing_home(runtime):
    session, _, mill = runtime
    serial = StepSerial(positions=("<Jog|WPos:10,20,29.5>",))
    mill.ser_mill = serial
    original_write = serial.write
    stopped = False

    def stop_on_probe(data):
        nonlocal stopped
        if data == b"?" and serial.step_started and not stopped:
            stopped = True
            serial.on_read = session.jog_cancel_interrupt
            serial.positions.clear()
        return original_write(data)

    serial.write = stop_on_probe
    with pytest.raises(GantryJogCancelledError):
        session.jog_blocking(z=-1, jog_id="released")
    assert not session._position_reference_untrusted
    assert session._last_jog_id is session._failed_jog_id is None
    assert serial.writes.count(b"\x85") == 1
    assert len(jogs(serial)) == 1


@pytest.mark.parametrize("stage", ["preflight", "ack", "probe"])
def test_connection_loss_propagates_identity_and_blocks_further_jogs(runtime, stage):
    session, gantry, mill = runtime
    serial = StepSerial()
    mill.ser_mill = serial
    failure = MillConnectionError("connection lost")
    if stage == "ack":
        gantry.jog_for_calibration = MagicMock(side_effect=failure)
    else:
        original = gantry.get_calibration_position_info
        calls = 0

        def read():
            nonlocal calls
            calls += 1
            if calls == (1 if stage == "preflight" else 2):
                raise failure
            return original()

        gantry.get_calibration_position_info = read
    with pytest.raises(MillConnectionError) as caught:
        session.jog_blocking(z=-1, jog_id="lost-connection")
    assert caught.value is failure
    assert session._position_reference_untrusted
    assert session._last_jog_id is session._failed_jog_id is None
    assert len(jogs(serial)) <= 1
    assert not any(write in (b"$H\n", b"$X\n", b"\x18") for write in serial.writes)


def test_queued_correlated_step_cancelled_before_lock_is_a_non_success(runtime):
    session, _, mill = runtime
    serial = StepSerial()
    mill.ser_mill = serial

    class CancelBeforeLock:
        def __enter__(self):
            session.jog_cancel_interrupt()

        def __exit__(self, *_):
            pass

    session._lock = CancelBeforeLock()
    with pytest.raises(GantryJogCancelledError, match="before it started"):
        session.jog_blocking(z=-1, jog_id="queued-then-stopped")
    assert not jogs(serial)
    assert not session._position_reference_untrusted


def test_offline_calibration_step_uses_same_displacement_contract():
    gantry = Gantry(offline=True)
    checked = MagicMock()
    gantry.jog_for_calibration(z=-0.25, check_cancelled=checked)
    assert gantry.get_calibration_position_info()["work_pos"]["z"] == -0.25
    checked.assert_called_once()


@pytest.mark.parametrize("kwargs", [{"timeout_s": 0}, {"timeout_s": float("nan")}, {"feed_rate": 0}, {"z": 0.0001}])
def test_invalid_step_parameters_reject_before_actuation_without_losing_reference(runtime, kwargs):
    session, _, mill = runtime
    serial = StepSerial()
    mill.ser_mill = serial
    with pytest.raises(ValueError):
        session.jog_blocking(**({"z": -1, "jog_id": "invalid"} | kwargs))
    assert not serial.writes
    assert not session._position_reference_untrusted


def test_missing_work_coordinates_and_unknown_step_resolution_cannot_start_motion(runtime):
    session, _, mill = runtime
    serial = StepSerial()
    serial.status = "<Idle|MPos:10,20,30>"
    mill.config.clear()
    mill.ser_mill = serial
    with pytest.raises(GantrySessionError, match="finite work coordinates"):
        session.jog_blocking(z=-1, jog_id="no-wpos")
    assert not jogs(serial)


@pytest.mark.parametrize("bad_input", [b"ok" * 3000, b"ok", b"\n" * 129])
def test_unbounded_or_incomplete_calibration_backlog_fails_before_jog(runtime, bad_input):
    _, _, mill = runtime
    serial = StepSerial()
    serial.queue(bad_input)
    mill.ser_mill = serial
    with pytest.raises(CommandExecutionError):
        mill.jog(z=-1, calibration=True)
    assert not jogs(serial)


def test_buffer_drain_transport_failure_is_not_hidden(runtime):
    import serial as pyserial

    _, _, mill = runtime
    serial = StepSerial()
    serial.queue_line("ok")
    serial.readline = MagicMock(side_effect=pyserial.SerialException("USB disconnected"))
    mill.ser_mill = serial
    with pytest.raises(MillConnectionError, match="USB disconnected"):
        mill.jog(z=-1, calibration=True)
    assert not jogs(serial)


def test_unknown_fresh_status_response_is_terminal_before_motion(runtime):
    session, _, mill = runtime
    serial = StepSerial()
    original_write = serial.write

    def write_unknown(data):
        if data == b"?":
            serial.writes.append(data)
            serial.queue_line("[MSG:unexpected]")
            return len(data)
        return original_write(data)

    serial.write = write_unknown
    mill.ser_mill = serial
    with pytest.raises(StatusReturnError, match="unexpected"):
        session.jog_blocking(z=-1, jog_id="unknown-status")
    assert not jogs(serial)


@pytest.mark.parametrize("failure_type", [MillConnectionError, StatusReturnError])
def test_cancel_verification_failure_never_leaves_a_usable_unverified_reference(runtime, failure_type):
    session, gantry, _ = runtime
    failure = failure_type("cancel status unavailable")
    def cancel_and_fail(**kwargs):
        session._cancel_jog_ownership()
        gantry.get_calibration_position_info = MagicMock(side_effect=failure)
        kwargs["check_cancelled"]()

    gantry.jog_for_calibration = cancel_and_fail
    gantry.get_calibration_position_info = MagicMock(return_value={
        "raw_status": "<Idle|WPos:10,20,30>", "work_pos": {"x": 10, "y": 20, "z": 30},
    })
    with pytest.raises((GantryJogCancelledError, failure_type)) as caught:
        session.jog_blocking(z=-1, jog_id="cancel-unverified")
    if failure_type is MillConnectionError:
        assert caught.value is failure
    assert session._position_reference_untrusted
    assert session._last_jog_id is session._failed_jog_id is None
