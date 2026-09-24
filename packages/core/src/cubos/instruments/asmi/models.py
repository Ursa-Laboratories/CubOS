import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Optional


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


class TipShape(str, Enum):
    """Indenter tip geometries CubOS can record for contact-mechanics analysis."""

    SPHERICAL = "spherical"
    FLAT_PUNCH = "flat_punch"


_TIP_FIELDS = frozenset({"shape", "radius_mm", "material"})


@dataclass(frozen=True)
class IndenterTip:
    """Physical indenter tip mounted on an ASMI instrument.

    ``radius_mm`` is the sphere radius for ``spherical`` tips and the punch
    radius for ``flat_punch`` tips.
    """

    shape: TipShape
    radius_mm: float
    material: Optional[str] = None

    def __post_init__(self) -> None:
        try:
            shape = TipShape(self.shape)
        except ValueError:
            choices = ", ".join(s.value for s in TipShape)
            raise ValueError(
                f"ASMI tip.shape must be one of: {choices} (got {self.shape!r})."
            ) from None
        object.__setattr__(self, "shape", shape)
        if self.radius_mm is None:
            raise ValueError(
                f"ASMI tip.radius_mm is required for a {shape.value} tip."
            )
        if isinstance(self.radius_mm, bool) or not isinstance(
            self.radius_mm, (int, float)
        ):
            raise ValueError(
                f"ASMI tip.radius_mm must be a number in mm (got {self.radius_mm!r})."
            )
        if not math.isfinite(self.radius_mm) or self.radius_mm <= 0:
            raise ValueError(
                f"ASMI tip.radius_mm must be a positive number in mm "
                f"(got {self.radius_mm!r})."
            )
        object.__setattr__(self, "radius_mm", float(self.radius_mm))
        if self.material is not None and not isinstance(self.material, str):
            raise ValueError(
                f"ASMI tip.material must be text (got {self.material!r})."
            )

    @classmethod
    def from_config(cls, value: Any) -> Optional["IndenterTip"]:
        """Build a tip from the gantry YAML ``tip`` mapping, or ``None`` if unset."""
        if value is None or isinstance(value, IndenterTip):
            return value
        if not isinstance(value, Mapping):
            raise ValueError(
                "ASMI tip must be a mapping with `shape` and `radius_mm` "
                f"(got {type(value).__name__})."
            )
        unknown = sorted(set(value) - _TIP_FIELDS)
        if unknown:
            raise ValueError(
                f"ASMI tip has unknown field(s): {', '.join(unknown)}. "
                f"Allowed: {', '.join(sorted(_TIP_FIELDS))}."
            )
        if "shape" not in value:
            raise ValueError("ASMI tip.shape is required.")
        return cls(
            shape=value["shape"],
            radius_mm=value.get("radius_mm"),
            material=value.get("material"),
        )

    def result_fields(self) -> dict[str, Any]:
        return {
            "tip_shape": self.shape.value,
            "tip_radius_mm": self.radius_mm,
            "tip_material": self.material,
        }
