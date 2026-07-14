"""Camera instrument support."""

from cubos.instruments.camera.interface import CameraInstrument
from cubos.instruments.camera.vendors.mount_only import MountOnlyCamera
from cubos.instruments.camera.vendors.raspberry_pi import RaspberryPiCamera

__all__ = ["CameraInstrument", "MountOnlyCamera", "RaspberryPiCamera"]

