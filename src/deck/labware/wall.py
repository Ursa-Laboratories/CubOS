"""Simple rectangular obstacle on the deck defined by two corners."""

from __future__ import annotations

from pydantic import ConfigDict, Field, field_validator, model_validator

from .labware import BoundingBoxGeometry, Coordinate3D, Labware


class Wall(Labware):
    """Rectangular physical obstacle defined by two diagonally opposite corners.

    Walls have no slots, tips, or wells — they exist purely as geometry
    for bounds validation and collision avoidance.

    ``corner_1`` and ``corner_2`` must be diagonally opposite corners of
    the bounding box, with corner_1 < corner_2 on every axis.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    corner_1: Coordinate3D = Field(..., description="Diagonally opposite corner (lower x, y, z).")
    corner_2: Coordinate3D = Field(..., description="Diagonally opposite corner (upper x, y, z).")

    @field_validator("name")
    def _validate_name(cls, value: str) -> str:
        return Labware.validate_name(value)

    @model_validator(mode="after")
    def _validate_corners_and_set_geometry(self) -> "Wall":
        if self.corner_1.x >= self.corner_2.x:
            raise ValueError("corner_1.x must be < corner_2.x")
        if self.corner_1.y >= self.corner_2.y:
            raise ValueError("corner_1.y must be < corner_2.y")
        if self.corner_1.z >= self.corner_2.z:
            raise ValueError("corner_1.z must be < corner_2.z")
        self.geometry = BoundingBoxGeometry(
            length=self.length,
            width=self.width,
            height=self.height,
        )
        return self

    @property
    def x_min(self) -> float:
        return self.corner_1.x

    @property
    def x_max(self) -> float:
        return self.corner_2.x

    @property
    def y_min(self) -> float:
        return self.corner_1.y

    @property
    def y_max(self) -> float:
        return self.corner_2.y

    @property
    def z_min(self) -> float:
        return self.corner_1.z

    @property
    def z_max(self) -> float:
        return self.corner_2.z

    @property
    def length(self) -> float:
        return self.corner_2.x - self.corner_1.x

    @property
    def width(self) -> float:
        return self.corner_2.y - self.corner_1.y

    @property
    def height(self) -> float:
        return self.corner_2.z - self.corner_1.z

    def get_location(self, location_id: str | None = None) -> Coordinate3D:
        if location_id is None or location_id in {"location", "min"}:
            return self.corner_1
        if location_id == "max":
            return self.corner_2
        raise KeyError(f"Unknown location ID '{location_id}'")

    def get_initial_position(self) -> Coordinate3D:
        return self.corner_1

    def iter_positions(self) -> dict[str, Coordinate3D]:
        return {"min": self.corner_1, "max": self.corner_2}
