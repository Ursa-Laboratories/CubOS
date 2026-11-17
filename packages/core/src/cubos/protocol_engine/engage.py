"""Opt-in bottom-/top-relative engage positions for pipette commands.

Existing ``height`` fields are offsets from the well reference Z (the rim) and
keep that meaning. ``from_bottom_mm`` measures up from the inside floor;
``from_top_mm`` measures from the rim and is the explicit spelling of
``height``. Both are resolved to an equivalent rim-relative ``height`` before
routing, bounds and semantic validation read the step, so those layers never
see the new fields.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from cubos.deck.labware.vial import Vial
from cubos.deck.labware.well_plate import WellPlate

# command -> ((target arg, height arg, from-bottom arg, from-top arg), ...)
_SINGLE = ("position", "height", "from_bottom_mm", "from_top_mm")
_SOURCE = ("source", "source_height", "source_from_bottom_mm", "source_from_top_mm")
_DESTINATION = (
    "destination", "destination_height",
    "destination_from_bottom_mm", "destination_from_top_mm",
)
_PLATE_DESTINATION = (
    "plate", "destination_height",
    "destination_from_bottom_mm", "destination_from_top_mm",
)
ENGAGE_SPECS: dict[str, tuple[tuple[str, str, str, str], ...]] = {
    "aspirate": (_SINGLE,),
    "dispense": (_SINGLE,),
    "blowout": (_SINGLE,),
    "mix": (_SINGLE,),
    "transfer": (_SOURCE, _DESTINATION),
    "serial_transfer": (_SOURCE, _PLATE_DESTINATION),
    "multi_dispense": (_SOURCE, ("destinations", *_DESTINATION[1:])),
}
ENGAGE_FIELDS = frozenset(
    name for specs in ENGAGE_SPECS.values() for spec in specs for name in spec[2:]
)


class EngagePositionError(ValueError):
    """An engage position cannot be resolved against the deck."""


def floor_depth_mm(deck: Any, target: str) -> float:
    """Rim-to-inside-floor depth of the container *target* names."""
    try:
        labware = deck.resolve_labware_target(target).labware
    except (KeyError, ValueError) as exc:
        raise EngagePositionError(f"cannot resolve {target!r} on the deck: {exc}") from exc
    if isinstance(labware, WellPlate):
        depth, field = labware.well_depth, "well_depth"
    elif isinstance(labware, Vial):
        depth, field = labware.inner_depth, "inner_depth"
    else:
        raise EngagePositionError(
            f"{target!r} is a {type(labware).__name__}; bottom-relative engage "
            "positions need a well plate or vial."
        )
    if depth is None:
        raise EngagePositionError(
            f"{target!r} has no {field}; set it in the deck YAML to use from_bottom_mm."
        )
    return float(depth)


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise EngagePositionError(f"{field} must be a finite number, got {value!r}.")
    return float(value)


def resolve_engage_height(
    deck: Any,
    target: str,
    *,
    height: float | None,
    from_bottom_mm: float | None,
    from_top_mm: float | None,
    height_field: str = "height",
    depth_mm: float | None = None,
) -> float | None:
    """Return the rim-relative height, or ``height`` when no opt-in is used."""
    if from_bottom_mm is None and from_top_mm is None:
        return height
    if from_bottom_mm is not None and from_top_mm is not None:
        raise EngagePositionError(
            f"{height_field}: give only one of from_bottom_mm and from_top_mm."
        )
    if height not in (None, 0, 0.0):
        raise EngagePositionError(
            f"{height_field} is set to {height!r}; do not combine it with "
            "from_bottom_mm/from_top_mm."
        )
    if from_top_mm is not None:
        return _number(from_top_mm, "from_top_mm")
    offset = _number(from_bottom_mm, "from_bottom_mm")
    if offset < 0:
        raise EngagePositionError(f"from_bottom_mm must be >= 0, got {offset:g}.")
    depth = floor_depth_mm(deck, target) if depth_mm is None else depth_mm
    return offset - depth


def _targets(value: Any) -> list[str]:
    return list(value) if isinstance(value, (list, tuple)) else [value]


def resolve_step_args(command: str, args: Mapping[str, Any], deck: Any) -> dict[str, Any]:
    """Return *args* with engage opt-ins replaced by rim-relative heights."""
    specs = ENGAGE_SPECS.get(command)
    if not specs or not any(name in args for spec in specs for name in spec[2:]):
        return dict(args)
    resolved = dict(args)
    for target_arg, height_arg, bottom_arg, top_arg in specs:
        bottom, top = resolved.pop(bottom_arg, None), resolved.pop(top_arg, None)
        if bottom is None and top is None:
            continue
        targets = _targets(resolved[target_arg])
        depths = {floor_depth_mm(deck, t) for t in targets} if bottom is not None else {None}
        if len(depths) > 1:
            raise EngagePositionError(
                f"{bottom_arg}: {target_arg} spans containers with different depths "
                f"({sorted(d for d in depths if d is not None)}); split the command."
            )
        resolved[height_arg] = resolve_engage_height(
            deck, targets[0],
            height=resolved.get(height_arg), from_bottom_mm=bottom, from_top_mm=top,
            height_field=height_arg, depth_mm=depths.pop(),
        )
    return resolved
