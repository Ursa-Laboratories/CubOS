"""Load protocol YAML into an executable Protocol."""

from __future__ import annotations

from pathlib import Path
from typing import List

import yaml
from pydantic import ValidationError

# Hints for legacy top-level scan/measure command fields. These fields are
# rejected at the registry-derived schema layer with Pydantic's generic
# "Extra inputs are not permitted"; intercepting on field name lets us
# substitute a rename- or semantic-shift hint that points at the new
# field name (and, for `indentation_limit`, the magnitude→signed-offset
# semantic flip).
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

# Side-effect import: triggers all @protocol_command decorators so that
# the CommandRegistry is populated before any YAML is validated.
from . import commands as _commands  # noqa: F401

from .errors import ProtocolLoaderError
from .protocol import Protocol, ProtocolStep
from .registry import CommandRegistry
from .yaml_schema import ProtocolYamlSchema


def _format_loader_exception(path: Path, error: Exception) -> str:
    """Return a concise, actionable error message with fix guidance.

    Mirrors ``src/deck/loader.py::_format_loader_exception``.
    """
    detail = str(error)

    if isinstance(error, ValidationError):
        first_error = error.errors()[0] if error.errors() else {}
        detail = first_error.get("msg", detail)
        error_type = first_error.get("type", "")
        location = ".".join(str(part) for part in first_error.get("loc", []))
        offending_field = (
            str(first_error["loc"][-1])
            if first_error.get("loc") else ""
        )

        if "Unknown protocol command" in detail:
            registry = CommandRegistry.instance()
            guidance = (
                "Use a registered command. "
                f"Available: {', '.join(registry.command_names)}."
            )
        elif error_type == "missing" or "Field required" in detail:
            guidance = "Add the missing required argument shown in the error location."
        elif (
            ("extra_forbidden" in error_type or "Extra inputs are not permitted" in detail)
            and offending_field in _LEGACY_TOP_LEVEL_HINTS
        ):
            # Legacy top-level fields land here as generic "extra inputs not
            # permitted" — surface the rename / semantic-shift hint instead so
            # users migrating from staging see what to change.
            guidance = _LEGACY_TOP_LEVEL_HINTS[offending_field]
        elif "extra_forbidden" in error_type or "Extra inputs are not permitted" in detail:
            guidance = "Remove unknown arguments; only registered parameters are allowed."
        elif "exactly one command" in detail:
            guidance = "Each list item under 'protocol:' must contain exactly one command."
        else:
            guidance = "Review the protocol YAML against the command schemas."

        prefix = f" at `{location}`" if location else ""
        return f"Protocol YAML error{prefix}: {detail}\nHow to fix: {guidance}"

    if isinstance(error, yaml.YAMLError):
        return (
            f"Protocol YAML parse error in `{path}`.\n"
            "How to fix: Check YAML indentation, colons, and list/dict structure."
        )

    return (
        f"Protocol loader error in `{path}`: {detail}\n"
        "How to fix: Verify the file path and protocol YAML contents."
    )


def _compile_steps(schema: ProtocolYamlSchema) -> List[ProtocolStep]:
    """Convert validated schema steps into executable ProtocolStep objects."""
    registry = CommandRegistry.instance()
    steps: List[ProtocolStep] = []
    for i, step_schema in enumerate(schema.protocol):
        registered = registry.get(step_schema.command)
        validated_args = registered.schema.model_validate(step_schema.args)
        steps.append(
            ProtocolStep(
                index=i,
                command_name=step_schema.command,
                handler=registered.handler,
                # Keep the compiled step aligned with the YAML surface by only
                # carrying arguments that were explicitly provided. This avoids
                # materializing handler defaults such as ``travel_z=None`` or
                # ``reason=""`` into ProtocolStep.args.
                args=validated_args.model_dump(exclude_unset=True),
            )
        )
    return steps


def load_protocol_from_yaml(path: str | Path) -> Protocol:
    """Load a protocol YAML file and return an executable Protocol."""
    path = Path(path)
    with path.open() as f:
        raw = yaml.safe_load(f)
    if raw is None:
        raw = {}
    schema = ProtocolYamlSchema.model_validate(raw)
    steps = _compile_steps(schema)
    positions = schema.positions or {}
    return Protocol(steps=steps, source_path=path, positions=positions)


def load_protocol_from_yaml_safe(path: str | Path) -> Protocol:
    """Load protocol YAML with user-friendly exception formatting.

    Raises:
        ProtocolLoaderError: concise, actionable message intended for CLI output.
    """
    resolved_path = Path(path)
    try:
        return load_protocol_from_yaml(resolved_path)
    except Exception as exc:
        raise ProtocolLoaderError(
            _format_loader_exception(resolved_path, exc)
        ) from exc
