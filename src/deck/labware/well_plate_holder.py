from __future__ import annotations

from pydantic import Field, field_validator, model_validator

from .holder import HolderLabware
from .labware import Coordinate3D


class WellPlateHolder(HolderLabware):
    """Holder for a single well plate or slide-mounted plate assembly."""

    model_name: str = "SlideHolder_Top"
    length: float = 100.0
    width: float = 155.0
    height: float = 14.8
    labware_support_height: float = 10.0
    labware_seat_height_from_bottom: float = 5.0
    well_plate_surface_height_from_bottom: float | None = Field(
        default=None,
        description=(
            "Vertical distance from holder bottom to the nested plate's "
            "calibrated well/rim surface. When omitted, nested plates use "
            "labware_seat_height_from_bottom for backward compatibility."
        ),
    )

    @field_validator("well_plate_surface_height_from_bottom")
    def _validate_surface_height(cls, value: float | None) -> float | None:
        if value is not None and value <= 0:
            raise ValueError(
                "well_plate_surface_height_from_bottom must be positive."
            )
        return value

    @model_validator(mode="after")
    def _validate_surface_not_below_seat(self) -> "WellPlateHolder":
        surface_height = self.well_plate_surface_height_from_bottom
        seat_height = self.labware_seat_height_from_bottom
        if (
            surface_height is not None
            and seat_height is not None
            and surface_height < seat_height
        ):
            raise ValueError(
                "well_plate_surface_height_from_bottom must be >= "
                "labware_seat_height_from_bottom."
            )
        return self

    def get_plate_slot(self, slot_id: str = "plate") -> Coordinate3D:
        return self.get_slot(slot_id)
