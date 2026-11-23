"""Frame proofs need actual reports and their own terminal acknowledgements."""
from unittest.mock import MagicMock
import pytest
from cubos.gantry.gantry_driver.driver import Mill
from cubos.gantry.errors import StatusReturnError
from tests.gantry.fake_serial import FakeGrblSerial


class FrameSerial(FakeGrblSerial):
    def __init__(self, modal="G0 G54 G17 G21 G90 G94 M5 M9 T0 F0 S0", ack=True, offsets=None):
        super().__init__()
        self.modal, self.ack = modal, ack
        self.offsets = offsets or ["[G54:-405,-400,-90]", "[G55:0,0,0]", "[G92:0,0,0]", "[TLO:0]"]

    def write(self, data):
        self.writes.append(data)
        if data == b"$G\n": self.queue_line(f"[GC:{self.modal}]")
        elif data == b"$#\n":
            for line in self.offsets: self.queue_line(line)
        else: return len(data)
        if self.ack: self.queue_line("ok")
        return len(data)


@pytest.fixture
def mill(monkeypatch):
    monkeypatch.setattr("cubos.gantry.gantry_driver.driver.set_up_mill_logger", lambda _: MagicMock())
    monkeypatch.setattr("cubos.gantry.gantry_driver.driver.set_up_command_logger", lambda _: MagicMock())
    return Mill()


def test_actual_modal_and_offsets_are_read_without_actuation(mill):
    serial = FrameSerial()
    mill.ser_mill = serial
    from cubos.gantry.gantry import Gantry
    gantry = Gantry(offline=True)
    gantry._offline, gantry._mill = False, mill
    assert gantry.read_calibration_frame() == {"G54": [-405, -400, -90], "G92": [0, 0, 0], "TLO": [0]}
    assert serial.writes == [b"$G\n", b"$#\n"]


@pytest.mark.parametrize("modal", ["G54 G55 G21 G90", "G54 G20 G21 G90", "G54 G21 G90 G91", "G55 G21 G90"])
def test_conflicting_or_wrong_modal_state_cannot_prove_frame(mill, modal):
    mill.ser_mill = FrameSerial(modal=modal)
    with pytest.raises(StatusReturnError): mill.read_calibration_frame()


def test_preexisting_ok_cannot_replace_missing_own_frame_ack(mill):
    serial = FrameSerial(ack=False)
    serial.queue_line("ok")
    mill.ser_mill = serial
    with pytest.raises(StatusReturnError, match="ACK|line limit"):
        mill.read_calibration_frame()
    assert serial.writes == [b"$G\n"]


@pytest.mark.parametrize("offsets", [["error:9"], ["[G54:nan,0,0]"], ["[G54:0,0,0]"], ["[G54:0,0,0]", "[G54:1,2,3]"]])
def test_incomplete_or_bad_offset_reports_fail_closed(mill, offsets):
    mill.ser_mill = FrameSerial(offsets=offsets)
    with pytest.raises(StatusReturnError): mill.read_calibration_frame()


def test_arm32_four_axis_reports_keep_fourth_offset_in_signature(mill):
    serial = FrameSerial(offsets=["[G54:-405.879,-399.730,-89.479,0.000]", "[G55:0,0,0,0]", "[G28:0,0,0,0]", "[G30:0,0,0,0]", "[G92:0,0,0,1.250]", "[TLO:0.000]", "[PRB:0,0,0,0:0]"])
    mill.ser_mill = serial
    frame = mill.read_calibration_frame()
    assert frame["G54"] == [-405.879, -399.730, -89.479, 0]
    assert frame["G92"] == [0, 0, 0, 1.25]
    assert serial.writes == [b"$G\n", b"$#\n"]


@pytest.mark.parametrize("offsets", [["[G54:1,2,3,4]", "[G92:0,0,0]", "[TLO:0]"], ["[G54:bad,0,0]"], ["[G54:0,0,0]", "[PRB:0,0,0:unknown]"]])
def test_offset_dimensionality_and_numbers_must_be_consistent(mill, offsets):
    mill.ser_mill = FrameSerial(offsets=offsets)
    with pytest.raises(StatusReturnError): mill.read_calibration_frame()


def test_deadline_before_first_read_never_reuses_an_old_ack(mill, monkeypatch):
    mill.ser_mill = FrameSerial()
    # No pending input: first clock value sets deadline, second expires it.
    clock = iter([0, 0, 3])
    monkeypatch.setattr("cubos.gantry.gantry_driver.driver.time.monotonic", lambda: next(clock))
    with pytest.raises(StatusReturnError, match="own ACK"):
        mill.read_calibration_frame()


def test_offline_frame_is_explicit_and_does_not_access_transport():
    from cubos.gantry.gantry import Gantry
    assert Gantry(offline=True).read_calibration_frame() == {"G54": [0, 0, 0], "G92": [0, 0, 0], "TLO": [0]}


def test_own_ack_without_requested_modal_report_fails(mill):
    serial = FrameSerial()
    serial.write = lambda data: serial.queue_line("ok")
    mill.ser_mill = serial
    with pytest.raises(StatusReturnError, match="without its requested report"):
        mill.read_calibration_frame()
