from unittest.mock import MagicMock

import pytest
import serial

from cubos.gantry.gantry_driver.driver import Mill
from tests.gantry.fake_serial import FakeGrblSerial


@pytest.fixture
def mill(monkeypatch):
    monkeypatch.setattr("cubos.gantry.gantry_driver.driver.time.sleep", lambda _: None)
    monkeypatch.setattr("cubos.gantry.gantry_driver.driver.set_up_mill_logger", MagicMock())
    monkeypatch.setattr("cubos.gantry.gantry_driver.driver.set_up_command_logger", MagicMock())
    return Mill()


@pytest.mark.parametrize("line,expected", [(b"[MSG:Check Limits]\r\n", True), (b"noise\r\n", False)])
def test_probe_finishes_when_serial_output_never_goes_quiet(mill, line, expected):
    connection = FakeGrblSerial(timeout=2)
    connection.readlines = MagicMock(side_effect=AssertionError("unbounded drain"))
    connection.readline = MagicMock(return_value=line)

    assert mill._verify_connection(connection) is expected
    assert connection.timeout == 2
    assert connection.readline.call_count < 100
    assert b"$X\n" not in connection.writes
    assert b"$H\n" not in connection.writes


def test_probe_restores_serial_timeout_when_read_fails(mill):
    connection = FakeGrblSerial(timeout=2)
    connection.readline = MagicMock(side_effect=serial.SerialException("device removed"))
    with pytest.raises(serial.SerialException, match="device removed"):
        mill._verify_connection(connection)
    assert connection.timeout == 2


def test_probe_consumes_settings_after_an_earlier_acknowledgment(mill):
    class DelayedAcknowledgment(FakeGrblSerial):
        def write(self, data):
            if data == b"?":
                self.queue_line("ok")
            return super().write(data)

    connection = DelayedAcknowledgment()
    assert mill._verify_connection(connection)
    assert connection.in_waiting == 0


def test_limit_warning_connection_skips_controller_setup(mill, monkeypatch):
    connection = FakeGrblSerial(status="[MSG:Check Limits]")
    monkeypatch.setattr(mill, "_locate_over_serial", lambda _: (connection, connection.port))
    mill.read_config = MagicMock()
    mill.enforce_wpos_mode = MagicMock()
    mill.set_feed_rate = MagicMock()
    assert mill.connect(connection.port) is connection
    mill.read_config.assert_not_called()
    mill.enforce_wpos_mode.assert_not_called()
    mill.set_feed_rate.assert_not_called()
    assert connection.writes == [b"?"]
