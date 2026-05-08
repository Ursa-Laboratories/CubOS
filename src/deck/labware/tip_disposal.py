from __future__ import annotations

from .holder import HolderLabware


class TipDisposal(HolderLabware):
    """Bounding-box model for the used-tip disposal fixture."""

    model_name: str = "tip_disposal"
    length_mm: float = 198.0
    width_mm: float = 62.0
    height_mm: float = 30.0
