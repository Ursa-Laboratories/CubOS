"""Coordinate conversion from PANDA-BEAR tool-point DB coordinates to the
CubOS home-origin gantry frame, plus rounding/envelope helpers.

PANDA-BEAR stores DB coordinates as *tool-point* targets: where the operator
wanted the mounted tool's tip to be. PANDA-BEAR's own driver converts that to
a gantry command with ``gantry = tool_target + tool_offset`` (per axis). The
generated CubOS deck stores that same gantry-frame value directly (see
``protocol/panda/position_tour.yaml``, which hovers a zero-offset ``camera``
instrument over each stored point) -- so importing one DB coordinate is
exactly this addition.
"""

from __future__ import annotations

from dataclasses import dataclass

from .constants import ROUND_NDIGITS
from .constants import ToolOffset


def round_mm(value: float) -> float:
    """Round a millimeter value to CubOS's 0.001mm determinism grain."""
    return round(float(value), ROUND_NDIGITS)


@dataclass(frozen=True)
class Point:
    """A plain XYZ point (no coordinate-space info attached)."""

    x: float
    y: float
    z: float


def to_gantry(point: Point, offset: ToolOffset) -> Point:
    """Convert a PANDA-BEAR tool-point DB coordinate to CubOS gantry frame.

    ``gantry = tool_target + tool_offset`` per axis, rounded to CubOS's
    0.001mm determinism grain.
    """
    return Point(
        x=round_mm(point.x + offset.x),
        y=round_mm(point.y + offset.y),
        z=round_mm(point.z + offset.z),
    )


@dataclass(frozen=True)
class WorkingVolume:
    """Absolute gantry-frame working volume bounds (mm)."""

    x_min: float
    x_max: float
    y_min: float
    y_max: float
    z_min: float
    z_max: float


def envelope_violation(
    point: Point, volume: WorkingVolume, tolerance_mm: float,
) -> str | None:
    """Return a human-readable violation message, or ``None`` if in bounds.

    A point is in bounds when every axis is within ``[min - tolerance,
    max + tolerance]``.
    """
    axes = (
        ("x", point.x, volume.x_min, volume.x_max),
        ("y", point.y, volume.y_min, volume.y_max),
        ("z", point.z, volume.z_min, volume.z_max),
    )
    messages: list[str] = []
    for axis, value, lo, hi in axes:
        if value < lo - tolerance_mm:
            messages.append(f"{axis}={value:.3f} < {axis}_min={lo:.3f} (by {lo - value:.3f}mm)")
        elif value > hi + tolerance_mm:
            messages.append(f"{axis}={value:.3f} > {axis}_max={hi:.3f} (by {value - hi:.3f}mm)")
    return "; ".join(messages) if messages else None


def pitch_offsets(a1: Point, a2: Point, b1: Point) -> tuple[float, float]:
    """Return ``(x_offset, y_offset)`` for the CubOS two-point calibration
    convention, given measured ``A1`` (origin), ``A2`` (next column, axis-
    aligned with A1), and ``B1`` (next row).

    Mirrors ``cubos.deck.loader._resolve_plate_orientation``: when A1/A2
    share the same Y, the column pitch is the X delta and the row pitch
    comes from ``B1``'s Y delta (and vice versa when they share the same X).
    Uses already-rounded points on both sides of every subtraction so the
    result satisfies the loader's strict 1e-9 axis-alignment tolerance.
    """
    same_y = abs(a1.y - a2.y) < 1e-9
    same_x = abs(a1.x - a2.x) < 1e-9
    if same_y and not same_x:
        x_offset = round_mm(abs(a2.x - a1.x))
        y_offset = round_mm(abs(b1.y - a1.y))
    elif same_x and not same_y:
        y_offset = round_mm(abs(a2.y - a1.y))
        x_offset = round_mm(abs(b1.x - a1.x))
    else:
        raise ValueError(
            "Calibration points A1/A2 must be axis-aligned in exactly one "
            f"of X or Y (got A1={a1}, A2={a2})."
        )
    return x_offset, y_offset
