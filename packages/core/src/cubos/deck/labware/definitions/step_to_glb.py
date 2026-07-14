#!/usr/bin/env python3
"""Convert STEP or STL files to glTF (.glb) for web and local 3D viewing.

Usage:
    python step_to_glb.py <file.step>                      # single file, writes alongside
    python step_to_glb.py <file.stl>                       # STL works too
    python step_to_glb.py <file.step> -o out.glb           # single file, explicit output
    python step_to_glb.py <dir>                            # batch all .step/.stp/.stl in dir
    python step_to_glb.py <dir> -o <out_dir>               # batch to a different dir
    python step_to_glb.py <dir> --tolerance 0.05           # finer STEP tessellation

Requires:
    cadquery  (for STEP): pip install cadquery  or  conda install -c conda-forge cadquery
    trimesh   (for STL):  pip install trimesh
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

STEP_SUFFIXES = {".step", ".stp"}
STL_SUFFIXES = {".stl"}
SUPPORTED_SUFFIXES = STEP_SUFFIXES | STL_SUFFIXES


def _convert_step(step_path: Path, glb_path: Path, tolerance: float, angular_tolerance: float) -> None:
    import cadquery as cq

    shape = cq.importers.importStep(str(step_path))
    assembly = cq.Assembly(shape, name=step_path.stem)
    assembly.save(
        str(glb_path),
        exportType="GLTF",
        tolerance=tolerance,
        angularTolerance=angular_tolerance,
    )


def _convert_stl(stl_path: Path, glb_path: Path) -> None:
    import trimesh

    mesh = trimesh.load(str(stl_path), force="mesh")
    # trimesh infers format from the output suffix (.glb -> binary glTF).
    mesh.export(str(glb_path))


def convert(
    src_path: Path,
    glb_path: Path,
    tolerance: float,
    angular_tolerance: float,
) -> None:
    """Load a STEP or STL file and write it out as a binary glTF (.glb)."""
    glb_path.parent.mkdir(parents=True, exist_ok=True)
    suffix = src_path.suffix.lower()
    if suffix in STEP_SUFFIXES:
        _convert_step(src_path, glb_path, tolerance, angular_tolerance)
    elif suffix in STL_SUFFIXES:
        _convert_stl(src_path, glb_path)
    else:
        raise ValueError(f"Unsupported file type: {src_path}")


def resolve_io(input_path: Path, output: Path | None) -> list[tuple[Path, Path]]:
    """Return a list of (src, glb) path pairs to process."""
    if input_path.is_file():
        if input_path.suffix.lower() not in SUPPORTED_SUFFIXES:
            raise ValueError(f"{input_path} is not a STEP or STL file")
        if output is None:
            return [(input_path, input_path.with_suffix(".glb"))]
        if output.suffix.lower() == ".glb":
            return [(input_path, output)]
        # Treat as directory
        return [(input_path, output / input_path.with_suffix(".glb").name)]

    if not input_path.is_dir():
        raise FileNotFoundError(input_path)

    src_files = sorted(
        p for p in input_path.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES
    )
    if not src_files:
        raise ValueError(f"No STEP/STL files found in {input_path}")

    out_dir = output if output is not None else input_path
    return [(p, out_dir / p.with_suffix(".glb").name) for p in src_files]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert STEP/STL files to glTF (.glb).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("input", type=Path, help="STEP/STL file or directory of them")
    parser.add_argument(
        "-o", "--output", type=Path, default=None,
        help="Output .glb file or directory (default: alongside input)",
    )
    parser.add_argument(
        "--tolerance", type=float, default=0.1,
        help="Linear tessellation tolerance in mm (STEP only; smaller = finer mesh)",
    )
    parser.add_argument(
        "--angular-tolerance", type=float, default=0.1,
        help="Angular tessellation tolerance in radians (STEP only)",
    )
    args = parser.parse_args()

    try:
        jobs = resolve_io(args.input, args.output)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    for step_path, glb_path in jobs:
        print(f"{step_path}  ->  {glb_path}")
        convert(step_path, glb_path, args.tolerance, args.angular_tolerance)

    print(f"Done. Converted {len(jobs)} file(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
