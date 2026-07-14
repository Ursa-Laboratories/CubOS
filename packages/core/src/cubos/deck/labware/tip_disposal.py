from __future__ import annotations

from .holder import HolderLabware


class TipDisposal(HolderLabware):
    """Bounding-box model for the used-tip disposal fixture."""

    model_name: str = "tip_disposal"
    length: float = 198.0
    width: float = 62.0
    height: float = 30.0
