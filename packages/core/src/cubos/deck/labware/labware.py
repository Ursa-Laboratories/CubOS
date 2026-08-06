from __future__ import annotations

import math
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Coordinate3D(BaseModel):
    """Simple 3D coordinate representation in deck space (absolute gantry coordinates)."""

    model_config = ConfigDict(extra="forbid")

    x: float
    y: float
    z: float

    @field_validator("x", "y", "z")
    def _validate_finite(cls, value: float, info):  # type: ignore[override]
        if not math.isfinite(value):
            raise ValueError(f"{info.field_name} must be finite (not NaN/Inf).")
        return value


class BoundingBoxGeometry(BaseModel):
    """Axis-aligned bounding-box geometry metadata for a labware item."""

    model_config = ConfigDict(extra="forbid")

    length: float | None = Field(default=None, description="Bounding-box X dimension.")
    width: float | None = Field(default=None, description="Bounding-box Y dimension.")
    height: float | None = Field(default=None, description="Bounding-box Z dimension.")

    @field_validator("length", "width", "height")
    def _validate_positive_dimension(cls, value: float | None, info):  # type: ignore[override]
        if value is not None and value <= 0:
            raise ValueError(f"{info.field_name} must be positive.")
        return value


BottomShape = Literal["flat", "round", "v"]


class CircularWellGeometry(BaseModel):
    """Lateral geometry of a single circular well."""

    model_config = ConfigDict(extra="forbid")

    shape: Literal["circular"] = "circular"
    diameter: float = Field(..., gt=0, description="Well inner diameter in millimeters.")
    bottom: BottomShape = Field("flat", description="Well bottom profile.")

    @property
    def cross_section_area_mm2(self) -> float:
        return math.pi * (self.diameter / 2.0) ** 2

    @property
    def inscribed_radius_mm(self) -> float:
        """Largest radius from the well center that stays inside the wall."""
        return self.diameter / 2.0


class RectangularWellGeometry(BaseModel):
    """Lateral geometry of a single square or rectangular well."""

    model_config = ConfigDict(extra="forbid")

    shape: Literal["rectangular"] = "rectangular"
    x_dimension: float = Field(..., gt=0, description="Well inner X width in millimeters.")
    y_dimension: float = Field(..., gt=0, description="Well inner Y width in millimeters.")
    bottom: BottomShape = Field("flat", description="Well bottom profile.")

    @property
    def cross_section_area_mm2(self) -> float:
        return self.x_dimension * self.y_dimension

    @property
    def inscribed_radius_mm(self) -> float:
        return min(self.x_dimension, self.y_dimension) / 2.0


# Discriminated on ``shape`` so each variant's required fields are enforced
# independently: illegal states (a circular well carrying `x_dimension`, a
# rectangular well missing `y_dimension`) are unrepresentable rather than
# validated after the fact. Consumers should read `cross_section_area_mm2` /
# `inscribed_radius_mm` and never branch on `shape`; adding a new well shape
# is then purely additive.
WellGeometry = Annotated[
    Union[CircularWellGeometry, RectangularWellGeometry],
    Field(discriminator="shape"),
]


class Labware(BaseModel):
    """
    Base behavior shared by all labware models.

    Concrete labware classes define their own required fields so users can inspect
    each class directly and understand exactly what YAML attributes are required.
    """

    model_config = ConfigDict(extra="forbid")

    geometry: BoundingBoxGeometry = Field(
        default_factory=BoundingBoxGeometry,
        description="Shared geometry metadata for this labware.",
    )

    @staticmethod
    def validate_name(value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Labware name must be a non-empty string.")
        return value

    def get_location(self, location_id: str | None = None) -> Coordinate3D:
        """Return an absolute deck coordinate for this labware."""
        raise NotImplementedError("Subclasses of Labware must implement get_location().")

    def get_initial_position(self) -> Coordinate3D:
        """
        Return the labware-level initial/anchor position.

        Subclasses are expected to override this.
        """
        raise NotImplementedError(
            "Subclasses of Labware must implement get_initial_position()."
        )

    def iter_positions(self) -> dict[str, Coordinate3D]:
        """
        Return every named deck position exposed by this labware.

        This is used by generic validators that need to reason about all
        addressable points without hard-coding concrete labware types.
        """
        raise NotImplementedError("Subclasses of Labware must implement iter_positions().")
