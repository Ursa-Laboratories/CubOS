"""Generic compact UV-Vis spectrometer interface."""

from abc import abstractmethod

from instruments.base_instrument import BaseInstrument
from instruments.uvvis_ccs.models import UVVisSpectrum


class UVVisCCSInstrument(BaseInstrument):
    """Base class for compact UV-Vis spectrometer implementations."""

    @abstractmethod
    def set_integration_time(self, seconds: float) -> None:
        """Set spectrum integration time in seconds."""

    @abstractmethod
    def get_integration_time(self) -> float:
        """Return the active spectrum integration time in seconds."""

    @abstractmethod
    def measure(self) -> UVVisSpectrum:
        """Capture and return a UV-Vis spectrum."""

    @abstractmethod
    def get_device_info(self) -> list[str]:
        """Return vendor-provided device identification fields."""
