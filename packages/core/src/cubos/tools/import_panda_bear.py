"""PANDA-BEAR -> CubOS production configuration importer.

Reads a PANDA-BEAR SQLite snapshot read-only and deterministically emits
native CubOS deck / initial-fluids / gantry / protocol configs. PANDA table
names and SQL live only in ``cubos.tools.panda_bear_import.db_reader`` --
everything downstream of that module works with plain dataclasses/dicts.

Usage:
    python -m cubos.tools.import_panda_bear <db_path> \\
        [--resolutions <resolutions.yaml>] \\
        [--out-dir <dir>] \\
        --gantry-source <calibrated-gantry.yaml> \\
        [--tools-json <tools.json>] \\
        [--no-resolutions]

Example:
    python -m cubos.tools.import_panda_bear \\
        /path/to/panda_prod_db.db \\
        --gantry-source /path/to/calibrated-gantry.yaml --out-dir /tmp/panda_import_out

Outputs (relative to --out-dir, default packages/core/configs):
    deck/panda_imported_deck.yaml
    deck/panda_initial_fluids.yaml
    gantry/cub_xl_panda_imported.yaml
    protocol/panda/position_tour.yaml
    panda_import_report.json   -- machine-readable conflict report

Exit code is non-zero if any row-selection conflict remains unresolved by
the resolutions file -- in that case NOTHING is written. Positional/
geometric observations (out-of-envelope coordinates, well-grid pitch
residuals, vial content/volume rescale) are reported as warnings and never
block the import; see the resolutions file's own header for why.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from cubos.gantry.yaml_schema import GantryYamlSchema
from cubos.yaml_utils import load_yaml_file

from .panda_bear_import.build import ImportResult, build_import
from .panda_bear_import.conflicts import Conflict, sort_key as conflict_sort_key
from .panda_bear_import.constants import DEFAULT_TOOL_OFFSETS
from .panda_bear_import.conversion import Point, WorkingVolume
from .panda_bear_import.db_reader import PandaBearSnapshot, SourceChangedError, read_snapshot
from .panda_bear_import.resolutions import Resolutions, empty_resolutions, load_resolutions
from .panda_bear_import.tools_json import load_tool_offsets
from .panda_bear_import.yaml_io import write_yaml_with_header

_HERE = Path(__file__).resolve()
_CORE_ROOT = _HERE.parents[3]  # packages/core
DEFAULT_OUT_DIR = _CORE_ROOT / "configs"
DEFAULT_RESOLUTIONS = DEFAULT_OUT_DIR / "deck" / "panda_import_resolutions.yaml"

_DECK_HEADER = [
    "GENERATED FILE -- do not hand-edit. Regenerate with:",
    "  python -m cubos.tools.import_panda_bear <db_path> "
    "--gantry-source <calibrated-gantry.yaml>",
    "",
    "Imported from a PANDA-BEAR production SQLite snapshot (read-only; see",
    "panda_import_report.json next to this file for the source DB path/hash",
    "and the full conflict report).",
    "",
    "Coordinates use the calibrated CubOS deck frame. The importer adds the",
    "PANDA-BEAR tool offset and the calibrated home XYZ to each legacy point.",
    "Use a zero-offset camera to inspect these gantry-reference positions.",
    "",
    "Vial location.z / well-plate calibration.a1.z are the converted mouth",
    "(DB 'top' generated column), matching CubOS's vial/well-plate Z",
    "semantics (calibration anchor = labware-surface reference).",
    "",
    "Positions are NOT guaranteed physically exact -- labware will be moved",
    "and positions re-derived after the hardware gate; out-of-envelope",
    "coordinates are written as-is with a WARNING in the conflict report,",
    "never clamped or blocked.",
]

_FLUIDS_HEADER = [
    "GENERATED FILE -- do not hand-edit. See panda_imported_deck.yaml's header.",
    "",
    "Seeded from surviving PANDA-BEAR vials' recorded volume + contents.",
    "A few production rows have a contents JSON that doesn't sum to their",
    "own volume column; those are rescaled proportionally to match volume_ul",
    "and flagged as a `vial_contents_volume_mismatch` warning in the",
    "conflict report (cubos.data.fluid_state.load_initial_fluids requires",
    "composition to sum exactly to volume_ul).",
]

_GANTRY_HEADER = [
    "GENERATED FILE -- do not hand-edit. See panda_imported_deck.yaml's header.",
    "",
    "Keeps existing calibrated instruments and fills in a missing `pipette`",
    "entry derived from PANDA-BEAR's tools.json. CubOS instrument offsets are",
    "the NEGATION of the PANDA-BEAR tool offset for x/y; depth is the +z",
    "offset unchanged (instrument_mount.py: gantry_x = target_x - offset_x,",
    "gantry_z = target_z + depth -- algebraically identical to PANDA-BEAR's",
    "gantry = tool_target + tool_offset when offset_cubos = -offset_pandabear).",
]

_TOUR_HEADER = [
    "GENERATED FILE -- do not hand-edit. See panda_imported_deck.yaml's header.",
    "",
    "Hover-only positional tour: home, then visit every imported labware",
    "target at the gantry's safe_z (deck-target moves never descend), then",
    "home again. No aspirate/dispense/measure -- this is a bring-up sanity",
    "tour, not a working protocol.",
    "",
    "Uses `instrument: camera` (0 offset, 0 depth) for every step, including",
    "the electrode-frame e1 vial. The imported deck already stores GANTRY-",
    "frame coordinates (see panda_imported_deck.yaml's header), so a",
    "zero-offset instrument hovers the gantry reference directly over each",
    "stored point. Using `instrument: pipette` here would double-apply the",
    "pipette's mounting offset on top of the frame conversion already baked",
    "into the deck YAML.",
]


def _load_calibrated_gantry(path: Path) -> tuple[dict, WorkingVolume, Point]:
    raw = load_yaml_file(path)
    if not isinstance(raw, dict) or raw.get("origin_policy", "deck_origin") != "deck_origin":
        raise ValueError("PANDA import requires a calibrated deck-origin gantry YAML.")
    schema = GantryYamlSchema.model_validate(raw)
    volume = WorkingVolume(**schema.working_volume.model_dump())
    if (
        not all(math.isfinite(value) for value in schema.working_volume.model_dump().values())
        or not (volume.x_min <= 0.0 < volume.x_max and volume.y_min <= 0.0 < volume.y_max)
        or volume.z_min < 0.0
    ):
        raise ValueError("PANDA import requires finite deck-origin working-volume bounds.")
    settings = schema.grbl_settings
    block_height = schema.cnc.calibration_block_height_mm
    if block_height is None or not math.isfinite(block_height) or settings is None or settings.homing_pull_off is None:
        raise ValueError("PANDA import requires a gantry YAML saved after measuring the deck reference and homing pull-off.")
    if not math.isfinite(settings.homing_pull_off) or settings.homing_pull_off < 0.0:
        raise ValueError("The calibrated homing pull-off must be finite and nonnegative.")
    for axis in ("x", "y", "z"):
        travel = getattr(settings, f"max_travel_{axis}")
        span = getattr(volume, f"{axis}_max") - getattr(volume, f"{axis}_min")
        if travel is None or not math.isfinite(travel) or abs(travel - span - settings.homing_pull_off) > 0.25:
            raise ValueError(f"Calibrated {axis.upper()} limits must match the working span plus homing pull-off.")
    camera = raw.get("instruments", {}).get("camera", {})
    if camera.get("type") != "camera" or any(camera.get(key, 0.0) != 0.0 for key in ("offset_x", "offset_y", "depth")):
        raise ValueError("PANDA import requires the zero-offset reference camera used for the position tour.")
    return raw, volume, Point(volume.x_max, volume.y_max, volume.z_max)


def run_import(
    db_path: Path,
    *,
    resolutions_path: Path | None,
    gantry_source: Path,
    tools_json_path: Path | None = None,
) -> tuple[ImportResult, PandaBearSnapshot, Resolutions]:
    """Read the snapshot and build all four outputs; raises on hash mismatch."""
    gantry_raw, working_volume, deck_home = _load_calibrated_gantry(gantry_source)
    snapshot = read_snapshot(db_path)
    resolutions = load_resolutions(resolutions_path) if resolutions_path else empty_resolutions()

    tool_offsets = dict(DEFAULT_TOOL_OFFSETS)
    if tools_json_path is not None:
        tool_offsets.update(load_tool_offsets(tools_json_path))

    result = build_import(snapshot, resolutions, tool_offsets, working_volume, gantry_raw, deck_home=deck_home)
    return result, snapshot, resolutions


def _build_report(
    result: ImportResult,
    snapshot: PandaBearSnapshot,
    resolutions_path: Path | None,
    gantry_source: Path,
) -> dict:
    conflicts = sorted(result.conflicts, key=conflict_sort_key)
    return {
        "source_db": snapshot.db_path,
        "source_sha256": snapshot.sha256,
        "gantry_source": str(gantry_source),
        "deck_home_mm": {
            axis: result.gantry_full["working_volume"][f"{axis}_max"]
            for axis in ("x", "y", "z")
        },
        "resolutions_path": str(resolutions_path) if resolutions_path else None,
        "conflicts": [c.to_dict() for c in conflicts],
        "conflict_count": len(conflicts),
        "warning_count": sum(1 for c in conflicts if c.severity == "warning"),
        "unresolved_conflict_count": len(result.blocking),
        "status": "blocked" if result.blocking else "ok",
    }


def _print_conflict(conflict: Conflict, *, stream) -> None:
    print(f"  - [{conflict.category}] {conflict.message}", file=stream)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("db_path", type=Path, help="Path to the PANDA-BEAR SQLite snapshot (read-only).")
    parser.add_argument(
        "--resolutions", type=Path, default=DEFAULT_RESOLUTIONS,
        help="Resolutions YAML (default: the committed panda_import_resolutions.yaml).",
    )
    parser.add_argument(
        "--no-resolutions", action="store_true",
        help="Ignore --resolutions and run with no resolutions applied (conflict-detection dry run).",
    )
    parser.add_argument(
        "--out-dir", type=Path, default=DEFAULT_OUT_DIR,
        help="Output configs root (default: packages/core/configs).",
    )
    parser.add_argument(
        "--gantry-source", type=Path, required=True,
        help="Calibrated deck-origin gantry YAML from the PANDA that produced the snapshot.",
    )
    parser.add_argument(
        "--tools-json", type=Path, default=None,
        help="Optional tools.json to override the documented default tool offsets.",
    )
    args = parser.parse_args(argv)

    resolutions_path = None if args.no_resolutions else args.resolutions

    try:
        result, snapshot, _resolutions = run_import(
            args.db_path,
            resolutions_path=resolutions_path,
            gantry_source=args.gantry_source,
            tools_json_path=args.tools_json,
        )
    except (OSError, SourceChangedError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    report = _build_report(result, snapshot, resolutions_path, args.gantry_source)
    report_json = json.dumps(report, indent=2, sort_keys=True) + "\n"
    report_path = args.out_dir / "panda_import_report.json"

    if result.blocking:
        print(
            f"BLOCKED: {len(result.blocking)} unresolved conflict(s); no files written.",
            file=sys.stderr,
        )
        for conflict in result.blocking:
            _print_conflict(conflict, stream=sys.stderr)
        print(report_json)
        return 1

    deck_path = args.out_dir / "deck" / "panda_imported_deck.yaml"
    fluids_path = args.out_dir / "deck" / "panda_initial_fluids.yaml"
    gantry_full_path = args.out_dir / "gantry" / "cub_xl_panda_imported.yaml"
    tour_path = args.out_dir / "protocol" / "panda" / "position_tour.yaml"

    write_yaml_with_header(deck_path, _DECK_HEADER, result.deck)
    write_yaml_with_header(fluids_path, _FLUIDS_HEADER, result.fluids)
    write_yaml_with_header(gantry_full_path, _GANTRY_HEADER, result.gantry_full)
    write_yaml_with_header(tour_path, _TOUR_HEADER, result.tour)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_json, encoding="utf-8")

    print(f"Wrote {deck_path}")
    print(f"Wrote {fluids_path}")
    print(f"Wrote {gantry_full_path}")
    print(f"Wrote {tour_path}")
    print(f"Wrote {report_path}")
    warnings = [c for c in result.conflicts if c.severity == "warning"]
    print(f"{len(warnings)} warning(s), 0 blocking conflict(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
