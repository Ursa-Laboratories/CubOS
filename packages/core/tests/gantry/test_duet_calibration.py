"""Deck-origin calibration on Duet firmware: G54-carried, envelope-fixed.

On a Duet machine the physical envelope (config.g M208 + homing anchors) is
never rewritten by calibration; the calibrated deck frame rides on G54 work
offsets. These tests drive the real Gantry facade over a FakeDuetSerial
through the full flow: home -> block touch -> assign origin -> finalize.
"""

from __future__ import annotations

import pytest

from cubos.gantry.gantry import Gantry
from cubos.gantry.gantry_driver import duet_driver as duet_module
from cubos.gantry.gantry_driver.duet_driver import DuetDriver
from cubos.gantry.errors import MillConnectionError

from .fake_serial import FakeDuetSerial


@pytest.fixture(autouse=True)
def _fast_sleep(monkeypatch):
    monkeypatch.setattr(duet_module.time, "sleep", lambda *_: None)


DUET_CONFIG = {
    "serial_port": "/dev/fake-duet",
    "firmware": "duet",
    "gantry_type": "cub_xl",
}


def make_gantry(tmp_path, fake: FakeDuetSerial, config=None) -> Gantry:
    gantry = Gantry(config=dict(config or DUET_CONFIG))
    driver: DuetDriver = gantry._mill
    driver.logger_location = tmp_path
    driver.ser_mill = fake
    driver.active_connection = True
    driver.port = fake.port
    return gantry


def sent_commands(fake: FakeDuetSerial) -> list[str]:
    return [w.decode("ascii", errors="ignore").strip() for w in fake.writes]


def test_full_deck_origin_calibration_flow(tmp_path):
    fake = FakeDuetSerial()
    gantry = make_gantry(tmp_path, fake)

    # Home, then simulate the operator jogging the tip onto the block top
    # at deck-origin XY: machine pose (8, 6, 38), block height 35.
    gantry.home()
    home_z = gantry.get_coordinates()["z"]
    assert home_z == 110.0
    fake.position = [8.0, 6.0, 38.0]
    block_touch_z = gantry.get_coordinates()["z"]
    assert block_touch_z == 38.0

    gantry.set_work_coordinates(x=0.0, y=0.0, z=35.0)
    assert fake.work_offsets == [8.0, 6.0, 3.0]

    result = gantry.finalize_deck_origin_calibration(
        home_z=home_z,
        block_touch_z=block_touch_z,
        block_height=35.0,
        total_z_range=110.0,
        status_report=0,
        homing_pull_off=None,
    )

    # Usable maxima are the homed pose seen through the calibrated frame.
    assert result["measured_volume"] == {"x": 392.0, "y": 294.0, "z": 107.0}
    # Pull-off is structurally zero on Duet: max_travel == usable spans.
    assert result["homing_pull_off_mm"] == 0.0
    assert result["max_travel"] == {"x": 392.0, "y": 294.0, "z": 107.0}
    assert result["work_offsets"] == {"x": 8.0, "y": 6.0, "z": 3.0}
    assert result["position"] == {"x": 392.0, "y": 294.0, "z": 107.0}

    commands = sent_commands(fake)
    # No GRBL $-settings ever hit the wire, and the machine envelope was
    # not reprogrammed.
    assert not any(cmd.startswith("$") for cmd in commands)
    assert not any(cmd.startswith("M208") for cmd in commands)
    # Limit enforcement is on at the end.
    assert fake.limit_axes is True
    assert "M564 S1" in commands


def test_finalize_rejects_spans_exceeding_machine_envelope(tmp_path):
    fake = FakeDuetSerial()
    gantry = make_gantry(tmp_path, fake)
    gantry.home()
    # A negative offset would claim usable travel beyond the envelope.
    fake.position = [-5.0, 6.0, 38.0]
    gantry.set_work_coordinates(x=0.0, y=0.0, z=35.0)
    with pytest.raises(MillConnectionError, match="machine envelope"):
        gantry.finalize_deck_origin_calibration(
            home_z=110.0,
            block_touch_z=38.0,
            block_height=35.0,
            total_z_range=110.0,
        )


def test_soft_limit_dispatch_uses_m564(tmp_path):
    fake = FakeDuetSerial()
    gantry = make_gantry(tmp_path, fake)
    assert gantry.soft_limits_enabled() is True
    gantry.set_soft_limits_enabled(False)
    assert fake.limit_axes is False
    assert gantry.soft_limits_enabled() is False
    gantry.set_soft_limits_enabled(True)
    assert fake.limit_axes is True
    assert not any(cmd.startswith("$20") for cmd in sent_commands(fake))


def test_homing_pull_off_is_zero_on_duet(tmp_path):
    gantry = make_gantry(tmp_path, FakeDuetSerial())
    assert gantry.homing_pull_off_mm() == 0.0


def test_connect_reapplies_configured_work_offsets(tmp_path, monkeypatch):
    fake = FakeDuetSerial()
    monkeypatch.setattr(duet_module.serial, "Serial", lambda *a, **k: fake)
    config = dict(DUET_CONFIG)
    config["duet_settings"] = {"work_offsets": {"x": 8.0, "y": 6.0, "z": 3.0}}
    gantry = Gantry(config=config)
    gantry.connect(port="/dev/fake-duet")
    assert "G10 L2 P1 X8.000 Y6.000 Z3.000" in sent_commands(fake)
    assert fake.work_offsets == [8.0, 6.0, 3.0]


def test_work_offset_roundtrip(tmp_path):
    fake = FakeDuetSerial(position=(100.0, 50.0, 20.0))
    gantry = make_gantry(tmp_path, fake)
    driver: DuetDriver = gantry._mill
    driver.apply_work_offsets(x=1.5, y=-2.0, z=0.25)
    assert fake.work_offsets == [1.5, -2.0, 0.25]
    assert driver.read_work_offsets() == {"x": 1.5, "y": -2.0, "z": 0.25}
    assert gantry.get_work_offsets() == {"x": 1.5, "y": -2.0, "z": 0.25}


def test_read_axis_extents(tmp_path):
    fake = FakeDuetSerial()
    driver = make_gantry(tmp_path, fake)._mill
    assert driver.read_axis_extents() == {
        "x": (0.0, 400.0),
        "y": (0.0, 300.0),
        "z": (0.0, 110.0),
    }
