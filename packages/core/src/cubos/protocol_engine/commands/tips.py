"""Protocol command: camera scan of a tip rack reconciling tip presence.

``scan_tip_rack`` packages the sensing loop the tip-state journal cannot do
on its own: move the camera over the rack, light it, capture one top-down
frame, classify per-slot tip presence (``cubos.vision.tip_detection``), and
reconcile the result into durable tip state (or the in-memory rack when
untracked) so ``pick_up_tip``'s next-available selection reflects physical
reality. Unlike ``image_well``, a failed capture raises — the scan exists to
produce state, not a souvenir image.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Optional

from cubos.deck.labware.labware import Coordinate3D
from cubos.deck.labware.tip_rack import TipRack
from cubos.instruments.camera.exceptions import CameraError
from cubos.vision.tip_detection import (
    DEFAULT_ABSENT_THRESHOLD,
    DEFAULT_PRESENT_THRESHOLD,
    classify_tip_rack,
    project_tips_to_pixels,
    read_png_grayscale,
)

from ..errors import ProtocolExecutionError
from ..registry import protocol_command
from . import _summaries
from ._movement import _assert_finite_number
from .camera import (
    _SETTLE_S,
    _get_camera,
    _persist_image,
    _resolve_lighting,
    build_image_path,
)

if TYPE_CHECKING:
    from ..runtime import ProtocolContext


def _tracked_tip_state(context: "ProtocolContext") -> bool:
    """Mirror ``commands.pipette._tracked_fluid_state``'s completeness check."""
    if context.fluid_state_id is None:
        return False
    missing = []
    if context.data_store is None:
        missing.append("data_store")
    if context.campaign_id is None:
        missing.append("campaign_id")
    if missing:
        raise ProtocolExecutionError(
            "Durable fluid tracking context is incomplete: fluid_state_id is "
            f"set but {', '.join(missing)} is missing. No motion was attempted."
        )
    return True


@protocol_command("scan_tip_rack", summary=_summaries.scan_tip_rack)
def scan_tip_rack(
    context: "ProtocolContext",
    camera: str,
    rack: str,
    image_height: float,
    mm_per_px: float,
    lights: Optional[str] = None,
    brightness: int = 5,
    label: Optional[str] = None,
    patch_radius_mm: float = 1.0,
    present_threshold: float = DEFAULT_PRESENT_THRESHOLD,
    absent_threshold: float = DEFAULT_ABSENT_THRESHOLD,
    flip_x: bool = False,
    flip_y: bool = True,
) -> dict:
    """Image *rack* from above, classify per-slot tip presence, reconcile.

    The camera centers over the rack's tip grid at ``rack.location.z +
    image_height`` (``image_height`` is labware-relative, like
    ``image_well``'s), lights it (white at ``brightness``, resolved like
    ``image_well``'s ``lights``), captures one frame, and classifies each
    slot by mean patch intensity: at or above ``present_threshold`` (0-1) is
    present, at or below ``absent_threshold`` is absent, anything else — or
    a slot outside the frame — is uncertain and treated as not pickable.
    ``mm_per_px`` is the per-rig pixel scale at the scan height and
    ``flip_x``/``flip_y`` the camera-to-deck axis orientation (calibrate
    once with ``python -m cubos.tools.tip_scan_check``).

    With durable tracking active, the result reconciles ``available``/
    ``consumed`` slot state through ``DataStore.reconcile_tip_presence``
    (slots mid-operation are skipped and reported); untracked runs update
    the in-memory ``tip_present`` map instead. Returns the saved image path
    and per-slot ``present``/``absent``/``uncertain`` statuses.
    """
    camera_instr = _get_camera(context, camera)
    lighting = _resolve_lighting(context, lights)
    try:
        _assert_finite_number(
            image_height, field_name="image_height", source="scan_tip_rack",
        )
    except ValueError as exc:
        raise ProtocolExecutionError(str(exc)) from exc
    if not isinstance(mm_per_px, (int, float)) or not mm_per_px > 0:
        raise ProtocolExecutionError(
            f"scan_tip_rack: mm_per_px must be a positive number, "
            f"got {mm_per_px!r}."
        )
    if not isinstance(patch_radius_mm, (int, float)) or not patch_radius_mm > 0:
        raise ProtocolExecutionError(
            f"scan_tip_rack: patch_radius_mm must be a positive number, "
            f"got {patch_radius_mm!r}."
        )
    if not (0.0 <= absent_threshold <= present_threshold <= 1.0):
        raise ProtocolExecutionError(
            "scan_tip_rack: thresholds must satisfy 0 <= absent_threshold "
            f"<= present_threshold <= 1, got absent={absent_threshold!r} "
            f"present={present_threshold!r}."
        )

    try:
        rack_labware = context.deck.resolve_labware(rack)
    except KeyError as exc:
        raise ProtocolExecutionError(
            f"scan_tip_rack: rack {rack!r} is not on the deck."
        ) from exc
    if not isinstance(rack_labware, TipRack):
        raise ProtocolExecutionError(
            f"scan_tip_rack: {rack!r} resolves to "
            f"{type(rack_labware).__name__}, not a TipRack."
        )
    tracked = _tracked_tip_state(context)

    center_x = sum(tip.x for tip in rack_labware.tips.values()) / len(rack_labware.tips)
    center_y = sum(tip.y for tip in rack_labware.tips.values()) / len(rack_labware.tips)
    scan_z = rack_labware.location.z + image_height

    def _lights_call(action: str, *args) -> bool:
        if lighting is None:
            return True
        try:
            getattr(lighting, action)(*args)
            return True
        except Exception as exc:
            context.logger.warning(
                "scan_tip_rack: lighting %s failed (continuing): %s",
                action, exc,
            )
            return False

    saved: Optional[str] = None
    try:
        context.gantry.move_to_labware(
            camera,
            Coordinate3D(x=center_x, y=center_y, z=rack_labware.location.z),
        )
        context.gantry.move(camera, (center_x, center_y, scan_z))
        time.sleep(_SETTLE_S)
        _lights_call("set_channel", "white", brightness)
        path = build_image_path(context, label or f"scan_{rack}", camera)
        try:
            saved = camera_instr.capture(save_path=str(path))
        except CameraError as exc:
            raise ProtocolExecutionError(
                f"scan_tip_rack: capture failed: {exc}"
            ) from exc
    finally:
        _lights_call("all_off")
        safe_z = context.gantry.safe_z
        if safe_z is not None:
            try:
                context.gantry.move(
                    camera, (center_x, center_y, safe_z), travel_z=safe_z,
                )
            except Exception as exc:
                context.logger.error(
                    "scan_tip_rack: retract to safe_z failed; manual "
                    "hardware check required: %s", exc, exc_info=True,
                )

    _persist_image(context, rack, saved)
    try:
        image = read_png_grayscale(saved)
    except ValueError as exc:
        raise ProtocolExecutionError(f"scan_tip_rack: {exc}") from exc
    centers = project_tips_to_pixels(
        {tip_id: (tip.x, tip.y) for tip_id, tip in rack_labware.tips.items()},
        (center_x, center_y),
        len(image[0]) if image else 0,
        len(image),
        mm_per_px,
        flip_x=flip_x,
        flip_y=flip_y,
    )
    presence = classify_tip_rack(
        image,
        centers,
        patch_radius_px=max(1, round(patch_radius_mm / mm_per_px)),
        present_threshold=present_threshold,
        absent_threshold=absent_threshold,
    )

    if tracked:
        try:
            summary = context.data_store.reconcile_tip_presence(
                context.fluid_state_id, rack, presence,
            )
        except Exception as exc:
            raise ProtocolExecutionError(
                f"scan_tip_rack: tip-state reconcile failed for {rack!r}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        if summary["skipped"]:
            context.logger.warning(
                "scan_tip_rack: %s slots mid-operation were not reconciled: %s",
                rack, summary["skipped"],
            )
    else:
        for slot_id, value in presence.items():
            rack_labware.tip_present[slot_id] = value is True

    statuses = {
        slot_id: (
            "present" if value is True
            else "absent" if value is False
            else "uncertain"
        )
        for slot_id, value in presence.items()
    }
    context.logger.info(
        "scan_tip_rack: %s -> %d present, %d absent, %d uncertain (%s)",
        rack,
        sum(1 for status in statuses.values() if status == "present"),
        sum(1 for status in statuses.values() if status == "absent"),
        sum(1 for status in statuses.values() if status == "uncertain"),
        saved,
    )
    return {"image_path": saved, "slots": statuses}
