"""DuetDriver (RepRapFirmware) driver-contract tests against FakeDuetSerial."""

from __future__ import annotations

import pytest
import serial

from cubos.gantry.gantry_driver import duet_driver as duet_module
from cubos.gantry.gantry_driver.duet_driver import DuetDriver
from cubos.gantry.errors import (
    CommandExecutionError,
    LocationNotFound,
    MillConnectionError,
    StatusReturnError,
)

from ..fake_serial import FakeDuetSerial


@pytest.fixture(autouse=True)
def _fast_sleep(monkeypatch):
    monkeypatch.setattr(duet_module.time, "sleep", lambda *_: None)


def make_driver(tmp_path, fake: FakeDuetSerial) -> DuetDriver:
    driver = DuetDriver(log_dir=tmp_path)
    driver.ser_mill = fake
    driver.active_connection = True
    driver.port = fake.port
    return driver


def sent_commands(fake: FakeDuetSerial) -> list[str]:
    return [w.decode("ascii", errors="ignore").strip() for w in fake.writes]


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------


def test_connect_verifies_identity_and_initializes(tmp_path, monkeypatch):
    fake = FakeDuetSerial()
    monkeypatch.setattr(
        duet_module.serial, "Serial", lambda *args, **kwargs: fake
    )
    driver = DuetDriver(log_dir=tmp_path)
    driver.connect(port="/dev/fake-duet")

    assert driver.active_connection
    assert driver.is_connected()
    assert driver.connected_port() == "/dev/fake-duet"
    assert "RepRapFirmware" in driver.config["firmware_info"]
    assert "G90" in sent_commands(fake)


def test_connect_halted_board_skips_setup(tmp_path, monkeypatch):
    fake = FakeDuetSerial(status="halted")
    monkeypatch.setattr(
        duet_module.serial, "Serial", lambda *args, **kwargs: fake
    )
    driver = DuetDriver(log_dir=tmp_path)
    driver.connect(port="/dev/fake-duet")

    assert driver.active_connection
    assert "Alarm" in driver.last_status
    assert "G90" not in sent_commands(fake)


def test_connect_rejects_non_duet_device(tmp_path, monkeypatch):
    fake = FakeDuetSerial(identity="Grbl 1.1h ['$' for help]")
    monkeypatch.setattr(
        duet_module.serial, "Serial", lambda *args, **kwargs: fake
    )
    driver = DuetDriver(log_dir=tmp_path)
    with pytest.raises(MillConnectionError):
        driver.connect(port="/dev/fake-duet")


# ---------------------------------------------------------------------------
# Status / position
# ---------------------------------------------------------------------------


def test_current_status_synthesizes_grbl_frame(tmp_path):
    fake = FakeDuetSerial(position=(1.0, 2.0, 3.0))
    driver = make_driver(tmp_path, fake)
    status = driver.current_status()
    assert status == "<Idle|WPos:1.000,2.000,3.000>"
    assert driver.last_status == status


def test_current_status_maps_halted_to_alarm(tmp_path):
    fake = FakeDuetSerial(status="halted")
    driver = make_driver(tmp_path, fake)
    assert driver.current_status().startswith("<Alarm|")


def test_current_status_maps_paused_to_hold(tmp_path):
    fake = FakeDuetSerial(status="paused")
    driver = make_driver(tmp_path, fake)
    assert driver.current_status().startswith("<Hold:0|")


def test_current_coordinates_rounds_and_updates_status(tmp_path):
    fake = FakeDuetSerial(position=(1.23456, 2.0, 3.5))
    driver = make_driver(tmp_path, fake)
    coords = driver.current_coordinates()
    assert (coords.x, coords.y, coords.z) == (1.235, 2.0, 3.5)
    assert "WPos:1.235,2.000,3.500" in driver.last_status


def test_current_coordinates_raises_location_not_found(tmp_path, monkeypatch):
    fake = FakeDuetSerial()
    monkeypatch.setattr(fake, "_axes_payload", lambda: [])
    driver = make_driver(tmp_path, fake)
    with pytest.raises(LocationNotFound):
        driver.current_coordinates()


def test_query_raw_status_empty_when_unconnected(tmp_path):
    driver = DuetDriver(log_dir=tmp_path)
    assert driver.query_raw_status() == ""


def test_query_raw_status_raises_on_broken_transport(tmp_path):
    class BrokenFake(FakeDuetSerial):
        def write(self, data: bytes) -> int:
            raise serial.SerialException("USB gone")

    driver = make_driver(tmp_path, BrokenFake())
    with pytest.raises(MillConnectionError):
        driver.query_raw_status()


def test_query_raw_status_reports_alarm_without_raising(tmp_path):
    fake = FakeDuetSerial(status="halted")
    driver = make_driver(tmp_path, fake)
    assert driver.query_raw_status().startswith("<Alarm|")


# ---------------------------------------------------------------------------
# Motion
# ---------------------------------------------------------------------------


def g01_commands(fake: FakeDuetSerial) -> list[str]:
    return [cmd for cmd in sent_commands(fake) if cmd.startswith("G01")]


def test_move_to_direct_axis_by_axis(tmp_path):
    fake = FakeDuetSerial()
    driver = make_driver(tmp_path, fake)
    driver.move_to(x_coordinate=10.0, y_coordinate=20.0, z_coordinate=5.0)

    commands = g01_commands(fake)
    assert [cmd.split()[1][0] for cmd in commands] == ["X", "Y", "Z"]
    assert fake.position == [10.0, 20.0, 5.0]


def test_move_to_prunes_unchanged_axes(tmp_path):
    fake = FakeDuetSerial(position=(0.0, 20.0, 5.0))
    driver = make_driver(tmp_path, fake)
    driver.move_to(x_coordinate=10.0, y_coordinate=20.0, z_coordinate=5.0)
    assert len(g01_commands(fake)) == 1
    assert g01_commands(fake)[0].startswith("G01 X10")


def test_move_to_skips_when_already_at_target(tmp_path):
    fake = FakeDuetSerial(position=(10.0, 20.0, 5.0))
    driver = make_driver(tmp_path, fake)
    driver.move_to(x_coordinate=10.0, y_coordinate=20.0, z_coordinate=5.0)
    assert not g01_commands(fake)


def test_move_to_transit_lifts_then_travels_then_descends(tmp_path):
    fake = FakeDuetSerial(position=(0.0, 0.0, 5.0))
    driver = make_driver(tmp_path, fake)
    driver.move_to(
        x_coordinate=10.0, y_coordinate=20.0, z_coordinate=5.0, travel_z=50.0
    )
    commands = g01_commands(fake)
    assert commands[0].startswith("G01 Z50")
    assert commands[1].startswith("G01 X10")
    assert commands[2].startswith("G01 Y20")
    assert commands[3].startswith("G01 Z5")


def test_move_to_waits_through_motion(tmp_path):
    fake = FakeDuetSerial(moves_to_idle_after=3)
    driver = make_driver(tmp_path, fake)
    driver.move_to(x_coordinate=10.0, y_coordinate=0.0, z_coordinate=0.0)
    assert fake.position[0] == 10.0


def test_move_limit_refusal_raises_with_limit_text(tmp_path):
    fake = FakeDuetSerial(
        move_error="Error: G1: target position outside machine limits"
    )
    driver = make_driver(tmp_path, fake)
    with pytest.raises(CommandExecutionError) as excinfo:
        driver.move_to(x_coordinate=999.0, y_coordinate=0.0, z_coordinate=0.0)
    assert "limit" in str(excinfo.value).lower()


def test_move_to_rejects_non_finite_targets(tmp_path):
    driver = make_driver(tmp_path, FakeDuetSerial())
    with pytest.raises(ValueError):
        driver.move_to(x_coordinate=float("nan"), y_coordinate=0.0, z_coordinate=0.0)


# ---------------------------------------------------------------------------
# Jogging
# ---------------------------------------------------------------------------


def test_jog_when_homed_uses_soft_limited_relative_move(tmp_path):
    fake = FakeDuetSerial(position=(10.0, 0.0, 0.0), homed=True)
    driver = make_driver(tmp_path, fake)
    driver.homed = True
    driver.jog(x=5.0, feed_rate=600)

    commands = sent_commands(fake)
    assert "M120" in commands and "M121" in commands
    move = next(cmd for cmd in commands if cmd.startswith("G1 "))
    assert "H2" not in move
    assert fake.position[0] == 15.0


def test_jog_when_unhomed_uses_h2(tmp_path):
    fake = FakeDuetSerial()
    driver = make_driver(tmp_path, fake)
    driver.homed = False
    driver.jog(z=-2.0)
    move = next(cmd for cmd in sent_commands(fake) if cmd.startswith("G1"))
    assert "H2" in move


def test_jog_error_raises(tmp_path):
    fake = FakeDuetSerial(move_error="Error: G1: target position outside machine limits")
    driver = make_driver(tmp_path, fake)
    with pytest.raises(CommandExecutionError):
        driver.jog(x=5.0)


def test_jog_noop_without_axes(tmp_path):
    fake = FakeDuetSerial()
    driver = make_driver(tmp_path, fake)
    driver.jog()
    assert not fake.writes


# ---------------------------------------------------------------------------
# Homing
# ---------------------------------------------------------------------------


def test_home_sets_homed_and_position(tmp_path):
    fake = FakeDuetSerial()
    driver = make_driver(tmp_path, fake)
    driver.home()
    assert driver.homed
    assert fake.position == [400.0, 300.0, 110.0]
    assert driver.last_status.startswith("<Idle|")


def test_home_paused_raises_without_auto_resume(tmp_path):
    class PausedAfterG28(FakeDuetSerial):
        def write(self, data: bytes) -> int:
            result = super().write(data)
            if data.strip() == b"G28":
                self.status = "paused"
            return result

    fake = PausedAfterG28()
    driver = make_driver(tmp_path, fake)
    with pytest.raises(StatusReturnError) as excinfo:
        driver.home()
    assert "resume or reset" in str(excinfo.value).lower()
    assert "M24" not in sent_commands(fake)


def test_home_halted_raises_alarm(tmp_path):
    fake = FakeDuetSerial(status="halted")
    driver = make_driver(tmp_path, fake)
    with pytest.raises(StatusReturnError) as excinfo:
        driver.home()
    assert "alarm" in str(excinfo.value).lower()


# ---------------------------------------------------------------------------
# Stop / reset / recovery
# ---------------------------------------------------------------------------


def test_stop_sends_m112_and_reports_alarm(tmp_path):
    fake = FakeDuetSerial()
    driver = make_driver(tmp_path, fake)
    driver.stop()
    assert "M112" in sent_commands(fake)
    assert fake.status == "halted"
    assert "Alarm" in driver.last_status
    assert not driver.homed


def test_soft_reset_reconnects_and_clears_halt(tmp_path, monkeypatch):
    fake = FakeDuetSerial(status="halted", homed=True)
    monkeypatch.setattr(
        duet_module.serial, "Serial", lambda *args, **kwargs: fake
    )
    driver = make_driver(tmp_path, fake)
    driver.soft_reset()
    assert fake.status == "idle"
    assert driver.active_connection
    assert not driver.homed
    assert "M999" in sent_commands(fake)


def test_soft_reset_and_unlock_raises_if_still_halted(tmp_path, monkeypatch):
    class StubbornFake(FakeDuetSerial):
        def write(self, data: bytes) -> int:
            if data.strip() == b"M999":
                self.writes.append(data)
                return len(data)  # ignore the reset request
            return super().write(data)

    fake = StubbornFake(status="halted")
    monkeypatch.setattr(
        duet_module.serial, "Serial", lambda *args, **kwargs: fake
    )
    driver = make_driver(tmp_path, fake)
    with pytest.raises(CommandExecutionError):
        driver.soft_reset_and_unlock()


def test_unlock_noop_when_not_halted(tmp_path):
    fake = FakeDuetSerial()
    driver = make_driver(tmp_path, fake)
    driver.unlock()
    assert "M999" not in sent_commands(fake)


# ---------------------------------------------------------------------------
# GRBL-parity surface
# ---------------------------------------------------------------------------


def test_read_grbl_settings_returns_empty(tmp_path):
    driver = make_driver(tmp_path, FakeDuetSerial())
    assert driver.read_grbl_settings() == {}


def test_set_grbl_setting_raises(tmp_path):
    driver = make_driver(tmp_path, FakeDuetSerial())
    with pytest.raises(CommandExecutionError):
        driver.set_grbl_setting("10", "0")


def test_execute_command_error_line_raises(tmp_path):
    fake = FakeDuetSerial(move_error="Error: G1: bad command")
    driver = make_driver(tmp_path, fake)
    with pytest.raises(CommandExecutionError):
        driver.execute_command("G1 X5 F600")


def test_execute_command_dollar_dump_returns_empty_dict(tmp_path):
    driver = make_driver(tmp_path, FakeDuetSerial())
    assert driver.execute_command("$$") == {}
