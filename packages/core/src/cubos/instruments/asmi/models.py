from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class MeasurementResult:
    """Result of an ASMI force measurement (one or more samples)."""

    readings: tuple
    mean_n: float
    std_n: float
    timestamp: float

    @property
    def force_n(self) -> float:
        return self.mean_n

    @property
    def is_valid(self) -> bool:
        return len(self.readings) > 0 and self.mean_n > -100.0


@dataclass(frozen=True)
class ASMIStatus:
    """Snapshot of force sensor state."""

    is_connected: bool
    sensor_description: Optional[str]

    @property
    def is_valid(self) -> bool:
        return self.is_connected and self.sensor_description is not None
