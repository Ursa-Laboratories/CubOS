"""Strict Pydantic schemas for deck YAML."""

from __future__ import annotations

from typing import Annotated, Dict, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _YamlPoint3D(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: float
    y: float
    z: Optional[float] = None


class _YamlCalibrationPoints(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Preferred location for A1 in deck YAML.
    a1: Optional[_YamlPoint3D] = None
    a2: _YamlPoint3D


class WellPlateYamlEntry(BaseModel):
    """Strict schema for one well plate in deck labware."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    type: Literal["well_plate"] = "well_plate"
    name: str
    model_name: str = ""
    rows: int = Field(..., gt=0)
    columns: int = Field(..., gt=0)
    # Geometry — optional metadata, not used for well position computation.
    length: Optional[float] = Field(default=None, gt=0)
    width: Optional[float] = Field(default=None, gt=0)
    height: Optional[float] = Field(default=None, gt=0)
    # Inside well depth from rim (calibration anchor) to inside floor where
    # the sample sits. Distinct from `height` (outer plate height): outer
    # and inside depth differ by a few millimeters depending on well-bottom
    # geometry and skirt thickness. External analysis consumers compute the
    # sample-floor Z as the deck-frame rim Z minus this depth.
    well_depth: Optional[float] = Field(default=None, gt=0)
    # Backward compatibility: top-level A1 is accepted but deprecated.
    a1: Optional[_YamlPoint3D] = None
    calibration: _YamlCalibrationPoints
    x_offset: float = Field(..., gt=0)
    y_offset: float = Field(..., gt=0)
    # Volume — optional metadata.
    capacity_ul: Optional[float] = None
    working_volume_ul: Optional[float] = None

    @property
    def a1_point(self) -> _YamlPoint3D:
        """Return canonical A1 point, preferring calibration.a1."""
        a1 = self.calibration.a1 or self.a1
        if a1 is None:
            raise ValueError("Calibration must define `a1` (prefer `calibration.a1`).")
        return a1

    @model_validator(mode="after")
    def _validate_two_point_calibration(self) -> "WellPlateYamlEntry":
        a1, a2 = self.a1_point, self.calibration.a2
        if a1.x == a2.x and a1.y == a2.y:
            raise ValueError("Calibration points A1 and A2 must not be identical.")
        same_x = abs(a1.x - a2.x) < 1e-9
        same_y = abs(a1.y - a2.y) < 1e-9
        if not same_x and not same_y:
            raise ValueError(
                "Calibration A2 must be axis-aligned with A1 (same x or same y); diagonal orientation is invalid."
            )
        if self.capacity_ul is not None and self.capacity_ul <= 0:
            raise ValueError("capacity_ul must be positive when specified.")
        if self.working_volume_ul is not None and self.working_volume_ul <= 0:
            raise ValueError("working_volume_ul must be positive when specified.")
        if (self.capacity_ul is not None and self.working_volume_ul is not None
                and self.working_volume_ul > self.capacity_ul):
            raise ValueError("working_volume_ul must be <= capacity_ul.")
        if (self.well_depth is not None and self.height is not None
                and self.well_depth > self.height):
            raise ValueError(
                f"well_depth ({self.well_depth}) must be <= height "
                f"({self.height}) — inside floor cannot sit below the plate "
                f"underside."
            )
        return self


class VialYamlEntry(BaseModel):
    """Strict schema for one vial labware in deck labware."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    type: Literal["vial"] = "vial"
    name: str
    model_name: str = ""
    height: float
    diameter: float
    location: _YamlPoint3D
    capacity_ul: float
    working_volume_ul: float

    @model_validator(mode="after")
    def _validate_vial_volumes(self) -> "VialYamlEntry":
        if self.working_volume_ul > self.capacity_ul:
            raise ValueError("working_volume_ul must be <= capacity_ul.")
        if self.capacity_ul <= 0 or self.working_volume_ul <= 0:
            raise ValueError("capacity_ul and working_volume_ul must be positive.")
        return self


class NestedVialYamlEntry(BaseModel):
    """Schema for a vial positioned inside a holder."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    name: Optional[str] = None
    model_name: str = ""
    height: float
    diameter: float
    location: _YamlPoint3D
    capacity_ul: float
    working_volume_ul: float

    @model_validator(mode="after")
    def _validate_nested_vial(self) -> "NestedVialYamlEntry":
        if self.location.z is not None:
            raise ValueError("Nested vial location.z is derived from holder seat height and must be omitted.")
        if self.capacity_ul <= 0 or self.working_volume_ul <= 0:
            raise ValueError("capacity_ul and working_volume_ul must be positive.")
        if self.working_volume_ul > self.capacity_ul:
            raise ValueError("working_volume_ul must be <= capacity_ul.")
        return self


class NestedWellPlateYamlEntry(BaseModel):
    """Schema for a well plate positioned inside a holder."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    name: Optional[str] = None
    model_name: str = ""
    rows: int = Field(..., gt=0)
    columns: int = Field(..., gt=0)
    length: Optional[float] = Field(default=None, gt=0)
    width: Optional[float] = Field(default=None, gt=0)
    height: Optional[float] = Field(default=None, gt=0)
    well_depth: Optional[float] = Field(default=None, gt=0)
    calibration: _YamlCalibrationPoints
    x_offset: float = Field(..., gt=0)
    y_offset: float = Field(..., gt=0)
    capacity_ul: Optional[float] = None
    working_volume_ul: Optional[float] = None

    @property
    def a1_point(self) -> _YamlPoint3D:
        a1 = self.calibration.a1
        if a1 is None:
            raise ValueError("Nested well plate calibration must define `a1`.")
        return a1

    @model_validator(mode="after")
    def _validate_nested_well_plate(self) -> "NestedWellPlateYamlEntry":
        a1 = self.a1_point
        a2 = self.calibration.a2
        if a1.z is not None or a2.z is not None:
            raise ValueError("Nested well plate calibration z is derived from holder seat height and must be omitted.")
        if a1.x == a2.x and a1.y == a2.y:
            raise ValueError("Calibration points A1 and A2 must not be identical.")
        same_x = abs(a1.x - a2.x) < 1e-9
        same_y = abs(a1.y - a2.y) < 1e-9
        if not same_x and not same_y:
            raise ValueError(
                "Calibration A2 must be axis-aligned with A1 (same x or same y); diagonal orientation is invalid."
            )
        if self.capacity_ul is not None and self.capacity_ul <= 0:
            raise ValueError("capacity_ul must be positive when specified.")
        if self.working_volume_ul is not None and self.working_volume_ul <= 0:
            raise ValueError("working_volume_ul must be positive when specified.")
        if (
            self.capacity_ul is not None
            and self.working_volume_ul is not None
            and self.working_volume_ul > self.capacity_ul
        ):
            raise ValueError("working_volume_ul must be <= capacity_ul.")
        if (self.well_depth is not None and self.height is not None
                and self.well_depth > self.height):
            raise ValueError(
                f"well_depth ({self.well_depth}) must be <= height "
                f"({self.height}) — inside floor cannot sit below the plate "
                f"underside."
            )
        return self


class _YamlHolderSlot(BaseModel):
    """Strict schema for an addressable holder slot."""

    model_config = ConfigDict(extra="forbid")

    location: _YamlPoint3D
    supported_labware_types: tuple[str, ...] = ()
    description: Optional[str] = None


class _BaseHolderYamlEntry(BaseModel):
    """Common schema for non-liquid physical holder fixtures.

    Bounding-box and seat-geometry fields are optional at the YAML layer:
    when omitted, the corresponding Python class's defaults are used. This
    lets simple deck YAMLs stay small while still allowing a definition
    config (see ``labware/definitions/``) to fully specify a physical part.
    """

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    name: str
    model_name: str
    location: _YamlPoint3D
    slots: Dict[str, _YamlHolderSlot] = Field(default_factory=dict)
    # Holder geometry — fall through to the Python class defaults if unset.
    length: Optional[float] = Field(default=None, gt=0)
    width: Optional[float] = Field(default=None, gt=0)
    height: Optional[float] = Field(default=None, gt=0)
    labware_support_height: Optional[float] = Field(default=None, gt=0)
    labware_seat_height_from_bottom: Optional[float] = Field(default=None, gt=0)


class TipRackYamlEntry(_BaseHolderYamlEntry):
    """Strict schema for one tip rack.

    Tip pickup positions are derived from a two-point calibration + pitch
    offsets, mirroring the well plate schema. ``location`` is optional and
    derived from the A1 tip when omitted.
    """

    type: Literal["tip_rack"] = "tip_rack"
    model_name: str = "tip_rack"
    rows: int = Field(..., gt=0, le=26)
    columns: int = Field(..., gt=0)
    pickup_z: float = Field(..., gt=0)
    drop_z: Optional[float] = Field(default=None, gt=0)
    calibration: _YamlCalibrationPoints
    x_offset: float = Field(..., gt=0)
    y_offset: float = Field(..., gt=0)
    tip_present: Dict[str, bool] = Field(default_factory=dict)
    # Derived from the A1 tip if omitted.
    location: Optional[_YamlPoint3D] = None  # type: ignore[assignment]

    @property
    def a1_point(self) -> _YamlPoint3D:
        """Return the A1 calibration point (required)."""
        a1 = self.calibration.a1
        if a1 is None:
            raise ValueError("Tip rack calibration must define `a1`.")
        return a1

    @model_validator(mode="after")
    def _validate_tip_rack_calibration(self) -> "TipRackYamlEntry":
        a1, a2 = self.a1_point, self.calibration.a2
        if a1.x == a2.x and a1.y == a2.y:
            raise ValueError("Calibration points A1 and A2 must not be identical.")
        same_x = abs(a1.x - a2.x) < 1e-9
        same_y = abs(a1.y - a2.y) < 1e-9
        if not same_x and not same_y:
            raise ValueError(
                "Calibration A2 must be axis-aligned with A1 (same x or same y); "
                "diagonal orientation is invalid."
            )
        return self


class TipDisposalYamlEntry(_BaseHolderYamlEntry):
    type: Literal["tip_disposal"] = "tip_disposal"
    model_name: str = "tip_disposal"


class WallYamlEntry(BaseModel):
    """Rectangular obstacle defined by two opposite corners."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["wall"] = "wall"
    name: str
    corner_1: _YamlPoint3D
    corner_2: _YamlPoint3D


class WellPlateHolderYamlEntry(_BaseHolderYamlEntry):
    type: Literal["well_plate_holder"] = "well_plate_holder"
    model_name: str = "SlideHolder_Top"
    well_plate: Optional[NestedWellPlateYamlEntry] = None

    @model_validator(mode="after")
    def _validate_single_nested_plate(self) -> "WellPlateHolderYamlEntry":
        if self.well_plate is None:
            return self
        return self


class VialHolderYamlEntry(_BaseHolderYamlEntry):
    type: Literal["vial_holder"] = "vial_holder"
    model_name: str = "9VialHolder20mL_TightFit"
    slot_count: int = Field(default=9, gt=0)
    vials: Dict[str, NestedVialYamlEntry] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_slot_capacity(self) -> "VialHolderYamlEntry":
        if len(self.slots) > self.slot_count:
            raise ValueError("slots count must be <= slot_count.")
        if len(self.vials) > self.slot_count:
            raise ValueError("vials count must be <= slot_count.")
        return self


LabwareYamlEntry = Annotated[
    Union[
        WellPlateYamlEntry,
        VialYamlEntry,
        TipRackYamlEntry,
        TipDisposalYamlEntry,
        WallYamlEntry,
        WellPlateHolderYamlEntry,
        VialHolderYamlEntry,
    ],
    Field(discriminator="type"),
]


class DeckYamlSchema(BaseModel):
    """Root deck YAML schema: only 'labware' key allowed."""

    model_config = ConfigDict(extra="forbid")

    labware: Dict[str, LabwareYamlEntry] = Field(
        ..., description="Mapping of labware key to well_plate or vial entry."
    )
