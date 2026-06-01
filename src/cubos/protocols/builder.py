"""Helpers for compiling Python protocol definitions."""

from __future__ import annotations

from typing import Any

from protocol_engine.protocol import ProtocolStep
from protocol_engine.registry import CommandRegistry

# Side-effect import: registers built-in commands before registry lookup.
from protocol_engine import commands as _commands  # noqa: F401


def protocol_step(command_name: str, **args: Any) -> ProtocolStep:
    """Build one validated ProtocolStep from Python keyword arguments.

    This mirrors YAML compilation: the command must be registered and the
    keyword arguments must satisfy that command's Pydantic schema. The returned
    step has index 0 so callers can compose steps naturally and let
    compile_protocol_steps renumber them.
    """
    registry = CommandRegistry.instance()
    registered = registry.get(command_name)
    validated_args = registered.schema.model_validate(args)
    return ProtocolStep(
        index=0,
        command_name=command_name,
        handler=registered.handler,
        args=validated_args.model_dump(exclude_unset=True),
    )


def compile_protocol_steps(*steps: ProtocolStep) -> list[ProtocolStep]:
    """Return a fresh step list with sequential indexes."""
    return [
        ProtocolStep(
            index=index,
            command_name=step.command_name,
            handler=step.handler,
            args=dict(step.args),
        )
        for index, step in enumerate(steps)
    ]
