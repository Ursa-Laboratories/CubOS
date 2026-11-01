"""Camera positions shared by command execution and setup validation."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class ImageWellMotion:
    positions: list[tuple[float, float, float]]
    sweep_offsets: list[float] | None


def _finite(value: Any, field: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise ValueError(f"image_well: {field} must be a finite number.")
    return float(value)


def _sweep_offsets(args: Mapping[str, Any]) -> list[float] | None:
    start = args.get("x_sweep_start_mm")
    stop = args.get("x_sweep_stop_mm")
    if start is None and stop is None:
        return None
    if start is None or stop is None:
        raise ValueError(
            "image_well: x_sweep_start_mm and x_sweep_stop_mm must be provided together."
        )
    start = _finite(start, "x_sweep_start_mm")
    stop = _finite(stop, "x_sweep_stop_mm")
    step = _finite(args.get("x_sweep_step_mm", 1.0), "x_sweep_step_mm")
    if step == 0:
        raise ValueError("image_well: x_sweep_step_mm must be non-zero.")
    if (stop - start) * step < 0:
        raise ValueError("image_well: x_sweep_step_mm points away from x_sweep_stop_mm.")
    offsets = []
    tolerance = abs(step) * 1e-9 + 1e-9
    while True:
        value = start + len(offsets) * step
        if (
            (step > 0 and value > stop + tolerance)
            or (step < 0 and value < stop - tolerance)
        ):
            return offsets
        if len(offsets) >= 1000:
            raise ValueError("image_well: X sweep exceeds 1000 positions.")
        offsets.append(value)


def plan_image_well(coord: Any, args: Mapping[str, Any]) -> ImageWellMotion:
    """Resolve the exact capture positions, including partial final sweeps."""
    mode = args.get("mode", "standard")
    if mode not in ("standard", "curvature"):
        raise ValueError(
            f"image_well: unknown mode {mode!r}; expected 'standard' or 'curvature'."
        )
    height = _finite(args.get("image_height"), "image_height")
    x_offset = _finite(args.get("x_offset_mm", 0.0), "x_offset_mm")
    y_offset = _finite(args.get("y_offset_mm", 0.0), "y_offset_mm")
    offsets = _sweep_offsets(args)
    if offsets is not None:
        if mode != "standard":
            raise ValueError("image_well: X sweeps require mode 'standard'.")
        if x_offset != 0:
            raise ValueError(
                "image_well: use either x_offset_mm or x_sweep_* fields, not both."
            )
        positions = [
            (coord.x + offset, coord.y + y_offset, coord.z + height)
            for offset in offsets
        ]
    else:
        steps, step_mm = 1, 0.0
        if mode == "curvature":
            steps = args.get("z_steps", 11)
            if isinstance(steps, bool) or not isinstance(steps, int) or steps < 1:
                raise ValueError("image_well: z_steps must be >= 1 and an integer.")
            step_mm = _finite(args.get("z_step_mm", 0.2), "z_step_mm")
            if step_mm < 0:
                raise ValueError("image_well: z_step_mm must be >= 0.")
        positions = [
            (
                coord.x + x_offset, coord.y + y_offset,
                coord.z + height - index * step_mm,
            )
            for index in range(steps)
        ]
    for position in positions:
        for axis, value in zip("xyz", position):
            _finite(value, f"resolved {axis}")
    return ImageWellMotion(positions=positions, sweep_offsets=offsets)
