"""Parameter and result dataclasses for potentiostat experiments.

All dataclasses are frozen. ``*Params`` types validate in ``__post_init__``
and raise :class:`PotentiostatConfigError` on bad input. ``*Result`` types
carry ``tuple[float, ...]`` traces plus the requested-experiment scalars,
the driver's ``vendor`` name, and a free-form ``metadata`` mapping with
run-level info (device ID, timestamps, ``aborted`` flag, stop reason).

The result shape matches ``UVVisSpectrum`` and friends: tuple-backed arrays
serialize cheaply into SQLite via :class:`DataStore.log_measurement`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from cubos.instruments.potentiostat.exceptions import PotentiostatConfigError


# ── Param types ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CVParams:
    """Cyclic voltammetry sweep parameters.

    The sweep goes start_V → vertex1_V → vertex2_V → end_V and repeats for
    ``cycles`` passes. ``scan_rate_V_per_s`` controls ramp speed;
    ``sampling_interval_s`` controls how often data is recorded.
    """

    start_V: float
    vertex1_V: float
    vertex2_V: float
    end_V: float
    scan_rate_V_per_s: float
    cycles: int = 1
    sampling_interval_s: float = 0.01

    def __post_init__(self) -> None:
        if self.scan_rate_V_per_s <= 0:
            raise PotentiostatConfigError(
                f"scan_rate_V_per_s must be > 0, got {self.scan_rate_V_per_s}"
            )
        if self.cycles < 1:
            raise PotentiostatConfigError(
                f"cycles must be >= 1, got {self.cycles}"
            )
        if self.sampling_interval_s <= 0:
            raise PotentiostatConfigError(
                f"sampling_interval_s must be > 0, got {self.sampling_interval_s}"
            )
        if self.vertex1_V == self.vertex2_V:
            raise PotentiostatConfigError(
                "vertex1_V and vertex2_V must differ to define a sweep"
            )


@dataclass(frozen=True)
class OCPParams:
    """Open-circuit potential measurement parameters."""

    duration_s: float
    sampling_interval_s: float = 0.1

    def __post_init__(self) -> None:
        if self.duration_s <= 0:
            raise PotentiostatConfigError(
                f"duration_s must be > 0, got {self.duration_s}"
            )
        if self.sampling_interval_s <= 0:
            raise PotentiostatConfigError(
                f"sampling_interval_s must be > 0, got {self.sampling_interval_s}"
            )
        if self.sampling_interval_s > self.duration_s:
            raise PotentiostatConfigError(
                "sampling_interval_s must be <= duration_s"
            )


@dataclass(frozen=True)
class CAParams:
    """Chronoamperometry (constant applied potential) parameters."""

    potential_V: float
    duration_s: float
    sampling_interval_s: float = 0.01

    def __post_init__(self) -> None:
        if self.duration_s <= 0:
            raise PotentiostatConfigError(
                f"duration_s must be > 0, got {self.duration_s}"
            )
        if self.sampling_interval_s <= 0:
            raise PotentiostatConfigError(
                f"sampling_interval_s must be > 0, got {self.sampling_interval_s}"
            )
        if self.sampling_interval_s > self.duration_s:
            raise PotentiostatConfigError(
                "sampling_interval_s must be <= duration_s"
            )


@dataclass(frozen=True)
class CPParams:
    """Chronopotentiometry (constant applied current) parameters."""

    current_A: float
    duration_s: float
    sampling_interval_s: float = 0.01

    def __post_init__(self) -> None:
        if self.duration_s <= 0:
            raise PotentiostatConfigError(
                f"duration_s must be > 0, got {self.duration_s}"
            )
        if self.sampling_interval_s <= 0:
            raise PotentiostatConfigError(
                f"sampling_interval_s must be > 0, got {self.sampling_interval_s}"
            )
        if self.sampling_interval_s > self.duration_s:
            raise PotentiostatConfigError(
                "sampling_interval_s must be <= duration_s"
            )


# ── Result types ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class OCPResult:
    """Open-circuit potential trace.

    Current is not recorded by OCP (the cell is open), so only voltage_v is
    populated. Use ``final_voltage_v`` to grab the last reading.
    """

    time_s: tuple[float, ...]
    voltage_v: tuple[float, ...]
    sample_period_s: float
    duration_s: float
    vendor: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def technique(self) -> str:
        return "ocp"

    @property
    def final_voltage_v(self) -> float | None:
        return self.voltage_v[-1] if self.voltage_v else None

    @property
    def is_valid(self) -> bool:
        return (
            len(self.time_s) > 0
            and len(self.time_s) == len(self.voltage_v)
            and self.sample_period_s > 0
            and self.duration_s > 0
        )


@dataclass(frozen=True)
class CAResult:
    """Chronoamperometry trace (current measured at constant applied potential)."""

    time_s: tuple[float, ...]
    voltage_v: tuple[float, ...]
    current_a: tuple[float, ...]
    sample_period_s: float
    duration_s: float
    step_potential_v: float
    vendor: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def technique(self) -> str:
        return "ca"

    @property
    def is_valid(self) -> bool:
        return (
            len(self.time_s) > 0
            and len(self.time_s) == len(self.current_a)
            and len(self.time_s) == len(self.voltage_v)
            and self.sample_period_s > 0
            and self.duration_s > 0
        )


@dataclass(frozen=True)
class CPResult:
    """Chronopotentiometry trace (voltage measured at constant applied current)."""

    time_s: tuple[float, ...]
    voltage_v: tuple[float, ...]
    current_a: tuple[float, ...]
    sample_period_s: float
    duration_s: float
    step_current_a: float
    vendor: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def technique(self) -> str:
        return "cp"

    @property
    def is_valid(self) -> bool:
        return (
            len(self.time_s) > 0
            and len(self.time_s) == len(self.current_a)
            and len(self.time_s) == len(self.voltage_v)
            and self.sample_period_s > 0
            and self.duration_s > 0
        )


@dataclass(frozen=True)
class CVResult:
    """Cyclic voltammetry trace."""

    time_s: tuple[float, ...]
    voltage_v: tuple[float, ...]
    current_a: tuple[float, ...]
    scan_rate_v_s: float
    step_size_v: float
    cycles: int
    vendor: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def technique(self) -> str:
        return "cv"

    @property
    def is_valid(self) -> bool:
        return (
            len(self.time_s) > 0
            and len(self.time_s) == len(self.current_a)
            and len(self.time_s) == len(self.voltage_v)
            and self.scan_rate_v_s > 0
            and self.step_size_v > 0
            and self.cycles >= 1
        )
