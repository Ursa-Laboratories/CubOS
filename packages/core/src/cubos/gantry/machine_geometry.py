"""Built-in machine geometry for supported gantry families."""

from __future__ import annotations

from dataclasses import dataclass

from .gantry_config import GantryConfig, GantryType, OriginPolicy


@dataclass(frozen=True)
class FixedStructureBox:
    """Fixed AABB machine structure.

    Coordinates are in whichever signed frame the caller requested them in
    (CubOS deck-frame or home-frame); see :func:`fixed_structures_for_gantry`.
    """

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


def _translate(box: FixedStructureBox, offset: tuple[float, float, float]) -> FixedStructureBox:
    """Translate a home-frame box into deck-frame by the machine's travel span."""
    dx, dy, dz = offset
    return FixedStructureBox(
        name=box.name,
        x_min=box.x_min + dx,
        x_max=box.x_max + dx,
        y_min=box.y_min + dy,
        y_max=box.y_max + dy,
        z_min=box.z_min + dz,
        z_max=box.z_max + dz,
    )


# Cub XL total reachable travel span (x, y, z), used only to translate the
# canonical home-frame geometry below into deck-frame absolute coordinates.
_CUB_XL_REFERENCE_TRAVEL_MM = (540.0, 300.0, 100.0)

# Canonical home-frame geometry: offsets from the homed back-right-top
# corner (WPos zero under home_origin), which never change with policy.
_CUB_XL_RIGHT_RAIL_HOME_FRAME = FixedStructureBox(
    name="Cub XL right X-max rail",
    x_min=-60.0,
    x_max=0.0,
    y_min=-300.0,
    y_max=0.0,
    z_min=-100.0,
    z_max=0.0,
)

# Deck-frame absolute coordinates, derived from the canonical home-frame
# geometry. Values are unchanged from before origin_policy existed:
# x[480, 540], y[0, 300], z[0, 100].
CUB_XL_RIGHT_X_MAX_RAIL = _translate(
    _CUB_XL_RIGHT_RAIL_HOME_FRAME, _CUB_XL_REFERENCE_TRAVEL_MM,
)

_FIXED_STRUCTURES_BY_GANTRY_TYPE: dict[GantryType, tuple[FixedStructureBox, ...]] = {
    GantryType.CUB_XL: (CUB_XL_RIGHT_X_MAX_RAIL,),
}

_FIXED_STRUCTURES_HOME_FRAME_BY_GANTRY_TYPE: dict[GantryType, tuple[FixedStructureBox, ...]] = {
    GantryType.CUB_XL: (_CUB_XL_RIGHT_RAIL_HOME_FRAME,),
}


def fixed_structures_for_gantry_type(
    gantry_type: GantryType | str,
) -> tuple[FixedStructureBox, ...]:
    """Return built-in fixed machine structures in deck-frame coordinates.

    Type-only lookup; always deck-frame regardless of any config's
    ``origin_policy``. Use :func:`fixed_structures_for_gantry` when a loaded
    gantry config is available so the result is expressed in that config's
    active frame.
    """
    return _FIXED_STRUCTURES_BY_GANTRY_TYPE.get(GantryType(gantry_type), ())


def fixed_structures_for_gantry(
    gantry: GantryConfig | None,
) -> tuple[FixedStructureBox, ...]:
    """Return built-in fixed machine structures for a loaded gantry config.

    Coordinates are expressed in the config's active frame: deck-frame for
    ``origin_policy: deck_origin`` (the default), home-frame for
    ``origin_policy: home_origin``.
    """
    if gantry is None:
        return ()
    if OriginPolicy(gantry.origin_policy) is OriginPolicy.HOME_ORIGIN:
        return _FIXED_STRUCTURES_HOME_FRAME_BY_GANTRY_TYPE.get(
            GantryType(gantry.gantry_type), (),
        )
    return fixed_structures_for_gantry_type(gantry.gantry_type)
