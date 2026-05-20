"""Load deck YAML into a Deck containing configured labware fixtures."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Type

import yaml
from pydantic import BaseModel, ValidationError

from .deck import Deck
from .labware import Coordinate3D, Labware
from .labware.definitions.registry import (
    get_supported_definitions,
    load_definition_config,
)
from .labware.holder import LabwareSlot
from .labware.tip_disposal import TipDisposal
from .labware.tip_rack import TipRack
from .labware.wall import Wall
from .labware.vial import Vial
from .labware.vial_holder import VialHolder
from .labware.well_plate import WellPlate
from .labware.well_plate_holder import WellPlateHolder
from .errors import DeckLoaderError
from .yaml_schema import (
    DeckYamlSchema,
    NestedVialYamlEntry,
    NestedWellPlateYamlEntry,
    TipDisposalYamlEntry,
    TipRackYamlEntry,
    VialHolderYamlEntry,
    WallYamlEntry,
    VialYamlEntry,
    WellPlateHolderYamlEntry,
    WellPlateYamlEntry,
    _BaseHolderYamlEntry,
    _YamlHolderSlot,
    _YamlPoint3D,
)


def _format_loader_exception(path: Path, error: Exception) -> str:
    """Return a concise, actionable error message with fix guidance."""
    detail = str(error)

    if isinstance(error, ValidationError):
        first_error = error.errors()[0] if error.errors() else {}
        detail = first_error.get("msg", detail)
        error_type = first_error.get("type", "")
        location = ".".join(str(part) for part in first_error.get("loc", []))

        if "axis-aligned" in detail or "diagonal orientation is invalid" in detail:
            guidance = (
                "Set `calibration.a1` and `calibration.a2` so A2 shares either "
                "the same x or the same y as A1 (not both different)."
            )
        elif error_type == "missing" or "Field required" in detail:
            guidance = "Add the missing required YAML field shown in the error location."
        elif "extra_forbidden" in error_type or "Extra inputs are not permitted" in detail:
            guidance = "Remove unknown YAML fields; only schema-defined fields are allowed."
        elif "model_type" in error_type:
            guidance = "Check YAML nesting/indentation and field types."
        else:
            guidance = "Review the YAML values against the deck schema and correct invalid entries."

        prefix = f" at `{location}`" if location else ""
        return f"❌ Deck YAML error{prefix}: {detail}\nHow to fix: {guidance}"

    if isinstance(error, yaml.YAMLError):
        return (
            f"❌ Deck YAML parse error in `{path}`.\n"
            "How to fix: Check YAML indentation, colons, and list/dict structure."
        )

    return (
        f"❌ Deck loader error in `{path}`: {detail}\n"
        "How to fix: Verify the file path and deck YAML contents."
    )


def _point_to_coord(p: _YamlPoint3D, z_value: float | None = None) -> Coordinate3D:
    """Convert schema point (x, y, z) to Coordinate3D."""
    z = p.z if z_value is None else z_value
    if z is None:
        raise ValueError("Missing z value for coordinate conversion.")
    return Coordinate3D(x=p.x, y=p.y, z=z)


def _resolve_user_z(
    explicit_z: float | None,
    *,
    context: str,
    default_z: float | None = None,
) -> float:
    """Resolve a deck-frame Z from the calibration/location anchor.

    The deck YAML's calibration anchor (``calibration.a1.z`` or
    ``location.z``) is the single source of truth for the
    labware-surface deck-frame Z. The legacy ``height`` z-hint shorthand
    was removed when the dimensional field was renamed from
    ``height_mm`` to ``height`` — the z-hint and the dimension can no
    longer share the same field name.
    """
    if explicit_z is None:
        if default_z is not None:
            return default_z
        raise ValueError(
            f"{context}: calibration anchor must include a `z` value."
        )
    return explicit_z


def _entry_kwargs_for_model(entry: BaseModel, model_class: Type[BaseModel]) -> Dict[str, Any]:
    """
    Build constructor kwargs from entry by keeping only keys that exist on the target model.

    ``exclude_none=True`` drops optional YAML fields that weren't set, so the
    target class's defaults take effect instead of being overridden with
    ``None`` (which would fail pydantic validation for required dimensions).
    """
    allowed = set(model_class.model_fields.keys())
    raw = entry.model_dump(exclude_none=True)
    return {k: v for k, v in raw.items() if k in allowed}


def _resolve_load_names(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Expand ``load_name:`` references against the labware definitions registry.

    For each entry in ``raw["labware"]`` that has a ``load_name`` field, load
    the corresponding definition config from ``labware/definitions/``, merge
    the user's fields on top (user wins), drop the ``load_name`` key, and
    default the labware ``name`` to the deck key if the user didn't override it.

    Entries without ``load_name`` are passed through untouched, so existing
    deck YAMLs keep working unchanged.
    """
    labware = raw.get("labware")
    if not isinstance(labware, dict):
        return raw

    expanded: Dict[str, Dict[str, Any]] = {}
    for deck_key, entry in labware.items():
        if not isinstance(entry, dict) or "load_name" not in entry:
            expanded[deck_key] = entry
            continue

        load_name = entry["load_name"]
        try:
            base = load_definition_config(load_name)
        except (ValueError, FileNotFoundError) as exc:
            raise DeckLoaderError(
                f"❌ Unknown `load_name: '{load_name}'` in deck entry "
                f"'{deck_key}'.\n"
                f"How to fix: use one of {get_supported_definitions()}, or "
                f"add a new folder + registry entry under "
                f"`src/deck/labware/definitions/`."
            ) from exc

        # Shallow merge: user fields override config fields. Drop load_name.
        merged: Dict[str, Any] = dict(base)
        for key, value in entry.items():
            if key == "load_name":
                continue
            merged[key] = value

        # Default the labware `name` to the deck key unless the user set it.
        if "name" not in entry:
            merged["name"] = deck_key

        expanded[deck_key] = merged

    new_raw = dict(raw)
    new_raw["labware"] = expanded
    return new_raw


def _slot_to_model(slot_entry: _YamlHolderSlot, *, default_z: float) -> LabwareSlot:
    """Convert a YAML holder slot definition into a LabwareSlot."""
    resolved_z = slot_entry.location.z if slot_entry.location.z is not None else default_z
    return LabwareSlot(
        location=_point_to_coord(slot_entry.location, z_value=resolved_z),
        supported_labware_types=slot_entry.supported_labware_types,
        description=slot_entry.description,
    )


def _build_holder_slots(
    slots: Dict[str, _YamlHolderSlot],
    *,
    default_z: float,
) -> Dict[str, LabwareSlot]:
    return {
        slot_name: _slot_to_model(slot_entry, default_z=default_z)
        for slot_name, slot_entry in slots.items()
    }


def _build_tip_rack(
    entry: TipRackYamlEntry,
    total_z_range: float | None,
) -> TipRack:
    del total_z_range
    # Derive every tip pickup position from the two-point calibration and
    # pitch offsets, mirroring how well plates derive their wells.
    tips = _derive_wells_from_calibration(entry, resolved_z=entry.pickup_z)

    # Anchor location: use the explicit entry.location if given, otherwise
    # default to the A1 tip so the holder's bounding-box/geometry still works.
    if entry.location is not None:
        loc = _point_to_coord(
            entry.location,
            z_value=entry.location.z if entry.location.z is not None else entry.pickup_z,
        )
    else:
        loc = tips["A1"]

    kwargs = _entry_kwargs_for_model(entry, TipRack)
    kwargs.update(
        location=loc,
        tips=tips,
        tip_present=dict(entry.tip_present),
        slots=_build_holder_slots(entry.slots, default_z=loc.z),
    )
    return TipRack(**kwargs)


def _row_labels(rows: int) -> list[str]:
    if rows <= 0:
        raise ValueError("rows must be positive for row label generation.")
    labels: list[str] = []
    for index in range(rows):
        label = ""
        value = index + 1
        while value > 0:
            value, remainder = divmod(value - 1, 26)
            label = chr(65 + remainder) + label
        labels.append(label)
    return labels


@dataclass(frozen=True)
class _PlateOrientation:
    """Resolved per-step deltas for column and row traversal.

    Separating orientation resolution from well generation makes the
    coordinate math easier to follow and test independently.
    """
    col_delta_x: float
    col_delta_y: float
    row_delta_x: float
    row_delta_y: float


def _resolve_plate_orientation(entry: Any) -> _PlateOrientation:
    """Determine column/row axis mapping from the two-point calibration.

    Returns a ``_PlateOrientation`` whose deltas are used to compute each
    well position relative to A1 in ``_derive_wells_from_calibration``.

    Raises ``ValueError`` when the A2 calibration step magnitude does not
    match the declared offset magnitude or the points are not axis-aligned.
    """
    a1 = entry.a1_point
    a2 = entry.calibration.a2

    same_x = abs(a1.x - a2.x) < 1e-9
    same_y = abs(a1.y - a2.y) < 1e-9

    if same_y:
        col_step = a2.x - a1.x
        if abs(abs(col_step) - entry.x_offset) > 1e-9:
            raise ValueError(
                "Calibration A2 must match one adjacent column step from A1 "
                "(delta x magnitude must equal x_offset magnitude)."
            )
        row_step = -entry.y_offset if col_step > 0 else entry.y_offset
        return _PlateOrientation(
            col_delta_x=col_step, col_delta_y=0.0,
            row_delta_x=0.0, row_delta_y=row_step,
        )

    if same_x:
        col_step = a2.y - a1.y
        if abs(abs(col_step) - entry.y_offset) > 1e-9:
            raise ValueError(
                "Calibration A2 must match one adjacent column step from A1 "
                "(delta y magnitude must equal y_offset magnitude)."
            )
        row_step = entry.x_offset if col_step > 0 else -entry.x_offset
        return _PlateOrientation(
            col_delta_x=0.0, col_delta_y=col_step,
            row_delta_x=row_step, row_delta_y=0.0,
        )

    raise ValueError("Calibration must be axis-aligned (same x or same y).")


def _derive_wells_from_calibration(
    entry: Any,
    resolved_z: float,
) -> Dict[str, Coordinate3D]:
    """Build well ID -> Coordinate3D from calibration A1/A2 and offsets."""
    a1 = entry.a1_point
    orientation = _resolve_plate_orientation(entry)
    rounding = 3
    wells: Dict[str, Coordinate3D] = {}

    for row_idx, row_label in enumerate(_row_labels(entry.rows)):
        for col_idx, col_num in enumerate(range(1, entry.columns + 1)):
            x = a1.x + orientation.col_delta_x * col_idx + orientation.row_delta_x * row_idx
            y = a1.y + orientation.col_delta_y * col_idx + orientation.row_delta_y * row_idx
            wells[f"{row_label}{col_num}"] = Coordinate3D(
                x=round(x, rounding),
                y=round(y, rounding),
                z=round(resolved_z, rounding),
            )

    return wells


def _build_well_plate(
    entry: WellPlateYamlEntry,
    total_z_range: float | None,
) -> WellPlate:
    resolved_z = _resolve_user_z(
        entry.a1_point.z,
        context=f"well_plate '{entry.name}'",
    )
    kwargs = _entry_kwargs_for_model(entry, WellPlate)
    kwargs["wells"] = _derive_wells_from_calibration(entry, resolved_z=resolved_z)
    # ``height`` is the plate's physical outer dimension (rim →
    # underside), inherited from the labware definition. The deck-frame Z
    # of the plate surface lives on each well's ``Coordinate3D.z`` (set by
    # ``_derive_wells_from_calibration`` from the calibration anchor).
    return WellPlate(**kwargs)


def _build_vial(
    entry: VialYamlEntry,
    total_z_range: float | None,
) -> Vial:
    resolved_z = _resolve_user_z(
        entry.location.z,
        context=f"vial '{entry.name}'",
    )
    kwargs = _entry_kwargs_for_model(entry, Vial)
    kwargs["location"] = _point_to_coord(entry.location, z_value=resolved_z)
    return Vial(**kwargs)


def _build_holder(
    entry: _BaseHolderYamlEntry,
    total_z_range: float | None,
    *,
    model_class: Type[Labware],
) -> Labware:
    resolved_z = _resolve_user_z(
        entry.location.z,
        context=f"{entry.type} '{entry.name}'",
    )
    kwargs = _entry_kwargs_for_model(entry, model_class)
    kwargs["location"] = _point_to_coord(entry.location, z_value=resolved_z)
    kwargs["slots"] = _build_holder_slots(entry.slots, default_z=resolved_z)
    holder = model_class(**kwargs)

    seat_height = getattr(holder, "labware_seat_height_from_bottom", None)
    contained_labware: Dict[str, Labware] = {}
    if isinstance(entry, VialHolderYamlEntry):
        if seat_height is not None:
            contained_z = holder.location.z + seat_height
            contained_labware = {
                vial_key: _build_nested_vial(
                    vial_key,
                    vial_entry,
                    resolved_z=contained_z,
                )
                for vial_key, vial_entry in entry.vials.items()
            }
    elif (
        isinstance(entry, WellPlateHolderYamlEntry)
        and entry.well_plate is not None
    ):
        surface_height = getattr(
            holder, "well_plate_surface_height_from_bottom", None,
        )
        nested_height = (
            surface_height
            if surface_height is not None
            else seat_height
        )
        if nested_height is not None:
            contained_z = holder.location.z + nested_height
            contained_labware["plate"] = _build_nested_well_plate(
                "plate",
                entry.well_plate,
                resolved_z=contained_z,
            )

    holder.contained_labware = contained_labware
    return holder


def _build_nested_vial(
    vial_key: str,
    entry: NestedVialYamlEntry,
    *,
    resolved_z: float,
) -> Vial:
    return Vial(
        name=entry.name or vial_key,
        model_name=entry.model_name,
        height=entry.height,
        diameter=entry.diameter,
        location=Coordinate3D(
            x=entry.location.x,
            y=entry.location.y,
            z=resolved_z,
        ),
        capacity_ul=entry.capacity_ul,
        working_volume_ul=entry.working_volume_ul,
    )


def _build_nested_well_plate(
    plate_key: str,
    entry: NestedWellPlateYamlEntry,
    *,
    resolved_z: float,
) -> WellPlate:
    return WellPlate(
        name=entry.name or plate_key,
        model_name=entry.model_name,
        length=entry.length,
        width=entry.width,
        height=entry.height,
        well_depth=entry.well_depth,
        rows=entry.rows,
        columns=entry.columns,
        wells=_derive_wells_from_calibration(entry, resolved_z=resolved_z),
        capacity_ul=entry.capacity_ul,
        working_volume_ul=entry.working_volume_ul,
    )


def _build_deck_from_raw(raw: dict[str, Any], *, total_z_range: float | None = None) -> Deck:
    raw = _resolve_load_names(raw)
    schema = DeckYamlSchema.model_validate(raw)
    labware: Dict[str, Labware] = {}
    for name, entry in schema.labware.items():
        if isinstance(entry, WellPlateYamlEntry):
            labware[name] = _build_well_plate(entry, total_z_range=total_z_range)
        elif isinstance(entry, VialYamlEntry):
            labware[name] = _build_vial(entry, total_z_range=total_z_range)
        elif isinstance(entry, TipRackYamlEntry):
            labware[name] = _build_tip_rack(entry, total_z_range=total_z_range)
        elif isinstance(entry, TipDisposalYamlEntry):
            labware[name] = _build_holder(
                entry,
                total_z_range=total_z_range,
                model_class=TipDisposal,
            )
        elif isinstance(entry, WallYamlEntry):
            labware[name] = Wall(
                name=entry.name,
                corner_1=Coordinate3D(
                    x=entry.corner_1.x,
                    y=entry.corner_1.y,
                    z=entry.corner_1.z if entry.corner_1.z is not None else 0.0,
                ),
                corner_2=Coordinate3D(
                    x=entry.corner_2.x,
                    y=entry.corner_2.y,
                    z=entry.corner_2.z if entry.corner_2.z is not None else 0.0,
                ),
            )
        elif isinstance(entry, WellPlateHolderYamlEntry):
            labware[name] = _build_holder(
                entry,
                total_z_range=total_z_range,
                model_class=WellPlateHolder,
            )
        elif isinstance(entry, VialHolderYamlEntry):
            labware[name] = _build_holder(
                entry,
                total_z_range=total_z_range,
                model_class=VialHolder,
            )
        else:
            raise TypeError(f"Unsupported deck labware entry type: {type(entry).__name__}")
    return Deck(labware)


def load_deck_from_yaml(
    path: str | Path,
    total_z_range: float | None = None,
) -> Deck:
    """
    Load a deck YAML file and return a Deck containing all labware.
    """
    resolved_path = Path(path)
    with resolved_path.open() as handle:
        raw = yaml.safe_load(handle)
    if raw is None:
        raw = {}
    return _build_deck_from_raw(raw, total_z_range=total_z_range)


def load_deck_from_yaml_safe(
    path: str | Path,
    total_z_range: float | None = None,
) -> Deck:
    """
    Load deck YAML with user-friendly exception formatting.

    Raises:
        DeckLoaderError: concise, actionable message intended for CLI/UX output.
    """
    resolved_path = Path(path)
    try:
        return load_deck_from_yaml(resolved_path, total_z_range=total_z_range)
    except Exception as exc:
        raise DeckLoaderError(_format_loader_exception(resolved_path, exc)) from exc
