from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class MeasurementResult:
    """Immutable result of a single Filmetrics thickness measurement."""

    thickness_nm: Optional[float]
    goodness_of_fit: Optional[float]

    @property
    def is_valid(self) -> bool:
        return (
            self.thickness_nm is not None
            and self.goodness_of_fit is not None
            and self.goodness_of_fit >= 0.6
        )
