"""Compile protocol command calls into executable runtime objects."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

from pydantic import ValidationError

# Side-effect import: triggers all @protocol_command decorators so that
# the CommandRegistry is populated before Python-authored protocols compile.
from . import commands as _commands  # noqa: F401
from .protocol import Protocol, ProtocolSetup
from .registry import CommandRegistry
from .runtime import ProtocolStep
from .yaml_schema import ProtocolStepSchema, RepeatArgsSchema

MAX_EXPANDED_PROTOCOL_STEPS = 1000

_LEGACY_TOP_LEVEL_HINTS: dict[str, str] = {
    "safe_approach_height": (
        "`safe_approach_height` was renamed to `interwell_scan_height` "
        "(labware-relative offset above the well surface for between-wells "
        "XY travel)."
    ),
    "indentation_limit": (
        "`indentation_limit` was renamed to `indentation_limit_height` and "
        "its meaning changed: it is now a *signed* labware-relative offset "
        "(mm above the well surface; negative = below), not a sign-agnostic "
        "descent magnitude. Convert e.g. `indentation_limit: 5.0` to "
        "`indentation_limit_height: -5.0`."
    ),
    "z_limit": (
        "`z_limit` is no longer supported. Use `indentation_limit_height` "
        "(signed labware-relative offset, mm above the well surface)."
    ),
    "entry_travel_height": (
        "`entry_travel_height` is no longer supported. Inter-labware/entry "
        "travel uses the gantry's `safe_z` (absolute deck-frame Z)."
    ),
    "interwell_travel_height": (
        "`interwell_travel_height` was renamed to `interwell_scan_height`."
    ),
}


@dataclass
class CommandCall:
    """A protocol command name plus the explicit arguments supplied for it."""

    command: str
    args: dict[str, Any]


def _validate_position_xyz(name: str, coordinates: Any) -> list[float]:
    if not isinstance(coordinates, (list, tuple)) or len(coordinates) != 3:
        raise ValueError(
            f"position {name!r} must be exactly three finite XYZ floats, "
            f"got {coordinates!r}."
        )
    values: list[float] = []
    for index, coord in enumerate(coordinates):
        if (
            isinstance(coord, bool)
            or not isinstance(coord, (int, float))
            or not math.isfinite(float(coord))
        ):
            raise ValueError(
                f"position {name!r} coordinate {index} must be a finite "
                f"float, got {type(coord).__name__} {coord!r}."
            )
        values.append(float(coord))
    return values


def _validate_positions(positions: Mapping[str, Any] | None) -> dict[str, list[float]]:
    return {
        str(name): _validate_position_xyz(str(name), coordinates)
        for name, coordinates in (positions or {}).items()
    }


def _schema_error_message(index: int, command: str, error: Exception) -> str:
    detail = str(error)
    guidance = "Review the command arguments against the registered schema."
    location = ""

    if isinstance(error, ValidationError):
        first_error = error.errors()[0] if error.errors() else {}
        detail = first_error.get("msg", detail)
        error_type = first_error.get("type", "")
        location = ".".join(str(part) for part in first_error.get("loc", []))
        offending_field = (
            str(first_error["loc"][-1])
            if first_error.get("loc") else ""
        )
        if error_type == "missing" or "Field required" in detail:
            guidance = "Add the missing required argument shown in the error location."
        elif (
            ("extra_forbidden" in error_type or "Extra inputs are not permitted" in detail)
            and offending_field in _LEGACY_TOP_LEVEL_HINTS
        ):
            guidance = _LEGACY_TOP_LEVEL_HINTS[offending_field]
        elif "extra_forbidden" in error_type or "Extra inputs are not permitted" in detail:
            guidance = "Remove unknown arguments; only registered parameters are allowed."

    where = f" argument `{location}`" if location else ""
    return (
        f"Protocol compile error at step {index} ({command}){where}: {detail}\n"
        f"How to fix: {guidance}"
    )


def compile_protocol(
    calls: Iterable[CommandCall],
    *,
    positions: Mapping[str, Any] | None = None,
    source_path: str | Path | None = None,
    setup: ProtocolSetup | None = None,
    deck: Any | None = None,
) -> Protocol:
    """Compile validated command calls into an executable ``Protocol``.

    The compiler intentionally uses the same registry-derived Pydantic schemas
    as the YAML loader. Only explicitly supplied arguments are carried into
    ``ProtocolStep.args``; handler defaults stay on the handler signature.
    """
    calls = expand_repeat_calls(calls, deck=deck)
    registry = CommandRegistry.instance()
    steps: list[ProtocolStep] = []

    for index, call in enumerate(calls):
        registered = registry.get(call.command)
        try:
            validated_args = registered.schema.model_validate(call.args)
        except Exception as exc:
            raise ValueError(_schema_error_message(index, call.command, exc)) from exc
        steps.append(
            ProtocolStep(
                index=index,
                command_name=call.command,
                handler=registered.handler,
                args=deepcopy(validated_args.model_dump(exclude_unset=True)),
            )
        )

    protocol_source = Path(source_path) if source_path is not None else None
    validated_positions = _validate_positions(positions)
    return Protocol(
        steps=steps,
        source_path=protocol_source,
        positions=deepcopy(validated_positions),
        setup=setup,
    )


def _replace_target(value: Any, source: str, target: str) -> Any:
    if isinstance(value, str):
        return target if value == source else value
    if isinstance(value, dict):
        return {key: _replace_target(item, source, target) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_target(item, source, target) for item in value]
    if isinstance(value, tuple):
        return tuple(_replace_target(item, source, target) for item in value)
    return value


def expand_repeat_calls(
    calls: Iterable[CommandCall], *, deck: Any | None = None,
) -> list[CommandCall]:
    """Expand authored repeat calls into bounded, schema-validated commands."""
    registry = CommandRegistry.instance()
    calls = list(calls)
    has_repeat = any(call.command == "repeat" for call in calls)
    expanded: list[CommandCall] = []
    for call in calls:
        if call.command != "repeat":
            expanded.append(call)
        else:
            repeat = RepeatArgsSchema.model_validate(call.args)
            contribution = len(repeat.wells) * len(repeat.steps)
            if has_repeat and len(expanded) + contribution > MAX_EXPANDED_PROTOCOL_STEPS:
                raise ValueError(
                    f"Protocol expansion exceeds the maximum of "
                    f"{MAX_EXPANDED_PROTOCOL_STEPS} concrete steps."
                )
            if deck is not None:
                try:
                    labware = deck.resolve_labware(repeat.labware)
                except (KeyError, ValueError) as exc:
                    raise ValueError(f"repeat labware {repeat.labware!r} cannot be resolved: {exc}") from exc
                well_ids = getattr(labware, "wells", None)
                if well_ids is None:
                    raise ValueError(f"repeat labware {repeat.labware!r} does not contain wells.")
                unknown = [well for well in repeat.wells if well not in well_ids]
                if repeat.template_well not in well_ids:
                    unknown.insert(0, repeat.template_well)
                if unknown:
                    raise ValueError(
                        f"repeat contains unknown well(s) for {repeat.labware!r}: {unknown}."
                    )
            source = f"{repeat.labware}.{repeat.template_well}"
            for well in repeat.wells:
                target = f"{repeat.labware}.{well}"
                for raw_step in repeat.steps:
                    child = ProtocolStepSchema.model_validate(raw_step)
                    args = _replace_target(deepcopy(child.args), source, target)
                    if isinstance(args.get("label"), str) and args["label"].strip():
                        args["label"] = f"{args['label']}_{well}"
                    registered = registry.get(child.command)
                    validated = registered.schema.model_validate(args)
                    expanded.append(CommandCall(
                        command=child.command,
                        args=validated.model_dump(exclude_unset=True),
                    ))
        if has_repeat and len(expanded) > MAX_EXPANDED_PROTOCOL_STEPS:
            raise ValueError(
                f"Protocol expansion exceeds the maximum of "
                f"{MAX_EXPANDED_PROTOCOL_STEPS} concrete steps."
            )
    return expanded
