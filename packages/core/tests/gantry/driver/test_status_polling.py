"""Offline regression tests for GRBL realtime status polling."""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from cubos.gantry.gantry_driver import driver as driver_module
from cubos.gantry.gantry_driver.driver import Mill
from cubos.gantry.gantry_driver.exceptions import (
    MillConnectionError,
    StatusReturnError,
)
from tests.gantry.fake_serial import FakeGrblSerial


IDLE = "<Idle|WPos:0.000,0.000,0.000|WCO:0.000,0.000,0.000|FS:0,0>"
RUN = "<Run|WPos:0.000,0.000,0.000|FS:0,0>"
HOLD = "<Hold:0|WPos:0.000,0.000,0.000|FS:0,0>"
ALARM = "<Alarm|WPos:0.000,0.000,0.000|FS:0,0>"


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@contextmanager
def use_clock(clock):
    # Patch only within the test: driver.time is the shared stdlib time module.
    with patch.object(driver_module.time, "monotonic", clock.monotonic), patch.object(
        driver_module.time, "sleep", clock.advance
    ):
        yield


class PollingSerial(FakeGrblSerial):
    """Serial fake that scripts each status response and records event order."""

    def __init__(self, clock, *, status_responses=None, command_lines=None, **kwargs):
        super().__init__(**kwargs)
        self.clock = clock
        self.status_responses = list(status_responses or [])
        self.command_lines = command_lines or {}
        self.events = []
        self.query_times = []
        self.read_count = 0
        self.write_error = None
        self.read_error = None
        self.response_delay = 0.0
        self.pending_response_delay = 0.0

    def write(self, data):
        self.events.append(("write", data, self.clock.now))
        if self.write_error:
            raise self.write_error
        if data == b"?":
            self.writes.append(data)
            self.query_times.append(self.clock.now)
            self.pending_response_delay = self.response_delay
            responses = self.status_responses.pop(0) if self.status_responses else []
            for line in responses:
                self.queue_line(line)
            return len(data)
        if data in (b"!", b"~", b"\x85", b"\x18"):
            return super().write(data)
        command = data.decode("ascii", errors="ignore").strip()
        if command in self.command_lines:
            self.writes.append(data)
            for line in self.command_lines[command]:
                self.queue_line(line)
            return len(data)
        return super().write(data)

    def readline(self):
        self.events.append(("read", None, self.clock.now))
        if self.read_error:
            raise self.read_error
        self.read_count += 1
        if not self._rx:
            self.clock.advance(self.timeout or 0.0)
            return b""
        if self.pending_response_delay:
            self.clock.advance(self.pending_response_delay)
            self.pending_response_delay = 0.0
        return super().readline()


def make_mill(fake):
    with patch.object(driver_module, "set_up_mill_logger", return_value=MagicMock()), patch.object(
        driver_module, "set_up_command_logger", return_value=MagicMock()
    ):
        mill = Mill()
    mill.ser_mill = fake
    return mill


def test_first_status_query_is_immediate_and_written_before_read():
    clock = FakeClock()
    fake = PollingSerial(clock, status_responses=[[IDLE]], timeout=0.4)
    mill = make_mill(fake)

    with use_clock(clock):
        assert mill.current_status() == IDLE

    assert fake.query_times == [0.0]
    assert fake.events[:2] == [("write", b"?", 0.0), ("read", None, 0.0)]
    assert fake.timeout == 0.4


def test_repeated_calls_keep_five_hz_cadence_per_mill():
    clock = FakeClock()
    fake = PollingSerial(clock, status_responses=[[IDLE]] * 3)
    mill = make_mill(fake)

    with use_clock(clock):
        assert mill.current_status() == IDLE
        assert mill.current_status() == IDLE
        assert mill.current_status() == IDLE

    assert fake.query_times[0] == 0.0
    assert all(b - a >= 0.2 for a, b in zip(fake.query_times, fake.query_times[1:]))


def test_time_spent_waiting_for_response_counts_toward_next_interval():
    clock = FakeClock()
    fake = PollingSerial(clock, status_responses=[[IDLE], [IDLE]])
    fake.response_delay = 0.25
    mill = make_mill(fake)

    with use_clock(clock):
        assert mill.current_status() == IDLE
        assert mill.current_status() == IDLE

    assert fake.query_times == [0.0, 0.25]


def test_reinitializing_mill_resets_status_query_cadence():
    clock = FakeClock()
    fake = PollingSerial(clock, status_responses=[[IDLE], [IDLE]])
    mill = make_mill(fake)

    with use_clock(clock):
        assert mill.current_status() == IDLE
        clock.advance(0.01)
        with patch.object(driver_module, "set_up_command_logger", return_value=MagicMock()):
            mill._init_state()
        assert mill.current_status() == IDLE

    assert fake.query_times == [0.0, 0.01]


def test_silence_and_noise_are_bounded_by_query_and_line_limits():
    clock = FakeClock()
    noise = [f"[MSG:noise {i}]" for i in range(10)]
    fake = PollingSerial(
        clock,
        status_responses=[noise] * 5,
        timeout=0.01,
    )
    fake.readlines = MagicMock(
        side_effect=AssertionError("status polling must not drain readlines")
    )
    mill = make_mill(fake)

    with use_clock(clock):
        try:
            mill.current_status()
        except StatusReturnError:
            pass
        else:
            raise AssertionError("noise must not be accepted as a status report")

    assert len(fake.query_times) == 5
    assert fake.query_times == pytest.approx([0.0, 0.2, 0.4, 0.6, 0.8])
    assert fake.read_count <= 50
    fake.readlines.assert_not_called()


def test_all_silent_queries_are_bounded_and_preserve_timeout():
    clock = FakeClock()
    fake = PollingSerial(clock, status_responses=[[]] * 5, timeout=0.37)
    fake.readlines = MagicMock(
        side_effect=AssertionError("status polling must not drain readlines")
    )
    mill = make_mill(fake)

    with use_clock(clock), pytest.raises(StatusReturnError):
        mill.current_status()

    assert len(fake.query_times) == 5
    assert fake.query_times == pytest.approx([0.0, 0.37, 0.74, 1.11, 1.48])
    assert fake.read_count <= 50
    assert fake.timeout == 0.37
    fake.readlines.assert_not_called()


def test_ack_and_info_lines_are_skipped_until_status_frame():
    clock = FakeClock()
    fake = PollingSerial(clock, status_responses=[["ok", "[MSG:hello]", IDLE]])
    mill = make_mill(fake)

    with use_clock(clock):
        assert mill.current_status() == IDLE

    assert len(fake.query_times) == 1


def test_command_info_reply_does_not_complete_move_before_idle_frame():
    clock = FakeClock()
    fake = PollingSerial(
        clock,
        command_lines={"G1 X1": ["[MSG:Not idle yet]"]},
        status_responses=[[IDLE]],
    )
    mill = make_mill(fake)

    with use_clock(clock):
        result = mill.execute_command("G1 X1")

    assert result == IDLE
    assert fake.query_times == [0.0]
    assert fake.writes[:2] == [b"G1 X1\n", b"?"]


def test_hold_does_not_satisfy_idle_wait():
    clock = FakeClock()
    fake = PollingSerial(clock, status_responses=[[RUN], [IDLE]])
    mill = make_mill(fake)

    with use_clock(clock):
        result = mill._wait_until_idle(HOLD, timeout=2)

    assert result == IDLE
    assert len(fake.query_times) == 2


def test_status_frames_are_returned_verbatim_and_error_line_is_not_hidden():
    clock = FakeClock()
    fake = PollingSerial(clock, status_responses=[[HOLD], [ALARM], ["error:9", IDLE]])
    mill = make_mill(fake)

    with use_clock(clock):
        assert mill.current_status() == HOLD
        assert mill.current_status() == ALARM
        with pytest.raises(StatusReturnError, match="error:9"):
            mill.current_status()


def test_alarm_line_before_idle_raises_and_leaves_idle_unread():
    clock = FakeClock()
    fake = PollingSerial(clock, status_responses=[["ALARM:1", IDLE]])
    mill = make_mill(fake)

    with use_clock(clock), pytest.raises(StatusReturnError, match="ALARM:1"):
        mill.current_status()

    assert fake.in_waiting > 0
    assert len(fake.query_times) == 1


def test_alarm_status_fails_idle_wait():
    clock = FakeClock()
    mill = make_mill(PollingSerial(clock))

    with use_clock(clock):
        try:
            mill._wait_until_idle(ALARM)
        except StatusReturnError as exc:
            assert ALARM in str(exc)
        else:
            raise AssertionError("Alarm must fail an idle wait")


def test_serial_write_and_read_disconnects_propagate_as_connection_errors():
    for failure in ("write", "read"):
        clock = FakeClock()
        fake = PollingSerial(clock, status_responses=[[IDLE]])
        disconnect = MillConnectionError(f"{failure} disconnected")
        setattr(fake, f"{failure}_error", disconnect)
        mill = make_mill(fake)

        with use_clock(clock), pytest.raises(MillConnectionError) as raised:
            mill.current_status()
        assert raised.value is disconnect


def test_partial_poll_interval_and_separate_mill_cadence():
    clock = FakeClock()
    first_serial = PollingSerial(clock, status_responses=[[IDLE], [IDLE]])
    second_serial = PollingSerial(clock, status_responses=[[IDLE]])
    first_mill = make_mill(first_serial)
    second_mill = make_mill(second_serial)

    with use_clock(clock):
        assert first_mill.current_status() == IDLE
        clock.advance(0.075)
        assert second_mill.current_status() == IDLE
        assert second_serial.query_times == [0.075]
        assert first_mill.current_status() == IDLE

    assert first_serial.query_times == pytest.approx([0.0, 0.2])
    assert second_serial.query_times == [0.075]


def test_realtime_feed_hold_bypasses_active_status_poll_interval():
    clock = FakeClock()
    fake = PollingSerial(clock, status_responses=[[IDLE]])
    mill = make_mill(fake)

    with use_clock(clock):
        assert mill.current_status() == IDLE
        clock.advance(0.075)
        before_hold = clock.now
        mill.feed_hold_realtime()

    assert fake.writes == [b"?", b"!"]
    assert fake.query_times == [0.0]
    assert fake.events[-1] == ("write", b"!", before_hold)
    assert clock.now == before_hold
