"""Validate a protocol setup by loading all configs and checking bounds.

Usage:
    python -m cubos.tools.validate_setup <gantry.yaml> <deck.yaml> <protocol.yaml>

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
    if len(sys.argv) != 4:
        print("Usage: python -m cubos.tools.validate_setup <gantry.yaml> <deck.yaml> <protocol.yaml>")
        print()
        print("Example:")
        print("  python -m cubos.tools.validate_setup \\")
        print("    ../BU-Configs/configs/gantry/cub_xl_asmi.yaml \\")
        print("    ../BU-Configs/configs/deck/asmi_deck.yaml \\")
        print("    ../BU-Configs/configs/protocol/asmi/move_a1.yaml")
        sys.exit(1)

    gantry_path, deck_path, protocol_path = sys.argv[1:4]
    result = run_setup_validation(gantry_path, deck_path, protocol_path)
    print(result.output)
    if not result.passed:
        sys.exit(1)


__all__ = [
    "SetupValidationResult",
    "run_setup_validation",
]


if __name__ == "__main__":
    main()
