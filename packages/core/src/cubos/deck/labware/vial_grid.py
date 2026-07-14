from __future__ import annotations

from typing import Dict

from pydantic import ConfigDict, Field, field_validator, model_validator

from .labware import Coordinate3D, Labware
from .vial import Vial


class VialGrid(Labware):
    """A flat, addressable collection of vials.

    ``vials`` contains only canonical position IDs. ``aliases`` provides
    compatibility or operator-friendly names that resolve to those canonical
    IDs without creating additional positions. Each vial retains its own exact
    coordinate, volume metadata, and optional physical geometry.
    """

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    name: str = Field(..., description="Stable runtime name for this vial grid.")
    model_name: str = Field("", description="Vial-grid model identifier.")
    label: str | None = Field(
        default=None,
        description="Optional display label; never used for addressing or identity.",
    )
    rows: int | None = Field(
        default=None,
        gt=0,
        le=26,
        description="Optional number of grid rows.",
    )
    columns: int | None = Field(
        default=None,
        gt=0,
        description="Optional number of grid columns.",
    )
    vials: Dict[str, Vial] = Field(
        ...,
        description="Canonical position ID to exact vial runtime model.",
    )
    aliases: Dict[str, str] = Field(
        default_factory=dict,
        description="Alias to canonical vial position ID.",
    )

    @field_validator("name")
    def _validate_non_empty_name(cls, value: str) -> str:
        return Labware.validate_name(value)

    @field_validator("label")
    def _validate_optional_label(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("VialGrid label must be a non-empty string when provided.")
        return value

    @field_validator("vials")
    def _validate_vial_ids(cls, value: Dict[str, Vial]) -> Dict[str, Vial]:
        if not value:
            raise ValueError("VialGrid must define at least one vial.")
        for position_id in value:
            if not position_id or not position_id.strip():
                raise ValueError("VialGrid position IDs must be non-empty strings.")
        return value

    @model_validator(mode="after")
    def _validate_layout_and_aliases(self) -> "VialGrid":
        if (self.rows is None) != (self.columns is None):
            raise ValueError("VialGrid rows and columns must be provided together.")
        if (
            self.rows is not None
            and self.columns is not None
            and self.rows * self.columns != len(self.vials)
        ):
            raise ValueError(
                "VialGrid vial count must equal rows*columns "
                f"({self.rows * self.columns}), got {len(self.vials)}."
            )

        for alias, canonical_id in self.aliases.items():
            if not alias or not alias.strip():
                raise ValueError("VialGrid aliases must be non-empty strings.")
            if alias in self.vials:
                raise ValueError(
                    f"VialGrid alias {alias!r} conflicts with a canonical position ID."
                )
            if canonical_id not in self.vials:
                raise ValueError(
                    f"VialGrid alias {alias!r} targets unknown canonical position "
                    f"{canonical_id!r}."
                )
        return self

    @property
    def canonical_position_ids(self) -> tuple[str, ...]:
        """Return canonical position IDs in their defined order."""
        return tuple(self.vials)

    def canonicalize_location_id(self, location_id: str) -> str:
        """Resolve a canonical ID or alias to the canonical position ID."""
        if location_id in self.vials:
            return location_id
        try:
            return self.aliases[location_id]
        except KeyError as exc:
            raise KeyError(f"Unknown vial-grid location ID {location_id!r}") from exc

    def get_vial(self, location_id: str) -> Vial:
        """Return the vial at a canonical position ID or alias."""
        return self.vials[self.canonicalize_location_id(location_id)]

    def get_location(self, location_id: str | None = None) -> Coordinate3D:
        if location_id is None:
            raise KeyError("VialGrid location_id is required, e.g. 'A1'.")
        return self.get_vial(location_id).location

    def get_initial_position(self) -> Coordinate3D:
        """Return A1 when present, otherwise the first defined vial position."""
        position_id = "A1" if "A1" in self.vials else next(iter(self.vials))
        return self.vials[position_id].location

    def iter_positions(self) -> dict[str, Coordinate3D]:
        """Return canonical positions only; aliases never duplicate locations."""
        return {
            position_id: vial.location
            for position_id, vial in self.vials.items()
        }
