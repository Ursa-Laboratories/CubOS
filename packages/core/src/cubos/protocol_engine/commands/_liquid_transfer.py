"""Stroke planning, preflight bounds, and state-derived height for `transfer`.

Pure, hardware-agnostic helpers used by the ``transfer`` protocol command
(``cubos.protocol_engine.commands.pipette``). Nothing here is specific to a
machine name: every bound comes from the pipette's configured
``PipetteConfig`` (model min/max volume), the source labware's geometry
(``Vial.height``/``diameter``/``dead_volume_ul``), and the durably tracked
current volume.

Model-based safety (splitting, min/max preflight) only engages when the
pipette instrument exposes a real :class:`~cubos.instruments.pipette.models.
PipetteConfig` via a ``.config`` attribute (true for every vendor driver,
including offline-mode ones). Test doubles that don't expose one (bare
``MagicMock``s in unit tests) fall back to the pre-Feature-04 single-stroke,
uncorrected behavior — see :func:`pipette_capacity`.
"""

from __future__ import annotations

import math
from typing import Any

from cubos.deck.labware.vial import Vial
from cubos.deck.labware.vial_grid import VialGrid
from cubos.instruments.pipette.models import PipetteConfig

_VOLUME_TOLERANCE_UL = 1e-6


class LiquidTransferPreflightError(ValueError):
    """Raised when a transfer request fails a before-motion safety check."""


def pipette_capacity(pipette: Any) -> PipetteConfig | None:
    """Return the pipette's model capacity, or ``None`` if not discoverable.

    Returning ``None`` disables model-based splitting/preflight entirely
    (single, uncorrected stroke) -- the pre-Feature-04 behavior test doubles
    without a real ``PipetteConfig`` already rely on.
    """
    config = getattr(pipette, "config", None)
    return config if isinstance(config, PipetteConfig) else None


def plan_strokes(
    volume_ul: float,
    capacity: PipetteConfig | None,
    correction: Any | None = None,
) -> list[float]:
    """Split *volume_ul* into deterministic, capacity-bounded strokes.

    Rejects (``LiquidTransferPreflightError``) before returning anything if
    the volume is non-positive, below the model minimum, or -- in a
    pathological config -- cannot be split into strokes that all honor the
    model's ``[min_volume, max_volume]`` bounds.

    When *capacity* is ``None`` (no model metadata available), returns a
    single unsplit stroke -- callers already reject <= 0 volumes
    independent of capacity.

    *correction* (a ``LiquidClassCorrection``-like object with ``multiplier``
    / ``offset_ul`` / ``apply``) participates in planning: the driver is
    commanded the *corrected* stroke volume, so the effective per-stroke
    ceiling for the *requested* volume is
    ``(max_volume - offset_ul) / multiplier`` -- otherwise a full-capacity
    stroke plus a positive correction would exceed the model max at the
    driver boundary. Every planned stroke's corrected volume is verified to
    stay inside ``[min_volume, max_volume]``.

    Splitting: ``n = ceil(volume_ul / effective_max)`` equal strokes, with
    the last stroke absorbing the float remainder so the strokes sum exactly
    to *volume_ul* (same remainder-on-the-last-item convention as
    ``fluid_state._proportional_composition``). Mirrors the ``repetitions =
    ceil(volume / capacity)`` split in PANDA-BEAR's
    ``panda_lib.actions.pipetting._pipette_action``.
    """
    if (
        isinstance(volume_ul, bool)
        or not isinstance(volume_ul, (int, float))
        or not math.isfinite(float(volume_ul))
    ):
        raise LiquidTransferPreflightError(
            f"volume_ul must be a finite number, got {volume_ul!r}."
        )
    volume = float(volume_ul)
    if volume <= 0:
        raise LiquidTransferPreflightError(
            f"volume_ul must be > 0, got {volume:g}."
        )

    if capacity is None:
        return [volume]

    if volume < capacity.min_volume - _VOLUME_TOLERANCE_UL:
        raise LiquidTransferPreflightError(
            f"Requested volume {volume:g} uL is below {capacity.name}'s "
            f"minimum of {capacity.min_volume:g} uL; splitting cannot help "
            "since every stroke must independently clear the model minimum."
        )

    effective_max = capacity.max_volume
    if correction is not None:
        multiplier = float(getattr(correction, "multiplier", 1.0))
        offset_ul = float(getattr(correction, "offset_ul", 0.0))
        corrected_ceiling = (capacity.max_volume - offset_ul) / multiplier
        effective_max = min(effective_max, corrected_ceiling)
        if effective_max <= 0:
            raise LiquidTransferPreflightError(
                f"Liquid-class correction (x{multiplier:g} + {offset_ul:g} uL) "
                f"leaves no usable stroke capacity on {capacity.name} "
                f"(max {capacity.max_volume:g} uL)."
            )

    if volume <= effective_max + _VOLUME_TOLERANCE_UL:
        strokes = [volume]
    else:
        stroke_count = math.ceil(volume / effective_max)
        base_stroke = volume / stroke_count
        strokes = [base_stroke] * (stroke_count - 1)
        strokes.append(volume - sum(strokes))

    for stroke in strokes:
        commanded = correction.apply(stroke) if correction is not None else stroke
        if (
            stroke < capacity.min_volume - _VOLUME_TOLERANCE_UL
            or stroke > effective_max + _VOLUME_TOLERANCE_UL
            or commanded < capacity.min_volume - _VOLUME_TOLERANCE_UL
            or commanded > capacity.max_volume + _VOLUME_TOLERANCE_UL
        ):
            raise LiquidTransferPreflightError(
                f"Cannot split {volume:g} uL into strokes that all honor "
                f"{capacity.name}'s bounds [{capacity.min_volume:g}, "
                f"{capacity.max_volume:g}] uL; got a {stroke:g} uL stroke "
                f"({commanded:g} uL driver-commanded)."
            )
    return strokes


def vial_for_target(target: Any) -> Vial | None:
    """Return the concrete ``Vial`` behind a resolved deck target, if any.

    ``target.labware`` is either a bare ``Vial`` (``location_id`` unused) or
    a ``VialGrid`` (``location_id`` names one of its canonical vials).
    Non-vial labware (well plates) has no single liquid-column geometry to
    derive a height from, so this returns ``None``.
    """
    labware = getattr(target, "labware", None)
    if isinstance(labware, Vial):
        return labware
    if isinstance(labware, VialGrid) and target.location_id:
        return labware.vials.get(target.location_id)
    return None


def working_volume_for_target(target: Any) -> float | None:
    """Return the working volume of the container behind a resolved target."""
    vial = vial_for_target(target)
    if vial is not None:
        return float(vial.working_volume_ul)
    labware = getattr(target, "labware", None)
    working = getattr(labware, "working_volume_ul", None)
    return None if working is None else float(working)


def validate_dead_volume(
    *,
    source_current_volume_ul: float,
    dead_volume_ul: float,
    requested_volume_ul: float,
    source_label: str,
) -> None:
    """Reject a transfer that would draw *source* below its dead-volume floor."""
    available = source_current_volume_ul - dead_volume_ul
    if requested_volume_ul > available + _VOLUME_TOLERANCE_UL:
        raise LiquidTransferPreflightError(
            f"Cannot transfer {requested_volume_ul:g} uL from {source_label}: "
            f"only {available:g} uL is available above its "
            f"{dead_volume_ul:g} uL dead-volume floor "
            f"(current volume {source_current_volume_ul:g} uL)."
        )


def validate_destination_overflow(
    *,
    destination_current_volume_ul: float,
    working_volume_ul: float,
    requested_volume_ul: float,
    destination_label: str,
) -> None:
    """Reject a transfer that would push *destination* above its working volume.

    Stricter than ``fluid_state._validate_replacement_volume``, which only
    hard-rejects capacity overflow and merely warns above working volume;
    Feature-04 preflight hard-rejects working-volume overflow too.
    """
    projected = destination_current_volume_ul + requested_volume_ul
    if projected > working_volume_ul + _VOLUME_TOLERANCE_UL:
        raise LiquidTransferPreflightError(
            f"Cannot transfer {requested_volume_ul:g} uL into "
            f"{destination_label}: projected volume {projected:g} uL exceeds "
            f"its {working_volume_ul:g} uL working volume "
            f"(current volume {destination_current_volume_ul:g} uL)."
        )


def derive_liquid_relative_height(
    vial: Vial,
    current_volume_ul: float,
    *,
    bottom_clearance_mm: float = 2.0,
) -> float | None:
    """Return a labware-relative Z offset that tracks the liquid surface.

    Same sign convention as ``measurement_height``/explicit ``source_height``
    (``_movement.engage_at_labware``): 0 = labware reference Z (the vial
    rim, i.e. ``vial.location.z``); negative = below the rim.

    Geometry: treats the vial as a uniform cylinder of diameter
    ``vial.diameter`` and outer height ``vial.height``. The current liquid
    column height (mm) is ``current_volume_ul / cross_section_area_mm2``
    (1 uL == 1 mm^3), so the liquid surface sits
    ``-(vial.height - liquid_column_height_mm)`` relative to the rim.

    The tip follows that surface down as volume drops, but is clamped to
    never go below a floor: the higher (safer / less negative) of the
    dead-volume floor (the Z at which ``vial.dead_volume_ul`` remains) and a
    fixed ``bottom_clearance_mm`` above the physical bottom. Returns
    ``None`` (state derivation unavailable) when the vial doesn't carry
    enough geometry (``height``/``diameter``) to compute this -- callers
    fall back to the legacy explicit-height default.
    """
    if vial.height is None or vial.diameter is None:
        return None
    if vial.height <= 0 or vial.diameter <= 0:
        return None

    area_mm2 = math.pi * (vial.diameter / 2.0) ** 2
    dead_volume_ul = float(getattr(vial, "dead_volume_ul", 0.0) or 0.0)

    liquid_column_mm = max(0.0, float(current_volume_ul)) / area_mm2
    surface_offset = liquid_column_mm - vial.height

    dead_column_mm = dead_volume_ul / area_mm2
    dead_floor_offset = dead_column_mm - vial.height
    clearance_floor_offset = bottom_clearance_mm - vial.height
    floor_offset = max(dead_floor_offset, clearance_floor_offset)

    target_offset = max(surface_offset, floor_offset)
    # Never reach above the rim even if volume nominally exceeds capacity;
    # capacity/overflow preflight should already have rejected that case.
    return min(0.0, target_offset)


__all__ = [
    "LiquidTransferPreflightError",
    "derive_liquid_relative_height",
    "pipette_capacity",
    "plan_strokes",
    "validate_dead_volume",
    "validate_destination_overflow",
    "vial_for_target",
    "working_volume_for_target",
]
