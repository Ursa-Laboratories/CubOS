from __future__ import annotations

from typing import Dict

from pydantic import ConfigDict, Field, field_validator, model_validator

from .labware import BoundingBoxGeometry, Coordinate3D, Labware


class LabwareSlot(Labware):
    """
    Addressable placement point inside a holder.

    The slot stores only deck-space metadata for now. Future work can attach
    occupancy, collision geometry, or compatibility rules here without having
    to change the holder API.
    """

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    location: Coordinate3D = Field(..., description="Absolute XYZ location for this slot.")
    supported_labware_types: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Optional labware type names that this slot is intended to accept.",
    )
    description: str | None = Field(default=None, description="Optional free-text note.")

    @field_validator("supported_labware_types")
    def _validate_supported_labware_types(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip() for item in value)
        if any(not item for item in normalized):
            raise ValueError("supported_labware_types entries must be non-empty strings.")
        return normalized

    def get_location(self, location_id: str | None = None) -> Coordinate3D:
        if location_id is None or location_id in {"location", "anchor"}:
            return self.location
        raise KeyError(f"Unknown location ID '{location_id}'")

    def get_initial_position(self) -> Coordinate3D:
        return self.location

    def iter_positions(self) -> dict[str, Coordinate3D]:
        return {"location": self.location}

    @model_validator(mode="after")
    def _set_slot_geometry(self) -> "LabwareSlot":
        self.geometry = BoundingBoxGeometry()
        return self


class HolderLabware(Labware):
    """Base class for physical deck fixtures defined by a bounding box."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    name: str = Field(..., description="Unique holder name.")
    model_name: str = Field(..., description="Holder model identifier.")
    location: Coordinate3D = Field(..., description="Absolute XYZ reference point for this holder.")
    length_mm: float = Field(..., description="Bounding-box X dimension in millimeters.")
    width_mm: float = Field(..., description="Bounding-box Y dimension in millimeters.")
    height_mm: float = Field(..., description="Bounding-box Z dimension in millimeters.")
    labware_support_height_mm: float | None = Field(
        default=None,
        description=(
            "Total height of the holder sub-geometry that physically supports the nested labware. "
            "This may differ from the overall collision-envelope height_mm for multi-part fixtures."
        ),
    )
    labware_seat_height_from_bottom_mm: float | None = Field(
        default=None,
        description="Vertical distance from the holder bottom to the seated labware support surface.",
    )
    slots: Dict[str, LabwareSlot] = Field(
        default_factory=dict,
        description="Optional addressable placement slots defined inside the holder.",
    )
    contained_labware: Dict[str, Labware] = Field(
        default_factory=dict,
        description="Optional nested labware instances whose Z is derived from this holder.",
    )

    @field_validator("name", "model_name")
    def _validate_non_empty_text(cls, value: str) -> str:
        return Labware.validate_name(value)

    @field_validator(
        "length_mm",
        "width_mm",
        "height_mm",
        "labware_support_height_mm",
        "labware_seat_height_from_bottom_mm",
    )
    def _validate_positive_dimension(cls, value: float, info):  # type: ignore[override]
        if value is not None and value <= 0:
            raise ValueError(f"{info.field_name} must be positive.")
        return value

    @field_validator("slots")
    def _validate_slot_names(cls, value: Dict[str, LabwareSlot]) -> Dict[str, LabwareSlot]:
        for slot_name in value:
            if not slot_name.strip():
                raise ValueError("Holder slot names must be non-empty strings.")
        return value

    @field_validator("contained_labware")
    def _validate_contained_labware_names(cls, value: Dict[str, Labware]) -> Dict[str, Labware]:
        for child_name in value:
            if not child_name.strip():
                raise ValueError("Contained labware names must be non-empty strings.")
        return value

    @model_validator(mode="after")
    def _validate_labware_support_geometry(self) -> "HolderLabware":
        if self.labware_support_height_mm is not None and self.labware_support_height_mm > self.height_mm:
            raise ValueError("labware_support_height_mm must be <= height_mm.")
        if (
            self.labware_support_height_mm is not None
            and self.labware_seat_height_from_bottom_mm is not None
            and self.labware_seat_height_from_bottom_mm > self.labware_support_height_mm
        ):
            raise ValueError(
                "labware_seat_height_from_bottom_mm must be <= labware_support_height_mm."
            )
        self.geometry = BoundingBoxGeometry(
            length_mm=self.length_mm,
            width_mm=self.width_mm,
            height_mm=self.height_mm,
        )
        return self

    def get_location(self, location_id: str | None = None) -> Coordinate3D:
        if location_id is None or location_id in {"location", "anchor", self.name}:
            return self.location

        if "." in location_id:
            child_name, child_location_id = location_id.split(".", 1)
            try:
                return self.contained_labware[child_name].get_location(child_location_id)
            except KeyError as exc:
                raise KeyError(f"Unknown location ID '{location_id}'") from exc

        if location_id in self.contained_labware:
            return self.contained_labware[location_id].get_initial_position()

        try:
            return self.slots[location_id].location
        except KeyError as exc:
            raise KeyError(f"Unknown location ID '{location_id}'") from exc

    def get_slot(self, slot_id: str) -> Coordinate3D:
        return self.get_location(slot_id)

    def get_initial_position(self) -> Coordinate3D:
        return self.location

    def iter_positions(self) -> dict[str, Coordinate3D]:
        positions = {"location": self.location}
        positions.update({slot_id: slot.location for slot_id, slot in self.slots.items()})
        for child_name, child in self.contained_labware.items():
            positions[child_name] = child.get_initial_position()
            for position_id, coord in child.iter_positions().items():
                if position_id == "location":
                    continue
                positions[f"{child_name}.{position_id}"] = coord
        return positions
