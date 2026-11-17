"""Convert an Opentrons labware definition JSON (schema v2) to CubOS YAML.

Usage:
    python -m cubos.tools.import_opentrons_labware <definition.json> [-o out.yaml]

Opentrons definitions are Apache-2.0 licensed (CubOS is MIT); see
``cubos.deck.labware.definitions.opentrons_import``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cubos.deck.labware.definitions.opentrons_import import (
    OpentronsImportError,
    import_opentrons_labware,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("definition", type=Path)
    parser.add_argument("-o", "--output", type=Path)
    args = parser.parse_args(argv)
    try:
        imported = import_opentrons_labware(args.definition)
    except OpentronsImportError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    for warning in imported.warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    text = imported.to_yaml()
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
