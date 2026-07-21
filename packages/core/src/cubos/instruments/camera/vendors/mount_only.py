"""Mount-only camera implementation.

This class lets CubOS model a mounted non-contact camera for calibration,
visualization, and protocol planning before a hardware capture driver exists.
"""

from __future__ import annotations

from typing import Optional

from cubos.instruments.camera.interface import CameraInstrument


class MountOnlyCamera(CameraInstrument):
    """Camera placeholder with valid mounting semantics and no acquisition."""

    def __init__(
        self,
        name: Optional[str] = None,
        offset_x: float = 0.0,
        offset_y: float = 0.0,
        depth: float = 0.0,
        offline: bool = True,
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
        self.logger.info("MountOnlyCamera connect is a no-op")

    def disconnect(self) -> None:
        self.logger.info("MountOnlyCamera disconnect is a no-op")

    def health_check(self) -> bool:
        return True

    def capture(self, *args, **kwargs) -> str:
        raise NotImplementedError(
            "MountOnlyCamera models a mounted non-contact instrument but does "
            "not implement image capture. Register a vendor camera driver to "
            "capture images."
        )

