"""Command registry: @protocol_command decorator and CommandRegistry singleton."""

from __future__ import annotations

import inspect
from typing import Any, Callable, Dict, Type, get_type_hints

from pydantic import BaseModel, ConfigDict, create_model


class RegisteredCommand:
    """A registered command: its name, handler callable, and Pydantic schema."""

    __slots__ = ("name", "handler", "schema")

    def __init__(self, name: str, handler: Callable, schema: Type[BaseModel]) -> None:
        self.name = name
        self.handler = handler
        self.schema = schema


class CommandRegistry:
    """Singleton registry mapping YAML command names to handlers + schemas."""

    _instance: CommandRegistry | None = None

    def __init__(self) -> None:
        self._commands: Dict[str, RegisteredCommand] = {}

    @classmethod
    def instance(cls) -> CommandRegistry:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton for test isolation."""
        cls._instance = None

    def register(self, name: str, handler: Callable, schema: Type[BaseModel]) -> None:
        if name in self._commands:
            raise ValueError(f"Protocol command '{name}' is already registered.")
        self._commands[name] = RegisteredCommand(
            name=name, handler=handler, schema=schema,
        )

    def get(self, name: str) -> RegisteredCommand:
        if name not in self._commands:
            available = ", ".join(sorted(self._commands.keys()))
            raise KeyError(
                f"Unknown protocol command '{name}'. "
                f"Available commands: {available}"
            )
        return self._commands[name]

    @property
    def command_names(self) -> list[str]:
        return sorted(self._commands.keys())


def _build_schema_from_signature(
    name: str, func: Callable,
) -> Type[BaseModel]:
    """Introspect a function's signature and build a strict Pydantic model.

    Skips ``self`` and ``context`` parameters (context is injected at runtime).
    All remaining parameters become required schema fields unless they have
    default values in the function signature.
    """
    sig = inspect.signature(func)
    globalns = dict(getattr(func, "__globals__", {}))
    if "ProtocolContext" not in globalns:
        from .runtime import ProtocolContext

        globalns["ProtocolContext"] = ProtocolContext
    type_hints = get_type_hints(func, globalns=globalns, localns=globalns)
    field_definitions: Dict[str, Any] = {}

    skip_params = {"self", "context"}

    for param_name, param in sig.parameters.items():
        if param_name in skip_params:
            continue

        annotation = type_hints.get(param_name)
        if annotation is None:
            annotation = (
                param.annotation
                if param.annotation != inspect.Parameter.empty
                else str
            )

        if param.default != inspect.Parameter.empty:
            field_definitions[param_name] = (annotation, param.default)
        else:
            field_definitions[param_name] = (annotation, ...)

    schema_class_name = f"{name.title().replace('_', '')}Schema"
    model = create_model(
        schema_class_name,
        __config__=ConfigDict(extra="forbid"),
        **field_definitions,
    )
    return model


def protocol_command(name: str | None = None) -> Callable:
    """Decorator that registers a function as a protocol YAML command.

    Usage::

        @protocol_command("move")
        def move(context: ProtocolContext, instrument: str, position: str) -> None:
            ...

    Or with the function name as the command name::

        @protocol_command()
        def move(context: ProtocolContext, instrument: str, position: str) -> None:
            ...
    """
    def decorator(func: Callable) -> Callable:
        cmd_name = name or func.__name__
        schema = _build_schema_from_signature(cmd_name, func)
        CommandRegistry.instance().register(cmd_name, func, schema)
        func._protocol_command_name = cmd_name  # type: ignore[attr-defined]
        func._protocol_schema = schema  # type: ignore[attr-defined]
        return func
    return decorator
