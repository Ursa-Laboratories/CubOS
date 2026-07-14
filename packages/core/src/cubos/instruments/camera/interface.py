"""Generic camera instrument interface."""

from abc import abstractmethod
from typing import Any

from cubos.instruments.base_instrument import BaseInstrument


class CameraInstrument(BaseInstrument):
    """Base class for mounted camera implementations."""

    @abstractmethod
    def capture(self, *args: Any, **kwargs: Any) -> str:
        """Capture an image and return the vendor-defined image reference."""
