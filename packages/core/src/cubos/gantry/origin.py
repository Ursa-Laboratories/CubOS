"""Helpers for deck-origin work-coordinate calibration."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math

from .gantry_config import GantryConfig


_ZERO_TOLERANCE = 1e-9


def _round_mm(value: float) -> float:
    return round(float(value), 3)


@dataclass(frozen=True)
class DeckOriginZCalibration:
    """Z calibration derived from a block touch in the deck-origin frame."""

    block_height: float
    total_z_range: float
    home_z: float
    block_touch_z: float
    home_to_block_travel: float
    remaining_below_block: float
    can_reach_deck_bottom: bool
    z_min: float
    z_max: float
    max_travel_z: float

    def as_dict(self) -> dict[str, float | bool]:
        return asdict(self)


def calculate_deck_origin_z_calibration(
    *,
    home_z: float,
    block_touch_z: float,
    block_height: float,
    total_z_range: float,
    tolerance_mm: float = 0.001,
) -> DeckOriginZCalibration:
    """Calculate deck-origin Z bounds from a calibration block touch.

    ``home_z`` and ``block_touch_z`` must come from the same pre-finalization
    work-coordinate frame. ``total_z_range`` is the physical Z travel span that
    GRBL should enforce in the unreachable-bottom case.
    """
    values = {
        "home_z": home_z,
        "block_touch_z": block_touch_z,
        "block_height": block_height,
        "total_z_range": total_z_range,
        "tolerance_mm": tolerance_mm,
    }
    bad = [name for name, value in values.items() if not math.isfinite(float(value))]
    if bad:
        raise ValueError("Z calibration values must be finite: " + ", ".join(bad))
    if block_height <= 0:
        raise ValueError("block_height must be > 0.")
    if total_z_range <= 0:
        raise ValueError("total_z_range must be > 0.")
    if tolerance_mm < 0:
        raise ValueError("tolerance_mm must be >= 0.")

    home_to_block_travel = _round_mm(float(home_z) - float(block_touch_z))
    if home_to_block_travel <= tolerance_mm:
        raise ValueError("block_touch_z must be below home_z.")
    if home_to_block_travel > float(total_z_range) + tolerance_mm:
        raise ValueError(
            "home-to-block travel exceeds total_z_range: "
            f"travel={home_to_block_travel:g}, total_z_range={float(total_z_range):g}."
        )

    remaining_below_block = _round_mm(float(total_z_range) - home_to_block_travel)
    can_reach_deck_bottom = remaining_below_block + tolerance_mm >= float(block_height)
    if can_reach_deck_bottom:
        z_min = 0.0
        max_travel_z = _round_mm(home_to_block_travel + float(block_height))
    else:
        z_min = _round_mm(float(block_height) - remaining_below_block)
        max_travel_z = _round_mm(float(total_z_range))
    z_max = _round_mm(z_min + max_travel_z)

    return DeckOriginZCalibration(
        block_height=_round_mm(block_height),
        total_z_range=_round_mm(total_z_range),
        home_z=_round_mm(home_z),
        block_touch_z=_round_mm(block_touch_z),
        home_to_block_travel=home_to_block_travel,
        remaining_below_block=remaining_below_block,
        can_reach_deck_bottom=can_reach_deck_bottom,
        z_min=z_min,
        z_max=z_max,
        max_travel_z=max_travel_z,
    )


@dataclass(frozen=True)
class DeckOriginCalibrationPlan:
    """Concrete GRBL command skeleton for physical-origin calibration."""

    origin_wpos: tuple[float, float, float]
    commands: tuple[str, ...]


def format_gcode_number(value: float) -> str:
    """Format a float compactly for G-code command strings."""
    formatted = f"{float(value):.6f}".rstrip("0").rstrip(".")
    return formatted if formatted and formatted != "-0" else "0"


def format_set_work_position_command(
    x: float | None = None,
    y: float | None = None,
    z: float | None = None,
) -> str:
    """Return a G10 command that assigns WPos at the current machine pose."""
    parts = ["G10 L20 P1"]
    if x is not None:
        parts.append(f"X{format_gcode_number(x)}")
    if y is not None:
        parts.append(f"Y{format_gcode_number(y)}")
    if z is not None:
        parts.append(f"Z{format_gcode_number(z)}")
    if len(parts) == 1:
        raise ValueError("At least one axis must be supplied.")
    return " ".join(parts)


def validate_deck_origin_minima(config: GantryConfig) -> None:
    """Validate that a gantry config is in the deck-origin frame shape."""
    volume = config.working_volume
    non_zero_xy_mins = [
        (axis, value)
        for axis, value in (
            ("x_min", volume.x_min),
            ("y_min", volume.y_min),
        )
        if abs(value) > _ZERO_TOLERANCE
    ]
    if non_zero_xy_mins:
        formatted = ", ".join(f"{axis}={value}" for axis, value in non_zero_xy_mins)
        raise ValueError(
            "Deck-origin calibration requires working_volume X/Y minima at 0.0; "
            f"got {formatted}. Use a deck-origin gantry config before setting "
            "front-left-bottom origin."
        )
    if volume.z_min < -_ZERO_TOLERANCE:
        raise ValueError(
            "Deck-origin calibration requires working_volume.z_min >= 0.0; "
            f"got z_min={volume.z_min}. Use a deck-origin gantry config before "
            "setting front-left-bottom origin."
        )


def build_deck_origin_calibration_plan(
    config: GantryConfig,
) -> DeckOriginCalibrationPlan:
    """Build the GRBL command skeleton for deck-origin calibration.

    The physical travel values are intentionally not included here. They must
    be measured by jogging to a front-left XY reference at the lowest safe
    reachable Z, assigning only X/Y to zero, assigning Z either to true deck
    bottom or to the ruler-measured deck-to-TCP gap, then re-homing and reading
    WPos at the homed back-right-top corner.
    """
    validate_deck_origin_minima(config)
    return DeckOriginCalibrationPlan(
        origin_wpos=(0.0, 0.0, 0.0),
        commands=(
            "$H",
            "$10=0",
            "G90",
            "G54",
            "G92.1",
            "<interactive jog to front-left XY origin/lower reach point>",
            "G10 L20 P1 X0 Y0",
            "<confirm deck-bottom contact or enter ruler-measured TCP gap>",
            "G10 L20 P1 Z<z_min_mm>",
            "$H",
            "?",
            "<compute max travel spans from measured WPos>",
            "$20=0",
            "$130=<x_span_mm>",
            "$131=<y_span_mm>",
            "$132=<z_span_mm>",
            "$22=1",
            "$20=1",
            "$H",
            "G54",
            "G10 L20 P1 X<x_max_mm> Y<y_max_mm> Z<z_max_mm>",
            "?",
        ),
    )
