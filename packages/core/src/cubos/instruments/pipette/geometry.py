"""Eight-channel mounting geometry, relative to the first bare nozzle."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EightChannelGeometry(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    axis: Literal["x", "y"]
    spacing_mm: float = Field(default=9.0, gt=0, strict=True)
    length_mm: float = Field(gt=0, strict=True)
    width_mm: float = Field(gt=0, strict=True)
    height_mm: float = Field(gt=0, strict=True)

    @model_validator(mode="after")
    def _covers_nozzles(self) -> "EightChannelGeometry":
        if self.length_mm <= 7 * self.spacing_mm:
            raise ValueError("length_mm must exceed the span of all eight nozzles (7 × spacing_mm).")
        return self

    @property
    def xy_bounds(self) -> tuple[float, float, float, float]:
        span = 7 * self.spacing_mm
        overhang = (self.length_mm - span) / 2
        along = (-overhang, span + overhang)
        across = (-self.width_mm / 2, self.width_mm / 2)
        return (*along, *across) if self.axis == "x" else (*across, *along)

    @property
    def reference_tip(self) -> str:
        return "leftmost" if self.axis == "x" else "frontmost"


def resolve_channel_geometry(channels: int, value: dict | None) -> EightChannelGeometry | None:
    if channels == 8:
        if value is None:
            raise ValueError("8-channel pipettes require channel_geometry with axis and measured length_mm, width_mm, height_mm.")
        return EightChannelGeometry.model_validate(value)
    if value is not None:
        raise ValueError("channel_geometry is only supported for 8-channel pipettes.")
    return None
