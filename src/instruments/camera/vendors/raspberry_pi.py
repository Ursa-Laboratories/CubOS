"""Base Raspberry Pi camera instrument.

The class only models CubOS mounting/runtime identity for now. Image capture is
intentionally left to deployment-specific code.
"""

from __future__ import annotations

from typing import Optional

from instruments.camera.interface import CameraInstrument


class RaspberryPiCamera(CameraInstrument):
    """Placeholder Raspberry Pi camera instrument.

    The gantry runtime can position this instrument through the standard
    ``offset_x``, ``offset_y``, and ``depth`` mount fields. ``capture`` is not
    implemented here because camera acquisition will be provided by the Sterling
    deployment.
    """

    def __init__(
        self,
        name: Optional[str] = None,
        offset_x: float = 0.0,
        offset_y: float = 0.0,
        depth: float = 0.0,
        offline: bool = False,
        **kwargs,
    ):
        super().__init__(
            name=name,
            offset_x=offset_x,
            offset_y=offset_y,
            depth=depth,
            offline=offline,
        )

    def connect(self) -> None:
        # TODO: Implement camera connection handling in a hardware-backed implementation.
        if self._offline:
            self.logger.info("RaspberryPiCamera connected (offline)")
            return
        self.logger.info("RaspberryPiCamera connect is a no-op in the base class")

    def disconnect(self) -> None:
        # TODO: Implement camera disconnection handling in a hardware-backed implementation.
        if self._offline:
            self.logger.info("RaspberryPiCamera disconnected (offline)")
            return
        self.logger.info("RaspberryPiCamera disconnect is a no-op in the base class")

    def health_check(self) -> bool:
        return True

    def capture(self, *args, **kwargs) -> str:
        # TODO: Implement camera capture in a hardware-backed implementation.
        raise NotImplementedError(
            "RaspberryPiCamera.capture is not implemented in the base CubOS class."
        )
