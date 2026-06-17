import pytest

from instruments.rpi_camera.driver import RPiCamera


def test_rpi_camera_uses_standard_mount_fields():
    camera = RPiCamera(offset_x=-12.0, offset_y=-4.0, depth=3.0, offline=True)

    assert camera.offset_x == -12.0
    assert camera.offset_y == -4.0
    assert camera.depth == 3.0
    assert camera.health_check() is True


def test_rpi_camera_capture_is_not_implemented():
    camera = RPiCamera(offline=True)

    with pytest.raises(NotImplementedError, match="capture is not implemented"):
        camera.capture()
