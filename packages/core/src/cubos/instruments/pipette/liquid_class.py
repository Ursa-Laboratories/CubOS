"""Generic per-liquid-class volume correction for pipette strokes.

Real pipetting deviates from the commanded volume in a way that depends on
the liquid being handled (viscosity, surface tension, vapor pressure).
PANDA-BEAR's ``panda_lib.actions.pipetting.correction_factor`` (see
``panda_lib/utilities.py``) captures this with a linear model per viscosity
bucket::

    corrected_volume = multiplier * commanded_volume + offset

e.g. ``0.91 cP // y = 1.01x + 6.23``, ``3.06 cP // y = 1.03x + 4.91``, one
``(multiplier, offset)`` pair selected by a hard-coded viscosity match.

CubOS keeps the mathematical form (linear multiplier + offset) but drops the
machine-specific viscosity branching: a :class:`LiquidClassCorrection` is a
named, explicitly configured parameter set (per pipette instrument, keyed by
an operator-chosen liquid-class name) rather than an implicit lookup keyed by
a physical constant. Disabled by default (``IDENTITY_CORRECTION``, i.e.
``multiplier=1.0, offset_ul=0.0``) so behavior is unchanged unless a protocol
explicitly opts in.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


class LiquidClassConfigError(ValueError):
    """Raised when a liquid-class correction is misconfigured."""


@dataclass(frozen=True)
class LiquidClassCorrection:
    """Linear stroke-volume correction: ``corrected = multiplier * v + offset_ul``."""

    multiplier: float = 1.0
    offset_ul: float = 0.0

    def __post_init__(self) -> None:
        if (
            isinstance(self.multiplier, bool)
            or not isinstance(self.multiplier, (int, float))
            or not math.isfinite(float(self.multiplier))
            or float(self.multiplier) <= 0
        ):
            raise LiquidClassConfigError(
                f"multiplier must be a finite positive number, got {self.multiplier!r}."
            )
        if (
            isinstance(self.offset_ul, bool)
            or not isinstance(self.offset_ul, (int, float))
            or not math.isfinite(float(self.offset_ul))
        ):
            raise LiquidClassConfigError(
                f"offset_ul must be a finite number, got {self.offset_ul!r}."
            )

    def apply(self, volume_ul: float) -> float:
        """Return the driver-commanded volume for a *requested* stroke volume."""
        return float(self.multiplier) * float(volume_ul) + float(self.offset_ul)


IDENTITY_CORRECTION = LiquidClassCorrection()


def build_liquid_classes(
    raw: dict[str, dict[str, float]] | None,
) -> dict[str, LiquidClassCorrection]:
    """Parse a ``{name: {multiplier, offset_ul}}`` config mapping.

    Accepts the minimal parametric form documented on
    :class:`LiquidClassCorrection`. Returns ``{}`` for ``None``/empty input
    (i.e. correction disabled by default).
    """
    if not raw:
        return {}
    if not isinstance(raw, dict):
        raise LiquidClassConfigError("liquid_classes must be a mapping of name to config.")
    corrections: dict[str, LiquidClassCorrection] = {}
    for name, config in raw.items():
        if not isinstance(name, str) or not name.strip():
            raise LiquidClassConfigError("liquid_classes keys must be non-empty strings.")
        if not isinstance(config, dict):
            raise LiquidClassConfigError(
                f"liquid_classes[{name!r}] must be a mapping of multiplier/offset_ul."
            )
        unknown = set(config) - {"multiplier", "offset_ul"}
        if unknown:
            raise LiquidClassConfigError(
                f"liquid_classes[{name!r}] has unknown fields: {sorted(unknown)}."
            )
        corrections[name] = LiquidClassCorrection(
            multiplier=config.get("multiplier", 1.0),
            offset_ul=config.get("offset_ul", 0.0),
        )
    return corrections


__all__ = [
    "IDENTITY_CORRECTION",
    "LiquidClassConfigError",
    "LiquidClassCorrection",
    "build_liquid_classes",
]
