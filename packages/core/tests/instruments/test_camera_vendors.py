"""Tests for the FLIR and OpenCV camera vendors (offline + import guards)."""

import struct

import pytest

from cubos.instruments.camera.exceptions import CameraCaptureError, CameraConfigError
from cubos.instruments.camera.interface import CameraInstrument
from cubos.instruments.camera.placeholder import write_placeholder_png
from cubos.instruments.camera.vendors.flir import FlirCamera
from cubos.instruments.camera.vendors.opencv import OpenCVCamera
from cubos.instruments.registry import get_instrument_class


def _assert_valid_png(path):
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", data[16:24])
    assert width > 0 and height > 0


class TestPlaceholder:
    def test_writes_decodable_png(self, tmp_path):
        target = write_placeholder_png(tmp_path / "sub" / "img.png")
        _assert_valid_png(target)


class TestRegistry:
    def test_vendors_resolve(self):
        assert get_instrument_class("camera", "flir") is FlirCamera
        assert get_instrument_class("camera", "opencv") is OpenCVCamera
        assert issubclass(FlirCamera, CameraInstrument)
        assert issubclass(OpenCVCamera, CameraInstrument)


@pytest.mark.parametrize("vendor_cls", [FlirCamera, OpenCVCamera])
class TestOfflineCapture:
    def test_offline_lifecycle(self, vendor_cls):
        camera = vendor_cls(offline=True)
        camera.connect()
        assert camera.health_check() is True
        camera.disconnect()

    def test_offline_capture_writes_real_file(self, vendor_cls, tmp_path):
        camera = vendor_cls(offline=True)
        camera.connect()
        saved = camera.capture(save_path=str(tmp_path / "shot.png"))
        assert saved == str(tmp_path / "shot.png")
        _assert_valid_png(tmp_path / "shot.png")

    def test_capture_requires_save_path(self, vendor_cls):
        camera = vendor_cls(offline=True)
        with pytest.raises(CameraCaptureError, match="save_path"):
            camera.capture()


class TestHardwareGuards:
    def test_flir_connect_without_pyspin_names_sdk(self):
        if FlirCamera.is_available():
            pytest.skip("PySpin installed in this environment")
        camera = FlirCamera(offline=False)
        with pytest.raises(CameraConfigError, match="Spinnaker"):
            camera.connect()

    def test_capture_before_connect_raises(self):
        camera = FlirCamera(offline=False)
        with pytest.raises((CameraCaptureError, CameraConfigError)):
            camera.capture(save_path="/tmp/never.png")
