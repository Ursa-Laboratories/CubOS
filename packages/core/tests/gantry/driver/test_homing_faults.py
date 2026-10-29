"""Homing faults never start a second controller cycle."""

from unittest.mock import MagicMock

import pytest

from cubos.gantry.errors import CommandExecutionError, MillConnectionError, StatusReturnError
from cubos.gantry.gantry_driver.driver import Mill


@pytest.fixture(autouse=True)
def _mock_loggers(monkeypatch):
    monkeypatch.setattr("cubos.gantry.gantry_driver.driver.set_up_mill_logger", lambda _: MagicMock())
    monkeypatch.setattr("cubos.gantry.gantry_driver.driver.set_up_command_logger", lambda _: MagicMock())


@pytest.mark.parametrize(
    "status",
    ["<Idle|Pn:Z>", "<idle|Pn:XY>", "<Alarm|Pn:Z>", "<Hold:0|Pn:Z>", "error:9"],
)
def test_home_fault_does_not_mark_homed_or_restart(monkeypatch, status):
    monkeypatch.setattr("cubos.gantry.gantry_driver.driver.time.sleep", lambda _: None)
    mill = Mill()
    mill.homed = True
    mill.execute_command = MagicMock()
    mill.current_status = MagicMock(return_value=status)
    mill.soft_reset = MagicMock()
    mill.unlock = MagicMock()

    with pytest.raises(StatusReturnError):
        mill.home()

    assert not mill.homed
    mill.execute_command.assert_called_once_with("$H")
    mill.current_status.assert_called_once()
    mill.soft_reset.assert_not_called()
    mill.unlock.assert_not_called()


@pytest.mark.parametrize("stage", ["execute_command", "current_status"])
@pytest.mark.parametrize("error_type", [MillConnectionError, StatusReturnError, CommandExecutionError])
def test_home_propagates_failure_unchanged(monkeypatch, stage, error_type):
    monkeypatch.setattr("cubos.gantry.gantry_driver.driver.time.sleep", lambda _: None)
    mill = Mill()
    mill.homed = True
    mill.execute_command = MagicMock()
    mill.current_status = MagicMock(return_value="<Idle|WPos:0,0,0>")
    failure = error_type("controller stopped responding")
    getattr(mill, stage).side_effect = failure

    with pytest.raises(error_type) as caught:
        mill.home()

    assert caught.value is failure
    assert not mill.homed
    mill.execute_command.assert_called_once_with("$H")


def test_home_finishes_only_after_homing_and_idle_without_limit(monkeypatch):
    monkeypatch.setattr("cubos.gantry.gantry_driver.driver.time.sleep", lambda _: None)
    mill = Mill()
    mill.execute_command = MagicMock()
    mill.current_status = MagicMock(side_effect=["<Home|Pn:Z>", "<Idle|WPos:0,0,0>"])

    mill.home()

    assert mill.homed
    mill.execute_command.assert_called_once_with("$H")
    assert mill.current_status.call_count == 2


@pytest.mark.parametrize("operation", ["current_status", "current_coordinates"])
def test_check_limits_is_terminal_and_does_not_consume_following_idle(monkeypatch, operation):
    monkeypatch.setattr("cubos.gantry.gantry_driver.driver.time.sleep", lambda _: None)
    mill = Mill()
    mill.ser_mill = MagicMock(is_open=True)
    mill.ser_mill.readline = MagicMock(side_effect=[b"[MSG:Check Limits]\n", b"<Idle|WPos:0,0,0>\n", b"ok\n"])

    with pytest.raises((StatusReturnError, CommandExecutionError), match="[Cc]heck [Ll]imits"):
        getattr(mill, operation)()

    assert mill.ser_mill.readline.call_count == 1
    assert "Check Limits" in mill.last_status


def test_homing_command_rejects_check_limits_without_retry(monkeypatch):
    monkeypatch.setattr("cubos.gantry.gantry_driver.driver.time.sleep", lambda _: None)
    mill = Mill()
    mill.ser_mill = MagicMock(is_open=True)
    mill.ser_mill.readline.return_value = b"[MSG:Check Limits]\n"

    with pytest.raises(CommandExecutionError, match="check limits"):
        mill.home()

    mill.ser_mill.write.assert_called_once_with(b"$H\n")
    assert not mill.homed


@pytest.mark.parametrize("reject_jog", [False, True])
def test_guarded_pull_off_models_check_limits_then_ok_and_requires_actual_jog_ack(monkeypatch, reject_jog):
    from cubos.gantry.gantry import Gantry
    from cubos.gantry.limit_recovery import recover_from_limit_alarm

    class ActiveSwitchSerial:
        is_open = True
        in_waiting = 0

        def __init__(self):
            self.lines = []
            self.writes = []
            self.jog_sent = False

        def write(self, value):
            self.writes.append(value)
            if value == b"$X\n":
                self.lines.extend([b"[MSG:Check Limits]\n", b"ok\n"])
            elif value == b"?":
                self.lines.append(b"<Idle|WPos:0,0,0>\n" if self.jog_sent else b"<Idle|WPos:0,0,0|Pn:Z>\n")
            elif value.startswith(b"$J="):
                self.jog_sent = True
                self.lines.append(b"error:9\n" if reject_jog else b"ok\n")
            return len(value)

        def reset_input_buffer(self):
            self.lines.clear()

        def readline(self):
            return self.lines.pop(0) if self.lines else b""

    monkeypatch.setattr("cubos.gantry.gantry_driver.driver.time.sleep", lambda _: None)
    gantry = Gantry()
    mill = gantry._mill
    serial = ActiveSwitchSerial()
    mill.ser_mill = serial

    def recover():
        return recover_from_limit_alarm(
            gantry, {"z": -1}, pull_off_mm=5, feed_rate=100,
            output=lambda _: None, confirmed_limit_axis="z",
        )

    if reject_jog:
        with pytest.raises(CommandExecutionError, match="error:9"):
            recover()
    else:
        result = recover()
        assert result.attempts == 1
        assert result.final_status.startswith("<Idle|")
        assert "Pn:" not in result.final_status

    assert serial.writes.count(b"\x18") == 1
    assert serial.writes.count(b"$X\n") == 1
    assert serial.writes.count(b"$J=G91 Z5.000 F100\n") == 1
    assert b"$H\n" not in serial.writes


@pytest.mark.parametrize("deadline_expires", [False, True])
def test_continuous_reset_output_stops_at_budget_without_unlock_or_retry(monkeypatch, deadline_expires):
    monkeypatch.setattr("cubos.gantry.gantry_driver.driver.time.sleep", lambda _: None)
    if deadline_expires:
        monkeypatch.setattr("cubos.gantry.gantry_driver.driver.time.monotonic", iter([0, 0, 2.1]).__next__)
    else:
        monkeypatch.setattr("cubos.gantry.gantry_driver.driver.time.monotonic", lambda: 0)
    mill = Mill()
    mill.ser_mill = MagicMock(is_open=True, in_waiting=1)
    mill.ser_mill.readline.return_value = b"[MSG:Check Limits]\n"
    mill.unlock = MagicMock()
    mill.reconnect = MagicMock()

    with pytest.raises(CommandExecutionError, match="did not settle"):
        mill.soft_reset_and_unlock()

    assert mill.ser_mill.readline.call_count == (1 if deadline_expires else 32)
    mill.ser_mill.write.assert_called_once_with(b"\x18")
    mill.unlock.assert_not_called()
    mill.reconnect.assert_not_called()


class HomingStatusSerial:
    is_open = True

    def __init__(self, reports):
        self.reports = list(reports)
        self.lines = []
        self.writes = []

    def write(self, value):
        self.writes.append(value)
        if value == b"$H\n":
            self.lines.append(b"ok\n")
        elif value == b"?":
            report = self.reports.pop(0) if self.reports else ""
            if isinstance(report, Exception):
                raise report
            self.lines.append((report + "\n").encode())
        else:
            raise AssertionError(f"Unexpected actuation: {value!r}")
        return len(value)

    def reset_input_buffer(self):
        self.lines.clear()

    def readline(self):
        return self.lines.pop(0) if self.lines else b""


def test_homing_missing_frames_then_home_idle_polls_without_resending_home(monkeypatch):
    monkeypatch.setattr("cubos.gantry.gantry_driver.driver.time.sleep", lambda _: None)
    mill = Mill()
    serial = HomingStatusSerial([""] * 5 + ["<Home|Pn:Z>", "<Idle|WPos:0,0,0>"])
    mill.ser_mill = serial

    mill.home(timeout=90)

    assert mill.homed
    assert serial.writes == [b"$H\n"] + [b"?"] * 7


@pytest.mark.parametrize("report", ["ALARM:1", "error:9", "[MSG:Check Limits]", "<Alarm|Pn:Z>", "<Idle|Pn:Z>", MillConnectionError("USB disconnected")])
def test_homing_missing_frames_do_not_retry_terminal_fault(monkeypatch, report):
    monkeypatch.setattr("cubos.gantry.gantry_driver.driver.time.sleep", lambda _: None)
    mill = Mill()
    serial = HomingStatusSerial([""] * 5 + [report, "<Idle|WPos:0,0,0>"])
    mill.ser_mill = serial
    expected_error = MillConnectionError if isinstance(report, MillConnectionError) else StatusReturnError

    with pytest.raises(expected_error):
        mill.home(timeout=90)

    assert not mill.homed
    assert serial.writes == [b"$H\n"] + [b"?"] * 6
    assert serial.reports == ["<Idle|WPos:0,0,0>"]


def test_homing_missing_frames_keep_original_deadline_and_never_claim_motion_stopped(monkeypatch):
    monkeypatch.setattr("cubos.gantry.gantry_driver.driver.time.sleep", lambda _: None)
    monkeypatch.setattr("cubos.gantry.gantry_driver.driver.time.time", iter([0, 0, 2]).__next__)
    mill = Mill()
    serial = HomingStatusSerial([""] * 10)
    mill.ser_mill = serial

    with pytest.raises(StatusReturnError, match="may still be moving"):
        mill.home(timeout=1)

    assert not mill.homed
    assert serial.writes == [b"$H\n"] + [b"?"] * 5


def test_no_status_frame_has_distinct_timeout_type(monkeypatch):
    from cubos.gantry.errors import StatusResponseTimeoutError

    monkeypatch.setattr("cubos.gantry.gantry_driver.driver.time.sleep", lambda _: None)
    mill = Mill()
    mill.ser_mill = HomingStatusSerial([""] * 5)

    with pytest.raises(StatusResponseTimeoutError):
        mill.current_status()


def test_idle_arriving_after_overall_deadline_does_not_restart_verification(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("cubos.gantry.gantry_driver.driver.time.sleep", lambda _: None)
    monkeypatch.setattr("cubos.gantry.gantry_driver.driver.time.time", lambda: clock[0])

    class LateIdleSerial(HomingStatusSerial):
        def write(self, value):
            result = super().write(value)
            if value == b"?":
                clock[0] = 2.0
            return result

    mill = Mill()
    serial = LateIdleSerial(["<Idle|WPos:0,0,0>"])
    mill.ser_mill = serial

    with pytest.raises(StatusReturnError, match="completion did not verify"):
        mill.home(timeout=1)

    assert not mill.homed
    assert serial.writes == [b"$H\n", b"?"]


def test_unlock_consumes_check_limits_through_ack_without_extra_actuation():
    mill = Mill()
    mill.ser_mill = HomingStatusSerial([])
    mill.ser_mill.write = MagicMock(side_effect=lambda value: mill.ser_mill.writes.append(value))
    mill.ser_mill.lines = [b"[MSG:Check Limits]\n", b"ok\n", b"<Idle|WPos:0,0,0>\n"]

    mill.unlock()

    assert mill.ser_mill.writes == [b"$X\n"]
    assert mill.ser_mill.lines == [b"<Idle|WPos:0,0,0>\n"]
    assert mill.last_status == "[MSG:Check Limits]"


@pytest.mark.parametrize("terminal", [b"ALARM:1\n", b"error:9\n", b"<Alarm|Pn:Y>\n"])
def test_unlock_check_limits_warning_does_not_hide_terminal_fault(terminal):
    mill = Mill()
    mill.ser_mill = HomingStatusSerial([])
    mill.ser_mill.write = MagicMock(side_effect=lambda value: mill.ser_mill.writes.append(value))
    mill.ser_mill.lines = [b"[MSG:Check Limits]\n", terminal, b"ok\n"]

    with pytest.raises(CommandExecutionError):
        mill.unlock()

    assert mill.ser_mill.writes == [b"$X\n"]
    assert mill.ser_mill.lines == [b"ok\n"]


def test_settings_read_skips_legacy_leftover_unlock_ok_without_resending():
    from tests.gantry.fake_serial import FakeGrblSerial

    mill = Mill()
    mill.ser_mill = FakeGrblSerial(chunks=[b"ok\n"], settings={"$20": "1", "$21": "1"})

    assert mill.read_grbl_settings() == {"$20": "1", "$21": "1"}
    assert mill.ser_mill.writes == [b"$$\n"]


@pytest.mark.parametrize("lines", [[b"ok\n"], [b"ok\n", b"$20=1\n"], [b"$20=1\n", b"ALARM:1\n"], [b"[MSG:Check Limits]\n", b"ok\n"], [b"$20=\n", b"ok\n"]])
def test_unverified_settings_block_raises_and_preserves_config(monkeypatch, lines):
    monkeypatch.setattr("cubos.gantry.gantry_driver.driver.time.time", lambda: 0)
    mill = Mill()
    mill.config = {"$20": "0", "$21": "1"}
    mill.ser_mill = HomingStatusSerial([])
    mill.ser_mill.write = MagicMock(side_effect=lambda value: mill.ser_mill.writes.append(value))
    mill.ser_mill.lines = list(lines)

    with pytest.raises(CommandExecutionError):
        mill.read_grbl_settings()

    assert mill.config == {"$20": "0", "$21": "1"}
    assert mill.ser_mill.writes == [b"$$\n"]


@pytest.mark.parametrize("reports,expected_pin", [(["<Idle|WPos:1,2,3>", "<Idle|WPos:1,2,3>"], None), (["<Idle|WPos:1,2,3|Pn:Y>"], "Y"), (["<Idle|WPos:1,2,3>", "<Idle|WPos:1,2,3|Pn:Y>"], "Y"), (["<Alarm|WPos:1,2,3>"], "Alarm")])
def test_session_unlock_verifies_fresh_state_after_check_limits_ack(monkeypatch, reports, expected_pin):
    from cubos.gantry.gantry import Gantry
    from cubos.gantry.session import GantryAlarmError, GantrySession

    class UnlockSerial(HomingStatusSerial):
        def write(self, value):
            if value == b"$X\n":
                self.writes.append(value)
                self.lines.extend([b"[MSG:Check Limits]\n", b"ok\n"])
                return len(value)
            return super().write(value)

    monkeypatch.setattr("cubos.gantry.gantry_driver.driver.time.sleep", lambda _: None)
    gantry = Gantry()
    serial = UnlockSerial(reports)
    gantry._mill.ser_mill = serial
    session = GantrySession()
    session._gantry = gantry
    session._latch_alarm_locked("ALARM:3")

    if expected_pin:
        with pytest.raises(GantryAlarmError):
            session.unlock()
        assert session._alarm_status is not None
    else:
        snapshot = session.unlock()
        assert snapshot.status == "Home required"
        assert snapshot.work_x is snapshot.work_y is snapshot.work_z is None
        assert session._alarm_status is None

    assert serial.writes.count(b"$X\n") == 1
    assert all(value in (b"$X\n", b"?") for value in serial.writes)


@pytest.mark.parametrize("operation", ["get_recovery_status", "get_recovery_position_info"])
def test_scoped_recovery_read_skips_only_courtesy_message_and_returns_fresh_y_pin(monkeypatch, operation):
    from cubos.gantry.gantry import Gantry

    monkeypatch.setattr("cubos.gantry.gantry_driver.driver.time.sleep", lambda _: None)
    gantry = Gantry()
    serial = HomingStatusSerial(["[MSG:Check Limits]"])
    def respond(value):
        serial.writes.append(value)
        serial.lines.extend([b"[MSG:Check Limits]\n", b"<Idle|WPos:1,2,3|Pn:Y>\n"])
    serial.write = MagicMock(side_effect=respond)
    gantry._mill.ser_mill = serial

    result = getattr(gantry, operation)()

    raw = result if isinstance(result, str) else result["raw_status"]
    assert raw == "<Idle|WPos:1,2,3|Pn:Y>"
    if isinstance(result, dict):
        assert result["work_pos"] == {"x": 1, "y": 2, "z": 3}
    assert serial.writes == [b"?"]


@pytest.mark.parametrize("operation", ["get_recovery_status", "get_recovery_position_info"])
@pytest.mark.parametrize("fault", ["ALARM:1", "error:9", "[MSG:Check Limits] unexpected"])
def test_scoped_recovery_read_does_not_hide_actual_fault_after_courtesy(monkeypatch, operation, fault):
    from cubos.gantry.gantry import Gantry

    monkeypatch.setattr("cubos.gantry.gantry_driver.driver.time.sleep", lambda _: None)
    gantry = Gantry()
    serial = HomingStatusSerial([])
    def respond(value):
        serial.writes.append(value)
        serial.lines.extend([b"[MSG:Check Limits]\n", (fault + "\n").encode(), b"<Idle|WPos:1,2,3>\n"])
    serial.write = MagicMock(side_effect=respond)
    gantry._mill.ser_mill = serial

    with pytest.raises(StatusReturnError):
        getattr(gantry, operation)()

    assert serial.lines == [b"<Idle|WPos:1,2,3>\n"]
    assert serial.writes == [b"?"]


@pytest.mark.parametrize("operation", ["get_recovery_status", "get_recovery_position_info"])
def test_scoped_recovery_read_connection_loss_propagates_unchanged(operation):
    from cubos.gantry.gantry import Gantry

    gantry = Gantry()
    failure = MillConnectionError("USB disconnected")
    gantry._mill._write_serial = MagicMock(side_effect=failure)
    gantry._mill.ser_mill = MagicMock(is_open=True)

    with pytest.raises(MillConnectionError) as caught:
        getattr(gantry, operation)()

    assert caught.value is failure


def test_recovery_status_courtesy_stream_is_bounded_without_actuation(monkeypatch):
    from cubos.gantry.errors import StatusResponseTimeoutError

    monkeypatch.setattr("cubos.gantry.gantry_driver.driver.time.sleep", lambda _: None)
    mill = Mill()
    mill.ser_mill = MagicMock(is_open=True)
    mill.ser_mill.readline.return_value = b"[MSG:Check Limits]\n"

    with pytest.raises(StatusResponseTimeoutError):
        mill.current_status(recovery=True)

    assert mill.ser_mill.readline.call_count == 50
    assert mill.ser_mill.write.call_args_list == [((b"?",),)] * 5


@pytest.mark.parametrize("fault", [None, "rejected_jog", "new_pin_at_final_position"])
def test_manual_y_recovery_full_serial_sequence_preserves_real_faults(monkeypatch, fault):
    from cubos.gantry.gantry import Gantry
    from cubos.gantry.session import GantryAlarmError, GantrySession

    class ManualYSerial(HomingStatusSerial):
        reset_done = False
        moved = False
        queries = 0

        @property
        def in_waiting(self):
            return sum(len(line) for line in self.lines)

        def write(self, value):
            self.writes.append(value)
            if value == b"?":
                self.queries += 1
                if not self.reset_done:
                    report = "<Alarm|WPos:10,20,30|Pn:Y>"
                elif not self.moved:
                    report = "<Idle|WPos:10,20,30|Pn:Y>"
                elif fault == "new_pin_at_final_position" and self.queries == 6:
                    report = "<Idle|WPos:10,21,30|Pn:Y>"
                else:
                    report = "<Idle|WPos:10,21,30>"
                self.lines.extend([b"[MSG:Check Limits]\n", (report + "\n").encode()])
            elif value == b"\x18":
                self.reset_done = True
                self.lines.extend([b"Grbl 1.1h\n", b"[MSG:Check Limits]\n"])
            elif value == b"$X\n":
                self.lines.extend([b"[MSG:Check Limits]\n", b"ok\n"])
            elif value.startswith(b"$J="):
                self.moved = fault != "rejected_jog"
                self.lines.append(b"error:9\n" if fault == "rejected_jog" else b"ok\n")
            elif value != b"\x85":
                raise AssertionError(f"Unexpected actuation: {value!r}")
            return len(value)

    monkeypatch.setattr("cubos.gantry.gantry_driver.driver.time.sleep", lambda _: None)
    gantry = Gantry()
    serial = ManualYSerial([])
    gantry._mill.ser_mill = serial
    session = GantrySession()
    session._gantry = gantry
    session._latch_alarm_locked("ALARM:1")

    def recover():
        return session.recover_calibration_limit_manual(axis="y", away_direction=1, operator_confirmed=True)

    if fault:
        with pytest.raises(CommandExecutionError if fault == "rejected_jog" else GantryAlarmError):
            recover()
        assert session._alarm_status is not None
    else:
        result, _ = recover()
        assert result.mode == "manual"
        assert result.failed_delta is None
        assert result.commanded_delta == {"x": 0, "y": 1, "z": 0}
        assert session._alarm_status is None
        assert session._position_from_cache_with_status("Idle").status == "Home required"

    assert serial.writes.count(b"\x18") == 1
    assert serial.writes.count(b"$X\n") == 1
    assert [value for value in serial.writes if value.startswith(b"$J=")] == [b"$J=G91 Y1.000 F100.0\n"]
    assert all(value in (b"?", b"\x18", b"$X\n", b"\x85", b"$J=G91 Y1.000 F100.0\n") for value in serial.writes)


@pytest.mark.parametrize("operation", ["get_recovery_status", "get_recovery_position_info"])
def test_recovery_query_discards_seeded_old_idle_and_wrong_pin_before_live_reply(monkeypatch, operation):
    from cubos.gantry.gantry import Gantry

    monkeypatch.setattr("cubos.gantry.gantry_driver.driver.time.sleep", lambda _: None)
    gantry = Gantry()
    serial = HomingStatusSerial(["<Alarm|WPos:1,2,3|Pn:Y>"])
    serial.lines = [b"<Idle|WPos:0,0,0>\n", b"<Alarm|WPos:9,9,9|Pn:X>\n"]
    gantry._mill.ser_mill = serial

    result = getattr(gantry, operation)()

    raw = result if isinstance(result, str) else result["raw_status"]
    assert raw == "<Alarm|WPos:1,2,3|Pn:Y>"
    assert serial.writes == [b"?"]
    if isinstance(result, dict):
        assert result["work_pos"] == {"x": 1, "y": 2, "z": 3}


@pytest.mark.parametrize("continuous_new_output", [False, True])
def test_soft_reset_discards_old_courtesy_backlog_but_bounds_new_output(monkeypatch, continuous_new_output):
    class ResetSerial(HomingStatusSerial):
        new_output = False
        resets = 0
        reads = 0

        @property
        def in_waiting(self):
            return 1 if self.new_output and continuous_new_output else sum(len(line) for line in self.lines)

        def reset_input_buffer(self):
            self.resets += 1
            super().reset_input_buffer()

        def write(self, value):
            assert value == b"\x18"
            self.writes.append(value)
            self.new_output = True
            self.lines.append(b"Grbl 1.1h\n")
            return len(value)

        def readline(self):
            self.reads += 1
            return b"[MSG:Check Limits]\n" if continuous_new_output else super().readline()

    monkeypatch.setattr("cubos.gantry.gantry_driver.driver.time.sleep", lambda _: None)
    monkeypatch.setattr("cubos.gantry.gantry_driver.driver.time.monotonic", lambda: 0)
    mill = Mill()
    serial = ResetSerial([])
    serial.lines = [b"[MSG:Check Limits]\n"] * 100
    mill.ser_mill = serial

    if continuous_new_output:
        with pytest.raises(CommandExecutionError, match="did not settle"):
            mill.soft_reset()
        assert serial.reads == 32
    else:
        mill.soft_reset()
        assert serial.reads == 1
    assert serial.resets == 1
    assert serial.writes == [b"\x18"]


@pytest.mark.parametrize("operation", ["get_recovery_status", "get_recovery_position_info", "soft_reset"])
def test_recovery_input_buffer_failure_is_connection_loss_before_any_write(operation):
    from cubos.gantry.gantry import Gantry

    gantry = Gantry()
    gantry._mill.ser_mill = MagicMock(is_open=True)
    gantry._mill.ser_mill.reset_input_buffer.side_effect = OSError("device disconnected")
    target = gantry._mill if operation == "soft_reset" else gantry
    with pytest.raises(MillConnectionError, match="discard stale recovery input"):
        getattr(target, operation)()
    gantry._mill.ser_mill.write.assert_not_called()


def test_actual_driver_connect_on_pressed_y_reaches_manual_context_without_actuation(monkeypatch):
    from cubos.gantry.gantry import Gantry
    from cubos.gantry.session import GantryAlarmError, GantrySession
    from tests.gantry.fake_serial import FakeGrblSerial

    class PressedPort(FakeGrblSerial):
        def write(self, value):
            if value == b"?":
                self.writes.append(value)
                self.queue_line("[MSG:Check Limits]")
                self.queue_line("<Alarm|WPos:10,20,30|Pn:Y>")
                return len(value)
            return super().write(value)

    monkeypatch.setattr("cubos.gantry.gantry_driver.driver.time.sleep", lambda _: None)
    pressed_serial = PressedPort()

    def factory(config=None):
        gantry = Gantry(config=config)
        gantry._mill._locate_over_serial = lambda port=None: (pressed_serial, "/dev/test")
        return gantry

    session = GantrySession(gantry_factory=factory, sleep=lambda _: None)
    snapshot = session.connect(filename="pressed-y")

    assert snapshot.connected
    assert snapshot.work_x is snapshot.work_y is snapshot.work_z is None
    context = session.limit_recovery_context()
    assert context.manual_available
    assert context.active_limit_axes == ["y"]
    assert not context.eligible
    with pytest.raises(GantryAlarmError):
        session.jog(y=1)
    assert pressed_serial.is_open
    assert pressed_serial.writes and all(value == b"?" for value in pressed_serial.writes)


OBSERVED_ARM32_RESET_LINES = (
    '',
    "Grbl 1.1f ['$' for help]",
    '',
    'Grbl for ARM32',
    'Version:ARM32 V3.8',
    '$0=10 (step pulse,usec)',
    '$1=25 (step idle delay,msec)',
    '$2=0 (stepport invert mask)',
    '$3=4 (dirport invert mask)',
    '$4=0 (stepenable invert,bool)',
    '$5=1 (lims pin invert,bool)',
    '$6=1 (probe pin invert,bool)',
    '$10=0 (status report mask)',
    '$11=0.010 (junction deviation)',
    '$12=0.002 (arc tolerance,mm)',
    '$13=0 (report inches,bool)',
    '$20=0 (soft limits,bool)',
    '$21=1 (hard limits,bool)',
    '$22=1 (home cycle,bool)',
    '$23=0 (homing dir invert mask)',
    '$24=100.000 (homing feed,mm/min)',
    '$25=500.000 (homing seek,mm/min)',
    '$26=250 (homing debounce,msec)',
    '$27=1.000 (homing pull-off,mm)',
    '$30=10000 (maximum spindle speed,rpm)',
    '$31=0 (minimum spindle speed,rpm)',
    '$32=0 (laser mode enable,bool)',
    '$100=800.000 (X axis pulse:step/mm)',
    '$101=800.000 (Y axis pulse:step/mm)',
    '$102=800.000 (Z axis pulse:step/mm)',
    '$103=177.777 (A axis pulse:step/mm)',
    '$110=2000.000 (X axis max rata:mm/min)',
)


COMPLETE_ARM32_BOOT_LINES = (
    '',
    "Grbl 1.1f ['$' for help]",
    '',
    'Grbl for ARM32',
    'Version:ARM32 V3.8',
    '$0=10 (step pulse,usec)',
    '$1=25 (step idle delay,msec)',
    '$2=0 (stepport invert mask)',
    '$3=4 (dirport invert mask)',
    '$4=0 (stepenable invert,bool)',
    '$5=1 (lims pin invert,bool)',
    '$6=1 (probe pin invert,bool)',
    '$10=0 (status report mask)',
    '$11=0.010 (junction deviation)',
    '$12=0.002 (arc tolerance,mm)',
    '$13=0 (report inches,bool)',
    '$20=1 (soft limits,bool)',
    '$21=1 (hard limits,bool)',
    '$22=1 (home cycle,bool)',
    '$23=0 (homing dir invert mask)',
    '$24=100.000 (homing feed,mm/min)',
    '$25=500.000 (homing seek,mm/min)',
    '$26=250 (homing debounce,msec)',
    '$27=1.000 (homing pull-off,mm)',
    '$30=10000 (maximum spindle speed,rpm)',
    '$31=0 (minimum spindle speed,rpm)',
    '$32=0 (laser mode enable,bool)',
    '$100=800.000 (X axis pulse:step/mm)',
    '$101=800.000 (Y axis pulse:step/mm)',
    '$102=800.000 (Z axis pulse:step/mm)',
    '$103=177.777 (A axis pulse:step/mm)',
    '$110=2000.000 (X axis max rata:mm/min)',
    '$111=2000.000 (Y axis max rata:mm/min)',
    '$112=2000.000 (Z axis max rata:mm/min)',
    '$113=1000.000 (A axis max rata:mm/min)',
    '$120=20.000 (X axis acceleration:mm/s^2)',
    '$121=20.000 (Y axis acceleration:mm/s^2)',
    '$122=20.000 (Z axis acceleration:mm/s^2)',
    '$123=20.000 (A axis acceleration:mm/s^2)',
    '$130=406.879 (X aixs max travel:mm)',
    '$131=400.730 (Y aixs max travel:mm)',
    '$132=81.000 (Z aixs max travel:mm)',
    '$133=9999.000 (A aixs max travel:mm)',
    '[MSG:Check Limits]',
    "[MSG:'$H'|'$X' to unlock]",
    'ok',
)


@pytest.mark.parametrize("startup_banner", [b"Grbl 1.1h ['$' for help]\n", b"\nGrbl 1.1f ['$' for help]\n\nGrbl for ARM32\nVersion:ARM32 V3.8\n$20=1\nok\n", ("\n".join(OBSERVED_ARM32_RESET_LINES) + "\n").encode(), ("\n".join(COMPLETE_ARM32_BOOT_LINES) + "\n").encode()], ids=["standard", "arm32", "observed-settings", "complete-observed-boot"])
@pytest.mark.parametrize("fault", [None, "reset_error", "reset_alarm8", "reset_wrong_pin", "reset_unknown_banner", "reset_other_arm", "reset_version_without_arm_banner", "reset_unknown_arm_version", "reset_settings_without_arm_banner", "reset_settings_without_version", "reset_malformed_boot_setting", "reset_unterminated_description", "reset_bad_register", "reset_unqualified_ok", "reset_arm32_ok_without_settings", "reset_tail_error", "reset_tail_unknown_version", "reset_tail_malformed_setting", "reset_tail_unrecognized_text", "before_unlock_wrong_pin", "before_unlock_running", "before_unlock_error", "before_unlock_invalid", "before_unlock_unknown_text", "unlock_error", "unlock_no_ack", "after_unlock_wrong_pin"])
def test_guarded_reset_accepts_continuous_expected_notices_only_with_fresh_gates(monkeypatch, fault, startup_banner):
    from cubos.gantry.gantry import Gantry
    from cubos.gantry.session import GantrySession

    class NoticeStream(HomingStatusSerial):
        reset_started = False
        unlocked = False
        moved = False
        queries = 0
        dump_tail_validated = False
        tail_present_at_query = False

        @property
        def in_waiting(self):
            return sum(len(line) for line in self.lines) or int(self.reset_started)

        def write(self, value):
            self.writes.append(value)
            if value == b"?":
                if any(line.startswith(b"$111=") for line in self.lines):
                    self.tail_present_at_query = True
                self.queries += 1
                if not self.reset_started:
                    report = "<Alarm|WPos:200,400.730,89.479|Pn:Y>"
                elif not self.unlocked:
                    report = {
                        "before_unlock_wrong_pin": "<Alarm|Pn:X>",
                        "before_unlock_running": "<Run|Pn:Y>",
                        "before_unlock_error": "error:9",
                        "before_unlock_invalid": "<Unknown|Pn:Y>",
                        "before_unlock_unknown_text": "unexpected startup output",
                    }.get(fault, "<Alarm|WPos:200,400.730,89.479|Pn:Y>")
                elif not self.moved:
                    report = "<Idle|Pn:X>" if fault == "after_unlock_wrong_pin" else "<Idle|WPos:200,400.730,89.479|Pn:Y>"
                else:
                    report = "<Idle|WPos:200,399.730,89.479>"
                self.lines.extend([b"[MSG:Check Limits]\n", (report + "\n").encode()])
            elif value == b"\x18":
                self.reset_started = True
                first = {
                    "reset_error": b"error:9\n",
                    "reset_alarm8": b"ALARM:8\n",
                    "reset_wrong_pin": b"<Alarm|Pn:X>\n",
                    "reset_unknown_banner": b"Grbl for ARM32 unexpected\n",
                    "reset_other_arm": b"Grbl for ARM64\n",
                    "reset_version_without_arm_banner": b"Version:ARM32 V3.8\n",
                    "reset_unknown_arm_version": b"Grbl for ARM32\nVersion:ARM32 V3.9\n",
                    "reset_settings_without_arm_banner": b"$20=1 (boot data)\n",
                    "reset_settings_without_version": b"Grbl for ARM32\n$20=1\n",
                    "reset_malformed_boot_setting": b"Grbl for ARM32\nVersion:ARM32 V3.8\n$20=nan\n",
                    "reset_unterminated_description": b"Grbl for ARM32\nVersion:ARM32 V3.8\n$0=10 (unclosed\n",
                    "reset_bad_register": b"Grbl for ARM32\nVersion:ARM32 V3.8\n$foo=1\n",
                    "reset_unqualified_ok": b"ok\n",
                    "reset_arm32_ok_without_settings": b"Grbl for ARM32\nVersion:ARM32 V3.8\nok\n",
                }.get(fault, startup_banner)
                if fault and fault.startswith("reset_tail_"):
                    first = ("\n".join(OBSERVED_ARM32_RESET_LINES) + "\n").encode()
                self.lines.extend(first.splitlines(keepends=True))
                tail_fault = {
                    "reset_tail_error": b"error:9\n",
                    "reset_tail_unknown_version": b"Version:ARM32 V3.9\n",
                    "reset_tail_malformed_setting": b"$111=nan\n",
                    "reset_tail_unrecognized_text": b"unexpected startup output\n",
                }.get(fault)
                if tail_fault:
                    self.lines.append(tail_fault)
                if len(first.splitlines()) == 32:
                    self.lines.extend([b"$111=1 (synthetic unread startup tail)\n", b"$133=1 (synthetic unread startup tail)\n"])
                if len(first.splitlines()) == 32:
                    self.lines.extend([b"[MSG:Check Limits]\n", b"[MSG:'$H'|'$X' to unlock]\n", b"ok\n"])
                elif first != ("\n".join(COMPLETE_ARM32_BOOT_LINES) + "\n").encode():
                    self.lines.extend([b"[MSG:'$H'|'$X' to unlock]\n", b"ALARM:3\n"])
            elif value == b"$X\n":
                self.unlocked = fault != "unlock_error"
                self.lines.append(b"[MSG:Check Limits]\n")
                if fault != "unlock_no_ack":
                    self.lines.append(b"error:9\n" if fault == "unlock_error" else b"ok\n")
            elif value.startswith(b"$J="):
                self.moved = True
                self.lines.extend([b"[MSG:Check Limits]\n", b"ok\n"])
            elif value != b"\x85":
                raise AssertionError(f"Unexpected actuation: {value!r}")
            return len(value)

        def readline(self):
            line = self.lines.pop(0) if self.lines else b"[MSG:Check Limits]\n"
            if line.startswith(b"$111="):
                self.dump_tail_validated = True
            return line

    monkeypatch.setattr("cubos.gantry.gantry_driver.driver.time.sleep", lambda _: None)
    gantry = Gantry()
    gantry._mill.config = {"$20": "0", "$21": "1"}
    serial = NoticeStream([])
    gantry._mill.ser_mill = serial
    session = GantrySession()
    session._gantry = gantry
    session._latch_alarm_locked("ALARM:1")

    def recover():
        return session.recover_calibration_limit_manual(axis="y", away_direction=-1, operator_confirmed=True)

    if fault:
        with pytest.raises((CommandExecutionError, StatusReturnError)):
            recover()
        assert not any(value.startswith(b"$J=") for value in serial.writes)
        assert session._alarm_status is not None
    else:
        result, messages = recover()
        assert result.mode == "manual"
        assert result.commanded_delta == {"x": 0, "y": -1, "z": 0}
        assert result.failed_delta is None
        for banner_line in startup_banner.decode().splitlines():
            if banner_line.strip():
                assert any(banner_line in message for message in messages)
        if len(startup_banner.splitlines()) < 32:
            assert any("ALARM:3" in message for message in messages)
            assert any("Check Limits" in message for message in messages)
        elif len(startup_banner.splitlines()) == 32:
            assert serial.dump_tail_validated
            assert not serial.tail_present_at_query
        if b"Grbl for ARM32" in startup_banner:
            assert "Reset notice: ok" in messages
        assert gantry._mill.config == {"$20": "0", "$21": "1"}
        assert any("Pre-unlock status: <Alarm" in message for message in messages)
        assert any("Before pull-off: <Idle" in message for message in messages)
        assert [value for value in serial.writes if value.startswith(b"$J=")] == [b"$J=G91 Y-1.000 F100.0\n"]
        assert session._position_from_cache_with_status("Idle").status == "Home required"
    assert serial.writes.count(b"\x18") == 1
    should_unlock = fault is None or fault in ("unlock_error", "unlock_no_ack", "after_unlock_wrong_pin")
    assert serial.writes.count(b"$X\n") == int(should_unlock)
    assert all(value in (b"?", b"\x18", b"$X\n", b"\x85", b"$J=G91 Y-1.000 F100.0\n") for value in serial.writes)


@pytest.mark.parametrize("cancel_stage", ["after_reset", "after_pre_unlock_query", "after_unlock"])
def test_guarded_reset_cancellation_prevents_later_actuation(monkeypatch, cancel_stage):
    from cubos.gantry.gantry import Gantry

    monkeypatch.setattr("cubos.gantry.gantry_driver.driver.time.sleep", lambda _: None)
    gantry = Gantry()
    gantry._mill.soft_reset = MagicMock(return_value=["[MSG:Check Limits]"])
    gantry.get_recovery_status = MagicMock(return_value="<Alarm|Pn:Y>")
    gantry._mill.unlock = MagicMock()
    stages = iter(["after_reset", "after_pre_unlock_query", "after_unlock"])

    def cancelled():
        if next(stages) == cancel_stage:
            raise CommandExecutionError("Recovery cancelled")

    with pytest.raises(CommandExecutionError, match="cancelled"):
        gantry.reset_and_unlock_for_limit_recovery(axis="y", check_cancelled=cancelled)

    gantry._mill.soft_reset.assert_called_once_with(recovery_axis="y")
    assert gantry.get_recovery_status.call_count == (0 if cancel_stage == "after_reset" else 1)
    assert gantry._mill.unlock.call_count == int(cancel_stage == "after_unlock")


@pytest.mark.parametrize("failure", ["oversized", "incomplete", "deadline", "line_budget"])
def test_unvalidated_buffered_reset_tail_blocks_status_query_before_unlock(monkeypatch, failure):
    mill = Mill()
    mill.ser_mill = MagicMock(is_open=True)
    mill.ser_mill.in_waiting = 16385 if failure == "oversized" else 16384 if failure == "line_budget" else 10
    mill.ser_mill.readline.return_value = b"$20=1" if failure == "incomplete" else b"\n"
    mill._guarded_reset_tail = ("y", ["Grbl for ARM32", "Version:ARM32 V3.8"])
    monkeypatch.setattr("cubos.gantry.gantry_driver.driver.time.monotonic", iter([0, 3]).__next__ if failure == "deadline" else lambda: 0)

    with pytest.raises(CommandExecutionError, match="reset output"):
        mill.current_status(recovery=True)

    mill.ser_mill.write.assert_not_called()


@pytest.mark.parametrize("notices", [[], ["Grbl for ARM32"], ["Grbl for ARM32", "Version:ARM32 V3.8"], ["Grbl for ARM32", "Version:ARM32 V3.8", "$20=nan"]])
def test_boot_ok_requires_identified_arm32_and_valid_numeric_startup_data(notices):
    mill = Mill()
    with pytest.raises(CommandExecutionError, match="Unexpected guarded reset response: ok"):
        mill._record_guarded_reset_notice("ok", "y", list(notices))


def test_missing_boot_completion_blocks_query_even_if_frame_would_precede_boot_ok(monkeypatch):
    class DelayedBootOk(HomingStatusSerial):
        @property
        def in_waiting(self):
            return sum(len(line) for line in self.lines)

        def write(self, value):
            self.writes.append(value)
            if value == b"\x18":
                self.lines.extend([(line + "\n").encode() for line in COMPLETE_ARM32_BOOT_LINES[:-1]])
            elif value == b"?":
                self.lines.extend([b"<Alarm|Pn:Y>\n", b"ok\n"])
            return len(value)

    monkeypatch.setattr("cubos.gantry.gantry_driver.driver.time.sleep", lambda _: None)
    mill = Mill()
    serial = DelayedBootOk([])
    mill.ser_mill = serial
    mill.soft_reset(recovery_axis="y")

    with pytest.raises(CommandExecutionError, match="startup completion was not verified"):
        mill.current_status(recovery=True)

    assert serial.writes == [b"\x18"]


def test_startup_frame_before_boot_ok_cannot_replace_fresh_post_completion_query(monkeypatch):
    class EarlyFrame(HomingStatusSerial):
        tail_supplied = False
        boot_ok_read = False

        @property
        def in_waiting(self):
            return sum(len(line) for line in self.lines)

        def write(self, value):
            self.writes.append(value)
            if value == b"\x18":
                self.lines.extend([(line + "\n").encode() for line in COMPLETE_ARM32_BOOT_LINES[:-1]])
            elif value == b"?":
                assert self.boot_ok_read
                self.lines.append(b"<Alarm|Pn:X>\n")
            return len(value)

        def readline(self):
            if not self.lines and not self.tail_supplied:
                self.tail_supplied = True
                self.lines.extend([b"<Alarm|Pn:Y>\n", b"ok\n"])
            line = super().readline()
            self.boot_ok_read = self.boot_ok_read or line == b"ok\n"
            return line

    from cubos.gantry.gantry import Gantry
    monkeypatch.setattr("cubos.gantry.gantry_driver.driver.time.sleep", lambda _: None)
    gantry = Gantry()
    serial = EarlyFrame([])
    gantry._mill.ser_mill = serial

    with pytest.raises(StatusReturnError, match="did not verify before unlock"):
        gantry.reset_and_unlock_for_limit_recovery(axis="y")

    assert serial.boot_ok_read
    assert serial.writes == [b"\x18", b"?"]


@pytest.mark.parametrize("fresh_pin", ["Y", "X"])
@pytest.mark.parametrize("boot_ok_before_frame", [False, True])
def test_late_arm32_identity_requires_boot_completion_and_new_query_before_unlock(monkeypatch, fresh_pin, boot_ok_before_frame):
    from cubos.gantry.gantry import Gantry
    from cubos.gantry.session import GantrySession

    class LateIdentity(HomingStatusSerial):
        reset_started = False
        unlocked = False
        queries = 0
        boot_ok_read = False

        @property
        def in_waiting(self):
            return sum(len(line) for line in self.lines)

        def write(self, value):
            self.writes.append(value)
            if value == b"\x18":
                self.reset_started = True
            elif value == b"?":
                self.queries += 1
                if not self.reset_started:
                    self.lines.append(b"<Alarm|WPos:200,400.730,89.479|Pn:Y>\n")
                elif self.queries == 2:
                    self.lines.extend([b"Grbl for ARM32\n", b"Version:ARM32 V3.8\n", b"$20=1\n"])
                    self.lines.extend([b"ok\n", b"<Alarm|Pn:Y>\n"] if boot_ok_before_frame else [b"<Alarm|Pn:Y>\n", b"ok\n"])
                elif not self.unlocked:
                    assert self.boot_ok_read
                    self.lines.append(f"<Alarm|Pn:{fresh_pin}>\n".encode())
                else:
                    self.lines.append(b"<Idle|WPos:200,400.730,89.479|Pn:Y>\n")
            elif value == b"$X\n":
                assert self.boot_ok_read
                self.unlocked = True
                self.lines.append(b"[MSG:Check Limits]\n")
            elif value.startswith(b"$J="):
                self.lines.append(b"ok\n")
            elif value != b"\x85":
                raise AssertionError(f"Unexpected actuation: {value!r}")
            return len(value)

        def readline(self):
            line = super().readline()
            self.boot_ok_read = self.boot_ok_read or line == b"ok\n"
            return line

    monkeypatch.setattr("cubos.gantry.gantry_driver.driver.time.sleep", lambda _: None)
    gantry = Gantry()
    serial = LateIdentity([])
    gantry._mill.ser_mill = serial
    session = GantrySession()
    session._gantry = gantry
    session._latch_alarm_locked("ALARM:1")

    with pytest.raises((CommandExecutionError, StatusReturnError)):
        session.recover_calibration_limit_manual(axis="y", away_direction=-1, operator_confirmed=True)

    assert serial.queries == 3
    assert serial.boot_ok_read
    assert serial.writes.count(b"\x18") == 1
    assert serial.writes.count(b"$X\n") == int(fresh_pin == "Y")
    assert not any(value.startswith(b"$J=") for value in serial.writes)


@pytest.mark.parametrize("reply", [["[MSG:Check Limits]", "ok"], ["[MSG:Check Limits]"], ["[MSG:Check Limits]"] * 40, ["[MSG:Check Limits]", "error:9"], ["[MSG:Check Limits]", "ALARM:1"], ["[MSG:Check Limits]", "<Alarm|Pn:Y>"], ["[MSG:Check Limits]", "[MSG:other]"], ["[MSG:Check Limits] trailing", "ok"], ["[MSG:Check Limits]", "<Jog|Pn:Y>"]])
def test_verified_recovery_jog_requires_own_ack_after_exact_courtesy_only(reply):
    class JogAckSerial(HomingStatusSerial):
        @property
        def in_waiting(self):
            return sum(len(line) for line in self.lines)

        def write(self, value):
            self.writes.append(value)
            self.lines.extend([(line + "\n").encode() for line in reply])
            return len(value)

    mill = Mill()
    serial = JogAckSerial([])
    mill.ser_mill = serial
    if reply == ["[MSG:Check Limits]", "ok"]:
        mill.jog(y=-5, feed_rate=100, recovery_axis="y")
    else:
        with pytest.raises(CommandExecutionError):
            mill.jog(y=-5, feed_rate=100, recovery_axis="y")
    assert serial.writes == [b"$J=G91 Y-5.000 F100\n"]


def test_normal_jog_still_rejects_courtesy_before_ack_without_using_later_ok():
    mill = Mill()
    mill.ser_mill = HomingStatusSerial([])
    mill.ser_mill.lines = [b"[MSG:Check Limits]\n", b"ok\n"]
    mill.ser_mill.write = MagicMock()
    with pytest.raises(CommandExecutionError, match="check limits"):
        mill.jog(y=0.25, feed_rate=100)
    assert mill.ser_mill.lines == [b"ok\n"]
    mill.ser_mill.write.assert_called_once_with(b"$J=G91 Y0.250 F100\n")


def test_buffered_old_ok_cannot_acknowledge_a_missing_recovery_jog_reply():
    class OldAckSerial(HomingStatusSerial):
        @property
        def in_waiting(self):
            return sum(len(line) for line in self.lines)

        def write(self, value):
            self.writes.append(value)
            self.lines.append(b"[MSG:Check Limits]\n")
            return len(value)

    from cubos.gantry.errors import JogAcceptanceUnknownError
    mill = Mill()
    serial = OldAckSerial([])
    serial.lines = [b"ok\n"]
    mill.ser_mill = serial
    with pytest.raises(JogAcceptanceUnknownError):
        mill.jog(y=-1, feed_rate=100, recovery_axis="y")
    assert serial.writes == [b"$J=G91 Y-1.000 F100\n"]


@pytest.mark.parametrize("queued", ["error:9", "ALARM:1", "<Alarm|Pn:Y>", "<Idle|Pn:X>", "<Idle>", "[MSG:unknown]"])
def test_recovery_jog_does_not_discard_buffered_fault_or_unknown_input(queued):
    class BufferedSerial(HomingStatusSerial):
        @property
        def in_waiting(self):
            return sum(len(line) for line in self.lines)

    mill = Mill()
    serial = BufferedSerial([])
    serial.lines = [(queued + "\n").encode()]
    mill.ser_mill = serial
    with pytest.raises(CommandExecutionError):
        mill.jog(y=-1, feed_rate=100, recovery_axis="y")
    assert not serial.writes


@pytest.mark.parametrize("failure", ["oversized", "incomplete", "deadline", "line_budget", "connection"])
def test_recovery_jog_buffer_validation_is_bounded_before_command(monkeypatch, failure):
    mill = Mill()
    mill.ser_mill = MagicMock(is_open=True)
    mill.ser_mill.in_waiting = 4097 if failure == "oversized" else 4096 if failure == "line_budget" else 5
    mill.ser_mill.readline.return_value = b"ok" if failure == "incomplete" else b"\n"
    if failure == "connection":
        mill.ser_mill.readline.side_effect = OSError("USB disconnected")
    monkeypatch.setattr("cubos.gantry.gantry_driver.driver.time.monotonic", iter([0, 3]).__next__ if failure == "deadline" else lambda: 0)
    with pytest.raises(MillConnectionError if failure == "connection" else CommandExecutionError):
        mill.jog(y=-1, feed_rate=100, recovery_axis="y")
    mill.ser_mill.write.assert_not_called()


def test_recovery_jog_ack_deadline_cannot_resend_command(monkeypatch):
    from cubos.gantry.errors import JogAcceptanceUnknownError
    mill = Mill()
    mill.ser_mill = MagicMock(is_open=True, in_waiting=0)
    monkeypatch.setattr("cubos.gantry.gantry_driver.driver.time.monotonic", iter([0, 0, 3]).__next__)
    with pytest.raises(JogAcceptanceUnknownError, match="own ok"):
        mill.jog(y=-1, feed_rate=100, recovery_axis="y")
    mill.ser_mill.write.assert_called_once_with(b"$J=G91 Y-1.000 F100\n")


@pytest.mark.parametrize("kwargs", [{"y": -2, "feed_rate": 100, "recovery_axis": "y"}, {"y": -1, "feed_rate": 800, "recovery_axis": "y"}, {"y": -1, "feed_rate": 100, "recovery_axis": "x"}])
def test_recovery_jog_cannot_change_fixed_distance_speed_or_axis(kwargs):
    mill = Mill()
    mill.ser_mill = MagicMock(is_open=True)
    with pytest.raises(ValueError):
        mill.jog(**kwargs)
    mill.ser_mill.write.assert_not_called()


@pytest.mark.parametrize("stage", ["before_buffer", "after_buffer", "awaiting_ack"])
def test_recovery_jog_cancel_checks_prevent_new_or_repeated_commands(stage):
    mill = Mill()
    mill.ser_mill = MagicMock(is_open=True, in_waiting=0)
    mill._read_serial = MagicMock(return_value="ok")
    checks = iter(["before_buffer", "after_buffer", "awaiting_ack"])

    def cancelled():
        if next(checks) == stage:
            raise CommandExecutionError("Recovery cancelled")

    with pytest.raises(CommandExecutionError, match="cancelled"):
        mill.jog(y=-1, feed_rate=100, recovery_axis="y", check_cancelled=cancelled)
    assert mill.ser_mill.write.call_count == int(stage == "awaiting_ack")


def test_recovery_jog_public_wrapper_uses_bounded_offline_move():
    from cubos.gantry.gantry import Gantry
    gantry = Gantry(offline=True)
    gantry.jog_for_limit_recovery(y=-1, feed_rate=100)
    assert gantry.get_coordinates() == {"x": 0, "y": -1, "z": 0}


def test_recovery_jog_public_wrapper_rejects_multiple_axes_before_driver_call():
    from cubos.gantry.gantry import Gantry
    gantry = Gantry()
    gantry._mill.jog = MagicMock()
    with pytest.raises(ValueError, match="one axis"):
        gantry.jog_for_limit_recovery(x=1, y=1, feed_rate=100)
    gantry._mill.jog.assert_not_called()


def test_stop_during_buffered_recovery_read_prevents_jog_after_drain():
    stopped = False

    class StopOnRead(HomingStatusSerial):
        @property
        def in_waiting(self):
            return sum(len(line) for line in self.lines)

        def readline(self):
            nonlocal stopped
            stopped = True
            return super().readline()

    mill = Mill()
    serial = StopOnRead([])
    serial.lines = [b"[MSG:Check Limits]\n"]
    mill.ser_mill = serial

    def check_cancelled():
        if stopped:
            raise CommandExecutionError("Stopped during input validation")

    with pytest.raises(CommandExecutionError, match="Stopped during input validation"):
        mill.jog(y=-1, feed_rate=100, recovery_axis="y", check_cancelled=check_cancelled)
    assert stopped
    assert not serial.writes


def test_recovery_jog_cancel_is_rechecked_after_prewrite_logging():
    stopped = False
    mill = Mill()
    mill.ser_mill = MagicMock(is_open=True, in_waiting=0)

    def stop_while_logging(*args):
        nonlocal stopped
        stopped = True

    def check_cancelled():
        if stopped:
            raise CommandExecutionError("Stopped before command write")

    mill.logger.debug = MagicMock(side_effect=stop_while_logging)
    with pytest.raises(CommandExecutionError, match="Stopped before command write"):
        mill.jog(y=-1, feed_rate=100, recovery_axis="y", check_cancelled=check_cancelled)
    mill.ser_mill.write.assert_not_called()
