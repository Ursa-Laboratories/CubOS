"""Reusable offline setup validation for gantry/deck/protocol triples."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

_log = logging.getLogger(__name__)

from cubos.deck.deck import Deck
from cubos.deck.labware.vial import Vial
from cubos.deck.labware.well_plate import WellPlate
from cubos.deck.loader import load_deck_from_yaml
from cubos.gantry.gantry import Gantry
from cubos.gantry.instrument_loader import load_instrumented_gantry_from_config
from cubos.gantry.loader import load_gantry_from_yaml
from cubos.gantry.origin import validate_working_volume_origin
from cubos.protocol_engine.loader import load_protocol_from_yaml
from cubos.validation.bounds import (
    collect_protocol_motion_targets,
    validate_protocol_motion_bounds,
)
from cubos.validation.protocol_semantics import validate_protocol_semantics

SEPARATOR = "-" * 60
ValidationStage = Literal[
    "gantry",
    "deck",
    "instruments",
    "protocol",
    "validation",
]


@dataclass(frozen=True)
class SetupValidationResult:
    """Structured result of offline protocol setup validation."""

    output: str
    passed: bool
    errors: tuple[str, ...] = ()
    stage: ValidationStage = "validation"

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


def _instrument_summary(instrumented_gantry) -> list[str]:
    """Return one-line summaries for each instrument."""
    lines = []
    for name, instr in instrumented_gantry.instruments.items():
        lines.append(
            f"    {name}: offset=({instr.offset_x}, {instr.offset_y}), "
            f"depth={instr.depth}"
        )
    return lines


def _error_result(
    lines: list[str],
    *,
    stage: ValidationStage,
    message: str,
    result_message: str,
) -> SetupValidationResult:
    lines.extend([
        f"  ERROR: {message}",
        "",
        SEPARATOR,
        result_message,
        SEPARATOR,
    ])
    return SetupValidationResult(
        output="\n".join(lines),
        passed=False,
        errors=(message,),
        stage=stage,
    )


def run_setup_validation(
    gantry_path: str | Path,
    deck_path: str | Path,
    protocol_path: str | Path,
) -> SetupValidationResult:
    """Run full offline setup validation and return a structured result."""
    lines: list[str] = []

    def out(text: str = "") -> None:
        lines.append(text)

    out(SEPARATOR)
    out("Protocol Setup Validation")
    out(SEPARATOR)
    out()

    out("[1/4] Loading gantry config...")
    try:
        gantry_config = load_gantry_from_yaml(gantry_path)
        validate_working_volume_origin(gantry_config)
    except Exception as exc:
        _log.error("Failed to load gantry config from %s", gantry_path, exc_info=True)
        return _error_result(
            lines,
            stage="gantry",
            message=f"{type(exc).__name__}: {exc}",
            result_message="RESULT: ERROR - could not load gantry config",
        )

    vol = gantry_config.working_volume
    out(f"  OK: {gantry_path}")
    out(f"  Gantry type: {gantry_config.gantry_type.value}")
    out(
        f"  Working volume: X[{vol.x_min}, {vol.x_max}]  "
        f"Y[{vol.y_min}, {vol.y_max}]  Z[{vol.z_min}, {vol.z_max}]"
    )
    out()

    out("[2/4] Loading deck config...")
    try:
        deck = load_deck_from_yaml(
            deck_path,
            factory_z_travel_mm=gantry_config.factory_z_travel_mm,
        )
    except Exception as exc:
        _log.error("Failed to load deck config from %s", deck_path, exc_info=True)
        return _error_result(
            lines,
            stage="deck",
            message=f"{type(exc).__name__}: {exc}",
            result_message="RESULT: ERROR - could not load deck config",
        )

    out(f"  OK: {deck_path}")
    out(f"  Labware ({len(deck)}):")
    for summary_line in _labware_summary(deck):
        out(summary_line)
    out()

    out("[3/4] Loading instruments...")
    try:
        offline_gantry = Gantry(offline=True)
        instrumented_gantry = load_instrumented_gantry_from_config(
            gantry_config,
            offline_gantry,
            mock_mode=True,
        )
    except Exception as exc:
        _log.error("Failed to load instruments", exc_info=True)
        return _error_result(
            lines,
            stage="instruments",
            message=f"{type(exc).__name__}: {exc}",
            result_message="RESULT: ERROR - could not load instruments",
        )

    out(f"  OK: {gantry_path} (offline/mock - hardware not contacted)")
    out(f"  Instruments ({len(instrumented_gantry.instruments)}):")
    for summary_line in _instrument_summary(instrumented_gantry):
        out(summary_line)
    out()

    out("[4/4] Loading protocol...")
    try:
        protocol = load_protocol_from_yaml(protocol_path)
    except Exception as exc:
        _log.error("Failed to load protocol from %s", protocol_path, exc_info=True)
        return _error_result(
            lines,
            stage="protocol",
            message=f"{type(exc).__name__}: {exc}",
            result_message="RESULT: ERROR - could not load protocol",
        )

    out(f"  OK: {protocol_path}")
    out(f"  Steps: {len(protocol)}")
    for step in protocol.steps:
        args = ", ".join(f"{key}={value!r}" for key, value in step.args.items())
        out(f"    [{step.index}] {step.command_name}({args})")
    out()

    out("Validating protocol motion bounds...")
    try:
        motion_targets = collect_protocol_motion_targets(gantry_config, protocol, deck)
        motion_violations = validate_protocol_motion_bounds(
            gantry_config,
            protocol,
            deck,
            instrumented_gantry,
        )
    except Exception as exc:
        _log.exception("Motion bounds validation raised unexpectedly")
        return _error_result(
            lines,
            stage="validation",
            message=f"{type(exc).__name__}: {exc}",
            result_message="RESULT: ERROR - validation engine failure",
        )
    errors: list[str] = []
    if motion_violations:
        out(f"  FAIL - {len(motion_violations)} violation(s):")
        for violation in motion_violations:
            prefix = (
                f"{violation.instrument_name} -> "
                if violation.coordinate_type == "gantry" and violation.instrument_name
                else ""
            )
            error = (
                f"{prefix}{violation.labware_key}.{violation.position_id}: "
                f"{violation.coordinate_type} ({violation.x}, {violation.y}, {violation.z}) "
                f"violates {violation.bound_name}={violation.bound_value}"
            )
            errors.append(error)
            out(f"  - {error}")
    else:
        out(f"  OK ({len(motion_targets)} protocol target(s) checked)")
    out()

    out("Validating protocol semantics...")
    try:
        semantic_violations = validate_protocol_semantics(
            protocol,
            instrumented_gantry,
            deck,
            gantry_config,
        )
    except Exception as exc:
        _log.exception("Semantic validation raised unexpectedly")
        return _error_result(
            lines,
            stage="validation",
            message=f"{type(exc).__name__}: {exc}",
            result_message="RESULT: ERROR - validation engine failure",
        )
    if semantic_violations:
        out(f"  FAIL - {len(semantic_violations)} violation(s):")
        for violation in semantic_violations:
            error = (
                f"step {violation.step_index} ({violation.command_name}): "
                f"{violation.message}"
            )
            errors.append(error)
            out(f"  - {error}")
    else:
        out("  OK")
    out()

    out(SEPARATOR)
    if errors:
        out(f"RESULT: FAIL - {len(errors)} violation(s) found")
        out(SEPARATOR)
        return SetupValidationResult(
            output="\n".join(lines),
            passed=False,
            errors=tuple(errors),
            stage="validation",
        )

    out("RESULT: PASS - protocol motion targets within gantry bounds")
    out("Protocol is ready to run.")
    out(SEPARATOR)
    return SetupValidationResult(
        output="\n".join(lines),
        passed=True,
        stage="validation",
    )
__all__ = [
    "SetupValidationResult",
    "run_setup_validation",
]
