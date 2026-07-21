"""Validate a protocol setup by loading all configs and checking bounds.

Usage:
    python -m cubos.tools.validate_setup <gantry.yaml> <deck.yaml> <protocol.yaml> [initial_fluids.yaml]

The optional fourth argument is a fluid seed YAML (same ``fluids:`` shape as
``run_protocol --initial-fluids``); when given, protocol liquid handling is
also simulated offline (pipette-model volume bounds, vial dead-volume floors,
destination working-volume overflow).

Example:
    python -m cubos.tools.validate_setup \
        ../BU-Configs/configs/gantry/cub_xl_asmi.yaml \
        ../BU-Configs/configs/deck/asmi_deck.yaml \
        ../BU-Configs/configs/protocol/asmi/move_a1.yaml
"""

from __future__ import annotations

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

from cubos.protocol_engine.setup_validator import (  # noqa: E402
    SetupValidationResult,
    run_setup_validation,
)


def main() -> None:
    if len(sys.argv) not in (4, 5):
        print(
            "Usage: python -m cubos.tools.validate_setup "
            "<gantry.yaml> <deck.yaml> <protocol.yaml> [initial_fluids.yaml]"
        )
        print()
        print("Example:")
        print("  python -m cubos.tools.validate_setup \\")
        print("    ../BU-Configs/configs/gantry/cub_xl_asmi.yaml \\")
        print("    ../BU-Configs/configs/deck/asmi_deck.yaml \\")
        print("    ../BU-Configs/configs/protocol/asmi/move_a1.yaml")
        sys.exit(1)

    gantry_path, deck_path, protocol_path = sys.argv[1:4]
    initial_fluids_path = sys.argv[4] if len(sys.argv) == 5 else None
    result = run_setup_validation(
        gantry_path, deck_path, protocol_path, initial_fluids_path,
    )
    print(result.output)
    if not result.passed:
        sys.exit(1)


__all__ = [
    "SetupValidationResult",
    "run_setup_validation",
]


if __name__ == "__main__":
    main()
