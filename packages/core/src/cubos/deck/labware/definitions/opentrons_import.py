"""Convert an Opentrons labware definition (JSON schema v2) to a CubOS definition.

Opentrons' labware definitions are Apache-2.0 licensed; CubOS itself is MIT
(see the repository LICENSE). CubOS does not vendor the Opentrons library: this
module only reads definition files the operator supplies and emits a CubOS
well-plate config. Keep the provenance string it records and the upstream
license notice when redistributing a converted definition.

Only regular-grid well plates and troughs convert. Anything that cannot be
represented faithfully raises :class:`OpentronsImportError` rather than being
approximated; approximations that remain are returned as warnings.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from cubos.deck.yaml_schema import WellPlateYamlEntry

_GRID_TOLERANCE_MM = 0.05
_DEFAULT_PITCH_MM = 9.0
_WELL_ID = re.compile(r"^([A-Z])([0-9]+)$")


class OpentronsImportError(ValueError):
    """The Opentrons definition cannot be converted."""


@dataclass(frozen=True)
class ImportedLabware:
    config: dict[str, Any]
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.config, sort_keys=False)


def _num(value: Any, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise OpentronsImportError(f"{what} must be a finite number, got {value!r}.")
    return float(value)


def _uniform(values: list[float], what: str, tolerance: float = _GRID_TOLERANCE_MM) -> float:
    if max(values) - min(values) > tolerance:
        raise OpentronsImportError(
            f"{what} is not uniform across wells ({min(values):g} to {max(values):g}); "
            "CubOS well plates take one value per plate."
        )
    return sum(values) / len(values)


def _spacing(steps: list[float], axis: str) -> float | None:
    if not steps:
        return None
    pitch = _uniform(steps, f"well {axis} spacing")
    if pitch <= 0:
        raise OpentronsImportError(f"well {axis} spacing must be positive.")
    return pitch


def convert_opentrons_labware(definition: Mapping[str, Any]) -> ImportedLabware:
    """Convert a parsed Opentrons v2 definition."""
    if definition.get("schemaVersion") != 2:
        raise OpentronsImportError(
            f"unsupported schemaVersion {definition.get('schemaVersion')!r}; only 2 is supported."
        )
    parameters = definition.get("parameters") or {}
    if parameters.get("isTiprack"):
        raise OpentronsImportError("tip racks are not converted; define a CubOS tip_rack instead.")
    ordering = definition.get("ordering")
    wells = definition.get("wells")
    dimensions = definition.get("dimensions") or {}
    if not ordering or not wells or not isinstance(ordering, list):
        raise OpentronsImportError("definition has no wells/ordering.")
    warnings: list[str] = []

    rows = len(ordering[0])
    if any(len(column) != rows for column in ordering):
        raise OpentronsImportError("columns have different lengths; irregular layouts are unsupported.")
    ids = [well for column in ordering for well in column]
    if len(set(ids)) != len(ids) or set(ids) != set(wells):
        raise OpentronsImportError("ordering and wells list different well ids.")
    for column_index, column in enumerate(ordering):
        for row_index, well_id in enumerate(column):
            match = _WELL_ID.match(well_id)
            if not match or match.group(1) != chr(ord("A") + row_index) or int(match.group(2)) != column_index + 1:
                raise OpentronsImportError(
                    f"well {well_id!r} is not at row {chr(ord('A') + row_index)}, "
                    f"column {column_index + 1}; non-lettered or reordered layouts are unsupported."
                )
    columns = len(ordering)

    def well(row: int, column: int) -> Mapping[str, Any]:
        return wells[ordering[column][row]]

    xs = [[_num(well(r, c)["x"], "well x") for c in range(columns)] for r in range(rows)]
    ys = [[_num(well(r, c)["y"], "well y") for c in range(columns)] for r in range(rows)]
    x_steps = [xs[r][c + 1] - xs[r][c] for r in range(rows) for c in range(columns - 1)]
    y_steps = [ys[r][c] - ys[r + 1][c] for c in range(columns) for r in range(rows - 1)]
    if any(abs(xs[r][c] - xs[0][c]) > _GRID_TOLERANCE_MM for r in range(rows) for c in range(columns)):
        raise OpentronsImportError("well x positions are not aligned by column.")
    if any(abs(ys[r][c] - ys[r][0]) > _GRID_TOLERANCE_MM for r in range(rows) for c in range(columns)):
        raise OpentronsImportError("well y positions are not aligned by row.")
    x_pitch = _spacing([abs(step) for step in x_steps], "x")
    y_pitch = _spacing([abs(step) for step in y_steps], "y")
    if any(step <= 0 for step in x_steps) or any(step <= 0 for step in y_steps):
        raise OpentronsImportError("wells must run +x across columns and -y down rows.")
    if x_pitch is None:
        x_pitch = _DEFAULT_PITCH_MM
        warnings.append(f"single column: x_offset set to the placeholder {x_pitch:g} mm.")
    if y_pitch is None:
        y_pitch = _DEFAULT_PITCH_MM
        warnings.append(f"single row: y_offset set to the placeholder {y_pitch:g} mm.")

    depth = _uniform([_num(w["depth"], "well depth") for w in wells.values()], "well depth")
    volumes = [_num(w["totalLiquidVolume"], "totalLiquidVolume") for w in wells.values()]
    capacity = _uniform(volumes, "totalLiquidVolume", tolerance=1e-6)
    shapes = {w.get("shape") for w in wells.values()}
    if len(shapes) != 1 or next(iter(shapes)) not in {"circular", "rectangular"}:
        raise OpentronsImportError(f"wells must share one circular or rectangular shape, got {sorted(map(str, shapes))}.")
    shape = next(iter(shapes))
    cross: dict[str, Any] = {"well_shape": shape}
    if shape == "circular":
        cross["well_diameter"] = round(_uniform([_num(w["diameter"], "diameter") for w in wells.values()], "well diameter"), 3)
    else:
        cross["well_x_dimension"] = round(_uniform([_num(w["xDimension"], "xDimension") for w in wells.values()], "well xDimension"), 3)
        cross["well_y_dimension"] = round(_uniform([_num(w["yDimension"], "yDimension") for w in wells.values()], "well yDimension"), 3)

    load_name = str(parameters.get("loadName") or "").strip()
    if not load_name:
        raise OpentronsImportError("parameters.loadName is required to name the definition.")
    a1_x, a1_y = round(xs[0][0], 3), round(ys[0][0], 3)
    x_offset = round(x_pitch, 3)
    attributes: dict[str, Any] = {
        "source": f"opentrons:{definition.get('namespace', 'unknown')}/{load_name}/v{definition.get('version', '?')}",
    }
    for group in definition.get("groups") or []:
        bottom = (group.get("metadata") or {}).get("wellBottomShape")
        if bottom:
            attributes["bottom"] = str(bottom)
            break
    config: dict[str, Any] = {
        "type": "well_plate",
        "name": load_name,
        "model_name": load_name,
        "rows": rows,
        "columns": columns,
        "length": round(_num(dimensions["xDimension"], "xDimension"), 3),
        "width": round(_num(dimensions["yDimension"], "yDimension"), 3),
        "height": round(_num(dimensions["zDimension"], "zDimension"), 3),
        "well_depth": round(depth, 3),
        **cross,
        "well_attributes": attributes,
        "calibration": {
            "a1": {"x": a1_x, "y": a1_y},
            "a2": {"x": round(a1_x + x_offset, 3), "y": a1_y},
        },
        "x_offset": x_offset,
        "y_offset": round(y_pitch, 3),
        "capacity_ul": round(capacity, 3),
        "working_volume_ul": round(capacity, 3),
    }
    warnings.append(
        "working_volume_ul was set equal to capacity_ul (totalLiquidVolume); lower it "
        "to the volume you are willing to fill."
    )
    warnings.append(
        "calibration holds labware-frame placeholders; set a1/a2 and z from the deck "
        "calibration before use."
    )
    tops = [_num(w["z"], "well z") + _num(w["depth"], "well depth") for w in wells.values()]
    if max(tops) - min(tops) > _GRID_TOLERANCE_MM:
        warnings.append("well rim heights differ; CubOS uses one rim Z per plate.")
    try:
        WellPlateYamlEntry.model_validate(config)
    except ValueError as exc:
        raise OpentronsImportError(f"converted definition is invalid: {exc}") from exc
    return ImportedLabware(config=config, warnings=tuple(warnings))


def import_opentrons_labware(path: str | Path) -> ImportedLabware:
    """Read an Opentrons v2 definition JSON file and convert it."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OpentronsImportError(f"cannot read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise OpentronsImportError("definition must be a JSON object.")
    return convert_opentrons_labware(data)


__all__ = [
    "ImportedLabware",
    "OpentronsImportError",
    "convert_opentrons_labware",
    "import_opentrons_labware",
]
