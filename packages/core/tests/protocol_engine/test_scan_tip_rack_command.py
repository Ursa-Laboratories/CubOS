"""Tests for the scan_tip_rack protocol command."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from cubos.deck.deck import Deck
from cubos.deck.labware.labware import Coordinate3D
from cubos.deck.labware.tip_rack import TipRack
from cubos.instruments.camera.exceptions import CameraCaptureError
from cubos.instruments.camera.interface import CameraInstrument
from cubos.protocol_engine.commands.tips import scan_tip_rack
from cubos.protocol_engine.errors import ProtocolExecutionError
from cubos.protocol_engine.runtime import ProtocolContext

SAFE_Z = 60.0

# Geometry chosen so the projection math is exact: tips at deck X 10/18,
# mm_per_px=1, camera centered at their mean (14, 20) over a 41x41 frame
# whose center pixel is (20, 20) -> A1 at pixel x 16, A2 at pixel x 24.
A1_XY = (10.0, 20.0)
A2_XY = (18.0, 20.0)
IMAGE_SIZE = 41
A1_PX, A2_PX, CENTER_PY = 16, 24, 20


def _rack() -> TipRack:
    return TipRack(
        name="tips",
        model_name="test_tip_rack",
        rows=1,
        columns=2,
        pickup_z=42.0,
        drop_z=32.0,
        tip_length=59.3,
        location=Coordinate3D(x=A1_XY[0], y=A1_XY[1], z=42.0),
        length=8.0,
        width=1.0,
        height=10.0,
        tips={
            "A1": Coordinate3D(x=A1_XY[0], y=A1_XY[1], z=42.0),
            "A2": Coordinate3D(x=A2_XY[0], y=A2_XY[1], z=42.0),
        },
    )


def _gray_png_bytes(rows: list[list[int]]) -> bytes:
    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    raw = b"".join(b"\x00" + bytes(row) for row in rows)
    ihdr = struct.pack(">IIBBBBB", len(rows[0]), len(rows), 8, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _rack_image(a1_value: int = 240, a2_value: int = 10) -> bytes:
    rows = [[10] * IMAGE_SIZE for _ in range(IMAGE_SIZE)]
    for py in range(CENTER_PY - 3, CENTER_PY + 4):
        for px in range(A1_PX - 3, A1_PX + 4):
            rows[py][px] = a1_value
        for px in range(A2_PX - 3, A2_PX + 4):
            rows[py][px] = a2_value
    return _gray_png_bytes(rows)


class FakeCamera(CameraInstrument):
    """Camera double that writes prebuilt PNG bytes to the save path."""

    def __init__(self, png_bytes: bytes, **kwargs):
        super().__init__(name="cam", **kwargs)
        self._png_bytes = png_bytes
        self.fail = False

    def connect(self) -> None:  # pragma: no cover - unused
        pass

    def disconnect(self) -> None:  # pragma: no cover - unused
        pass

    def health_check(self) -> bool:  # pragma: no cover - unused
        return True

    def capture(self, *args, save_path: str = "", **kwargs) -> str:
        if self.fail:
            raise CameraCaptureError("shutter jammed")
        Path(save_path).write_bytes(self._png_bytes)
        return save_path


class FakeGantry:
    def __init__(self, instruments, safe_z=SAFE_Z):
        self.instruments = instruments
        self.safe_z = safe_z
        self.trace: list = []

    def move_to_labware(self, instrument, position):
        self.trace.append(("approach", (position.x, position.y)))

    def move(self, instrument, position, travel_z=None):
        self.trace.append(("move", position, travel_z))


@pytest.fixture(autouse=True)
def _images_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CUBOS_IMAGES_DIR", str(tmp_path / "images"))
    return tmp_path / "images"


def _context(png_bytes: bytes, rack: TipRack | None = None):
    rack = rack or _rack()
    camera = FakeCamera(png_bytes)
    gantry = FakeGantry({"cam": camera})
    context = ProtocolContext(gantry=gantry, deck=Deck({"tips": rack}))
    return context, rack, camera, gantry


def _scan(context, **overrides):
    kwargs = {
        "camera": "cam",
        "rack": "tips",
        "image_height": 30.0,
        "mm_per_px": 1.0,
        "patch_radius_mm": 2.0,
    }
    kwargs.update(overrides)
    return scan_tip_rack(context, **kwargs)


class TestScanTipRack:

    def test_untracked_scan_updates_in_memory_presence(self):
        context, rack, _camera, _gantry = _context(_rack_image())
        rack.mark_tip_used("A1")

        result = _scan(context)

        assert result["slots"] == {"A1": "present", "A2": "absent"}
        assert rack.tip_present == {"A1": True, "A2": False}
        assert result["image_path"].endswith(".png")

    def test_moves_to_grid_center_then_retracts_to_safe_z(self):
        context, _rack_obj, _camera, gantry = _context(_rack_image())

        _scan(context)

        assert gantry.trace[0] == ("approach", (14.0, 20.0))
        assert gantry.trace[1] == ("move", (14.0, 20.0, 72.0), None)
        assert gantry.trace[-1] == ("move", (14.0, 20.0, SAFE_Z), SAFE_Z)

    def test_uncertain_slots_are_not_pickable(self):
        rows = [[10] * IMAGE_SIZE for _ in range(IMAGE_SIZE)]
        for py in range(CENTER_PY - 3, CENTER_PY + 4):
            for px in range(A1_PX - 3, A1_PX + 4):
                rows[py][px] = 120
        context, rack, _camera, _gantry = _context(_gray_png_bytes(rows))

        result = _scan(context)

        assert result["slots"]["A1"] == "uncertain"
        assert rack.tip_present["A1"] is False

    def test_out_of_frame_slots_are_uncertain(self):
        tiny = _gray_png_bytes([[200] * 5 for _ in range(5)])
        context, rack, _camera, _gantry = _context(tiny)

        result = _scan(context)

        assert result["slots"] == {"A1": "uncertain", "A2": "uncertain"}
        assert rack.tip_present == {"A1": False, "A2": False}

    def test_tracked_scan_reconciles_through_data_store(self):
        context, _rack_obj, _camera, _gantry = _context(_rack_image())
        context.campaign_id = 7
        context.fluid_state_id = 11
        store = MagicMock()
        store.reconcile_tip_presence.return_value = {
            "changed": [("A2", "available", "consumed")],
            "skipped": [],
            "unchanged": ["A1"],
        }
        context.data_store = store

        result = _scan(context)

        store.reconcile_tip_presence.assert_called_once_with(
            11, "tips", {"A1": True, "A2": False},
        )
        assert result["slots"] == {"A1": "present", "A2": "absent"}

    def test_tracked_scan_warns_on_skipped_slots(self, caplog):
        context, _rack_obj, _camera, _gantry = _context(_rack_image())
        context.campaign_id = 7
        context.fluid_state_id = 11
        store = MagicMock()
        store.reconcile_tip_presence.return_value = {
            "changed": [],
            "skipped": [("A1", "attached")],
            "unchanged": ["A2"],
        }
        context.data_store = store

        with caplog.at_level("WARNING"):
            _scan(context)

        assert any("not reconciled" in message for message in caplog.messages)

    def test_tracked_reconcile_failure_raises(self):
        context, _rack_obj, _camera, _gantry = _context(_rack_image())
        context.campaign_id = 7
        context.fluid_state_id = 11
        store = MagicMock()
        store.reconcile_tip_presence.side_effect = RuntimeError("locked")
        context.data_store = store

        with pytest.raises(ProtocolExecutionError, match="reconcile failed"):
            _scan(context)

    def test_capture_failure_raises_and_still_retracts(self):
        context, rack, camera, gantry = _context(_rack_image())
        camera.fail = True

        with pytest.raises(ProtocolExecutionError, match="capture failed"):
            _scan(context)

        assert gantry.trace[-1] == ("move", (14.0, 20.0, SAFE_Z), SAFE_Z)
        assert rack.tip_present == {"A1": True, "A2": True}

    def test_unreadable_image_raises(self):
        context, _rack_obj, _camera, _gantry = _context(b"not a png at all")

        with pytest.raises(ProtocolExecutionError, match="not a PNG"):
            _scan(context)

    def test_missing_rack_raises(self):
        context, _rack_obj, _camera, _gantry = _context(_rack_image())

        with pytest.raises(ProtocolExecutionError, match="not on the deck"):
            _scan(context, rack="missing")

    def test_missing_camera_raises(self):
        context, _rack_obj, _camera, _gantry = _context(_rack_image())

        with pytest.raises(ProtocolExecutionError, match="No instrument"):
            _scan(context, camera="ghost")

    @pytest.mark.parametrize(
        "overrides,match",
        [
            ({"mm_per_px": 0}, "mm_per_px"),
            ({"mm_per_px": -1.0}, "mm_per_px"),
            ({"patch_radius_mm": 0}, "patch_radius_mm"),
            ({"image_height": float("nan")}, "image_height"),
            (
                {"present_threshold": 0.2, "absent_threshold": 0.5},
                "threshold",
            ),
        ],
    )
    def test_invalid_parameters_raise_before_motion(self, overrides, match):
        context, _rack_obj, _camera, gantry = _context(_rack_image())

        with pytest.raises(ProtocolExecutionError, match=match):
            _scan(context, **overrides)

        assert gantry.trace == []


class TestScanTipRackEdges:

    def test_incomplete_tracked_context_fails_before_motion(self):
        context, _rack_obj, _camera, gantry = _context(_rack_image())
        context.fluid_state_id = 11

        with pytest.raises(ProtocolExecutionError, match="incomplete"):
            _scan(context)

        assert gantry.trace == []

    def test_non_tip_rack_target_raises(self):
        from types import SimpleNamespace

        context, _rack_obj, _camera, _gantry = _context(_rack_image())
        context.deck = MagicMock()
        context.deck.resolve_labware.return_value = SimpleNamespace()

        with pytest.raises(ProtocolExecutionError, match="not a TipRack"):
            _scan(context)

    def test_lighting_failure_logs_and_continues(self, caplog):
        from cubos.instruments.lighting.vendors.pawduino import PawduinoLighting

        context, _rack_obj, camera, gantry = _context(_rack_image())
        lights = PawduinoLighting(offline=True)
        lights.connect()
        lights.set_channel = MagicMock(side_effect=RuntimeError("bulb out"))
        gantry.instruments["lights"] = lights

        with caplog.at_level("WARNING"):
            result = _scan(context)

        assert result["slots"] == {"A1": "present", "A2": "absent"}
        assert any("lighting" in message for message in caplog.messages)

    def test_retract_failure_logs_and_scan_still_returns(self, caplog):
        context, _rack_obj, _camera, gantry = _context(_rack_image())
        original_move = gantry.move

        def move(instrument, position, travel_z=None):
            if travel_z is not None:
                raise RuntimeError("alarm state")
            return original_move(instrument, position, travel_z)

        gantry.move = move

        with caplog.at_level("ERROR"):
            result = _scan(context)

        assert result["slots"] == {"A1": "present", "A2": "absent"}
        assert any("retract" in message for message in caplog.messages)
