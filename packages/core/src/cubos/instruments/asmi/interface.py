"""Generic ASMI/force-indentation instrument interface."""

from abc import abstractmethod
from typing import Any

from cubos.instruments.base_instrument import BaseInstrument
from cubos.instruments.asmi.models import ASMIStatus, MeasurementResult


class ASMIInstrument(BaseInstrument):
    """Base class for ASMI-compatible force sensing instruments."""

    @abstractmethod
    def measure(self, n_samples: int = 1) -> MeasurementResult:
        """Collect force readings and return the measured force summary."""

    @abstractmethod
    def get_status(self) -> ASMIStatus:
        """Return the current force-sensor connection status."""

    @abstractmethod
    def get_force_reading(self) -> float:
        """Return one force reading in Newtons."""

    @abstractmethod
    def get_baseline_force(self, samples: int = 10) -> tuple[float, float]:
        """Return baseline force mean and standard deviation in Newtons."""

    @abstractmethod
    def indentation(
        self,
        gantry: Any,
        *,
        measurement_height: float,
        indentation_limit_height: float,
        well_z: float,
        step_size: float | None = None,
        force_limit: float | None = None,
        baseline_samples: int | None = None,
        measure_with_return: bool = False,
    ) -> dict:
        """Run a controlled force-indentation measurement at the current XY."""
