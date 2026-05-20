"""Gantry configuration domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class HomingStrategy(str, Enum):
    """Supported CNC homing strategies."""

    STANDARD = "standard"


class YAxisMotion(str, Enum):
    """Whether Y-axis motion moves the head or the bed (base plate)."""

    HEAD = "head"
    BED = "bed"


class GantryType(str, Enum):
    """Supported physical gantry families."""

    CUB = "cub"
    CUB_XL = "cub_xl"


@dataclass(frozen=True)
class WorkingVolume:
    """Gantry working volume bounds in millimeters.

    Bounds are inclusive and use the CubOS deck-origin frame for supported
    protocol execution.
    """

    x_min: float
    x_max: float
    y_min: float
    y_max: float
    z_min: float
    z_max: float

    def __post_init__(self) -> None:
        for axis in ("x", "y", "z"):
            lo = getattr(self, f"{axis}_min")
            hi = getattr(self, f"{axis}_max")
            if lo >= hi:
                raise ValueError(
                    f"{axis}_min ({lo}) must be < {axis}_max ({hi})"
                )

    def contains(self, x: float, y: float, z: float) -> bool:
        """Return True if (x, y, z) is within this working volume (inclusive)."""
        return (
            self.x_min <= x <= self.x_max
            and self.y_min <= y <= self.y_max
            and self.z_min <= z <= self.z_max
        )


@dataclass(frozen=True)
class GantryConfig:
    """Loaded gantry configuration."""

    serial_port: str
    gantry_type: GantryType
    homing_strategy: HomingStrategy
    total_z_range: float
    working_volume: WorkingVolume
    y_axis_motion: YAxisMotion = YAxisMotion.HEAD
    safe_z: Optional[float] = None
    expected_grbl_settings: Optional[Dict[str, float]] = field(default=None)
    instruments: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "gantry_type", GantryType(self.gantry_type))
        except ValueError as exc:
            raise ValueError(
                f"Unsupported gantry_type {self.gantry_type!r}."
            ) from exc
        if self.total_z_range <= 0:
            raise ValueError(
                f"total_z_range ({self.total_z_range}) must be > 0"
            )
        if self.safe_z is not None:
            if not (
                self.working_volume.z_min
                <= self.safe_z
                <= self.working_volume.z_max
            ):
                raise ValueError(
                    "safe_z must be within the configured "
                    "working-volume Z bounds."
                )

    @property
    def resolved_safe_z(self) -> float:
        """Effective safe travel Z: explicit ``safe_z`` or ``working_volume.z_max``."""
        return self.safe_z if self.safe_z is not None else self.working_volume.z_max
