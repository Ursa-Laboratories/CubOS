"""Compile protocol command calls into executable runtime objects."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

# Side-effect import: triggers all @protocol_command decorators so that
# the CommandRegistry is populated before Python-authored protocols compile.
from . import commands as _commands  # noqa: F401
from .protocol import Protocol, ProtocolSetup
from .registry import CommandRegistry
from .runtime import ProtocolStep


@dataclass
class CommandCall:
    """A protocol command name plus the explicit arguments supplied for it."""

    command: str
    args: dict[str, Any]


def compile_protocol(
    calls: Iterable[CommandCall],
    *,
    positions: Mapping[str, Any] | None = None,
    source_path: str | Path | None = None,
    setup: ProtocolSetup | None = None,
) -> Protocol:
    """Compile validated command calls into an executable ``Protocol``.

    The compiler intentionally uses the same registry-derived Pydantic schemas
    as the YAML loader. Only explicitly supplied arguments are carried into
    ``ProtocolStep.args``; handler defaults stay on the handler signature.
    """
    registry = CommandRegistry.instance()
    steps: list[ProtocolStep] = []

    for index, call in enumerate(calls):
        registered = registry.get(call.command)
        validated_args = registered.schema.model_validate(call.args)
        steps.append(
            ProtocolStep(
                index=index,
                command_name=call.command,
                handler=registered.handler,
                args=deepcopy(validated_args.model_dump(exclude_unset=True)),
            )
        )

    protocol_source = Path(source_path) if source_path is not None else None
    return Protocol(
        steps=steps,
        source_path=protocol_source,
        positions=deepcopy(dict(positions or {})),
        setup=setup,
    )
