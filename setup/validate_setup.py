"""Validate a protocol setup by loading all configs and checking bounds.

Usage:
    python setup/validate_setup.py <gantry.yaml> <deck.yaml> <protocol.yaml>

Example:
    python setup/validate_setup.py \
        configs/gantry/cub_xl_asmi.yaml \
        configs/deck/asmi_deck.yaml \
        configs/protocol/asmi_move_a1.yaml
"""

from __future__ import annotations

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

from protocol_engine.setup_validation import (  # noqa: E402
    SetupValidationResult,
    ValidationResult,
    run_setup_validation,
    run_validation,
)


def main() -> None:
    if len(sys.argv) not in (4, 5):
        print("Usage: python setup/validate_setup.py <gantry.yaml> <deck.yaml> <protocol.yaml>")
        print()
        print("Example:")
        print("  python setup/validate_setup.py \\")
        print("    configs/gantry/cub_xl_asmi.yaml \\")
        print("    configs/deck/asmi_deck.yaml \\")
        print("    configs/protocol/asmi_move_a1.yaml")
        sys.exit(1)

    if len(sys.argv) == 4:
        gantry_path, deck_path, protocol_path = sys.argv[1:4]
        result = run_setup_validation(gantry_path, deck_path, protocol_path)
    else:
        gantry_path, deck_path, board_path, protocol_path = sys.argv[1:5]
        result = run_setup_validation(gantry_path, deck_path, board_path, protocol_path)
    print(result.output)
    if not result.passed:
        sys.exit(1)


__all__ = [
    "SetupValidationResult",
    "ValidationResult",
    "run_setup_validation",
    "run_validation",
]


if __name__ == "__main__":
    main()
