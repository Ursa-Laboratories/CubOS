"""Generic camera instrument interface."""

from instruments.base_instrument import BaseInstrument


class CameraInstrument(BaseInstrument):
    """Base class for mounted camera implementations."""

    def capture(self, *args, **kwargs):
        raise NotImplementedError("Camera capture is not implemented.")

