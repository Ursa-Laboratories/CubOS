"""Mount-only contact tool implementation."""

from __future__ import annotations

from typing import Optional

from instruments.mounted_tool.interface import MountedToolInstrument


class MountOnlyTool(MountedToolInstrument):
    """Mounted tool placeholder with valid offsets/depth and no actuation."""

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
        self.logger.info("MountOnlyTool connect is a no-op")

    def disconnect(self) -> None:
        self.logger.info("MountOnlyTool disconnect is a no-op")

    def health_check(self) -> bool:
        return True

    def actuate(self, *args, **kwargs):
        raise NotImplementedError(
            "MountOnlyTool models a mounted contact tool but does not implement "
            "actuation. Register a vendor tool driver to run tool-specific "
            "actions."
        )

