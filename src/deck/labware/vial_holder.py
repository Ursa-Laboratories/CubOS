from __future__ import annotations

from pydantic import Field, field_validator, model_validator

from .holder import HolderLabware
from .labware import Coordinate3D


class VialHolder(HolderLabware):
    """Holder for a linear array of vial slots."""

    model_name: str = "9VialHolder20mL_TightFit"
    length: float = 36.2
    width: float = 300.2
    height: float = 35.1
    labware_support_height: float = 35.1
    labware_seat_height_from_bottom: float = 18.0
    slot_count: int = Field(default=9, description="Maximum number of supported vial slots.")

    @field_validator("slot_count")
    def _validate_slot_count(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("slot_count must be positive.")
        return value

    @model_validator(mode="after")
    def _validate_slot_capacity(self) -> "VialHolder":
        if len(self.slots) > self.slot_count:
            raise ValueError("slots count must be <= slot_count.")
        return self

    def get_vial_slot(self, slot_id: str) -> Coordinate3D:
        return self.get_slot(slot_id)
