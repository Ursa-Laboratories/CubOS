import pytest

from instruments.camera.vendors.mount_only import MountOnlyCamera
from instruments.camera.vendors.raspberry_pi import RaspberryPiCamera


def test_rpi_camera_uses_standard_mount_fields():
    camera = RaspberryPiCamera(offset_x=-12.0, offset_y=-4.0, depth=3.0, offline=True)

    assert camera.offset_x == -12.0
    assert camera.offset_y == -4.0
    assert camera.depth == 3.0
    assert camera.health_check() is True


def test_rpi_camera_capture_is_not_implemented():
    camera = RaspberryPiCamera(offline=True)

    with pytest.raises(NotImplementedError, match="capture is not implemented"):
        camera.capture()


def test_mount_only_camera_models_non_contact_mount_without_capture():
    camera = MountOnlyCamera(offset_x=1.0, offset_y=2.0, depth=3.0)

    camera.connect()
    assert camera.health_check() is True
    camera.disconnect()
    with pytest.raises(NotImplementedError, match="does not implement image capture"):
        camera.capture()
