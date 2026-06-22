"""Generic film-thickness instrument interface."""

from abc import abstractmethod

from instruments.base_instrument import BaseInstrument
from instruments.filmetrics.models import MeasurementResult


class FilmetricsInstrument(BaseInstrument):
    """Base class for film-thickness measurement instruments."""

    @abstractmethod
    def acquire_sample(self) -> None:
        """Acquire a sample spectrum."""

    @abstractmethod
    def acquire_reference(self, reference_standard: str) -> None:
        """Acquire a reference spectrum for the named standard."""

    @abstractmethod
    def acquire_background(self) -> None:
        """Acquire a background spectrum."""

    @abstractmethod
    def commit_baseline(self) -> None:
        """Commit the current reference/background baseline."""

    @abstractmethod
    def measure(self) -> MeasurementResult:
        """Measure film thickness from the current optical setup."""

    @abstractmethod
    def save_spectrum(self, identifier: str) -> None:
        """Save the latest spectrum using a vendor-defined identifier."""
