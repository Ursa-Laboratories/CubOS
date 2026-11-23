"""The automatic Home write gate runs inside the serial write lock."""
from unittest.mock import MagicMock

import pytest

from cubos.gantry.errors import StatusReturnError
from cubos.gantry.gantry import Gantry
from cubos.gantry.gantry_driver.driver import Mill
from cubos.gantry.session import GantryJogCancelledError
from tests.gantry.fake_serial import FakeGrblSerial


@pytest.fixture
def mill(monkeypatch):
    monkeypatch.setattr("cubos.gantry.gantry_driver.driver.set_up_mill_logger", lambda _: MagicMock())
    monkeypatch.setattr("cubos.gantry.gantry_driver.driver.set_up_command_logger", lambda _: MagicMock())
    monkeypatch.setattr("cubos.gantry.gantry_driver.driver.time.sleep", lambda _: None)
    mill = Mill()
    mill.ser_mill = FakeGrblSerial()
    return mill


def test_cancel_while_waiting_for_serial_write_lock_prevents_home(mill):
    cancelled = False

    class CancelBeforeLockAcquired:
        def __enter__(self):
            nonlocal cancelled
            cancelled = True
        def __exit__(self, *_): pass

    def check_cancelled():
        if cancelled: raise GantryJogCancelledError("Stop preceded the Home write")

    mill._write_lock = CancelBeforeLockAcquired()
    with pytest.raises(GantryJogCancelledError): mill.home(check_cancelled=check_cancelled)
    assert mill.ser_mill.writes == []


def test_guarded_home_never_retries_error22_or_restores_feed(mill):
    serial = mill.ser_mill
    original = serial.write

    def reject_home(data):
        if data == b"$H\n":
            serial.writes.append(data)
            serial.queue_line("error:22")
            return len(data)
        return original(data)

    serial.write = reject_home
    mill.set_feed_rate = MagicMock()
    mill.current_status = MagicMock()
    with pytest.raises(StatusReturnError): mill.home(check_cancelled=lambda: None)
    assert serial.writes == [b"$H\n"]
    mill.set_feed_rate.assert_not_called()
    mill.current_status.assert_not_called()


def test_gantry_guard_reaches_one_home_write_and_verifies_completion(mill):
    gantry = Gantry(offline=True)
    gantry._offline, gantry._mill = False, mill
    mill.current_status = MagicMock(return_value="<Idle|WPos:300,200,80>")
    checked = MagicMock()
    gantry.home(check_cancelled=checked)
    assert mill.ser_mill.writes == [b"$H\n"]
    assert mill.homed
    assert checked.call_count >= 1


def test_offline_guarded_home_still_honors_cancellation_gate():
    gantry = Gantry(offline=True)
    callback = MagicMock()
    gantry.home(check_cancelled=callback)
    callback.assert_called_once()
