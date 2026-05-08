from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import ConfigDict, Field, field_validator, model_validator

from .labware import BoundingBoxGeometry, Coordinate3D, Labware


class WellPlate(Labware):
    """
    Labware representing a multi-well plate (e.g. SBS 96-well).

    Coordinates for each well are expressed as absolute deck coordinates.
    """

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    name: str = Field(..., description="Unique well plate name.")
    model_name: str = Field("", description="Well plate model identifier.")
    # Geometry — optional metadata, not used for well position computation.
    length: Optional[float] = Field(None, description="Overall plate length in millimeters.")
    width: Optional[float] = Field(None, description="Overall plate width in millimeters.")
    height: Optional[float] = Field(
        None,
        description=(
            "Outer plate height in millimeters — calibration rim to underside "
            "of the plate (including skirt/feet). A dimension, not a deck-frame "
            "Z coordinate."
        ),
    )
    well_depth: Optional[float] = Field(
        None,
        description=(
            "Inside well depth in millimeters from the calibration rim to the "
            "inside floor where the sample sits. Distinct from `height` "
            "(outer plate height): outer and inside depth differ by a few "
            "millimeters depending on well-bottom geometry and skirt thickness. "
            "External analysis consumers use it to compute the sample-floor Z "
            "from the deck-frame rim Z."
        ),
    )
    rows: int = Field(
        ...,
        gt=0,
        le=26,
        description="Number of well rows (e.g. 8 for 96-well). Max 26 (A-Z).",
    )
    columns: int = Field(..., gt=0, description="Number of well columns (e.g. 12 for 96-well).")
    wells: Dict[str, Coordinate3D] = Field(
        ...,
        description="Mapping from well ID (e.g. 'A1') to absolute XYZ centers.",
    )
    # Volume — optional metadata.
    capacity_ul: Optional[float] = Field(None, description="Well capacity in microliters.")
    working_volume_ul: Optional[float] = Field(None, description="Working volume per well in microliters.")

    @field_validator("name")
    def _validate_non_empty_text(cls, value: str) -> str:
        return Labware.validate_name(value)

    @field_validator("capacity_ul", "working_volume_ul")
    def _validate_positive_volume(cls, value: Optional[float], info):  # type: ignore[override]
        if value is not None and value <= 0:
            raise ValueError(f"{info.field_name} must be positive.")
        return value

    @model_validator(mode="after")
    def _validate_working_le_capacity(self) -> "WellPlate":
        if (self.capacity_ul is not None and self.working_volume_ul is not None
                and self.working_volume_ul > self.capacity_ul):
            raise ValueError("working_volume_ul must be <= capacity_ul.")
        return self

    @model_validator(mode="after")
    def _validate_well_depth_le_height(self) -> "WellPlate":
        # Inside well depth cannot exceed outer plate height; physically the
        # inside floor sits *above* the underside of the plate by at least the
        # bottom-wall thickness. Catches the realistic miscalibration bug
        # (e.g. swapped values) that gt=0 alone wouldn't.
        if (
            self.well_depth is not None
            and self.height is not None
            and self.well_depth > self.height
        ):
            raise ValueError(
                f"well_depth ({self.well_depth}) must be <= height "
                f"({self.height}) — inside floor cannot sit below the plate "
                f"underside."
            )
        return self

    @field_validator("length", "width", "well_depth")
    def _validate_positive_dimension(cls, value: Optional[float], info):  # type: ignore[override]
        if value is not None and value <= 0:
            raise ValueError(f"{info.field_name} must be positive.")
        return value

    @model_validator(mode="before")
    def _validate_wells(cls, data):
        wells: Dict[str, Coordinate3D] = data.get("wells") or {}
        if not wells:
            raise ValueError("WellPlate must define at least one well.")

        # Ensure the anchor well A1 exists so we can use it as the initial position.
        if "A1" not in wells:
            raise ValueError("WellPlate must define an 'A1' well for anchoring.")

        return data

    @model_validator(mode="after")
    def _validate_well_count(self) -> "WellPlate":
        expected_well_count = self.rows * self.columns
        if len(self.wells) != expected_well_count:
            raise ValueError(
                f"WellPlate wells count must equal rows*columns ({expected_well_count}), got {len(self.wells)}."
            )
        # ``height`` is the plate's physical outer dimension (rim →
        # underside). The deck-frame Z of the plate surface is carried
        # on each well's coordinate (set by calibration). The geometry
        # below carries only XY footprint metadata; bounding-box height
        # would conflate the dimension with the surface Z.
        self.geometry = BoundingBoxGeometry(
            length=self.length,
            width=self.width,
        )
        return self

    def get_location(self, location_id: str | None = None) -> Coordinate3D:
        if location_id is None:
            raise KeyError("WellPlate location_id is required, e.g. 'A1'.")
        return self.get_well_center(location_id)

    def get_well_center(self, well_id: str) -> Coordinate3D:
        """
        Convenience wrapper to fetch a well center by ID.
        """
        try:
            return self.wells[well_id]
        except KeyError as exc:
            raise KeyError(f"Unknown well ID '{well_id}'") from exc

    def get_initial_position(self) -> Coordinate3D:
        """
        Initial position for a well plate: the A1 well.
        """
        # By construction, 'A1' must exist in `wells`.
        return self.get_well_center("A1")

    def iter_positions(self) -> dict[str, Coordinate3D]:
        return dict(self.wells)


def generate_wells_from_offsets(
    *,
    row_labels: List[str],
    column_indices: List[int],
    a1_center: Coordinate3D,
    x_offset: float,
    y_offset: float,
    rounding_decimals: int = 3,
) -> Dict[str, Coordinate3D]:
    """
    Generate a complete well-position mapping from an A1 anchor and per-step offsets.

    This mirrors the classic well-to-XY logic:
      - row index is derived from row_labels (e.g. ['A','B',...])
      - column index is derived from column_indices (e.g. [1,2,...,12])
      - each step in X/Y applies the configured offsets
    """
    wells: Dict[str, Coordinate3D] = {}

    for row_idx, row_label in enumerate(row_labels):
        for col_idx, col_num in enumerate(column_indices):
            well_id = f"{row_label}{col_num}"

            x = a1_center.x + x_offset * col_idx
            y = a1_center.y + y_offset * row_idx
            z = a1_center.z

            wells[well_id] = Coordinate3D(
                x=round(x, rounding_decimals),
                y=round(y, rounding_decimals),
                z=round(z, rounding_decimals),
            )

    return wells
