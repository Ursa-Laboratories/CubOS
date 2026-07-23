"""Generic ASMI/force-indentation instrument interface."""

from abc import abstractmethod
from typing import Any

from cubos.instruments.base_instrument import BaseInstrument
from cubos.instruments.asmi.models import ASMIStatus, MeasurementResult

# Surface-detection defaults shared by drivers and static validators.
# The search descends in coarse steps from the measurement plane until the
# baseline-corrected force changes by more than the threshold, then backs
# off one search step and runs the fine-step indentation from there.
DEFAULT_SURFACE_SEARCH_STEP_MM = 0.5
DEFAULT_SURFACE_FORCE_THRESHOLD_N = 0.01  # 10 mN
DEFAULT_SURFACE_SEARCH_MAX_TRAVEL_MM = 10.0


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
        detect_surface: bool = False,
        surface_search_step: float | None = None,
        surface_force_threshold: float | None = None,
        surface_search_max_travel: float | None = None,
    ) -> dict:
        """Run a controlled force-indentation measurement at the current XY.

        With ``detect_surface`` enabled the probe first searches downward
        from the measurement plane in ``surface_search_step`` increments
        until the baseline-corrected force changes by more than
        ``surface_force_threshold`` (N), backs off one search step, and
        anchors ``indentation_limit_height`` to that detected surface
        instead of the calibrated well surface. The search never descends
        more than ``surface_search_max_travel`` mm below the measurement
        plane.
        """
