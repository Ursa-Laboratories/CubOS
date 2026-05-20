"""Structured protocol setup validation.

This module owns the reusable CubOS validation API used by CLI tools and
dependent apps such as Zoo. It mirrors the offline validation sequence used
before hardware execution without opening serial ports or moving hardware.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from board.loader import load_board_from_gantry_config, load_board_from_yaml
from deck.deck import Deck
from deck.labware.vial import Vial
from deck.labware.well_plate import WellPlate
from deck.loader import load_deck_from_yaml
from gantry.gantry import Gantry
from gantry.loader import load_gantry_from_yaml
from gantry.origin import validate_deck_origin_minima
from protocol_engine.loader import load_protocol_from_yaml
from validation.bounds import (
    collect_protocol_motion_targets,
    validate_protocol_motion_bounds,
)
from validation.protocol_semantics import validate_protocol_semantics

SEPARATOR = "-" * 60


@dataclass(frozen=True)
class SetupValidationResult:
    """Result of running offline protocol setup validation."""

    output: str
    passed: bool
    errors: tuple[str, ...] = ()
    stage: str | None = None


# Backwards-compatible name for older script imports.
ValidationResult = SetupValidationResult


def _labware_summary(deck: Deck) -> list[str]:
    """Return one-line summaries for each piece of labware."""
    lines = []
    for key in deck:
        labware = deck[key]
        if isinstance(labware, WellPlate):
            lines.append(f"    {key}: well_plate ({len(labware.wells)} wells)")
        elif isinstance(labware, Vial):
            loc = labware.location
            lines.append(f"    {key}: vial at ({loc.x}, {loc.y}, {loc.z})")
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


def _finish(
    lines: list[str],
    *,
    passed: bool,
    errors: list[str] | tuple[str, ...] = (),
    stage: str | None = None,
) -> SetupValidationResult:
    return SetupValidationResult(
        output="\n".join(lines),
        passed=passed,
        errors=tuple(errors),
        stage=stage,
    )


def run_setup_validation(
    gantry_path: str | Path,
    deck_path: str | Path,
    protocol_or_board_path: str | Path,
    protocol_path: str | Path | None = None,
) -> SetupValidationResult:
    """Run full offline setup validation and return a structured result."""
    board_path: str | Path | None = None
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
        message = f"ERROR: {exc}"
        out(f"  {message}")
        out()
        out(SEPARATOR)
        out("RESULT: ERROR - could not load gantry config")
        out(SEPARATOR)
        return _finish(lines, passed=False, errors=[message], stage="gantry")

    vol = gantry_config.working_volume
    out(f"  OK: {gantry_path}")
    out(f"  Gantry type: {gantry_config.gantry_type.value}")
    out(
        f"  Working volume: X[{vol.x_min}, {vol.x_max}]  "
        f"Y[{vol.y_min}, {vol.y_max}]  Z[{vol.z_min}, {vol.z_max}]"
    )
    out(f"  Homing strategy: {gantry_config.homing_strategy}")
    out()

    # 2. Deck
    out("[2/4] Loading deck config...")
    try:
        deck = load_deck_from_yaml(
            deck_path,
            total_z_range=gantry_config.total_z_range,
        )
    except Exception as exc:
        message = f"ERROR: {exc}"
        out(f"  {message}")
        out()
        out(SEPARATOR)
        out("RESULT: ERROR - could not load deck config")
        out(SEPARATOR)
        return _finish(lines, passed=False, errors=[message], stage="deck")

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
                gantry_config,
                offline_gantry,
                mock_mode=True,
            )
            board_source = gantry_path
        else:
            board = load_board_from_yaml(
                board_path,
                offline_gantry,
                mock_mode=True,
            )
            board_source = board_path
    except Exception as exc:
        message = f"ERROR: {exc}"
        out(f"  {message}")
        out()
        out(SEPARATOR)
        out("RESULT: ERROR - could not load instruments")
        out(SEPARATOR)
        return _finish(lines, passed=False, errors=[message], stage="instruments")

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
        message = f"ERROR: {exc}"
        out(f"  {message}")
        out()
        out(SEPARATOR)
        out("RESULT: ERROR - could not load protocol")
        out(SEPARATOR)
        return _finish(lines, passed=False, errors=[message], stage="protocol")

    out(f"  OK: {protocol_path}")
    out(f"  Steps: {len(protocol)}")
    for step in protocol.steps:
        args = ", ".join(f"{k}={v!r}" for k, v in step.args.items())
        out(f"    [{step.index}] {step.command_name}({args})")
    out()

    # 5. Protocol motion bounds validation
    errors: list[str] = []
    out("Validating protocol motion bounds...")
    motion_targets = collect_protocol_motion_targets(gantry_config, protocol, deck)
    motion_violations = validate_protocol_motion_bounds(
        gantry_config,
        protocol,
        deck,
        board,
    )
    if motion_violations:
        out(f"  FAIL - {len(motion_violations)} violation(s):")
        for v in motion_violations:
            prefix = (
                f"{v.instrument_name} -> "
                if v.coordinate_type == "gantry" and v.instrument_name
                else ""
            )
            message = (
                f"{prefix}{v.labware_key}.{v.position_id}: "
                f"{v.coordinate_type} ({v.x}, {v.y}, {v.z}) "
                f"violates {v.bound_name}={v.bound_value}"
            )
            errors.append(message)
            out(f"  - {message}")
    else:
        out(f"  OK ({len(motion_targets)} protocol target(s) checked)")
    out()

    # 6. Protocol semantic validation
    out("Validating protocol semantics...")
    semantic_violations = validate_protocol_semantics(
        protocol,
        board,
        deck,
        gantry_config,
    )
    if semantic_violations:
        out(f"  FAIL - {len(semantic_violations)} violation(s):")
        for v in semantic_violations:
            message = f"step {v.step_index} ({v.command_name}): {v.message}"
            errors.append(message)
            out(f"  - {message}")
    else:
        out("  OK")
    out()

    # Final result
    out(SEPARATOR)
    if motion_violations or semantic_violations:
        total = len(motion_violations) + len(semantic_violations)
        out(f"RESULT: FAIL - {total} violation(s) found")
        out(SEPARATOR)
        return _finish(lines, passed=False, errors=errors, stage="validation")

    out("RESULT: PASS - protocol motion targets within gantry bounds")
    out("Protocol is ready to run.")
    out(SEPARATOR)
    return _finish(lines, passed=True)


def run_validation(
    gantry_path: str | Path,
    deck_path: str | Path,
    protocol_or_board_path: str | Path,
    protocol_path: str | Path | None = None,
) -> SetupValidationResult:
    """Backward-compatible alias for older callers."""
    return run_setup_validation(
        gantry_path,
        deck_path,
        protocol_or_board_path,
        protocol_path,
    )
