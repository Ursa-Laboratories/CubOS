from __future__ import annotations

from .holder import HolderLabware
from .labware import Coordinate3D


class TipDisposal(HolderLabware):
    """Bounding-box model for the used-tip disposal fixture."""

    model_name: str = "tip_disposal"
    length_mm: float = 198.0
    width_mm: float = 62.0
    height_mm: float = 30.0

    def iter_motion_targets(self) -> dict[str, Coordinate3D]:
        return {"location": self.location}
