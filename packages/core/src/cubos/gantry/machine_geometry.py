"""Built-in machine geometry for supported gantry families."""

from __future__ import annotations

from dataclasses import dataclass

from .gantry_config import GantryConfig, GantryType


@dataclass(frozen=True)
class FixedStructureBox:
    """Fixed AABB machine structure in CubOS deck-frame coordinates."""

    name: str
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    z_min: float
    z_max: float

    def contains(self, x: float, y: float, z: float) -> bool:
        return (
            self.x_min <= x <= self.x_max
            and self.y_min <= y <= self.y_max
            and self.z_min <= z <= self.z_max
        )


CUB_XL_RIGHT_X_MAX_RAIL = FixedStructureBox(
    name="Cub XL right X-max rail",
    x_min=480.0,
    x_max=540.0,
    y_min=0.0,
    y_max=300.0,
    z_min=0.0,
    z_max=100.0,
)

_FIXED_STRUCTURES_BY_GANTRY_TYPE: dict[GantryType, tuple[FixedStructureBox, ...]] = {
    GantryType.CUB_XL: (CUB_XL_RIGHT_X_MAX_RAIL,),
}


def fixed_structures_for_gantry_type(
    gantry_type: GantryType | str,
) -> tuple[FixedStructureBox, ...]:
    """Return built-in fixed machine structures for a gantry family."""
    return _FIXED_STRUCTURES_BY_GANTRY_TYPE.get(GantryType(gantry_type), ())


def fixed_structures_for_gantry(
    gantry: GantryConfig | None,
) -> tuple[FixedStructureBox, ...]:
    """Return built-in fixed machine structures for a loaded gantry config."""
    if gantry is None:
        return ()
    return fixed_structures_for_gantry_type(gantry.gantry_type)
