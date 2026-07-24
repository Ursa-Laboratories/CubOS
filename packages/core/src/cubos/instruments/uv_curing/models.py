from dataclasses import dataclass


@dataclass(frozen=True)
class CureResult:
    """Result of a single UV curing exposure."""

    intensity_percent: float
    exposure_time_s: float
    timestamp: float


@dataclass(frozen=True)
class UVCuringStatus:
    """Snapshot of OmniCure connection state."""

    is_connected: bool
