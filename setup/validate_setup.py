"""Validate a protocol setup by loading all configs and checking bounds.

Usage:
    python setup/validate_setup.py <gantry.yaml> <deck.yaml> <protocol.yaml>

Example:
    python setup/validate_setup.py \\
        configs/gantry/cub_xl_asmi.yaml \\
        configs/deck/asmi_deck.yaml \\
        configs/protocol/asmi_move_a1.yaml
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

from board.loader import load_board_from_gantry_config, load_board_from_yaml
from deck.deck import Deck
from deck.labware.vial import Vial
from deck.labware.well_plate import WellPlate
from deck.loader import load_deck_from_yaml
from gantry.loader import load_gantry_from_yaml
from gantry.origin import validate_deck_origin_minima
from gantry.gantry import Gantry
from protocol_engine.loader import load_protocol_from_yaml
from validation.bounds import (
    collect_protocol_motion_targets,
    validate_protocol_motion_bounds,
)
from validation.protocol_semantics import validate_protocol_semantics

SEPARATOR = "-" * 60


@dataclass
class ValidationResult:
    """Result of running protocol setup validation."""

    output: str
    passed: bool


def _labware_summary(deck: Deck) -> list[str]:
    """Return one-line summaries for each piece of labware."""
    lines = []
    for key in deck:
        labware = deck[key]
        if isinstance(labware, WellPlate):
            lines.append(f"    {key}: well_plate ({len(labware.wells)} wells)")
        elif isinstance(labware, Vial):
            loc = labware.location
            lines.append(
                f"    {key}: vial at ({loc.x}, {loc.y}, {loc.z})"
            )
        else:
            lines.append(f"    {key}: {type(labware).__name__}")
    return lines


def _instrument_summary(board) -> list[str]:
    """Return one-line summaries for each instrument."""
    lines = []
    for name, instr in board.instruments.items():
        lines.append(
            f"    {name}: offset=({instr.offset_x}, {instr.offset_y}), "
            f"depth={instr.depth}"
        )
    return lines


def run_validation(
    gantry_path: str,
    deck_path: str,
    protocol_or_board_path: str,
    protocol_path: str | None = None,
) -> ValidationResult:
    """Run full setup validation and return structured result."""
    board_path: str | None = None
    if protocol_path is None:
        protocol_path = protocol_or_board_path
    else:
        board_path = protocol_or_board_path

    lines: list[str] = []

    def out(text: str = "") -> None:
        lines.append(text)

    out(SEPARATOR)
    out("Protocol Setup Validation")
    out(SEPARATOR)
    out()

    # 1. Gantry
    out("[1/4] Loading gantry config...")
    try:
        gantry_config = load_gantry_from_yaml(gantry_path)
        validate_deck_origin_minima(gantry_config)
    except Exception as exc:
        out(f"  ERROR: {exc}")
        out()
        out(SEPARATOR)
        out("RESULT: ERROR — could not load gantry config")
        out(SEPARATOR)
        return ValidationResult(output="\n".join(lines), passed=False)

    vol = gantry_config.working_volume
    out(f"  OK: {gantry_path}")
    out(f"  Gantry type: {gantry_config.gantry_type.value}")
    out(f"  Working volume: X[{vol.x_min}, {vol.x_max}]  "
        f"Y[{vol.y_min}, {vol.y_max}]  Z[{vol.z_min}, {vol.z_max}]")
    out(f"  Homing strategy: {gantry_config.homing_strategy}")
    out()

    # 2. Deck
    out("[2/4] Loading deck config...")
    try:
        deck = load_deck_from_yaml(
            deck_path,
            total_z_height=gantry_config.total_z_height,
        )
    except Exception as exc:
        out(f"  ERROR: {exc}")
        out()
        out(SEPARATOR)
        out("RESULT: ERROR — could not load deck config")
        out(SEPARATOR)
        return ValidationResult(output="\n".join(lines), passed=False)

    out(f"  OK: {deck_path}")
    out(f"  Labware ({len(deck)}):")
    for summary_line in _labware_summary(deck):
        out(summary_line)
    out()

    # 3. Board / instruments
    out("[3/4] Loading instruments...")
    try:
        offline_gantry = Gantry(offline=True)
        if board_path is None:
            board = load_board_from_gantry_config(
                gantry_config, offline_gantry, mock_mode=True,
            )
            board_source = gantry_path
        else:
            board = load_board_from_yaml(board_path, offline_gantry, mock_mode=True)
            board_source = board_path
    except Exception as exc:
        out(f"  ERROR: {exc}")
        out()
        out(SEPARATOR)
        out("RESULT: ERROR — could not load instruments")
        out(SEPARATOR)
        return ValidationResult(output="\n".join(lines), passed=False)

    out(f"  OK: {board_source}")
    out(f"  Instruments ({len(board.instruments)}):")
    for summary_line in _instrument_summary(board):
        out(summary_line)
    out()

    # 4. Protocol
    out("[4/4] Loading protocol...")
    try:
        protocol = load_protocol_from_yaml(protocol_path)
    except Exception as exc:
        out(f"  ERROR: {exc}")
        out()
        out(SEPARATOR)
        out("RESULT: ERROR — could not load protocol")
        out(SEPARATOR)
        return ValidationResult(output="\n".join(lines), passed=False)

    out(f"  OK: {protocol_path}")
    out(f"  Steps: {len(protocol)}")
    for step in protocol.steps:
        out(f"    [{step.index}] {step.command_name}({', '.join(f'{k}={v!r}' for k, v in step.args.items())})")
    out()

    # 5. Protocol motion bounds validation
    out("Validating protocol motion bounds...")
    motion_targets = collect_protocol_motion_targets(gantry_config, protocol, deck)
    motion_violations = validate_protocol_motion_bounds(
        gantry_config, protocol, deck, board,
    )
    if motion_violations:
        out(f"  FAIL — {len(motion_violations)} violation(s):")
        for v in motion_violations:
            prefix = (
                f"{v.instrument_name} -> "
                if v.coordinate_type == "gantry" and v.instrument_name
                else ""
            )
            out(f"  - {prefix}{v.labware_key}.{v.position_id}: "
                f"{v.coordinate_type} ({v.x}, {v.y}, {v.z}) "
                f"violates {v.bound_name}={v.bound_value}")
    else:
        out(f"  OK ({len(motion_targets)} protocol target(s) checked)")
    out()

    # 6. Protocol semantic validation
    out("Validating protocol semantics...")
    semantic_violations = validate_protocol_semantics(
        protocol, board, deck, gantry_config,
    )
    if semantic_violations:
        out(f"  FAIL — {len(semantic_violations)} violation(s):")
        for v in semantic_violations:
            out(f"  - step {v.step_index} ({v.command_name}): {v.message}")
    else:
        out("  OK")
    out()

    # Final result
    out(SEPARATOR)
    if motion_violations or semantic_violations:
        total = len(motion_violations) + len(semantic_violations)
        out(f"RESULT: FAIL — {total} violation(s) found")
        out(SEPARATOR)
        return ValidationResult(output="\n".join(lines), passed=False)

    out("RESULT: PASS — protocol motion targets within gantry bounds")
    out("Protocol is ready to run.")
    out(SEPARATOR)
    return ValidationResult(output="\n".join(lines), passed=True)


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
        result = run_validation(gantry_path, deck_path, protocol_path)
    else:
        gantry_path, deck_path, board_path, protocol_path = sys.argv[1:5]
        result = run_validation(gantry_path, deck_path, board_path, protocol_path)
    print(result.output)
    if not result.passed:
        sys.exit(1)


if __name__ == "__main__":
    main()
