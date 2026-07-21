"""Generic UV curing instrument interface."""

from abc import abstractmethod
from typing import Optional

from cubos.instruments.base_instrument import BaseInstrument
from cubos.instruments.uv_curing.models import CureResult, UVCuringStatus


class UVCuringInstrument(BaseInstrument):
    """Base class for UV curing implementations."""

    @abstractmethod
    def cure(
        self,
        intensity: Optional[float] = None,
        exposure_time: Optional[float] = None,
    ) -> CureResult:
        """Run a timed UV cure cycle."""

    @abstractmethod
    def measure(self, **kwargs) -> CureResult:
        """Run a protocol-compatible curing measurement."""

    @abstractmethod
    def get_status(self) -> UVCuringStatus:
        """Return UV source status."""
