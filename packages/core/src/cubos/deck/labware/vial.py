from __future__ import annotations

from typing import List, Optional

from pydantic import ConfigDict, Field, field_validator, model_validator

from .container_role import KNOWN_CONTAINER_ROLES
from .labware import BoundingBoxGeometry, Coordinate3D, Labware


class Vial(Labware):
    """
    Labware representing a single vial.
    """

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    name: str = Field(..., description="Unique vial name.")
    model_name: str = Field("", description="Vial model identifier.")
    height: float | None = Field(
        None,
        description=(
            "Optional vial outer height in millimeters (rim → underside). A "
            "physical dimension used by ``BoundingBoxGeometry`` for collision "
            "and visualization, not a Z coordinate. The deck-frame Z of the "
            "vial rim lives on ``location.z``."
        ),
    )
    diameter: float | None = Field(
        None,
        description="Optional vial outer diameter in millimeters.",
    )
    location: Coordinate3D = Field(
        ...,
        description=(
            "Absolute XYZ center of this vial. ``location.z`` is the "
            "deck-frame Z of the vial rim — the labware-surface reference "
            "for protocol-command labware-relative heights."
        ),
    )
    capacity_ul: float = Field(..., description="Vial capacity in microliters.")
    working_volume_ul: float = Field(..., description="Working volume per vial in microliters.")
    dead_volume_ul: float = Field(
        0.0,
        ge=0,
        description=(
            "Optional residual volume in microliters that cannot be "
            "aspirated (below the tip's physical reach or too shallow to "
            "draw cleanly). Defaults to 0 (no floor beyond the vial "
            "bottom). Used by state-derived aspiration height to keep the "
            "tip from descending into unreachable liquid, and by transfer "
            "preflight to reject requests that would draw the source below "
            "this floor."
        ),
    )
    role: Optional[str] = Field(
        default=None,
        description=(
            "Optional generic container role for automatic liquid-handling "
            "selection (see cubos.deck.labware.container_role); one of "
            "KNOWN_CONTAINER_ROLES (stock, waste, process, rinse). No "
            "machine-name branches ever key off this -- it is purely "
            "role-based selection metadata."
        ),
    )
    solution: Optional[str] = Field(
        default=None,
        description=(
            "Optional canonical solution identity (e.g. 'water'), distinct "
            "from any display alias. Stock selection matches a requested "
            "solution name against this field."
        ),
    )
    allowed_solutions: Optional[List[str]] = Field(
        default=None,
        description=(
            "Optional compatibility policy for waste containers: solutions "
            "this container may receive. Omitted/None means accept-all "
            "(the default). Only meaningful when role='waste'."
        ),
    )

    @field_validator("name")
    def _validate_non_empty_text(cls, value: str) -> str:
        return Labware.validate_name(value)

    @field_validator("role")
    def _validate_role(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in KNOWN_CONTAINER_ROLES:
            raise ValueError(
                f"role must be one of {sorted(KNOWN_CONTAINER_ROLES)}, got {value!r}."
            )
        return value

    @field_validator("solution")
    def _validate_solution(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not value.strip():
            raise ValueError("solution must be a non-empty string when provided.")
        return value

    @field_validator("allowed_solutions")
    def _validate_allowed_solutions(
        cls, value: Optional[List[str]],
    ) -> Optional[List[str]]:
        if value is None:
            return value
        if not value:
            raise ValueError("allowed_solutions, when provided, must be non-empty.")
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise ValueError("allowed_solutions entries must be non-empty strings.")
        return value

    @field_validator("capacity_ul", "working_volume_ul")
    def _validate_positive_volume(cls, value: float, info):  # type: ignore[override]
        if value <= 0:
            raise ValueError(f"{info.field_name} must be positive.")
        return value

    @model_validator(mode="after")
    def _validate_working_le_capacity(self) -> "Vial":
        if self.working_volume_ul > self.capacity_ul:
            raise ValueError("working_volume_ul must be <= capacity_ul.")
        if self.dead_volume_ul > self.working_volume_ul:
            raise ValueError("dead_volume_ul must be <= working_volume_ul.")
        self.geometry = BoundingBoxGeometry(
            length=self.diameter,
            width=self.diameter,
            height=self.height,
        )
        return self

    @field_validator("height", "diameter")
    def _validate_positive_dimension(
        cls,
        value: float | None,
        info,
    ):  # type: ignore[override]
        if value is not None and value <= 0:
            raise ValueError(f"{info.field_name} must be positive.")
        return value

    def get_location(self, location_id: str | None = None) -> Coordinate3D:
        if location_id is None or location_id == self.name:
            return self.location
        raise KeyError(f"Unknown location ID '{location_id}'")

    def get_vial_center(self) -> Coordinate3D:
        return self.location

    def get_initial_position(self) -> Coordinate3D:
        """
        Initial position for a single vial is its center location.
        """
        return self.location

    def iter_positions(self) -> dict[str, Coordinate3D]:
        return {"location": self.location}
